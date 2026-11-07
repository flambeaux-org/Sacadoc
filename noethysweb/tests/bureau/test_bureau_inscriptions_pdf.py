"""PDF / CSV documents built from inscriptions.

1. "Imprimer une liste d'inscrits" (individus/views/imprimer_liste_inscrits.py): the director picks an activity, a
   date of situation and custom columns; the list is rendered as a PDF (utils_impression_inscrits) or a CSV.
2. "Confirmation d'inscription" (fiche_individu/utils/utils_inscriptions.py + utils_impression_inscription.py),
   printed from "Imprimer des inscriptions" or attached to an email from "Envoyer des inscriptions par email".

The generated files are read back (pypdf / csv) so the tests check what the director actually gets.

Printing a confirmation currently crashes for every inscription (GetDonneesImpression reads inscription.tarif_id,
see the xfail in test_bureau_inscriptions_suivi.py). To still cover the rest of that pipeline, the
`sans_bug_tarif` fixture gives Inscription the `tarif` / `tarif_id` attributes the code expects (first tarif of the
M2M); the tests using it describe the behaviour expected once that bug is fixed.
"""

import csv
import datetime
import json
from decimal import Decimal

import pytest
from core.models import (
    CategorieTarif,
    CompteBancaire,
    Cotisation,
    DocumentJoint,
    Inscription,
    Mail,
    ModeleDocument,
    ModeleEmail,
    ModeleImpression,
    ModeReglement,
    Parametre,
    Payeur,
    Prestation,
    QuestionnaireQuestion,
    QuestionnaireReponse,
    Reglement,
    Tarif,
    NomTarif,
    TypeCotisation,
    UniteCotisation,
    Ventilation,
)
from django.urls import reverse
from pypdf import PdfReader
from tests.bureau.conftest import AJAX
from tests.unit.factories import (
    ActiviteFactory,
    FamilleFactory,
    GroupeFactory,
    IndividuFactory,
    RattachementFactory,
    StructureFactory,
)

DATE_SITUATION = datetime.date(2026, 7, 15)


# ---------------------------------------------------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    """Generated PDF / CSV files go to a throw-away MEDIA_ROOT."""
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


def _camp(structure, nom="Camp d'été"):
    activite = ActiviteFactory(structure=structure, nom=nom, abrege="CAMP",
                               date_debut=datetime.date(2026, 7, 1), date_fin=datetime.date(2026, 7, 31))
    categorie = CategorieTarif.objects.create(activite=activite, nom="Normal")
    tarif = Tarif.objects.create(activite=activite, nom_tarif=NomTarif.objects.create(activite=activite, nom="Séjour"),
                                 date_debut=datetime.date(2026, 1, 1), description="Séjour complet")
    return {"activite": activite, "categorie": categorie, "tarif": tarif,
            "louveteaux": GroupeFactory(activite=activite, nom="Louveteaux")}


@pytest.fixture
def camp(db, structure):
    return _camp(structure)


def _famille(nom, enfants, parent=None):
    """A family with an optional parent (categorie 1) and children (categorie 2); returns (famille, [enfants])."""
    famille = FamilleFactory(nom=nom, mail="%s@test.org" % nom.lower())
    if parent:
        RattachementFactory(famille=famille, categorie=1, titulaire=True, individu=IndividuFactory(nom=nom, **parent))
    individus = []
    for prenom, kwargs in enfants:
        individu = IndividuFactory(nom=nom, prenom=prenom, **kwargs)
        RattachementFactory(famille=famille, individu=individu, categorie=2)
        individus.append(individu)
    return famille, individus


def _inscrire(camp, famille, individu, **kwargs):
    kwargs.setdefault("date_debut", datetime.date(2026, 7, 1))
    kwargs.setdefault("categorie_tarif", camp["categorie"])
    inscription = Inscription.objects.create(famille=famille, individu=individu, activite=camp["activite"],
                                             groupe=camp["louveteaux"], **kwargs)
    inscription.tarifs.add(camp["tarif"])
    return inscription


def _colonnes(*codes, largeur="automatique"):
    return json.dumps([{"nom": code.upper(), "code": code, "largeur": largeur} for code in codes])


def _parametres(camp, colonnes=None, **extra):
    data = {"activite": camp["activite"].pk, "date_situation": DATE_SITUATION.isoformat(),
            "colonnes_perso": colonnes or _colonnes("nom", "prenom"), "orientation": "portrait"}
    data.update(extra)
    return data


def _pdf(media, nom_fichier):
    return PdfReader(str(media) + nom_fichier)


def _texte_pdf(media, nom_fichier):
    return "\n".join(page.extract_text() for page in _pdf(media, nom_fichier).pages)


def _generer_pdf(client, data):
    return client.post(reverse("ajax_imprimer_liste_inscrits_generer_pdf"), data, **AJAX)


def _generer_csv(client, data):
    return client.post(reverse("ajax_imprimer_liste_inscrits_generer_csv"), data, **AJAX)


def _lire_csv(media):
    with open(media / "inscriptions.csv", encoding="utf-8-sig", newline="") as fichier:
        return list(csv.reader(fichier))


def _regler(prestation, montant):
    famille = prestation.famille
    reglement = Reglement.objects.create(
        famille=famille, date=datetime.date(2026, 7, 2), montant=montant,
        mode=ModeReglement.objects.create(label="Chèque"),
        payeur=Payeur.objects.create(famille=famille, nom=famille.nom),
        compte=CompteBancaire.objects.create(nom="Compte courant"),
        modelimp=ModeleImpression.objects.create(categorie="reglement", nom="Reçu"),
    )
    return Ventilation.objects.create(famille=famille, reglement=reglement, prestation=prestation, montant=montant)


# ---------------------------------------------------------------------------------------------------------------------
# 1. Liste des inscrits: page and parameters
# ---------------------------------------------------------------------------------------------------------------------

@pytest.mark.django_db
class TestPageListeInscrits:
    def test_page(self, directeur_client, camp):
        ActiviteFactory(structure=StructureFactory(), nom="Camp voisin")
        response = directeur_client.get(reverse("imprimer_liste_inscrits"))
        assert response.status_code == 200
        form = response.context["form"]
        assert list(form.fields["activite"].queryset) == [camp["activite"]]
        assert [c["code"] for c in json.loads(form.fields["colonnes_perso"].initial)] == ["nom", "prenom"]
        assert form.fields["date_situation"].initial == datetime.date.today()

    def test_formulaire_de_colonne_propose_les_donnees_standard(self):
        """The column editor (ColonnesInscritsWidget) lists every value computed by utils_impression_inscrits."""
        from individus.forms.colonne_inscrits import Formulaire

        choix = dict(Formulaire.base_fields["donnee"].choices)
        assert {"nom", "prenom", "groupe", "tarifs", "tel_parents", "mail_parents", "solde"} <= set(choix)

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: colonne_inscrits.Formulaire builds the questionnaire choices in the class body, i.e. once at "
        "import time: a question created after the server started is not offered until the next restart "
        "(and the choices are not limited to the director's structures)."
    ))
    def test_question_creee_apres_le_demarrage_proposee(self, structure):
        from individus.forms.colonne_inscrits import Formulaire

        question = QuestionnaireQuestion.objects.create(categorie="individu", ordre=1, label="Allergies",
                                                        controle="bloc_texte", structure=structure)
        assert "question_individu_%d" % question.pk in dict(Formulaire().fields["donnee"].choices)

    def test_appliquer_un_profil(self, directeur_client, directeur, camp):
        profil = Parametre.objects.create(categorie="imprimer_liste_inscrits", nom="Liste camp", utilisateur=directeur,
                                          parametre=json.dumps({"activite": camp["activite"].pk,
                                                                "colonnes_perso": [{"nom": "Groupe", "code": "groupe",
                                                                                    "largeur": "80"}],
                                                                "orientation": "paysage"}))
        # Choosing a profile submits the whole parameters form (appliquer_profil() in EXTRA_HTML)
        response = directeur_client.post(reverse("imprimer_liste_inscrits"), _parametres(camp, profil=profil.pk))
        assert response.status_code == 200
        form = response.context["form"]
        assert form.data["activite"] == camp["activite"].pk
        assert form.data["orientation"] == "paysage"
        assert json.loads(form.data["colonnes_perso"]) == [{"nom": "Groupe", "code": "groupe", "largeur": "80"}]
        assert form.data["date_situation"] == str(datetime.date.today())

    def test_donnees_memorisees_dans_le_profil(self, rf, directeur, camp):
        from individus.views.imprimer_liste_inscrits import get_data_profil

        request = rf.post("/")
        request.user = directeur
        data = get_data_profil(_parametres(camp, colonnes=_colonnes("nom")), request=request)
        assert data == {"activite": camp["activite"].pk, "colonnes_perso": [{"nom": "NOM", "code": "nom",
                                                                            "largeur": "automatique"}],
                        "orientation": "portrait"}

    def test_profil_invalide_refuse(self, rf, directeur):
        from individus.views.imprimer_liste_inscrits import get_data_profil

        request = rf.post("/")
        request.user = directeur
        assert get_data_profil({"colonnes_perso": "[]"}, request=request).status_code == 401

    def test_profils_d_un_autre_directeur_non_proposes(self, directeur_client, directeur, camp):
        from tests.unit.factories import UtilisateurFactory

        autre = UtilisateurFactory(username="autre")
        mien = Parametre.objects.create(categorie="imprimer_liste_inscrits", nom="Mien", utilisateur=directeur)
        Parametre.objects.create(categorie="imprimer_liste_inscrits", nom="Le sien", utilisateur=autre)
        Parametre.objects.create(categorie="imprimer_liste_inscrits", nom="Autre structure",
                                 structure=StructureFactory())
        form = directeur_client.get(reverse("imprimer_liste_inscrits")).context["form"]
        assert list(form.fields["profil"].queryset) == [mien]


# ---------------------------------------------------------------------------------------------------------------------
# 1. Liste des inscrits: PDF
# ---------------------------------------------------------------------------------------------------------------------

@pytest.mark.django_db
class TestPdfListeInscrits:
    def test_liste_triee_avec_entetes(self, directeur_client, camp, media):
        famille_b, [zoe] = _famille("Bernard", [("Zoé", {})])
        famille_a, [leo, ana] = _famille("Arnaud", [("Léo", {}), ("Ana", {})])
        for famille, individu in ((famille_b, zoe), (famille_a, leo), (famille_a, ana)):
            _inscrire(camp, famille, individu)

        response = _generer_pdf(directeur_client, _parametres(camp, colonnes=_colonnes("nom", "prenom", "groupe")))
        assert response.status_code == 200, response.content
        texte = _texte_pdf(media, response.json()["nom_fichier"])
        assert "Liste des inscrits" in texte
        assert "Camp d'été" in texte
        # pypdf extracts one table cell per line
        tableau = texte.splitlines()[texte.splitlines().index("NOM"):]
        assert tableau == ["NOM", "PRENOM", "GROUPE",
                           "Arnaud", "Ana", "Louveteaux", "Arnaud", "Léo", "Louveteaux", "Bernard", "Zoé", "Louveteaux"]

    def test_seules_les_inscriptions_en_cours_a_la_date_de_situation(self, directeur_client, camp, structure, media):
        famille, [en_cours, sans_fin, terminee, autre_camp] = _famille(
            "Martin", [("Encours", {}), ("Sansfin", {}), ("Terminee", {}), ("Autrecamp", {})])
        _inscrire(camp, famille, en_cours, date_fin=DATE_SITUATION)
        _inscrire(camp, famille, sans_fin)
        _inscrire(camp, famille, terminee, date_fin=DATE_SITUATION - datetime.timedelta(days=1))
        _inscrire(_camp(structure, nom="Camp d'hiver"), famille, autre_camp)

        texte = _texte_pdf(media, _generer_pdf(directeur_client, _parametres(camp)).json()["nom_fichier"])
        assert "Encours" in texte and "Sansfin" in texte
        assert "Terminee" not in texte and "Autrecamp" not in texte

    def test_valeurs_des_colonnes(self, directeur_client, camp, media):
        famille, [enfant] = _famille(
            "Durand", [("Paul", {"date_naiss": datetime.date(2015, 3, 4), "mail": "paul@test.org",
                                 "tel_mobile": "0601020304", "ville_resid": "Lyon"})],
            parent={"prenom": "Claire", "tel_mobile": "0699999999", "mail": "claire@test.org"})
        _inscrire(camp, famille, enfant, date_fin=datetime.date(2026, 7, 31), statut="refus")
        prestation = Prestation.objects.create(famille=famille, individu=enfant, activite=camp["activite"],
                                               date=datetime.date(2026, 7, 1), label="Séjour complet",
                                               montant=Decimal("120"))
        Prestation.objects.create(famille=famille, individu=enfant, activite=camp["activite"],
                                  date=datetime.date(2026, 7, 1), label="Transport", montant=Decimal("30"))
        _regler(prestation, Decimal("100"))

        colonnes = ("date_debut", "date_fin", "categorie_tarif", "tarifs", "date_naiss", "mail", "portable",
                    "individu_ville", "tel_parents", "mail_parents", "famille", "statut", "solde")
        data = {}
        for code in colonnes:
            texte = _texte_pdf(media, _generer_pdf(directeur_client,
                                                   _parametres(camp, colonnes=_colonnes(code))).json()["nom_fichier"])
            data[code] = texte.splitlines()[-1]
        assert data == {
            "date_debut": "01/07/2026", "date_fin": "31/07/2026", "categorie_tarif": "Normal",
            "tarifs": "Séjour complet | Transport", "date_naiss": "04/03/2015", "mail": "paul@test.org",
            "portable": "0601020304", "individu_ville": "Lyon", "tel_parents": "Claire : 0699999999",
            "mail_parents": "Claire : claire@test.org", "famille": "Durand", "statut": "Inscription refusée",
            "solde": "-50.00 €",
        }

    def test_reponses_aux_questionnaires(self, directeur_client, camp, structure, media):
        question = QuestionnaireQuestion.objects.create(categorie="individu", ordre=1, label="Allergies",
                                                        controle="bloc_texte", structure=structure)
        famille, [enfant] = _famille("Petit", [("Jean", {})])
        QuestionnaireReponse.objects.create(question=question, individu=enfant, reponse="Arachides")
        _inscrire(camp, famille, enfant)
        colonnes = json.dumps([{"nom": "Allergies", "code": "question_individu_%d" % question.pk,
                                "largeur": "automatique"}])
        texte = _texte_pdf(media, _generer_pdf(directeur_client, _parametres(camp, colonnes=colonnes)).json()["nom_fichier"])
        assert "Arachides" in texte

    def test_orientation_paysage(self, directeur_client, camp, media):
        famille, [enfant] = _famille("Roux", [("Lou", {})])
        _inscrire(camp, famille, enfant)
        portrait = _pdf(media, _generer_pdf(directeur_client, _parametres(camp)).json()["nom_fichier"]).pages[0]
        paysage = _pdf(media, _generer_pdf(directeur_client, _parametres(camp, orientation="paysage"))
                       .json()["nom_fichier"]).pages[0]
        assert portrait.mediabox.width < portrait.mediabox.height
        assert paysage.mediabox.width > paysage.mediabox.height

    def test_colonnes_de_largeur_fixe(self, directeur_client, camp, media):
        famille, [enfant] = _famille("Roux", [("Lou", {})])
        _inscrire(camp, famille, enfant)
        colonnes = json.dumps([{"nom": "Nom", "code": "nom", "largeur": "60"},
                               {"nom": "Prénom", "code": "prenom", "largeur": "automatique"}])
        response = _generer_pdf(directeur_client, _parametres(camp, colonnes=colonnes))
        assert response.status_code == 200
        assert _texte_pdf(media, response.json()["nom_fichier"]).endswith("Nom\nPrénom\nRoux\nLou\n")

    def test_activite_sans_inscrit(self, directeur_client, camp, media):
        response = _generer_pdf(directeur_client, _parametres(camp))
        assert response.status_code == 200
        assert _texte_pdf(media, response.json()["nom_fichier"]).endswith("NOM\nPRENOM\n")

    def test_sans_colonne_refuse(self, directeur_client, camp):
        response = _generer_pdf(directeur_client, _parametres(camp, colonnes="[]"))
        assert response.status_code == 401
        assert response.json()["erreur"] == "Vous devez créer au moins une colonne."

    def test_sans_activite_refuse(self, directeur_client, camp):
        response = _generer_pdf(directeur_client, _parametres(camp, activite=""))
        assert response.status_code == 401
        assert response.json()["erreur"] == "Veuillez compléter les paramètres."

    def test_activite_d_une_autre_structure_refusee(self, directeur_client):
        autre = _camp(StructureFactory(), nom="Camp voisin")
        assert _generer_pdf(directeur_client, _parametres(autre)).status_code == 401

    @pytest.mark.parametrize("url", ["ajax_imprimer_liste_inscrits_generer_pdf",
                                     "ajax_imprimer_liste_inscrits_generer_csv"])
    def test_refuse_aux_familles_et_aux_anonymes(self, client, famille_bureau, camp, url):
        assert client.post(reverse(url), _parametres(camp), **AJAX).status_code == 403
        client.force_login(famille_bureau[0].utilisateur)
        assert client.post(reverse(url), _parametres(camp), **AJAX).status_code == 403

    @pytest.mark.xfail(strict=True, raises=AttributeError, reason=(
        "BUG: utils_impression_inscrits.Draw() builds every column value for every row, including "
        "inscription.categorie_tarif.nom: a single inscription without categorie_tarif (nullable) makes the "
        "whole list crash (500), whatever the selected columns."
    ))
    def test_inscription_sans_categorie_de_tarif(self, directeur_client, camp):
        famille, [enfant] = _famille("Roux", [("Lou", {})])
        _inscrire(camp, famille, enfant, categorie_tarif=None)
        assert _generer_pdf(directeur_client, _parametres(camp)).status_code == 200

    @pytest.mark.xfail(strict=True, raises=NameError, reason=(
        "BUG: utils_impression_inscrits.py:73 appends 'cotization' (typo for 'cotisation'): as soon as one "
        "adhésion overlaps the activity dates, the list of inscrits crashes (500) for everybody."
    ))
    def test_numero_d_adhesion(self, directeur_client, camp, media):
        famille, [enfant] = _famille("Roux", [("Lou", {})])
        _inscrire(camp, famille, enfant)
        type_cotisation = TypeCotisation.objects.create(nom="Adhésion")
        Cotisation.objects.create(famille=famille, type_cotisation=type_cotisation, numero="A-042",
                                  unite_cotisation=UniteCotisation.objects.create(type_cotisation=type_cotisation,
                                                                                  nom="2026"),
                                  date_debut=datetime.date(2026, 1, 1), date_fin=datetime.date(2026, 12, 31))
        response = _generer_pdf(directeur_client, _parametres(camp, colonnes=_colonnes("num_cotisation")))
        assert "A-042" in _texte_pdf(media, response.json()["nom_fichier"])

    @pytest.mark.xfail(strict=True, raises=ValueError, reason=(
        "BUG: utils_impression_inscrits.py:72 filters the adhésions with date_debut__lte=activite.date_fin: "
        "for an activity without dates (allowed, e.g. a year-round activity) Django raises 'Cannot use None "
        "as a query value' and the list cannot be printed."
    ))
    def test_activite_sans_date_de_fin(self, directeur_client, camp):
        camp["activite"].date_fin = None
        camp["activite"].save()
        assert _generer_pdf(directeur_client, _parametres(camp)).status_code == 200


# ---------------------------------------------------------------------------------------------------------------------
# 1. Liste des inscrits: CSV
# ---------------------------------------------------------------------------------------------------------------------

@pytest.mark.django_db
class TestCsvListeInscrits:
    def test_export(self, directeur_client, camp, media):
        famille, [lou, eva] = _famille("Roux", [("Lou", {}), ("Éva", {})])
        _inscrire(camp, famille, lou)
        _inscrire(camp, famille, eva, statut="refus")
        response = _generer_csv(directeur_client, _parametres(camp, colonnes=_colonnes("prenom", "statut")))
        assert response.status_code == 200, response.content
        assert response.json()["url_csv"] == "http://testserver/media/inscriptions.csv"
        assert _lire_csv(media) == [["PRENOM", "STATUT"], ["Lou", "Inscription validée"],
                                    ["Éva", "Inscription refusée"]]

    def test_tri_numerique_sur_la_premiere_colonne(self, directeur_client, camp, media):
        famille, enfants = _famille("Roux", [("A", {"date_naiss": datetime.date(2016, 1, 1)}),
                                             ("B", {"date_naiss": datetime.date(2010, 1, 1)}),
                                             ("C", {"date_naiss": datetime.date(2019, 1, 1)})])
        for enfant in enfants:
            _inscrire(camp, famille, enfant)
        _generer_csv(directeur_client, _parametres(camp, colonnes=_colonnes("age", "prenom")))
        assert [ligne[1] for ligne in _lire_csv(media)[1:]] == ["C", "A", "B"]

    def test_sans_colonne_refuse(self, directeur_client, camp):
        response = _generer_csv(directeur_client, _parametres(camp, colonnes="[]"))
        assert response.status_code == 400
        assert response.json()["erreur"] == "Vous devez créer au moins une colonne."

    def test_parametres_invalides_refuses(self, directeur_client, camp):
        response = _generer_csv(directeur_client, _parametres(camp, activite=""))
        assert response.status_code == 400

    def test_get_refuse(self, directeur_client):
        response = directeur_client.get(reverse("ajax_imprimer_liste_inscrits_generer_csv"), **AJAX)
        assert response.status_code == 405

    def test_erreur_de_generation_renvoyee_en_json(self, directeur_client, camp):
        famille, [enfant] = _famille("Roux", [("Lou", {})])
        _inscrire(camp, famille, enfant, categorie_tarif=None)
        response = _generer_csv(directeur_client, _parametres(camp))
        assert response.status_code == 500
        assert "nom" in response.json()["erreur"]

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (données personnelles): Generer_csv writes every export to the same public file "
        "MEDIA_ROOT/inscriptions.csv. Two directors exporting at the same time overwrite each other's list, "
        "and anyone who knows /media/inscriptions.csv downloads the last exported list (names, phones, "
        "emails of children and parents). Expected: one unguessable file per export, like the PDFs."
    ))
    def test_chaque_export_a_son_propre_fichier(self, directeur_client, camp, structure):
        famille, [enfant] = _famille("Roux", [("Lou", {})])
        _inscrire(camp, famille, enfant)
        premier = _generer_csv(directeur_client, _parametres(camp)).json()["url_csv"]
        second = _generer_csv(directeur_client, _parametres(camp)).json()["url_csv"]
        assert premier != second
        assert not premier.endswith("/media/inscriptions.csv")


# ---------------------------------------------------------------------------------------------------------------------
# 2. Confirmation d'inscription (print / email)
# ---------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def sans_bug_tarif(monkeypatch):
    """Work around the tarif_id bug (see the module docstring) to test the rest of the pipeline."""
    monkeypatch.setattr(Inscription, "tarif", property(lambda self: self.tarifs.first()), raising=False)
    monkeypatch.setattr(Inscription, "tarif_id", property(lambda self: getattr(self.tarifs.first(), "pk", None)),
                        raising=False)


@pytest.fixture
def modele(db, organisateur):
    """A "Confirmation d'inscription" model whose main frame is where the details table is drawn."""
    objets = [{"categorie": "cadre", "champ": "cadre_principal", "left": 15, "top": 15, "width": 180, "height": 260}]
    return ModeleDocument.objects.create(nom="Confirmation", categorie="inscription", largeur=210, hauteur=297,
                                         defaut=True, objets=json.dumps(objets))


@pytest.fixture
def inscrits(camp):
    famille_b, [zoe] = _famille("Bernard", [("Zoé", {})])
    famille_a, [leo] = _famille("Arnaud", [("Léo", {})])
    famille_a.mail = None
    famille_a.save()
    return [_inscrire(camp, famille_b, zoe, date_fin=datetime.date(2026, 7, 20)), _inscrire(camp, famille_a, leo)]


def _poster(client, url_name, inscriptions, modele):
    return client.post(reverse(url_name), {"inscriptions_cochees": json.dumps([i.pk for i in inscriptions]),
                                           "form_modele": json.dumps({"modele": modele.pk})}, **AJAX)


@pytest.mark.django_db
class TestConfirmationDInscription:
    def test_document_genere_par_l_impression(self, camp, inscrits, modele, media):
        """utils_impression_inscription alone: one page per inscription, sorted by family name."""
        from fiche_individu.utils.utils_impression_inscription import Impression

        donnees = {
            inscription.pk: {"{FAMILLE_NOM}": inscription.famille.nom, "{INDIVIDU_NOM}": inscription.individu.nom,
                             "{INDIVIDU_PRENOM}": inscription.individu.prenom, "{ACTIVITE_NOM_LONG}": "Camp d'été",
                             "{GROUPE_NOM_LONG}": "Louveteaux", "{NOM_CATEGORIE_TARIF}": "Normal",
                             "{DATE_DEBUT}": "01/07/2026", "{DATE_FIN}": ""}
            for inscription in inscrits
        }
        impression = Impression(dict_donnees=donnees, dict_options={}, IDmodele=modele.pk)
        pages = [page.extract_text() for page in _pdf(media, impression.Get_nom_fichier()).pages]
        assert len(pages) == 2
        assert "Arnaud" in pages[0] and "Bernard" in pages[1]
        for libelle in ("Confirmation d'inscription", "Nom", "Prénom", "Activité", "Groupe", "Catégorie",
                        "Date de début", "Date de fin", "Camp d'été", "Louveteaux", "Normal", "01/07/2026"):
            assert libelle in pages[0]

    def test_modele_sans_cadre_principal(self, organisateur, camp, inscrits, media):
        from fiche_individu.utils.utils_impression_inscription import Impression

        modele = ModeleDocument.objects.create(nom="Vide", categorie="inscription", largeur=210, hauteur=297,
                                               objets="[]")
        donnees = {inscrits[0].pk: {"{FAMILLE_NOM}": "Bernard"}}
        impression = Impression(dict_donnees=donnees, dict_options={}, IDmodele=modele.pk)
        pages = _pdf(media, impression.Get_nom_fichier()).pages
        assert len(pages) == 1
        assert "Bernard" not in pages[0].extract_text()

    def test_imprimer_des_inscriptions(self, directeur_client, inscrits, modele, media, sans_bug_tarif):
        response = _poster(directeur_client, "ajax_inscriptions_impression_pdf", inscrits, modele)
        assert response.status_code == 200, response.content
        texte = _texte_pdf(media, response.json()["nom_fichier"])
        assert "Zoé" in texte and "Léo" in texte
        assert "20/07/2026" in texte

    def test_champs_de_fusion(self, inscrits, modele, sans_bug_tarif):
        from fiche_individu.utils.utils_inscriptions import Inscriptions

        donnees, champs = Inscriptions().GetDonneesImpression([inscrits[0].pk])
        valeurs = champs[inscrits[0].pk]
        assert valeurs["{IDINSCRIPTION}"] == str(inscrits[0].pk)
        assert (valeurs["{INDIVIDU_PRENOM}"], valeurs["{FAMILLE_NOM}"]) == ("Zoé", "Bernard")
        assert (valeurs["{DATE_DEBUT}"], valeurs["{DATE_FIN}"]) == ("01/07/2026", "20/07/2026")
        assert (valeurs["{ACTIVITE_NOM_LONG}"], valeurs["{ACTIVITE_NOM_COURT}"]) == ("Camp d'été", "CAMP")
        assert (valeurs["{GROUPE_NOM_LONG}"], valeurs["{NOM_CATEGORIE_TARIF}"]) == ("Louveteaux", "Normal")
        assert valeurs["{TARIF_NOM}"] == "Séjour complet"

    def test_envoyer_par_email(self, directeur_client, directeur, inscrits, modele, media, sans_bug_tarif):
        ModeleEmail.objects.create(categorie="inscription", nom="Confirmation", objet="Votre inscription",
                                   html="<p>Bonjour {INDIVIDU_PRENOM}</p>", defaut=True)
        response = _poster(directeur_client, "ajax_inscriptions_email_pdf", inscrits, modele)
        assert response.status_code == 200, response.content

        mail = Mail.objects.get()
        assert response.json()["url"] == reverse("editeur_emails", kwargs={"pk": mail.pk})
        assert (mail.categorie, mail.objet, mail.utilisateur) == ("inscription", "Votre inscription", directeur)
        assert mail.verrouillage_destinataires is True

        # Only the family with an email address becomes a recipient, with its own PDF and merge fields
        [destinataire] = mail.destinataires.all()
        assert destinataire.adresse == "bernard@test.org"
        assert json.loads(destinataire.valeurs)["{INDIVIDU_PRENOM}"] == "Zoé"
        [document] = destinataire.documents.all()
        texte = _texte_pdf(media, document.fichier.name if hasattr(document.fichier, "name") else document.fichier)
        assert "Zoé" in texte and "Léo" not in texte

        # The family without an email is reported
        response = directeur_client.get(reverse("inscriptions_email"))
        assert any("Adresses mail manquantes : Arnaud" in str(m) for m in response.context["messages"])

    def test_envoyer_par_email_sans_modele_d_email(self, directeur_client, inscrits, modele, sans_bug_tarif):
        response = _poster(directeur_client, "ajax_inscriptions_email_pdf", inscrits[:1], modele)
        assert response.status_code == 200
        mail = Mail.objects.get()
        assert (mail.objet, mail.html) == ("", "")
        assert DocumentJoint.objects.count() == 1

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (données personnelles): Impression_pdf (individus/views/inscriptions_impression.py:16) and its "
        "email twin print any inscription id they receive, without checking the activity's structure: a "
        "director can generate the confirmation (name, address, family) of any child of another structure."
    ))
    @pytest.mark.parametrize("url_name", ["ajax_inscriptions_impression_pdf", "ajax_inscriptions_email_pdf"])
    def test_inscription_d_une_autre_structure_refusee(self, directeur_client, modele, sans_bug_tarif, url_name):
        autre = _camp(StructureFactory(), nom="Camp voisin")
        famille, [enfant] = _famille("Voisin", [("Secret", {})])
        response = _poster(directeur_client, url_name, [_inscrire(autre, famille, enfant)], modele)
        assert response.status_code in (401, 403)
