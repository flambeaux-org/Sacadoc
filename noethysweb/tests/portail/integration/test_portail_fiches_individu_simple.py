"""Consulter / Modifier tests for the "single object" individu fiches.

Covers identite, coords, regimes_alimentaires, maladies, allergies, dispmed and
medecin: GET render (consultation + edition), valid POST (validation_auto vs
pending approval), no-change POST, invalid POST, cross-family denial, the
PortailRenseignement bookkeeping and the extra context branches.
"""

import datetime
import json

import pytest
from core.models import (
    Individu,
    Medecin,
    PortailChamp,
    PortailRenseignement,
    Rattachement,
    RegimeAlimentaire,
    TypeAllergie,
    TypeDispmed,
    TypeMaladie,
)
from django.db.models import Model
from django.db.models.fields.files import FieldFile
from django.urls import reverse

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


def post_data(form, **overrides):
    """Build a POST payload mirroring the form's initial values."""
    data = {}
    for name in form.fields:
        val = form.initial.get(name, form.fields[name].initial)
        if val is None or isinstance(val, FieldFile) or hasattr(val, "read"):
            continue
        if isinstance(val, Model):
            val = val.pk
        elif isinstance(val, (list, tuple)):
            val = [v.pk if isinstance(v, Model) else v for v in val]
        elif hasattr(val, "isoformat"):
            val = val.isoformat()
        data[name] = val
    data.update(overrides)
    return data


# (consulter url name, modifier url name, onglet code, a dict of valid changes)
SIMPLE_FICHES = {
    "identite": (
        "portail_individu_identite",
        "portail_individu_identite_modifier",
        "individu_identite",
    ),
    "coords": (
        "portail_individu_coords",
        "portail_individu_coords_modifier",
        "individu_coords",
    ),
    "regimes": (
        "portail_individu_regimes_alimentaires",
        "portail_individu_regimes_alimentaires_modifier",
        "individu_regimes_alimentaires",
    ),
    "maladies": (
        "portail_individu_maladies",
        "portail_individu_maladies_modifier",
        "individu_maladies",
    ),
    "allergies": (
        "portail_individu_allergies",
        "portail_individu_allergies_modifier",
        "individu_allergies",
    ),
    "dispmed": (
        "portail_individu_dispmed",
        "portail_individu_dispmed_modifier",
        "individu_dispmed",
    ),
    "medecin": (
        "portail_individu_medecin",
        "portail_individu_medecin_modifier",
        "individu_medecin",
    ),
}


def _changes(key):
    """Return (overrides for POST, field name, expected attribute check) for a fiche."""
    if key == "identite":
        return {"nom": "NouveauNom"}, "nom", lambda i: i.nom == "NouveauNom"
    if key == "coords":
        return (
            {"rue_resid": "12 rue des Lilas"},
            "rue_resid",
            lambda i: i.rue_resid == "12 rue des Lilas",
        )
    if key == "regimes":
        regime = RegimeAlimentaire.objects.create(nom="Halal")
        return (
            {"regimes_alimentaires": [regime.pk]},
            "regimes_alimentaires",
            lambda i: i.regimes_alimentaires.filter(pk=regime.pk).exists(),
        )
    if key == "maladies":
        m = TypeMaladie.objects.create(nom="Rougeole")
        return (
            {"maladies": [m.pk]},
            "maladies",
            lambda i: i.maladies.filter(pk=m.pk).exists(),
        )
    if key == "allergies":
        return (
            {"allergies_detail": "Pas d'arachides"},
            "allergies_detail",
            lambda i: i.allergies_detail == "Pas d'arachides",
        )
    if key == "dispmed":
        return (
            {"dispmed_detail": "Appareil auditif"},
            "dispmed_detail",
            lambda i: i.dispmed_detail == "Appareil auditif",
        )
    if key == "medecin":
        med = Medecin.objects.create(nom="Martin")
        return {"medecin": med.pk}, "medecin", lambda i: i.medecin_id == med.pk
    raise AssertionError(key)


FICHE_KEYS = list(SIMPLE_FICHES)


def _url(name, ratt):
    return reverse(name, kwargs={"idrattachement": ratt.pk})


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("key", FICHE_KEYS)
class TestConsulterModifierGet:
    def test_consulter_is_read_only(self, logged_client, famille_user, key):
        """CONSULTATION mode: every field disabled, page title and onglet context set."""
        consulter, _modifier, onglet = SIMPLE_FICHES[key]
        _u, _f, ratt = famille_user
        response = logged_client.get(_url(consulter, ratt[1]))
        assert response.status_code == 200
        assert response.context["onglet_actif"] == onglet
        assert response.context["page_titre"] == "Fiche individuelle"
        assert response.context["rattachement"] == ratt[1]
        form = response.context["form"]
        assert form.mode == "CONSULTATION"
        assert all(field.disabled for field in form.fields.values())

    def test_modifier_is_editable(self, logged_client, famille_user, key):
        """EDITION mode: fields are editable and an introduction box is shown."""
        _c, modifier, _o = SIMPLE_FICHES[key]
        _u, _f, ratt = famille_user
        response = logged_client.get(_url(modifier, ratt[1]))
        assert response.status_code == 200
        form = response.context["form"]
        assert form.mode == "EDITION"
        assert any(not field.disabled for field in form.fields.values())
        assert response.context["box_introduction"]

    def test_modifier_shows_pending_warning_when_validation_manual(
        self, logged_client, famille_user, set_parametre_portail, key
    ):
        """validation_auto=False -> the introduction warns about admin approval."""
        _c, modifier, onglet = SIMPLE_FICHES[key]
        set_parametre_portail(f"validation_auto:{onglet}", False)
        _u, _f, ratt = famille_user
        response = logged_client.get(_url(modifier, ratt[1]))
        assert response.status_code == 200
        assert "validées par l'administrateur" in response.context["box_introduction"]

    def test_cross_family_get_denied(self, logged_client, other_famille, key):
        consulter, modifier, _o = SIMPLE_FICHES[key]
        _u, _f, ratt_b = other_famille
        assert logged_client.get(_url(consulter, ratt_b[1])).status_code == 403
        assert logged_client.get(_url(modifier, ratt_b[1])).status_code == 403

    def test_cross_family_post_denied_and_nothing_saved(
        self, logged_client, famille_user, other_famille, key
    ):
        _c, modifier, _o = SIMPLE_FICHES[key]
        _u, _f, ratt_b = other_famille
        overrides, _field, check = _changes(key)
        response = logged_client.post(_url(modifier, ratt_b[1]), overrides)
        assert response.status_code == 403
        assert PortailRenseignement.objects.count() == 0
        assert not check(Individu.objects.get(pk=ratt_b[1].individu_id))

    @pytest.mark.xfail(
        reason="BUG: portail/views/fiche.py:44 uses Rattachement.objects.get() unguarded, so an unknown "
        "idrattachement raises DoesNotExist (500) instead of a 404/403.",
        strict=True,
    )
    def test_unknown_rattachement_is_404_or_denied(
        self, logged_client, famille_user, key
    ):
        """A rattachement id that does not exist must not render a page."""
        consulter, _m, _o = SIMPLE_FICHES[key]
        response = logged_client.get(
            reverse(consulter, kwargs={"idrattachement": 999999})
        )
        assert response.status_code in (403, 404)


# ---------------------------------------------------------------------------
# POST
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("key", FICHE_KEYS)
class TestModifierPost:
    def _post(self, client, famille_user, key):
        _c, modifier, onglet = SIMPLE_FICHES[key]
        _u, famille, ratt = famille_user
        url = _url(modifier, ratt[1])
        overrides, field, check = _changes(key)
        data = post_data(client.get(url).context["form"], **overrides)
        return client.post(url, data), url, ratt, famille, field, check, onglet

    def test_validation_auto_saves_and_records_renseignement(
        self, logged_client, famille_user, key
    ):
        """validation_auto=True: value saved immediately, renseignement stored with idobjet + validation_auto."""
        response, _url_, ratt, famille, field, check, onglet = self._post(
            logged_client, famille_user, key
        )
        assert response.status_code == 302
        assert check(Individu.objects.get(pk=ratt[1].individu_id))
        renseignement = PortailRenseignement.objects.get(code=field)
        assert renseignement.categorie == onglet
        assert renseignement.famille == famille
        assert renseignement.individu == ratt[1].individu
        assert renseignement.validation_auto is True
        assert renseignement.idobjet == ratt[1].individu_id
        assert renseignement.etat == "ATTENTE"
        assert json.loads(renseignement.nouvelle_valeur) is not None

    def test_validation_auto_message_and_recertification(
        self, logged_client, famille_user, key
    ):
        """A saved change flashes a success message and resets the fiche certification."""
        _c, _m, _o = SIMPLE_FICHES[key]
        _u, _f, ratt = famille_user
        Rattachement.objects.filter(pk=ratt[1].pk).update(
            certification_date=datetime.datetime(2024, 1, 1)
        )
        response, *_rest = self._post(logged_client, famille_user, key)
        messages = [str(m) for m in response.wsgi_request._messages]
        assert any(
            "Votre modification a été enregistrée" in m and "transmise" not in m
            for m in messages
        )
        assert Rattachement.objects.get(pk=ratt[1].pk).certification_date is None

    def test_manual_validation_does_not_save_but_queues(
        self, logged_client, famille_user, set_parametre_portail, key
    ):
        """validation_auto=False: the Individu is untouched; the change waits in PortailRenseignement."""
        _c, _m, onglet = SIMPLE_FICHES[key]
        set_parametre_portail(f"validation_auto:{onglet}", False)
        response, _u, ratt, _f, field, check, _o = self._post(
            logged_client, famille_user, key
        )
        assert response.status_code == 302
        assert not check(Individu.objects.get(pk=ratt[1].individu_id))
        renseignement = PortailRenseignement.objects.get(code=field)
        assert renseignement.validation_auto is False
        assert renseignement.idobjet is None
        assert renseignement.etat == "ATTENTE"
        messages = [str(m) for m in response.wsgi_request._messages]
        assert any("transmise à l'administrateur" in m for m in messages)

    def test_pending_value_is_displayed_on_next_get(
        self, logged_client, famille_user, set_parametre_portail, key
    ):
        """After a queued change, the form shows the pending value with an orange warning."""
        _c, _modifier, onglet = SIMPLE_FICHES[key]
        set_parametre_portail(f"validation_auto:{onglet}", False)
        _response, url, _ratt, _f, field, _check, _o = self._post(
            logged_client, famille_user, key
        )
        form = logged_client.get(url).context["form"]
        assert "en attente de validation" in str(form.fields[field].help_text)

    def test_no_change_post_flashes_info(self, logged_client, famille_user, key):
        """Posting the initial values unchanged stores nothing."""
        _c, modifier, _o = SIMPLE_FICHES[key]
        _u, _f, ratt = famille_user
        url = _url(modifier, ratt[1])
        data = post_data(logged_client.get(url).context["form"])
        response = logged_client.post(url, data)
        assert response.status_code == 302
        assert PortailRenseignement.objects.count() == 0
        messages = [str(m) for m in response.wsgi_request._messages]
        assert any("Aucune modification" in m for m in messages)

    def test_success_redirects_to_consultation(self, logged_client, famille_user, key):
        consulter, _m, _o = SIMPLE_FICHES[key]
        response, _u, ratt, *_ = self._post(logged_client, famille_user, key)
        assert response.url == _url(consulter, ratt[1])


@pytest.mark.django_db
class TestInvalidPost:
    def test_identite_missing_required_date(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        url = _url("portail_individu_identite_modifier", ratt[1])
        data = post_data(
            logged_client.get(url).context["form"], date_naiss="", nom="Zorro"
        )
        response = logged_client.post(url, data)
        assert response.status_code == 200
        assert "date_naiss" in response.context["form"].errors
        assert Individu.objects.get(pk=ratt[1].individu_id).nom != "Zorro"
        assert PortailRenseignement.objects.count() == 0

    def test_identite_missing_required_nom(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        url = _url("portail_individu_identite_modifier", ratt[1])
        data = post_data(logged_client.get(url).context["form"], nom="")
        response = logged_client.post(url, data)
        assert response.status_code == 200
        assert "nom" in response.context["form"].errors

    def test_regimes_unknown_pk_rejected(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        url = _url("portail_individu_regimes_alimentaires_modifier", ratt[1])
        response = logged_client.post(url, {"regimes_alimentaires": [987654]})
        assert response.status_code == 200
        assert "regimes_alimentaires" in response.context["form"].errors

    def test_maladies_unknown_pk_rejected(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        url = _url("portail_individu_maladies_modifier", ratt[1])
        response = logged_client.post(url, {"maladies": [987654]})
        assert response.status_code == 200
        assert "maladies" in response.context["form"].errors

    def test_medecin_unknown_pk_rejected(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        url = _url("portail_individu_medecin_modifier", ratt[1])
        response = logged_client.post(url, {"medecin": 987654})
        assert response.status_code == 200
        assert "medecin" in response.context["form"].errors

    def test_coords_rattachee_without_target_is_error(
        self, logged_client, famille_user
    ):
        _u, _f, ratt = famille_user
        url = _url("portail_individu_coords_modifier", ratt[1])
        data = post_data(
            logged_client.get(url).context["form"],
            type_adresse="RATTACHEE",
            adresse_auto="",
        )
        response = logged_client.post(url, data)
        assert response.status_code == 200
        assert "adresse_auto" in response.context["form"].errors

    def test_coords_invalid_mail(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        url = _url("portail_individu_coords_modifier", ratt[0])
        data = post_data(logged_client.get(url).context["form"], mail="not-an-email")
        response = logged_client.post(url, data)
        assert response.status_code == 200
        assert "mail" in response.context["form"].errors

    def test_coords_mail_domain_without_mx_rejected(
        self, logged_client, famille_user, monkeypatch
    ):
        """clean_mail runs the MX domain validator for a non-empty address."""
        from django.core.exceptions import ValidationError

        def boom(value):
            raise ValidationError("Domaine inconnu")

        monkeypatch.setattr(
            "portail.forms.individu_coords.validate_email_domain_mx", boom
        )
        _u, _f, ratt = famille_user
        url = _url("portail_individu_coords_modifier", ratt[0])
        data = post_data(
            logged_client.get(url).context["form"], mail="a@b.invalid", travail_mail=""
        )
        response = logged_client.post(url, data)
        assert response.status_code == 200
        assert "mail" in response.context["form"].errors

    def test_coords_travail_mail_domain_without_mx_rejected(
        self, logged_client, famille_user, monkeypatch
    ):
        from django.core.exceptions import ValidationError

        def boom(value):
            raise ValidationError("Domaine inconnu")

        monkeypatch.setattr(
            "portail.forms.individu_coords.validate_email_domain_mx", boom
        )
        _u, _f, ratt = famille_user
        url = _url("portail_individu_coords_modifier", ratt[0])
        data = post_data(
            logged_client.get(url).context["form"], mail="", travail_mail="a@b.invalid"
        )
        response = logged_client.post(url, data)
        assert response.status_code == 200
        assert "travail_mail" in response.context["form"].errors


# ---------------------------------------------------------------------------
# Identite / coords specific context branches
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIdentiteContext:
    def test_no_missing_fields_when_identity_complete(
        self, logged_client, famille_user
    ):
        _u, _f, ratt = famille_user
        Individu.objects.filter(pk=ratt[1].individu_id).update(
            civilite=1,
            cp_naiss="75001",
            ville_naiss="PARIS",
            date_naiss=datetime.date(2015, 1, 1),
        )
        response = logged_client.get(
            _url("portail_individu_identite_modifier", ratt[1])
        )
        assert response.context["champs_manquants"] == []

    def test_all_missing_fields_detected(
        self, logged_client, famille_user, monkeypatch
    ):
        # civilite=0 is not a real civility, so the template photo lookup would crash: stub it.
        monkeypatch.setattr(Individu, "Get_photo", lambda self, *a, **k: "")
        _u, _f, ratt = famille_user
        Individu.objects.filter(pk=ratt[1].individu_id).update(
            civilite=0,
            nom="",
            prenom="",
            date_naiss=None,
            cp_naiss=None,
            ville_naiss=None,
        )
        response = logged_client.get(
            _url("portail_individu_identite_modifier", ratt[1])
        )
        assert set(response.context["champs_manquants"]) == {
            "civilite",
            "date_naiss",
            "cp_naiss",
            "ville_naiss",
            "nom",
            "prenom",
        }

    def test_consulter_has_no_champs_manquants_context(
        self, logged_client, famille_user
    ):
        _u, _f, ratt = famille_user
        response = logged_client.get(_url("portail_individu_identite", ratt[1]))
        assert "champs_manquants" not in response.context


@pytest.mark.django_db
class TestCoordsContext:
    def test_parent_missing_everything(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        response = logged_client.get(_url("portail_individu_coords_modifier", ratt[0]))
        assert set(response.context["champs_manquants"]) == {
            "rue_resid",
            "cp_resid",
            "ville_resid",
            "tel_mobile",
            "tel_domicile",
            "mail",
        }

    def test_parent_complete(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        Individu.objects.filter(pk=ratt[0].individu_id).update(
            rue_resid="1 rue X",
            cp_resid="75001",
            ville_resid="PARIS",
            tel_mobile="0601020304",
            mail="a@exemple.org",
        )
        response = logged_client.get(_url("portail_individu_coords_modifier", ratt[0]))
        assert response.context["champs_manquants"] == []

    def test_child_never_flagged(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        response = logged_client.get(_url("portail_individu_coords_modifier", ratt[1]))
        assert response.context["champs_manquants"] == []

    def test_titulaire_non_representant_is_flagged(self, logged_client, famille_user):
        """A titulaire (even with categorie != 1) is treated as a parent."""
        _u, _f, ratt = famille_user
        Rattachement.objects.filter(pk=ratt[1].pk).update(titulaire=True)
        response = logged_client.get(_url("portail_individu_coords_modifier", ratt[1]))
        assert "rue_resid" in response.context["champs_manquants"]

    def test_save_with_proper_address_rattachee_and_cascade(
        self, logged_client, famille_user
    ):
        """Choosing an attached address saves adresse_auto and Maj_infos cascades."""
        _u, _f, ratt = famille_user
        parent = ratt[0].individu
        Individu.objects.filter(pk=parent.pk).update(
            rue_resid="3 rue Parent", cp_resid="75002", ville_resid="PARIS"
        )
        url = _url("portail_individu_coords_modifier", ratt[1])
        form = logged_client.get(url).context["form"]
        assert form.fields["type_adresse"].initial == "PROPRE"
        assert parent.pk in [i.pk for i in form.fields["adresse_auto"].queryset]
        data = post_data(form, type_adresse="RATTACHEE", adresse_auto=parent.pk)
        response = logged_client.post(url, data)
        assert response.status_code == 302
        enfant = Individu.objects.get(pk=ratt[1].individu_id)
        assert enfant.adresse_auto == parent.pk
        # The attached form now reports RATTACHEE.
        form2 = logged_client.get(url).context["form"]
        assert form2.fields["type_adresse"].initial == "RATTACHEE"

    def test_type_adresse_propre_clears_adresse_auto(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        parent = ratt[0].individu
        Individu.objects.filter(pk=ratt[1].individu_id).update(adresse_auto=parent.pk)
        url = _url("portail_individu_coords_modifier", ratt[1])
        form = logged_client.get(url).context["form"]
        data = post_data(
            form,
            type_adresse="PROPRE",
            adresse_auto=parent.pk,
            rue_resid="9 rue Propre",
        )
        assert logged_client.post(url, data).status_code == 302
        enfant = Individu.objects.get(pk=ratt[1].individu_id)
        assert enfant.adresse_auto is None
        assert enfant.rue_resid == "9 rue Propre"


# ---------------------------------------------------------------------------
# Portail champ / onglet parameters
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestChampsParameters:
    def test_afficher_field_is_disabled_in_edition(self, logged_client, famille_user):
        """A field configured AFFICHER is read-only even in edit mode."""
        PortailChamp.objects.create(
            page="individu_identite", code="nom", enfant="AFFICHER"
        )
        _u, _f, ratt = famille_user
        form = logged_client.get(
            _url("portail_individu_identite_modifier", ratt[1])
        ).context["form"]
        assert form.fields["nom"].disabled is True
        assert "n'est pas modifiable" in str(form.fields["nom"].help_text)
        assert form.fields["prenom"].disabled is False

    def test_masquer_field_not_in_layout(self, logged_client, famille_user):
        PortailChamp.objects.create(
            page="individu_identite", code="prenom", enfant="MASQUER"
        )
        _u, _f, ratt = famille_user
        response = logged_client.get(
            _url("portail_individu_identite_modifier", ratt[1])
        )
        assert 'name="prenom"' not in response.content.decode()
        assert 'name="nom"' in response.content.decode()

    def test_onglet_hidden_when_all_fields_masked(self, logged_client, famille_user):
        PortailChamp.objects.create(
            page="individu_regimes_alimentaires",
            code="regimes_alimentaires",
            enfant="MASQUER",
        )
        _u, _f, ratt = famille_user
        response = logged_client.get(_url("portail_individu_identite", ratt[1]))
        codes = [o.code for o in response.context["liste_onglets"]]
        assert "individu_regimes_alimentaires" not in codes
        assert "individu_identite" in codes

    def test_modifier_page_for_hidden_field_still_renders(
        self, logged_client, famille_user
    ):
        PortailChamp.objects.create(
            page="individu_medecin", code="medecin", enfant="MASQUER"
        )
        _u, _f, ratt = famille_user
        assert (
            logged_client.get(
                _url("portail_individu_medecin_modifier", ratt[1])
            ).status_code
            == 200
        )


# ---------------------------------------------------------------------------
# Medecin
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_medecin_modifier_provides_creation_form(logged_client, famille_user):
    _u, _f, ratt = famille_user
    response = logged_client.get(_url("portail_individu_medecin_modifier", ratt[1]))
    assert "form_ajout" in response.context
    # The consultation page does not carry the "add a doctor" modal form.
    assert (
        "form_ajout"
        not in logged_client.get(_url("portail_individu_medecin", ratt[1])).context
    )


# ---------------------------------------------------------------------------
# AJAX "add a choice" endpoints
# ---------------------------------------------------------------------------

SIMPLE_AJAX = [
    ("portail_ajax_ajouter_regime_alimentaire", RegimeAlimentaire),
    ("portail_ajax_ajouter_maladie", TypeMaladie),
    ("portail_ajax_ajouter_allergie", TypeAllergie),
    ("portail_ajax_ajouter_dispmed", TypeDispmed),
]


@pytest.mark.django_db
@pytest.mark.parametrize("route,model", SIMPLE_AJAX)
class TestSimpleAjaxAdd:
    def test_valid_creates_and_returns_id(
        self, logged_client, famille_user, route, model
    ):
        response = logged_client.post(
            reverse(route), {"valeur": "Nouveau choix"}, **AJAX
        )
        assert response.status_code == 200
        obj = model.objects.get(nom="Nouveau choix")
        assert response.json() == {"id": obj.pk, "valeur": "Nouveau choix"}

    @pytest.mark.xfail(
        reason="BUG: the endpoint does not validate 'valeur'; a missing value crashes with an "
        "IntegrityError (500) instead of returning a 4xx JSON error.",
        strict=True,
    )
    def test_missing_value_is_client_error(
        self, logged_client, famille_user, route, model
    ):
        response = logged_client.post(reverse(route), {}, **AJAX)
        assert 400 <= response.status_code < 500

    @pytest.mark.xfail(
        reason="BUG: the endpoint accepts an empty/blank 'valeur' and creates a nameless choice.",
        strict=True,
    )
    def test_blank_value_is_rejected(self, logged_client, famille_user, route, model):
        response = logged_client.post(reverse(route), {"valeur": "   "}, **AJAX)
        assert response.status_code >= 400
        assert not model.objects.filter(nom__regex=r"^\s*$").exists()


@pytest.mark.django_db
class TestAjouterMedecinAjax:
    VALID = {
        "nom": "dupont",
        "prenom": "jean-paul",
        "rue_resid": "1 rue de la paix",
        "cp_resid": "75001",
        "ville_resid": "paris",
        "tel_cabinet": "0102030405",
    }

    def test_valid_formats_and_creates(self, logged_client, famille_user):
        response = logged_client.post(
            reverse("portail_ajax_ajouter_medecin"),
            {"valeurs": json.dumps(self.VALID)},
            **AJAX,
        )
        assert response.status_code == 200
        medecin = Medecin.objects.get(pk=response.json()["id"])
        assert medecin.nom == "DUPONT"
        assert medecin.prenom == "Jean-Paul"
        assert medecin.rue_resid == "1 Rue De La Paix"
        assert medecin.ville_resid == "PARIS"
        assert response.json()["nom"] == medecin.Get_nom(afficher_ville=True)

    def test_invalid_returns_401_with_message(self, logged_client, famille_user):
        valeurs = dict(self.VALID, nom="")
        response = logged_client.post(
            reverse("portail_ajax_ajouter_medecin"),
            {"valeurs": json.dumps(valeurs)},
            **AJAX,
        )
        assert response.status_code == 401
        assert "Nom" in response.json()["erreur"]
        assert not Medecin.objects.exists()

    @pytest.mark.xfail(
        reason="BUG: a missing 'valeurs' POST param makes json.loads(None) raise TypeError (500) "
        "instead of a 4xx JSON error.",
        strict=True,
    )
    def test_missing_valeurs_param_is_client_error(self, logged_client, famille_user):
        response = logged_client.post(
            reverse("portail_ajax_ajouter_medecin"), {}, **AJAX
        )
        assert 400 <= response.status_code < 500


@pytest.mark.django_db
class TestAjouterAssureurAjax:
    VALID = {
        "nom": "maif",
        "rue_resid": "2 rue du port",
        "cp_resid": "33000",
        "ville_resid": "bordeaux",
        "telephone": "0102030405",
    }

    def test_valid_formats_and_creates(self, logged_client, famille_user):
        from core.models import Assureur

        response = logged_client.post(
            reverse("portail_ajax_ajouter_assureur"),
            {"valeurs": json.dumps(self.VALID)},
            **AJAX,
        )
        assert response.status_code == 200
        assureur = Assureur.objects.get(pk=response.json()["id"])
        assert assureur.nom == "MAIF"
        assert assureur.rue_resid == "2 Rue Du Port"
        assert assureur.ville_resid == "BORDEAUX"
        assert response.json()["nom"] == assureur.Get_nom(afficher_ville=True)

    @pytest.mark.xfail(
        reason="BUG: a missing 'valeurs' POST param makes json.loads(None) raise TypeError (500) "
        "instead of a 4xx JSON error.",
        strict=True,
    )
    def test_missing_valeurs_param_is_client_error(self, logged_client, famille_user):
        response = logged_client.post(
            reverse("portail_ajax_ajouter_assureur"), {}, **AJAX
        )
        assert 400 <= response.status_code < 500

    def test_invalid_returns_401_with_message(self, logged_client, famille_user):
        from core.models import Assureur

        valeurs = dict(self.VALID, nom="")
        response = logged_client.post(
            reverse("portail_ajax_ajouter_assureur"),
            {"valeurs": json.dumps(valeurs)},
            **AJAX,
        )
        assert response.status_code == 401
        assert "Nom" in response.json()["erreur"]
        assert not Assureur.objects.exists()
