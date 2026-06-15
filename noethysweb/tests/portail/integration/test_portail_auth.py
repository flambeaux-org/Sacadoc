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

    def test_password_reset_complete_renders(self, client, organisateur):
        response = client.get(reverse("password_reset_complete"))
        assert response.status_code == 200


@pytest.mark.django_db
class TestProfil:
    def test_profil_renders(self, logged_client):
        response = logged_client.get(reverse("portail_profil"))
        assert response.status_code == 200

    def test_profil_password_change_renders(self, logged_client):
        response = logged_client.get(reverse("portail_profil_password_change"))
        assert response.status_code == 200

    def test_profil_password_change_post(self, logged_client):
        """POST with new passwords redirects to profil on success."""
        url = reverse("portail_profil_password_change")
        response = logged_client.post(url, {
            "new_password1": "NewSecure_Pass123!",
            "new_password2": "NewSecure_Pass123!",
        })
        assert response.status_code == 302


@pytest.mark.django_db
class TestPasswordChange:
    def test_done_renders(self, logged_client):
        assert logged_client.get(reverse("password_change_done")).status_code == 200

    def test_post_changes_password(self, logged_client, famille_user):
        """POST with valid passwords updates the stored hash."""
        from django.contrib.auth.hashers import check_password

        user, _famille, _ratt = famille_user
        url = reverse("password_change")
        response = logged_client.post(url, {
            "new_password1": "NewSecure_Pass123!",
            "new_password2": "NewSecure_Pass123!",
            "check_conditions": True,
        })
        assert response.status_code == 302
        user.refresh_from_db()
        assert check_password("NewSecure_Pass123!", user.password)


@pytest.mark.django_db
class TestPasswordResetConfirm:
    def test_confirm_renders(self, client, organisateur):
        """GET with a valid uid/token renders the set-password form (or redirects to it)."""
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        from tests.unit.factories import FamilleFactory, FamilleUtilisateurFactory

        user = FamilleUtilisateurFactory()
        FamilleFactory(utilisateur=user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        url = reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token})
        response = client.get(url, follow=True)
        assert response.status_code == 200


@pytest.mark.django_db
class TestFamilleParent:
    def test_post_creates_parent(self, logged_client, famille_user):
        """POST to famille_parent creates a new adult Individu + Rattachement."""
        from core.models import Rattachement

        _user, famille, _ratt = famille_user
        url = reverse("famille_parent")
        response = logged_client.post(url, {"prenom": "NouveauParent", "nom": "Dupont", "civilite": 1})
        assert response.status_code == 302
        assert Rattachement.objects.filter(
            famille=famille, individu__prenom="NouveauParent"
        ).exists()


@pytest.mark.django_db
class TestLogout:
    def test_logout_redirects_to_connexion(self, logged_client):
        response = logged_client.get(reverse("portail_deconnexion"))
        assert response.status_code == 302
        assert "connexion" in response.url
