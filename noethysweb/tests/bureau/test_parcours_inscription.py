"""End-to-end inscription journey: the family asks on the portail, the director handles it in the bureau.

Each side has its own tests (tests/portail/integration/test_portail_inscrire_activite.py and
tests/bureau/test_bureau_inscriptions.py), but the bureau ones build the PortailRenseignement by hand.
Here the request is created by the real portail view, so a change in the "idactivite;idgroupe;[idtarifs]"
format written by the portail and parsed by the bureau is caught.

Journey:
1. the parent submits the inscription wizard -> PortailRenseignement ATTENTE;
2. the director sees it in "demandes du portail" and validates it -> redirected to the pre-filled form;
3. the director confirms -> Inscription + Prestation, request VALIDE, confirmation email to the family;
4. the parent sees the inscription on the portail and no pending request anymore.
"""

import datetime
import json
from decimal import Decimal

import pytest
from core.models import CategorieTarif, Inscription, NomTarif, PortailRenseignement, Prestation, Tarif, TarifLigne
from django.test import Client, RequestFactory
from django.urls import reverse
from outils.views.demandes_portail import Liste as ListeDemandes
from tests.bureau.conftest import AJAX, build_form_data
from tests.unit.factories import ActiviteFactory, AdresseMailFactory, GroupeFactory, StructureFactory


@pytest.fixture
def camp(db, structure):
    """An activity of the director's structure, open on the portail, with one group and one 120 € tarif."""
    activite = ActiviteFactory(structure=structure, nom="Camp d'été", maitrise=False, public=5)
    groupe = GroupeFactory(activite=activite, nom="Louveteaux")
    categorie = CategorieTarif.objects.create(activite=activite, nom="Normal")
    nom_tarif = NomTarif.objects.create(activite=activite, nom="Formule", visible=True)
    tarif = Tarif.objects.create(activite=activite, nom_tarif=nom_tarif, type="FORFAIT",
                                 date_debut=datetime.date(2026, 1, 1), description="Séjour complet", visible=True)
    tarif.categories_tarifs.add(categorie)
    TarifLigne.objects.create(activite=activite, tarif=tarif, montant_unique=Decimal("120"))
    return activite, groupe, tarif


@pytest.fixture
def mail_outbox(monkeypatch, set_parametre_portail):
    """Configure the sender address and route the emails sent by the bureau (confirmation / refusal) to locmem."""
    from django.core import mail
    from fiche_individu.forms import individu_inscriptions
    from outils.views import demandes_portail

    adresse = AdresseMailFactory(adresse="noreply@sacadoc.test", moteur="console")
    set_parametre_portail("connexion_adresse_exp", adresse.pk)
    real_get_connection = mail.get_connection

    def locmem(*args, **kwargs):
        return real_get_connection("django.core.mail.backends.locmem.EmailBackend")

    monkeypatch.setattr(individu_inscriptions.djangomail, "get_connection", locmem)
    monkeypatch.setattr(demandes_portail.djangomail, "get_connection", locmem)
    mail.outbox = []
    return mail.outbox


@pytest.fixture
def parcours(db, organisateur, directeur_client, famille_bureau, camp, mail_outbox):
    famille, _titulaire, enfant = famille_bureau
    famille.mail = "parents@test.org"
    famille.save()
    parent_client = Client()
    parent_client.force_login(famille.utilisateur)
    return {"parent": parent_client, "directeur": directeur_client, "famille": famille, "enfant": enfant,
            "camp": camp, "outbox": mail_outbox}


def _demander_inscription(p):
    """Step 1, portail: the parent submits the inscription wizard."""
    activite, groupe, tarif = p["camp"]
    response = p["parent"].post(reverse("portail_ajax_inscrire_valid_form"), {
        "individu": p["enfant"].pk,
        "structure": activite.structure_id,
        "activite": activite.pk,
        "groupe": groupe.pk,
        "tarifs_%d" % tarif.nom_tarif_id: tarif.pk,
    }, **AJAX)
    assert response.status_code == 200, response.content
    assert response.json()["succes"] is True
    return PortailRenseignement.objects.filter(famille=p["famille"], individu=p["enfant"],
                                               code="inscrire_activite").latest("pk")


def _demandes_visibles_par(directeur):
    request = RequestFactory().get(reverse("demandes_portail_liste"))
    request.user = directeur
    view = ListeDemandes()
    view.setup(request)
    return list(view.get_queryset())


def _traiter(p, demande, etat, **extra):
    """Step 2, bureau: the director clicks "Valider" / "Refuser" in the requests list."""
    response = p["directeur"].post(reverse("ajax_appliquer_modification_portail"),
                                   {"iddemande": demande.pk, "etat": etat, **extra}, **AJAX)
    assert response.status_code == 200
    return response.json()


def _demandes_en_attente_portail(p):
    response = p["parent"].get(reverse("portail_activites"))
    assert response.status_code == 200
    return response.context["demandes_inscriptions_attente"], response.context["liste_individus"]


@pytest.mark.django_db
def test_demande_du_portail_validee_par_le_directeur(parcours, directeur):
    p = parcours
    activite, groupe, tarif = p["camp"]
    enfant, famille = p["enfant"], p["famille"]

    # 1. Portail: the parent asks, the request is pending on both sides
    demande = _demander_inscription(p)
    assert demande.etat == "ATTENTE"
    attente, _individus = _demandes_en_attente_portail(p)
    assert [d.nom_activite for d in attente] == [activite.nom]
    assert demande in _demandes_visibles_par(directeur)
    assert not Inscription.objects.filter(individu=enfant, activite=activite).exists()

    # 2. Bureau: "Valider" redirects to the inscription form, pre-filled with the family's choices
    redirection = _traiter(p, demande, "VALIDE")["redirection"]
    assert redirection == reverse("individu_inscriptions_ajouter", kwargs={
        "idfamille": famille.pk, "idindividu": enfant.pk, "idactivite": activite.pk,
        "idgroupe": groupe.pk, "idstarifs": str(tarif.pk), "iddemande": demande.pk,
    })
    demande.refresh_from_db()
    assert demande.etat == "ATTENTE", "the request stays pending until the director confirms the inscription"

    form = p["directeur"].get(redirection).context["form"]
    assert form.fields["activite"].initial == activite.pk
    assert form.fields["groupe"].initial == groupe.pk
    assert [t.pk for t in form.fields["tarifs"].initial] == [tarif.pk]

    # 3. Bureau: the director confirms
    data = build_form_data(form, individu=enfant.pk, famille=famille.pk, activite=activite.pk, groupe=groupe.pk,
                           tarifs=[tarif.pk], date_debut="2026-07-01", statut="ok")
    response = p["directeur"].post(redirection, data)
    assert response.status_code == 302, response.context and response.context["form"].errors.as_json()

    inscription = Inscription.objects.get(individu=enfant, activite=activite)
    assert (inscription.famille, inscription.groupe) == (famille, groupe)
    assert list(inscription.tarifs.all()) == [tarif]
    prestation = Prestation.objects.get(famille=famille, individu=enfant, activite=activite)
    assert prestation.montant == Decimal("120")

    demande.refresh_from_db()
    assert demande.etat == "VALIDE"
    assert demande.traitement_utilisateur == directeur
    assert demande not in _demandes_visibles_par(directeur)

    assert len(p["outbox"]) == 1
    assert p["outbox"][0].to == ["parents@test.org"]
    assert p["outbox"][0].subject == "Confirmation d'inscription"

    # 4. Portail: the inscription is listed, nothing pending anymore
    attente, individus = _demandes_en_attente_portail(p)
    assert attente == []
    individu = next(i for i in individus if i.pk == enfant.pk)
    assert activite in [i.activite for i in individu.inscriptions]


@pytest.mark.django_db
def test_demande_du_portail_refusee_par_le_directeur(parcours, directeur):
    p = parcours
    activite = p["camp"][0]

    demande = _demander_inscription(p)
    assert _traiter(p, demande, "REFUS", email_corps="Le camp est réservé aux plus grands.")["redirection"] is None

    demande.refresh_from_db()
    assert demande.etat == "REFUS"
    assert demande.traitement_utilisateur == directeur
    assert not Inscription.objects.filter(individu=p["enfant"], activite=activite).exists()

    assert len(p["outbox"]) == 1
    assert p["outbox"][0].to == ["parents@test.org"]
    assert p["outbox"][0].body == "Le camp est réservé aux plus grands."

    # The refused request is no longer pending, so the family can ask again
    attente, _individus = _demandes_en_attente_portail(p)
    assert attente == []
    nouvelle = _demander_inscription(p)
    assert nouvelle.pk != demande.pk and nouvelle.etat == "ATTENTE"


@pytest.mark.django_db
def test_demande_invisible_pour_le_directeur_d_une_autre_structure(parcours, organisateur):
    from tests.unit.factories import UtilisateurFactory

    autre_directeur = UtilisateurFactory(username="autre_directeur")
    autre_directeur.structures.add(StructureFactory())
    demande = _demander_inscription(parcours)
    assert demande not in _demandes_visibles_par(autre_directeur)
