# ruff: noqa: UP031
"""Remaining branches of the survey (sondage) views and of the survey form."""

import decimal

import pytest
from core.models import (
    SondagePage,
    SondageQuestion,
    SondageRepondant,
    SondageReponse,
)
from django.urls import reverse
from portail.forms.sondage import Formulaire
from tests.unit.factories import (
    ActiviteFactory,
    InscriptionFactory,
    SondageFactory,
)


def add_page(sondage, ordre=1, titre=None):
    return SondagePage.objects.create(
        sondage=sondage, titre=titre or "Page %d" % ordre, ordre=ordre
    )


def add_q(page, controle="ligne_texte", ordre=1, choix=None, **kw):
    return SondageQuestion.objects.create(
        page=page,
        label=f"Q {controle}",
        controle=controle,
        ordre=ordre,
        choix=choix,
        **kw,
    )


@pytest.fixture
def enfant_inscrit(famille_user):
    """Child enrolled in an activity of a fresh structure."""
    _u, famille, ratt = famille_user
    act = ActiviteFactory()
    InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
    return famille, ratt, act


# ---------------------------------------------------------------------------
# Liste
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestListe:
    url = "portail_sondages"

    def test_anonymous(self, client):
        response = client.get(reverse(self.url))
        assert response.status_code == 302 and "connexion" in response.url

    def test_staff_denied(self, client, staff_user):
        client.force_login(staff_user)
        assert client.get(reverse(self.url)).status_code in (302, 403)

    def test_empty(self, logged_client, famille_user):
        ctx = logged_client.get(reverse(self.url)).context
        assert ctx["sondages_famille"] == [] and ctx["sondages_individu"] == []

    def test_famille_survey_listed(self, logged_client, enfant_inscrit):
        _f, _r, act = enfant_inscrit
        s = SondageFactory(public="famille", structure=act.structure)
        ctx = logged_client.get(reverse(self.url)).context
        assert [i["sondage"] for i in ctx["sondages_famille"]] == [s]
        assert ctx["sondages_individu"] == []

    def test_individu_survey_grouped_by_code(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        act = ActiviteFactory()
        # adult and child both enrolled and eligible -> a single entry with two individus
        InscriptionFactory(individu=ratt[0].individu, famille=famille, activite=act)
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        s = SondageFactory(
            public="individu",
            structure=act.structure,
            categories_rattachements=["1", "2"],
        )
        ctx = logged_client.get(reverse(self.url)).context
        assert ctx["sondages_famille"] == []
        assert len(ctx["sondages_individu"]) == 1
        entry = ctx["sondages_individu"][0]
        assert (
            entry["sondage"] == s
            and str(entry["code"]) == str(s.code)
            and entry["titre"] == s.titre
        )
        assert entry["article"] is None
        assert set(entry["individus"]) == {ratt[0].individu, ratt[1].individu}

    def test_two_individu_surveys_two_entries(self, logged_client, enfant_inscrit):
        _f, _r, act = enfant_inscrit
        SondageFactory(
            public="individu", structure=act.structure, categories_rattachements=["2"]
        )
        SondageFactory(
            public="individu", structure=act.structure, categories_rattachements=["2"]
        )
        assert (
            len(logged_client.get(reverse(self.url)).context["sondages_individu"]) == 2
        )

    def test_answered_survey_not_listed(self, logged_client, enfant_inscrit):
        famille, _r, act = enfant_inscrit
        s = SondageFactory(public="famille", structure=act.structure)
        SondageRepondant.objects.create(sondage=s, famille=famille)
        assert logged_client.get(reverse(self.url)).context["sondages_famille"] == []


# ---------------------------------------------------------------------------
# Introduction / conclusion
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestIntroduction:
    def url(self, s):
        return reverse("portail_sondage", kwargs={"code": s.code})

    def test_anonymous(self, client):
        s = SondageFactory()
        assert client.get(self.url(s)).status_code == 302

    def test_famille_survey_lists_all_living_rattachements(
        self, logged_client, famille_user
    ):
        _u, _f, ratt = famille_user
        s = SondageFactory(public="famille")
        ctx = logged_client.get(self.url(s)).context
        assert {r.pk for r in ctx["rattachements"]} == {ratt[0].pk, ratt[1].pk}

    def test_individu_survey_filters_categories(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        s = SondageFactory(public="individu", categories_rattachements=["2"])
        ctx = logged_client.get(self.url(s)).context
        assert [r.pk for r in ctx["rattachements"]] == [ratt[1].pk]

    def test_existing_answers_attached_to_rattachement(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        s = SondageFactory(public="individu", categories_rattachements=["1", "2"])
        rep = SondageRepondant.objects.create(
            sondage=s, famille=famille, individu=ratt[1].individu
        )
        ctx = logged_client.get(self.url(s)).context
        by_pk = {r.pk: r for r in ctx["rattachements"]}
        assert by_pk[ratt[1].pk].repondant == rep
        assert not hasattr(by_pk[ratt[0].pk], "repondant")
        assert list(ctx["sondages_existants"]) == [rep]

    def test_deceased_hidden(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        enfant = ratt[1].individu
        enfant.deces = True
        enfant.save()
        s = SondageFactory(public="famille")
        assert [
            r.pk for r in logged_client.get(self.url(s)).context["rattachements"]
        ] == [ratt[0].pk]

    def test_other_family_answers_not_listed(
        self, logged_client, famille_user, other_famille
    ):
        _ub, fam_b, _ratt_b = other_famille
        s = SondageFactory(public="famille")
        SondageRepondant.objects.create(sondage=s, famille=fam_b)
        assert list(logged_client.get(self.url(s)).context["sondages_existants"]) == []

    @pytest.mark.xfail(
        reason="BUG: sondage views call Sondage.objects.get(code=...) without handling DoesNotExist: an unknown "
        "survey code returns a 500 instead of a 404.",
        strict=True,
    )
    def test_unknown_code_is_404(self, logged_client, famille_user):
        logged_client.raise_request_exception = False
        response = logged_client.get(
            reverse("portail_sondage", kwargs={"code": "does-not-exist"})
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestConclusion:
    def test_renders_with_titre(self, logged_client, famille_user):
        s = SondageFactory(conclusion="Merci")
        response = logged_client.get(
            reverse("portail_sondage_conclusion", kwargs={"code": s.code})
        )
        assert response.status_code == 200
        assert response.context["box_titre"] == s.titre

    def test_anonymous(self, client):
        s = SondageFactory()
        assert (
            client.get(
                reverse("portail_sondage_conclusion", kwargs={"code": s.code})
            ).status_code
            == 302
        )


# ---------------------------------------------------------------------------
# Questions (GET/POST)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestQuestionsGet:
    def test_anonymous(self, client):
        s = SondageFactory()
        assert (
            client.get(
                reverse("portail_sondage_questions", kwargs={"code": s.code})
            ).status_code
            == 302
        )

    def test_titre_includes_individu_first_name(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        s = SondageFactory(public="individu")
        add_page(s)
        url = reverse(
            "portail_sondage_questions",
            kwargs={"code": s.code, "idindividu": ratt[1].individu.pk},
        )
        ctx = logged_client.get(url).context
        assert ctx["box_titre"] == f"{s.titre} - {ratt[1].individu.prenom}"

    def test_existing_answers_prefilled(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        s = SondageFactory(public="individu")
        page = add_page(s)
        q = add_q(page)
        rep = SondageRepondant.objects.create(
            sondage=s, famille=famille, individu=ratt[1].individu
        )
        SondageReponse.objects.create(repondant=rep, question=q, reponse="déjà")
        url = reverse(
            "portail_sondage_questions",
            kwargs={"code": s.code, "idindividu": ratt[1].individu.pk},
        )
        ((_page, form),) = logged_client.get(url).context["pages"]
        assert form.fields["question_%d" % q.pk].initial == "déjà"

    def test_multiple_pages(self, logged_client, famille_user):
        s = SondageFactory()
        p1, p2 = add_page(s, 1), add_page(s, 2)
        add_q(p1)
        add_q(p2)
        pages = logged_client.get(
            reverse("portail_sondage_questions", kwargs={"code": s.code})
        ).context["pages"]
        assert [p.pk for p, _f in pages] == [p1.pk, p2.pk]
        assert all(len(f.fields) == 1 for _p, f in pages)


@pytest.mark.django_db
class TestQuestionsPost:
    def url(self, s, idindividu=None):
        kw = {"code": s.code}
        if idindividu:
            kw["idindividu"] = idindividu
        return reverse("portail_sondage_questions", kwargs=kw)

    def test_without_conclusion_redirects_to_accueil(self, logged_client, famille_user):
        s = SondageFactory(conclusion=None)
        q = add_q(add_page(s))
        response = logged_client.post(self.url(s), {"question_%d" % q.pk: "x"})
        assert response.status_code == 302 and response.url == reverse(
            "portail_accueil"
        )

    def test_with_conclusion_redirects_to_conclusion(self, logged_client, famille_user):
        s = SondageFactory(conclusion="Merci")
        q = add_q(add_page(s))
        response = logged_client.post(self.url(s), {"question_%d" % q.pk: "x"})
        assert response.url == reverse(
            "portail_sondage_conclusion", kwargs={"code": s.code}
        )

    def test_second_post_updates_same_repondant_and_response(
        self, logged_client, famille_user
    ):
        _u, famille, _r = famille_user
        s = SondageFactory()
        q = add_q(add_page(s))
        logged_client.post(self.url(s), {"question_%d" % q.pk: "v1"})
        rep = SondageRepondant.objects.get(sondage=s, famille=famille)
        assert rep.date_modification is None
        logged_client.post(self.url(s), {"question_%d" % q.pk: "v2"})
        rep.refresh_from_db()
        assert rep.date_modification is not None
        assert SondageRepondant.objects.filter(sondage=s, famille=famille).count() == 1
        assert SondageReponse.objects.get(repondant=rep, question=q).reponse == "v2"

    def test_individu_response_recorded_for_that_individu(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        s = SondageFactory(public="individu")
        q = add_q(add_page(s))
        logged_client.post(
            self.url(s, ratt[1].individu.pk), {"question_%d" % q.pk: "ok"}
        )
        assert SondageRepondant.objects.filter(
            sondage=s, famille=famille, individu=ratt[1].individu
        ).exists()

    def test_all_control_types_saved(self, logged_client, famille_user):
        _u, famille, _r = famille_user
        s = SondageFactory()
        page = add_page(s)
        qs = {
            "ligne_texte": add_q(page, "ligne_texte", 1),
            "bloc_texte": add_q(page, "bloc_texte", 2),
            "entier": add_q(page, "entier", 3),
            "decimal": add_q(page, "decimal", 4),
            "liste_deroulante": add_q(page, "liste_deroulante", 5, choix="A;B"),
            "liste_coches": add_q(page, "liste_coches", 6, choix="A;B"),
            "case_coche": add_q(page, "case_coche", 7),
            "date": add_q(page, "date", 8),
        }
        data = {
            "question_%d" % qs["ligne_texte"].pk: "t",
            "question_%d" % qs["bloc_texte"].pk: "b",
            "question_%d" % qs["entier"].pk: "4",
            "question_%d" % qs["decimal"].pk: "2.5",
            "question_%d" % qs["liste_deroulante"].pk: "A",
            "question_%d" % qs["liste_coches"].pk: ["A", "B"],
            "question_%d" % qs["case_coche"].pk: "on",
            "question_%d" % qs["date"].pk: "2021-02-03",
        }
        logged_client.post(self.url(s), data)
        rep = SondageRepondant.objects.get(sondage=s, famille=famille)
        got = {
            r.question.controle: r.reponse
            for r in SondageReponse.objects.filter(repondant=rep)
        }
        assert got["liste_coches"] == "A;B"
        assert (
            got["entier"] == "4"
            and got["case_coche"] == "True"
            and got["date"] == "2021-02-03"
        )
        assert got["decimal"] == "2.50" or got["decimal"] == "2.5"

    def test_multi_page_post_merges_values(self, logged_client, famille_user):
        _u, famille, _r = famille_user
        s = SondageFactory()
        q1, q2 = add_q(add_page(s, 1)), add_q(add_page(s, 2))
        logged_client.post(
            self.url(s), {"question_%d" % q1.pk: "a", "question_%d" % q2.pk: "b"}
        )
        rep = SondageRepondant.objects.get(sondage=s, famille=famille)
        assert SondageReponse.objects.filter(repondant=rep).count() == 2

    def test_invalid_form_branch_does_not_crash(self, logged_client, famille_user):
        """A bad integer makes the page form invalid (the 'Form pas valide' branch); the request still completes."""
        s = SondageFactory()
        q = add_q(add_page(s), "entier")
        response = logged_client.post(
            self.url(s), {"question_%d" % q.pk: "pas un nombre"}
        )
        assert response.status_code == 302

    @pytest.mark.xfail(
        reason="BUG: sondage.View_questions.post ignores form validity: a required question left empty (or an "
        "invalid value) is silently dropped and the survey is nonetheless recorded as answered (respondent created).",
        strict=True,
    )
    def test_required_question_blocks_submission(self, logged_client, famille_user):
        _u, famille, _r = famille_user
        s = SondageFactory()
        q = add_q(add_page(s), obligatoire=True)
        logged_client.post(self.url(s), {"question_%d" % q.pk: ""})
        assert not SondageRepondant.objects.filter(sondage=s, famille=famille).exists()

    @pytest.mark.xfail(
        reason="BUG: sondage.View_questions accepts any idindividu (Individu.objects.get(pk=...), no family check): "
        "a family can record survey answers for another family's individual.",
        strict=True,
    )
    def test_cannot_answer_for_other_family_individual(
        self, logged_client, famille_user, other_famille
    ):
        _ub, _fb, ratt_b = other_famille
        s = SondageFactory(public="individu")
        q = add_q(add_page(s))
        logged_client.post(
            self.url(s, ratt_b[1].individu.pk), {"question_%d" % q.pk: "x"}
        )
        assert not SondageRepondant.objects.filter(
            sondage=s, individu=ratt_b[1].individu
        ).exists()


# ---------------------------------------------------------------------------
# Formulaire (portail.forms.sondage)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFormulaire:
    def build(self, rf, user, page, questions, **kw):
        request = rf.get("/")
        request.user = user
        return Formulaire(request=request, page=page, questions=questions, **kw)

    def test_only_questions_of_the_page(self, rf, famille_user):
        user, _f, _r = famille_user
        s = SondageFactory()
        p1, p2 = add_page(s, 1), add_page(s, 2)
        q1, q2 = add_q(p1), add_q(p2)
        form = self.build(rf, user, p1, SondageQuestion.objects.filter(page__sondage=s))
        assert list(form.fields) == ["question_%d" % q1.pk]
        assert q2.pk not in [int(k.split("_")[1]) for k in form.fields]

    def test_unknown_control_skipped(self, rf, famille_user):
        user, _f, _r = famille_user
        s = SondageFactory()
        p = add_page(s)
        add_q(p, "inconnu")
        form = self.build(rf, user, p, SondageQuestion.objects.filter(page=p))
        assert form.fields == {}

    def test_required_flag(self, rf, famille_user):
        user, _f, _r = famille_user
        s = SondageFactory()
        p = add_page(s)
        q_req = add_q(p, ordre=1, obligatoire=True)
        q_opt = add_q(p, ordre=2)
        form = self.build(rf, user, p, SondageQuestion.objects.filter(page=p))
        assert form.fields["question_%d" % q_req.pk].required is True
        assert form.fields["question_%d" % q_opt.pk].required is False

    def test_lecture_seule_disables_fields(self, rf, famille_user):
        user, _f, _r = famille_user
        s = SondageFactory()
        p = add_page(s)
        q = add_q(p)
        form = self.build(
            rf, user, p, SondageQuestion.objects.filter(page=p), lecture_seule=True
        )
        assert form.fields["question_%d" % q.pk].disabled is True
        form2 = self.build(rf, user, p, SondageQuestion.objects.filter(page=p))
        assert form2.fields["question_%d" % q.pk].disabled is False

    def test_reponses_initial_by_type_and_unknown_question_ignored(
        self, rf, famille_user
    ):
        user, famille, _r = famille_user
        s = SondageFactory()
        p1, p2 = add_page(s, 1), add_page(s, 2)
        q_int = add_q(p1, "entier", 1)
        q_list = add_q(p1, "liste_coches", 2, choix="A;B")
        q_dec = add_q(p1, "decimal", 3)
        q_other_page = add_q(p2, "ligne_texte", 4)
        rep = SondageRepondant.objects.create(sondage=s, famille=famille)
        SondageReponse.objects.create(repondant=rep, question=q_int, reponse="9")
        SondageReponse.objects.create(repondant=rep, question=q_list, reponse="A;B")
        SondageReponse.objects.create(repondant=rep, question=q_dec, reponse="1.5")
        SondageReponse.objects.create(
            repondant=rep, question=q_other_page, reponse="zzz"
        )
        reponses = SondageReponse.objects.select_related("question").filter(
            repondant=rep
        )
        form = self.build(
            rf,
            user,
            p1,
            SondageQuestion.objects.filter(page__sondage=s),
            reponses=reponses,
        )
        assert form.fields["question_%d" % q_int.pk].initial == 9
        assert form.fields["question_%d" % q_list.pk].initial == ["A", "B"]
        assert form.fields["question_%d" % q_dec.pk].initial == decimal.Decimal("1.5")
        assert "question_%d" % q_other_page.pk not in form.fields

    def test_clean_joins_lists_only(self, rf, famille_user):
        user, _f, _r = famille_user
        s = SondageFactory()
        p = add_page(s)
        q_list = add_q(p, "liste_coches", 1, choix="A;B")
        q_txt = add_q(p, "ligne_texte", 2)
        request = rf.post("/")
        request.user = user
        form = Formulaire(
            {"question_%d" % q_list.pk: ["A", "B"], "question_%d" % q_txt.pk: "t"},
            request=request,
            page=p,
            questions=SondageQuestion.objects.filter(page=p),
        )
        assert form.is_valid()
        assert form.cleaned_data["question_%d" % q_list.pk] == "A;B"
        assert form.cleaned_data["question_%d" % q_txt.pk] == "t"

    def test_clean_ignores_non_question_keys(self, rf, famille_user):
        user, _f, _r = famille_user
        s = SondageFactory()
        p = add_page(s)
        form = self.build(rf, user, p, SondageQuestion.objects.filter(page=p))
        form.cleaned_data = {"autre": ["x"]}
        assert form.clean() == {"autre": ["x"]}
