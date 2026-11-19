"""Gap-closing tests for the portail "fiche" machinery.

Covers portail/views/fiche.py (Onglet base class), the Ajouter/Importer branches of
individu_{contacts,assurances,informations,vaccinations}, forms/fiche.py and
forms/individu_coords.py, famille_caisse and famille_parametres.
"""

import datetime
import io
import json
from types import SimpleNamespace

import pytest
from core.models import (
    Assureur,
    CategorieInformation,
    Famille,
    Individu,
    PortailChamp,
    PortailRenseignement,
    Rattachement,
    TypeVaccin,
)
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.files.images import ImageFile
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.db.models.fields.files import FieldFile
from django.test import RequestFactory
from django.urls import reverse
from django.views.generic import View
from portail.utils import utils_onglets
from portail.views import (
    individu_assurances,
    individu_contacts,
    individu_informations,
    individu_vaccinations,
)
from portail.views.fiche import Onglet


class OngletView(Onglet, View):
    """Onglet is a mixin; add View so that it can be set up with a request."""


def make_view(cls, user, method="post", **attrs):
    """Instantiate a class based view outside of the URL machinery (unit-level)."""
    request = getattr(RequestFactory(), method)("/")
    request.user = user
    request.session = {}
    request._messages = FallbackStorage(request)
    view = cls()
    view.setup(request)
    for key, value in attrs.items():
        setattr(view, key, value)
    return view


def stub_form(changed=("email_blocage",), saved_pk=1):
    return SimpleNamespace(
        changed_data=list(changed),
        cleaned_data={code: True for code in changed},
        initial={},
        save=lambda: SimpleNamespace(pk=saved_pk),
    )


# ---------------------------------------------------------------------------
# views/fiche.py : Onglet
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestOngletUnit:
    def test_formate_valeur_uploaded_file_becomes_null(self):
        """fiche.py:116 - a freshly uploaded file is not serialised."""
        upload = InMemoryUploadedFile(
            io.BytesIO(b"x"), "f", "f.pdf", "application/pdf", 1, None
        )
        assert Onglet().Formate_valeur(upload) == "null"

    def test_formate_valeur_field_file_becomes_null(self):
        assert (
            Onglet().Formate_valeur(
                FieldFile(None, Individu._meta.get_field("photo"), "x.png")
            )
            == "null"
        )

    def test_formate_valeur_image_file_is_marked_as_new_photo(self):
        """fiche.py:120 - ImageFile (not a FieldFile/Uploaded type) -> "nouvelle photo"."""
        assert Onglet().Formate_valeur(
            ImageFile(io.BytesIO(b"x"), name="p.png")
        ) == json.dumps("nouvelle photo")

    def test_formate_valeur_model_queryset_and_list(self, famille_user):
        _u, famille, ratt = famille_user
        view = Onglet()
        assert view.Formate_valeur(famille) == str(famille.pk)
        assert view.Formate_valeur(
            Rattachement.objects.filter(famille=famille).order_by("pk")
        ) == json.dumps(
            [r.pk for r in Rattachement.objects.filter(famille=famille).order_by("pk")]
        )
        assert view.Formate_valeur([ratt[0], 5]) == json.dumps([ratt[0].pk, 5])

    def test_dict_onglet_actif_is_memoised(self):
        """fiche.py:59->64 - second call returns the cached onglet without a new lookup."""
        view = Onglet()
        view.onglet_actif = "famille_caisse"
        first = view.get_dict_onglet_actif()
        assert first.code == "famille_caisse"
        assert view.get_dict_onglet_actif() is first

    def test_dict_onglet_actif_individu_branch(self):
        view = Onglet()
        view.onglet_actif = "individu_identite"
        assert view.get_dict_onglet_actif().code == "individu_identite"

    @pytest.mark.parametrize("validation_auto", [True, False])
    def test_form_valid_ajouter_with_changes_and_no_object(
        self, famille_user, validation_auto, set_parametre_portail
    ):
        """fiche.py:152->156 and 158->161 - verbe_action "Ajouter" (no 'Modifier' debug log) and self.object is None."""
        user, famille, _ratt = famille_user
        set_parametre_portail("validation_auto:famille_caisse", validation_auto)
        view = make_view(
            OngletView,
            user,
            onglet_actif="famille_caisse",
            categorie="famille_caisse",
            verbe_action="Ajouter",
            object=None,
        )
        view.get_success_url = lambda: "/retour/"
        famille.certification_date = datetime.datetime(2024, 1, 1)
        famille.save()

        response = view.form_valid(stub_form())

        assert response.status_code == 302 and response.url == "/retour/"
        renseignement = PortailRenseignement.objects.get(
            famille=famille, categorie="famille_caisse"
        )
        assert renseignement.validation_auto is validation_auto
        assert (renseignement.idobjet == 1) is validation_auto
        messages = [str(m) for m in view.request._messages]
        assert any("Votre ajout a été enregistré" in m for m in messages)
        assert any("transmis à l'administrateur" in m for m in messages) is (
            not validation_auto
        )
        famille.refresh_from_db()
        assert famille.certification_date is None

    def test_apres_suppression_requests_new_certification(self, famille_user):
        """fiche.py:165"""
        user, famille, _ratt = famille_user
        Famille.objects.filter(pk=famille.pk).update(
            certification_date=datetime.datetime(2024, 1, 1)
        )
        view = make_view(OngletView, user, onglet_actif="famille_caisse")
        view.Apres_suppression(objet=None)
        assert Famille.objects.get(pk=famille.pk).certification_date is None

    def test_maj_infos_famille_cascades_to_individus_sharing_the_address(
        self, famille_user, monkeypatch
    ):
        """fiche.py:176 - individus whose adresse_auto points to the edited individu are refreshed too."""
        user, _famille, ratt = famille_user
        parent, enfant = ratt[0].individu, ratt[1].individu
        Individu.objects.filter(pk=enfant.pk).update(adresse_auto=parent.pk)
        refreshed = []
        monkeypatch.setattr(
            Individu, "Maj_infos", lambda self, *a, **k: refreshed.append(self.pk)
        )
        monkeypatch.setattr(Famille, "Maj_infos", lambda self, *a, **k: None)
        view = make_view(
            OngletView, user, onglet_actif="individu_coords", rattachement=ratt[0]
        )
        view.Maj_infos_famille()
        assert refreshed == [parent.pk, enfant.pk]

    @pytest.mark.xfail(
        reason="BUG: portail/views/fiche.py:175-179 - the cascade loop `for individu in Individu.objects.filter(adresse_auto=...)` "
        "rebinds `individu`, so the following Rattachement query refreshes the families of the LAST cascaded "
        "individu instead of the edited individu: families only linked to the edited individu are never refreshed.",
        strict=True,
    )
    def test_maj_infos_famille_refreshes_all_families_of_edited_individu(
        self, famille_user, other_famille, monkeypatch
    ):
        user, famille, ratt = famille_user
        _ub, famille_b, _ratt_b = other_famille
        parent, enfant = ratt[0].individu, ratt[1].individu
        # the parent is also attached to family B; the child shares the parent's address
        Rattachement.objects.create(
            famille=famille_b, individu=parent, categorie=1, titulaire=False
        )
        Individu.objects.filter(pk=enfant.pk).update(adresse_auto=parent.pk)
        refreshed = set()
        monkeypatch.setattr(Individu, "Maj_infos", lambda self, *a, **k: None)
        monkeypatch.setattr(
            Famille, "Maj_infos", lambda self, *a, **k: refreshed.add(self.pk)
        )
        view = make_view(
            OngletView, user, onglet_actif="individu_coords", rattachement=ratt[0]
        )
        view.Maj_infos_famille()
        assert {famille.pk, famille_b.pk} <= refreshed

    def test_get_famille_always_matches_request_user(self, famille_user):
        """fiche.py:74 is unreachable: get_famille() *is* request.user.famille, so the guard `!=` can never be true."""
        user, famille, _ratt = famille_user
        view = make_view(OngletView, user, method="get", onglet_actif="famille_caisse")
        assert view.get_famille() == user.famille == famille


# ---------------------------------------------------------------------------
# famille_caisse / famille_parametres
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFamilleCaisse:
    def test_modifier_manual_validation_warns_about_admin_approval(
        self, logged_client, set_parametre_portail
    ):
        """famille_caisse.py:38"""
        set_parametre_portail("validation_auto:famille_caisse", False)
        response = logged_client.get(reverse("portail_famille_caisse_modifier"))
        assert response.status_code == 200
        assert "validées par l'administrateur" in response.context["box_introduction"]

    def test_modifier_post_redirects_to_caisse_page(self, logged_client):
        """famille_caisse.py:42 - get_success_url (no visible field -> 'Aucune modification' + redirect)."""
        response = logged_client.post(reverse("portail_famille_caisse_modifier"), {})
        assert response.status_code == 302
        assert response.url == reverse("portail_famille_caisse")


@pytest.fixture
def parametres_onglet(monkeypatch):
    """Work around known bug #1: utils_onglets.LISTE_ONGLETS has the 'famille_parametres' onglet commented out
    (utils_onglets.py:27), which makes famille_parametres.Modifier crash with a 500. We re-register it here only
    to reach the remaining lines of the view; the xfail test in test_portail_renseignements.py documents the bug."""
    onglet = utils_onglets.Onglet(
        code="famille_parametres",
        label="Paramètres",
        icone="fa-gear",
        url="portail_famille_parametres",
        validation_auto=True,
    )
    monkeypatch.setattr(
        utils_onglets, "LISTE_ONGLETS", utils_onglets.LISTE_ONGLETS + [onglet]
    )


@pytest.mark.django_db
class TestFamilleParametres:
    def test_modifier_renders_with_onglet_registered(
        self, logged_client, parametres_onglet
    ):
        response = logged_client.get(reverse("portail_famille_parametres_modifier"))
        assert response.status_code == 200
        assert "Modifiez les paramètres" in response.context["box_introduction"]

    def test_modifier_manual_validation_warns(
        self, logged_client, parametres_onglet, set_parametre_portail
    ):
        """famille_parametres.py:38-39"""
        set_parametre_portail("validation_auto:famille_parametres", False)
        response = logged_client.get(reverse("portail_famille_parametres_modifier"))
        assert response.status_code == 200
        assert "validées par l'administrateur" in response.context["box_introduction"]

    def test_modifier_post_saves_and_redirects(
        self, logged_client, famille_user, parametres_onglet
    ):
        """famille_parametres.py:42"""
        _u, famille, _r = famille_user
        response = logged_client.post(
            reverse("portail_famille_parametres_modifier"), {"email_blocage": "on"}
        )
        assert response.status_code == 302
        assert response.url == reverse("portail_famille_parametres")
        assert Famille.objects.get(pk=famille.pk).email_blocage is True

    def test_modifier_post_crashes_without_onglet(self, logged_client):
        """Known bug #1 (see test_portail_renseignements.py) also breaks the POST: Get_onglet returns None."""
        with pytest.raises(AttributeError):
            logged_client.post(
                reverse("portail_famille_parametres_modifier"), {"email_blocage": "on"}
            )


# ---------------------------------------------------------------------------
# individu_{contacts,assurances,informations,vaccinations} : Ajouter / Importer
# ---------------------------------------------------------------------------

MODULES = {
    "contacts": (individu_contacts, "idcontact", "portail_individu_contacts"),
    "assurances": (individu_assurances, "idassurance", "portail_individu_assurances"),
    "informations": (
        individu_informations,
        "idinformation",
        "portail_individu_informations",
    ),
    "vaccinations": (
        individu_vaccinations,
        "idvaccin",
        "portail_individu_vaccinations",
    ),
}


def valid_post(key, famille, individu):
    if key == "contacts":
        return {
            "nom": "Tonton",
            "prenom": "Paul",
            "lien": "Oncle",
            "autorisation_sortie": "on",
            "autorisation_appel": "on",
            "famille": famille.pk,
            "individu": individu.pk,
        }
    if key == "assurances":
        assureur = Assureur.objects.create(nom="MAIF")
        return {
            "assureur": assureur.pk,
            "num_contrat": "NEW-42",
            "date_debut": "2024-02-01",
            "date_fin": "",
            "famille": famille.pk,
            "individu": individu.pk,
        }
    if key == "informations":
        cat = CategorieInformation.objects.create(nom="Autre")
        return {
            "categorie": cat.pk,
            "intitule": "Lunettes",
            "description": "port permanent",
            "individu": individu.pk,
        }
    tv = TypeVaccin.objects.create(nom="ROR")
    return {"type_vaccin": tv.pk, "date": "2021-03-04", "individu": individu.pk}


@pytest.mark.django_db
@pytest.mark.parametrize("key", list(MODULES))
class TestAjouterBranches:
    def test_get_object_without_pk_returns_none(self, key, famille_user):
        """individu_<x>.py get_object: `return None` when the URL has no object id.
        Not reachable through HTTP (CreateView never calls get_object), so it is exercised directly."""
        module, _kw, _url = MODULES[key]
        user, _f, ratt = famille_user
        view = make_view(
            module.Ajouter, user, method="get", kwargs={"idrattachement": ratt[1].pk}
        )
        assert view.get_object() is None

    def test_ajouter_saves_history_when_object_is_set(
        self, key, famille_user, logged_client, monkeypatch
    ):
        """individu_<x>.Ajouter.form_valid: `if self.object: self.save_historique(...)`.
        CreateView.post() always resets self.object to None before form_valid, so the branch can only be
        reached if the object is pre-set; simulate it by pre-setting the attribute from the CreateView.post hook."""

        module, _kw, url_liste = MODULES[key]
        _u, famille, ratt = famille_user
        sentinel = SimpleNamespace(pk=0)

        calls = []

        def spy(self, instance=None, form=None, **kw):
            calls.append(instance)

        monkeypatch.setattr(module.Ajouter, "save_historique", spy)
        # make the view believe an object exists at form_valid time
        original = module.Ajouter.form_valid

        def form_valid(self, form):
            self.object = sentinel
            return original(self, form)

        monkeypatch.setattr(module.Ajouter, "form_valid", form_valid)
        response = logged_client.post(
            reverse(url_liste + "_ajouter", kwargs={"idrattachement": ratt[1].pk}),
            valid_post(key, famille, ratt[1].individu),
        )
        assert response.status_code == 302
        assert calls == [sentinel]


@pytest.mark.django_db
@pytest.mark.parametrize("key", ["contacts", "assurances"])
class TestImporterInvalidForm:
    """individu_{contacts,assurances}.Importer.post - `if form.is_valid() == False: render`.
    The importer form has a single optional CharField so it can never be invalid from a real request (dead code
    in practice); the branch is covered by forcing is_valid() to False."""

    def test_invalid_form_returns_template_response(
        self, key, famille_user, monkeypatch
    ):
        module, _kw, _url = MODULES[key]
        user, _f, ratt = famille_user
        monkeypatch.setattr(module.Formulaire_importer, "is_valid", lambda self: False)
        view = make_view(module.Importer, user, kwargs={"idrattachement": ratt[1].pk})
        response = view.post(view.request, idrattachement=ratt[1].pk)
        assert response.status_code == 200
        assert response.template_name == ["portail/fiche_edit.html"]
        assert "form" in response.context_data
        assert not PortailRenseignement.objects.exists()

    @pytest.mark.xfail(
        reason="BUG (latent, unreachable with a real request): Importer.post() calls self.get_context_data(form=form) "
        "without the URL kwargs, so the template cannot reverse portail_individu_<x> (idrattachement missing) "
        "-> NoReverseMatch when the invalid-form response is rendered.",
        strict=True,
    )
    def test_invalid_form_response_renders(
        self, key, logged_client, famille_user, monkeypatch
    ):
        module, _kw, url_liste = MODULES[key]
        _u, _f, ratt = famille_user
        monkeypatch.setattr(module.Formulaire_importer, "is_valid", lambda self: False)
        response = logged_client.post(
            reverse(url_liste + "_importer", kwargs={"idrattachement": ratt[1].pk}), {}
        )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# forms/fiche.py and forms/individu_coords.py
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFormsBranches:
    def test_afficher_field_in_consultation_mode_has_no_edit_help_text(
        self, logged_client, famille_user
    ):
        """forms/fiche.py:64->68 - read-only (AFFICHER) field rendered in CONSULTATION mode."""
        _u, _f, ratt = famille_user
        PortailChamp.objects.create(
            page="individu_identite",
            code="nom",
            representant="AFFICHER",
            enfant="AFFICHER",
        )
        response = logged_client.get(
            reverse("portail_individu_identite", kwargs={"idrattachement": ratt[1].pk})
        )
        assert response.status_code == 200
        field = response.context["form"].fields["nom"]
        assert field.disabled is True
        assert "n'est pas modifiable" not in str(field.help_text)

    def test_afficher_field_in_edition_mode_says_not_modifiable(
        self, logged_client, famille_user
    ):
        _u, _f, ratt = famille_user
        PortailChamp.objects.create(
            page="individu_identite",
            code="nom",
            representant="AFFICHER",
            enfant="AFFICHER",
        )
        response = logged_client.get(
            reverse(
                "portail_individu_identite_modifier",
                kwargs={"idrattachement": ratt[1].pk},
            )
        )
        assert response.status_code == 200
        field = response.context["form"].fields["nom"]
        assert field.disabled is True
        assert "n'est pas modifiable" in str(field.help_text)

    # The two tests below build the form directly: rendering the whole page pulls in Select2 widgets, whose
    # settings are reset by the `settings` fixture used by other test modules (order dependent SELECT2_THEME error).

    @staticmethod
    def _coords_form(rattachement):
        from portail.forms.individu_coords import Formulaire

        return Formulaire(
            instance=rattachement.individu, rattachement=rattachement, mode="EDITION"
        )

    def test_coords_adresse_auto_excludes_members_with_a_linked_address(
        self, famille_user
    ):
        """forms/individu_coords.py:58->57 - a member whose address is itself linked is not offered."""
        _u, _f, ratt = famille_user
        parent = ratt[0].individu
        Individu.objects.filter(pk=parent.pk).update(adresse_auto=999999)
        form = self._coords_form(ratt[1])
        queryset = form.fields["adresse_auto"].queryset
        assert parent.pk not in [i.pk for i in queryset]

    def test_coords_adresse_auto_offers_members_with_their_own_address(
        self, famille_user
    ):
        _u, _f, ratt = famille_user
        queryset = self._coords_form(ratt[1]).fields["adresse_auto"].queryset
        assert ratt[0].individu.pk in [i.pk for i in queryset]
