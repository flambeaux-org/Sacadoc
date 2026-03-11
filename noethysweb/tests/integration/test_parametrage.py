import pytest

from tests.unit.factories import AdresseMailFactory, UtilisateurFactory


@pytest.mark.django_db
class TestAdresseMailViews:
    def test_liste_returns_200_for_staff(self, client):
        user = UtilisateurFactory(username="staff")
        client.force_login(user)
        response = client.get("/utilisateur/parametrage/adresses_mail/liste")
        assert response.status_code == 200

    def test_liste_redirects_for_anonymous(self, client):
        response = client.get("/utilisateur/parametrage/adresses_mail/liste")
        # Unauthenticated request must redirect (to login)
        assert response.status_code in (301, 302)

    def test_ajouter_returns_200_for_staff(self, client):
        user = UtilisateurFactory(username="staff2")
        client.force_login(user)
        response = client.get("/utilisateur/parametrage/adresses_mail/ajouter")
        assert response.status_code == 200

    def test_modifier_returns_200_for_staff(self, client):
        user = UtilisateurFactory(username="staff3")
        adresse = AdresseMailFactory()
        client.force_login(user)
        response = client.get(
            f"/utilisateur/parametrage/adresses_mail/modifier/{adresse.idadresse}"
        )
        assert response.status_code == 200


@pytest.mark.django_db
class TestStructureViews:
    def test_liste_returns_200_for_staff(self, client):
        user = UtilisateurFactory(username="staff4")
        client.force_login(user)
        response = client.get("/utilisateur/parametrage/structures/liste")
        assert response.status_code == 200

    def test_liste_redirects_for_anonymous(self, client):
        response = client.get("/utilisateur/parametrage/structures/liste")
        assert response.status_code in (301, 302)

    def test_ajouter_returns_200_for_staff(self, client):
        user = UtilisateurFactory(username="staff5")
        client.force_login(user)
        response = client.get("/utilisateur/parametrage/structures/ajouter")
        assert response.status_code == 200
