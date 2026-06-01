"""Tests for the contact hub, per-structure conversation and messagerie."""

import pytest
from django.urls import reverse

from core.models import PortailMessage
from tests.unit.factories import PortailMessageFactory, StructureFactory


@pytest.mark.django_db
class TestContact:
    def test_hub_renders(self, logged_client):
        response = logged_client.get(reverse("portail_contact"))
        assert response.status_code == 200

    def test_conversation_renders_and_marks_read(self, logged_client, famille_user, staff_user):
        _user, famille, _ratt = famille_user
        structure = StructureFactory()
        msg = PortailMessageFactory(
            famille=famille, structure=structure, utilisateur=staff_user
        )
        assert msg.date_lecture is None

        url = reverse("portail_contact_conversation", kwargs={"idstructure": structure.pk})
        response = logged_client.get(url)
        assert response.status_code == 200
        # Opening the conversation marks the incoming message as read.
        msg.refresh_from_db()
        assert msg.date_lecture is not None


@pytest.mark.django_db
class TestMessagerie:
    def test_form_renders(self, logged_client):
        structure = StructureFactory()
        url = reverse("portail_messagerie", kwargs={"idstructure": structure.pk})
        response = logged_client.get(url)
        assert response.status_code == 200

    def test_post_creates_message(self, logged_client, famille_user):
        _user, famille, _ratt = famille_user
        structure = StructureFactory()
        url = reverse("portail_messagerie", kwargs={"idstructure": structure.pk})
        response = logged_client.post(
            url,
            {"famille": famille.pk, "structure": structure.pk, "texte": "Bonjour la structure"},
        )
        assert response.status_code == 302
        msg = PortailMessage.objects.get(famille=famille, structure=structure)
        assert msg.texte == "Bonjour la structure"
        # A family-sent message has no staff utilisateur.
        assert msg.utilisateur is None
