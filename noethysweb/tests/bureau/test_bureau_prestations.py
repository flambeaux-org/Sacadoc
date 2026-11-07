"""Prestations of the fiche famille and the family balance shown on the summary.

Business rules under test:
- the director can bill a manual prestation (label, activity, amount) to a member;
- a deduction entered with the prestation is stored against it and the family;
- the balance on the fiche famille = prestations of the director's activities
  minus what was paid on them (ventilations); other structures' prestations are ignored;
- a prestation already invoiced or paid must not be deletable (accounting safety; the
  same rule is enforced for prestations recomputed by inscriptions).
"""

import datetime
from decimal import Decimal

import pytest
from core.models import (
    CompteBancaire,
    Deduction,
    Facture,
    ModeleImpression,
    ModeReglement,
    Payeur,
    Prestation,
    Reglement,
    TypeDeduction,
    Ventilation,
)
from django.urls import reverse
from tests.bureau.conftest import build_form_data
from tests.unit.factories import ActiviteFactory, StructureFactory


def assert_redirect(response):
    if response.status_code == 200 and response.context and "form" in response.context:
        errors = response.context["form"].errors.as_json()
        formset = response.context.get("formset_combi")
        pytest.fail("Form invalide : %s %s" % (errors, formset.errors if formset else ""))
    assert response.status_code in (302, 303), response.status_code


def _post_prestation(client, famille, url=None, deductions=(), **overrides):
    url = url or reverse("famille_prestations_ajouter", args=[famille.pk])
    response = client.get(url)
    data = build_form_data(response.context["form"], famille=famille.pk, **overrides)
    formset = response.context["formset_combi"]
    prefix = formset.prefix
    data.update({
        "%s-TOTAL_FORMS" % prefix: len(deductions),
        "%s-INITIAL_FORMS" % prefix: 0,
        "%s-MIN_NUM_FORMS" % prefix: 0,
        "%s-MAX_NUM_FORMS" % prefix: 1000,
    })
    for i, (montant, type_deduction) in enumerate(deductions):
        data["%s-%d-montant" % (prefix, i)] = montant
        data["%s-%d-label" % (prefix, i)] = type_deduction.pk
    return client.post(url, data)


def _prestation(famille, activite, montant, individu=None, **kwargs):
    return Prestation.objects.create(famille=famille, activite=activite, individu=individu,
                                     date=datetime.date(2026, 3, 1), label="Prestation",
                                     montant_initial=montant, montant=montant, **kwargs)


def _regler(famille, prestation, montant):
    reglement = Reglement.objects.create(
        famille=famille, date=datetime.date(2026, 3, 2), montant=montant,
        mode=ModeReglement.objects.create(label="Chèque"),
        payeur=Payeur.objects.create(famille=famille, nom=famille.nom),
        compte=CompteBancaire.objects.create(nom="Compte courant"),
        modelimp=ModeleImpression.objects.create(categorie="reglement", nom="Reçu"),
    )
    return Ventilation.objects.create(famille=famille, reglement=reglement, prestation=prestation, montant=montant)


def _solde(client, famille):
    return client.get(reverse("famille_resume", args=[famille.pk])).context["solde"]


@pytest.mark.django_db
class TestSaisiePrestation:
    def test_ajouter_une_prestation_manuelle(self, directeur_client, famille_bureau, activite):
        famille, _t, enfant = famille_bureau
        response = _post_prestation(
            directeur_client, famille,
            date="2026-03-01", categorie="autre", individu=enfant.pk, activite=activite.pk,
            label="Sortie piscine", quantite=2, montant_unitaire="12.50",
            montant_initial="25.00", montant="25.00", tva=0,
        )
        assert_redirect(response)
        prestation = Prestation.objects.get(famille=famille, label="Sortie piscine")
        assert prestation.individu == enfant
        assert prestation.activite == activite
        assert prestation.montant == Decimal("25.00")
        assert _solde(directeur_client, famille) == Decimal("25.00")

    def test_activite_obligatoire(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        response = _post_prestation(
            directeur_client, famille,
            date="2026-03-01", categorie="autre", individu=enfant.pk, activite="",
            label="Sans activité", quantite=1, montant_unitaire="10", montant_initial="10", montant="10",
        )
        assert response.status_code == 200
        assert "activite" in response.context["form"].errors
        assert not Prestation.objects.filter(label="Sans activité").exists()

    def test_prestation_avec_deduction(self, directeur_client, famille_bureau, activite, structure):
        famille, _t, enfant = famille_bureau
        bon_caf = TypeDeduction.objects.create(nom="Bon CAF", structure=structure)
        response = _post_prestation(
            directeur_client, famille, deductions=[("5.00", bon_caf)],
            date="2026-03-01", categorie="autre", individu=enfant.pk, activite=activite.pk,
            label="Journée", quantite=1, montant_unitaire="20", montant_initial="20.00", montant="15.00",
        )
        assert_redirect(response)
        prestation = Prestation.objects.get(famille=famille, label="Journée")
        deduction = Deduction.objects.get(prestation=prestation)
        assert deduction.montant == Decimal("5.00")
        assert deduction.label == bon_caf
        assert deduction.famille == famille
        assert deduction.date == prestation.date
        assert not deduction.remb

    def test_types_de_deduction_proposes(self, directeur_client, famille_bureau, structure):
        """Only deductions of my structures, plus the standard ones (no structure), are offered."""
        famille, _t, _e = famille_bureau
        mien = TypeDeduction.objects.create(nom="Bon CAF", structure=structure)
        standard = TypeDeduction.objects.create(nom="Remise")
        autre = TypeDeduction.objects.create(nom="Bon mairie voisine", structure=StructureFactory())
        formset = directeur_client.get(
            reverse("famille_prestations_ajouter", args=[famille.pk])
        ).context["formset_combi"]
        queryset = list(formset.forms[0].fields["label"].queryset)
        assert mien in queryset and standard in queryset
        assert autre not in queryset

    def test_modifier_le_montant(self, directeur_client, famille_bureau, activite):
        famille, _t, enfant = famille_bureau
        prestation = _prestation(famille, activite, Decimal("30"), individu=enfant)
        url = reverse("famille_prestations_modifier", args=[famille.pk, prestation.pk])
        assert_redirect(_post_prestation(directeur_client, famille, url=url,
                                         montant_initial="40.00", montant="40.00",
                                         montant_unitaire="40", quantite=1))
        prestation.refresh_from_db()
        assert prestation.montant == Decimal("40.00")


@pytest.mark.django_db
class TestSoldeFamille:
    def test_solde_ne_compte_que_mes_activites(self, directeur_client, famille_bureau, activite):
        famille, _t, enfant = famille_bureau
        _prestation(famille, activite, Decimal("100"), individu=enfant)
        _prestation(famille, ActiviteFactory(structure=StructureFactory()), Decimal("999"), individu=enfant)
        assert _solde(directeur_client, famille) == Decimal("100")

    def test_reglement_partiel_diminue_le_solde(self, directeur_client, famille_bureau, activite):
        famille, _t, enfant = famille_bureau
        prestation = _prestation(famille, activite, Decimal("100"), individu=enfant)
        _regler(famille, prestation, Decimal("60"))
        response = directeur_client.get(reverse("famille_resume", args=[famille.pk]))
        assert response.context["solde"] == Decimal("40")
        assert response.context["solde_famille"] == Decimal("40")
        ligne = response.context["liste_prestations_solde"][0]
        assert ligne.montant_restant == Decimal("40")

    def test_famille_a_jour(self, directeur_client, famille_bureau, activite):
        famille, _t, enfant = famille_bureau
        prestation = _prestation(famille, activite, Decimal("80"), individu=enfant)
        _regler(famille, prestation, Decimal("80"))
        assert _solde(directeur_client, famille) == Decimal("0")

    def test_prestation_supprimee_sort_du_solde(self, directeur_client, famille_bureau, activite):
        famille, _t, enfant = famille_bureau
        prestation = _prestation(famille, activite, Decimal("50"), individu=enfant)
        assert_redirect(directeur_client.post(
            reverse("famille_prestations_supprimer", args=[famille.pk, prestation.pk])
        ))
        assert not Prestation.objects.filter(pk=prestation.pk).exists()
        assert _solde(directeur_client, famille) == Decimal("0")


@pytest.mark.django_db
class TestSuppressionProtegee:
    @pytest.mark.xfail(strict=True, reason=(
        "BUG: famille_prestations.Supprimer has no protection: deleting a paid prestation cascades "
        "to its Ventilation, silently detaching the payment (the family then shows a credit). "
        "Inscriptions explicitly refuse to delete ventilated prestations for this reason."
    ))
    def test_prestation_reglee_non_supprimable(self, directeur_client, famille_bureau, activite):
        famille, _t, enfant = famille_bureau
        prestation = _prestation(famille, activite, Decimal("50"), individu=enfant)
        ventilation = _regler(famille, prestation, Decimal("50"))
        directeur_client.post(reverse("famille_prestations_supprimer", args=[famille.pk, prestation.pk]))
        assert Prestation.objects.filter(pk=prestation.pk).exists()
        assert Ventilation.objects.filter(pk=ventilation.pk).exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: an invoiced prestation can be deleted from the fiche famille; the invoice keeps its "
        "total but loses the line. Inscriptions refuse any change once prestations are invoiced."
    ))
    def test_prestation_facturee_non_supprimable(self, directeur_client, famille_bureau, activite):
        famille, _t, enfant = famille_bureau
        facture = Facture.objects.create(famille=famille, numero=10, date_edition=datetime.date(2026, 3, 31),
                                         date_debut=datetime.date(2026, 3, 1), date_fin=datetime.date(2026, 3, 31),
                                         total=Decimal("50"), solde_actuel=Decimal("50"))
        prestation = _prestation(famille, activite, Decimal("50"), individu=enfant, facture=facture)
        directeur_client.post(reverse("famille_prestations_supprimer", args=[famille.pk, prestation.pk]))
        assert Prestation.objects.filter(pk=prestation.pk).exists()
