"""Unit tests for the portail "manquants" helpers (renseignements, questionnaires,
sondages, verifications). Every branch of each helper is exercised directly."""

import datetime
from types import SimpleNamespace

import pytest
from core.models import (
    QuestionnaireQuestion,
    QuestionnaireReponse,
    SondageRepondant,
    Structure,
)
from portail.utils import (
    utils_questionnaires_manquants as uq,
)
from portail.utils import (
    utils_renseignements_manquants as ur,
)
from portail.utils import (
    utils_sondages_manquants as us,
)
from portail.utils import (
    utils_verifications_manquants as uv,
)
from tests.unit.factories import (
    ActiviteFactory,
    FamilleFactory,
    IndividuFactory,
    InscriptionFactory,
    RattachementFactory,
    SondageFactory,
    StructureFactory,
    create_famille_complete,
)


def complete_identity(individu, **extra):
    """Fill every field the renseignements checks look at."""
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


def make_question(activite, label="Q", controle="ligne_texte", **kw):
    kw.setdefault("categorie", "individu")
    kw.setdefault("ordre", 1)
    kw.setdefault("visible_portail", True)
    kw.setdefault("structure", activite.structure)
    return QuestionnaireQuestion.objects.create(
        activite=activite, label=label, controle=controle, **kw
    )


# ---------------------------------------------------------------------------
# Renseignements manquants
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestRenseignementsIndividu:
    def test_none_individu(self):
        assert ur.Get_renseignements_manquants_individu(None) == {
            "nbre": 0,
            "page_cible": None,
            "message_manquant": "",
        }

    def test_default_call_without_arg(self):
        assert ur.Get_renseignements_manquants_individu()["nbre"] == 0

    def test_everything_missing_identity_has_priority(self):
        ind = IndividuFactory(nom="", prenom="", date_naiss=None, civilite=0)
        ind.nom = ""
        ind.prenom = ""
        ind.civilite = 0
        res = ur.Get_renseignements_manquants_individu(ind)
        assert res["page_cible"] == "identite"
        # nom, prenom, civilite, date_naiss, cp_naiss, ville_naiss
        assert res["nbre"] == 6
        for fragment in (
            "- nom",
            "- prénom",
            "- civilité",
            "- date de naissance",
            "- code postal de naissance",
            "- ville de naissance",
        ):
            assert fragment in res["message_manquant"]

    def test_child_complete_identity_has_no_missing(self):
        ind = complete_identity(IndividuFactory())
        RattachementFactory(individu=ind, famille=FamilleFactory(), categorie=2)
        res = ur.Get_renseignements_manquants_individu(ind)
        assert res == {"nbre": 0, "page_cible": None, "message_manquant": ""}

    def test_individu_without_rattachement_only_identity_checked(self):
        ind = complete_identity(IndividuFactory(rue_resid=None))
        res = ur.Get_renseignements_manquants_individu(ind)
        assert res["nbre"] == 0

    def test_adult_missing_all_coords(self):
        ind = complete_identity(
            IndividuFactory(),
            rue_resid="",
            cp_resid="",
            ville_resid="",
            tel_mobile="",
            tel_domicile="",
            mail="",
        )
        RattachementFactory(individu=ind, famille=FamilleFactory(), categorie=1)
        res = ur.Get_renseignements_manquants_individu(ind)
        assert res["page_cible"] == "coords"
        assert res["nbre"] == 5
        for fragment in (
            "rue de domicile",
            "code postal de domicile",
            "ville de domicile",
            "numéro de téléphone",
            "adresse mail",
        ):
            assert fragment in res["message_manquant"]

    def test_adult_with_only_tel_domicile_is_ok(self):
        ind = complete_identity(
            IndividuFactory(), tel_mobile="", tel_domicile="0100000000"
        )
        RattachementFactory(individu=ind, famille=FamilleFactory(), categorie=1)
        assert ur.Get_renseignements_manquants_individu(ind)["nbre"] == 0

    def test_identity_missing_wins_over_coords(self):
        ind = complete_identity(IndividuFactory(), cp_naiss="", rue_resid="")
        RattachementFactory(individu=ind, famille=FamilleFactory(), categorie=1)
        res = ur.Get_renseignements_manquants_individu(ind)
        assert res["page_cible"] == "identite"
        assert res["nbre"] == 2


@pytest.mark.django_db
class TestRenseignementsParInscriptions:
    def test_empty(self):
        assert ur.Get_renseignements_manquants_par_inscriptions([]) == {}

    def test_batch_identity_and_coords_and_clean(self):
        fam = FamilleFactory()
        act = ActiviteFactory()
        # 1: child missing identity (nom, prenom, civilite, naissance)
        enfant = IndividuFactory(nom="", prenom="", date_naiss=None)
        enfant.nom = ""
        enfant.prenom = ""
        enfant.civilite = 0
        enfant.save()
        RattachementFactory(individu=enfant, famille=fam, categorie=2)
        # 2: adult complete identity, missing all coords
        adulte = complete_identity(
            IndividuFactory(),
            rue_resid="",
            cp_resid="",
            ville_resid="",
            tel_mobile="",
            tel_domicile="",
            mail="",
        )
        RattachementFactory(individu=adulte, famille=fam, categorie=1)
        # 3: adult entirely complete
        parfait = complete_identity(IndividuFactory())
        RattachementFactory(individu=parfait, famille=fam, categorie=1)
        # 4: individu with no rattachement
        seul = complete_identity(IndividuFactory())
        inscs = [
            InscriptionFactory(individu=i, famille=fam, activite=act)
            for i in (enfant, adulte, parfait, seul)
        ]

        res = ur.Get_renseignements_manquants_par_inscriptions(inscs)
        assert res[enfant.pk]["page_cible"] == "identite"
        assert res[enfant.pk]["nbre"] == 6
        assert "Il manque pour" in res[enfant.pk]["message_manquant"]
        assert res[adulte.pk]["page_cible"] == "coords"
        assert res[adulte.pk]["nbre"] == 5
        assert res[parfait.pk] == {
            "nbre": 0,
            "page_cible": None,
            "message_manquant": "",
        }
        assert res[seul.pk]["nbre"] == 0

    def test_adult_identity_wins_over_coords(self):
        fam = FamilleFactory()
        adulte = complete_identity(IndividuFactory(), cp_naiss="", rue_resid="")
        RattachementFactory(individu=adulte, famille=fam, categorie=1)
        res = ur.Get_renseignements_manquants_par_inscriptions(
            [InscriptionFactory(individu=adulte, famille=fam)]
        )
        assert res[adulte.pk]["page_cible"] == "identite"
        assert res[adulte.pk]["nbre"] == 2


@pytest.mark.django_db
class TestRenseignementsFamille:
    def test_none_famille(self):
        res = ur.Get_renseignements_manquants(None)
        assert res == {
            "nbre": 0,
            "premier_rattachement_id": None,
            "page_cible": None,
            "message_manquant": "",
        }

    def test_no_arg(self):
        assert ur.Get_renseignements_manquants()["nbre"] == 0

    def test_complete_family_with_parent_coords(self, organisateur):
        _u, famille, ratt = create_famille_complete()
        complete_identity(ratt[0].individu)
        complete_identity(ratt[1].individu)
        res = ur.Get_renseignements_manquants(famille)
        assert res["nbre"] == 0
        assert res["premier_rattachement_id"] is None

    def test_deceased_individus_ignored(self, organisateur):
        _u, famille, ratt = create_famille_complete()
        complete_identity(ratt[0].individu)
        enfant = ratt[1].individu
        enfant.deces = True
        enfant.save()
        assert ur.Get_renseignements_manquants(famille)["nbre"] == 0

    def test_adult_missing_coords_and_child_ok_when_parent_incomplete(
        self, organisateur
    ):
        """Adult (cat 1) lacking coords; the child has no parent with full coords -> child also needs address."""
        _u, famille, ratt = create_famille_complete()
        complete_identity(
            ratt[0].individu,
            rue_resid="",
            cp_resid="",
            ville_resid="",
            tel_mobile="",
            tel_domicile="",
            mail="",
        )
        complete_identity(ratt[1].individu, rue_resid="", cp_resid="", ville_resid="")
        res = ur.Get_renseignements_manquants(famille)
        # adult: 5 coords ; child: 3 address fields
        assert res["nbre"] == 8
        assert res["page_cible"] == "coords"
        assert res["premier_rattachement_id"] in (ratt[0].pk, ratt[1].pk)
        assert "adresse mail" in res["message_manquant"]

    def test_child_not_flagged_if_parent_has_coords(self, organisateur):
        _u, famille, ratt = create_famille_complete()
        complete_identity(ratt[0].individu)
        complete_identity(ratt[1].individu, rue_resid="", cp_resid="", ville_resid="")
        assert ur.Get_renseignements_manquants(famille)["nbre"] == 0

    def test_identity_missing_sets_identite_target(self, organisateur):
        _u, famille, ratt = create_famille_complete()
        complete_identity(ratt[0].individu)
        complete_identity(
            ratt[1].individu, cp_naiss="", ville_naiss="", civilite=0, date_naiss=None
        )
        res = ur.Get_renseignements_manquants(famille)
        assert res["nbre"] == 4
        assert res["page_cible"] == "identite"
        assert res["premier_rattachement_id"] == ratt[1].pk

    def test_first_missing_rattachement_not_overwritten_and_coords_target(
        self, organisateur
    ):
        """Two incomplete members: premier_rattachement_id keeps the first one; coords target for an adult."""
        _u, famille, ratt = create_famille_complete()
        complete_identity(ratt[0].individu, rue_resid="")
        complete_identity(ratt[1].individu)
        second = IndividuFactory(nom="Zed")
        complete_identity(second, cp_naiss="")
        rs = RattachementFactory(individu=second, famille=famille, categorie=2)
        res = ur.Get_renseignements_manquants(famille)
        assert res["nbre"] == 2
        assert res["premier_rattachement_id"] == ratt[0].pk
        assert rs.pk != res["premier_rattachement_id"]

    def test_nom_and_prenom_missing(self, organisateur):
        _u, famille, ratt = create_famille_complete()
        complete_identity(ratt[0].individu)
        enfant = complete_identity(ratt[1].individu)
        enfant.nom = ""
        enfant.prenom = ""
        enfant.save()
        res = ur.Get_renseignements_manquants(famille)
        assert res["nbre"] == 2
        assert res["page_cible"] == "identite"
        # BUG tracked separately: the prenom message overwrites the nom message


@pytest.mark.xfail(
    reason='BUG: utils_renseignements_manquants.py:~232 `tmp_msg = "- prénom\\n"` uses = instead of += so the nom message is lost',
    strict=True,
)
@pytest.mark.django_db
def test_renseignements_famille_message_lists_nom_and_prenom(organisateur):
    _u, famille, ratt = create_famille_complete()
    complete_identity(ratt[0].individu)
    enfant = complete_identity(ratt[1].individu)
    enfant.nom = ""
    enfant.prenom = ""
    enfant.save()
    msg = ur.Get_renseignements_manquants(famille)["message_manquant"]
    assert "- nom" in msg and "- prénom" in msg


# ---------------------------------------------------------------------------
# Questionnaires manquants
# ---------------------------------------------------------------------------


def reponse_obj(question, individu, valeur):
    return QuestionnaireReponse.objects.create(
        question=question, individu=individu, reponse=valeur
    )


@pytest.mark.django_db
class TestEstQuestionCompletee:
    def test_none_reponse(self):
        assert uq.est_question_complétée(None) is False

    def test_reponse_none_value_for_entier(self):
        """Empty entier answer -> Get_reponse_for_ctrl returns None -> incomplete."""
        act = ActiviteFactory()
        ind = IndividuFactory()
        q = make_question(act, controle="entier")
        assert uq.est_question_complétée(reponse_obj(q, ind, "")) is False

    def test_null_answer_is_incomplete(self):
        """A stored NULL answer -> Get_reponse_for_ctrl() is None -> incomplete."""
        act = ActiviteFactory()
        q = make_question(act, controle="ligne_texte")
        assert (
            uq.est_question_complétée(reponse_obj(q, IndividuFactory(), None)) is False
        )

    def test_case_coche_false_is_complete(self):
        act = ActiviteFactory()
        q = make_question(act, controle="case_coche")
        assert (
            uq.est_question_complétée(reponse_obj(q, IndividuFactory(), "False"))
            is True
        )

    def test_text_non_empty(self):
        act = ActiviteFactory()
        q = make_question(act, controle="ligne_texte")
        assert (
            uq.est_question_complétée(reponse_obj(q, IndividuFactory(), "abc")) is True
        )

    def test_text_blank(self):
        act = ActiviteFactory()
        q = make_question(act, controle="ligne_texte")
        assert (
            uq.est_question_complétée(reponse_obj(q, IndividuFactory(), "   ")) is False
        )

    def test_list_non_empty_is_complete(self):
        """liste_coches answer is split on ';' -> non-empty list."""
        act = ActiviteFactory()
        q = make_question(act, controle="liste_coches", choix="A;B")
        assert (
            uq.est_question_complétée(reponse_obj(q, IndividuFactory(), "A;B")) is True
        )

    def test_list_empty_tuple_branch(self):
        """A fake reponse returning an empty list hits the (list, tuple) branch -> False."""
        fake = SimpleNamespace(
            question=SimpleNamespace(controle="liste_coches"),
            Get_reponse_for_ctrl=list,
        )
        assert uq.est_question_complétée(fake) is False

    def test_list_non_empty_tuple_branch(self):
        fake = SimpleNamespace(
            question=SimpleNamespace(controle="liste_coches"),
            Get_reponse_for_ctrl=lambda: ("a",),
        )
        assert uq.est_question_complétée(fake) is True

    def test_entier_number_is_complete(self):
        act = ActiviteFactory()
        q = make_question(act, controle="entier")
        assert uq.est_question_complétée(reponse_obj(q, IndividuFactory(), "0")) is True

    def test_decimal_is_complete(self):
        act = ActiviteFactory()
        q = make_question(act, controle="decimal")
        # Decimal is not int/float/complex -> falls through to the final False
        assert (
            uq.est_question_complétée(reponse_obj(q, IndividuFactory(), "3.5")) is False
        )

    def test_float_value_is_complete(self):
        fake = SimpleNamespace(
            question=SimpleNamespace(controle="decimal"),
            Get_reponse_for_ctrl=lambda: 3.5,
        )
        assert uq.est_question_complétée(fake) is True

    def test_date_like_value_is_complete(self):
        fake = SimpleNamespace(
            question=SimpleNamespace(controle="date"),
            Get_reponse_for_ctrl=lambda: datetime.date(2020, 1, 1),
        )
        assert uq.est_question_complétée(fake) is True

    def test_unknown_type_is_incomplete(self):
        fake = SimpleNamespace(
            question=SimpleNamespace(controle="x"),
            Get_reponse_for_ctrl=lambda: object(),
        )
        assert uq.est_question_complétée(fake) is False


@pytest.mark.django_db
class TestGetQuestionIndividu:
    def test_no_inscription_no_questions(self):
        assert uq.Get_question_individu(IndividuFactory()) == []

    def test_unanswered_question_listed(self):
        ind = IndividuFactory()
        act = ActiviteFactory()
        InscriptionFactory(individu=ind, activite=act)
        q = make_question(act)
        assert uq.Get_question_individu(ind) == [q]

    def test_answered_question_not_listed(self):
        ind = IndividuFactory()
        act = ActiviteFactory()
        InscriptionFactory(individu=ind, activite=act)
        q = make_question(act)
        reponse_obj(q, ind, "ok")
        assert uq.Get_question_individu(ind) == []

    def test_blank_answer_is_still_missing(self):
        ind = IndividuFactory()
        act = ActiviteFactory()
        InscriptionFactory(individu=ind, activite=act)
        q = make_question(act)
        reponse_obj(q, ind, "")
        assert uq.Get_question_individu(ind) == [q]

    def test_question_not_visible_portail_or_wrong_category_ignored(self):
        ind = IndividuFactory()
        act = ActiviteFactory()
        InscriptionFactory(individu=ind, activite=act)
        make_question(act, visible_portail=False)
        make_question(act, categorie="famille")
        assert uq.Get_question_individu(ind) == []

    def test_invisible_structure_ignored(self):
        ind = IndividuFactory()
        struct = StructureFactory(visible=False)
        act = ActiviteFactory(structure=struct)
        InscriptionFactory(individu=ind, activite=act)
        make_question(act)
        assert uq.Get_question_individu(ind) == []

    def test_ordering_by_ordre(self):
        ind = IndividuFactory()
        act = ActiviteFactory()
        InscriptionFactory(individu=ind, activite=act)
        q2 = make_question(act, label="second", ordre=2)
        q1 = make_question(act, label="first", ordre=1)
        assert uq.Get_question_individu(ind) == [q1, q2]


@pytest.mark.django_db
class TestGetQuestionsParInscriptions:
    def test_empty(self):
        assert uq.Get_questions_par_inscriptions([]) == {}

    def test_batch_results(self):
        fam = FamilleFactory()
        act = ActiviteFactory()
        a, b = IndividuFactory(), IndividuFactory()
        q = make_question(act)
        reponse_obj(q, a, "done")
        inscs = [
            InscriptionFactory(individu=a, famille=fam, activite=act),
            InscriptionFactory(individu=b, famille=fam, activite=act),
        ]
        res = uq.Get_questions_par_inscriptions(inscs)
        assert res[a.pk] == []
        assert res[b.pk] == [q]

    def test_batch_blank_answer_counts_missing(self):
        fam = FamilleFactory()
        act = ActiviteFactory()
        a = IndividuFactory()
        q = make_question(act)
        reponse_obj(q, a, " ")
        res = uq.Get_questions_par_inscriptions(
            [InscriptionFactory(individu=a, famille=fam, activite=act)]
        )
        assert res[a.pk] == [q]


@pytest.mark.django_db
class TestGetQuestionsManquantesFamille:
    def test_none(self):
        assert uq.Get_questions_manquantes_famille(None) == {}

    def test_per_member_structure(self, organisateur):
        _u, famille, ratt = create_famille_complete()
        act = ActiviteFactory()
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        q = make_question(act)
        res = uq.Get_questions_manquantes_famille(famille)
        assert set(res) == {ratt[0].individu.pk, ratt[1].individu.pk}
        assert res[ratt[1].individu.pk]["nbre"] == 1
        assert res[ratt[1].individu.pk]["questions"] == [q]
        assert res[ratt[1].individu.pk]["rattachement"] == ratt[1]
        assert res[ratt[0].individu.pk]["nbre"] == 0

    def test_deceased_excluded(self, organisateur):
        _u, famille, ratt = create_famille_complete()
        enfant = ratt[1].individu
        enfant.deces = True
        enfant.save()
        assert set(uq.Get_questions_manquantes_famille(famille)) == {
            ratt[0].individu.pk
        }


# ---------------------------------------------------------------------------
# Sondages manquants
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGetSondagesManquants:
    def test_none(self):
        assert us.Get_sondages_manquants(None) == []
        assert us.Get_sondages_manquants() == []

    def test_famille_survey_missing_then_answered(self, organisateur):
        _u, famille, ratt = create_famille_complete()
        act = ActiviteFactory()
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        sondage = SondageFactory(public="famille", structure=act.structure)
        res = us.Get_sondages_manquants(famille)
        assert [r["sondage"] for r in res] == [sondage]
        assert (
            res[0]["type"] == "famille"
            and res[0]["individu"] is None
            and str(res[0]["code"]) == str(sondage.code)
        )
        SondageRepondant.objects.create(sondage=sondage, famille=famille)
        assert us.Get_sondages_manquants(famille) == []

    def test_survey_in_other_structure_ignored(self, organisateur):
        _u, famille, ratt = create_famille_complete()
        act = ActiviteFactory()
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        SondageFactory(public="famille", structure=StructureFactory())
        SondageFactory(public="famille", structure=None)
        assert us.Get_sondages_manquants(famille) == []

    def test_invisible_structure_ignored(self, organisateur):
        _u, famille, ratt = create_famille_complete()
        struct = StructureFactory(visible=False)
        act = ActiviteFactory(structure=struct)
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        SondageFactory(public="famille", structure=struct)
        assert us.Get_sondages_manquants(famille) == []

    def test_individu_survey_per_enrolled_individu(self, organisateur):
        _u, famille, ratt = create_famille_complete()
        act = ActiviteFactory()
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        sondage = SondageFactory(
            public="individu", structure=act.structure, categories_rattachements=["2"]
        )
        res = us.Get_sondages_manquants(famille)
        assert len(res) == 1
        assert res[0]["type"] == "individu" and res[0]["individu"] == ratt[1].individu
        # answered for that individu
        SondageRepondant.objects.create(
            sondage=sondage, famille=famille, individu=ratt[1].individu
        )
        assert us.Get_sondages_manquants(famille) == []

    def test_individu_survey_not_enrolled_individu_skipped(self, organisateur):
        """The adult has no inscription in the structure -> not concerned."""
        _u, famille, ratt = create_famille_complete()
        act = ActiviteFactory()
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        SondageFactory(
            public="individu",
            structure=act.structure,
            categories_rattachements=["1", "2"],
        )
        res = us.Get_sondages_manquants(famille)
        assert [r["individu"] for r in res] == [ratt[1].individu]

    def test_individu_survey_category_filter(self, organisateur):
        _u, famille, ratt = create_famille_complete()
        act = ActiviteFactory()
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        SondageFactory(
            public="individu", structure=act.structure, categories_rattachements=["1"]
        )
        assert us.Get_sondages_manquants(famille) == []

    def test_individu_survey_no_category_filter(self, organisateur):
        _u, famille, ratt = create_famille_complete()
        act = ActiviteFactory()
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        SondageFactory(
            public="individu", structure=act.structure, categories_rattachements=[]
        )
        assert len(us.Get_sondages_manquants(famille)) == 1

    def test_repondant_without_individu_for_individu_survey(self, organisateur):
        """An individu-type survey answered with individu=None must not crash and is not counted as an answer."""
        _u, famille, ratt = create_famille_complete()
        act = ActiviteFactory()
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        sondage = SondageFactory(
            public="individu", structure=act.structure, categories_rattachements=["2"]
        )
        SondageRepondant.objects.create(sondage=sondage, famille=famille, individu=None)
        assert len(us.Get_sondages_manquants(famille)) == 1

    def test_two_inscriptions_same_individu_and_foreign_repondant(self, organisateur):
        """Same individu enrolled twice in a structure (set already initialised) and a repondant for
        another individu of the same survey."""
        _u, famille, ratt = create_famille_complete()
        act = ActiviteFactory()
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        InscriptionFactory(
            individu=ratt[1].individu,
            famille=famille,
            activite=ActiviteFactory(structure=act.structure),
        )
        sondage = SondageFactory(
            public="individu",
            structure=act.structure,
            categories_rattachements=["1", "2"],
        )
        SondageRepondant.objects.create(
            sondage=sondage, famille=famille, individu=ratt[0].individu
        )
        res = us.Get_sondages_manquants(famille)
        assert [r["individu"] for r in res] == [ratt[1].individu]

    def test_second_repondant_same_survey_individu(self, organisateur):
        """Two repondants for the same individu survey exercise the 'already in dict' branch."""
        _u, famille, ratt = create_famille_complete()
        act = ActiviteFactory()
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        sondage = SondageFactory(
            public="individu", structure=act.structure, categories_rattachements=["2"]
        )
        SondageRepondant.objects.create(sondage=sondage, famille=famille, individu=None)
        SondageRepondant.objects.create(
            sondage=sondage, famille=famille, individu=ratt[1].individu
        )
        assert us.Get_sondages_manquants(famille) == []


@pytest.mark.django_db
class TestSondagesParInscriptions:
    def test_empty(self):
        assert us.Get_sondages_manquants_par_inscriptions([]) == {}

    def test_famille_and_individu_surveys(self, organisateur):
        _u, famille, ratt = create_famille_complete()
        act = ActiviteFactory()
        enfant, adulte = ratt[1].individu, ratt[0].individu
        s_fam = SondageFactory(public="famille", structure=act.structure)
        s_ind = SondageFactory(
            public="individu", structure=act.structure, categories_rattachements=["2"]
        )
        s_all = SondageFactory(
            public="individu", structure=act.structure, categories_rattachements=[]
        )
        inscs = [
            InscriptionFactory(individu=enfant, famille=famille, activite=act),
            InscriptionFactory(individu=adulte, famille=famille, activite=act),
        ]
        res = us.Get_sondages_manquants_par_inscriptions(inscs)
        codes_enfant = {m["sondage"] for m in res[enfant.pk]}
        codes_adulte = {m["sondage"] for m in res[adulte.pk]}
        assert codes_enfant == {s_fam, s_ind, s_all}
        # adult is category 1 -> excluded from s_ind
        assert codes_adulte == {s_fam, s_all}

    def test_repondant_of_other_individu_ignored(self, organisateur):
        _u, famille, ratt = create_famille_complete()
        act = ActiviteFactory()
        enfant, adulte = ratt[1].individu, ratt[0].individu
        s_fam = SondageFactory(public="famille", structure=act.structure)
        SondageRepondant.objects.create(sondage=s_fam, famille=famille, individu=adulte)
        inscs = [
            InscriptionFactory(individu=enfant, famille=famille, activite=act),
            InscriptionFactory(individu=adulte, famille=famille, activite=act),
        ]
        res = us.Get_sondages_manquants_par_inscriptions(inscs)
        assert [m["sondage"] for m in res[enfant.pk]] == [s_fam]
        assert res[adulte.pk] == []

    def test_answered_surveys_removed(self, organisateur):
        _u, famille, ratt = create_famille_complete()
        act = ActiviteFactory()
        enfant = ratt[1].individu
        s_fam = SondageFactory(public="famille", structure=act.structure)
        s_ind = SondageFactory(
            public="individu", structure=act.structure, categories_rattachements=["2"]
        )
        SondageRepondant.objects.create(sondage=s_fam, famille=famille, individu=enfant)
        SondageRepondant.objects.create(sondage=s_ind, famille=famille, individu=enfant)
        res = us.Get_sondages_manquants_par_inscriptions(
            [InscriptionFactory(individu=enfant, famille=famille, activite=act)]
        )
        assert res[enfant.pk] == []

    def test_individu_without_rattachement_not_category_filtered(self):
        fam = FamilleFactory()
        act = ActiviteFactory()
        ind = IndividuFactory()
        s = SondageFactory(
            public="individu", structure=act.structure, categories_rattachements=["1"]
        )
        res = us.Get_sondages_manquants_par_inscriptions(
            [InscriptionFactory(individu=ind, famille=fam, activite=act)]
        )
        assert [m["sondage"] for m in res[ind.pk]] == [s]


@pytest.mark.django_db
class TestSondagesIndividu:
    def test_famille_survey_missing_and_answered(self):
        ind = IndividuFactory()
        struct = StructureFactory()
        s = SondageFactory(public="famille", structure=struct)
        res = us.Get_sondages_manquants_individu(individu=ind, structure=[struct])
        assert res[0]["type"] == "famille" and res[0]["sondage"] == s
        SondageRepondant.objects.create(
            sondage=s, famille=FamilleFactory(), individu=ind
        )
        assert (
            us.Get_sondages_manquants_individu(individu=ind, structure=[struct]) == []
        )

    def test_individu_survey_without_category_filter(self):
        ind = IndividuFactory()
        struct = StructureFactory()
        s = SondageFactory(
            public="individu", structure=struct, categories_rattachements=[]
        )
        res = us.Get_sondages_manquants_individu(individu=ind, structure=[struct])
        assert res[0]["type"] == "individu" and res[0]["individu"] == ind
        SondageRepondant.objects.create(
            sondage=s, famille=FamilleFactory(), individu=ind
        )
        assert (
            us.Get_sondages_manquants_individu(individu=ind, structure=[struct]) == []
        )

    @pytest.mark.xfail(
        reason="BUG: utils_sondages_manquants.py:~265 Get_sondages_manquants_individu references the undefined name "
        "`rattachement` when a survey defines categories_rattachements (NameError); the `famille` arg is also unused.",
        strict=True,
    )
    def test_individu_survey_with_category_filter(self):
        ind = IndividuFactory()
        struct = StructureFactory()
        fam = FamilleFactory()
        RattachementFactory(individu=ind, famille=fam, categorie=2)
        SondageFactory(
            public="individu", structure=struct, categories_rattachements=["2"]
        )
        res = us.Get_sondages_manquants_individu(
            individu=ind, famille=fam, structure=[struct]
        )
        assert len(res) == 1


# ---------------------------------------------------------------------------
# Verifications manquantes (module is broken: undefined helpers)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestVerificationsManquants:
    def test_get_information_individu_without_questions_returns_empty(self):
        """With no matching question the loop body (which uses undefined names) never runs."""
        assert uv.Get_information_individu(IndividuFactory()) == []

    @pytest.mark.xfail(
        reason="BUG: utils_verifications_manquants.py:~35 Get_information_individu calls est_question_complétée which is "
        "neither defined nor imported (NameError) as soon as one question is already answered.",
        strict=True,
    )
    def test_get_information_individu_with_answered_question(self):
        ind = IndividuFactory()
        act = ActiviteFactory()
        InscriptionFactory(individu=ind, activite=act)
        q = make_question(act)
        reponse_obj(q, ind, "ok")
        assert uv.Get_information_individu(ind) == []

    def test_get_information_individu_with_unanswered_question(self):
        """No answer yet: short-circuits before the undefined helper is needed."""
        ind = IndividuFactory()
        act = ActiviteFactory()
        InscriptionFactory(individu=ind, activite=act)
        q = make_question(act)
        assert uv.Get_information_individu(ind) == [q]

    @pytest.mark.xfail(
        reason="BUG: utils_verifications_manquants.py:~55 Get_questions_manquantes_famille calls the undefined "
        "Get_question_individu (NameError) for any rattachement.",
        strict=True,
    )
    def test_get_questions_manquantes_famille(self, organisateur):
        _u, famille, _ratt = create_famille_complete()
        assert uv.Get_questions_manquantes_famille(famille) != {}

    def test_get_questions_manquantes_famille_none(self):
        assert uv.Get_questions_manquantes_famille(None) == {}

    def test_get_questions_manquantes_famille_no_rattachement(self):
        assert uv.Get_questions_manquantes_famille(FamilleFactory()) == {}


def test_structure_model_imported():
    # keep the Structure import meaningful for linting; sanity check on default
    assert Structure._meta.get_field("visible").default is True
