"""Director's questionnaire lists (Individus > Questionnaires), fed by real family answers.

- "Liste des questionnaires individuels": pick a question, see every child's answer;
- "Modification groupée des réponses": edit many answers at once, then save (validation view);
- "Relance": prepare an email to the families who have not answered yet.

Answers are given by the families on the portal (end to end), then read and edited by
the director; edited answers must still be read correctly by the family afterwards.
"""

import json

import pytest
from core.models import Destinataire, Mail, QuestionnaireReponse
from django.test import Client
from django.urls import reverse
from tests.bureau.conftest import AJAX
from tests.bureau.helpers_questionnaires import CAS, affiche, creer_question, form_portail, portail, ratt_enfant, \
    repondre_portail
from tests.unit.factories import ActiviteFactory, InscriptionFactory, StructureFactory, UtilisateurFactory, \
    create_famille_complete

XSS = "<img src=x onerror=alert(1)>"
XSS_ATTRIBUT = "x' onmouseover='alert(1)"


@pytest.fixture
def deux_familles(famille_bureau, activite):
    """famille_bureau (child Premier) + a second family (child Second) inscribed on the same activity."""
    famille_a, _t, enfant_a = famille_bureau
    famille_a.mail = "a@test.org"
    famille_a.save()
    _u, famille_b, ratt_b = create_famille_complete(username="famille_b")
    enfant_b = ratt_b[1].individu
    enfant_b.prenom = "Second"
    enfant_b.save()
    famille_b.mail = "b@test.org"
    famille_b.save()
    InscriptionFactory(famille=famille_b, individu=enfant_b, activite=activite)
    return (famille_a, enfant_a), (famille_b, enfant_b)


def _question_sans_activite(structure, controle="bloc_texte"):
    """Legacy question without activity: the parametrage now requires an activity, but such questions
    exist in the data and every screen still has a code path for them."""
    from core.models import QuestionnaireQuestion

    return QuestionnaireQuestion.objects.create(categorie="individu", ordre=99, label="Question générale",
                                                controle=controle, structure=structure, activite=None)


def _repondre(famille, enfant, question, valeur):
    response = repondre_portail(portail(famille), ratt_enfant(famille, enfant), {question: valeur})
    assert response.status_code == 302
    return response


def _reponse(question, individu):
    reponse = QuestionnaireReponse.objects.filter(question=question, individu=individu).first()
    return reponse.reponse if reponse else None


# ---------------------------------------------------------------------------
# Consultation list
# ---------------------------------------------------------------------------

def _lignes(client, question):
    response = client.get(reverse("questionnaires_individus_liste", kwargs={"categorie": question.pk}))
    assert response.status_code == 200
    return {(nom, prenom): reponse for nom, prenom, reponse in response.context["datatable"].lignes}, response


BUG_DECIMAL = ("BUG: Get_reponse_fr() returns a float for decimal/montant answers and Formate_reponse() calls "
               ".lower() on it: as soon as one family answered, the director's list (and the grouped edition "
               "page) of that question crashes (500).")

AFFICHAGE_LISTE = {
    "bloc_texte": "Allergique au pollen",
    "entier": "12",
    "decimal": 1.75,
    "montant": 35.5,
    "liste_deroulante": "Moyen",
    "liste_coches": "Piscine, Escalade",
    "date": "2026-05-01",
}


@pytest.mark.django_db
class TestListeConsultation:
    def test_page_sans_question_selectionnee(self, directeur_client):
        response = directeur_client.get(reverse("questionnaires_individus_liste"))
        assert response.status_code == 200
        assert response.context["datatable"] == ""

    def test_mes_questions_sont_proposees(self, directeur_client, structure, activite):
        question = creer_question(directeur_client, structure, activite, "bloc_texte", label="Taille de t-shirt")
        choix = dict(directeur_client.get(reverse("questionnaires_individus_liste")).context["liste_categories"])
        assert choix[question.pk] == "Individu : Taille de t-shirt"

    @pytest.mark.parametrize("controle", [
        pytest.param(c, marks=pytest.mark.xfail(strict=True, raises=AttributeError, reason=BUG_DECIMAL))
        if c in ("decimal", "montant") else c for c in AFFICHAGE_LISTE
    ])
    def test_reponse_de_chaque_famille_affichee(self, directeur_client, structure, activite, deux_familles,
                                                controle):
        (famille_a, enfant_a), (famille_b, enfant_b) = deux_familles
        choix, posted, _stocke, _relu = CAS[controle]
        question = creer_question(directeur_client, structure, activite, controle, choix=choix)
        _repondre(famille_a, enfant_a, question, posted)
        _repondre(famille_b, enfant_b, question, posted)

        lignes, _r = _lignes(directeur_client, question)
        assert lignes == {(enfant_a.nom, enfant_a.prenom): AFFICHAGE_LISTE[controle],
                          (enfant_b.nom, enfant_b.prenom): AFFICHAGE_LISTE[controle]}

    def test_oui_non_affiche_en_badge(self, directeur_client, structure, activite, deux_familles):
        (famille_a, enfant_a), _b = deux_familles
        question = creer_question(directeur_client, structure, activite, "liste_coches_ouinon")
        _repondre(famille_a, enfant_a, question, ["Non"])
        lignes, _r = _lignes(directeur_client, question)
        assert "badge-danger" in lignes[(enfant_a.nom, enfant_a.prenom)]

    def test_enfant_d_une_autre_activite_non_liste(self, directeur_client, structure, activite, deux_familles):
        (famille_a, enfant_a), (famille_b, enfant_b) = deux_familles
        question = creer_question(directeur_client, structure, activite, "bloc_texte")
        _repondre(famille_a, enfant_a, question, "Réponse A")
        # A stray answer for a child not inscribed in the question's activity
        autre = create_famille_complete(username="hors_activite")[2][1].individu
        QuestionnaireReponse.objects.create(question=question, individu=autre, reponse="Hors activité")
        lignes, _r = _lignes(directeur_client, question)
        assert set(lignes) == {(enfant_a.nom, enfant_a.prenom)}

    @pytest.mark.xfail(strict=True, reason=(
        "À CONFIRMER: the list only shows children who already have an answer row; a child inscribed in "
        "the activity who never opened the questionnaire does not appear at all, so the director cannot "
        "see who is missing from this screen (only the 'Relance' button knows)."
    ))
    def test_enfant_sans_reponse_apparait_vide(self, directeur_client, structure, activite, deux_familles):
        (famille_a, enfant_a), (_famille_b, enfant_b) = deux_familles
        question = creer_question(directeur_client, structure, activite, "bloc_texte")
        _repondre(famille_a, enfant_a, question, "Réponse A")
        lignes, _r = _lignes(directeur_client, question)
        assert lignes.get((enfant_b.nom, enfant_b.prenom), "absent") in ("", None)

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (XSS): family answers are injected unescaped into the director's list (Formate_reponse output "
        "is rendered as HTML), so a family can run JavaScript in the director's session."
    ))
    def test_reponse_html_echappee(self, directeur_client, structure, activite, deux_familles):
        (famille_a, enfant_a), _b = deux_familles
        question = creer_question(directeur_client, structure, activite, "bloc_texte")
        _repondre(famille_a, enfant_a, question, XSS)
        _l, response = _lignes(directeur_client, question)
        assert XSS not in response.content.decode()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (directors are limited to their structures): the question id in the URL is not checked, so a "
        "director can list the answers to another structure's question."
    ))
    def test_question_d_une_autre_structure_interdite(self, directeur_client, deux_familles):
        (famille_a, enfant_a), _b = deux_familles
        voisine = StructureFactory()
        activite_voisine = ActiviteFactory(structure=voisine)
        InscriptionFactory(famille=famille_a, individu=enfant_a, activite=activite_voisine)
        collegue = UtilisateurFactory(username="voisin")
        collegue.structures.add(voisine)
        client_voisin = Client()
        client_voisin.force_login(collegue)
        question = creer_question(client_voisin, voisine, activite_voisine, "bloc_texte")
        _repondre(famille_a, enfant_a, question, "Confidentiel")

        response = directeur_client.get(reverse("questionnaires_individus_liste", kwargs={"categorie": question.pk}))
        assert response.status_code in (403, 404) or "Confidentiel" not in str(response.context["datatable"].lignes)


# ---------------------------------------------------------------------------
# Grouped edition
# ---------------------------------------------------------------------------

def _page_modif(client, question):
    response = client.get(reverse("questionnaires_individus_modif", kwargs={"categorie": question.pk}))
    assert response.status_code == 200
    return response


def _valider(client, question, data):
    return client.post(reverse("questionnaires_individus_modif_valid", kwargs={"categorie": question.pk}), data)


def _id(question, individu):
    return QuestionnaireReponse.objects.get(question=question, individu=individu).pk


@pytest.mark.django_db
class TestModificationGroupee:
    def test_page_affiche_un_champ_par_reponse(self, directeur_client, structure, activite, deux_familles):
        (famille_a, enfant_a), (famille_b, enfant_b) = deux_familles
        question = creer_question(directeur_client, structure, activite, "entier")
        _repondre(famille_a, enfant_a, question, "7")
        _repondre(famille_b, enfant_b, question, "9")
        html = _page_modif(directeur_client, question).content.decode()
        assert "name='reponse_%d' value='7'" % _id(question, enfant_a) in html
        assert "name='reponse_%d' value='9'" % _id(question, enfant_b) in html

    @pytest.mark.xfail(strict=True, raises=AttributeError, reason=BUG_DECIMAL)
    @pytest.mark.parametrize("controle", ["decimal", "montant"])
    def test_page_de_modification_d_une_question_decimale(self, directeur_client, structure, activite,
                                                          deux_familles, controle):
        (famille_a, enfant_a), _b = deux_familles
        question = creer_question(directeur_client, structure, activite, controle)
        _repondre(famille_a, enfant_a, question, CAS[controle][1])
        _page_modif(directeur_client, question)

    @pytest.mark.parametrize("controle, nouvelle, stocke, relu", [
        ("bloc_texte", "Plus d'allergie", "Plus d'allergie", "Plus d'allergie"),
        ("entier", "13", "13", 13),
        ("decimal", "2,5", "2.5", __import__("decimal").Decimal("2.5")),
        ("liste_deroulante", "Grand", "Grand", ["Grand"]),
    ])
    def test_modifier_une_reponse_puis_la_famille_la_voit(
        self, directeur_client, structure, activite, deux_familles, controle, nouvelle, stocke, relu
    ):
        (famille_a, enfant_a), (famille_b, enfant_b) = deux_familles
        choix, posted, ancien, _relu = CAS[controle]
        question = creer_question(directeur_client, structure, activite, controle, choix=choix)
        _repondre(famille_a, enfant_a, question, posted)
        _repondre(famille_b, enfant_b, question, posted)

        response = _valider(directeur_client, question, {
            "reponse_%d" % _id(question, enfant_a): nouvelle,
            "reponse_%d" % _id(question, enfant_b): ancien,
        })
        assert response["Location"] == reverse("questionnaires_individus_modif", kwargs={"categorie": question.pk})
        assert _reponse(question, enfant_a) == stocke
        assert _reponse(question, enfant_b) == ancien
        champ = form_portail(portail(famille_a), ratt_enfant(famille_a, enfant_a)).fields["question_%d" % question.pk]
        assert affiche(champ) == relu

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the grouped edition saves 'Sélection multiple' answers joined with ', ' instead of ';' "
        "('Piscine, Vélo'), so the family's (and director's) questionnaire tab no longer shows any "
        "option selected."
    ))
    def test_modifier_une_selection_multiple(self, directeur_client, structure, activite, deux_familles):
        (famille_a, enfant_a), _b = deux_familles
        question = creer_question(directeur_client, structure, activite, "liste_coches", choix=CAS["liste_coches"][0])
        _repondre(famille_a, enfant_a, question, ["Piscine"])
        idr = _id(question, enfant_a)
        _valider(directeur_client, question, {"reponse_%d_Piscine" % idr: "on", "reponse_%d_Vélo" % idr: "on"})
        assert _reponse(question, enfant_a) == "Piscine;Vélo"
        champ = form_portail(portail(famille_a), ratt_enfant(famille_a, enfant_a)).fields["question_%d" % question.pk]
        assert affiche(champ) == ["Piscine", "Vélo"]

    def test_cases_de_la_selection_multiple_precochees(self, directeur_client, structure, activite, deux_familles):
        (famille_a, enfant_a), _b = deux_familles
        question = creer_question(directeur_client, structure, activite, "liste_coches", choix=CAS["liste_coches"][0])
        _repondre(famille_a, enfant_a, question, ["Piscine", "Escalade"])
        html = _page_modif(directeur_client, question).content.decode()
        idr = _id(question, enfant_a)
        assert "name='reponse_%d_Piscine' checked" % idr in html
        assert "name='reponse_%d_Escalade' checked" % idr in html
        assert "name='reponse_%d_Vélo'  />" % idr in html

    def test_entier_invalide_ignore(self, directeur_client, structure, activite, deux_familles):
        (famille_a, enfant_a), _b = deux_familles
        question = creer_question(directeur_client, structure, activite, "entier")
        _repondre(famille_a, enfant_a, question, "7")
        _valider(directeur_client, question, {"reponse_%d" % _id(question, enfant_a): "sept"})
        assert _reponse(question, enfant_a) == "7"

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the page invites the director to filter the list before editing, but the validation view "
        "loops over ALL answers of the question and reads a missing field as '' : every answer not "
        "displayed (filtered out) is erased."
    ))
    def test_les_reponses_non_affichees_ne_sont_pas_effacees(self, directeur_client, structure, activite,
                                                             deux_familles):
        (famille_a, enfant_a), (famille_b, enfant_b) = deux_familles
        question = creer_question(directeur_client, structure, activite, "bloc_texte")
        _repondre(famille_a, enfant_a, question, "Réponse A")
        _repondre(famille_b, enfant_b, question, "Réponse B")
        # The director filtered the list on child A: only A's field is posted
        _valider(directeur_client, question, {"reponse_%d" % _id(question, enfant_a): "Corrigée"})
        assert _reponse(question, enfant_b) == "Réponse B"

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: a 'Liste déroulante' answer is edited in a free text input and saved as typed: a value outside "
        "the choices makes the question look unanswered in the family's questionnaire tab."
    ))
    def test_liste_deroulante_hors_choix_refusee(self, directeur_client, structure, activite, deux_familles):
        (famille_a, enfant_a), _b = deux_familles
        question = creer_question(directeur_client, structure, activite, "liste_deroulante",
                                  choix=CAS["liste_deroulante"][0])
        _repondre(famille_a, enfant_a, question, "Moyen")
        _valider(directeur_client, question, {"reponse_%d" % _id(question, enfant_a): "Géant"})
        assert _reponse(question, enfant_a) == "Moyen"

    @pytest.mark.xfail(strict=True, raises=NameError, reason=(
        "BUG: for a question without activity, the validation view never defines 'individus_inscrits' "
        "(it is only set in the else branch): saving crashes with a NameError (500)."
    ))
    def test_question_sans_activite(self, directeur_client, structure, deux_familles):
        (famille_a, enfant_a), _b = deux_familles
        question = _question_sans_activite(structure)
        QuestionnaireReponse.objects.create(question=question, individu=enfant_a, reponse="Avant")
        response = _valider(directeur_client, question, {"reponse_%d" % _id(question, enfant_a): "Après"})
        assert response.status_code == 302

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (XSS): answers are written into value='...' (single-quoted, unescaped) and rendered |safe: "
        "a family answer containing a quote injects attributes (event handlers) into the director's page."
    ))
    def test_reponse_avec_apostrophe_echappee(self, directeur_client, structure, activite, deux_familles):
        (famille_a, enfant_a), _b = deux_familles
        question = creer_question(directeur_client, structure, activite, "bloc_texte")
        _repondre(famille_a, enfant_a, question, XSS_ATTRIBUT)
        html = _page_modif(directeur_client, question).content.decode()
        assert "onmouseover='alert(1)'" not in html

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (security): the validation view is a plain django View with no login / category check: an "
        "anonymous visitor can overwrite every answer of a question."
    ))
    def test_validation_refusee_aux_anonymes(self, directeur_client, structure, activite, deux_familles):
        (famille_a, enfant_a), _b = deux_familles
        question = creer_question(directeur_client, structure, activite, "bloc_texte")
        _repondre(famille_a, enfant_a, question, "Vraie réponse")
        # NB: a fresh Client — pytest-django's `client` is the same object as directeur_client
        _valider(Client(), question, {"reponse_%d" % _id(question, enfant_a): "Piratée"})
        assert _reponse(question, enfant_a) == "Vraie réponse"

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (security): same view, a family account can overwrite other families' answers."
    ))
    def test_validation_refusee_aux_familles(self, directeur_client, structure, activite, deux_familles):
        (famille_a, enfant_a), (famille_b, _enfant_b) = deux_familles
        question = creer_question(directeur_client, structure, activite, "bloc_texte")
        _repondre(famille_a, enfant_a, question, "Vraie réponse")
        _valider(portail(famille_b), question, {"reponse_%d" % _id(question, enfant_a): "Piratée"})
        assert _reponse(question, enfant_a) == "Vraie réponse"

    def test_page_reservee_au_staff(self, structure, activite, deux_familles, directeur_client):
        (famille_a, _e), _b = deux_familles
        question = creer_question(directeur_client, structure, activite, "bloc_texte")
        url = reverse("questionnaires_individus_modif", kwargs={"categorie": question.pk})
        assert Client().get(url).status_code == 302
        assert portail(famille_a).get(url).status_code == 403


# ---------------------------------------------------------------------------
# Reminder ("Relance")
# ---------------------------------------------------------------------------

def _relancer(client, question=None):
    categorie = reverse("questionnaires_individus_liste", kwargs={"categorie": question.pk}) if question \
        else reverse("questionnaires_individus_liste")
    return client.post(reverse("ajax_get_relance"), {"categorie": categorie}, **AJAX)


def _destinataires(mail):
    return {(d.famille_id, json.loads(d.valeurs)["{INDIVIDU}"]) for d in mail.destinataires.all()}


@pytest.mark.django_db
class TestRelance:
    def test_aucune_question_selectionnee(self, directeur_client):
        response = _relancer(directeur_client)
        assert response.status_code == 401
        assert "sélectionner une question" in response.json()["erreur"]

    def test_relance_les_familles_sans_reponse(self, directeur_client, directeur, structure, activite, deux_familles):
        (famille_a, enfant_a), (famille_b, enfant_b) = deux_familles
        question = creer_question(directeur_client, structure, activite, "bloc_texte")
        _repondre(famille_a, enfant_a, question, "Répondu")

        response = _relancer(directeur_client, question)
        mail = Mail.objects.get(categorie="rappel_reponses_manquantes")
        assert response.json()["url"] == reverse("editeur_emails", kwargs={"pk": mail.pk})
        assert mail.utilisateur == directeur
        assert mail.verrouillage_destinataires
        assert _destinataires(mail) == {(famille_b.pk, enfant_b.prenom)}
        assert mail.destinataires.get().adresse == "b@test.org"

    def test_reponse_vide_compte_comme_manquante(self, directeur_client, structure, activite, deux_familles):
        (famille_a, enfant_a), (famille_b, enfant_b) = deux_familles
        question = creer_question(directeur_client, structure, activite, "bloc_texte")
        _repondre(famille_a, enfant_a, question, "Répondu")
        QuestionnaireReponse.objects.create(question=question, individu=enfant_b, reponse="")
        _relancer(directeur_client, question)
        assert _destinataires(Mail.objects.get()) == {(famille_b.pk, enfant_b.prenom)}

    def test_tout_le_monde_a_repondu(self, directeur_client, structure, activite, deux_familles):
        (famille_a, enfant_a), (famille_b, enfant_b) = deux_familles
        question = creer_question(directeur_client, structure, activite, "bloc_texte")
        _repondre(famille_a, enfant_a, question, "A")
        _repondre(famille_b, enfant_b, question, "B")
        response = _relancer(directeur_client, question)
        assert response.status_code == 401
        assert not Mail.objects.exists()

    def test_famille_sans_email_signalee(self, directeur_client, structure, activite, deux_familles):
        (famille_a, enfant_a), (famille_b, _enfant_b) = deux_familles
        famille_b.mail = ""
        famille_b.save()
        question = creer_question(directeur_client, structure, activite, "bloc_texte")
        _repondre(famille_a, enfant_a, question, "A")
        _relancer(directeur_client, question)
        assert Mail.objects.get().destinataires.count() == 0
        messages = [str(m) for m in directeur_client.get(reverse("questionnaires_individus_liste")).context["messages"]]
        assert any("Adresses mail manquantes" in m and famille_b.nom in m for m in messages)

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: a family is excluded from the reminder as soon as ONE of its children answered; a sibling "
        "inscribed in the same activity who has not answered is never reminded."
    ))
    def test_relance_le_frere_qui_n_a_pas_repondu(self, directeur_client, structure, activite, deux_familles):
        from core.models import Rattachement
        from tests.unit.factories import IndividuFactory

        (famille_a, enfant_a), _b = deux_familles
        cadet = IndividuFactory(nom="Enfant", prenom="Cadet")
        Rattachement.objects.create(famille=famille_a, individu=cadet, categorie=2)
        InscriptionFactory(famille=famille_a, individu=cadet, activite=activite)
        question = creer_question(directeur_client, structure, activite, "bloc_texte")
        _repondre(famille_a, enfant_a, question, "Aîné a répondu")
        _relancer(directeur_client, question)
        assert (famille_a.pk, "Cadet") in _destinataires(Mail.objects.get())

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: for a question without activity the reminder looks for inscriptions with activite=None and "
        "always answers 'Aucune famille ... à relancer'."
    ))
    def test_relance_question_sans_activite(self, directeur_client, structure, deux_familles):
        (famille_a, enfant_a), (famille_b, enfant_b) = deux_familles
        for enfant in (enfant_a, enfant_b):
            enfant.statut = 5
            enfant.save()
        question = _question_sans_activite(structure)
        QuestionnaireReponse.objects.create(question=question, individu=enfant_a, reponse="A")
        response = _relancer(directeur_client, question)
        assert response.status_code == 200

    def test_relance_requiert_ajax(self, directeur_client, structure, activite, deux_familles):
        question = creer_question(directeur_client, structure, activite, "bloc_texte")
        response = directeur_client.post(reverse("ajax_get_relance"), {"categorie": "x/%d" % question.pk})
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Family questionnaires list (category not offered in the parametrage, page must still work)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_liste_questionnaires_familles(directeur_client):
    assert directeur_client.get(reverse("questionnaires_familles_liste")).status_code == 200
