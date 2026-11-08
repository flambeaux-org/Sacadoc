# ruff: noqa: UP031
"""Questionnaire fiches (famille + individu): form building for every control type,
consult/edit views, direct save vs. pending validation, and authorization."""

import decimal
import json

import pytest
from core.models import (
    PortailRenseignement,
    QuestionnaireQuestion,
    QuestionnaireReponse,
)
from django.urls import reverse
from tests.unit.factories import ActiviteFactory, InscriptionFactory

CONTROLES = [
    ("ligne_texte", None),
    ("bloc_texte", None),
    ("entier", None),
    ("decimal", None),
    ("montant", None),
    ("liste_deroulante", "A;B"),
    ("liste_coches", "A;B"),
    ("liste_coches_ouinon", None),
    ("case_coche", None),
    ("date", None),
    ("slider", None),
    ("couleur", None),
    ("codebarres", None),
]


def make_q(
    structure,
    activite=None,
    categorie="famille",
    controle="ligne_texte",
    choix=None,
    ordre=1,
    **kw,
):
    return QuestionnaireQuestion.objects.create(
        structure=structure,
        activite=activite,
        categorie=categorie,
        controle=controle,
        choix=choix,
        label=f"Question {controle}",
        ordre=ordre,
        **kw,
    )


@pytest.fixture
def structure(db):
    from tests.unit.factories import StructureFactory

    return StructureFactory()


@pytest.fixture
def pending_onglets(set_parametre_portail):
    """Make the questionnaire onglets require admin validation (validation_auto=False)."""
    for code in ("famille_questionnaire", "individu_questionnaire"):
        set_parametre_portail(f"validation_auto:{code}", False)


# ---------------------------------------------------------------------------
# Famille questionnaire
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestFamilleQuestionnaire:
    url = "portail_famille_questionnaire"
    url_mod = "portail_famille_questionnaire_modifier"

    def test_anonymous_redirected(self, client):
        for name in (self.url, self.url_mod):
            response = client.get(reverse(name))
            assert response.status_code == 302 and "connexion" in response.url

    def test_staff_denied(self, client, staff_user):
        client.force_login(staff_user)
        assert client.get(reverse(self.url)).status_code in (302, 403)

    def test_no_question_message(self, logged_client, famille_user):
        response = logged_client.get(reverse(self.url))
        assert response.status_code == 200
        assert not response.context["form"].fields
        assert "Aucun questionnaire" in response.content.decode()

    @pytest.mark.parametrize("controle,choix", CONTROLES)
    def test_every_control_type_renders_consult_and_edit(
        self, logged_client, famille_user, structure, controle, choix
    ):
        q = make_q(structure, controle=controle, choix=choix)
        for name in (self.url, self.url_mod):
            response = logged_client.get(reverse(name))
            assert response.status_code == 200
            assert "question_%d" % q.pk in response.context["form"].fields

    def test_unknown_control_has_no_field(self, logged_client, famille_user, structure):
        q = make_q(structure, controle="inconnu")
        response = logged_client.get(reverse(self.url))
        assert "question_%d" % q.pk not in response.context["form"].fields

    def test_consult_mode_fields_disabled_with_edit_button(
        self, logged_client, famille_user, structure
    ):
        q = make_q(structure)
        response = logged_client.get(reverse(self.url))
        assert response.context["form"].fields["question_%d" % q.pk].disabled is True
        assert "Modifier cette page" in response.content.decode()

    def test_edit_mode_fields_enabled_with_save_button(
        self, logged_client, famille_user, structure
    ):
        q = make_q(structure)
        response = logged_client.get(reverse(self.url_mod))
        assert response.context["form"].fields["question_%d" % q.pk].disabled is False
        assert "Enregistrer les modifications" in response.content.decode()
        assert (
            "validées par l'administrateur" not in response.context["box_introduction"]
        )

    def test_non_portail_and_other_category_questions_ignored(
        self, logged_client, famille_user, structure
    ):
        make_q(structure, visible_portail=False)
        make_q(structure, categorie="individu", ordre=2)
        response = logged_client.get(reverse(self.url))
        assert not response.context["form"].fields

    def test_existing_answers_prefill(self, logged_client, famille_user, structure):
        _u, famille, _r = famille_user
        qs = {
            c: make_q(structure, controle=c, choix=ch, ordre=i)
            for i, (c, ch) in enumerate(CONTROLES[:10])
        }
        values = {
            "ligne_texte": "txt",
            "bloc_texte": "bloc",
            "entier": "7",
            "decimal": "1.50",
            "montant": "2.00",
            "liste_deroulante": "A",
            "liste_coches": "A;B",
            "liste_coches_ouinon": "Oui",
            "case_coche": "True",
            "date": "2020-01-02",
        }
        for c, q in qs.items():
            QuestionnaireReponse.objects.create(
                question=q, famille=famille, reponse=values[c]
            )
        form = logged_client.get(reverse(self.url)).context["form"]
        assert form.fields["question_%d" % qs["entier"].pk].initial == 7
        assert form.fields["question_%d" % qs["case_coche"].pk].initial is True
        assert form.fields["question_%d" % qs["liste_coches"].pk].initial == ["A", "B"]
        assert form.fields["question_%d" % qs["decimal"].pk].initial == decimal.Decimal(
            "1.50"
        )
        assert form.fields["question_%d" % qs["ligne_texte"].pk].initial == "txt"

    def test_other_family_answers_not_loaded(
        self, logged_client, famille_user, other_famille, structure
    ):
        _ub, fam_b, _rb = other_famille
        q = make_q(structure)
        QuestionnaireReponse.objects.create(question=q, famille=fam_b, reponse="secret")
        form = logged_client.get(reverse(self.url)).context["form"]
        assert form.fields["question_%d" % q.pk].initial is None

    def test_post_saves_all_types_directly(
        self, logged_client, famille_user, structure
    ):
        _u, famille, _r = famille_user
        qs = {
            c: make_q(structure, controle=c, choix=ch, ordre=i)
            for i, (c, ch) in enumerate(CONTROLES[:10])
        }
        data = {
            "question_%d" % qs["ligne_texte"].pk: "hello",
            "question_%d" % qs["bloc_texte"].pk: "long\ntext",
            "question_%d" % qs["entier"].pk: "5",
            "question_%d" % qs["decimal"].pk: "3.25",
            "question_%d" % qs["montant"].pk: "9",
            "question_%d" % qs["liste_deroulante"].pk: "B",
            "question_%d" % qs["liste_coches"].pk: ["A", "B"],
            "question_%d" % qs["liste_coches_ouinon"].pk: ["Oui", "Non"],
            "question_%d" % qs["case_coche"].pk: "on",
            "question_%d" % qs["date"].pk: "2020-03-04",
        }
        response = logged_client.post(reverse(self.url_mod), data)
        assert response.status_code == 302 and response.url == reverse(self.url)
        rep = {
            r.question.controle: r.reponse
            for r in QuestionnaireReponse.objects.filter(famille=famille)
        }
        assert rep["ligne_texte"] == "hello"
        assert rep["entier"] == "5"
        assert rep["liste_coches"] == "A;B"
        assert rep["liste_coches_ouinon"] == "Oui;Non"
        assert rep["case_coche"] == "True"
        assert rep["date"] == "2020-03-04"
        assert rep["liste_deroulante"] == "B"
        assert not PortailRenseignement.objects.filter(
            famille=famille,
            categorie="famille_questionnaire",
            etat="ATTENTE",
            validation_auto=False,
        ).exists()
        assert PortailRenseignement.objects.filter(
            famille=famille, categorie="famille_questionnaire", validation_auto=True
        ).exists()

    def test_post_without_change_is_noop(self, logged_client, famille_user, structure):
        _u, famille, _r = famille_user
        make_q(structure)
        response = logged_client.post(reverse(self.url_mod), {})
        assert response.status_code == 302
        assert not QuestionnaireReponse.objects.filter(famille=famille).exists()

    def test_post_updates_existing_answer(self, logged_client, famille_user, structure):
        _u, famille, _r = famille_user
        q = make_q(structure)
        QuestionnaireReponse.objects.create(question=q, famille=famille, reponse="old")
        logged_client.post(reverse(self.url_mod), {"question_%d" % q.pk: "new"})
        assert (
            QuestionnaireReponse.objects.get(question=q, famille=famille).reponse
            == "new"
        )

    def test_pending_validation_mode_does_not_save_and_shows_notice(
        self, logged_client, famille_user, structure, pending_onglets
    ):
        _u, famille, _r = famille_user
        q = make_q(structure)
        response = logged_client.get(reverse(self.url_mod))
        assert "validées par l'administrateur" in response.context["box_introduction"]
        logged_client.post(reverse(self.url_mod), {"question_%d" % q.pk: "proposed"})
        assert not QuestionnaireReponse.objects.filter(famille=famille).exists()
        renseignement = PortailRenseignement.objects.get(
            famille=famille,
            categorie="famille_questionnaire",
            code="question_%d" % q.pk,
        )
        assert json.loads(renseignement.nouvelle_valeur) == "proposed"
        assert renseignement.validation_auto is False

    def test_pending_value_displayed_with_warning(
        self, logged_client, famille_user, structure, pending_onglets
    ):
        _u, famille, _r = famille_user
        q = make_q(structure)
        QuestionnaireReponse.objects.create(
            question=q, famille=famille, reponse="current"
        )
        PortailRenseignement.objects.create(
            famille=famille,
            categorie="famille_questionnaire",
            code="question_%d" % q.pk,
            nouvelle_valeur=json.dumps("proposed"),
            validation_auto=False,
            etat="ATTENTE",
        )
        field = (
            logged_client.get(reverse(self.url))
            .context["form"]
            .fields["question_%d" % q.pk]
        )
        assert field.initial == "proposed"
        assert "en attente de validation" in str(field.help_text).lower()

    def test_pending_equal_to_current_has_no_warning(
        self, logged_client, famille_user, structure
    ):
        _u, famille, _r = famille_user
        q = make_q(structure)
        QuestionnaireReponse.objects.create(question=q, famille=famille, reponse="same")
        PortailRenseignement.objects.create(
            famille=famille,
            categorie="famille_questionnaire",
            code="question_%d" % q.pk,
            nouvelle_valeur=json.dumps("same"),
            validation_auto=False,
            etat="ATTENTE",
        )
        field = (
            logged_client.get(reverse(self.url_mod))
            .context["form"]
            .fields["question_%d" % q.pk]
        )
        assert "attente" not in str(field.help_text or "")


# ---------------------------------------------------------------------------
# Individu questionnaire
# ---------------------------------------------------------------------------


@pytest.fixture
def enfant_ctx(famille_user):
    _u, famille, ratt = famille_user
    act = ActiviteFactory()
    InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
    return famille, ratt[1], act


@pytest.mark.django_db
class TestIndividuQuestionnaire:
    def u(self, ratt, edit=False):
        name = (
            "portail_individu_questionnaire_modifier"
            if edit
            else "portail_individu_questionnaire"
        )
        return reverse(name, kwargs={"idrattachement": ratt.pk})

    def test_anonymous_redirected(self, client, famille_user):
        _u, _f, ratt = famille_user
        for edit in (False, True):
            response = client.get(self.u(ratt[1], edit))
            assert response.status_code == 302 and "connexion" in response.url

    def test_cross_family_denied(self, logged_client, famille_user, other_famille):
        _u, _f, ratt_b = other_famille
        for edit in (False, True):
            assert logged_client.get(self.u(ratt_b[1], edit)).status_code in (
                302,
                403,
                404,
            )

    def test_no_question_message(self, logged_client, famille_user):
        _u, _f, ratt = famille_user
        response = logged_client.get(self.u(ratt[1]))
        assert response.status_code == 200
        assert not response.context["form"].fields
        assert "Aucun questionnaire" in response.content.decode()

    @pytest.mark.parametrize("controle,choix", CONTROLES)
    def test_every_control_type(self, logged_client, enfant_ctx, controle, choix):
        _f, ratt, act = enfant_ctx
        q = make_q(
            act.structure,
            activite=act,
            categorie="individu",
            controle=controle,
            choix=choix,
        )
        for edit in (False, True):
            response = logged_client.get(self.u(ratt, edit))
            assert response.status_code == 200
            assert "question_%d" % q.pk in response.context["form"].fields

    def test_unknown_control_has_no_field(self, logged_client, enfant_ctx):
        _f, ratt, act = enfant_ctx
        q = make_q(
            act.structure, activite=act, categorie="individu", controle="inconnu"
        )
        assert (
            "question_%d" % q.pk
            not in logged_client.get(self.u(ratt)).context["form"].fields
        )

    def test_only_questions_of_enrolled_visible_activities(
        self, logged_client, enfant_ctx
    ):
        _f, ratt, act = enfant_ctx
        q_ok = make_q(act.structure, activite=act, categorie="individu")
        other = ActiviteFactory()
        q_other = make_q(other.structure, activite=other, categorie="individu", ordre=2)
        q_hidden = make_q(
            act.structure,
            activite=act,
            categorie="individu",
            ordre=3,
            visible_portail=False,
        )
        fields = logged_client.get(self.u(ratt)).context["form"].fields
        assert "question_%d" % q_ok.pk in fields
        assert "question_%d" % q_other.pk not in fields
        assert "question_%d" % q_hidden.pk not in fields

    def test_general_question_for_status_outside_known_with_internal_activity(
        self, logged_client, famille_user
    ):
        """statut not in 0..4 and an internal activity -> questions without activity are included."""
        _u, famille, ratt = famille_user
        act = ActiviteFactory(interne=True)
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        ind = ratt[1].individu
        ind.statut = 9
        ind.save()
        q_general = make_q(act.structure, activite=None, categorie="individu")
        fields = logged_client.get(self.u(ratt[1])).context["form"].fields
        assert "question_%d" % q_general.pk in fields

    def test_general_question_excluded_for_known_status(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        act = ActiviteFactory(interne=True)
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        q_general = make_q(act.structure, activite=None, categorie="individu")
        fields = logged_client.get(self.u(ratt[1])).context["form"].fields
        assert "question_%d" % q_general.pk not in fields

    def test_general_question_excluded_without_internal_activity(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        act = ActiviteFactory(interne=False)
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        ind = ratt[1].individu
        ind.statut = 9
        ind.save()
        q_general = make_q(act.structure, activite=None, categorie="individu")
        fields = logged_client.get(self.u(ratt[1])).context["form"].fields
        assert "question_%d" % q_general.pk not in fields

    def test_prefill_and_modes(self, logged_client, enfant_ctx):
        _f, ratt, act = enfant_ctx
        q = make_q(act.structure, activite=act, categorie="individu", controle="entier")
        QuestionnaireReponse.objects.create(
            question=q, individu=ratt.individu, reponse="12"
        )
        consult = logged_client.get(self.u(ratt)).context["form"]
        assert consult.fields["question_%d" % q.pk].initial == 12
        assert consult.fields["question_%d" % q.pk].disabled is True
        edit = logged_client.get(self.u(ratt, True))
        assert edit.context["form"].fields["question_%d" % q.pk].disabled is False
        assert "Enregistrer les modifications" in edit.content.decode()
        assert "Modifier cette page" in logged_client.get(self.u(ratt)).content.decode()

    def test_post_saves_all_types_directly(self, logged_client, enfant_ctx):
        famille, ratt, act = enfant_ctx
        qs = {
            c: make_q(
                act.structure,
                activite=act,
                categorie="individu",
                controle=c,
                choix=ch,
                ordre=i,
            )
            for i, (c, ch) in enumerate(CONTROLES[:10])
        }
        data = {
            "question_%d" % qs["ligne_texte"].pk: "hello",
            "question_%d" % qs["entier"].pk: "5",
            "question_%d" % qs["decimal"].pk: "3.25",
            "question_%d" % qs["liste_coches"].pk: ["A", "B"],
            "question_%d" % qs["case_coche"].pk: "on",
            "question_%d" % qs["date"].pk: "2020-03-04",
        }
        response = logged_client.post(self.u(ratt, True), data)
        assert response.status_code == 302 and response.url == self.u(ratt)
        rep = {
            r.question.controle: r.reponse
            for r in QuestionnaireReponse.objects.filter(individu=ratt.individu)
        }
        assert (
            rep["ligne_texte"] == "hello"
            and rep["entier"] == "5"
            and rep["liste_coches"] == "A;B"
        )
        assert rep["case_coche"] == "True" and rep["date"] == "2020-03-04"
        assert PortailRenseignement.objects.filter(
            famille=famille,
            individu=ratt.individu,
            categorie="individu_questionnaire",
            validation_auto=True,
        ).exists()

    def test_post_no_change(self, logged_client, enfant_ctx):
        _f, ratt, act = enfant_ctx
        make_q(act.structure, activite=act, categorie="individu")
        assert logged_client.post(self.u(ratt, True), {}).status_code == 302
        assert not QuestionnaireReponse.objects.filter(individu=ratt.individu).exists()

    def test_pending_validation_mode(self, logged_client, enfant_ctx, pending_onglets):
        famille, ratt, act = enfant_ctx
        q = make_q(act.structure, activite=act, categorie="individu")
        response = logged_client.get(self.u(ratt, True))
        assert "validées par l'administrateur" in response.context["box_introduction"]
        logged_client.post(self.u(ratt, True), {"question_%d" % q.pk: "proposed"})
        assert not QuestionnaireReponse.objects.filter(individu=ratt.individu).exists()
        r = PortailRenseignement.objects.get(
            famille=famille, individu=ratt.individu, categorie="individu_questionnaire"
        )
        assert json.loads(r.nouvelle_valeur) == "proposed"

    def test_pending_value_displayed_with_warning(self, logged_client, enfant_ctx):
        famille, ratt, act = enfant_ctx
        q = make_q(act.structure, activite=act, categorie="individu")
        QuestionnaireReponse.objects.create(
            question=q, individu=ratt.individu, reponse="current"
        )
        PortailRenseignement.objects.create(
            famille=famille,
            individu=ratt.individu,
            categorie="individu_questionnaire",
            code="question_%d" % q.pk,
            nouvelle_valeur=json.dumps("proposed"),
            validation_auto=False,
            etat="ATTENTE",
        )
        field = (
            logged_client.get(self.u(ratt)).context["form"].fields["question_%d" % q.pk]
        )
        assert field.initial == "proposed"
        assert "attente" in str(field.help_text).lower()


@pytest.mark.django_db
def test_famille_answer_for_hidden_question_is_ignored(
    logged_client, famille_user, structure
):
    _u, famille, _r = famille_user
    q = make_q(structure, visible_portail=False)
    QuestionnaireReponse.objects.create(question=q, famille=famille, reponse="x")
    assert (
        "question_%d" % q.pk
        not in logged_client.get(reverse("portail_famille_questionnaire"))
        .context["form"]
        .fields
    )


@pytest.mark.django_db
def test_individu_answer_for_hidden_question_is_ignored(logged_client, enfant_ctx):
    _f, ratt, act = enfant_ctx
    q = make_q(act.structure, activite=act, categorie="individu", visible_portail=False)
    QuestionnaireReponse.objects.create(question=q, individu=ratt.individu, reponse="x")
    url = reverse("portail_individu_questionnaire", kwargs={"idrattachement": ratt.pk})
    assert "question_%d" % q.pk not in logged_client.get(url).context["form"].fields


@pytest.mark.django_db
def test_pending_renseignement_for_unknown_field_is_ignored(logged_client, enfant_ctx):
    famille, ratt, act = enfant_ctx
    q = make_q(act.structure, activite=act, categorie="individu")
    PortailRenseignement.objects.create(
        famille=famille,
        individu=ratt.individu,
        categorie="individu_questionnaire",
        code="question_99999",
        nouvelle_valeur=json.dumps("zz"),
        validation_auto=False,
        etat="ATTENTE",
    )
    url = reverse("portail_individu_questionnaire", kwargs={"idrattachement": ratt.pk})
    assert (
        logged_client.get(url).context["form"].fields["question_%d" % q.pk].initial
        is None
    )
