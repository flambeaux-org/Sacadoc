"""Tests for the survey (sondage) flow: intro -> questions -> conclusion."""

import pytest
from django.urls import reverse

from core.models import (
    SondagePage,
    SondageQuestion,
    SondageRepondant,
    SondageReponse,
)
from tests.unit.factories import SondageFactory


@pytest.fixture
def sondage_famille(db):
    """A family survey with one page and one free-text question."""
    sondage = SondageFactory(public="famille", conclusion="Merci !")
    page = SondagePage.objects.create(sondage=sondage, titre="Page 1", ordre=1)
    question = SondageQuestion.objects.create(
        page=page, label="Votre avis ?", controle="ligne_texte", ordre=1
    )
    return sondage, page, question


@pytest.mark.django_db
class TestSondageFlow:
    def test_introduction_renders(self, logged_client, sondage_famille):
        sondage, _page, _q = sondage_famille
        url = reverse("portail_sondage", kwargs={"code": sondage.code})
        response = logged_client.get(url)
        assert response.status_code == 200
        assert response.context["sondage"].pk == sondage.pk

    def test_questions_render(self, logged_client, sondage_famille):
        sondage, _page, _q = sondage_famille
        url = reverse("portail_sondage_questions", kwargs={"code": sondage.code})
        response = logged_client.get(url)
        assert response.status_code == 200
        assert len(response.context["pages"]) == 1

    def test_conclusion_renders(self, logged_client, sondage_famille):
        sondage, _page, _q = sondage_famille
        url = reverse("portail_sondage_conclusion", kwargs={"code": sondage.code})
        response = logged_client.get(url)
        assert response.status_code == 200

    def test_post_answers_creates_repondant_and_response(
        self, logged_client, famille_user, sondage_famille
    ):
        _user, famille, _ratt = famille_user
        sondage, _page, question = sondage_famille
        url = reverse("portail_sondage_questions", kwargs={"code": sondage.code})
        response = logged_client.post(url, {"question_%d" % question.pk: "Très bien"})
        assert response.status_code == 302
        repondant = SondageRepondant.objects.get(sondage=sondage, famille=famille)
        assert SondageReponse.objects.filter(
            repondant=repondant, question=question, reponse="Très bien"
        ).exists()
