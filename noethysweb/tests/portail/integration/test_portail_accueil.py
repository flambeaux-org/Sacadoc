"""Integration tests for the portail dashboard (accueil)."""

import pytest

from core.models import PortailMessage


@pytest.mark.django_db
class TestAccueil:
    def test_accueil_redirects_when_anonymous(self, client):
        response = client.get("/", follow=False)
        assert response.status_code == 302
        assert "connexion" in response.url

    def test_accueil_renders_for_famille(self, logged_client):
        response = logged_client.get("/")
        assert response.status_code == 200
        assert "portail/accueil.html" in [t.name for t in response.templates]

    def test_accueil_counts_unread_messages(self, logged_client, famille_user, staff_user):
        _user, famille, _ratt = famille_user
        from tests.unit.factories import StructureFactory

        structure = StructureFactory()
        PortailMessage.objects.create(
            famille=famille, structure=structure, utilisateur=staff_user, texte="Bonjour"
        )
        response = logged_client.get("/")
        assert response.status_code == 200
        assert response.context["nbre_messages_non_lus"] == 1
