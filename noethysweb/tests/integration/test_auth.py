import pytest

from tests.unit.factories import UtilisateurFactory


@pytest.mark.django_db
class TestLoginView:
    def test_login_page_returns_200(self, client):
        response = client.get("/connexion")
        assert response.status_code == 200

    def test_valid_login_redirects_to_accueil(self, client):
        UtilisateurFactory(username="staff", categorie="utilisateur")
        response = client.post(
            "/connexion",
            # "turnstile" field is required by the form but validation is skipped
            # when TURNSTILE_ENABLE=False; we still need to satisfy required=True.
            {"username": "staff", "password": "testpassword", "turnstile": "dummy"},
            follow=True,
        )
        assert response.status_code == 200
        # Should land on the staff home page after successful login
        assert "/utilisateur/" in response.redirect_chain[-1][0]

    def test_invalid_login_stays_on_login_page(self, client):
        response = client.post(
            "/connexion",
            {"username": "nobody", "password": "wrong", "turnstile": "dummy"},
            follow=True,
        )
        final_url = (
            response.redirect_chain[-1][0] if response.redirect_chain else "/connexion"
        )
        assert "connexion" in final_url

    def test_unauthenticated_staff_page_redirects(self, client):
        response = client.get("/utilisateur/", follow=False)
        # Must redirect (302 → login page)
        assert response.status_code in (302, 301)


@pytest.mark.django_db
class TestLogout:
    def test_logout_redirects_to_login(self, client):
        user = UtilisateurFactory(username="staff2", categorie="utilisateur")
        client.force_login(user)
        response = client.get("/deconnexion", follow=True)
        # After logout, should end up on the connexion page
        final_url = response.redirect_chain[-1][0] if response.redirect_chain else ""
        assert "connexion" in final_url
