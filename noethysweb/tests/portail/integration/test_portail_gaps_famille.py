"""Gap-closing tests for the "add a child / add a parent" portail views and the dead forms/famille_individu module."""

import pytest
from core.models import ContactUrgence, Individu, Rattachement
from django import forms
from django.test import RequestFactory
from django.urls import reverse
from portail.views import famille_individu, famille_parent
from portail.views.base import CustomView

CHILD = {"civilite": 1, "prenom": "Nouvel", "nom": "Enfant", "date_naiss": "2016-05-05"}


def _set_all_addresses_linked(famille):
    """Make every member of the family point to another address (adresse_auto not NULL)."""
    Individu.objects.filter(rattachement__famille=famille).update(adresse_auto=999999)


@pytest.mark.django_db
class TestAjouterEnfantBranches:
    def test_address_copied_from_first_parent(self, logged_client, famille_user):
        _u, _famille, ratt = famille_user
        logged_client.post(
            reverse("famille_individu"), dict(CHILD, copier_adresse_parent="on")
        )
        enfant = Individu.objects.get(prenom="Nouvel")
        assert enfant.adresse_auto == ratt[0].individu.pk

    def test_no_parent_address_available_leaves_address_unlinked(
        self, logged_client, famille_user
    ):
        """famille_individu.py:298->307 - no member without a linked address -> nothing to copy."""
        _u, famille, _ratt = famille_user
        _set_all_addresses_linked(famille)
        response = logged_client.post(
            reverse("famille_individu"), dict(CHILD, copier_adresse_parent="on")
        )
        assert response.status_code == 302
        assert Individu.objects.get(prenom="Nouvel").adresse_auto is None

    def test_manual_address_is_stored(self, logged_client, famille_user):
        """famille_individu.py:302-305 - copier_adresse_parent unchecked -> the typed address is used."""
        _u, _famille, _ratt = famille_user
        response = logged_client.post(
            reverse("famille_individu"),
            dict(
                CHILD,
                rue_resid="3 rue des Fleurs",
                cp_resid="35000",
                ville_resid="RENNES",
            ),
        )
        assert response.status_code == 302
        enfant = Individu.objects.get(prenom="Nouvel")
        assert (enfant.rue_resid, enfant.cp_resid, enfant.ville_resid) == (
            "3 rue des Fleurs",
            "35000",
            "RENNES",
        )
        assert enfant.adresse_auto is None

    def test_emergency_contact_is_created(self, logged_client, famille_user):
        """famille_individu.py:332-347"""
        _u, famille, _ratt = famille_user
        response = logged_client.post(
            reverse("famille_individu"),
            dict(
                CHILD,
                copier_adresse_parent="on",
                contact_nom="Dupont",
                contact_prenom="Marie",
                contact_lien="Tante",
                contact_tel_mobile="0600000000",
                contact_tel_domicile="0299000000",
                contact_autorisation_sortie="on",
            ),
        )
        assert response.status_code == 302
        contact = ContactUrgence.objects.get(famille=famille)
        assert (contact.nom, contact.prenom, contact.lien) == (
            "Dupont",
            "Marie",
            "Tante",
        )
        assert (contact.tel_mobile, contact.tel_domicile) == (
            "0600000000",
            "0299000000",
        )
        assert contact.individu.prenom == "Nouvel"
        assert contact.autorisation_sortie is True
        assert contact.autorisation_appel is False  # unchecked checkbox

    def test_contact_with_only_a_first_name_is_created(
        self, logged_client, famille_user
    ):
        _u, famille, _ratt = famille_user
        logged_client.post(
            reverse("famille_individu"),
            dict(CHILD, copier_adresse_parent="on", contact_prenom="Zoé"),
        )
        contact = ContactUrgence.objects.get(famille=famille)
        assert (contact.nom, contact.prenom) == ("", "Zoé")

    def test_no_contact_without_name(self, logged_client, famille_user):
        _u, famille, _ratt = famille_user
        logged_client.post(
            reverse("famille_individu"),
            dict(CHILD, copier_adresse_parent="on", contact_lien="Tante"),
        )
        assert not ContactUrgence.objects.filter(famille=famille).exists()

    def test_invalid_post_rerenders_with_errors(self, logged_client, famille_user):
        """famille_individu.py:367 and 396-398"""
        _u, famille, _ratt = famille_user
        before = Rattachement.objects.filter(famille=famille).count()
        response = logged_client.post(
            reverse("famille_individu"), {"civilite": 1, "nom": "SansPrenom"}
        )
        assert response.status_code == 200
        form = response.context["form"]
        assert form.is_bound and "prenom" in form.errors and "date_naiss" in form.errors
        assert response.context["page_titre"] == "Ajouter un enfant"
        assert Rattachement.objects.filter(famille=famille).count() == before

    def test_breadcrumb_is_extended(self, logged_client):
        response = logged_client.get(reverse("famille_individu"))
        assert response.context["breadcrumb"][-1] == {
            "titre": "Ajouter un enfant",
            "url": "",
            "code": "",
        }

    def test_without_breadcrumb_in_context(self, famille_user, monkeypatch):
        """famille_individu.py:361->366 - the base view gave no breadcrumb: nothing is appended."""
        user, _f, _r = famille_user
        monkeypatch.setattr(CustomView, "get_context_data", lambda self, **kw: {})
        request = RequestFactory().get("/")
        request.user = user
        view = famille_individu.AjouterIndividu()
        view.setup(request)
        context = view.get_context_data()
        assert "breadcrumb" not in context
        assert context["page_titre"] == "Ajouter un enfant"

    def test_children_without_many_to_many_querysets(self):
        """famille_individu.py:172->176, 176->180, 180->184, 184->192 - fields without a `queryset` are left alone.
        Unreachable with the stock ModelForm (M2M/FK fields always have a queryset), so the declared fields are
        replaced by plain CharFields in a subclass."""

        class Plain(famille_individu.IndividuForm):
            regimes_alimentaires = forms.CharField(required=False)
            allergies = forms.CharField(required=False)
            dispmed = forms.CharField(required=False)
            medecin = forms.CharField(required=False)

        form = Plain(user=None)
        assert not hasattr(form.fields["allergies"], "queryset")
        assert "bouton +" in form.fields["allergies"].help_text

    def test_children_form_sorts_querysets(self):
        form = famille_individu.IndividuForm(user=None)
        assert "ORDER BY" in str(form.fields["allergies"].queryset.query)


@pytest.mark.django_db
class TestAjouterParentBranches:
    def test_invalid_post_rerenders_with_errors(self, logged_client, famille_user):
        """famille_parent.py:169 and 196-198"""
        _u, famille, _ratt = famille_user
        before = Rattachement.objects.filter(famille=famille).count()
        response = logged_client.post(reverse("famille_parent"), {"nom": "SansPrenom"})
        assert response.status_code == 200
        form = response.context["form"]
        assert form.is_bound and "prenom" in form.errors
        assert response.context["page_titre"] == "Ajouter un parent"
        assert Rattachement.objects.filter(famille=famille).count() == before

    def test_breadcrumb_is_extended(self, logged_client):
        response = logged_client.get(reverse("famille_parent"))
        assert response.context["breadcrumb"][-1] == {
            "titre": "Ajouter un parent",
            "url": "",
            "code": "",
        }

    def test_without_breadcrumb_in_context(self, famille_user, monkeypatch):
        """famille_parent.py:163->168"""
        user, _f, _r = famille_user
        monkeypatch.setattr(CustomView, "get_context_data", lambda self, **kw: {})
        request = RequestFactory().get("/")
        request.user = user
        view = famille_parent.AjouterParent()
        view.setup(request)
        context = view.get_context_data()
        assert "breadcrumb" not in context
        assert context["page_titre"] == "Ajouter un parent"


# ---------------------------------------------------------------------------
# portail/forms/famille_individu.py - dead module
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeadFormsFamilleIndividu:
    """portail/forms/famille_individu.py is not imported anywhere (the live form is
    portail.views.famille_individu.IndividuForm; urls.py uses views.famille_individu.ajout).
    It is dead code; these tests only guarantee that it still imports, instantiates and renders."""

    def test_module_imports_and_form_instantiates(self):
        from portail.forms import famille_individu as dead

        form = dead.IndividuForm()
        assert list(form.fields) == ["prenom", "nom", "statut", "date_naiss"]

    def test_contact_view_passes_form_to_template(self, monkeypatch):
        """The dead view cannot be rendered for real (the template expects the context of the live view), so
        render() is stubbed and only the hand-off is checked."""
        from portail.forms import famille_individu as dead

        captured = {}

        def fake_render(request, template, context):
            captured.update(template=template, context=context)
            return "rendered"

        monkeypatch.setattr(dead, "render", fake_render)
        assert dead.contact(object()) == "rendered"
        assert captured["template"] == "portail/famille_individu.html"
        assert isinstance(captured["context"]["contact_form"], dead.IndividuForm)
