"""Tests for adding family members (child / parent) from the portal."""

import pytest
from django.urls import reverse

from core.models import Individu, Rattachement


@pytest.mark.django_db
class TestAjoutEnfant:
    def test_form_renders(self, logged_client):
        response = logged_client.get(reverse("famille_individu"))
        assert response.status_code == 200
        assert "form" in response.context

    def test_post_creates_child_and_rattachement(self, logged_client, famille_user):
        _user, famille, _ratt = famille_user
        before = Rattachement.objects.filter(famille=famille).count()

        response = logged_client.post(
            reverse("famille_individu"),
            {
                "civilite": 1,
                "prenom": "Nouvel",
                "nom": "Enfant",
                "date_naiss": "2016-05-05",
                "copier_adresse_parent": "on",
            },
        )
        assert response.status_code == 302
        assert Rattachement.objects.filter(famille=famille).count() == before + 1
        assert Individu.objects.filter(prenom="Nouvel", nom="Enfant").exists()


@pytest.mark.django_db
class TestAjoutParent:
    def test_form_renders(self, logged_client):
        response = logged_client.get(reverse("famille_parent"))
        assert response.status_code == 200
