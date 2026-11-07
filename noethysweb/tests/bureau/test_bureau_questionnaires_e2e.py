"""Questionnaires, end to end: staff creates the questions, the family answers on the portal,
the director reads (and corrects) the answers on the fiche individu.

Every answer type offered in Paramétrage > Questionnaires is exercised
(LISTE_CONTROLES_QUESTIONNAIRES): bloc_texte, entier, decimal, montant,
liste_deroulante, liste_coches, liste_coches_ouinon, date.

The key property checked for each type is the round trip: what the family typed must
be stored in a stable format AND be shown back (pre-filled / pre-selected) the next
time the family or the director opens the questionnaire.
"""

import datetime
from decimal import Decimal

import pytest
from core.models import LISTE_CONTROLES_QUESTIONNAIRES, QuestionnaireQuestion, QuestionnaireReponse, Utilisateur
from django.test import Client
from django.urls import reverse
from tests.bureau.helpers_questionnaires import CAS
from tests.bureau.helpers_questionnaires import creer_question as _creer_question
from tests.bureau.helpers_questionnaires import form_portail as _form_portail
from tests.bureau.helpers_questionnaires import portail as _portail
from tests.bureau.helpers_questionnaires import ratt_enfant as _ratt_enfant
from tests.bureau.helpers_questionnaires import repondre_portail as _repondre_portail
from tests.bureau.helpers_questionnaires import affiche as _affiche
from tests.unit.factories import ActiviteFactory, StructureFactory

CONTROLES = [ctrl["code"] for ctrl in LISTE_CONTROLES_QUESTIONNAIRES]

def test_tous_les_types_proposes_sont_couverts():
    """Guard: a new answer type added to the parametrage must get a case here."""
    assert set(CAS) == set(CONTROLES)


RAISON_CHANGED_DATA = {
    "liste_deroulante": (
        "BUG: QuestionnaireReponse.Get_reponse_for_ctrl() returns a list for a single-choice "
        "question (['Moyen']), so has_changed() compares \"['Moyen']\" to 'Moyen': every save of the "
        "tab logs a fake change (PortailRenseignement) and resets the fiche certification."
    ),
    "liste_coches_ouinon": (
        "BUG: Get_reponse_for_ctrl() does not split liste_coches_ouinon answers, so the initial is the "
        "string 'Oui' and MultipleChoiceField.has_changed() compares {'O','u','i'} to {'Oui'}: every "
        "save logs a fake change and resets the fiche certification."
    ),
    "date": (
        "BUG: date answers are read back as the stored string ('2026-05-01') and DateField.has_changed() "
        "compares it to a date object: every save logs a fake change and resets the fiche certification."
    ),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _form_bureau(client, famille, individu, edition=False):
    name = "individu_questionnaire_modifier" if edition else "individu_questionnaire"
    response = client.get(reverse(name, args=[famille.pk, individu.pk]))
    assert response.status_code == 200
    return response.context["form"]


def _reponse(question, individu):
    reponse = QuestionnaireReponse.objects.filter(question=question, individu=individu).first()
    return reponse.reponse if reponse else None


@pytest.fixture
def portail_famille(famille_bureau):
    famille, _t, enfant = famille_bureau
    return _portail(famille), _ratt_enfant(famille, enfant)


# ---------------------------------------------------------------------------
# 1. Creation by the staff (Paramétrage > Questionnaires)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCreationQuestion:
    @pytest.mark.parametrize("controle", CONTROLES)
    def test_creer_une_question_de_chaque_type(self, directeur_client, structure, activite, controle):
        choix = CAS[controle][0]
        question = _creer_question(directeur_client, structure, activite, controle, choix=choix)
        assert question.controle == controle
        assert question.categorie == "individu"
        assert question.structure == structure
        assert question.activite == activite
        assert question.visible and question.visible_portail

    def test_les_listes_recoivent_le_choix_ras(self, directeur_client, structure, activite):
        question = _creer_question(directeur_client, structure, activite, "liste_coches", choix=" Piscine ; Vélo ;")
        assert question.choix == "Piscine;Vélo;RAS"

    def test_ras_n_est_pas_double(self, directeur_client, structure, activite):
        question = _creer_question(directeur_client, structure, activite, "liste_deroulante", choix="Oui;RAS")
        assert question.choix == "Oui;RAS"

    def test_les_questions_sont_numerotees_a_la_suite(self, directeur_client, structure, activite):
        q1 = _creer_question(directeur_client, structure, activite, "entier", label="Q1")
        q2 = _creer_question(directeur_client, structure, activite, "date", label="Q2")
        assert q2.ordre == q1.ordre + 1

    def test_structure_obligatoire(self, directeur_client, activite):
        url = reverse("questions_ajouter", kwargs={"categorie": "individu"})
        response = directeur_client.post(url, {"categorie": "individu", "ordre": 1, "label": "Sans structure",
                                               "controle": "bloc_texte", "activite": activite.pk})
        assert response.status_code == 200
        assert "structure" in response.context["form"].errors
        assert not QuestionnaireQuestion.objects.filter(label="Sans structure").exists()

    def test_seules_mes_activites_sont_proposees(self, directeur_client, activite):
        autre = ActiviteFactory(structure=StructureFactory())
        queryset = directeur_client.get(
            reverse("questions_ajouter", kwargs={"categorie": "individu"})
        ).context["form"].fields["activite"].queryset
        assert activite in queryset and autre not in queryset

    def test_le_type_n_est_plus_modifiable_apres_creation(self, directeur_client, structure, activite):
        question = _creer_question(directeur_client, structure, activite, "entier")
        form = directeur_client.get(
            reverse("questions_modifier", kwargs={"categorie": "individu", "pk": question.pk})
        ).context["form"]
        assert form.fields["controle"].disabled

    def test_renommer_une_question_se_voit_sur_le_portail(
        self, directeur_client, structure, activite, portail_famille
    ):
        client_famille, ratt = portail_famille
        question = _creer_question(directeur_client, structure, activite, "bloc_texte", label="Ancien libellé")
        url = reverse("questions_modifier", kwargs={"categorie": "individu", "pk": question.pk})
        directeur_client.post(url, {
            "categorie": "individu", "ordre": question.ordre, "label": "Nouveau libellé", "controle": "bloc_texte",
            "structure": structure.pk, "activite": activite.pk, "visible": "True", "visible_portail": "True",
            "visible_fiche_renseignement": "True",
        })
        champ = _form_portail(client_famille, ratt).fields["question_%d" % question.pk]
        assert champ.label == "Nouveau libellé"

    def test_supprimer_une_question_supprime_ses_reponses_et_renumerote(
        self, directeur_client, structure, activite, portail_famille
    ):
        client_famille, ratt = portail_famille
        q1 = _creer_question(directeur_client, structure, activite, "bloc_texte", label="Q1")
        q2 = _creer_question(directeur_client, structure, activite, "bloc_texte", label="Q2")
        _repondre_portail(client_famille, ratt, {q1: "Réponse 1"})

        response = directeur_client.post(reverse("questions_supprimer", kwargs={"categorie": "individu", "pk": q1.pk}))
        assert response.status_code == 302
        assert not QuestionnaireReponse.objects.filter(question_id=q1.pk).exists()
        q2.refresh_from_db()
        assert q2.ordre == 1
        assert "question_%d" % q1.pk not in _form_portail(client_famille, ratt).fields


# ---------------------------------------------------------------------------
# 2. Who sees which question
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestVisibilite:
    def test_la_famille_voit_les_questions_de_l_activite_de_son_enfant(
        self, directeur_client, structure, activite, portail_famille
    ):
        client_famille, ratt = portail_famille
        question = _creer_question(directeur_client, structure, activite, "bloc_texte")
        assert "question_%d" % question.pk in _form_portail(client_famille, ratt).fields

    def test_question_d_une_autre_activite_non_affichee(self, directeur_client, structure, portail_famille):
        client_famille, ratt = portail_famille
        autre_activite = ActiviteFactory(structure=structure)
        question = _creer_question(directeur_client, structure, autre_activite, "bloc_texte")
        assert "question_%d" % question.pk not in _form_portail(client_famille, ratt).fields

    def test_le_directeur_ne_voit_que_les_questions_de_ses_structures(
        self, directeur_client, structure, activite, famille_bureau
    ):
        from tests.unit.factories import InscriptionFactory, UtilisateurFactory

        famille, _t, enfant = famille_bureau
        mienne = _creer_question(directeur_client, structure, activite, "bloc_texte", label="Mienne")

        voisine = StructureFactory()
        activite_voisine = ActiviteFactory(structure=voisine)
        InscriptionFactory(famille=famille, individu=enfant, activite=activite_voisine)
        collegue = UtilisateurFactory(username="directeur_voisin")
        collegue.structures.add(voisine)
        client_voisin = Client()
        client_voisin.force_login(collegue)
        sienne = _creer_question(client_voisin, voisine, activite_voisine, "bloc_texte", label="Sienne")

        champs = _form_bureau(directeur_client, famille, enfant).fields
        assert "question_%d" % mienne.pk in champs
        assert "question_%d" % sienne.pk not in champs
        # ...while the family, inscribed in both, answers both
        champs_famille = _form_portail(_portail(famille), _ratt_enfant(famille, enfant)).fields
        assert {"question_%d" % mienne.pk, "question_%d" % sienne.pk} <= set(champs_famille)


# ---------------------------------------------------------------------------
# 3. The family answers on the portal, everybody reads the same answer back
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestReponseFamille:
    @pytest.mark.parametrize("controle", CONTROLES)
    def test_reponse_enregistree_au_bon_format(
        self, directeur_client, structure, activite, famille_bureau, portail_famille, controle
    ):
        _f, _t, enfant = famille_bureau
        client_famille, ratt = portail_famille
        choix, posted, stocke, _relu = CAS[controle]
        question = _creer_question(directeur_client, structure, activite, controle, choix=choix)

        response = _repondre_portail(client_famille, ratt, {question: posted})
        assert response.status_code == 302
        assert _reponse(question, enfant) == stocke

    @pytest.mark.parametrize("controle", CONTROLES)
    def test_la_famille_retrouve_sa_reponse(
        self, directeur_client, structure, activite, portail_famille, controle
    ):
        client_famille, ratt = portail_famille
        choix, posted, _stocke, relu = CAS[controle]
        question = _creer_question(directeur_client, structure, activite, controle, choix=choix)
        _repondre_portail(client_famille, ratt, {question: posted})

        champ = _form_portail(client_famille, ratt).fields["question_%d" % question.pk]
        assert _affiche(champ) == relu

    @pytest.mark.parametrize("controle", CONTROLES)
    def test_le_directeur_voit_la_reponse_de_la_famille(
        self, directeur_client, structure, activite, famille_bureau, portail_famille, controle
    ):
        famille, _t, enfant = famille_bureau
        client_famille, ratt = portail_famille
        choix, posted, _stocke, relu = CAS[controle]
        question = _creer_question(directeur_client, structure, activite, controle, choix=choix)
        _repondre_portail(client_famille, ratt, {question: posted})

        champ = _form_bureau(directeur_client, famille, enfant).fields["question_%d" % question.pk]
        assert _affiche(champ) == relu

    @pytest.mark.parametrize("controle", [
        pytest.param(c, marks=pytest.mark.xfail(strict=True, reason=RAISON_CHANGED_DATA[c])) if c in RAISON_CHANGED_DATA
        else c for c in CONTROLES
    ])
    def test_reenregistrer_sans_rien_changer_n_est_pas_une_modification(
        self, directeur_client, structure, activite, famille_bureau, portail_famille, controle
    ):
        """Saving the tab again without touching anything must not log a change nor ask for a new
        certification of the fiche."""
        from core.models import PortailRenseignement

        famille, _t, _e = famille_bureau
        client_famille, ratt = portail_famille
        choix, posted, _stocke, _relu = CAS[controle]
        question = _creer_question(directeur_client, structure, activite, controle, choix=choix)
        _repondre_portail(client_famille, ratt, {question: posted})
        avant = PortailRenseignement.objects.filter(famille=famille).count()

        _repondre_portail(client_famille, ratt, {question: posted})
        assert PortailRenseignement.objects.filter(famille=famille).count() == avant

    def test_repondre_a_tout_le_questionnaire_en_une_fois(
        self, directeur_client, structure, activite, famille_bureau, portail_famille
    ):
        _f, _t, enfant = famille_bureau
        client_famille, ratt = portail_famille
        questions = {c: _creer_question(directeur_client, structure, activite, c, choix=CAS[c][0]) for c in CONTROLES}
        _repondre_portail(client_famille, ratt, {questions[c]: CAS[c][1] for c in CONTROLES})
        assert {c: _reponse(questions[c], enfant) for c in CONTROLES} == {c: CAS[c][2] for c in CONTROLES}

    def test_modifier_une_reponse_ne_touche_pas_les_autres(
        self, directeur_client, structure, activite, famille_bureau, portail_famille
    ):
        _f, _t, enfant = famille_bureau
        client_famille, ratt = portail_famille
        q1 = _creer_question(directeur_client, structure, activite, "bloc_texte", label="Q1")
        q2 = _creer_question(directeur_client, structure, activite, "entier", label="Q2")
        _repondre_portail(client_famille, ratt, {q1: "Premier", q2: "3"})
        _repondre_portail(client_famille, ratt, {q1: "Corrigé"})
        assert _reponse(q1, enfant) == "Corrigé"
        assert _reponse(q2, enfant) == "3"

    def test_valeur_invalide_refusee(self, directeur_client, structure, activite, famille_bureau, portail_famille):
        _f, _t, enfant = famille_bureau
        client_famille, ratt = portail_famille
        question = _creer_question(directeur_client, structure, activite, "entier")
        response = _repondre_portail(client_famille, ratt, {question: "douze"})
        assert response.status_code == 200
        assert "question_%d" % question.pk in response.context["form"].errors
        assert not _reponse(question, enfant)

    def test_choix_hors_liste_refuse(self, directeur_client, structure, activite, famille_bureau, portail_famille):
        _f, _t, enfant = famille_bureau
        client_famille, ratt = portail_famille
        question = _creer_question(directeur_client, structure, activite, "liste_deroulante", choix="A;B")
        response = _repondre_portail(client_famille, ratt, {question: "Z"})
        assert response.status_code == 200
        assert not _reponse(question, enfant)

    def test_la_famille_ne_repond_pas_pour_un_autre_enfant(self, directeur_client, structure, activite, famille_bureau):
        from tests.unit.factories import create_famille_complete

        famille, _t, _e = famille_bureau
        _u, autre, ratt_autre = create_famille_complete(username="voisins")
        response = _portail(famille).post(
            reverse("portail_individu_questionnaire_modifier", kwargs={"idrattachement": ratt_autre[1].pk}), {})
        assert response.status_code in (302, 403)


# ---------------------------------------------------------------------------
# 4. The director corrects an answer
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCorrectionDirecteur:
    @pytest.mark.parametrize("controle", CONTROLES)
    def test_le_directeur_repond_et_la_famille_voit_la_correction(
        self, directeur_client, structure, activite, famille_bureau, portail_famille, controle
    ):
        famille, _t, enfant = famille_bureau
        client_famille, ratt = portail_famille
        choix, posted, stocke, relu = CAS[controle]
        question = _creer_question(directeur_client, structure, activite, controle, choix=choix)

        response = directeur_client.post(reverse("individu_questionnaire_modifier", args=[famille.pk, enfant.pk]),
                                         {"question_%d" % question.pk: posted})
        assert response.status_code == 302
        assert _reponse(question, enfant) == stocke
        assert _affiche(_form_portail(client_famille, ratt).fields["question_%d" % question.pk]) == relu


# ---------------------------------------------------------------------------
# 5. "Réponses manquantes aux questionnaires" page of the portal
# ---------------------------------------------------------------------------

def _page_manquantes(client):
    response = client.get(reverse("portail_questionnaires"))
    assert response.status_code == 200
    return {q.pk: q for bloc in response.context["individus_forms"] for q in bloc["questions"]}


def _manquantes(client):
    return set(_page_manquantes(client))


def _repondre_page_manquantes(client, individu, question, valeur):
    return client.post(reverse("portail_questionnaires"), {
        "individu_pk": individu.pk, "question_pk": question.pk, "question_ctrl": question.controle, "valeur": valeur,
    })


def _valeur_proposee(client, question, controle):
    """What a family can actually submit on this page: free input, or one of the offered options."""
    libres = {"bloc_texte": "Allergique au pollen", "entier": "12", "decimal": "1.75", "montant": "35.50",
              "date": "2026-05-01"}
    if controle in libres:
        return libres[controle]
    options = _page_manquantes(client)[question.pk].choix_list
    souhait = {"liste_deroulante": "Moyen", "liste_coches": "Piscine", "liste_coches_ouinon": "oui"}[controle]
    return next(o for o in options if o.lower() == souhait.lower())


# What must be stored / shown back after answering on this page
ATTENDU_PAGE = {
    "bloc_texte": ("Allergique au pollen", "Allergique au pollen"),
    "entier": ("12", 12),
    "decimal": ("1.75", Decimal("1.75")),
    "montant": ("35.50", Decimal("35.50")),
    "liste_deroulante": ("Moyen", ["Moyen"]),
    "liste_coches": ("Piscine", ["Piscine"]),
    "liste_coches_ouinon": ("Oui", ["Oui"]),
    "date": ("2026-05-01", datetime.date(2026, 5, 1)),
}

BUG_RAS = ("BUG (confirmed): the 'missing answers' page appends 'RAS' to the family's own answer "
           "('Moyen' is stored 'Moyen;RAS'), so the fiche then shows 'RAS' selected as well. 'RAS' must only "
           "be an offered option. NB: tests/portail/.../test_portail_questionnaires_view.py::test_list_adds_ras "
           "asserts this buggy behaviour.")
BUG_OUINON = ("BUG: the parametrage stores choix='OUI;NON' for liste_coches_ouinon and the 'missing answers' "
              "page offers those options, while the questionnaire field uses 'Oui'/'Non': an answer given on "
              "this page ('OUI') is shown as unanswered in the fiche (portal and bureau).")
BUG_DECIMAL = ("BUG: est_question_complétée() treats int/float/complex as answered but not Decimal, which is "
               "what Get_reponse_for_ctrl() returns for decimal/montant: those questions stay 'missing' forever.")

XFAIL_RELU = {"liste_deroulante": BUG_RAS, "liste_coches": BUG_RAS, "liste_coches_ouinon": BUG_OUINON}
XFAIL_RETIREE = {"decimal": BUG_DECIMAL, "montant": BUG_DECIMAL}


def _avec_xfail(controles, raisons):
    return [pytest.param(c, marks=pytest.mark.xfail(strict=True, reason=raisons[c])) if c in raisons else c
            for c in controles]


@pytest.mark.django_db
class TestPageReponsesManquantes:
    @pytest.mark.parametrize("controle", CONTROLES)
    def test_question_sans_reponse_listee(self, directeur_client, structure, activite, portail_famille, controle):
        client_famille, _ratt = portail_famille
        question = _creer_question(directeur_client, structure, activite, controle, choix=CAS[controle][0])
        assert question.pk in _manquantes(client_famille)

    def test_question_d_une_autre_activite_non_listee(self, directeur_client, structure, portail_famille):
        client_famille, _ratt = portail_famille
        question = _creer_question(directeur_client, structure, ActiviteFactory(structure=structure), "bloc_texte")
        assert question.pk not in _manquantes(client_famille)

    def test_reponse_donnee_dans_la_fiche_retire_la_question(
        self, directeur_client, structure, activite, portail_famille
    ):
        client_famille, ratt = portail_famille
        question = _creer_question(directeur_client, structure, activite, "bloc_texte")
        _repondre_portail(client_famille, ratt, {question: "Rien de spécial"})
        assert question.pk not in _manquantes(client_famille)

    @pytest.mark.parametrize("controle", _avec_xfail(CONTROLES, XFAIL_RETIREE))
    def test_repondre_retire_la_question_de_la_liste(
        self, directeur_client, structure, activite, famille_bureau, portail_famille, controle
    ):
        _f, _t, enfant = famille_bureau
        client_famille, _ratt = portail_famille
        question = _creer_question(directeur_client, structure, activite, controle, choix=CAS[controle][0])
        valeur = _valeur_proposee(client_famille, question, controle)
        response = _repondre_page_manquantes(client_famille, enfant, question, valeur)
        assert response.status_code == 302
        assert question.pk not in _manquantes(client_famille)

    @pytest.mark.parametrize("controle", _avec_xfail(CONTROLES, XFAIL_RELU))
    def test_reponse_de_la_page_relue_dans_la_fiche(
        self, directeur_client, structure, activite, famille_bureau, portail_famille, controle
    ):
        """An answer given on the 'missing answers' page must look the same as one given in the
        questionnaire tab: same stored value, same pre-filled field (portal and bureau)."""
        famille, _t, enfant = famille_bureau
        client_famille, ratt = portail_famille
        question = _creer_question(directeur_client, structure, activite, controle, choix=CAS[controle][0])
        _repondre_page_manquantes(client_famille, enfant, question, _valeur_proposee(client_famille, question, controle))

        stocke, relu = ATTENDU_PAGE[controle]
        assert _reponse(question, enfant) == stocke
        assert _affiche(_form_portail(client_famille, ratt).fields["question_%d" % question.pk]) == relu
        assert _affiche(_form_bureau(directeur_client, famille, enfant).fields["question_%d" % question.pk]) == relu

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (confirmed): a 'Sélection multiple' question is rendered as a single <select name='valeur'> "
        "and the view reads request.POST.get('valeur'): only one option can be chosen on this page, "
        "whereas the questionnaire tab allows several."
    ))
    def test_selection_multiple_plusieurs_choix(self, directeur_client, structure, activite, famille_bureau,
                                                portail_famille):
        _f, _t, enfant = famille_bureau
        client_famille, _ratt = portail_famille
        question = _creer_question(directeur_client, structure, activite, "liste_coches", choix=CAS["liste_coches"][0])
        client_famille.post(reverse("portail_questionnaires"), {
            "individu_pk": enfant.pk, "question_pk": question.pk, "question_ctrl": "liste_coches",
            "valeur": ["Piscine", "Escalade"],
        })
        assert _reponse(question, enfant) == "Piscine;Escalade"

    def test_ne_peut_pas_repondre_pour_l_enfant_d_une_autre_famille(
        self, directeur_client, structure, activite, portail_famille
    ):
        from tests.unit.factories import create_famille_complete

        client_famille, _ratt = portail_famille
        question = _creer_question(directeur_client, structure, activite, "bloc_texte")
        _u, _autre, ratt_autre = create_famille_complete(username="voisins")
        _repondre_page_manquantes(client_famille, ratt_autre[1].individu, question, "Piraté")
        assert _reponse(question, ratt_autre[1].individu) != "Piraté"

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the 'missing answers' page saves any question_pk it receives: a family can answer (or "
        "overwrite) questions of activities its child is not inscribed in, even of other structures."
    ))
    def test_ne_peut_pas_repondre_a_une_question_qui_ne_le_concerne_pas(
        self, directeur_client, structure, famille_bureau, portail_famille
    ):
        _f, _t, enfant = famille_bureau
        client_famille, _ratt = portail_famille
        question = _creer_question(directeur_client, structure, ActiviteFactory(structure=structure), "bloc_texte")
        _repondre_page_manquantes(client_famille, enfant, question, "Hors sujet")
        assert _reponse(question, enfant) != "Hors sujet"
