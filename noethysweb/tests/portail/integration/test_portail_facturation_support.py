"""Shared builders for the test_portail_facturation_* test modules.

(Not a test module itself: it only holds helpers, imported with
`from test_portail_facturation_support import ...` since tests/portail has no
package structure.)
"""

import datetime
import decimal
import json

from core.models import (
    CompteBancaire,
    Cotisation,
    FactureRegie,
    ModeleImpression,
    ModeReglement,
    Paiement,
    Payeur,
    PortailPeriode,
    Prestation,
    Reglement,
    TypeCotisation,
    UniteCotisation,
    Ventilation,
)
from tests.unit.factories import ActiviteFactory, FactureFactory

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

TODAY = datetime.date.today()


def make_compte(nom="Compte test"):
    return CompteBancaire.objects.create(nom=nom)


def make_mode_reglement(label="Carte bancaire"):
    return ModeReglement.objects.create(label=label)


def make_modele_impression(nom="Modele test", options=None, categorie="reglement"):
    if options is None:
        options = {
            "signataire": "Le tresorier",
            "intro": "Recu",
            "afficher_prestations": False,
        }
    return ModeleImpression.objects.create(
        categorie=categorie, nom=nom, options=json.dumps(options)
    )


def make_regie(compte=None, nom="Régie Éducation"):
    return FactureRegie.objects.create(
        nom=nom,
        numclitipi="123456",
        email_regisseur="regie@example.org",
        compte_bancaire=compte,
    )


def make_prestation(
    famille, activite=None, montant=50, date=None, facture=None, label="Prestation"
):
    return Prestation.objects.create(
        famille=famille,
        activite=activite if activite is not None else ActiviteFactory(),
        montant=decimal.Decimal(str(montant)),
        montant_initial=decimal.Decimal(str(montant)),
        date=date or datetime.date(2024, 3, 1),
        facture=facture,
        label=label,
    )


def make_reglement(
    famille, montant=10, mode=None, compte=None, modelimp=None, payeur=None
):
    payeur = payeur or Payeur.objects.create(famille=famille, nom="Payeur")
    return Reglement.objects.create(
        famille=famille,
        date=TODAY,
        mode=mode or make_mode_reglement(),
        montant=decimal.Decimal(str(montant)),
        payeur=payeur,
        compte=compte or make_compte(),
        modelimp=modelimp or make_modele_impression(nom="Mod reglement"),
    )


def ventiler(reglement, prestation, montant):
    return Ventilation.objects.create(
        famille=reglement.famille,
        reglement=reglement,
        prestation=prestation,
        montant=decimal.Decimal(str(montant)),
    )


def make_facture(famille, prestation_montant=100, activite=None, **kwargs):
    """A facture with one linked prestation (total = prestation_montant)."""
    kwargs.setdefault("total", prestation_montant)
    kwargs.setdefault("solde_actuel", prestation_montant)
    facture = FactureFactory(famille=famille, **kwargs)
    prestation = make_prestation(
        famille, activite=activite, montant=prestation_montant, facture=facture
    )
    return facture, prestation


def make_periode(activite, prefacturation=True, **kwargs):
    kwargs.setdefault("nom", "Periode test")
    kwargs.setdefault("date_debut", datetime.date(2024, 3, 1))
    kwargs.setdefault("date_fin", datetime.date(2024, 3, 31))
    return PortailPeriode.objects.create(
        activite=activite, prefacturation=prefacturation, **kwargs
    )


def make_cotisation(famille, montant=30, prefacturation=True):
    """A cotisation prestation (returned) whose unite has `prefacturation`."""
    type_cotisation = TypeCotisation.objects.create(nom="Adhésion")
    unite = UniteCotisation.objects.create(
        type_cotisation=type_cotisation,
        nom="Unité",
        montant=montant,
        prefacturation=prefacturation,
    )
    prestation = make_prestation(
        famille, montant=montant, label="Adhésion", date=datetime.date(2024, 4, 1)
    )
    Cotisation.objects.create(
        famille=famille,
        type_cotisation=type_cotisation,
        unite_cotisation=unite,
        date_debut=datetime.date(2024, 1, 1),
        date_fin=datetime.date(2024, 12, 31),
        prestation=prestation,
    )
    return prestation


def make_paiement(
    famille, systeme="payzen", ventilation="", montant=10, idtransaction="TX1", **kwargs
):
    return Paiement.objects.create(
        famille=famille,
        systeme_paiement=systeme,
        idtransaction=idtransaction,
        montant=decimal.Decimal(str(montant)),
        ventilation=ventilation,
        **kwargs,
    )


def configure_paiement_en_ligne(
    set_parametre_portail, systeme, mode=None, compte=None, **extra
):
    """Persist the portail parameters needed to record an online payment.

    Returns (mode_reglement, compte_bancaire)."""
    mode = mode or make_mode_reglement()
    compte = compte or make_compte()
    set_parametre_portail("paiement_ligne_systeme", systeme)
    set_parametre_portail("paiement_ligne_mode_reglement", mode.pk)
    set_parametre_portail("paiement_ligne_compte_bancaire", compte.pk)
    for code, valeur in extra.items():
        set_parametre_portail(code, valeur)
    return mode, compte
