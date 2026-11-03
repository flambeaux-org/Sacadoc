"""Liste / Ajouter / Modifier / Supprimer / Importer tests for the multi-object
individu fiches: vaccinations, informations, assurances, contacts (+ traitements).

Extra factories are defined locally so that no shared test file is touched.
"""

import datetime
import json

import pytest
from core.models import (
    Assurance,
    Assureur,
    CategorieInformation,
    ContactUrgence,
    Information,
    PortailRenseignement,
    Rattachement,
    TypeMaladie,
    TypeVaccin,
    Vaccin,
)
from django.db.models import Model
from django.db.models.fields.files import FieldFile
from django.urls import reverse
from tests.unit.factories import ActiviteFactory, InscriptionFactory

TODAY = datetime.date.today()


def post_data(form, **overrides):
    data = {}
    for name in form.fields:
        val = form.initial.get(name, form.fields[name].initial)
        if val is None or isinstance(val, FieldFile) or hasattr(val, "read"):
            continue
        if isinstance(val, Model):
            val = val.pk
        elif hasattr(val, "isoformat"):
            val = val.isoformat()
        data[name] = val
    data.update(overrides)
    return data


# --- local factories -------------------------------------------------------


def make_vaccin(individu, nom="BCG"):
    tv = TypeVaccin.objects.get_or_create(nom=nom)[0]
    return Vaccin.objects.create(
        individu=individu, type_vaccin=tv, date=datetime.date(2020, 6, 1)
    )


def make_information(individu, intitule="Asthme"):
    cat = CategorieInformation.objects.get_or_create(nom="Santé")[0]
    return Information.objects.create(
        individu=individu, categorie=cat, intitule=intitule
    )


def make_assurance(individu, famille, num="CONTRAT-1"):
    assureur = Assureur.objects.get_or_create(nom="AXA")[0]
    return Assurance.objects.create(
        individu=individu,
        famille=famille,
        assureur=assureur,
        num_contrat=num,
        date_debut=datetime.date(2024, 1, 1),
    )


def make_contact(individu, famille, nom="Mamie"):
    return ContactUrgence.objects.create(
        individu=individu, famille=famille, nom=nom, prenom="Jeanne", lien="Grand-mère"
    )


class Spec:
    def __init__(
        self, key, model, pk_attr, kw, onglet, make, valid, change, check, url_base
    ):
        self.key, self.model, self.pk_attr, self.kw, self.onglet = (
            key,
            model,
            pk_attr,
            kw,
            onglet,
        )
        self.make, self.valid, self.change, self.check, self.url_base = (
            make,
            valid,
            change,
            check,
            url_base,
        )

    def url(self, action, ratt, obj=None):
        name = "portail_individu_{}{}".format(
            self.url_base,
            "" if action == "liste" else "_" + action,
        )
        kwargs = {"idrattachement": ratt.pk}
        if obj is not None:
            kwargs[self.kw] = getattr(obj, self.pk_attr)
        return reverse(name, kwargs=kwargs)


def _vac_valid(famille, individu):
    tv = TypeVaccin.objects.create(nom="ROR")
    return {"type_vaccin": tv.pk, "date": "2021-03-04", "individu": individu.pk}


def _info_valid(famille, individu):
    cat = CategorieInformation.objects.create(nom="Autre")
    return {
        "categorie": cat.pk,
        "intitule": "Lunettes",
        "description": "port permanent",
        "individu": individu.pk,
    }


def _ass_valid(famille, individu):
    assureur = Assureur.objects.create(nom="MAIF")
    return {
        "assureur": assureur.pk,
        "num_contrat": "NEW-42",
        "date_debut": "2024-02-01",
        "date_fin": "",
        "famille": famille.pk,
        "individu": individu.pk,
    }


def _con_valid(famille, individu):
    return {
        "nom": "Tonton",
        "prenom": "Paul",
        "lien": "Oncle",
        "autorisation_sortie": "on",
        "autorisation_appel": "on",
        "famille": famille.pk,
        "individu": individu.pk,
    }


SPECS = {
    "vaccinations": Spec(
        "vaccinations",
        Vaccin,
        "idvaccin",
        "idvaccin",
        "individu_vaccinations",
        make_vaccin,
        _vac_valid,
        {"date": "2022-02-02"},
        lambda o: o.date == datetime.date(2022, 2, 2),
        "vaccinations",
    ),
    "informations": Spec(
        "informations",
        Information,
        "idinformation",
        "idinformation",
        "individu_informations",
        make_information,
        _info_valid,
        {"intitule": "Modifié"},
        lambda o: o.intitule == "Modifié",
        "informations",
    ),
    "assurances": Spec(
        "assurances",
        Assurance,
        "idassurance",
        "idassurance",
        "individu_assurances",
        None,
        _ass_valid,
        {"num_contrat": "MOD-9"},
        lambda o: o.num_contrat == "MOD-9",
        "assurances",
    ),
    "contacts": Spec(
        "contacts",
        ContactUrgence,
        "idcontact",
        "idcontact",
        "individu_contacts",
        None,
        _con_valid,
        {"nom": "Modifié"},
        lambda o: o.nom == "Modifié",
        "contacts",
    ),
}
KEYS = list(SPECS)
LISTE_CTX = {
    "vaccinations": "liste_vaccinations",
    "informations": "liste_informations",
    "assurances": "liste_assurances",
    "contacts": "liste_contacts",
}


def make_obj(spec, individu, famille):
    if spec.key == "assurances":
        return make_assurance(individu, famille)
    if spec.key == "contacts":
        return make_contact(individu, famille)
    return spec.make(individu)


# ---------------------------------------------------------------------------
# Liste
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("key", KEYS)
class TestListe:
    def test_liste_shows_only_own_individu_objects(
        self, logged_client, famille_user, key
    ):
        spec = SPECS[key]
        _u, famille, ratt = famille_user
        mine = make_obj(spec, ratt[1].individu, famille)
        theirs = make_obj(spec, ratt[0].individu, famille)
        response = logged_client.get(spec.url("liste", ratt[1]))
        assert response.status_code == 200
        objets = response.context[LISTE_CTX[key]]
        pks = [getattr(o, spec.pk_attr) for o in objets]
        assert getattr(mine, spec.pk_attr) in pks
        assert getattr(theirs, spec.pk_attr) not in pks
        assert response.context["onglet_actif"] == spec.onglet

    def test_liste_empty(self, logged_client, famille_user, key):
        spec = SPECS[key]
        _u, _f, ratt = famille_user
        assert logged_client.get(spec.url("liste", ratt[1])).status_code == 200

    def test_liste_pending_intro_when_manual_validation(
        self, logged_client, famille_user, set_parametre_portail, key
    ):
        """Page.get_context_data: validation_auto=False replaces the intro by a warning (only when the Page context is
        not overridden by Liste.get_context_data)."""
        spec = SPECS[key]
        set_parametre_portail(f"validation_auto:{spec.onglet}", False)
        _u, _f, ratt = famille_user
        response = logged_client.get(spec.url("ajouter", ratt[1]))
        assert response.status_code == 200
        assert "validées par l'administrateur" in response.context["box_introduction"]

    def test_liste_cross_family_denied(self, logged_client, other_famille, key):
        spec = SPECS[key]
        _u, _f, ratt_b = other_famille
        assert logged_client.get(spec.url("liste", ratt_b[1])).status_code == 403
        assert logged_client.get(spec.url("ajouter", ratt_b[1])).status_code == 403


# ---------------------------------------------------------------------------
# Ajouter
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("key", KEYS)
class TestAjouter:
    def test_get_renders_form(self, logged_client, famille_user, key):
        spec = SPECS[key]
        _u, _f, ratt = famille_user
        response = logged_client.get(spec.url("ajouter", ratt[1]))
        assert response.status_code == 200
        assert "form" in response.context

    def test_valid_post_creates_and_records(self, logged_client, famille_user, key):
        spec = SPECS[key]
        _u, famille, ratt = famille_user
        data = spec.valid(famille, ratt[1].individu)
        response = logged_client.post(spec.url("ajouter", ratt[1]), data)
        assert response.status_code == 302
        assert response.url == spec.url("liste", ratt[1])
        assert spec.model.objects.count() == 1
        renseignement = PortailRenseignement.objects.get()
        assert renseignement.categorie == spec.onglet
        assert renseignement.famille == famille
        assert renseignement.individu == ratt[1].individu
        assert renseignement.idobjet == getattr(spec.model.objects.get(), spec.pk_attr)
        assert renseignement.code.startswith("Nouve")
        assert json.loads(renseignement.nouvelle_valeur)
        messages = [str(m) for m in response.wsgi_request._messages]
        assert any("Votre ajout a été enregistré" in m for m in messages)

    def test_valid_post_recertifies_fiche(self, logged_client, famille_user, key):
        spec = SPECS[key]
        _u, famille, ratt = famille_user
        Rattachement.objects.filter(pk=ratt[1].pk).update(
            certification_date=datetime.datetime(2024, 1, 1)
        )
        logged_client.post(
            spec.url("ajouter", ratt[1]), spec.valid(famille, ratt[1].individu)
        )
        assert Rattachement.objects.get(pk=ratt[1].pk).certification_date is None

    def test_save_and_new_redirects_to_add_form(self, logged_client, famille_user, key):
        spec = SPECS[key]
        _u, famille, ratt = famille_user
        data = dict(spec.valid(famille, ratt[1].individu), SaveAndNew="1")
        response = logged_client.post(spec.url("ajouter", ratt[1]), data)
        assert response.status_code == 302
        assert response.url == spec.url("ajouter", ratt[1])

    def test_invalid_post_rerenders_with_errors(self, logged_client, famille_user, key):
        spec = SPECS[key]
        _u, famille, ratt = famille_user
        response = logged_client.post(
            spec.url("ajouter", ratt[1]),
            {"individu": ratt[1].individu_id, "famille": famille.pk},
        )
        assert response.status_code == 200
        assert response.context["form"].errors
        assert spec.model.objects.count() == 0
        assert PortailRenseignement.objects.count() == 0

    def test_cross_family_post_denied(
        self, logged_client, famille_user, other_famille, key
    ):
        spec = SPECS[key]
        _u, famille_b, ratt_b = other_famille
        data = spec.valid(famille_b, ratt_b[1].individu)
        assert (
            logged_client.post(spec.url("ajouter", ratt_b[1]), data).status_code == 403
        )
        assert spec.model.objects.count() == 0


# ---------------------------------------------------------------------------
# Modifier
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("key", KEYS)
class TestModifier:
    def test_get_renders_prefilled(self, logged_client, famille_user, key):
        spec = SPECS[key]
        _u, famille, ratt = famille_user
        obj = make_obj(spec, ratt[1].individu, famille)
        response = logged_client.get(spec.url("modifier", ratt[1], obj))
        assert response.status_code == 200
        assert response.context["form"].instance == obj

    def test_valid_post_updates(self, logged_client, famille_user, key):
        spec = SPECS[key]
        _u, famille, ratt = famille_user
        obj = make_obj(spec, ratt[1].individu, famille)
        url = spec.url("modifier", ratt[1], obj)
        data = post_data(logged_client.get(url).context["form"], **spec.change)
        response = logged_client.post(url, data)
        assert response.status_code == 302
        assert response.url == spec.url("liste", ratt[1])
        assert spec.check(spec.model.objects.get(pk=obj.pk))

    def test_save_and_new_redirects_to_add(self, logged_client, famille_user, key):
        spec = SPECS[key]
        _u, famille, ratt = famille_user
        obj = make_obj(spec, ratt[1].individu, famille)
        url = spec.url("modifier", ratt[1], obj)
        data = post_data(
            logged_client.get(url).context["form"], SaveAndNew="1", **spec.change
        )
        assert logged_client.post(url, data).url == spec.url("ajouter", ratt[1])

    def test_invalid_post_rerenders(self, logged_client, famille_user, key):
        spec = SPECS[key]
        _u, famille, ratt = famille_user
        obj = make_obj(spec, ratt[1].individu, famille)
        url = spec.url("modifier", ratt[1], obj)
        bad = {
            "vaccinations": {"date": ""},
            "informations": {"intitule": ""},
            "assurances": {"num_contrat": ""},
            "contacts": {"nom": ""},
        }[key]
        data = post_data(logged_client.get(url).context["form"], **bad)
        response = logged_client.post(url, data)
        assert response.status_code == 200
        assert response.context["form"].errors

    def test_cross_family_rattachement_denied(
        self, logged_client, famille_user, other_famille, key
    ):
        spec = SPECS[key]
        _ub, famille_b, ratt_b = other_famille
        obj = make_obj(spec, ratt_b[1].individu, famille_b)
        assert (
            logged_client.get(spec.url("modifier", ratt_b[1], obj)).status_code == 403
        )

    @pytest.mark.xfail(
        reason="BUG: Page.get_object() fetches the object by pk only (no ownership check against the "
        "rattachement), so family A can open family B's object through A's own idrattachement (IDOR).",
        strict=True,
    )
    def test_cross_family_object_get_denied(
        self, logged_client, famille_user, other_famille, key
    ):
        spec = SPECS[key]
        _u, _f, ratt = famille_user
        _ub, famille_b, ratt_b = other_famille
        obj = make_obj(spec, ratt_b[1].individu, famille_b)
        assert logged_client.get(spec.url("modifier", ratt[1], obj)).status_code in (
            403,
            404,
        )

    @pytest.mark.xfail(
        reason="BUG: Page.get_object() has no ownership check, so family A can overwrite family B's object "
        "by posting to its own idrattachement with B's object id (IDOR).",
        strict=True,
    )
    def test_cross_family_object_post_denied(
        self, logged_client, famille_user, other_famille, key
    ):
        spec = SPECS[key]
        _u, _f, ratt = famille_user
        _ub, famille_b, ratt_b = other_famille
        obj = make_obj(spec, ratt_b[1].individu, famille_b)
        # Use the own-family modifier form to build a payload that rewrites B's object.
        own = make_obj(spec, ratt[1].individu, _f)
        data = post_data(
            logged_client.get(spec.url("modifier", ratt[1], own)).context["form"],
            **spec.change,
        )
        response = logged_client.post(spec.url("modifier", ratt[1], obj), data)
        assert response.status_code in (403, 404)
        assert not spec.check(spec.model.objects.get(pk=obj.pk))


# ---------------------------------------------------------------------------
# Supprimer
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("key", KEYS)
class TestSupprimer:
    def test_get_confirmation_page(self, logged_client, famille_user, key):
        spec = SPECS[key]
        _u, famille, ratt = famille_user
        obj = make_obj(spec, ratt[1].individu, famille)
        response = logged_client.get(spec.url("supprimer", ratt[1], obj))
        assert response.status_code == 200

    def test_post_deletes_and_records(self, logged_client, famille_user, key):
        spec = SPECS[key]
        _u, famille, ratt = famille_user
        obj = make_obj(spec, ratt[1].individu, famille)
        Rattachement.objects.filter(pk=ratt[1].pk).update(
            certification_date=datetime.datetime(2024, 1, 1)
        )
        response = logged_client.post(spec.url("supprimer", ratt[1], obj))
        assert response.status_code == 302
        assert not spec.model.objects.filter(pk=obj.pk).exists()
        renseignement = PortailRenseignement.objects.get()
        assert renseignement.categorie == spec.onglet
        assert "supprim" in renseignement.code
        assert renseignement.ancienne_valeur
        assert Rattachement.objects.get(pk=ratt[1].pk).certification_date is None

    def test_cross_family_rattachement_denied(
        self, logged_client, famille_user, other_famille, key
    ):
        spec = SPECS[key]
        _ub, famille_b, ratt_b = other_famille
        obj = make_obj(spec, ratt_b[1].individu, famille_b)
        assert (
            logged_client.post(spec.url("supprimer", ratt_b[1], obj)).status_code == 403
        )
        assert spec.model.objects.filter(pk=obj.pk).exists()

    @pytest.mark.xfail(
        reason="BUG: Page.get_object() has no ownership check, so family A can delete family B's object "
        "through its own idrattachement (IDOR).",
        strict=True,
    )
    def test_cross_family_object_delete_denied(
        self, logged_client, famille_user, other_famille, key
    ):
        spec = SPECS[key]
        _u, _f, ratt = famille_user
        _ub, famille_b, ratt_b = other_famille
        obj = make_obj(spec, ratt_b[1].individu, famille_b)
        response = logged_client.post(spec.url("supprimer", ratt[1], obj))
        assert response.status_code in (403, 404)
        assert spec.model.objects.filter(pk=obj.pk).exists()


# ---------------------------------------------------------------------------
# Posting a foreign individu through the hidden fields
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("key", ["vaccinations", "informations", "contacts"])
@pytest.mark.xfail(
    reason="BUG: the ModelForm exposes 'individu' (and 'famille' for contacts) as hidden inputs that are "
    "trusted on POST, so a family can attach a record to another family's individu (mass assignment).",
    strict=True,
)
def test_ajouter_cannot_target_foreign_individu(
    logged_client, famille_user, other_famille, key
):
    spec = SPECS[key]
    _u, famille, ratt = famille_user
    _ub, _famille_b, ratt_b = other_famille
    data = spec.valid(famille, ratt_b[1].individu)
    logged_client.post(spec.url("ajouter", ratt[1]), data)
    assert not spec.model.objects.filter(individu=ratt_b[1].individu).exists()


# ---------------------------------------------------------------------------
# Liste specifics
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestVaccinationsListe:
    def test_obligatory_vaccines_context(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        TypeMaladie.objects.create(nom="Tétanos", vaccin_obligatoire=True)
        response = logged_client.get(
            reverse(
                "portail_individu_vaccinations", kwargs={"idrattachement": ratt[1].pk}
            )
        )
        assert response.context["vaccins_obligatoires"] == [
            {"label": "Tétanos", "valide": False}
        ]

    def test_obligatory_vaccine_valid_after_vaccination(
        self, logged_client, famille_user
    ):
        _u, _f, ratt = famille_user
        maladie = TypeMaladie.objects.create(nom="Tétanos", vaccin_obligatoire=True)
        vaccin = make_vaccin(ratt[1].individu, nom="DTP")
        vaccin.type_vaccin.types_maladies.add(maladie)
        response = logged_client.get(
            reverse(
                "portail_individu_vaccinations", kwargs={"idrattachement": ratt[1].pk}
            )
        )
        assert response.context["vaccins_obligatoires"] == [
            {"label": "Tétanos", "valide": True}
        ]


@pytest.mark.django_db
class TestAssurancesListe:
    def _inscription(self, famille, individu, **kwargs):
        activite = ActiviteFactory(assurance_obligatoire=True)
        return InscriptionFactory(
            famille=famille, individu=individu, activite=activite, **kwargs
        )

    def test_assurance_manquante_true(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        self._inscription(famille, ratt[1].individu)
        response = logged_client.get(
            reverse(
                "portail_individu_assurances", kwargs={"idrattachement": ratt[1].pk}
            )
        )
        assert response.context["assurance_manquante"] is True

    def test_assurance_manquante_false_when_insured(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        self._inscription(famille, ratt[1].individu)
        make_assurance(ratt[1].individu, famille)
        response = logged_client.get(
            reverse(
                "portail_individu_assurances", kwargs={"idrattachement": ratt[1].pk}
            )
        )
        assert response.context["assurance_manquante"] is False

    def test_assurance_manquante_false_when_inscription_ended(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        self._inscription(famille, ratt[1].individu, date_fin=datetime.date(2021, 1, 1))
        response = logged_client.get(
            reverse(
                "portail_individu_assurances", kwargs={"idrattachement": ratt[1].pk}
            )
        )
        assert response.context["assurance_manquante"] is False

    def test_modifier_context_has_assureur_creation_form(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        obj = make_assurance(ratt[1].individu, famille)
        response = logged_client.get(SPECS["assurances"].url("modifier", ratt[1], obj))
        assert "form_ajout" in response.context

    def test_ajouter_invalid_dates_reports_error(self, logged_client, famille_user):
        """date_fin before date_debut: the form error is shown, nothing is saved."""
        _u, famille, ratt = famille_user
        spec = SPECS["assurances"]
        data = spec.valid(famille, ratt[1].individu)
        data.update(date_debut="2024-05-01", date_fin="2024-01-01")
        response = logged_client.post(spec.url("ajouter", ratt[1]), data)
        assert response.status_code == 200
        assert "date_fin" in response.context["form"].errors
        assert Assurance.objects.count() == 0

    def test_ajouter_missing_assureur_reports_error(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        spec = SPECS["assurances"]
        data = spec.valid(famille, ratt[1].individu)
        data.pop("assureur")
        data["date_fin"] = ""
        response = logged_client.post(spec.url("ajouter", ratt[1]), data)
        assert response.status_code == 200
        assert "assureur" in response.context["form"].errors


# ---------------------------------------------------------------------------
# Importers
# ---------------------------------------------------------------------------

IMPORT_SPECS = {
    "assurances": (
        "portail_individu_assurances_importer",
        "assurances",
        Assurance,
        "idassurance",
        "Assurance importée",
    ),
    "contacts": (
        "portail_individu_contacts_importer",
        "contacts",
        ContactUrgence,
        "idcontact",
        "Contact importé",
    ),
}


def _imp_url(key, ratt):
    return reverse(IMPORT_SPECS[key][0], kwargs={"idrattachement": ratt.pk})


@pytest.mark.django_db
@pytest.mark.parametrize("key", list(IMPORT_SPECS))
class TestImporter:
    def test_get_without_source_shows_cancel_only(
        self, logged_client, famille_user, key
    ):
        _u, _f, ratt = famille_user
        response = logged_client.get(_imp_url(key, ratt[1]))
        assert response.status_code == 200
        assert 'name="enregistrer"' not in response.content.decode()
        assert response.context["box_titre"]

    def test_get_with_source_shows_import_button(
        self, logged_client, famille_user, key
    ):
        _u, famille, ratt = famille_user
        make_obj(SPECS[key], ratt[0].individu, famille)
        response = logged_client.get(_imp_url(key, ratt[1]))
        assert response.status_code == 200
        assert 'name="enregistrer"' in response.content.decode()

    def test_post_imports_selected(self, logged_client, famille_user, key):
        _u, famille, ratt = famille_user
        _url, field, model, pk_attr, code = IMPORT_SPECS[key]
        src = make_obj(SPECS[key], ratt[0].individu, famille)
        response = logged_client.post(
            _imp_url(key, ratt[1]), {field: str(getattr(src, pk_attr))}
        )
        assert response.status_code == 302
        assert response.url == reverse(
            SPECS[key].onglet.replace("individu_", "portail_individu_"),
            kwargs={"idrattachement": ratt[1].pk},
        )
        assert model.objects.filter(individu=ratt[1].individu).count() == 1
        assert (
            model.objects.filter(individu=ratt[0].individu).count() == 1
        )  # source untouched
        assert PortailRenseignement.objects.get().code == code
        messages = [str(m) for m in response.wsgi_request._messages]
        assert any("importé" in m for m in messages)

    def test_post_imports_several(self, logged_client, famille_user, key):
        _u, famille, ratt = famille_user
        _url, field, model, pk_attr, _code = IMPORT_SPECS[key]
        a = make_obj(SPECS[key], ratt[0].individu, famille)
        b = make_obj(SPECS[key], ratt[0].individu, famille)
        payload = f"{getattr(a, pk_attr)};{getattr(b, pk_attr)}"
        logged_client.post(_imp_url(key, ratt[1]), {field: payload})
        assert model.objects.filter(individu=ratt[1].individu).count() == 2
        assert PortailRenseignement.objects.count() == 2

    def test_post_empty_selection_imports_nothing(
        self, logged_client, famille_user, key
    ):
        _u, _famille, ratt = famille_user
        _url, field, model, *_ = IMPORT_SPECS[key]
        response = logged_client.post(_imp_url(key, ratt[1]), {field: ""})
        assert response.status_code == 302
        assert model.objects.count() == 0
        messages = [str(m) for m in response.wsgi_request._messages]
        assert any(m.startswith("Aucun") for m in messages)

    def test_cross_family_rattachement_denied(
        self, logged_client, famille_user, other_famille, key
    ):
        _ub, _fb, ratt_b = other_famille
        assert logged_client.get(_imp_url(key, ratt_b[1])).status_code == 403
        assert (
            logged_client.post(
                _imp_url(key, ratt_b[1]), {IMPORT_SPECS[key][1]: ""}
            ).status_code
            == 403
        )

    @pytest.mark.xfail(
        reason="BUG: the importers copy any object by pk without checking it belongs to the user's family "
        "(also keeps the source famille), so a family can import another family's data (IDOR).",
        strict=True,
    )
    def test_cannot_import_other_family_object(
        self, logged_client, famille_user, other_famille, key
    ):
        _u, _f, ratt = famille_user
        _ub, famille_b, ratt_b = other_famille
        _url, field, model, pk_attr, _code = IMPORT_SPECS[key]
        src = make_obj(SPECS[key], ratt_b[1].individu, famille_b)
        logged_client.post(_imp_url(key, ratt[1]), {field: str(getattr(src, pk_attr))})
        assert not model.objects.filter(individu=ratt[1].individu).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("key", list(IMPORT_SPECS))
@pytest.mark.xfail(
    reason="BUG: importer does int() on the posted ids with no validation: a non-numeric value raises "
    "ValueError (500) instead of a form error.",
    strict=True,
)
def test_importer_non_numeric_selection_is_handled(logged_client, famille_user, key):
    _u, _f, ratt = famille_user
    response = logged_client.post(_imp_url(key, ratt[1]), {IMPORT_SPECS[key][1]: "abc"})
    assert response.status_code < 500


# ---------------------------------------------------------------------------
# Traitements (read only list)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTraitements:
    def _traitement(self, individu, auteur, date, activite, titre="Soin"):
        from core.models import Traitement

        return Traitement.objects.create(
            individu=individu,
            auteur=auteur,
            date=date,
            titre=titre,
            Description="d",
            typemaladie="m",
            activite=activite,
        )

    def test_lists_recent_visible_only(self, logged_client, famille_user):
        user, _f, ratt = famille_user
        act = ActiviteFactory()
        recent = self._traitement(
            ratt[1].individu, user, TODAY - datetime.timedelta(days=10), act, "Récent"
        )
        self._traitement(
            ratt[1].individu, user, TODAY - datetime.timedelta(days=400), act, "Ancien"
        )
        other_ind = self._traitement(
            ratt[0].individu, user, TODAY, act, "Autre individu"
        )
        hidden_act = ActiviteFactory(
            date_traitements_visibles=datetime.datetime.now()
            + datetime.timedelta(days=30)
        )
        self._traitement(
            ratt[1].individu, user, TODAY, hidden_act, "Pas encore visible"
        )
        visible_act = ActiviteFactory(
            date_traitements_visibles=datetime.datetime.now()
            - datetime.timedelta(days=1)
        )
        visible = self._traitement(
            ratt[1].individu, user, TODAY, visible_act, "Visible"
        )

        response = logged_client.get(
            reverse(
                "portail_individu_traitement", kwargs={"idrattachement": ratt[1].pk}
            )
        )
        assert response.status_code == 200
        titres = {t.titre for t in response.context["traitements"]}
        assert titres == {recent.titre, visible.titre}
        assert other_ind.titre not in titres
