# ruff: noqa: UP031
"""Branch tests for portail.views.renseignements.View (approbations + documents overview)."""

import datetime

import pytest
from core.models import (
    Attestationdoc,
    CategorieInformation,
    Consentement,
    Information,
    Piece,
    PortailDocument,
    TypeAllergie,
    TypeConsentement,
    TypeDispmed,
    TypeMaladie,
    TypePiece,
    UniteConsentement,
)
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.urls import reverse
from tests.unit.factories import (
    ActiviteFactory,
    InscriptionFactory,
    PieceFactory,
)

URL = "portail_renseignements"


@pytest.fixture
def media_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


@pytest.mark.django_db
class TestAuthorization:
    def test_anonymous_redirected(self, client):
        response = client.get(reverse(URL))
        assert response.status_code == 302 and "connexion" in response.url

    def test_anonymous_post_redirected(self, client):
        assert client.post(reverse(URL), {}).status_code == 302

    def test_staff_denied(self, client, staff_user):
        client.force_login(staff_user)
        assert client.get(reverse(URL)).status_code in (302, 403)


@pytest.mark.django_db
class TestGetContext:
    def test_renders_default(self, logged_client, famille_user):
        response = logged_client.get(reverse(URL))
        assert response.status_code == 200
        ctx = response.context
        assert ctx["page_titre"] == "Renseignements"
        assert ctx["renseignements_manquants"] == {}
        assert ctx["liste_documents"] == []
        assert list(ctx["liste_pieces"]) == []
        assert list(ctx["liste_attestations"]) == []
        assert ctx["pieces_fournir"] == []
        assert ctx["familleid"] is not None

    def test_rattachements_exclude_deceased_and_are_enriched(
        self, logged_client, famille_user
    ):
        _u, _f, ratt = famille_user
        enfant = ratt[1].individu
        cat = CategorieInformation.objects.create(nom="PAI")
        Information.objects.create(individu=enfant, categorie=cat, intitule="Asthme")
        allergie = TypeAllergie.objects.create(nom="Arachide")
        ras = TypeAllergie.objects.create(nom="RAS")
        enfant.allergies.add(allergie, ras)
        disp = TypeDispmed.objects.create(nom="Lunettes")
        enfant.dispmed.add(disp)
        response = logged_client.get(reverse(URL))
        by_pk = {r.pk: r for r in response.context["rattachements"]}
        assert set(by_pk) == {ratt[0].pk, ratt[1].pk}
        ind = by_pk[ratt[1].pk].individu
        assert [i.intitule for i in ind.traitements] == ["Asthme"]
        assert list(ind.allergies2) == [allergie]
        assert list(ind.dispmed2) == [disp]

    def test_deceased_individual_hidden(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        enfant = ratt[1].individu
        enfant.deces = True
        enfant.save()
        response = logged_client.get(reverse(URL))
        assert [r.pk for r in response.context["rattachements"]] == [ratt[0].pk]

    def test_missing_vaccinations_reported(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        TypeMaladie.objects.create(nom="Tétanos", vaccin_obligatoire=True)
        InscriptionFactory(individu=ratt[1].individu, famille=famille)
        response = logged_client.get(reverse(URL))
        manquants = response.context["renseignements_manquants"]
        assert manquants[ratt[1].individu] == ["1 vaccination manquante"] or manquants[
            ratt[1].individu
        ] == ["1 vaccinations manquantes"]

    def test_missing_insurance_reported(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        act = ActiviteFactory(assurance_obligatoire=True, vaccins_obligatoires=False)
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        response = logged_client.get(reverse(URL))
        assert response.context["renseignements_manquants"][ratt[1].individu] == [
            "Assurance manquante"
        ]

    def test_vaccination_and_insurance_both_reported(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        TypeMaladie.objects.create(nom="Tétanos", vaccin_obligatoire=True)
        act = ActiviteFactory(assurance_obligatoire=True)
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        response = logged_client.get(reverse(URL))
        msgs = response.context["renseignements_manquants"][ratt[1].individu]
        assert len(msgs) == 2 and msgs[1] == "Assurance manquante"

    def test_expired_inscription_ignored(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        TypeMaladie.objects.create(nom="Tétanos", vaccin_obligatoire=True)
        InscriptionFactory(
            individu=ratt[1].individu,
            famille=famille,
            date_fin=datetime.date(2000, 1, 1),
        )
        response = logged_client.get(reverse(URL))
        assert response.context["renseignements_manquants"] == {}

    def test_pieces_fournir(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        tp = TypePiece.objects.create(nom="Assurance", public="individu")
        act = ActiviteFactory()
        act.pieces.add(tp)
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        response = logged_client.get(reverse(URL))
        assert [p["type_piece"] for p in response.context["pieces_fournir"]] == [tp]

    def test_documents_for_family_activities(
        self, logged_client, famille_user, media_tmp
    ):
        _u, famille, ratt = famille_user
        act = ActiviteFactory()
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        doc = PortailDocument.objects.create(
            titre="Règlement",
            texte="v2",
            document=SimpleUploadedFile("reg.pdf", b"%PDF"),
            structure=act.structure,
        )
        doc.activites.add(act)
        other = ActiviteFactory()
        doc2 = PortailDocument.objects.create(
            titre="Autre",
            document=SimpleUploadedFile("o.pdf", b"%PDF"),
            structure=other.structure,
        )
        doc2.activites.add(other)
        response = logged_client.get(reverse(URL))
        docs = response.context["liste_documents"]
        assert [d["titre"] for d in docs] == ["Règlement"]
        assert (
            docs[0]["texte"] == "v2"
            and docs[0]["extension"] == "pdf"
            and docs[0]["couleur_fond"] == "primary"
        )

    def test_consentement_documents_listed(
        self, logged_client, famille_user, media_tmp
    ):
        _u, famille, ratt = famille_user
        act = ActiviteFactory()
        tc = TypeConsentement.objects.create(nom="Charte")
        act.types_consentements.add(tc)
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        unite = UniteConsentement.objects.create(
            type_consentement=tc,
            date_debut=datetime.date(2020, 1, 1),
            document=SimpleUploadedFile("c.pdf", b"%PDF"),
        )
        response = logged_client.get(reverse(URL))
        docs = response.context["liste_documents"]
        assert len(docs) == 1
        assert docs[0]["titre"] == "Charte"
        assert docs[0]["texte"].startswith("Version du ")
        assert docs[0]["extension"] == "pdf" and docs[0]["couleur_fond"] == "primary"
        assert docs[0]["fichier"] == unite.document

    @pytest.mark.xfail(
        reason="BUG: UniteConsentement.document is optional (blank=True) but the renseignements page renders "
        "{{ ...document.url }} unconditionally -> ValueError (500) when a consent unit has no file.",
        strict=True,
    )
    def test_consentement_without_document_does_not_crash(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        act = ActiviteFactory()
        tc = TypeConsentement.objects.create(nom="Charte")
        act.types_consentements.add(tc)
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        UniteConsentement.objects.create(
            type_consentement=tc, date_debut=datetime.date(2020, 1, 1)
        )
        assert logged_client.get(reverse(URL)).status_code == 200

    def test_pieces_and_attestations_of_family_only(
        self, logged_client, famille_user, other_famille
    ):
        _u, famille, ratt = famille_user
        _ub, fam_b, ratt_b = other_famille
        mine = PieceFactory(famille=famille)
        mine_individu = PieceFactory(famille=None, individu=ratt[1].individu)
        PieceFactory(famille=fam_b)
        act = ActiviteFactory()
        att = Attestationdoc.objects.create(
            famille=famille, activites=act, individus=ratt[1].individu, fichier="x.pdf"
        )
        Attestationdoc.objects.create(
            famille=fam_b, activites=act, individus=ratt_b[1].individu, fichier="y.pdf"
        )
        response = logged_client.get(reverse(URL))
        assert set(response.context["liste_pieces"]) == {mine, mine_individu}
        assert list(response.context["liste_attestations"]) == [att]


@pytest.mark.django_db
class TestFormValid:
    def _inputs(self, logged_client):
        response = logged_client.get(reverse(URL))
        return list(response.context["form"].fields)

    def test_form_lists_family_and_rattachement_approbations(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        fields = self._inputs(logged_client)
        assert "famille_%d" % famille.pk in fields
        assert {"rattachement_%d" % r.pk for r in ratt} <= set(fields)

    def test_nothing_checked_shows_error(self, logged_client, famille_user):
        response = logged_client.post(reverse(URL), {}, follow=True)
        assert response.redirect_chain[-1][0] == reverse(URL)
        msgs = [str(m) for m in response.context["messages"]]
        assert "Aucune approbation n'a été cochée" in msgs

    def test_single_famille_approbation(self, logged_client, famille_user):
        _u, famille, _ratt = famille_user
        response = logged_client.post(
            reverse(URL), {"famille_%d" % famille.pk: "on"}, follow=True
        )
        msgs = [str(m) for m in response.context["messages"]]
        assert "L'approbation cochée a bien été enregistrée" in msgs
        famille.refresh_from_db()
        assert famille.certification_date is not None

    def test_single_rattachement_approbation(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        logged_client.post(reverse(URL), {"rattachement_%d" % ratt[1].pk: "on"})
        ratt[1].refresh_from_db()
        assert ratt[1].certification_date is not None
        ratt[0].refresh_from_db()
        assert ratt[0].certification_date is None

    def test_multiple_approbations_and_consentement(
        self, logged_client, famille_user, media_tmp
    ):
        _u, famille, ratt = famille_user
        act = ActiviteFactory()
        tc = TypeConsentement.objects.create(nom="Charte")
        act.types_consentements.add(tc)
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        unite = UniteConsentement.objects.create(
            type_consentement=tc,
            date_debut=datetime.date(2020, 1, 1),
            document=SimpleUploadedFile("c.pdf", b"%PDF"),
        )
        data = {
            "unite_%d" % unite.pk: "on",
            "rattachement_%d" % ratt[0].pk: "on",
            "famille_%d" % famille.pk: "on",
        }
        response = logged_client.post(reverse(URL), data, follow=True)
        msgs = [str(m) for m in response.context["messages"]]
        assert "Les 3 approbations cochées ont bien été enregistrées" in msgs
        assert Consentement.objects.filter(
            famille=famille, unite_consentement=unite
        ).exists()

    def test_cannot_certify_other_family_rattachement(
        self, logged_client, famille_user, other_famille
    ):
        """A rattachement of another family is not a field of the form -> ignored."""
        _ub, _fb, ratt_b = other_famille
        response = logged_client.post(
            reverse(URL), {"rattachement_%d" % ratt_b[0].pk: "on"}, follow=True
        )
        ratt_b[0].refresh_from_db()
        assert ratt_b[0].certification_date is None
        assert "Aucune approbation n'a été cochée" in [
            str(m) for m in response.context["messages"]
        ]


@pytest.mark.django_db
class TestSupprimerPieceDeadCode:
    """renseignements.View.supprimer_piece is not routed (documents.supprimer_piece is) but is still part of the module."""

    def test_post_deletes_and_redirects(self, famille_user, rf, django_user_model):
        from portail.views.renseignements import View

        _u, famille, _r = famille_user
        piece = PieceFactory(famille=famille)
        request = rf.post("/x")
        request.session = {}
        from django.contrib.messages.storage.fallback import FallbackStorage

        request._messages = FallbackStorage(request)
        response = View.supprimer_piece(request, piece.pk)
        assert response.status_code == 302
        assert response.url == reverse(URL)
        assert not Piece.objects.filter(pk=piece.pk).exists()

    def test_unknown_piece_404(self, rf):
        from portail.views.renseignements import View

        request = rf.post("/x")
        with pytest.raises(Http404):
            View.supprimer_piece(request, 999999)

    @pytest.mark.xfail(
        reason="BUG: renseignements.py:supprimer_piece renders 'core/confirmation_suppression.html' via a bare render() "
        "without the portail context (options_interface, menu...) -> crash in base.html. The function is also unrouted "
        "dead code (no self, nested in View) with no ownership check.",
        strict=True,
    )
    def test_get_renders_confirmation(self, famille_user, rf):
        from portail.views.renseignements import View

        _u, famille, _r = famille_user
        piece = PieceFactory(famille=famille)
        response = View.supprimer_piece(rf.get("/x"), piece.pk)
        assert response.status_code == 200
