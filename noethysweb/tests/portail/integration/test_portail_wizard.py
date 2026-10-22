"""Tests for the activity-inscription AJAX wizard steps.

Covers the cascading endpoints used by the inscription form:
  Get_activites_par_structure -> Get_form_extra -> Valid_form
"""

import pytest
from django.urls import reverse

from tests.unit.factories import ActiviteFactory, GroupeFactory, StructureFactory

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


@pytest.mark.django_db
class TestGetActivitesParStructure:
    def test_returns_activities_with_groups(self, logged_client):
        structure = StructureFactory()
        activite = ActiviteFactory(structure=structure, visible=True)
        GroupeFactory(activite=activite, nom="Groupe A")

        response = logged_client.post(
            reverse("portail_ajax_get_activites_par_structure"),
            {"structure_id": structure.pk},
            **AJAX,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["activites"]) == 1
        assert data["activites"][0]["nom"] == activite.nom
        assert data["activites"][0]["groupes"][0]["nom"] == "Groupe A"


@pytest.mark.django_db
class TestGetFormExtra:
    def test_missing_params_returns_prompt(self, logged_client):
        response = logged_client.post(
            reverse("portail_ajax_inscrire_get_form_extra"), {}, **AJAX
        )
        assert response.status_code == 200
        assert "Veuillez sélectionner" in response.json()["form_html"]

    def test_returns_form_html(self, logged_client, famille_user):
        _user, _famille, ratt = famille_user
        enfant = ratt[1].individu
        activite = ActiviteFactory()
        response = logged_client.post(
            reverse("portail_ajax_inscrire_get_form_extra"),
            {"individu": enfant.pk, "activite": activite.pk},
            **AJAX,
        )
        assert response.status_code == 200
        assert "form_html" in response.json()


@pytest.mark.django_db
class TestValidForm:
    def test_invalid_submission_returns_400(self, logged_client):
        # Empty payload -> the main form is invalid -> 400 with an error message.
        response = logged_client.post(
            reverse("portail_ajax_inscrire_valid_form"), {}, **AJAX
        )
        assert response.status_code == 400
        assert "erreur" in response.json()
