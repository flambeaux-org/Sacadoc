"""Tests for portal authentication-adjacent pages (anonymous + logged-in)."""

import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestAnonymousPages:
    """Pages reachable without logging in."""

    def test_reset_password_renders(self, client, organisateur):
        response = client.get(reverse("reset_password"))
        assert response.status_code == 200

    def test_reset_password_done_renders(self, client, organisateur):
        response = client.get(reverse("password_reset_done"))
        assert response.status_code == 200

    def test_inscription_famille_renders(self, client, organisateur):
        response = client.get(reverse("inscription_famille"))
        assert response.status_code == 200


@pytest.mark.django_db
class TestProfil:
    def test_profil_renders(self, logged_client):
        response = logged_client.get(reverse("portail_profil"))
        assert response.status_code == 200

    def test_profil_password_change_renders(self, logged_client):
        response = logged_client.get(reverse("portail_profil_password_change"))
        assert response.status_code == 200


@pytest.mark.django_db
class TestLogout:
    def test_logout_redirects_to_connexion(self, logged_client):
        response = logged_client.get(reverse("portail_deconnexion"))
        assert response.status_code == 302
        assert "connexion" in response.url
