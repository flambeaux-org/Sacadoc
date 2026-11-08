# ruff: noqa: RUF012
"""Tests for the "Compléter mon dossier" wizard (portail.views.completer_dossier).

Covers every step builder branch of Get_etapes, the active-step selection in
get_context_data, the PDF generation helper and each POST action.
"""

import datetime

import pytest
from core.models import (
    Piece,
    PortailRenseignement,
    QuestionnaireQuestion,
    QuestionnaireReponse,
    Rattachement,
    TypeCotisation,
    TypeMaladie,
    TypePiece,
)
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from portail.views import completer_dossier
from tests.unit.factories import (
    ActiviteFactory,
    IndividuFactory,
    InscriptionFactory,
    SondageFactory,
)

URL = "portail_completer_dossier"


def complete_identity(individu, **extra):
    individu.civilite = 1
    individu.cp_naiss = "75001"
    individu.ville_naiss = "Paris"
    individu.rue_resid = "1 rue A"
    individu.cp_resid = "75001"
    individu.ville_resid = "Paris"
    individu.tel_mobile = "0600000000"
    individu.mail = "a@test.org"
    for k, v in extra.items():
        setattr(individu, k, v)
    individu.save()
    return individu


@pytest.fixture
def dossier_complet(famille_user):
    """Family whose identity/coords are complete, with no activities (every step complete)."""
    _user, _famille, ratt = famille_user
    for r in ratt:
        complete_identity(r.individu)
    return famille_user


def etapes_by_code(response):
    return {e["code"]: e for e in response.context["etapes"]}


def question(activite, **kw):
    kw.setdefault("categorie", "individu")
    kw.setdefault("ordre", 1)
    kw.setdefault("label", "Q")
    kw.setdefault("controle", "ligne_texte")
    kw.setdefault("structure", activite.structure)
    return QuestionnaireQuestion.objects.create(activite=activite, **kw)


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAuthorization:
    def test_anonymous_redirected_get(self, client):
        response = client.get(reverse(URL))
        assert response.status_code == 302 and "connexion" in response.url

    def test_anonymous_redirected_post(self, client):
        response = client.post(reverse(URL), {"type_action": "questionnaire"})
        assert response.status_code == 302 and "connexion" in response.url

    def test_staff_denied(self, client, staff_user):
        client.force_login(staff_user)
        assert client.get(reverse(URL)).status_code in (302, 403)

    def test_cannot_validate_other_famille_inscription(
        self, logged_client, other_famille, dossier_complet
    ):
        _u, fam_b, ratt_b = other_famille
        insc = InscriptionFactory(
            individu=ratt_b[1].individu, famille=fam_b, besoin_certification=True
        )
        response = logged_client.post(
            reverse(URL), {"type_action": "verification", "inscription_id": insc.pk}
        )
        assert response.status_code == 302
        insc.refresh_from_db()
        assert insc.besoin_certification is True


# ---------------------------------------------------------------------------
# GET : steps
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEtapesStructure:
    def test_renders_with_all_steps_in_order(self, logged_client, dossier_complet):
        response = logged_client.get(reverse(URL))
        assert response.status_code == 200
        codes = [e["code"] for e in response.context["etapes"]]
        assert codes == [
            "renseignements",
            "vaccinations",
            "pieces",
            "questionnaires",
            "sondages",
            "verifications",
        ]
        assert response.context["nbre_etapes"] == 6
        assert response.context["nbre_total_manquants"] == 0

    def test_complete_dossier_lands_on_last_step(self, logged_client, dossier_complet):
        response = logged_client.get(reverse(URL))
        assert response.context["etape_active"]["code"] == "verifications"
        assert response.context["numero_etape"] == 6
        assert response.context["etape_suivante"] is None
        assert response.context["etape_precedente"]["code"] == "sondages"
        assert response.context["etape_active"]["bloquee"] is False
        assert response.context["etape_active"]["complete"] is True

    def test_incomplete_first_step_is_active_by_default(
        self, logged_client, famille_user
    ):
        """Raw family: identity incomplete -> renseignements step active, no previous step."""
        response = logged_client.get(reverse(URL))
        assert response.context["etape_active"]["code"] == "renseignements"
        assert response.context["etape_precedente"] is None
        assert response.context["numero_etape"] == 1
        assert response.context["etape_suivante"]["code"] == "vaccinations"

    def test_requested_step_is_honoured(self, logged_client, dossier_complet):
        response = logged_client.get(reverse(URL) + "?etape=pieces")
        assert response.context["etape_active"]["code"] == "pieces"
        assert response.context["numero_etape"] == 3
        assert response.context["etape_precedente"]["code"] == "vaccinations"
        assert response.context["etape_suivante"]["code"] == "questionnaires"

    def test_unknown_step_falls_back(self, logged_client, dossier_complet):
        response = logged_client.get(reverse(URL) + "?etape=nimportequoi")
        assert response.context["etape_active"]["code"] == "verifications"

    def test_unknown_step_falls_back_to_first_incomplete(
        self, logged_client, famille_user
    ):
        response = logged_client.get(reverse(URL) + "?etape=nimportequoi")
        assert response.context["etape_active"]["code"] == "renseignements"

    def test_pieces_step_provides_form(self, logged_client, dossier_complet):
        response = logged_client.get(reverse(URL) + "?etape=pieces")
        assert "form_piece" in response.context

    def test_non_pieces_step_has_no_form(self, logged_client, dossier_complet):
        response = logged_client.get(reverse(URL) + "?etape=questionnaires")
        assert "form_piece" not in response.context

    def test_titre(self, logged_client, dossier_complet):
        response = logged_client.get(reverse(URL))
        assert response.context["page_titre"] == "Compléter mon dossier"


@pytest.mark.django_db
class TestEtapeRenseignements:
    def test_identity_item(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        complete_identity(ratt[0].individu)
        complete_identity(ratt[1].individu, cp_naiss="")
        response = logged_client.get(reverse(URL))
        etape = etapes_by_code(response)["renseignements"]
        assert etape["nbre"] == 1 and etape["complete"] is False
        item = etape["items"][0]
        assert item["individu"] == ratt[1].individu
        assert item["label"] == "Identité incomplète"
        assert item["url"] == reverse(
            "portail_individu_identite_modifier", args=[ratt[1].pk]
        )
        assert "code postal de naissance" in item["detail"]

    def test_coords_item(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        complete_identity(ratt[0].individu, mail="")
        complete_identity(ratt[1].individu)
        response = logged_client.get(reverse(URL))
        item = etapes_by_code(response)["renseignements"]["items"][0]
        assert item["label"] == "Coordonnées incomplètes"
        assert item["url"] == reverse(
            "portail_individu_coords_modifier", args=[ratt[0].pk]
        )

    def test_deceased_individual_ignored(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        complete_identity(ratt[0].individu)
        complete_identity(ratt[1].individu, cp_naiss="", deces=True)
        response = logged_client.get(reverse(URL))
        assert etapes_by_code(response)["renseignements"]["nbre"] == 0

    def test_blocks_verification_step(self, logged_client, famille_user):
        response = logged_client.get(reverse(URL))
        assert etapes_by_code(response)["verifications"]["bloquee"] is True


@pytest.fixture
def vaccin_obligatoire(db):
    return TypeMaladie.objects.create(nom="Diphtérie", vaccin_obligatoire=True)


@pytest.mark.django_db
class TestEtapeVaccinations:
    def test_missing_vaccination_item(
        self, logged_client, dossier_complet, vaccin_obligatoire
    ):
        _u, famille, ratt = dossier_complet
        InscriptionFactory(individu=ratt[1].individu, famille=famille)
        response = logged_client.get(reverse(URL))
        etape = etapes_by_code(response)["vaccinations"]
        assert etape["nbre"] == 1 and etape["complete"] is False
        item = etape["items"][0]
        assert item["individu"] == ratt[1].individu
        assert item["label"] == "1 vaccination(s) manquante(s)"
        assert item["detail"] == "Diphtérie"
        assert item["url"] == reverse(
            "portail_individu_vaccinations", args=[ratt[1].pk]
        )

    def test_no_item_if_activity_has_no_mandatory_vaccines(
        self, logged_client, dossier_complet, vaccin_obligatoire
    ):
        _u, famille, ratt = dossier_complet
        InscriptionFactory(
            individu=ratt[1].individu,
            famille=famille,
            activite=ActiviteFactory(vaccins_obligatoires=False),
        )
        response = logged_client.get(reverse(URL))
        assert etapes_by_code(response)["vaccinations"]["nbre"] == 0

    def test_expired_inscription_ignored(
        self, logged_client, dossier_complet, vaccin_obligatoire
    ):
        _u, famille, ratt = dossier_complet
        InscriptionFactory(
            individu=ratt[1].individu,
            famille=famille,
            date_fin=datetime.date(2000, 1, 1),
        )
        response = logged_client.get(reverse(URL))
        assert etapes_by_code(response)["vaccinations"]["nbre"] == 0


@pytest.mark.django_db
class TestEtapePieces:
    def test_missing_piece_counts(self, logged_client, dossier_complet):
        _u, famille, ratt = dossier_complet
        type_piece = TypePiece.objects.create(nom="Assurance", public="individu")
        act = ActiviteFactory()
        act.pieces.add(type_piece)
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        response = logged_client.get(reverse(URL))
        etape = etapes_by_code(response)["pieces"]
        assert etape["nbre"] == 1 and etape["complete"] is False
        assert etape["pieces_fournir"][0]["type_piece"] == type_piece

    def test_masked_individual_excluded(self, logged_client, dossier_complet):
        _u, famille, ratt = dossier_complet
        type_piece = TypePiece.objects.create(nom="Assurance", public="individu")
        act = ActiviteFactory()
        act.pieces.add(type_piece)
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        famille.individus_masques.add(ratt[1].individu)
        response = logged_client.get(reverse(URL))
        assert etapes_by_code(response)["pieces"]["nbre"] == 0

    def test_valid_piece_not_missing(self, logged_client, dossier_complet):
        _u, famille, ratt = dossier_complet
        type_piece = TypePiece.objects.create(nom="Assurance", public="individu")
        act = ActiviteFactory()
        act.pieces.add(type_piece)
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        Piece.objects.create(
            type_piece=type_piece,
            famille=famille,
            individu=ratt[1].individu,
            titre="ok",
            date_debut=datetime.date(2000, 1, 1),
            date_fin=datetime.date(2999, 1, 1),
        )
        response = logged_client.get(reverse(URL))
        assert etapes_by_code(response)["pieces"]["nbre"] == 0


@pytest.mark.django_db
class TestEtapeQuestionnaires:
    def test_unanswered_question_listed_with_defaults(
        self, logged_client, dossier_complet
    ):
        _u, famille, ratt = dossier_complet
        act = ActiviteFactory()
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        q = question(act)
        response = logged_client.get(reverse(URL) + "?etape=questionnaires")
        etape = etapes_by_code(response)["questionnaires"]
        assert etape["nbre"] == 1 and etape["complete"] is False
        bloc = etape["individus_forms"][0]
        assert bloc["individu"] == ratt[1].individu
        assert bloc["questions"][0] == q
        assert bloc["questions"][0].is_liste is False
        assert bloc["questions"][0].reponse is None

    def test_list_question_gets_choix_list(self, logged_client, dossier_complet):
        _u, famille, ratt = dossier_complet
        act = ActiviteFactory()
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        question(act, controle="liste_deroulante", choix="A;B;C")
        response = logged_client.get(reverse(URL) + "?etape=questionnaires")
        q = etapes_by_code(response)["questionnaires"]["individus_forms"][0][
            "questions"
        ][0]
        assert q.is_liste is True and q.choix_list == ["A", "B", "C"]

    def test_prefilled_blank_reponse(self, logged_client, dossier_complet):
        """A blank stored answer is still 'missing' but is used to prefill (reponse not None)."""
        _u, famille, ratt = dossier_complet
        act = ActiviteFactory()
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        q = question(act)
        QuestionnaireReponse.objects.create(
            question=q, individu=ratt[1].individu, reponse=""
        )
        response = logged_client.get(reverse(URL) + "?etape=questionnaires")
        bloc = etapes_by_code(response)["questionnaires"]["individus_forms"][0]
        assert bloc["questions"][0].reponse == ""

    def test_answered_question_not_listed(self, logged_client, dossier_complet):
        _u, famille, ratt = dossier_complet
        act = ActiviteFactory()
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        q = question(act)
        QuestionnaireReponse.objects.create(
            question=q, individu=ratt[1].individu, reponse="x"
        )
        response = logged_client.get(reverse(URL))
        etape = etapes_by_code(response)["questionnaires"]
        assert etape["nbre"] == 0 and etape["individus_forms"] == []


@pytest.mark.django_db
class TestEtapeSondages:
    def test_missing_survey_counted_and_redirect_step(
        self, logged_client, dossier_complet
    ):
        _u, famille, ratt = dossier_complet
        act = ActiviteFactory()
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        SondageFactory(public="famille", structure=act.structure)
        response = logged_client.get(reverse(URL))
        etape = etapes_by_code(response)["sondages"]
        assert (
            etape["type"] == "redirect"
            and etape["nbre"] == 1
            and etape["complete"] is False
        )
        assert etape["url"] == reverse("portail_sondages")
        assert response.context["etape_active"]["code"] == "sondages"


@pytest.mark.django_db
class TestEtapeCotisations:
    def test_step_absent_by_default(self, logged_client, dossier_complet):
        response = logged_client.get(reverse(URL))
        assert "cotisations" not in etapes_by_code(response)

    def test_step_present_when_parameter_enabled(
        self, logged_client, dossier_complet, set_parametre_portail
    ):
        set_parametre_portail("cotisations_afficher_page", True)
        response = logged_client.get(reverse(URL))
        codes = [e["code"] for e in response.context["etapes"]]
        assert codes == [
            "renseignements",
            "vaccinations",
            "pieces",
            "questionnaires",
            "sondages",
            "cotisations",
            "verifications",
        ]
        assert etapes_by_code(response)["cotisations"]["nbre"] == 0

    def test_missing_cotisation_counted(
        self, logged_client, dossier_complet, set_parametre_portail
    ):
        set_parametre_portail("cotisations_afficher_page", True)
        _u, famille, ratt = dossier_complet
        act = ActiviteFactory()
        tc = TypeCotisation.objects.create(nom="Adhésion", type="famille")
        act.cotisations.add(tc)
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        response = logged_client.get(reverse(URL))
        etape = etapes_by_code(response)["cotisations"]
        assert etape["nbre"] == 1 and etape["complete"] is False
        assert response.context["etape_active"]["code"] == "cotisations"


@pytest.fixture
def media_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


@pytest.mark.django_db
class TestEtapeVerifications:
    def test_inscription_needing_certification(
        self, logged_client, dossier_complet, media_tmp
    ):
        _u, famille, ratt = dossier_complet
        insc = InscriptionFactory(
            individu=ratt[1].individu, famille=famille, besoin_certification=True
        )
        # activite is "actif" by default; vaccins_obligatoires -> avoid missing vaccins (no TypeMaladie)
        response = logged_client.get(reverse(URL))
        etape = response.context["etape_active"]
        assert etape["code"] == "verifications"
        assert (
            etape["nbre"] == 1
            and etape["complete"] is False
            and etape["bloquee"] is False
        )
        item = etape["inscriptions_rattachements"][0]
        assert item["inscription"] == insc and item["rattachement"] == ratt[1]
        assert item["nom_fichier"].startswith("/media")
        assert item["nom_fichier"].endswith(".pdf")

    def test_pdf_not_generated_when_other_step_requested(
        self, logged_client, dossier_complet, media_tmp
    ):
        _u, famille, ratt = dossier_complet
        InscriptionFactory(
            individu=ratt[1].individu, famille=famille, besoin_certification=True
        )
        response = logged_client.get(reverse(URL) + "?etape=pieces")
        item = etapes_by_code(response)["verifications"]["inscriptions_rattachements"][
            0
        ]
        assert "nom_fichier" not in item

    def test_pdf_not_generated_when_blocked(
        self, logged_client, famille_user, media_tmp
    ):
        """Incomplete earlier step -> verification step is blocked and no PDF is generated."""
        _u, famille, ratt = famille_user
        InscriptionFactory(
            individu=ratt[1].individu, famille=famille, besoin_certification=True
        )
        response = logged_client.get(reverse(URL) + "?etape=verifications")
        etape = response.context["etape_active"]
        assert etape["code"] == "verifications" and etape["bloquee"] is True
        assert "nom_fichier" not in etape["inscriptions_rattachements"][0]

    def test_inactive_activity_not_verified(self, logged_client, dossier_complet):
        _u, famille, ratt = dossier_complet
        InscriptionFactory(
            individu=ratt[1].individu,
            famille=famille,
            besoin_certification=True,
            activite=ActiviteFactory(actif=False),
        )
        response = logged_client.get(reverse(URL))
        assert etapes_by_code(response)["verifications"]["nbre"] == 0

    def test_inscription_without_rattachement_skipped(
        self, logged_client, dossier_complet
    ):
        _u, famille, _ratt = dossier_complet
        orphelin = IndividuFactory()
        InscriptionFactory(
            individu=orphelin, famille=famille, besoin_certification=True
        )
        response = logged_client.get(reverse(URL))
        assert etapes_by_code(response)["verifications"]["nbre"] == 0

    def test_generer_pdf_error_branch(
        self, logged_client, dossier_complet, monkeypatch
    ):
        """If the PDF generator reports errors, the item gets nom_fichier=None."""
        _u, famille, ratt = dossier_complet

        class FakeImpression:
            erreurs = ["boom"]

            def __init__(self, *a, **kw):
                pass

        monkeypatch.setattr(
            completer_dossier.utils_impression_renseignements,
            "Impression",
            FakeImpression,
        )
        InscriptionFactory(
            individu=ratt[1].individu, famille=famille, besoin_certification=True
        )
        response = logged_client.get(reverse(URL))
        item = response.context["etape_active"]["inscriptions_rattachements"][0]
        assert item["nom_fichier"] is None


# ---------------------------------------------------------------------------
# POST actions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPostDispatch:
    def test_unknown_action_redirects_to_wizard(self, logged_client, dossier_complet):
        response = logged_client.post(reverse(URL), {"foo": "bar"})
        assert response.status_code == 302 and response.url == reverse(URL)

    def test_empty_post_redirects_to_wizard(self, logged_client, dossier_complet):
        response = logged_client.post(reverse(URL), {})
        assert response.status_code == 302 and response.url == reverse(URL)


@pytest.mark.django_db
class TestPostVerification:
    def test_validates_inscription_and_stamps_rattachement(
        self, logged_client, dossier_complet
    ):
        _u, famille, ratt = dossier_complet
        insc = InscriptionFactory(
            individu=ratt[1].individu, famille=famille, besoin_certification=True
        )
        response = logged_client.post(
            reverse(URL), {"type_action": "verification", "inscription_id": insc.pk}
        )
        assert response.status_code == 302
        assert response.url == reverse(URL) + "?etape=verifications"
        insc.refresh_from_db()
        assert insc.besoin_certification is False
        ratt[1].refresh_from_db()
        assert ratt[1].certification_date is not None
        msgs = [str(m) for m in response.wsgi_request._messages]
        assert any("Vérification validée" in m for m in msgs)

    def test_unknown_inscription_is_noop(self, logged_client, dossier_complet):
        response = logged_client.post(
            reverse(URL), {"type_action": "verification", "inscription_id": 999999}
        )
        assert response.status_code == 302 and response.url.endswith(
            "?etape=verifications"
        )

    def test_missing_inscription_id_is_noop(self, logged_client, dossier_complet):
        response = logged_client.post(reverse(URL), {"type_action": "verification"})
        assert response.status_code == 302 and response.url.endswith(
            "?etape=verifications"
        )

    def test_inscription_without_rattachement(self, logged_client, dossier_complet):
        _u, famille, _ratt = dossier_complet
        orphelin = IndividuFactory()
        insc = InscriptionFactory(
            individu=orphelin, famille=famille, besoin_certification=True
        )
        response = logged_client.post(
            reverse(URL), {"type_action": "verification", "inscription_id": insc.pk}
        )
        assert response.status_code == 302
        insc.refresh_from_db()
        assert insc.besoin_certification is False
        assert Rattachement.objects.filter(individu=orphelin).count() == 0


@pytest.mark.django_db
class TestPostQuestionnaire:
    def _post(self, client, individu, q, ctrl, valeur):
        data = {
            "type_action": "questionnaire",
            "individu_pk": individu.pk,
            "question_pk": q.pk,
            "question_ctrl": ctrl,
        }
        if valeur is not None:
            data["valeur"] = valeur
        return client.post(reverse(URL), data)

    def test_creates_text_answer(self, logged_client, dossier_complet):
        _u, _famille, ratt = dossier_complet
        act = ActiviteFactory()
        q = question(act)
        response = self._post(
            logged_client, ratt[1].individu, q, "ligne_texte", "bonjour"
        )
        assert response.status_code == 302 and response.url.endswith(
            "?etape=questionnaires"
        )
        assert (
            QuestionnaireReponse.objects.get(
                question=q, individu=ratt[1].individu
            ).reponse
            == "bonjour"
        )

    def test_updates_existing_answer(self, logged_client, dossier_complet):
        _u, _famille, ratt = dossier_complet
        q = question(ActiviteFactory())
        QuestionnaireReponse.objects.create(
            question=q, individu=ratt[1].individu, reponse="old"
        )
        self._post(logged_client, ratt[1].individu, q, "ligne_texte", "new")
        assert (
            QuestionnaireReponse.objects.filter(
                question=q, individu=ratt[1].individu
            ).count()
            == 1
        )
        assert (
            QuestionnaireReponse.objects.get(
                question=q, individu=ratt[1].individu
            ).reponse
            == "new"
        )

    @pytest.mark.parametrize("ctrl", ["liste_deroulante", "liste_coches"])
    def test_list_answer_gets_ras_appended(self, logged_client, dossier_complet, ctrl):
        _u, _f, ratt = dossier_complet
        q = question(ActiviteFactory(), controle=ctrl, choix="A;B")
        self._post(logged_client, ratt[1].individu, q, ctrl, "A; B ;")
        assert (
            QuestionnaireReponse.objects.get(
                question=q, individu=ratt[1].individu
            ).reponse
            == "A;B;RAS"
        )

    def test_list_answer_ras_not_duplicated(self, logged_client, dossier_complet):
        _u, _f, ratt = dossier_complet
        q = question(ActiviteFactory(), controle="liste_coches", choix="A")
        self._post(logged_client, ratt[1].individu, q, "liste_coches", "RAS;A")
        assert (
            QuestionnaireReponse.objects.get(
                question=q, individu=ratt[1].individu
            ).reponse
            == "RAS;A"
        )

    def test_list_answer_empty_value(self, logged_client, dossier_complet):
        _u, _f, ratt = dossier_complet
        q = question(ActiviteFactory(), controle="liste_deroulante", choix="A")
        self._post(logged_client, ratt[1].individu, q, "liste_deroulante", None)
        assert (
            QuestionnaireReponse.objects.get(
                question=q, individu=ratt[1].individu
            ).reponse
            == "RAS"
        )

    def test_cannot_answer_for_individual_of_other_family(
        self, logged_client, dossier_complet, other_famille
    ):
        _u, _f, ratt_b = other_famille
        q = question(ActiviteFactory())
        self._post(logged_client, ratt_b[1].individu, q, "ligne_texte", "pwned")
        assert not QuestionnaireReponse.objects.filter(
            question=q, individu=ratt_b[1].individu
        ).exists()


@pytest.fixture
def pdf_bytes():
    from io import BytesIO

    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(10, 10, "hello")
    c.save()
    return buf.getvalue()


@pytest.mark.django_db
class TestPostPiece:
    def _data(self, ratt, **extra):
        data = {
            "selection_piece": 9999,
            "titre": "Mon document",
            "choix_individu": ratt[1].individu_id,
            "document": SimpleUploadedFile(
                "doc.png", b"\x89PNG\r\n\x1a\nfake", content_type="image/png"
            ),
        }
        data.update(extra)
        return data

    def test_valid_piece_creates_piece_and_renseignement(
        self, logged_client, dossier_complet, media_tmp
    ):
        _u, famille, ratt = dossier_complet
        response = logged_client.post(reverse(URL), self._data(ratt))
        assert response.status_code == 302 and response.url.endswith("?etape=pieces")
        piece = Piece.objects.get(famille=famille, titre="Mon document")
        assert piece.individu == ratt[1].individu
        assert PortailRenseignement.objects.filter(
            famille=famille, categorie="famille_pieces", idobjet=piece.pk
        ).exists()
        msgs = [str(m) for m in response.wsgi_request._messages]
        assert any("ajoutées avec succès" in m for m in msgs)

    def test_extra_documents_create_extra_pieces(
        self, logged_client, dossier_complet, media_tmp
    ):
        _u, famille, ratt = dossier_complet
        data = self._data(
            ratt,
            document1=SimpleUploadedFile("d1.jpg", b"jpg1", content_type="image/jpeg"),
            document2=SimpleUploadedFile("d2.jpg", b"jpg2", content_type="image/jpeg"),
            document3=SimpleUploadedFile("d3.jpg", b"jpg3", content_type="image/jpeg"),
            document4=SimpleUploadedFile("d4.jpg", b"jpg4", content_type="image/jpeg"),
        )
        response = logged_client.post(reverse(URL), data)
        assert response.status_code == 302
        assert Piece.objects.filter(famille=famille, titre="Mon document").count() == 5

    def test_pdf_document_is_watermarked(
        self, logged_client, dossier_complet, media_tmp, pdf_bytes
    ):
        _u, famille, ratt = dossier_complet
        data = self._data(
            ratt,
            document=SimpleUploadedFile(
                "doc.pdf", pdf_bytes, content_type="application/pdf"
            ),
        )
        assert b"pypdf" not in pdf_bytes
        response = logged_client.post(reverse(URL), data)
        assert response.status_code == 302
        piece = Piece.objects.get(famille=famille, titre="Mon document")
        with open(piece.document.path, "rb") as f:
            assert b"pypdf" in f.read()  # file was rewritten by the watermark step

    def test_invalid_form_rerenders_with_errors(
        self, logged_client, dossier_complet, media_tmp
    ):
        _u, famille, ratt = dossier_complet
        data = self._data(ratt, titre="", choix_individu="")
        response = logged_client.post(reverse(URL), data)
        assert response.status_code == 200
        assert response.context["form_piece"].errors
        assert (
            response.context["etape_active"]["code"] == "pieces"
            or "form_piece" in response.context
        )
        assert not Piece.objects.filter(famille=famille).exists()

    def test_wrong_extension_rejected(self, logged_client, dossier_complet, media_tmp):
        _u, famille, ratt = dossier_complet
        data = self._data(
            ratt,
            document=SimpleUploadedFile(
                "evil.exe", b"MZ", content_type="application/octet-stream"
            ),
        )
        response = logged_client.post(reverse(URL), data)
        assert response.status_code == 200
        assert "document" in response.context["form_piece"].errors
        assert not Piece.objects.filter(famille=famille).exists()
