"""Tests for miscellaneous portal pages (mentions, email unsubscribe)."""

import pytest
from django.urls import reverse

from core.models import Album


@pytest.mark.django_db
class TestMentions:
    def test_renders(self, logged_client):
        response = logged_client.get(reverse("portail_mentions"))
        assert response.status_code == 200


@pytest.mark.django_db
class TestAlbum:
    def test_renders_for_valid_code(self, logged_client):
        album = Album.objects.create(titre="Sortie 2024", code="album-test-code")
        response = logged_client.get(reverse("portail_album", kwargs={"code": album.code}))
        assert response.status_code == 200
        assert response.context["album"].pk == album.pk


@pytest.mark.django_db
class TestDesinscription:
    def test_renders_with_invalid_token(self, client):
        """The unsubscribe page is public (csrf-exempt, GET) and renders even
        for an unrecognised token."""
        response = client.get(reverse("desinscription", kwargs={"valeur": "invalid-token"}))
        assert response.status_code == 200
