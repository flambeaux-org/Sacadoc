"""Tests for the documents page, upload (transmettre) and piece deletion.

Includes security probes for `supprimer_piece`, which is a plain function view
with no authentication or ownership checks (see TEST_PLAN.md).
"""

import pytest
from core.models import Piece
from django.urls import reverse
from tests.unit.factories import PieceFactory


@pytest.mark.django_db
class TestDocumentsPage:
    def test_page_renders(self, logged_client):
        response = logged_client.get(reverse("portail_documents"))
        assert response.status_code == 200

    def test_lists_family_pieces(self, logged_client, famille_user):
        _user, famille, _ratt = famille_user
        PieceFactory(famille=famille, titre="Justificatif")
        response = logged_client.get(reverse("portail_documents"))
        assert response.status_code == 200
        assert any(p.titre == "Justificatif" for p in response.context["liste_pieces"])


@pytest.mark.django_db
class TestTransmettrePiece:
    def test_upload_form_renders(self, logged_client):
        response = logged_client.get(reverse("portail_transmettre_piece"))
        assert response.status_code == 200

    def test_upload_creates_piece(self, logged_client, famille_user):
        """POST with a file and selection_piece=9999 creates a Piece in the DB."""
        from django.core.files.uploadedfile import SimpleUploadedFile

        user, famille, _ratt = famille_user
        doc = SimpleUploadedFile("doc.png", b"\x89PNG\r\n", content_type="image/png")
        response = logged_client.post(
            reverse("portail_transmettre_piece"),
            {
                "selection_piece": 9999,
                "titre": "Test document",
                "famille": famille.pk,
                "auteur": user.pk,
                "document": doc,
            },
        )
        assert response.status_code == 302
        assert Piece.objects.filter(famille=famille, titre="Test document").exists()


@pytest.mark.django_db
class TestSupprimerPiece:
    @pytest.mark.xfail(
        reason="BUG: supprimer_piece GET renders 'core/confirmation_suppression.html' "
        "which does not exist -> TemplateDoesNotExist (500). See TEST_PLAN.md.",
        strict=True,
    )
    def test_confirmation_page_renders_for_owner(self, logged_client, famille_user):
        _user, famille, _ratt = famille_user
        piece = PieceFactory(famille=famille)
        response = logged_client.get(
            reverse("supprimer_piece", kwargs={"pk": piece.pk})
        )
        assert response.status_code == 200

    def test_owner_can_delete_own_piece(self, logged_client, famille_user):
        _user, famille, _ratt = famille_user
        piece = PieceFactory(famille=famille)
        response = logged_client.post(
            reverse("supprimer_piece", kwargs={"pk": piece.pk})
        )
        assert response.status_code == 302
        assert not Piece.objects.filter(pk=piece.pk).exists()

    @pytest.mark.xfail(
        reason="BUG: documents.supprimer_piece is a plain function view with no "
        "login/ownership check — an anonymous user can delete any Piece by pk. "
        "See TEST_PLAN.md.",
        strict=True,
    )
    def test_anonymous_cannot_delete_piece(self, client, famille_user):
        _user, famille, _ratt = famille_user
        piece = PieceFactory(famille=famille)
        client.post(reverse("supprimer_piece", kwargs={"pk": piece.pk}))
        assert Piece.objects.filter(pk=piece.pk).exists()

    @pytest.mark.xfail(
        reason="BUG: documents.supprimer_piece has no ownership check — family A can "
        "delete family B's Piece by pk. See TEST_PLAN.md.",
        strict=True,
    )
    def test_cannot_delete_other_family_piece(self, logged_client, other_famille):
        _user_b, famille_b, _ratt_b = other_famille
        piece = PieceFactory(famille=famille_b)
        logged_client.post(reverse("supprimer_piece", kwargs={"pk": piece.pk}))
        assert Piece.objects.filter(pk=piece.pk).exists()


@pytest.mark.django_db
class TestModifierPiece:
    @pytest.mark.xfail(
        reason="BUG #4: transmettre_piece.Modifier.get_queryset filters only by pk (no "
        "famille) despite its 'sécurité' comment — family A can open/modify family B's "
        "Piece via /documents/modifier/<pk>/. See TEST_PLAN.md.",
        strict=True,
    )
    def test_cannot_open_other_family_piece(self, logged_client, other_famille):
        _user_b, famille_b, _ratt_b = other_famille
        piece = PieceFactory(famille=famille_b)
        response = logged_client.get(
            reverse("portail_documents_parents_modifier", kwargs={"pk": piece.pk})
        )
        # Secure behaviour would deny (403/404); the bug returns the edit form (200).
        assert response.status_code in (403, 404)

    def test_owner_can_open_own_piece(self, logged_client, famille_user):
        _user, famille, _ratt = famille_user
        piece = PieceFactory(famille=famille)
        response = logged_client.get(
            reverse("portail_documents_parents_modifier", kwargs={"pk": piece.pk})
        )
        assert response.status_code == 200

    @pytest.mark.xfail(
        reason="BUG #7: documents.html / renseignements.html link the edit button with "
        "{% url 'portail_documents_modifier' %}, a name now owned by the *staff* parametrage "
        "route — the family's edit button points to a page they cannot access. See TEST_PLAN.md.",
        strict=True,
    )
    def test_documents_page_edit_link_targets_portail_route(
        self, logged_client, famille_user
    ):
        _user, famille, _ratt = famille_user
        piece = PieceFactory(famille=famille)
        response = logged_client.get(reverse("portail_documents"))
        portail_url = reverse(
            "portail_documents_parents_modifier", kwargs={"pk": piece.pk}
        )
        assert portail_url in response.content.decode()
