"""Tests for portail.views.questionnaires.View (missing questionnaire answers page)."""

import datetime

import pytest
from core.models import QuestionnaireQuestion, QuestionnaireReponse
from django.urls import reverse
from portail.views.questionnaires import View
from tests.unit.factories import ActiviteFactory, InscriptionFactory

URL = "portail_questionnaires"


def question(activite, **kw):
    kw.setdefault("categorie", "individu")
    kw.setdefault("ordre", 1)
    kw.setdefault("label", "Q")
    kw.setdefault("controle", "ligne_texte")
    kw.setdefault("structure", activite.structure)
    return QuestionnaireQuestion.objects.create(activite=activite, **kw)


@pytest.fixture
def enfant_inscrit(famille_user):
    _u, famille, ratt = famille_user
    act = ActiviteFactory()
    InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
    return ratt[1].individu, act


@pytest.mark.django_db
class TestAuthorization:
    def test_anonymous_get(self, client):
        response = client.get(reverse(URL))
        assert response.status_code == 302 and "connexion" in response.url

    def test_anonymous_post(self, client):
        response = client.post(reverse(URL), {"individu_pk": 1})
        assert response.status_code == 302 and "connexion" in response.url

    def test_staff_denied(self, client, staff_user):
        client.force_login(staff_user)
        assert client.get(reverse(URL)).status_code in (302, 403)


@pytest.mark.django_db
class TestGet:
    def test_empty_when_no_questions(self, logged_client, famille_user):
        response = logged_client.get(reverse(URL))
        assert response.status_code == 200
        assert response.context["individus_forms"] == []
        assert (
            response.context["page_titre"] == "Réponses manquantes aux questionnaires"
        )

    def test_unanswered_question_without_prefill(self, logged_client, enfant_inscrit):
        enfant, act = enfant_inscrit
        q = question(act)
        response = logged_client.get(reverse(URL))
        forms = response.context["individus_forms"]
        assert len(forms) == 1 and forms[0]["individu"] == enfant
        assert forms[0]["questions"] == [q]
        assert (
            forms[0]["questions"][0].reponse is None
            and forms[0]["questions"][0].is_liste is False
        )

    def test_list_question_choices_split(self, logged_client, enfant_inscrit):
        _enfant, act = enfant_inscrit
        question(act, controle="liste_coches", choix="Oui;Non")
        response = logged_client.get(reverse(URL))
        q = response.context["individus_forms"][0]["questions"][0]
        assert q.is_liste is True and q.choix_list == ["Oui", "Non"]

    def test_prefill_with_blank_existing_answer(self, logged_client, enfant_inscrit):
        enfant, act = enfant_inscrit
        q = question(act)
        QuestionnaireReponse.objects.create(question=q, individu=enfant, reponse="")
        response = logged_client.get(reverse(URL))
        assert response.context["individus_forms"][0]["questions"][0].reponse == ""

    def test_answered_questions_are_hidden(self, logged_client, enfant_inscrit):
        enfant, act = enfant_inscrit
        q = question(act)
        QuestionnaireReponse.objects.create(question=q, individu=enfant, reponse="rep")
        response = logged_client.get(reverse(URL))
        assert response.context["individus_forms"] == []

    def test_other_family_questions_not_shown(
        self, logged_client, famille_user, other_famille
    ):
        _u, _fb, ratt_b = other_famille
        act = ActiviteFactory()
        InscriptionFactory(individu=ratt_b[1].individu, famille=_fb, activite=act)
        question(act)
        response = logged_client.get(reverse(URL))
        assert response.context["individus_forms"] == []


@pytest.mark.django_db
class TestPost:
    def post(self, client, individu, q, ctrl=None, valeur=None):
        data = {"individu_pk": individu.pk, "question_pk": q.pk}
        if ctrl is not None:
            data["question_ctrl"] = ctrl
        if valeur is not None:
            data["valeur"] = valeur
        return client.post(reverse(URL), data)

    def test_creates_answer_and_redirects(self, logged_client, enfant_inscrit):
        enfant, act = enfant_inscrit
        q = question(act)
        response = self.post(logged_client, enfant, q, "ligne_texte", "salut")
        assert response.status_code == 302 and response.url == reverse(URL)
        assert (
            QuestionnaireReponse.objects.get(question=q, individu=enfant).reponse
            == "salut"
        )

    def test_updates_existing_answer(self, logged_client, enfant_inscrit):
        enfant, act = enfant_inscrit
        q = question(act)
        QuestionnaireReponse.objects.create(question=q, individu=enfant, reponse="old")
        self.post(logged_client, enfant, q, "ligne_texte", "new")
        assert (
            QuestionnaireReponse.objects.filter(question=q, individu=enfant).count()
            == 1
        )
        assert (
            QuestionnaireReponse.objects.get(question=q, individu=enfant).reponse
            == "new"
        )

    @pytest.mark.parametrize("ctrl", ["liste_deroulante", "liste_coches"])
    def test_list_adds_ras(self, logged_client, enfant_inscrit, ctrl):
        enfant, act = enfant_inscrit
        q = question(act, controle=ctrl, choix="A;B")
        self.post(logged_client, enfant, q, ctrl, "A;B")
        assert (
            QuestionnaireReponse.objects.get(question=q, individu=enfant).reponse
            == "A;B;RAS"
        )

    def test_list_keeps_existing_ras(self, logged_client, enfant_inscrit):
        enfant, act = enfant_inscrit
        q = question(act, controle="liste_coches", choix="A")
        self.post(logged_client, enfant, q, "liste_coches", "RAS")
        assert (
            QuestionnaireReponse.objects.get(question=q, individu=enfant).reponse
            == "RAS"
        )

    def test_list_without_value(self, logged_client, enfant_inscrit):
        enfant, act = enfant_inscrit
        q = question(act, controle="liste_deroulante", choix="A")
        self.post(logged_client, enfant, q, "liste_deroulante")
        assert (
            QuestionnaireReponse.objects.get(question=q, individu=enfant).reponse
            == "RAS"
        )

    def test_oui_non_stored_verbatim(self, logged_client, enfant_inscrit):
        enfant, act = enfant_inscrit
        q = question(act, controle="liste_coches_ouinon")
        self.post(logged_client, enfant, q, "liste_coches_ouinon", "Oui;Non")
        assert (
            QuestionnaireReponse.objects.get(question=q, individu=enfant).reponse
            == "Oui;Non"
        )

    def test_other_control_stored_verbatim(self, logged_client, enfant_inscrit):
        enfant, act = enfant_inscrit
        q = question(act, controle="entier")
        self.post(logged_client, enfant, q, "entier", "42")
        assert (
            QuestionnaireReponse.objects.get(question=q, individu=enfant).reponse
            == "42"
        )

    def test_cannot_answer_for_other_family(
        self, logged_client, famille_user, other_famille
    ):
        _u, _fam_b, ratt_b = other_famille
        act = ActiviteFactory()
        q = question(act)
        self.post(logged_client, ratt_b[1].individu, q, "ligne_texte", "pwned")
        assert not QuestionnaireReponse.objects.filter(
            question=q, individu=ratt_b[1].individu
        ).exists()


@pytest.mark.django_db
class TestCleanQuestionnaire:
    """View.clean_questionnaire is a helper that normalises a raw value per control type."""

    def clean(self, controle, valeur):
        q = QuestionnaireQuestion(controle=controle)
        return View().clean_questionnaire(q, valeur)

    @pytest.mark.parametrize(
        "ctrl", ["ligne_texte", "bloc_texte", "codebarres", "couleur"]
    )
    def test_text_controls(self, ctrl):
        assert self.clean(ctrl, "abc") == "abc"
        assert self.clean(ctrl, None) == ""

    @pytest.mark.parametrize("ctrl", ["entier", "slider"])
    def test_integer_controls(self, ctrl):
        assert self.clean(ctrl, "12") == 12
        assert self.clean(ctrl, "abc") is None
        assert self.clean(ctrl, None) is None

    @pytest.mark.parametrize("ctrl", ["decimal", "montant"])
    def test_decimal_controls(self, ctrl):
        assert self.clean(ctrl, "1.5") == 1.5
        assert self.clean(ctrl, "x") is None
        assert self.clean(ctrl, None) is None

    def test_checkbox(self):
        assert self.clean("case_coche", "on") is True
        assert self.clean("case_coche", None) is False

    @pytest.mark.parametrize("ctrl", ["liste_deroulante", "liste_coches"])
    def test_lists(self, ctrl):
        assert self.clean(ctrl, "A; B") == "A;B;RAS"
        assert self.clean(ctrl, "A;RAS") == "A;RAS"
        assert self.clean(ctrl, None) == "RAS"

    def test_oui_non(self):
        assert self.clean("liste_coches_ouinon", "Oui") == "Oui"

    def test_date(self):
        assert self.clean("date", "2020-05-17") == datetime.date(2020, 5, 17)
        assert self.clean("date", "17/05/2020") is None
        assert self.clean("date", "") is None
        assert self.clean("date", None) is None

    def test_unknown_control_passthrough(self):
        assert self.clean("inconnu", "val") == "val"
