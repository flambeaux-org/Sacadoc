"""Formulaires (sondages), end to end:

1. the staff builds a formulaire in Paramétrage > Formulaires: the formulaire itself, then pages
   and questions through the AJAX builder, with every answer type;
2. the family sees it on the portal ("Sondages manquants"), picks the child and answers;
3. the director reads the answers in the fiche famille "Formulaires" tab and in
   Individus > Formulaires (detail / table / CSV export / summary).
"""

import csv
import json
import io

import pytest
from core.models import (
    LISTE_CONTROLES_QUESTIONNAIRES,
    Sondage,
    SondagePage,
    SondageQuestion,
    SondageRepondant,
    SondageReponse,
    Utilisateur,
)
from django.test import Client, RequestFactory
from django.urls import reverse
from tests.bureau.conftest import AJAX
from tests.bureau.helpers_questionnaires import CAS, affiche
from tests.unit.factories import ActiviteFactory, InscriptionFactory, StructureFactory

CONTROLES = [ctrl["code"] for ctrl in LISTE_CONTROLES_QUESTIONNAIRES]


# ---------------------------------------------------------------------------
# Staff side: building the formulaire with the real screens
# ---------------------------------------------------------------------------

def _creer_formulaire(client, structure, titre="Fiche de rentrée", public="individu", categories=("2",),
                      conclusion="<p>Merci pour vos réponses</p>", modifiable=True):
    data = {"titre": titre, "description": "<p>Quelques questions</p>", "conclusion": conclusion,
            "public": public, "categories_rattachements": list(categories), "structure": structure.pk}
    if modifiable:
        data["modifiable"] = "on"
    response = client.post(reverse("sondages_ajouter"), data)
    assert response.status_code == 302, response.context["form"].errors.as_json() if response.context else response
    sondage = Sondage.objects.get(titre=titre)
    assert response["Location"] == reverse("sondages_consulter", kwargs={"pk": sondage.pk})
    return sondage


def _ajouter_page(client, sondage, titre=None):
    form = client.post(reverse("ajax_sondages_get_form_page"), {"idsondage": sondage.pk}, **AJAX)
    assert form.status_code == 200
    ordre = SondagePage.objects.filter(sondage=sondage).count() + 1
    response = client.post(reverse("ajax_sondages_valid_form_page"), {
        "sondage": sondage.pk, "ordre": ordre, "idpage": "None", "titre": titre or "Page %d" % ordre,
        "description": "",
    }, **AJAX)
    assert response.status_code == 200, response.content
    return SondagePage.objects.get(pk=response.json()["id_page"])


def _ajouter_question(client, page, controle, label=None, choix=None, obligatoire=False):
    ordre = SondageQuestion.objects.filter(page=page).count() + 1
    data = {"page": page.pk, "ordre": ordre, "idquestion": "None", "label": "Question %s" % controle if label is None else label,
            "controle": controle, "choix": choix or "", "texte_aide": ""}
    if obligatoire:
        data["obligatoire"] = "on"
    response = client.post(reverse("ajax_sondages_valid_form_question"), data, **AJAX)
    return response


def _question(client, page, controle, **kwargs):
    response = _ajouter_question(client, page, controle, choix=CAS[controle][0], **kwargs)
    assert response.status_code == 200, response.content
    return SondageQuestion.objects.get(pk=response.json()["id_question"])


@pytest.fixture
def formulaire_complet(directeur_client, structure, famille_bureau):
    """A formulaire for children, with one question of each answer type on one page."""
    sondage = _creer_formulaire(directeur_client, structure)
    page = _ajouter_page(directeur_client, sondage)
    questions = {c: _question(directeur_client, page, c) for c in CONTROLES}
    return sondage, questions


# ---------------------------------------------------------------------------
# Family side
# ---------------------------------------------------------------------------

def _portail(famille):
    client = Client()
    client.force_login(Utilisateur.objects.get(pk=famille.utilisateur_id))
    return client


def _url_questions(sondage, individu=None):
    kwargs = {"code": sondage.code}
    if individu:
        kwargs["idindividu"] = individu.pk
    return reverse("portail_sondage_questions", kwargs=kwargs)


def _repondre(client, sondage, individu, reponses):
    data = {"question_%d" % q.pk: v for q, v in reponses.items()}
    return client.post(_url_questions(sondage, individu), data)


def _champs_portail(client, sondage, individu=None):
    response = client.get(_url_questions(sondage, individu))
    assert response.status_code == 200
    champs = {}
    for _page, form in response.context["pages"]:
        champs.update(form.fields)
    return champs


def _sondages_a_completer(client):
    response = client.get(reverse("portail_sondages"))
    assert response.status_code == 200
    return response.context


# ---------------------------------------------------------------------------
# 1. Building the formulaire
# ---------------------------------------------------------------------------

def test_tous_les_types_proposes_sont_couverts():
    assert set(CAS) == set(CONTROLES)


@pytest.mark.django_db
class TestConstructionFormulaire:
    def test_creer_un_formulaire(self, directeur_client, structure):
        sondage = _creer_formulaire(directeur_client, structure)
        assert sondage.public == "individu"
        assert list(sondage.categories_rattachements) == ["2"]
        assert sondage.modifiable
        assert sondage.structure == structure
        assert sondage.code  # unique code used in the portal URL

    def test_page_de_construction(self, directeur_client, formulaire_complet):
        import json

        sondage, questions = formulaire_complet
        response = directeur_client.get(reverse("sondages_consulter", kwargs={"pk": sondage.pk}))
        assert response.status_code == 200
        donnees = json.loads(response.context["donnees"])
        assert [q["id_question"] for q in donnees[0]["questions"]] == [q.pk for q in questions.values()]

    @pytest.mark.parametrize("controle", CONTROLES)
    def test_ajouter_une_question_de_chaque_type(self, directeur_client, structure, controle):
        page = _ajouter_page(directeur_client, _creer_formulaire(directeur_client, structure))
        question = _question(directeur_client, page, controle, obligatoire=True)
        assert question.controle == controle
        assert question.obligatoire
        assert question.ordre == 1

    def test_pages_numerotees_a_la_suite(self, directeur_client, structure):
        sondage = _creer_formulaire(directeur_client, structure)
        p1, p2 = _ajouter_page(directeur_client, sondage), _ajouter_page(directeur_client, sondage)
        assert (p1.ordre, p2.ordre) == (1, 2)
        assert p2.titre == "Page 2"

    @pytest.mark.xfail(strict=True, raises=TypeError, reason=(
        "BUG: Valid_form_question joins the form error messages with ', '.join(); Django's default "
        "'This field is required' message is a lazy string, so leaving the label empty crashes (500) "
        "instead of showing the error in the builder."
    ))
    def test_question_sans_libelle_refusee(self, directeur_client, structure):
        page = _ajouter_page(directeur_client, _creer_formulaire(directeur_client, structure))
        response = _ajouter_question(directeur_client, page, "bloc_texte", label="")
        assert response.status_code == 401
        assert not SondageQuestion.objects.filter(page=page).exists()

    @pytest.mark.xfail(strict=True, raises=TypeError, reason=(
        "BUG: same as for questions — Valid_form_page crashes (500) on an empty page title."
    ))
    def test_page_sans_titre_refusee(self, directeur_client, structure):
        sondage = _creer_formulaire(directeur_client, structure)
        response = directeur_client.post(reverse("ajax_sondages_valid_form_page"), {
            "sondage": sondage.pk, "ordre": 1, "idpage": "None", "titre": "", "description": ""}, **AJAX)
        assert response.status_code == 401

    @pytest.mark.parametrize("controle", ["liste_deroulante", "liste_coches"])
    def test_liste_sans_choix_refusee(self, directeur_client, structure, controle):
        """Without choices the portal could not build the field: the builder must refuse it."""
        page = _ajouter_page(directeur_client, _creer_formulaire(directeur_client, structure))
        response = _ajouter_question(directeur_client, page, controle, choix="")
        assert response.status_code == 401
        assert "au moins un choix" in response.json()["erreur"]
        assert not SondageQuestion.objects.filter(page=page).exists()

    def test_modifier_une_question(self, directeur_client, formulaire_complet):
        _sondage, questions = formulaire_complet
        question = questions["bloc_texte"]
        response = directeur_client.post(reverse("ajax_sondages_valid_form_question"), {
            "page": question.page_id, "ordre": question.ordre, "idquestion": question.pk,
            "label": "Libellé corrigé", "controle": "bloc_texte", "choix": "", "texte_aide": "",
        }, **AJAX)
        assert response.json()["nouvelle_question"] is False
        question.refresh_from_db()
        assert question.label == "Libellé corrigé"

    def test_reorganiser_les_questions(self, directeur_client, formulaire_complet):
        import json

        sondage, questions = formulaire_complet
        q1, q2 = questions["bloc_texte"], questions["entier"]
        directeur_client.post(reverse("ajax_sondages_reorganiser"), {
            "donnee": "question", "idsondage": sondage.pk,
            "nouvel_ordre": json.dumps([[q1.page_id, ["question_%d" % q2.pk, "question_%d" % q1.pk]]]),
        }, **AJAX)
        q1.refresh_from_db()
        q2.refresh_from_db()
        assert (q2.ordre, q1.ordre) == (1, 2)

    def test_supprimer_une_question(self, directeur_client, formulaire_complet):
        _sondage, questions = formulaire_complet
        question = questions["date"]
        directeur_client.post(reverse("ajax_sondages_supprimer_question"), {"idquestion": question.pk}, **AJAX)
        assert not SondageQuestion.objects.filter(pk=question.pk).exists()

    def test_supprimer_une_page_supprime_ses_questions(self, directeur_client, formulaire_complet):
        _sondage, questions = formulaire_complet
        page_id = questions["date"].page_id
        directeur_client.post(reverse("ajax_sondages_supprimer_page"), {"idpage": page_id}, **AJAX)
        assert not SondageQuestion.objects.filter(page_id=page_id).exists()

    def test_constructeur_reserve_au_staff(self, famille_bureau, formulaire_complet):
        famille, _t, _e = famille_bureau
        sondage, _q = formulaire_complet
        response = _portail(famille).post(reverse("ajax_sondages_valid_form_page"),
                                          {"sondage": sondage.pk, "ordre": 9, "idpage": "None", "titre": "Pirate"},
                                          **AJAX)
        assert response.status_code == 403
        assert not SondagePage.objects.filter(titre="Pirate").exists()


# ---------------------------------------------------------------------------
# 2. The family answers
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestReponseFamille:
    def test_le_formulaire_apparait_dans_les_sondages_a_completer(self, famille_bureau, formulaire_complet):
        famille, _t, enfant = famille_bureau
        sondage, _q = formulaire_complet
        context = _sondages_a_completer(_portail(famille))
        bloc = next(s for s in context["sondages_individu"] if s["code"] == sondage.code)
        assert bloc["individus"] == [enfant]

    def test_formulaire_d_une_structure_sans_inscription_absent(self, directeur_client, famille_bureau):
        from tests.unit.factories import UtilisateurFactory

        famille, _t, _e = famille_bureau
        voisine = StructureFactory()
        collegue = UtilisateurFactory(username="voisin")
        collegue.structures.add(voisine)
        client_voisin = Client()
        client_voisin.force_login(collegue)
        sondage = _creer_formulaire(client_voisin, voisine, titre="Formulaire voisin")
        codes = [s["code"] for s in _sondages_a_completer(_portail(famille))["sondages_individu"]]
        assert sondage.code not in codes

    def test_introduction_ne_propose_que_les_enfants(self, famille_bureau, formulaire_complet):
        famille, _t, enfant = famille_bureau
        sondage, _q = formulaire_complet
        response = _portail(famille).get(reverse("portail_sondage", kwargs={"code": sondage.code}))
        assert [r.individu for r in response.context["rattachements"]] == [enfant]

    def test_chaque_type_de_question_est_affiche(self, famille_bureau, formulaire_complet):
        famille, _t, enfant = famille_bureau
        sondage, questions = formulaire_complet
        champs = _champs_portail(_portail(famille), sondage, enfant)
        assert set(champs) == {"question_%d" % q.pk for q in questions.values()}
        assert champs["question_%d" % questions["liste_deroulante"].pk].choices[1:] == [
            ("Petit", "Petit"), ("Moyen", "Moyen"), ("Grand", "Grand")]

    def test_repondre_a_tout_le_formulaire(self, famille_bureau, formulaire_complet):
        famille, _t, enfant = famille_bureau
        sondage, questions = formulaire_complet
        client = _portail(famille)
        response = _repondre(client, sondage, enfant, {questions[c]: CAS[c][1] for c in CONTROLES})
        assert response["Location"] == reverse("portail_sondage_conclusion", kwargs={"code": sondage.code})
        assert client.get(response["Location"]).status_code == 200

        repondant = SondageRepondant.objects.get(sondage=sondage)
        assert (repondant.famille, repondant.individu) == (famille, enfant)
        stocke = {r.question.controle: r.reponse for r in SondageReponse.objects.filter(repondant=repondant)}
        assert stocke == {c: CAS[c][2] for c in CONTROLES}

    def test_le_formulaire_n_est_plus_a_completer(self, famille_bureau, formulaire_complet):
        famille, _t, enfant = famille_bureau
        sondage, questions = formulaire_complet
        client = _portail(famille)
        _repondre(client, sondage, enfant, {questions["bloc_texte"]: "Ok"})
        codes = [s["code"] for s in _sondages_a_completer(client)["sondages_individu"]]
        assert sondage.code not in codes

    @pytest.mark.parametrize("controle", CONTROLES)
    def test_la_famille_retrouve_ses_reponses(self, famille_bureau, formulaire_complet, controle):
        famille, _t, enfant = famille_bureau
        sondage, questions = formulaire_complet
        client = _portail(famille)
        _repondre(client, sondage, enfant, {questions[c]: CAS[c][1] for c in CONTROLES})
        champ = _champs_portail(client, sondage, enfant)["question_%d" % questions[controle].pk]
        assert affiche(champ) == CAS[controle][3]

    def test_modifier_ses_reponses(self, famille_bureau, formulaire_complet):
        famille, _t, enfant = famille_bureau
        sondage, questions = formulaire_complet
        client = _portail(famille)
        _repondre(client, sondage, enfant, {questions["entier"]: "3"})
        _repondre(client, sondage, enfant, {questions["entier"]: "4"})
        repondant = SondageRepondant.objects.get(sondage=sondage)
        assert repondant.date_modification is not None
        assert SondageReponse.objects.get(repondant=repondant, question=questions["entier"]).reponse == "4"

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: 'Réponses modifiables' unchecked is not enforced server-side: View_questions accepts "
        "a new POST and overwrites the answers already given."
    ))
    def test_reponses_non_modifiables(self, directeur_client, structure, famille_bureau):
        famille, _t, enfant = famille_bureau
        sondage = _creer_formulaire(directeur_client, structure, titre="Inscription définitive", modifiable=False)
        question = _question(directeur_client, _ajouter_page(directeur_client, sondage), "entier")
        client = _portail(famille)
        _repondre(client, sondage, enfant, {question: "3"})
        _repondre(client, sondage, enfant, {question: "99"})
        assert SondageReponse.objects.get(question=question).reponse == "3"

    def test_formulaire_famille_une_seule_reponse(self, directeur_client, structure, famille_bureau):
        famille, _t, _e = famille_bureau
        sondage = _creer_formulaire(directeur_client, structure, titre="Avis des parents", public="famille")
        question = _question(directeur_client, _ajouter_page(directeur_client, sondage), "liste_deroulante")
        client = _portail(famille)
        assert sondage.code in [s["sondage"].code for s in _sondages_a_completer(client)["sondages_famille"]]

        _repondre(client, sondage, None, {question: "Grand"})
        repondant = SondageRepondant.objects.get(sondage=sondage)
        assert repondant.individu is None
        assert sondage.code not in [s["sondage"].code for s in _sondages_a_completer(client)["sondages_famille"]]

    def test_plusieurs_pages(self, directeur_client, structure, famille_bureau):
        famille, _t, enfant = famille_bureau
        sondage = _creer_formulaire(directeur_client, structure, titre="Deux pages")
        q1 = _question(directeur_client, _ajouter_page(directeur_client, sondage), "bloc_texte")
        q2 = _question(directeur_client, _ajouter_page(directeur_client, sondage), "entier")
        _repondre(_portail(famille), sondage, enfant, {q1: "Page un", q2: "2"})
        assert {r.question_id: r.reponse for r in SondageReponse.objects.all()} == {q1.pk: "Page un", q2.pk: "2"}

    def test_ne_peut_pas_repondre_pour_l_enfant_d_une_autre_famille(self, famille_bureau, formulaire_complet):
        from tests.unit.factories import create_famille_complete

        famille, _t, _e = famille_bureau
        sondage, questions = formulaire_complet
        _u, _autre, ratt_autre = create_famille_complete(username="voisins")
        response = _repondre(_portail(famille), sondage, ratt_autre[1].individu, {questions["bloc_texte"]: "x"})
        assert response.status_code in (302, 403)
        assert not SondageRepondant.objects.filter(individu=ratt_autre[1].individu).exists()


# ---------------------------------------------------------------------------
# 3. The director reads the answers
# ---------------------------------------------------------------------------

@pytest.fixture
def formulaire_repondu(famille_bureau, formulaire_complet):
    famille, _t, enfant = famille_bureau
    sondage, questions = formulaire_complet
    _repondre(_portail(famille), sondage, enfant, {questions[c]: CAS[c][1] for c in CONTROLES})
    return sondage, questions, SondageRepondant.objects.get(sondage=sondage)


@pytest.mark.django_db
class TestConsultationDirecteur:
    def test_onglet_formulaires_de_la_fiche_famille(self, directeur_client, famille_bureau, formulaire_repondu):
        from fiche_famille.views.famille_formulaires import Liste

        famille, _t, _e = famille_bureau
        _s, _q, repondant = formulaire_repondu
        assert directeur_client.get(reverse("famille_formulaires_liste", args=[famille.pk])).status_code == 200
        request = RequestFactory().get("/")
        request.user = Utilisateur.objects.get(username="directeur")
        view = Liste()
        view.setup(request, idfamille=famille.pk)
        assert list(view.get_queryset()) == [repondant]

    @pytest.mark.parametrize("controle", CONTROLES)
    def test_voir_les_reponses_dans_la_fiche_famille(
        self, directeur_client, famille_bureau, formulaire_repondu, controle
    ):
        famille, _t, _e = famille_bureau
        _s, questions, repondant = formulaire_repondu
        response = directeur_client.get(reverse("famille_voir_formulaire", args=[famille.pk, repondant.pk]))
        champs = {}
        for _page, form in response.context["pages"]:
            champs.update(form.fields)
        champ = champs["question_%d" % questions[controle].pk]
        assert champ.disabled, "answers are shown read-only"
        assert affiche(champ) == CAS[controle][3]

    def test_supprimer_les_reponses_d_une_famille(self, directeur_client, famille_bureau, formulaire_repondu):
        famille, _t, enfant = famille_bureau
        sondage, _q, repondant = formulaire_repondu
        response = directeur_client.post(reverse("famille_formulaires_supprimer", args=[famille.pk, repondant.pk]))
        assert response.status_code == 302
        assert not SondageReponse.objects.filter(repondant_id=repondant.pk).exists()
        # The formulaire is to be completed again
        bloc = next(s for s in _sondages_a_completer(_portail(famille))["sondages_individu"] if s["code"] == sondage.code)
        assert bloc["individus"] == [enfant]

    def test_detail_des_reponses(self, directeur_client, formulaire_repondu):
        sondage, _q, repondant = formulaire_repondu
        response = directeur_client.get(reverse("sondages_reponses_detail", kwargs={"idsondage": sondage.pk}))
        assert response.status_code == 200
        assert response.context["nbre_repondants"] == 1
        assert response.context["repondant"] == repondant

    def test_tableau_et_export_csv(self, directeur_client, famille_bureau, formulaire_repondu):
        import json

        famille, _t, enfant = famille_bureau
        sondage, questions, _r = formulaire_repondu
        url = reverse("sondages_reponses_tableau", kwargs={"idsondage": sondage.pk})
        lignes = json.loads(directeur_client.get(url).context["lignes"])
        assert len(lignes) == 1 and lignes[0][2] == famille.nom

        response = directeur_client.get(url + "?export=csv")
        assert response["Content-Type"].startswith("text/csv")
        lignes = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
        entetes, ligne = lignes[0], lignes[1]
        valeurs = dict(zip(entetes, ligne))
        assert valeurs["Famille"] == famille.nom
        assert valeurs["Individu"] == enfant.Get_nom()
        attendu = {"bloc_texte": "Allergique au pollen", "entier": "12", "decimal": "1.75", "montant": "35.5",
                   "liste_deroulante": "Moyen", "liste_coches": "Piscine, Escalade", "liste_coches_ouinon": "Oui",
                   "date": "01/05/2026"}
        assert {c: valeurs[questions[c].label] for c in CONTROLES} == attendu

    def test_resume_compte_les_reponses(self, directeur_client, formulaire_repondu):
        sondage, questions, _r = formulaire_repondu
        data = directeur_client.get(
            reverse("sondages_reponses_resume", kwargs={"idsondage": sondage.pk})).context["data"]
        graphes = {element.titre: element for element in data}
        deroulante = graphes[questions["liste_deroulante"].label]
        assert dict(zip(deroulante.labels, deroulante.valeurs)) == {"Petit": 0, "Moyen": 1, "Grand": 0}
        coches = graphes[questions["liste_coches"].label]
        assert dict(zip(coches.labels, coches.valeurs)) == {"Piscine": 1, "Vélo": 0, "Escalade": 1}

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (directors are limited to their structures): Individus > Formulaires only lists my structures' "
        "formulaires, but the detail / table / CSV export of any formulaire opens by changing idsondage."
    ))
    def test_reponses_d_un_formulaire_d_une_autre_structure_interdites(self, directeur_client, formulaire_repondu):
        sondage, _q, _r = formulaire_repondu
        sondage.structure = StructureFactory()
        sondage.save()
        url = reverse("sondages_reponses_tableau", kwargs={"idsondage": sondage.pk})
        response = directeur_client.get(url + "?export=csv")
        assert response.status_code in (403, 404)

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (directors are limited to their structures): the fiche famille 'Formulaires' tab lists the "
        "answers to every structure's formulaires, not only mine."
    ))
    def test_onglet_formulaires_limite_a_mes_structures(self, famille_bureau, formulaire_repondu):
        from fiche_famille.views.famille_formulaires import Liste

        famille, _t, _e = famille_bureau
        sondage, _q, _r = formulaire_repondu
        sondage.structure = StructureFactory()
        sondage.save()
        request = RequestFactory().get("/")
        request.user = Utilisateur.objects.get(username="directeur")
        view = Liste()
        view.setup(request, idfamille=famille.pk)
        assert list(view.get_queryset()) == []


# ---------------------------------------------------------------------------
# 4. Security of the director's answer screens + reminder ("Relance")
# ---------------------------------------------------------------------------

XSS = "<img src=x onerror=alert(1)>"
XSS_SCRIPT = "</script><script>alert(1)</script>"


@pytest.fixture
def formulaire_texte(directeur_client, structure):
    sondage = _creer_formulaire(directeur_client, structure, titre="Remarques")
    question = _question(directeur_client, _ajouter_page(directeur_client, sondage), "bloc_texte")
    return sondage, question


@pytest.mark.django_db
class TestSecuriteEcransReponses:
    @pytest.mark.parametrize("vue", ["sondages_reponses_resume", "sondages_reponses_tableau",
                                     "sondages_reponses_detail"])
    def test_ecrans_reserves_au_staff(self, famille_bureau, formulaire_texte, vue):
        famille, _t, _e = famille_bureau
        sondage, _q = formulaire_texte
        url = reverse(vue, kwargs={"idsondage": sondage.pk})
        assert Client().get(url).status_code == 302
        assert _portail(famille).get(url).status_code == 403

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (XSS): the 'Résumé' screen renders free-text answers with |safe: a family answer "
        "containing HTML runs JavaScript in the director's session."
    ))
    def test_resume_echappe_les_reponses(self, directeur_client, famille_bureau, formulaire_texte):
        famille, _t, enfant = famille_bureau
        sondage, question = formulaire_texte
        _repondre(_portail(famille), sondage, enfant, {question: XSS})
        html = directeur_client.get(reverse("sondages_reponses_resume", kwargs={"idsondage": sondage.pk})).content
        assert XSS not in html.decode()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (XSS): the 'Tableau' screen injects the answers into a <script> block with "
        "mark_safe(json.dumps(...)), which does not escape '</script>': a family answer closes the "
        "script and runs its own JavaScript in the director's session."
    ))
    def test_tableau_echappe_les_reponses(self, directeur_client, famille_bureau, formulaire_texte):
        famille, _t, enfant = famille_bureau
        sondage, question = formulaire_texte
        _repondre(_portail(famille), sondage, enfant, {question: XSS_SCRIPT})
        html = directeur_client.get(reverse("sondages_reponses_tableau", kwargs={"idsondage": sondage.pk})).content
        assert XSS_SCRIPT not in html.decode()

    @pytest.mark.parametrize("vue", ["sondages_reponses_detail", "famille_voir_formulaire"])
    def test_detail_et_fiche_famille_echappent_les_reponses(self, directeur_client, famille_bureau,
                                                           formulaire_texte, vue):
        famille, _t, enfant = famille_bureau
        sondage, question = formulaire_texte
        _repondre(_portail(famille), sondage, enfant, {question: XSS})
        if vue == "famille_voir_formulaire":
            repondant = SondageRepondant.objects.get(sondage=sondage)
            url = reverse(vue, args=[famille.pk, repondant.pk])
        else:
            url = reverse(vue, kwargs={"idsondage": sondage.pk})
        html = directeur_client.get(url).content.decode()
        assert XSS not in html
        assert "&lt;img src=x onerror=alert(1)&gt;" in html, "the answer must still be displayed (escaped)"


def _relancer_formulaire(client, sondage=None):
    return client.post(reverse("ajax_sondages_relance"), {"idsondage": sondage.pk if sondage else ""}, **AJAX)


@pytest.fixture
def famille_b(famille_bureau, activite):
    """A second family whose child is inscribed on the director's activity."""
    from tests.unit.factories import create_famille_complete

    famille_a, _t, _e = famille_bureau
    famille_a.mail = "a@test.org"
    famille_a.save()
    _u, famille, ratt = create_famille_complete(username="famille_b")
    famille.mail = "b@test.org"
    famille.save()
    InscriptionFactory(famille=famille, individu=ratt[1].individu, activite=activite)
    return famille, ratt[1].individu


@pytest.mark.django_db
class TestRelanceFormulaire:
    def test_aucun_formulaire_selectionne(self, directeur_client):
        response = _relancer_formulaire(directeur_client)
        assert response.status_code == 400

    def test_relance_les_familles_sans_reponse(self, directeur_client, directeur, famille_bureau, famille_b,
                                               formulaire_texte):
        famille_a, _t, enfant_a = famille_bureau
        famille_b_, _enfant_b = famille_b
        sondage, question = formulaire_texte
        _repondre(_portail(famille_a), sondage, enfant_a, {question: "Répondu"})

        response = _relancer_formulaire(directeur_client, sondage)
        from core.models import Mail

        mail = Mail.objects.get(categorie="rappel_reponses_manquantes")
        assert response.json()["url"] == reverse("editeur_emails", kwargs={"pk": mail.pk})
        assert mail.utilisateur == directeur
        destinataires = list(mail.destinataires.all())
        assert [(d.famille, d.adresse) for d in destinataires] == [(famille_b_, "b@test.org")]
        assert json.loads(destinataires[0].valeurs)["{SONDAGE_TITRE}"] == sondage.titre

    def test_tout_le_monde_a_repondu(self, directeur_client, famille_bureau, famille_b, formulaire_texte):
        famille_a, _t, enfant_a = famille_bureau
        famille_b_, enfant_b = famille_b
        sondage, question = formulaire_texte
        _repondre(_portail(famille_a), sondage, enfant_a, {question: "A"})
        _repondre(_portail(famille_b_), sondage, enfant_b, {question: "B"})
        assert _relancer_formulaire(directeur_client, sondage).status_code == 401

    def test_famille_sans_email_signalee(self, directeur_client, famille_bureau, famille_b, formulaire_texte):
        from core.models import Mail

        famille_a, _t, enfant_a = famille_bureau
        famille_b_, _enfant_b = famille_b
        famille_b_.mail = ""
        famille_b_.save()
        sondage, question = formulaire_texte
        _repondre(_portail(famille_a), sondage, enfant_a, {question: "A"})
        _relancer_formulaire(directeur_client, sondage)
        assert Mail.objects.get().destinataires.count() == 0
        messages = [str(m) for m in directeur_client.get(reverse("sondages_liste")).context["messages"]]
        assert any("Adresses mail manquantes" in m and famille_b_.nom in m for m in messages)

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: for a formulaire per child (public='individu'), a family is excluded from the reminder as "
        "soon as ONE child answered; a sibling who has not answered is never reminded."
    ))
    def test_relance_le_frere_qui_n_a_pas_repondu(self, directeur_client, famille_bureau, famille_b,
                                                 formulaire_texte, activite):
        from core.models import Mail, Rattachement
        from tests.unit.factories import IndividuFactory

        famille_a, _t, enfant_a = famille_bureau
        cadet = IndividuFactory(nom="Enfant", prenom="Cadet")
        Rattachement.objects.create(famille=famille_a, individu=cadet, categorie=2)
        InscriptionFactory(famille=famille_a, individu=cadet, activite=activite)
        sondage, question = formulaire_texte
        _repondre(_portail(famille_a), sondage, enfant_a, {question: "Aîné a répondu"})
        _relancer_formulaire(directeur_client, sondage)
        assert famille_a.pk in Mail.objects.get().destinataires.values_list("famille_id", flat=True)

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (directors are limited to their structures): the reminder accepts any idsondage and prepares "
        "an email to another structure's families."
    ))
    def test_relance_d_un_formulaire_d_une_autre_structure_interdite(self, directeur_client, famille_bureau):
        from core.models import Mail

        famille, _t, enfant = famille_bureau
        famille.mail = "a@test.org"
        famille.save()
        voisine = StructureFactory()
        InscriptionFactory(famille=famille, individu=enfant, activite=ActiviteFactory(structure=voisine))
        sondage = Sondage.objects.create(titre="Formulaire voisin", structure=voisine)
        _relancer_formulaire(directeur_client, sondage)
        assert not Mail.objects.exists()

    def test_relance_requiert_ajax(self, directeur_client, formulaire_texte):
        sondage, _q = formulaire_texte
        assert directeur_client.post(reverse("ajax_sondages_relance"), {"idsondage": sondage.pk}).status_code == 400
