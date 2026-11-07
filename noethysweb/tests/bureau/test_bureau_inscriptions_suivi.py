"""Director-side follow-up of inscriptions and handling of the portail requests.

Screens under test:
- "Inscriptions en attente" / "Inscriptions refusées" (individus/views/liste_inscriptions_attente.py);
- "Suivi des inscriptions" and its AJAX endpoints (individus/views/suivi_inscriptions.py);
- "Demandes de vérification" (individus/views/demande_approbation.py);
- "Demandes du portail" list, "Valider", "Refuser", "Tout valider" (outils/views/demandes_portail.py);
- "Imprimer / Envoyer des inscriptions par email" (individus/views/inscriptions_impression.py, inscriptions_email.py).

Business rules under test: a director only sees and acts on the activities of his own structures, the pending
portail requests are counted and listed where the director follows his inscriptions, and handling a request
has the expected effect in database.
"""

import datetime
import json
from decimal import Decimal
from unittest import mock

import pytest
from core.models import (
    CategorieTarif,
    Inscription,
    Mail,
    ModeleDocument,
    NomTarif,
    Parametre,
    PortailRenseignement,
    Tarif,
    TarifLigne,
)
from django.urls import reverse
from tests.bureau.conftest import AJAX
from tests.unit.factories import (
    ActiviteFactory,
    GroupeFactory,
    StructureFactory,
    UtilisateurFactory,
    create_famille_complete,
)

FIN = datetime.date(2999, 1, 1)


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def camp(db, structure):
    """(activite, groupe, tarif) of the director's structure, still running."""
    activite = ActiviteFactory(structure=structure, nom="Camp d'été", date_debut=datetime.date(2026, 1, 1),
                               date_fin=FIN, nbre_inscrits_max=10)
    groupe = GroupeFactory(activite=activite, nom="Louveteaux", nbre_inscrits_max=3)
    nom_tarif = NomTarif.objects.create(activite=activite, nom="Formule")
    tarif = Tarif.objects.create(activite=activite, nom_tarif=nom_tarif, date_debut=datetime.date(2026, 1, 1),
                                 description="Séjour complet")
    TarifLigne.objects.create(activite=activite, tarif=tarif, montant_unique=Decimal("120"))
    return activite, groupe, tarif


@pytest.fixture
def camp_voisin(db):
    """(activite, groupe, tarif) of a structure the director does not belong to."""
    activite = ActiviteFactory(structure=StructureFactory(nom="Structure voisine"), nom="Camp voisin",
                               date_debut=datetime.date(2026, 1, 1), date_fin=FIN)
    groupe = GroupeFactory(activite=activite, nom="Groupe voisin")
    nom_tarif = NomTarif.objects.create(activite=activite, nom="Formule")
    tarif = Tarif.objects.create(activite=activite, nom_tarif=nom_tarif, date_debut=datetime.date(2026, 1, 1),
                                 description="Tarif voisin")
    return activite, groupe, tarif


@pytest.fixture
def famille(famille_bureau, activite):
    # The conftest activity has no end date, which the approbation page cannot display (see BUG below)
    activite.date_debut, activite.date_fin = datetime.date(2020, 1, 1), FIN
    activite.save()
    famille, _titulaire, enfant = famille_bureau
    famille.mail = "parents@test.org"
    famille.save()
    return famille, enfant


def _demande(famille, individu, activite, groupe, tarifs, etat="ATTENTE"):
    """A request exactly as the portail writes it (see portail/views/inscrire_activite.py)."""
    valeur = "%d;%d;%s" % (activite.pk, groupe.pk, json.dumps([str(t.pk) for t in tarifs]))
    return PortailRenseignement.objects.create(
        famille=famille, individu=individu, categorie="activites", code="inscrire_activite",
        nouvelle_valeur=json.dumps(valeur), etat=etat, activite=activite, validation_auto=False,
    )


def _autre_famille(username="autre_famille"):
    _user, famille, ratt = create_famille_complete(username=username)
    return famille, ratt[1].individu


def _datatable(client, url, colonnes, **params):
    """Reproduce the DataTables AJAX query of a crud.Liste and return its rows."""
    data = {"draw": "1", "start": "0", "length": "100", "search[value]": "", "search[regex]": "false"}
    for index, nom in enumerate(colonnes):
        data.update({
            f"columns[{index}][data]": str(index), f"columns[{index}][name]": nom,
            f"columns[{index}][searchable]": "true", f"columns[{index}][orderable]": "true",
            f"columns[{index}][search][value]": "", f"columns[{index}][search][regex]": "false",
        })
    data.update(params)
    response = client.get(url, data, **AJAX)
    assert response.status_code == 200, response.content
    return response.json()["data"]


def _texte(lignes):
    return json.dumps(lignes, ensure_ascii=False)


def _messages(response):
    return [str(m) for m in response.context["messages"]]


# ---------------------------------------------------------------------------
# Inscriptions en attente / refusées
# ---------------------------------------------------------------------------

def _selection(*activites):
    """POST data of the activities selection widget (SelectionActivitesWidget)."""
    return {"choix_activites": "activites", "liste_activites": [a.pk for a in activites]}


def _resultats(client, url_name, *activites):
    response = client.post(reverse(url_name), _selection(*activites))
    assert response.status_code == 200
    return json.loads(response.context["resultats"])


@pytest.mark.django_db
class TestInscriptionsEnAttente:
    def test_page_vide_sans_selection(self, directeur_client):
        response = directeur_client.get(reverse("liste_inscriptions_attente"))
        assert response.status_code == 200
        assert response.context["page_titre"] == "Liste des inscriptions en attente"
        assert json.loads(response.context["resultats"]) == []

    def test_selection_obligatoire(self, directeur_client):
        response = directeur_client.post(reverse("liste_inscriptions_attente"), {})
        assert response.status_code == 200
        assert "activites" in response.context["form_parametres"].errors

    def test_les_demandes_du_portail_sont_listees(self, directeur_client, famille, camp):
        famille, enfant = famille
        activite, groupe, tarif = camp
        _demande(famille, enfant, activite, groupe, [tarif])
        resultats = _resultats(directeur_client, "liste_inscriptions_attente", activite)

        assert [r["type"] for r in resultats] == ["activite", "inscription"]
        assert resultats[0]["label"] == activite.nom
        ligne = resultats[1]
        assert ligne["pid"] == resultats[0]["id"]
        assert enfant.Get_nom() in ligne["label"]
        assert ligne["categorie_tarif"] == "Pré-inscription"
        assert ligne["tarifs"] == "Séjour complet"
        assert reverse("famille_resume", args=[famille.pk]) in ligne["action"]

    def test_les_demandes_traitees_ne_sont_plus_listees(self, directeur_client, famille, camp):
        famille, enfant = famille
        activite, groupe, tarif = camp
        _demande(famille, enfant, activite, groupe, [tarif], etat="VALIDE")
        _demande(famille, enfant, activite, groupe, [tarif], etat="REFUS")
        assert _resultats(directeur_client, "liste_inscriptions_attente", activite) == []

    def test_places_restantes_du_groupe(self, directeur_client, famille, camp):
        """The group has 3 places, 2 are taken: the first request fits, the second does not."""
        famille, enfant = famille
        activite, groupe, tarif = camp
        for username in ("inscrit1", "inscrit2"):
            autre, individu = _autre_famille(username)
            Inscription.objects.create(famille=autre, individu=individu, activite=activite, groupe=groupe,
                                       date_debut=datetime.date(2026, 1, 1))
        _demande(famille, enfant, activite, groupe, [tarif])
        autre, individu = _autre_famille("demandeur2")
        _demande(autre, individu, activite, groupe, [tarif])

        lignes = [r for r in _resultats(directeur_client, "liste_inscriptions_attente", activite)
                  if r["type"] == "inscription"]
        assert "fa-check" in lignes[0]["label"]
        assert "fa-remove" in lignes[1]["label"]

    def test_demande_avec_valeur_corrompue_ignoree(self, directeur_client, famille, camp):
        famille, enfant = famille
        activite = camp[0]
        PortailRenseignement.objects.create(famille=famille, individu=enfant, categorie="activites",
                                            code="inscrire_activite", nouvelle_valeur='"abc"', etat="ATTENTE",
                                            activite=activite)
        assert _resultats(directeur_client, "liste_inscriptions_attente", activite) == []

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: Get_resultats() trusts the activity ids posted by the form and never restricts them to the "
        "director's structures: any director can read the pending requests (names, families) of any activity."
    ))
    def test_activite_d_une_autre_structure_non_listee(self, directeur_client, camp_voisin):
        activite, groupe, tarif = camp_voisin
        famille, individu = _autre_famille()
        _demande(famille, individu, activite, groupe, [tarif])
        assert _resultats(directeur_client, "liste_inscriptions_attente", activite) == []


@pytest.mark.django_db
class TestInscriptionsRefusees:
    def test_titre(self, directeur_client):
        response = directeur_client.get(reverse("liste_inscriptions_refus"))
        assert response.status_code == 200
        assert response.context["page_titre"] == "Liste des inscriptions refusées"

    def test_les_inscriptions_refusees_sont_listees(self, directeur_client, famille, camp):
        famille, enfant = famille
        activite, groupe, tarif = camp
        categorie = CategorieTarif.objects.create(activite=activite, nom="Normal")
        Inscription.objects.create(famille=famille, individu=enfant, activite=activite, groupe=groupe,
                                   categorie_tarif=categorie, statut="refus", date_debut=datetime.date(2026, 7, 1))
        resultats = _resultats(directeur_client, "liste_inscriptions_refus", activite)
        lignes = [r for r in resultats if r["type"] == "inscription"]
        assert len(lignes) == 1
        assert enfant.Get_nom() in lignes[0]["label"]
        assert lignes[0]["categorie_tarif"] == "Normal"

    def test_les_inscriptions_validees_ne_sont_pas_listees(self, directeur_client, famille, camp):
        famille, enfant = famille
        activite, groupe, _tarif = camp
        categorie = CategorieTarif.objects.create(activite=activite, nom="Normal")
        Inscription.objects.create(famille=famille, individu=enfant, activite=activite, groupe=groupe,
                                   categorie_tarif=categorie, date_debut=datetime.date(2026, 7, 1))
        assert _resultats(directeur_client, "liste_inscriptions_refus", activite) == []

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: Get_resultats() always adds the pending portail requests (etat='ATTENTE'), whatever self.etat: "
        "the 'Inscriptions refusées' page lists every pending request as a 'Pré-inscription'."
    ))
    def test_les_demandes_en_attente_ne_sont_pas_des_refus(self, directeur_client, famille, camp):
        famille, enfant = famille
        activite, groupe, tarif = camp
        _demande(famille, enfant, activite, groupe, [tarif])
        assert _resultats(directeur_client, "liste_inscriptions_refus", activite) == []

    @pytest.mark.xfail(strict=True, raises=AttributeError, reason=(
        "BUG: Get_resultats() reads inscription.categorie_tarif.nom but categorie_tarif is nullable: one "
        "refused inscription without tarif category crashes the page (500)."
    ))
    def test_inscription_refusee_sans_categorie_de_tarif(self, directeur_client, famille, camp):
        famille, enfant = famille
        activite, groupe, _tarif = camp
        Inscription.objects.create(famille=famille, individu=enfant, activite=activite, groupe=groupe,
                                   statut="refus", date_debut=datetime.date(2026, 7, 1))
        resultats = _resultats(directeur_client, "liste_inscriptions_refus", activite)
        assert len([r for r in resultats if r["type"] == "inscription"]) == 1


# ---------------------------------------------------------------------------
# Suivi des inscriptions
# ---------------------------------------------------------------------------

def _suivi(client, parametres=None, filtre=""):
    response = client.post(reverse("ajax_get_suivi_inscriptions"),
                           {"parametres": json.dumps(parametres), "filtre": filtre}, **AJAX)
    assert response.status_code == 200
    return {ligne["activite"].pk: ligne for ligne in response.context["data_suivi_inscriptions"]}


def _parametres_suivi(*activites, **extra):
    parametres = {"activites": {"type": "activites", "ids": [a.pk for a in activites]},
                  "masquer_activites_obsoletes": True, "masquer_individus_partis": True}
    parametres.update(extra)
    return parametres


@pytest.mark.django_db
class TestSuiviInscriptions:
    def test_page(self, directeur_client):
        response = directeur_client.get(reverse("suivi_inscriptions"))
        assert response.status_code == 200
        parametres = response.context["suivi_inscriptions_parametres"]
        assert parametres["activites"] == {}
        assert parametres["masquer_activites_obsoletes"] is True

    def test_sans_activite_selectionnee_tableau_vide(self, directeur_client):
        response = directeur_client.post(reverse("ajax_get_suivi_inscriptions"),
                                         {"parametres": "null"}, **AJAX)
        assert response.status_code == 200
        assert response.context["data_suivi_inscriptions"] == {}

    def test_compteurs(self, directeur_client, famille, camp):
        famille, enfant = famille
        activite, groupe, tarif = camp
        GroupeFactory(activite=activite, nom="Éclaireurs")
        for username, statut in (("inscrit1", "ok"), ("inscrit2", "ok"), ("refuse", "refus")):
            autre, individu = _autre_famille(username)
            Inscription.objects.create(famille=autre, individu=individu, activite=activite, groupe=groupe,
                                       statut=statut, date_debut=datetime.date(2026, 1, 1))
        autre, individu = _autre_famille("parti")
        Inscription.objects.create(famille=autre, individu=individu, activite=activite, groupe=groupe,
                                   date_debut=datetime.date(2020, 1, 1), date_fin=datetime.date(2020, 12, 31))
        _demande(famille, enfant, activite, groupe, [tarif])

        ligne = _suivi(directeur_client, _parametres_suivi(activite))[activite.pk]
        assert ligne["nbre_max"] == 10
        assert ligne["nbre_inscrits"] == 2
        assert ligne["nbre_refus"] == 1
        assert ligne["nbre_attente"] == 1
        assert ligne["nbre_dispo"] == 8
        louveteaux = next(g for g in ligne["groupes"] if g["groupe"] == groupe)
        assert (louveteaux["nbre_inscrits"], louveteaux["nbre_max"], louveteaux["nbre_dispo"]) == (2, 3, 1)

    def test_individus_partis_affiches_sur_demande(self, directeur_client, camp):
        activite, groupe, _tarif = camp
        autre, individu = _autre_famille("parti")
        Inscription.objects.create(famille=autre, individu=individu, activite=activite, groupe=groupe,
                                   date_debut=datetime.date(2020, 1, 1), date_fin=datetime.date(2020, 12, 31))
        ligne = _suivi(directeur_client, _parametres_suivi(activite, masquer_individus_partis=False))[activite.pk]
        assert ligne["nbre_inscrits"] == 1

    def test_activites_terminees_masquees(self, directeur_client, structure, camp):
        terminee = ActiviteFactory(structure=structure, date_debut=datetime.date(2020, 1, 1),
                                   date_fin=datetime.date(2020, 12, 31))
        assert set(_suivi(directeur_client, _parametres_suivi(camp[0], terminee))) == {camp[0].pk}
        lignes = _suivi(directeur_client, _parametres_suivi(camp[0], terminee, masquer_activites_obsoletes=False))
        assert set(lignes) == {camp[0].pk, terminee.pk}

    def test_filtre_sur_le_nom(self, directeur_client, structure, camp):
        autre = ActiviteFactory(structure=structure, nom="Week-end ski", date_debut=datetime.date(2026, 1, 1),
                                date_fin=FIN)
        assert set(_suivi(directeur_client, _parametres_suivi(camp[0], autre), filtre="ski")) == {autre.pk}

    def test_activite_d_une_autre_structure_exclue(self, directeur_client, camp, camp_voisin):
        assert set(_suivi(directeur_client, _parametres_suivi(camp[0], camp_voisin[0]))) == {camp[0].pk}

    def test_les_parametres_sont_memorises_par_utilisateur(self, directeur_client, directeur, camp):
        _suivi(directeur_client, _parametres_suivi(camp[0]))
        assert Parametre.objects.filter(categorie="suivi_inscriptions", utilisateur=directeur).exists()
        # A later refresh without new parameters reuses the stored selection
        assert set(_suivi(directeur_client, None)) == {camp[0].pk}

    def test_formulaire_de_selection_des_activites(self, directeur_client, camp):
        defaut = {"type": "activites", "ids": [camp[0].pk]}
        response = directeur_client.post(reverse("ajax_get_form_activites"), {"activites": json.dumps(defaut)},
                                         **AJAX)
        assert response.status_code == 200
        assert json.loads(response.context["form_activites"].fields["activites"].initial) == defaut

    def test_valider_la_selection_des_activites(self, directeur_client, camp):
        response = directeur_client.post(reverse("ajax_valider_form_activites"), _selection(camp[0]), **AJAX)
        assert response.status_code == 200
        assert json.loads(response.json()["activites"]) == {"type": "activites", "ids": [camp[0].pk]}

    def test_selection_vide_refusee(self, directeur_client):
        response = directeur_client.post(reverse("ajax_valider_form_activites"), {}, **AJAX)
        assert response.status_code == 401
        assert "erreur" in response.json()


@pytest.mark.django_db
class TestAccesAjax:
    URLS = ["ajax_get_suivi_inscriptions", "ajax_get_form_activites", "ajax_valider_form_activites",
            "ajax_appliquer_modification_portail", "ajax_tout_valider_portail",
            "ajax_inscriptions_impression_pdf", "ajax_inscriptions_email_pdf"]

    @pytest.mark.parametrize("url_name", URLS)
    def test_requete_non_ajax_refusee(self, directeur_client, url_name):
        assert directeur_client.post(reverse(url_name)).status_code == 400

    @pytest.mark.parametrize("url_name", URLS)
    def test_anonyme_refuse(self, client, url_name):
        assert client.post(reverse(url_name), **AJAX).status_code == 403

    @pytest.mark.parametrize("url_name", URLS)
    def test_compte_famille_refuse(self, client, famille_bureau, url_name):
        client.force_login(famille_bureau[0].utilisateur)
        assert client.post(reverse(url_name), **AJAX).status_code == 403

    @pytest.mark.parametrize("url_name", ["liste_inscriptions_attente", "liste_inscriptions_refus",
                                          "suivi_inscriptions", "demandes_portail_liste",
                                          "demande_approbation_liste", "inscriptions_impression",
                                          "inscriptions_email"])
    def test_pages_interdites_aux_familles(self, client, famille_bureau, url_name):
        client.force_login(famille_bureau[0].utilisateur)
        response = client.get(reverse(url_name))
        assert response.status_code in (302, 403)


# ---------------------------------------------------------------------------
# Demandes du portail
# ---------------------------------------------------------------------------

COLONNES_DEMANDES = ["check", "idrenseignement", "date", "famille", "individu", "code", "nouvelle_valeur",
                     "ancienne_valeur", "etat", "traitement", "boutons_validation", "actions"]


def _lignes_demandes(client):
    return _datatable(client, reverse("demandes_portail_liste"), COLONNES_DEMANDES)


def _traiter(client, demande, etat, **extra):
    return client.post(reverse("ajax_appliquer_modification_portail"),
                       {"iddemande": demande.pk, "etat": etat, **extra}, **AJAX)


@pytest.fixture
def mail_outbox(monkeypatch):
    from django.core import mail
    from outils.views import demandes_portail

    real_get_connection = mail.get_connection
    monkeypatch.setattr(demandes_portail.djangomail, "get_connection",
                        lambda *a, **kw: real_get_connection("django.core.mail.backends.locmem.EmailBackend"))
    mail.outbox = []
    return mail.outbox


@pytest.fixture
def adresse_expedition(db, set_parametre_portail):
    from tests.unit.factories import AdresseMailFactory

    adresse = AdresseMailFactory(adresse="noreply@sacadoc.test", moteur="console")
    set_parametre_portail("connexion_adresse_exp", adresse.pk)
    return adresse


@pytest.mark.django_db
class TestListeDemandesPortail:
    def test_page(self, directeur_client):
        response = directeur_client.get(reverse("demandes_portail_liste"))
        assert response.status_code == 200
        assert response.context["box_titre"] == "Liste des inscriptions en attentes"

    def test_rendu_d_une_demande_d_inscription(self, directeur_client, famille, camp):
        famille, enfant = famille
        activite, groupe, tarif = camp
        demande = _demande(famille, enfant, activite, groupe, [tarif])

        lignes = _lignes_demandes(directeur_client)
        assert len(lignes) == 1
        ligne = _texte(lignes[0])
        assert "Inscription à une activité" in ligne
        assert "%s (%s)" % (activite.nom, groupe.nom) in ligne
        assert "Attente" in ligne
        assert "traiter_demande(%d, 'VALIDE')" % demande.pk in ligne
        assert "ouvrir_popup_refus" in ligne
        assert reverse("famille_resume", args=[famille.pk]) in ligne

    def test_seules_les_demandes_en_attente_sont_listees(self, directeur_client, famille, camp):
        famille, enfant = famille
        activite, groupe, tarif = camp
        _demande(famille, enfant, activite, groupe, [tarif], etat="VALIDE")
        _demande(famille, enfant, activite, groupe, [tarif], etat="REFUS")
        assert _lignes_demandes(directeur_client) == []

    def test_demande_d_une_autre_structure_non_listee(self, directeur_client, camp_voisin):
        activite, groupe, tarif = camp_voisin
        famille, individu = _autre_famille()
        _demande(famille, individu, activite, groupe, [tarif])
        assert _lignes_demandes(directeur_client) == []


@pytest.mark.django_db
class TestTraiterDemandePortail:
    def test_valider_redirige_vers_le_formulaire_sans_tarif(self, directeur_client, famille, camp):
        """A request without tarif goes to the dedicated URL (no idstarifs segment)."""
        famille, enfant = famille
        activite, groupe, _tarif = camp
        demande = _demande(famille, enfant, activite, groupe, [])
        response = _traiter(directeur_client, demande, "VALIDE")
        assert response.json()["redirection"] == reverse("individu_inscriptions_ajouter1", kwargs={
            "idfamille": famille.pk, "idindividu": enfant.pk, "idactivite": activite.pk,
            "idgroupe": groupe.pk, "iddemande": demande.pk})

    def test_valider_avec_plusieurs_tarifs(self, directeur_client, famille, camp):
        famille, enfant = famille
        activite, groupe, tarif = camp
        tarif2 = Tarif.objects.create(activite=activite, nom_tarif=tarif.nom_tarif,
                                      date_debut=datetime.date(2026, 1, 1), description="Option")
        demande = _demande(famille, enfant, activite, groupe, [tarif, tarif2])
        redirection = _traiter(directeur_client, demande, "VALIDE").json()["redirection"]
        assert "/%d,%d/" % (tarif.pk, tarif2.pk) in redirection

    def test_refus_avec_message_par_defaut(self, directeur_client, directeur, famille, camp, adresse_expedition,
                                           mail_outbox):
        famille, enfant = famille
        activite, groupe, tarif = camp
        demande = _demande(famille, enfant, activite, groupe, [tarif])
        assert _traiter(directeur_client, demande, "REFUS").json() == {"succes": True, "redirection": None}

        demande.refresh_from_db()
        assert demande.etat == "REFUS"
        assert demande.traitement_utilisateur == directeur
        assert demande.traitement_date is not None
        assert len(mail_outbox) == 1
        email = mail_outbox[0]
        assert email.to == ["parents@test.org"]
        assert email.subject == "Refus de votre inscription"
        assert activite.nom in email.body and enfant.prenom in email.body

    def test_refus_avec_objet_personnalise(self, directeur_client, famille, camp, adresse_expedition, mail_outbox):
        famille, enfant = famille
        activite, groupe, tarif = camp
        demande = _demande(famille, enfant, activite, groupe, [tarif])
        _traiter(directeur_client, demande, "REFUS", email_objet="Camp complet", email_corps="Désolé.")
        assert (mail_outbox[0].subject, mail_outbox[0].body) == ("Camp complet", "Désolé.")

    def test_revalider_une_demande_refusee(self, directeur_client, famille, camp, adresse_expedition, mail_outbox):
        """A refused request can still be validated afterwards (the button stays available)."""
        famille, enfant = famille
        activite, groupe, tarif = camp
        demande = _demande(famille, enfant, activite, groupe, [tarif], etat="REFUS")
        assert _traiter(directeur_client, demande, "VALIDE").json()["redirection"]

    @pytest.mark.xfail(strict=True, raises=NameError, reason=(
        "BUG: envoyer_email_refus() returns _('...') when no 'connexion_adresse_exp' is configured, but '_' is "
        "never imported in outils/views/demandes_portail.py: refusing a request crashes (500) and the request "
        "stays pending."
    ))
    def test_refus_sans_adresse_d_expedition(self, directeur_client, famille, camp):
        famille, enfant = famille
        activite, groupe, tarif = camp
        demande = _demande(famille, enfant, activite, groupe, [tarif])
        _traiter(directeur_client, demande, "REFUS")
        demande.refresh_from_db()
        assert demande.etat == "REFUS"

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: Appliquer_modification() loads any PortailRenseignement by id without checking that its activity "
        "belongs to the director's structures: a director can refuse (and email) the requests of another structure."
    ))
    def test_refuser_la_demande_d_une_autre_structure_interdit(self, directeur_client, camp_voisin,
                                                               adresse_expedition, mail_outbox):
        activite, groupe, tarif = camp_voisin
        famille, individu = _autre_famille()
        demande = _demande(famille, individu, activite, groupe, [tarif])
        _traiter(directeur_client, demande, "REFUS")
        demande.refresh_from_db()
        assert demande.etat == "ATTENTE"

    def test_valider_une_modification_d_identite(self, directeur_client, famille):
        """Other categories are applied directly to the individual."""
        famille, enfant = famille
        demande = PortailRenseignement.objects.create(famille=famille, individu=enfant, categorie="individu_identite",
                                                      code="prenom", nouvelle_valeur=json.dumps("Léa"), etat="ATTENTE")
        assert _traiter(directeur_client, demande, "VALIDE").json()["redirection"] is None
        enfant.refresh_from_db()
        assert enfant.prenom == "Léa"

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: Traiter_demande() applies a validated non-inscription request but never sets etat='VALIDE' "
        "(nor saves the request): it stays pending forever and is applied again on each validation."
    ))
    def test_une_modification_validee_n_est_plus_en_attente(self, directeur_client, famille):
        famille, enfant = famille
        demande = PortailRenseignement.objects.create(famille=famille, individu=enfant, categorie="individu_identite",
                                                      code="prenom", nouvelle_valeur=json.dumps("Léa"), etat="ATTENTE")
        _traiter(directeur_client, demande, "VALIDE")
        demande.refresh_from_db()
        assert demande.etat == "VALIDE"

    def test_valider_les_regimes_alimentaires(self, directeur_client, famille):
        from core.models import RegimeAlimentaire

        famille, enfant = famille
        regime = RegimeAlimentaire.objects.create(nom="Sans gluten")
        demande = PortailRenseignement.objects.create(famille=famille, individu=enfant,
                                                      categorie="individu_regimes_alimentaires",
                                                      code="regimes_alimentaires",
                                                      nouvelle_valeur=json.dumps([regime.pk]), etat="ATTENTE")
        _traiter(directeur_client, demande, "VALIDE")
        assert list(enfant.regimes_alimentaires.all()) == [regime]


@pytest.mark.django_db
class TestToutValider:
    def _tout_valider(self, client, *demandes):
        response = client.post(reverse("ajax_tout_valider_portail"),
                               {"liste_demandes": json.dumps([d.pk for d in demandes])}, **AJAX)
        assert response.status_code == 200
        assert response.json() == {"resultat": "ok"}

    def test_les_demandes_d_inscription_ne_sont_pas_validees_en_masse(self, directeur_client, famille, camp):
        """An inscription needs the director to check the form: 'Tout valider' skips them on purpose."""
        famille, enfant = famille
        activite, groupe, tarif = camp
        demande = _demande(famille, enfant, activite, groupe, [tarif])
        self._tout_valider(directeur_client, demande)
        demande.refresh_from_db()
        assert demande.etat == "ATTENTE"
        assert not Inscription.objects.filter(individu=enfant, activite=activite).exists()

    def test_les_autres_demandes_sont_appliquees(self, directeur_client, famille):
        famille, enfant = famille
        demande = PortailRenseignement.objects.create(famille=famille, individu=enfant, categorie="individu_identite",
                                                      code="nom", nouvelle_valeur=json.dumps("DUPONT"), etat="ATTENTE")
        self._tout_valider(directeur_client, demande)
        enfant.refresh_from_db()
        assert enfant.nom == "DUPONT"

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: Tout_valider() applies any request id it receives, without checking that the family belongs to "
        "the director's structures: a director can overwrite the data of any family of the instance."
    ))
    def test_demande_d_une_famille_d_une_autre_structure_ignoree(self, directeur_client, camp_voisin):
        activite, groupe, _tarif = camp_voisin
        famille, individu = _autre_famille()
        Inscription.objects.create(famille=famille, individu=individu, activite=activite, groupe=groupe,
                                   date_debut=datetime.date(2026, 1, 1))
        demande = PortailRenseignement.objects.create(famille=famille, individu=individu,
                                                      categorie="individu_identite", code="nom",
                                                      nouvelle_valeur=json.dumps("PIRATE"), etat="ATTENTE")
        self._tout_valider(directeur_client, demande)
        individu.refresh_from_db()
        assert individu.nom != "PIRATE"


# ---------------------------------------------------------------------------
# Demandes de vérification (approbation)
# ---------------------------------------------------------------------------

COLONNES_APPROBATION = ["individu", "besoin_certification", "last_approbation", "actions"]


def _url_approbation(activite):
    return reverse("demande_approbation_liste", kwargs={"activite": "A%d" % activite.pk})


@pytest.fixture
def envoi_mail():
    with mock.patch("individus.views.demande_approbation.utils_email.Envoyer_model_mail",
                    return_value=True) as envoi:
        yield envoi


@pytest.fixture
def inscrit(famille, camp):
    famille, enfant = famille
    activite, groupe, _tarif = camp
    inscription = Inscription.objects.create(famille=famille, individu=enfant, activite=activite, groupe=groupe,
                                             date_debut=datetime.date(2026, 1, 1))
    return inscription


@pytest.mark.django_db
class TestDemandeApprobation:
    def test_liste_des_activites_de_mes_structures(self, directeur_client, camp, camp_voisin):
        response = directeur_client.get(reverse("demande_approbation_liste"))
        assert response.status_code == 200
        ids = [pk for pk, _label in response.context["liste_activites"]]
        assert camp[0].pk in ids
        assert camp_voisin[0].pk not in ids
        assert response.context["activite"] is None

    @pytest.mark.xfail(strict=True, raises=AttributeError, reason=(
        "BUG: Liste.get_context_data() tests activite.date_fin.year before checking date_fin is set: one visible "
        "activity without end date in the director's structures crashes the whole page (500)."
    ))
    def test_activite_sans_date_de_fin(self, directeur_client, structure):
        ActiviteFactory(structure=structure, nom="Activité ouverte", date_debut=datetime.date(2026, 1, 1))
        response = directeur_client.get(reverse("demande_approbation_liste"))
        assert response.status_code == 200

    def test_activite_illimitee(self, directeur_client, camp):
        response = directeur_client.get(_url_approbation(camp[0]))
        assert response.context["activite"] == camp[0].pk
        assert ("%s - Activité illimitée" % camp[0].nom) in [label for _pk, label in response.context["liste_activites"]]

    def test_contenu_de_la_liste(self, directeur_client, inscrit):
        lignes = _datatable(directeur_client, _url_approbation(inscrit.activite), COLONNES_APPROBATION)
        assert len(lignes) == 1
        ligne = _texte(lignes[0])
        assert inscrit.individu.nom in ligne
        assert "Non" in ligne
        assert reverse("demande_approbation_individuelle", args=[inscrit.pk]) in ligne

    def test_inscrits_d_une_autre_structure_invisibles(self, directeur_client, camp_voisin):
        activite, groupe, _tarif = camp_voisin
        famille, individu = _autre_famille()
        Inscription.objects.create(famille=famille, individu=individu, activite=activite, groupe=groupe,
                                   date_debut=datetime.date(2026, 1, 1))
        assert _datatable(directeur_client, _url_approbation(activite), COLONNES_APPROBATION) == []

    def test_action_sans_activite(self, directeur_client):
        response = directeur_client.post(reverse("demande_approbation_liste"), {"action": "demande_globale"},
                                         follow=True)
        assert "Aucune activité sélectionnée." in _messages(response)

    def test_demande_globale(self, directeur_client, inscrit, envoi_mail):
        response = directeur_client.post(_url_approbation(inscrit.activite), {"action": "demande_globale"},
                                         follow=True)
        inscrit.refresh_from_db()
        assert inscrit.besoin_certification is True
        mail = Mail.objects.get()
        assert inscrit.individu.prenom in mail.objet
        assert mail.destinataires.get().adresse == "parents@test.org"
        envoi_mail.assert_called_once()
        assert "1 inscriptions mises en demande de vérification." in _messages(response)

    def test_demande_globale_sans_email_famille(self, directeur_client, inscrit, envoi_mail):
        inscrit.famille.mail = ""
        inscrit.famille.save()
        response = directeur_client.post(_url_approbation(inscrit.activite), {"action": "demande_globale"},
                                         follow=True)
        inscrit.refresh_from_db()
        assert inscrit.besoin_certification is True
        assert not Mail.objects.exists()
        assert any("informations manquantes" in m for m in _messages(response))

    def test_echec_d_envoi_signale(self, directeur_client, inscrit):
        with mock.patch("individus.views.demande_approbation.utils_email.Envoyer_model_mail", return_value=False):
            response = directeur_client.post(_url_approbation(inscrit.activite), {"action": "demande_globale"},
                                             follow=True)
        assert any("n'a pas pu être envoyée" in m for m in _messages(response))

    def test_rappel_uniquement_aux_verifications_en_attente(self, directeur_client, inscrit, envoi_mail):
        autre, individu = _autre_famille()
        autre.mail = "autre@test.org"
        autre.save()
        Inscription.objects.create(famille=autre, individu=individu, activite=inscrit.activite,
                                   groupe=inscrit.groupe, date_debut=datetime.date(2026, 1, 1),
                                   besoin_certification=False)
        inscrit.besoin_certification = True
        inscrit.save()

        response = directeur_client.post(_url_approbation(inscrit.activite), {"action": "demande_rappel"},
                                         follow=True)
        mail = Mail.objects.get()
        assert mail.objet.startswith("[SACADOC] Rappel")
        assert mail.destinataires.get().adresse == "parents@test.org"
        assert "1 rappels envoyés." in _messages(response)

    def test_annulation(self, directeur_client, inscrit):
        inscrit.besoin_certification = True
        inscrit.save()
        directeur_client.post(_url_approbation(inscrit.activite), {"action": "demande_annulation"})
        inscrit.refresh_from_db()
        assert inscrit.besoin_certification is False

    def test_actions_sans_effet_sur_une_autre_structure(self, directeur_client, camp_voisin, envoi_mail):
        activite, groupe, _tarif = camp_voisin
        famille, individu = _autre_famille()
        inscription = Inscription.objects.create(famille=famille, individu=individu, activite=activite,
                                                 groupe=groupe, date_debut=datetime.date(2026, 1, 1))
        directeur_client.post(_url_approbation(activite), {"action": "demande_globale"})
        inscription.refresh_from_db()
        assert inscription.besoin_certification is False
        envoi_mail.assert_not_called()

    def test_demande_individuelle(self, directeur_client, inscrit, envoi_mail):
        response = directeur_client.get(reverse("demande_approbation_individuelle", args=[inscrit.pk]))
        assert response.status_code == 302
        assert response["Location"] == _url_approbation(inscrit.activite)
        inscrit.refresh_from_db()
        assert inscrit.besoin_certification is True
        assert Mail.objects.get().destinataires.get().adresse == "parents@test.org"
        envoi_mail.assert_called_once()

    def test_demande_individuelle_sans_email(self, directeur_client, inscrit, envoi_mail):
        inscrit.famille.mail = ""
        inscrit.famille.save()
        response = directeur_client.get(reverse("demande_approbation_individuelle", args=[inscrit.pk]), follow=True)
        assert any("informations manquantes" in m for m in _messages(response))
        envoi_mail.assert_not_called()

    def test_demande_individuelle_autre_structure_refusee(self, directeur_client, camp_voisin, envoi_mail):
        activite, groupe, _tarif = camp_voisin
        famille, individu = _autre_famille()
        inscription = Inscription.objects.create(famille=famille, individu=individu, activite=activite,
                                                 groupe=groupe, date_debut=datetime.date(2026, 1, 1))
        response = directeur_client.get(reverse("demande_approbation_individuelle", args=[inscription.pk]),
                                        follow=True)
        assert "Vous n'avez pas les droits sur cette activité." in _messages(response)
        inscription.refresh_from_db()
        assert inscription.besoin_certification is False
        envoi_mail.assert_not_called()

    def test_demande_individuelle_inscription_inconnue(self, directeur_client):
        assert directeur_client.get(reverse("demande_approbation_individuelle", args=[999999])).status_code == 404


# ---------------------------------------------------------------------------
# Impression / envoi par email des inscriptions
# ---------------------------------------------------------------------------

COLONNES_IMPRESSION = ["check", "idinscription", "date_debut", "date_fin", "individu", "famille", "activite",
                       "groupe", "categorie_tarif", "statut"]


@pytest.fixture
def modele_inscription(db):
    return ModeleDocument.objects.create(nom="Fiche d'inscription", categorie="inscription", largeur=210,
                                         hauteur=297, defaut=True, objets="[]")


@pytest.mark.django_db
class TestImpressionEtEmail:
    @pytest.mark.parametrize("url_name", ["inscriptions_impression", "inscriptions_email"])
    def test_page(self, directeur_client, modele_inscription, url_name):
        response = directeur_client.get(reverse(url_name))
        assert response.status_code == 200
        assert response.context["onglet_actif"] == url_name
        assert response.context["form_modele"].fields["modele"].initial == modele_inscription

    @pytest.mark.parametrize("url_name", ["inscriptions_impression", "inscriptions_email"])
    def test_seules_mes_inscriptions_sont_listees(self, directeur_client, inscrit, camp_voisin, url_name):
        activite, groupe, _tarif = camp_voisin
        famille, individu = _autre_famille()
        Inscription.objects.create(famille=famille, individu=individu, activite=activite, groupe=groupe,
                                   date_debut=datetime.date(2026, 1, 1))
        lignes = _datatable(directeur_client, reverse(url_name), COLONNES_IMPRESSION)
        mes_inscriptions = Inscription.objects.filter(activite__structure=inscrit.activite.structure)
        assert sorted(ligne["1"] for ligne in lignes) == sorted(str(i.pk) for i in mes_inscriptions)
        assert "Camp voisin" not in _texte(lignes)
        assert "Valide" in _texte(lignes)

    @pytest.mark.parametrize("url_name", ["ajax_inscriptions_impression_pdf", "ajax_inscriptions_email_pdf"])
    def test_aucune_inscription_cochee(self, directeur_client, url_name):
        response = directeur_client.post(reverse(url_name), {"inscriptions_cochees": "[]", "form_modele": "{}"},
                                         **AJAX)
        assert response.status_code == 401
        assert "cocher au moins une inscription" in response.json()["erreur"]

    @pytest.mark.parametrize("url_name", ["ajax_inscriptions_impression_pdf", "ajax_inscriptions_email_pdf"])
    def test_modele_obligatoire(self, directeur_client, inscrit, url_name):
        response = directeur_client.post(reverse(url_name), {"inscriptions_cochees": json.dumps([inscrit.pk]),
                                                             "form_modele": "{}"}, **AJAX)
        assert response.status_code == 401
        assert "modèle de document" in response.json()["erreur"]

    @pytest.mark.xfail(strict=True, raises=AttributeError, reason=(
        "BUG: utils_inscriptions.Inscriptions.GetDonneesImpression() reads inscription.tarif_id / "
        "inscription.tarif, but Inscription only has a 'tarifs' M2M: printing or emailing any inscription "
        "crashes (500). Note: Impression_pdf() also never checks that the ticked inscriptions belong to the "
        "director's structures."
    ))
    @pytest.mark.parametrize("url_name", ["ajax_inscriptions_impression_pdf", "ajax_inscriptions_email_pdf"])
    def test_generation_du_pdf(self, directeur_client, inscrit, modele_inscription, url_name):
        inscrit.categorie_tarif = CategorieTarif.objects.create(activite=inscrit.activite, nom="Normal")
        inscrit.save()
        response = directeur_client.post(reverse(url_name), {
            "inscriptions_cochees": json.dumps([inscrit.pk]),
            "form_modele": json.dumps({"modele": modele_inscription.pk}),
        }, **AJAX)
        assert response.status_code == 200
