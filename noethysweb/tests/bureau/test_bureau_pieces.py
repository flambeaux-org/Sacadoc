"""Pièces justificatives managed from the fiche famille.

Business rules under test:
- an activity lists the types of pièces it requires; while a pièce is missing the
  fiche famille shows an alert, which disappears once the director uploads it;
- a family-level pièce (public="famille") is attached to the family, an individual
  one to the inscribed member;
- a free pièce ("AUTRE") needs a title; a limited validity needs an end date,
  an unlimited one never expires;
- each extra file uploaded in the same form creates its own pièce.
"""

import datetime

import pytest
from core.models import Piece, TypePiece
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from tests.bureau.conftest import build_form_data


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


def _fichier(nom="scan.pdf"):
    return SimpleUploadedFile(nom, b"%PDF-1.4 test", content_type="application/pdf")


def assert_redirect(response):
    if response.status_code == 200 and response.context and "form" in response.context:
        pytest.fail("Form invalide : %s" % response.context["form"].errors.as_json())
    assert response.status_code in (302, 303), response.status_code


def _post_piece(client, famille, **overrides):
    url = reverse("famille_pieces_ajouter", args=[famille.pk])
    form = client.get(url).context["form"]
    data = build_form_data(form, famille=famille.pk, date_debut="2026-01-01", validite_type="ILLIMITEE")
    data.update({"document": _fichier()})
    data.update(overrides)
    data = {k: v for k, v in data.items() if v is not None}
    return client.post(url, data)


def _alertes(client, famille):
    return client.get(reverse("famille_resume", args=[famille.pk])).context["pieces_fournir"]


@pytest.fixture
def certificat(db, activite):
    """The director's activity requires a medical certificate for each child."""
    type_piece = TypePiece.objects.create(nom="Certificat médical", public="individu")
    activite.pieces.add(type_piece)
    return type_piece


@pytest.fixture
def attestation_assurance(db, activite):
    type_piece = TypePiece.objects.create(nom="Attestation d'assurance", public="famille")
    activite.pieces.add(type_piece)
    return type_piece


@pytest.mark.django_db
class TestPiecesAFournir:
    def test_piece_manquante_signalee_sur_le_resume(self, directeur_client, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        alertes = _alertes(directeur_client, famille)
        assert [(a["type_piece"], a["individu"]) for a in alertes] == [(certificat, enfant)]

    def test_fournir_la_piece_leve_l_alerte(self, directeur_client, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        form = directeur_client.get(reverse("famille_pieces_ajouter", args=[famille.pk])).context["form"]
        # The "pièces à fournir" choice list proposes the missing certificate
        index = next(i for i, label in form.fields["pieces_fournir"].choices if label and "Certificat" in label)

        assert_redirect(_post_piece(directeur_client, famille, mode_piece="AFOURNIR", pieces_fournir=index))
        piece = Piece.objects.get(type_piece=certificat)
        assert piece.individu == enfant
        assert piece.date_fin == datetime.date(2999, 1, 1)
        assert _alertes(directeur_client, famille) == []

    def test_piece_famille_rattachee_a_la_famille(self, directeur_client, directeur, famille_bureau, attestation_assurance):
        famille, _t, _e = famille_bureau
        form = directeur_client.get(reverse("famille_pieces_ajouter", args=[famille.pk])).context["form"]
        index = next(i for i, label in form.fields["pieces_fournir"].choices if label and "assurance" in label)

        assert_redirect(_post_piece(directeur_client, famille, mode_piece="AFOURNIR", pieces_fournir=index))
        piece = Piece.objects.get(type_piece=attestation_assurance)
        assert piece.famille == famille
        assert piece.individu is None
        assert piece.auteur == directeur

    def test_piece_expiree_redevient_a_fournir(self, directeur_client, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        Piece.objects.create(type_piece=certificat, famille=famille, individu=enfant,
                             date_debut=datetime.date(2024, 1, 1), date_fin=datetime.date(2025, 1, 1))
        assert [a["type_piece"] for a in _alertes(directeur_client, famille)] == [certificat]

    def test_piece_d_une_autre_structure_non_signalee(self, directeur_client, famille_bureau):
        """Alerts only concern the director's activities."""
        from tests.unit.factories import ActiviteFactory, InscriptionFactory, StructureFactory

        famille, _t, enfant = famille_bureau
        autre = ActiviteFactory(structure=StructureFactory())
        autre.pieces.add(TypePiece.objects.create(nom="Fiche sanitaire voisine", public="individu"))
        InscriptionFactory(famille=famille, individu=enfant, activite=autre)
        assert _alertes(directeur_client, famille) == []


@pytest.mark.django_db
class TestPieceLibre:
    def test_piece_libre_avec_titre(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        assert_redirect(_post_piece(directeur_client, famille, mode_piece="AUTRE", titre="Jugement de garde",
                                    choix_individu=enfant.pk))
        piece = Piece.objects.get(titre="Jugement de garde")
        assert piece.individu == enfant
        assert piece.type_piece is None
        assert piece.document

    def test_piece_libre_sans_titre_refusee(self, directeur_client, famille_bureau):
        famille, _t, _e = famille_bureau
        response = _post_piece(directeur_client, famille, mode_piece="AUTRE", titre="")
        assert response.status_code == 200
        assert "titre" in response.context["form"].errors
        assert not Piece.objects.exists()

    def test_validite_limitee_sans_date_de_fin_refusee(self, directeur_client, famille_bureau):
        famille, _t, _e = famille_bureau
        response = _post_piece(directeur_client, famille, mode_piece="AUTRE", titre="Ordonnance",
                               validite_type="LIMITEE", date_fin="")
        assert response.status_code == 200
        assert "date_fin" in response.context["form"].errors

    def test_validite_limitee(self, directeur_client, famille_bureau):
        famille, _t, _e = famille_bureau
        assert_redirect(_post_piece(directeur_client, famille, mode_piece="AUTRE", titre="Ordonnance",
                                    validite_type="LIMITEE", date_fin="2026-12-31"))
        assert Piece.objects.get(titre="Ordonnance").date_fin == datetime.date(2026, 12, 31)

    def test_plusieurs_fichiers_creent_plusieurs_pieces(self, directeur_client, famille_bureau):
        famille, _t, _e = famille_bureau
        assert_redirect(_post_piece(directeur_client, famille, mode_piece="AUTRE", titre="Livret de famille",
                                    document1=_fichier("page2.pdf")))
        assert Piece.objects.filter(titre="Livret de famille").count() == 2

    def test_supprimer_une_piece_reactive_l_alerte(self, directeur_client, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        piece = Piece.objects.create(type_piece=certificat, famille=famille, individu=enfant,
                                     date_debut=datetime.date(2026, 1, 1), date_fin=datetime.date(2999, 1, 1))
        assert _alertes(directeur_client, famille) == []
        assert_redirect(directeur_client.post(reverse("famille_pieces_supprimer", args=[famille.pk, piece.pk])))
        assert [a["type_piece"] for a in _alertes(directeur_client, famille)] == [certificat]
