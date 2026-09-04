"""Tests for the activities / inscriptions pages."""

import pytest
from django.urls import reverse

from tests.unit.factories import ActiviteFactory, InscriptionFactory


@pytest.mark.django_db
class TestActivites:
    def test_list_renders(self, logged_client):
        response = logged_client.get(reverse("portail_activites"))
        assert response.status_code == 200

    def test_list_shows_inscription(self, logged_client, famille_user):
        _user, famille, ratt = famille_user
        enfant = ratt[1].individu
        InscriptionFactory(famille=famille, individu=enfant)
        response = logged_client.get(reverse("portail_activites"))
        assert response.status_code == 200
        assert enfant in response.context["liste_individus"]

    def test_inscrire_form_renders(self, logged_client):
        # An activity must be open to inscription for the page to be meaningful.
        ActiviteFactory(portail_inscriptions_affichage="TOUJOURS")
        response = logged_client.get(reverse("portail_inscrire_activite"))
        assert response.status_code == 200


@pytest.mark.django_db
class TestCotisations:
    def test_page_renders(self, logged_client):
        response = logged_client.get(reverse("portail_cotisations"))
        assert response.status_code == 200
