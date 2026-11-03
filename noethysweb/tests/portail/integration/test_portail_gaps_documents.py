"""Gap-closing tests: documents page, transmettre_piece (view + form), approbations form/utils, utils_champs,
verifications and the "renseignements manquants" helpers."""

import datetime
from io import BytesIO

import pytest
from core.models import (
    Inscription,
    Piece,
    PortailChamp,
    PortailDocument,
    PortailRenseignement,
    Rattachement,
    TypeConsentement,
    UniteConsentement,
)
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from portail.utils import utils_approbations, utils_champs
from pypdf import PdfReader, PdfWriter
from tests.unit.factories import (
    ActiviteFactory,
    IndividuFactory,
    InscriptionFactory,
    StructureFactory,
    TypePieceFactory,
)


@pytest.fixture(autouse=True)
def media_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def png(name="doc.png"):
    return SimpleUploadedFile(name, b"\x89PNG\r\n\x1a\n", content_type="image/png")


def pdf(name="doc.pdf"):
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="application/pdf")


# ---------------------------------------------------------------------------
# views/documents.py
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDocumentsPage:
    def test_lists_portail_documents_of_family_activities(
        self, logged_client, famille_user
    ):
        """documents.py:44"""
        _u, famille, ratt = famille_user
        insc = InscriptionFactory(individu=ratt[1].individu, famille=famille)
        document = PortailDocument.objects.create(
            titre="Règlement",
            texte="Version 2024",
            couleur_fond="info",
            structure=insc.activite.structure,
            document=SimpleUploadedFile("reglement.pdf", b"%PDF-1.4"),
        )
        document.activites.add(insc.activite)
        other = PortailDocument.objects.create(
            titre="Autre activité",
            structure=insc.activite.structure,
            document=SimpleUploadedFile("x.pdf", b"%PDF-1.4"),
        )
        other.activites.add(ActiviteFactory())

        response = logged_client.get(reverse("portail_documents"))

        assert response.status_code == 200
        assert response.context["liste_documents"] == [
            {
                "titre": "Règlement",
                "texte": "Version 2024",
                "fichier": document.document,
                "couleur_fond": "info",
                "extension": "pdf",
            }
        ]

    def test_lists_pending_consent_documents(self, logged_client, famille_user):
        """documents.py:55 - unsigned consent units required by an active inscription are offered for download."""
        _u, famille, ratt = famille_user
        insc = InscriptionFactory(individu=ratt[1].individu, famille=famille)
        type_consentement = TypeConsentement.objects.create(nom="Règlement intérieur")
        insc.activite.types_consentements.add(type_consentement)
        unite = UniteConsentement.objects.create(
            type_consentement=type_consentement,
            date_debut=datetime.date(2024, 9, 1),
            document=SimpleUploadedFile("ri.pdf", b"%PDF-1.4"),
        )

        response = logged_client.get(reverse("portail_documents"))

        assert response.status_code == 200
        assert response.context["liste_documents"] == [
            {
                "titre": "Règlement intérieur",
                "texte": "Version du 01/09/2024",
                "fichier": unite.document,
                "couleur_fond": "primary",
                "extension": "pdf",
            }
        ]


# ---------------------------------------------------------------------------
# views/transmettre_piece.py and forms/transmettre_piece.py
# ---------------------------------------------------------------------------

URL_ADD = "portail_transmettre_piece"


@pytest.mark.django_db
class TestTransmettrePieceBranches:
    def test_extra_documents_create_one_piece_each(self, logged_client, famille_user):
        """transmettre_piece.py:60 - document1..4 each become an additional Piece."""
        user, famille, _ratt = famille_user
        response = logged_client.post(
            reverse(URL_ADD),
            {
                "selection_piece": 9999,
                "titre": "Lot",
                "auteur": user.pk,
                "document": png("a.png"),
                "document1": png("b.png"),
                "document3": png("c.png"),
            },
        )
        assert response.status_code == 302
        pieces = Piece.objects.filter(famille=famille, titre="Lot")
        assert pieces.count() == 3
        assert all(p.auteur == user for p in pieces)
        assert (
            PortailRenseignement.objects.filter(
                famille=famille, code="Nouvelle pièce"
            ).count()
            == 1
        )

    def test_pdf_upload_is_watermarked(self, logged_client, famille_user):
        """transmettre_piece.py:77 - PDFs receive the portal watermark."""
        user, famille, _ratt = famille_user
        response = logged_client.post(
            reverse(URL_ADD),
            {
                "selection_piece": 9999,
                "titre": "Certificat",
                "auteur": user.pk,
                "document": pdf(),
            },
        )
        assert response.status_code == 302
        piece = Piece.objects.get(famille=famille, titre="Certificat")
        text = PdfReader(piece.document.path).pages[0].extract_text()
        assert "Sacadoc" in text

    def test_free_piece_requires_a_title(self, logged_client, famille_user):
        user, famille, _ratt = famille_user
        response = logged_client.post(
            reverse(URL_ADD),
            {
                "selection_piece": 9999,
                "titre": "",
                "auteur": user.pk,
                "document": png(),
            },
        )
        assert response.status_code == 200
        assert "titre" in response.context["form"].errors
        assert not Piece.objects.filter(famille=famille).exists()

    def test_modifier_redirects_to_renseignements(self, logged_client, famille_user):
        """transmettre_piece.py:106 - Modifier.get_success_url"""
        user, famille, _ratt = famille_user
        piece = Piece.objects.create(
            famille=famille,
            type_piece=TypePieceFactory(),
            titre="Ancien",
            auteur=user,
            date_debut=datetime.date(2024, 1, 1),
            date_fin=datetime.date(2999, 1, 1),
        )
        url = reverse("portail_documents_parents_modifier", kwargs={"pk": piece.pk})
        form = logged_client.get(url).context["form"]
        data = {name: form.initial[name] for name in ("titre",) if name in form.initial}
        data.update(
            {
                "selection_piece": 9999,
                "titre": "Nouveau titre",
                "auteur": user.pk,
                "document": png(),
            }
        )
        response = logged_client.post(url, data)
        assert response.status_code == 302, response.context["form"].errors
        assert response.url == reverse("portail_renseignements")
        piece.refresh_from_db()
        assert piece.titre == "Nouveau titre"


@pytest.mark.django_db
class TestPredefinedPieceSelection:
    """forms/transmettre_piece.py:144 and :151 - a missing piece listed in "pièces à fournir" is selected by index."""

    def _missing_piece(self, famille, ratt, public):
        insc = InscriptionFactory(individu=ratt[1].individu, famille=famille)
        type_piece = TypePieceFactory(public=public, nom="Assurance")
        insc.activite.pieces.add(type_piece)
        return type_piece

    def _post(self, client, user, **extra):
        data = {"selection_piece": 0, "titre": "", "auteur": user.pk, "document": png()}
        data.update(extra)
        return client.post(reverse(URL_ADD), data)

    def test_form_lists_the_missing_piece(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        type_piece = self._missing_piece(famille, ratt, "individu")
        form = logged_client.get(reverse(URL_ADD)).context["form"]
        assert [p["type_piece"] for p in form.liste_pieces_fournir] == [type_piece]
        assert form.fields["selection_piece"].choices[-1] == (
            9999,
            "Un autre type de pièce",
        )

    def test_individu_piece_is_attached_to_the_individu(
        self, logged_client, famille_user
    ):
        user, famille, ratt = famille_user
        type_piece = self._missing_piece(famille, ratt, "individu")
        response = self._post(logged_client, user)
        assert response.status_code == 302, (
            response.context and response.context["form"].errors
        )
        piece = Piece.objects.get(famille=famille)
        assert piece.type_piece == type_piece
        assert piece.individu == ratt[1].individu
        assert piece.date_debut == datetime.date.today()
        assert piece.date_fin >= datetime.date.today()

    def test_family_piece_has_no_individu(self, logged_client, famille_user):
        user, famille, ratt = famille_user
        type_piece = self._missing_piece(famille, ratt, "famille")
        response = self._post(logged_client, user)
        assert response.status_code == 302
        piece = Piece.objects.get(famille=famille)
        assert piece.type_piece == type_piece
        assert piece.individu is None


# ---------------------------------------------------------------------------
# forms/approbations.py, utils/utils_approbations.py
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestApprobations:
    def test_form_without_pending_approbation_shows_message(
        self, logged_client, famille_user
    ):
        """forms/approbations.py:54"""
        _u, famille, _ratt = famille_user
        now = datetime.datetime.now()
        famille.certification_date = now
        famille.save()
        Rattachement.objects.filter(famille=famille).update(certification_date=now)
        response = logged_client.get(reverse("portail_renseignements"))
        assert response.status_code == 200
        assert list(response.context["form"].fields) == []
        layout = response.context["form"].helper.layout
        assert (
            "Aucune approbation n'est actuellement nécessaire." in layout.fields[0].html
        )

    def test_shared_consent_type_is_deduplicated(self, famille_user):
        """utils_approbations.py:28->27 - two activities requiring the same consent type -> one unit."""
        _u, famille, _ratt = famille_user
        structure = StructureFactory()
        a1, a2 = (
            ActiviteFactory(structure=structure),
            ActiviteFactory(structure=structure),
        )
        type_consentement = TypeConsentement.objects.create(nom="RI")
        a1.types_consentements.add(type_consentement)
        a2.types_consentements.add(type_consentement)
        unite = UniteConsentement.objects.create(
            type_consentement=type_consentement, date_debut=datetime.date(2024, 1, 1)
        )
        result = utils_approbations.Get_approbations_requises(
            famille=famille, activites=[a1, a2]
        )
        assert result["consentements"] == [unite]

    def test_has_any_approbation_missing(self, famille_user):
        """utils_approbations.py:65-66"""
        _u, famille, ratt = famille_user
        assert utils_approbations.has_any_approbation_missing(famille) is False
        InscriptionFactory(
            individu=ratt[1].individu, famille=famille, besoin_certification=False
        )
        assert utils_approbations.has_any_approbation_missing(famille) is False
        InscriptionFactory(
            individu=ratt[1].individu, famille=famille, besoin_certification=True
        )
        assert utils_approbations.has_any_approbation_missing(famille) is True
        assert (
            Inscription.objects.filter(
                famille=famille, besoin_certification=True
            ).count()
            == 1
        )


# ---------------------------------------------------------------------------
# utils/utils_champs.py
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUtilsChamps:
    def test_champ_repr(self):
        """utils_champs.py:22"""
        assert (
            repr(utils_champs.Champ(page="individu_identite", code="nom"))
            == "<individu_identite:nom>"
        )

    def test_get_champs_page_with_explicit_list_skips_lookup(self):
        """utils_champs.py:107->109 - a caller-provided list is used as is (no PortailChamp / cache lookup)."""
        champs = [
            utils_champs.Champ(
                page="p", code="a", representant="AFFICHER", enfant="MASQUER"
            ),
            utils_champs.Champ(
                page="p", code="b", representant="MODIFIABLE", enfant="AFFICHER"
            ),
            utils_champs.Champ(
                page="autre", code="c", representant="MODIFIABLE", enfant="MODIFIABLE"
            ),
        ]
        assert utils_champs.Get_champs_page(
            page="p", categorie="representant", liste_champs=champs
        ) == {"a": "AFFICHER", "b": "MODIFIABLE"}
        assert utils_champs.Get_champs_page(
            page="p", categorie=2, liste_champs=champs
        ) == {"a": "MASQUER", "b": "AFFICHER"}

    @pytest.mark.parametrize(
        "numero, attribut", [(1, "representant"), (2, "enfant"), (3, "contact")]
    )
    def test_get_champs_page_numeric_categories(self, numero, attribut):
        champs = [
            utils_champs.Champ(
                page="p", code="a", representant="R", enfant="E", contact="C"
            )
        ]
        assert utils_champs.Get_champs_page(
            page="p", categorie=numero, liste_champs=champs
        ) == {"a": attribut[0].upper()}

    def test_get_champs_page_default_list_is_overridden_by_db(self):
        PortailChamp.objects.create(
            page="individu_identite",
            code="nom",
            representant="MASQUER",
            enfant="AFFICHER",
            contact="MODIFIABLE",
        )
        assert (
            utils_champs.Get_champs_page(
                page="individu_identite", categorie="representant"
            )["nom"]
            == "MASQUER"
        )
        assert (
            utils_champs.Get_champs_page(page="individu_identite", categorie="enfant")[
                "nom"
            ]
            == "AFFICHER"
        )

    def test_get_labels_champs(self):
        """utils_champs.py:119-122"""
        labels = utils_champs.Get_labels_champs()
        assert labels["caisse"] == "Caisse d'allocation"
        assert labels["nom"]
        assert set(labels) == {champ.code for champ in utils_champs.LISTE_CHAMPS}

    def test_famille_level_db_override_is_ignored(self):
        """Observation (not asserted as a bug): Get_liste_champs copies representant/enfant/contact from PortailChamp
        but never `famille`, so a famille-level setting stored in the database has no effect."""
        PortailChamp.objects.create(
            page="famille_caisse", code="caisse", famille="MODIFIABLE"
        )
        assert (
            utils_champs.Get_champs_page(page="famille_caisse", categorie="famille")[
                "caisse"
            ]
            == "MASQUER"
        )


# ---------------------------------------------------------------------------
# views/verifications.py
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestVerificationsBranches:
    @pytest.mark.xfail(
        reason="BUG: portail/views/verifications.py:32-33 `[rattachement.pk]` is evaluated before the `if rattachement:` "
        "guard at :41, so an inscription whose individu has no Rattachement crashes the page with AttributeError "
        "instead of skipping it. Fix: test `rattachement` (continue) before building the Impression.",
        strict=True,
    )
    def test_inscription_of_individu_without_rattachement_is_skipped(
        self, logged_client, famille_user
    ):
        _u, famille, _ratt = famille_user
        orphelin = IndividuFactory()
        InscriptionFactory(
            individu=orphelin, famille=famille, besoin_certification=True
        )
        response = logged_client.get(reverse("portail_verifications"))
        assert response.status_code == 200
        assert response.context["inscriptions_rattachements"] == []
