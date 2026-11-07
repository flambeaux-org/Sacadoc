"""Facturation, end to end (director side):

1. the director looks for the families to invoice (Facturation > Générer des factures: period,
   activities, categories of prestations) and generates the invoices: numbering, totals, prestations
   linked to their invoice;
2. he consults an invoice from the fiche famille, removes or adds prestations (totals follow), edits it,
   cancels or deletes it;
3. he records the family's payments (Règlements) and allocates them to the prestations (ventilation):
   the invoice's 'solde actuel' follows;
4. the family sees its invoices and what remains to pay on the portal;
5. the invoices list only shows the invoices of the director's structures.

The portal payment itself (online payment, callbacks) is covered by tests/portail.
"""

import datetime
import json
import re
from decimal import Decimal

import pytest
from core.models import ComptaAnalytique, ComptaCategorie, CompteBancaire, Facture, ModeleImpression, ModeReglement, \
    Payeur, Prestation, Reglement, Utilisateur, Ventilation
from django.test import Client, RequestFactory
from django.urls import reverse
from tests.bureau.conftest import AJAX, build_form_data
from tests.bureau.test_bureau_prestations import _regler
from tests.unit.factories import ActiviteFactory, StructureFactory, create_famille_complete


# As typed in the date range picker
PERIODE = "01/01/2026 - 31/12/2026"


@pytest.fixture
def modele_facture(db):
    return ModeleImpression.objects.create(categorie="facture", nom="Facture standard", options="{}")


def _prestation(famille, activite, montant, individu=None, date=datetime.date(2026, 3, 1), categorie="consommation",
                label="Journée", **kwargs):
    return Prestation.objects.create(famille=famille, activite=activite, individu=individu, date=date, label=label,
                                     categorie=categorie, montant_initial=montant, montant=montant, **kwargs)


@pytest.fixture
def deux_journees(famille_bureau, activite):
    """Two unbilled days for the inscribed child in March 2026."""
    famille, _t, enfant = famille_bureau
    return (_prestation(famille, activite, Decimal("12.50"), individu=enfant, date=datetime.date(2026, 3, 2)),
            _prestation(famille, activite, Decimal("7.50"), individu=enfant, date=datetime.date(2026, 3, 3)))


# ---------------------------------------------------------------------------
# Génération des factures (real AJAX endpoints of the generation page)
# ---------------------------------------------------------------------------

def _parametres(activites, modele, famille=None, **extra):
    data = {"periode": PERIODE, "prochain_numero": "1", "date_emission": "2026-10-31", "date_echeance": "2026-11-30",
            "categories": ["consommation", "cotisation", "location", "autre"], "prestations_anterieures": "",
            "choix_activites": "activites", "liste_activites": [a.pk for a in activites],
            "selection_familles": "FAMILLE" if famille else "TOUTES", "famille": famille.pk if famille else "",
            "modelimp": modele.pk, "lot_factures": "", "prefixe": "", "date_limite_paiement": ""}
    data.update(extra)
    return data


def _rechercher(client, activites, modele, **extra):
    """Families (and amounts) proposed for invoicing, keyed by family id."""
    response = client.post(reverse("ajax_recherche_factures"), _parametres(activites, modele, **extra), **AJAX)
    assert response.status_code == 200, response.content
    return {f["IDfamille"]: f for f in response.context["factures"]}


def _generer(client, activites, modele, familles, **extra):
    avant = set(Facture.objects.values_list("pk", flat=True))
    data = _parametres(activites, modele, **extra)
    data["liste_factures_json"] = json.dumps([f.pk for f in familles])
    response = client.post(reverse("ajax_generation_factures"), data, **AJAX)
    if response.status_code != 200:
        return response
    return list(Facture.objects.exclude(pk__in=avant).order_by("numero"))


def _prochain_numero(client):
    return client.post(reverse("ajax_generation_factures_numero"), {}, **AJAX).json()["numero"]


@pytest.fixture
def facture(directeur_client, activite, modele_facture, famille_bureau, deux_journees):
    famille, _t, _e = famille_bureau
    return _generer(directeur_client, [activite], modele_facture, [famille])[0]


@pytest.mark.django_db
class TestRechercheDesFacturesAGenerer:
    def test_famille_avec_prestations_non_facturees(self, directeur_client, activite, modele_facture, famille_bureau,
                                                    deux_journees):
        famille, _t, _e = famille_bureau
        resultats = _rechercher(directeur_client, [activite], modele_facture)
        assert list(resultats) == [famille.pk]
        assert resultats[famille.pk]["total"] == Decimal("20.00")
        assert resultats[famille.pk]["solde"] == Decimal("20.00")
        assert set(resultats[famille.pk]["listePrestations"]) == set(deux_journees)

    def test_hors_periode_ignore(self, directeur_client, activite, modele_facture, famille_bureau, deux_journees):
        famille, _t, enfant = famille_bureau
        _prestation(famille, activite, Decimal("100"), individu=enfant, date=datetime.date(2025, 12, 31))
        assert _rechercher(directeur_client, [activite], modele_facture)[famille.pk]["total"] == Decimal("20.00")

    def test_prestations_anterieures_incluses_sur_demande(self, directeur_client, activite, modele_facture,
                                                          famille_bureau, deux_journees):
        famille, _t, enfant = famille_bureau
        _prestation(famille, activite, Decimal("100"), individu=enfant, date=datetime.date(2025, 12, 31))
        resultats = _rechercher(directeur_client, [activite], modele_facture, prestations_anterieures="2025-01-01")
        assert resultats[famille.pk]["total"] == Decimal("120.00")

    def test_categories_choisies(self, directeur_client, activite, modele_facture, famille_bureau, deux_journees):
        famille, _t, _e = famille_bureau
        _prestation(famille, activite, Decimal("15"), categorie="cotisation", label="Adhésion")
        seulement_conso = _rechercher(directeur_client, [activite], modele_facture, categories=["consommation"])
        seulement_adhesions = _rechercher(directeur_client, [activite], modele_facture, categories=["cotisation"])
        assert seulement_conso[famille.pk]["total"] == Decimal("20.00")
        assert seulement_adhesions[famille.pk]["total"] == Decimal("15.00")

    def test_activites_non_cochees_ignorees(self, directeur_client, structure, modele_facture, famille_bureau,
                                            deux_journees):
        autre_activite = ActiviteFactory(structure=structure, nom="Séjour")
        assert _rechercher(directeur_client, [autre_activite], modele_facture) == {}

    def test_une_seule_famille(self, directeur_client, activite, modele_facture, famille_bureau, deux_journees):
        famille, _t, _e = famille_bureau
        _u, autre, ratt = create_famille_complete(username="autre_famille")
        _prestation(autre, activite, Decimal("30"), individu=ratt[1].individu)
        assert len(_rechercher(directeur_client, [activite], modele_facture)) == 2
        assert list(_rechercher(directeur_client, [activite], modele_facture, famille=famille)) == [famille.pk]

    def test_famille_obligatoire_si_une_seule_famille(self, directeur_client, activite, modele_facture):
        response = directeur_client.post(reverse("ajax_recherche_factures"),
                                         _parametres([activite], modele_facture, selection_familles="FAMILLE"), **AJAX)
        assert response.status_code == 401
        assert "sélectionner une famille" in response.json()["erreur"]

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: Recherche_factures joins the form error messages with ', '.join(): Django's own messages "
        "('Ce champ est obligatoire.') are lazy translation proxies, so any missing parameter (période, "
        "modèle d'impression, date...) crashes with TypeError (500) instead of showing the error."
    ))
    def test_parametre_manquant_message_d_erreur(self, directeur_client, activite, modele_facture):
        response = directeur_client.post(reverse("ajax_recherche_factures"),
                                         _parametres([activite], modele_facture, periode=""), **AJAX)
        assert response.status_code == 401
        assert "obligatoire" in response.json()["erreur"]

    def test_reglement_anterieur_deduit(self, directeur_client, activite, modele_facture, famille_bureau,
                                        deux_journees):
        """A payment already allocated to a prestation is shown as paid on the invoice to come."""
        famille, _t, _e = famille_bureau
        _regler(famille, deux_journees[0], Decimal("12.50"))
        resultat = _rechercher(directeur_client, [activite], modele_facture)[famille.pk]
        assert (resultat["total"], resultat["ventilation"], resultat["solde"]) == \
            (Decimal("20.00"), Decimal("12.50"), Decimal("7.50"))


@pytest.mark.django_db
class TestGenerationDesFactures:
    def test_facture_generee(self, directeur_client, activite, modele_facture, famille_bureau, deux_journees):
        famille, _t, enfant = famille_bureau
        factures = _generer(directeur_client, [activite], modele_facture, [famille], prochain_numero="1")
        assert len(factures) == 1
        facture = factures[0]
        assert (facture.famille, facture.numero) == (famille, 1)
        assert (facture.total, facture.regle, facture.solde, facture.solde_actuel) == \
            (Decimal("20.00"), Decimal("0"), Decimal("20.00"), Decimal("20.00"))
        assert (facture.date_edition, facture.date_echeance) == (datetime.date(2026, 10, 31), datetime.date(2026, 11, 30))
        assert (facture.date_debut, facture.date_fin) == (datetime.date(2026, 1, 1), datetime.date(2026, 12, 31))
        assert facture.activites == str(activite.pk)
        assert facture.individus == str(enfant.pk)
        assert set(Prestation.objects.filter(facture=facture)) == set(deux_journees)

    def test_prestations_facturees_ne_sont_plus_proposees(self, directeur_client, activite, modele_facture,
                                                          famille_bureau, deux_journees):
        famille, _t, _e = famille_bureau
        _generer(directeur_client, [activite], modele_facture, [famille])
        assert _rechercher(directeur_client, [activite], modele_facture) == {}

    def test_seules_les_familles_cochees_sont_facturees(self, directeur_client, activite, modele_facture,
                                                        famille_bureau, deux_journees):
        famille, _t, _e = famille_bureau
        _u, autre, ratt = create_famille_complete(username="autre_famille")
        prestation_autre = _prestation(autre, activite, Decimal("30"), individu=ratt[1].individu)
        factures = _generer(directeur_client, [activite], modele_facture, [famille])
        assert [f.famille for f in factures] == [famille]
        prestation_autre.refresh_from_db()
        assert prestation_autre.facture is None

    def test_numeros_consecutifs(self, directeur_client, activite, modele_facture, famille_bureau, deux_journees):
        famille, _t, _e = famille_bureau
        _u, autre, ratt = create_famille_complete(username="autre_famille")
        _prestation(autre, activite, Decimal("30"), individu=ratt[1].individu)
        factures = _generer(directeur_client, [activite], modele_facture, [famille, autre], prochain_numero="41")
        assert sorted(f.numero for f in factures) == [41, 42]

    def test_prochain_numero_propose(self, directeur_client, activite, modele_facture, famille_bureau, deux_journees):
        famille, _t, _e = famille_bureau
        assert _prochain_numero(directeur_client) == 1
        _generer(directeur_client, [activite], modele_facture, [famille], prochain_numero="41")
        assert _prochain_numero(directeur_client) == 42
        form = directeur_client.get(reverse("factures_generation", args=[famille.pk])).context["form"]
        assert form.fields["prochain_numero"].initial == 42

    def test_la_numerotation_continue_apres_une_annulation(self, directeur_client, famille_bureau, facture):
        famille, _t, _e = famille_bureau
        directeur_client.post(reverse("famille_factures_annuler", args=[famille.pk, facture.pk]))
        assert _prochain_numero(directeur_client) == facture.numero + 1

    def test_aucune_famille_cochee(self, directeur_client, activite, modele_facture, famille_bureau, deux_journees):
        response = _generer(directeur_client, [activite], modele_facture, [])
        assert response.status_code == 401
        assert not Facture.objects.exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: 'Prochain numéro' can be typed by hand and is never checked: invoices are generated with a number "
        "already used by another invoice (invoice numbers must be unique and continuous)."
    ))
    def test_numero_deja_utilise_refuse(self, directeur_client, activite, modele_facture, famille_bureau,
                                        deux_journees, facture):
        famille, _t, enfant = famille_bureau
        _prestation(famille, activite, Decimal("5"), individu=enfant, date=datetime.date(2026, 4, 1))
        _generer(directeur_client, [activite], modele_facture, [famille], prochain_numero=str(facture.numero))
        assert Facture.objects.filter(numero=facture.numero).count() == 1

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: if none of the checked families still has something to invoice (e.g. the list was searched again "
        "in another tab), Generation_factures calls min() on an empty list: ValueError, 500."
    ))
    def test_famille_cochee_sans_rien_a_facturer(self, directeur_client, activite, modele_facture, famille_bureau,
                                                 deux_journees, facture):
        famille, _t, _e = famille_bureau
        response = _generer(directeur_client, [activite], modele_facture, [famille])
        assert response == [] or response.status_code == 401

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (périmètre): the activities posted to the generation are not checked against the director's "
        "structures: he can invoice the prestations of another structure's activity."
    ))
    def test_activite_d_une_autre_structure_non_facturable(self, directeur_client, modele_facture):
        autre_activite = ActiviteFactory(structure=StructureFactory(nom="Autre"), nom="Ailleurs")
        _u, autre, ratt = create_famille_complete(username="autre_famille")
        _prestation(autre, autre_activite, Decimal("30"), individu=ratt[1].individu)
        assert _rechercher(directeur_client, [autre_activite], modele_facture) == {}


# ===========================================================================
# Consultation et modification depuis la fiche famille
# ===========================================================================

@pytest.mark.django_db
class TestConsultationFacture:
    def test_consulter_les_prestations_de_la_facture(self, directeur_client, famille_bureau, facture, deux_journees):
        famille, _t, _e = famille_bureau
        response = directeur_client.get(reverse("famille_factures_consulter", args=[famille.pk, facture.pk]))
        assert response.context["facture"] == facture
        assert set(response.context["view"].get_queryset()) == set(deux_journees)
        assert "20,00" in response.context["stats"] or "20.00" in response.context["stats"]

    def test_retirer_une_prestation_recalcule_le_total(self, directeur_client, famille_bureau, facture, deux_journees):
        famille, _t, _e = famille_bureau
        directeur_client.post(reverse("famille_factures_supprimer_prestation",
                                      args=[famille.pk, facture.pk, deux_journees[1].pk]))
        facture.refresh_from_db()
        deux_journees[1].refresh_from_db()
        assert deux_journees[1].facture is None
        assert Prestation.objects.filter(pk=deux_journees[1].pk).exists()
        assert (facture.total, facture.solde, facture.solde_actuel) == (Decimal("12.50"),) * 3

    def test_retirer_plusieurs_prestations(self, directeur_client, famille_bureau, facture, deux_journees):
        famille, _t, _e = famille_bureau
        directeur_client.post(reverse("famille_factures_supprimer_plusieurs_prestations", kwargs={
            "idfamille": famille.pk, "idfacture": facture.pk, "listepk": ";".join(str(p.pk) for p in deux_journees)}))
        facture.refresh_from_db()
        assert facture.total == Decimal("0")
        assert not Prestation.objects.filter(facture=facture).exists()

    def test_ajouter_une_prestation_recalcule_le_total(self, directeur_client, famille_bureau, activite, facture):
        famille, _t, enfant = famille_bureau
        oubliee = _prestation(famille, activite, Decimal("5"), individu=enfant, date=datetime.date(2026, 4, 1))
        directeur_client.post(reverse("famille_factures_selection", args=[famille.pk, facture.pk]),
                              {"selections": json.dumps([oubliee.pk])})
        facture.refresh_from_db()
        oubliee.refresh_from_db()
        assert oubliee.facture == facture
        assert (facture.total, facture.solde_actuel) == (Decimal("25.00"), Decimal("25.00"))

    def test_seules_les_prestations_libres_de_la_famille_sont_proposees(self, directeur_client, famille_bureau,
                                                                        activite, facture):
        famille, _t, enfant = famille_bureau
        oubliee = _prestation(famille, activite, Decimal("5"), individu=enfant, date=datetime.date(2026, 4, 1))
        _u, autre, ratt = create_famille_complete(username="autre_famille")
        _prestation(autre, activite, Decimal("30"), individu=ratt[1].individu)
        page = directeur_client.get(reverse("famille_factures_selection", args=[famille.pk, facture.pk]))
        assert list(page.context["view"].get_queryset()) == [oubliee]

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the selection page only lists the family's unbilled prestations, but its POST accepts any id: a "
        "prestation of another family (or of another invoice) is moved into this invoice."
    ))
    def test_prestation_d_une_autre_famille_non_ajoutable(self, directeur_client, famille_bureau, activite, facture):
        famille, _t, _e = famille_bureau
        _u, autre, ratt = create_famille_complete(username="autre_famille")
        etrangere = _prestation(autre, activite, Decimal("30"), individu=ratt[1].individu)
        directeur_client.post(reverse("famille_factures_selection", args=[famille.pk, facture.pk]),
                              {"selections": json.dumps([etrangere.pk])})
        etrangere.refresh_from_db()
        assert etrangere.facture is None

    def test_modifier_la_date_d_emission(self, directeur_client, famille_bureau, facture):
        famille, _t, _e = famille_bureau
        url = reverse("famille_factures_modifier", args=[famille.pk, facture.pk])
        response = directeur_client.get(url)
        data = build_form_data(response.context["form"], date_edition="2026-11-02")
        assert directeur_client.post(url, data).status_code == 302
        facture.refresh_from_db()
        assert facture.date_edition == datetime.date(2026, 11, 2)

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the invoice edit form keeps date_echeance, date_limite_paiement, lot, regie and prefixe in its "
        "fields but no longer renders them: saving the invoice (e.g. to fix its date) wipes its due date and "
        "online payment deadline (the family can then pay after the deadline), its lot and its prefix."
    ))
    def test_modifier_conserve_les_champs_non_affiches(self, directeur_client, famille_bureau, facture):
        famille, _t, _e = famille_bureau
        Facture.objects.filter(pk=facture.pk).update(date_limite_paiement=datetime.date(2026, 11, 15))
        url = reverse("famille_factures_modifier", args=[famille.pk, facture.pk])
        response = directeur_client.get(url)
        html = response.content.decode()
        data = build_form_data(response.context["form"], date_edition="2026-11-02")
        data = {cle: valeur for cle, valeur in data.items() if 'name="%s"' % cle in html}
        assert directeur_client.post(url, data).status_code == 302
        facture.refresh_from_db()
        assert facture.date_echeance == datetime.date(2026, 11, 30)
        assert facture.date_limite_paiement == datetime.date(2026, 11, 15)


@pytest.mark.django_db
class TestAnnulationSuppression:
    def test_annuler_libere_les_prestations(self, directeur_client, famille_bureau, activite, modele_facture,
                                            facture, deux_journees):
        famille, _t, _e = famille_bureau
        directeur_client.post(reverse("famille_factures_annuler", args=[famille.pk, facture.pk]))
        facture.refresh_from_db()
        assert facture.etat == "annulation"
        assert not Prestation.objects.filter(facture=facture).exists()
        # The cancelled invoice is kept (its number is not reused) and its prestations can be invoiced again
        assert _rechercher(directeur_client, [activite], modele_facture)[famille.pk]["total"] == Decimal("20.00")

    def test_facture_annulee_absente_du_portail(self, directeur_client, famille_bureau, facture):
        famille, _t, _e = famille_bureau
        directeur_client.post(reverse("famille_factures_annuler", args=[famille.pk, facture.pk]))
        assert _portail_facturation(famille).context["liste_factures"] == []

    def test_supprimer_libere_les_prestations(self, directeur_client, famille_bureau, facture, deux_journees):
        famille, _t, _e = famille_bureau
        directeur_client.post(reverse("famille_factures_supprimer", args=[famille.pk, facture.pk]))
        assert not Facture.objects.exists()
        assert Prestation.objects.filter(pk__in=[p.pk for p in deux_journees], facture__isnull=True).count() == 2

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the fiche famille delete URL does not check that the invoice belongs to the family of the URL: "
        "from any family the director can delete the invoice of another family (of another structure)."
    ))
    def test_supprimer_la_facture_d_une_autre_famille_refuse(self, directeur_client, famille_bureau, modele_facture):
        famille, _t, _e = famille_bureau
        autre_activite = ActiviteFactory(structure=StructureFactory(nom="Autre"), nom="Ailleurs")
        _u, autre, _r = create_famille_complete(username="autre_famille")
        etrangere = Facture.objects.create(famille=autre, numero=99, date_edition=datetime.date(2026, 10, 31),
                                           date_debut=datetime.date(2026, 1, 1), date_fin=datetime.date(2026, 12, 31),
                                           activites=str(autre_activite.pk), total=Decimal("30"))
        directeur_client.post(reverse("famille_factures_supprimer_plusieurs",
                                      kwargs={"idfamille": famille.pk, "listepk": str(etrangere.pk)}))
        assert Facture.objects.filter(pk=etrangere.pk).exists()


# ===========================================================================
# Règlements et solde
# ===========================================================================

@pytest.fixture
def cheque(db):
    """A payment mode, plus the rows that the payment form hard-codes: Payeur 3 as default payer (bug pinned in
    test_bureau_fiches_pages), accounting categories 1 and 33 and analytic 1 (famille_reglements.form_valid)."""
    _u, famille_payeur, _r = create_famille_complete(username="famille_payeur_3")
    Payeur.objects.create(pk=3, famille=famille_payeur, nom="Payeur par défaut")
    for pk in (1, 33):
        ComptaCategorie.objects.create(pk=pk, type="credit", nom="Catégorie %d" % pk)
    ComptaAnalytique.objects.create(pk=1, nom="Analytique")
    CompteBancaire.objects.create(nom="Compte courant")
    ModeleImpression.objects.create(categorie="reglement", nom="Reçu")
    return ModeReglement.objects.create(label="Chèque")


def _ventilation_proposee(client, famille, reglement=None):
    response = client.post(reverse("ajax_get_ventilation"), {
        "idfamille": famille.pk, "idreglement": reglement.pk if reglement else 0}, **AJAX)
    # Rows of the allocation table: one JS 'Ligne' per prestation with what remains to allocate
    lignes = re.findall(r"idprestation: (\d+),.*?reste_ventilation: parseFloat\(([-\d.]+)\)",
                        response.content.decode(), re.S)
    return {Prestation.objects.get(pk=int(pk)): Decimal(reste) for pk, reste in lignes}


def _regler_ui(client, famille, mode, montant, ventilation, reglement=None):
    """Fiche famille > Règlements > Ajouter (or Modifier): amount and allocation to prestations."""
    if reglement:
        url = reverse("famille_reglements_modifier", args=[famille.pk, reglement.pk])
    else:
        url = reverse("famille_reglements_ajouter", args=[famille.pk])
    form = client.get(url).context["form"]
    payeur = Payeur.objects.filter(famille=famille).first() or Payeur.objects.create(famille=famille, nom=famille.nom)
    assert payeur.pk != 3
    data = build_form_data(form, famille=famille.pk, date="2026-11-02", mode=mode.pk, payeur=payeur.pk,
                           compte=CompteBancaire.objects.get().pk, modelimp=ModeleImpression.objects.get(categorie="reglement").pk,
                           montant=str(montant), ventilation=json.dumps(
                               [{"idprestation": p.pk, "montant": str(m)} for p, m in ventilation]))
    return client.post(url, data)


@pytest.mark.django_db
class TestReglements:
    def test_ventilation_proposee(self, directeur_client, famille_bureau, facture, deux_journees):
        famille, _t, _e = famille_bureau
        _regler(famille, deux_journees[0], Decimal("10"))
        assert _ventilation_proposee(directeur_client, famille) == {deux_journees[0]: Decimal("2.50"),
                                                                    deux_journees[1]: Decimal("7.50")}

    def test_reglement_total_solde_la_facture(self, directeur_client, famille_bureau, facture, deux_journees, cheque):
        famille, _t, _e = famille_bureau
        response = _regler_ui(directeur_client, famille, cheque, Decimal("20"),
                              [(deux_journees[0], Decimal("12.50")), (deux_journees[1], Decimal("7.50"))])
        assert response.status_code == 302, response.context["form"].errors
        reglement = Reglement.objects.get()
        assert (reglement.famille, reglement.montant, reglement.mode) == (famille, Decimal("20"), cheque)
        assert Ventilation.objects.filter(reglement=reglement).count() == 2
        facture.refresh_from_db()
        assert (facture.regle, facture.solde_actuel) == (Decimal("20.00"), Decimal("0"))
        assert _ventilation_proposee(directeur_client, famille) == {}

    def test_reglement_partiel(self, directeur_client, famille_bureau, facture, deux_journees, cheque):
        famille, _t, _e = famille_bureau
        _regler_ui(directeur_client, famille, cheque, Decimal("12.50"), [(deux_journees[0], Decimal("12.50"))])
        facture.refresh_from_db()
        assert facture.solde_actuel == Decimal("7.50")

    def test_ventilation_differente_du_montant_refusee(self, directeur_client, famille_bureau, facture, deux_journees,
                                                       cheque):
        famille, _t, _e = famille_bureau
        response = _regler_ui(directeur_client, famille, cheque, Decimal("20"), [(deux_journees[0], Decimal("12.50"))])
        assert response.status_code == 200
        assert "ne correspond pas au montant" in str(response.context["form"].non_field_errors())
        assert not Reglement.objects.exists()

    def test_modifier_la_ventilation(self, directeur_client, famille_bureau, facture, deux_journees, cheque):
        famille, _t, _e = famille_bureau
        _regler_ui(directeur_client, famille, cheque, Decimal("12.50"), [(deux_journees[0], Decimal("12.50"))])
        reglement = Reglement.objects.get()
        response = _regler_ui(directeur_client, famille, cheque, Decimal("12.50"),
                              [(deux_journees[0], Decimal("5")), (deux_journees[1], Decimal("7.50"))],
                              reglement=reglement)
        assert response.status_code == 302, response.context["form"].errors
        assert {v.prestation: v.montant for v in Ventilation.objects.filter(reglement=reglement)} == \
            {deux_journees[0]: Decimal("5"), deux_journees[1]: Decimal("7.50")}
        facture.refresh_from_db()
        assert facture.solde_actuel == Decimal("7.50")

    def test_supprimer_le_reglement_remet_la_facture_a_payer(self, directeur_client, famille_bureau, facture,
                                                             deux_journees, cheque):
        famille, _t, _e = famille_bureau
        _regler_ui(directeur_client, famille, cheque, Decimal("20"),
                   [(deux_journees[0], Decimal("12.50")), (deux_journees[1], Decimal("7.50"))])
        reglement = Reglement.objects.get()
        directeur_client.post(reverse("famille_reglements_supprimer", args=[famille.pk, reglement.pk]))
        assert not Reglement.objects.exists()
        facture.refresh_from_db()
        assert facture.solde_actuel == Decimal("20.00")

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the allocation is only checked against the payment amount, not against what remains to pay on each "
        "prestation: 20 € allocated to a 12.50 € day is accepted, the invoice shows a negative balance and the "
        "other day stays unpaid."
    ))
    def test_ventilation_superieure_au_reste_refusee(self, directeur_client, famille_bureau, facture, deux_journees,
                                                     cheque):
        famille, _t, _e = famille_bureau
        _regler_ui(directeur_client, famille, cheque, Decimal("20"), [(deux_journees[0], Decimal("20"))])
        assert not Reglement.objects.exists()
        facture.refresh_from_db()
        assert facture.solde_actuel == Decimal("20.00")

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the allocation posted with a payment is not checked against the family: a payment of family A "
        "can be allocated to a prestation of family B (the ventilation is then recorded under family A)."
    ))
    def test_ventilation_sur_la_prestation_d_une_autre_famille_refusee(self, directeur_client, famille_bureau,
                                                                       activite, cheque):
        famille, _t, _e = famille_bureau
        _u, autre, ratt = create_famille_complete(username="autre_famille")
        etrangere = _prestation(autre, activite, Decimal("30"), individu=ratt[1].individu)
        _regler_ui(directeur_client, famille, cheque, Decimal("30"), [(etrangere, Decimal("30"))])
        assert not Ventilation.objects.filter(prestation=etrangere).exists()


# ===========================================================================
# Portail : la famille voit ses factures
# ===========================================================================

def _portail_facturation(famille):
    client = Client()
    client.force_login(Utilisateur.objects.get(pk=famille.utilisateur_id))
    response = client.get(reverse("portail_facturation"))
    assert response.status_code == 200
    return response


@pytest.mark.django_db
class TestPortail:
    def test_facture_generee_visible_et_a_payer(self, famille_bureau, facture):
        famille, _t, _e = famille_bureau
        response = _portail_facturation(famille)
        assert response.context["liste_factures"] == [facture]
        assert response.context["liste_factures_impayees"] == [facture]
        assert "20,00" in response.context["texte_impayes"] or "20.00" in response.context["texte_impayes"]

    def test_facture_reglee_n_est_plus_a_payer(self, directeur_client, famille_bureau, facture, deux_journees, cheque):
        famille, _t, _e = famille_bureau
        _regler_ui(directeur_client, famille, cheque, Decimal("20"),
                   [(deux_journees[0], Decimal("12.50")), (deux_journees[1], Decimal("7.50"))])
        response = _portail_facturation(famille)
        assert response.context["liste_factures"] == [facture]
        assert response.context["liste_factures_impayees"] == []
        assert response.context["texte_impayes"] is None

    def test_factures_d_une_autre_famille_invisibles(self, famille_bureau, facture):
        _u, autre, _r = create_famille_complete(username="autre_famille")
        assert _portail_facturation(autre).context["liste_factures"] == []

    def test_paiement_en_ligne_ferme_apres_la_date_limite(self, famille_bureau, facture):
        famille, _t, _e = famille_bureau
        Facture.objects.filter(pk=facture.pk).update(date_limite_paiement=datetime.date(2020, 1, 1))
        response = _portail_facturation(famille)
        assert response.context["liste_factures"] == [facture]
        assert response.context["liste_factures_impayees"] == []


# ===========================================================================
# Liste des factures (Facturation > Liste des factures)
# ===========================================================================

def _liste_factures(directeur):
    from facturation.views.liste_factures import Liste

    request = RequestFactory().get(reverse("liste_factures"))
    request.user = directeur
    view = Liste()
    view.setup(request)
    return list(view.get_queryset())


@pytest.mark.django_db
class TestListeDesFactures:
    def test_mes_factures_listees(self, directeur, facture):
        assert _liste_factures(directeur) == [facture]

    def test_factures_d_une_autre_structure_masquees(self, directeur, facture):
        autre_activite = ActiviteFactory(structure=StructureFactory(nom="Autre"), nom="Ailleurs")
        _u, autre, _r = create_famille_complete(username="autre_famille")
        Facture.objects.create(famille=autre, numero=99, date_edition=datetime.date(2026, 10, 31),
                               date_debut=datetime.date(2026, 1, 1), date_fin=datetime.date(2026, 12, 31),
                               activites=str(autre_activite.pk), total=Decimal("30"))
        assert _liste_factures(directeur) == [facture]

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: Facture.activites is a text field ('3;5') filtered with activites__in=<activities>: an invoice "
        "covering two activities never matches and is missing from 'Liste des factures' (and from every list "
        "built the same way)."
    ))
    def test_facture_sur_deux_activites_listee(self, directeur, directeur_client, structure, activite,
                                               modele_facture, famille_bureau, deux_journees):
        famille, _t, enfant = famille_bureau
        sejour = ActiviteFactory(structure=structure, nom="Séjour")
        _prestation(famille, sejour, Decimal("100"), individu=enfant, date=datetime.date(2026, 7, 10))
        facture = _generer(directeur_client, [activite, sejour], modele_facture, [famille])[0]
        assert set(facture.activites.split(";")) == {str(activite.pk), str(sejour.pk)}
        assert _liste_factures(directeur) == [facture]
