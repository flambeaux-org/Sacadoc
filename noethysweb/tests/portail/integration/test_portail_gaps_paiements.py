# ruff: noqa: F811, UP031, RUF059, RUF012
"""Gap-closing tests for portail payment code: paiement_retour (dead HelloAsso return view) and facturation.

No external gateway is ever contacted (eopayment's Payment is mocked).
"""

import datetime
from types import SimpleNamespace
from unittest import mock

import pytest
from core.models import Ventilation
from django.http import QueryDict
from django.test import Client
from django.urls import reverse
from portail.views import facturation
from portail.views import paiement_retour as pr
from test_portail_facturation_support import (
    AJAX,
    configure_paiement_en_ligne,
    make_facture,
    make_paiement,
    make_prestation,
)
from tests.unit.factories import ActiviteFactory

# ---------------------------------------------------------------------------
# views/paiement_retour.py (HelloAsso return page - not routed, see test_portail_paiements_retour.py)
# ---------------------------------------------------------------------------


class FakePaiementModel:
    """Stand-in for core.models.Paiement: the real model has none of helloasso_checkout_id / statut / STATUT_*
    (known bug documented in test_portail_paiements_retour.py), so the view's lookup can only be driven by a fake."""

    STATUT_SUCCES = "succes"
    STATUT_ECHEC = "echec"

    class DoesNotExist(Exception):
        pass

    found = None
    lookups = []

    class objects:
        @staticmethod
        def get(**kwargs):
            FakePaiementModel.lookups.append(kwargs)
            if FakePaiementModel.found is None:
                raise FakePaiementModel.DoesNotExist()
            return FakePaiementModel.found


@pytest.fixture
def fake_paiement(monkeypatch):
    FakePaiementModel.lookups = []
    FakePaiementModel.found = SimpleNamespace(
        statut=None, helloasso_order_id=None, save=mock.Mock()
    )
    monkeypatch.setattr(pr, "Paiement", FakePaiementModel)
    return FakePaiementModel.found


def call_retour(rf, user, **params):
    request = rf.get("/", params)
    request.user = user
    view = pr.View()
    view.request, view.args, view.kwargs = request, (), {}
    with mock.patch.object(pr, "messages") as messages:
        response = view.get(request)
    return response, messages


@pytest.mark.django_db
class TestPaiementRetourWithFakeModel:
    def test_unknown_checkout_redirects_to_error(self, rf, famille_user, monkeypatch):
        """paiement_retour.py:59-60"""
        FakePaiementModel.lookups = []
        FakePaiementModel.found = None
        monkeypatch.setattr(pr, "Paiement", FakePaiementModel)
        response, messages = call_retour(
            rf, famille_user[0], checkoutIntentId="nope", code="succeeded"
        )
        assert response.status_code == 302 and response.url == "/paiement/error/"
        messages.error.assert_called_once()
        assert "introuvable" in messages.error.call_args[0][1]
        assert FakePaiementModel.lookups == [{"helloasso_checkout_id": "nope"}]

    def test_succeeded_marks_paiement_as_success(self, rf, famille_user, fake_paiement):
        """paiement_retour.py:65-69"""
        response, messages = call_retour(
            rf, famille_user[0], checkoutIntentId="c1", code="succeeded", orderId="o9"
        )
        assert response.status_code == 302 and response.url == "/paiement/success/"
        assert fake_paiement.statut == FakePaiementModel.STATUT_SUCCES
        assert fake_paiement.helloasso_order_id == "o9"
        fake_paiement.save.assert_called_once()
        messages.success.assert_called_once()

    @pytest.mark.parametrize("code", ["failed", "canceled"])
    def test_failed_or_canceled_marks_paiement_as_failed(
        self, rf, famille_user, fake_paiement, code
    ):
        """paiement_retour.py:73-76"""
        response, messages = call_retour(
            rf, famille_user[0], checkoutIntentId="c1", code=code
        )
        assert response.status_code == 302 and response.url == "/paiement/error/"
        assert fake_paiement.statut == FakePaiementModel.STATUT_ECHEC
        fake_paiement.save.assert_called_once()
        messages.error.assert_called_once()

    def test_unknown_status_code_is_an_error_and_leaves_paiement_untouched(
        self, rf, famille_user, fake_paiement
    ):
        response, messages = call_retour(
            rf, famille_user[0], checkoutIntentId="c1", code="weird"
        )
        assert response.url == "/paiement/error/"
        assert fake_paiement.statut is None
        fake_paiement.save.assert_not_called()
        assert "inconnu" in messages.error.call_args[0][1]


# ---------------------------------------------------------------------------
# views/facturation.py
# ---------------------------------------------------------------------------


def gateway_response(
    result=99, transaction_id="TX1", bank_status="00", signed=True, order_id="TX1"
):
    return SimpleNamespace(
        result=result,
        transaction_id=transaction_id,
        bank_status=bank_status,
        signed=signed,
        order_id=order_id,
    )


@pytest.fixture
def querydict_get_accepts_type(monkeypatch):
    """Work around known bug (facturation.py:482-483 calls QueryDict.get(key, default, type=str), a Flask idiom
    Django does not support -> TypeError whenever Payzen reports ERROR; see test_portail_facturation_callbacks.py,
    where the same scenarios are xfail'd). The wrapper lets the code AFTER the call (the MULTI promotion) run."""
    original = QueryDict.get

    def get(self, key, default=None, type=None):
        value = original(self, key, default)
        return type(value) if type else value

    monkeypatch.setattr(QueryDict, "get", get)


@pytest.mark.django_db
class TestIpnPayzenMultiPromotion:
    """facturation.py:483-485 - result ERROR + signed + MULTI + vads_result 00 is promoted to PAID."""

    @pytest.fixture(autouse=True)
    def _setup(
        self,
        famille_user,
        set_parametre_portail,
        reglement_modelimp_workaround,
        querydict_get_accepts_type,
    ):
        self.famille = famille_user[1]
        configure_paiement_en_ligne(set_parametre_portail, "payzen")
        self.paiement = make_paiement(
            self.famille,
            "payzen",
            ventilation="F99999#90.00",
            montant=90,
            idtransaction="TX1",
        )

    def _post(self, response, data):
        with mock.patch("portail.views.facturation.Payment") as payment_cls:
            payment_cls.return_value.response.return_value = response
            return Client().post(reverse("ipn_payzen"), data)

    def test_signed_multi_ok_is_promoted_to_paid(self):
        today = datetime.date.today()
        d2 = today + datetime.timedelta(days=30)
        config = "MULTI_EXT:%s=3000;%s=6000" % (
            today.strftime("%Y%m%d"),
            d2.strftime("%Y%m%d"),
        )
        response = self._post(
            gateway_response(),
            {
                "vads_card_brand": "MULTI",
                "vads_result": "00",
                "vads_payment_config": config,
            },
        )
        assert response.status_code == 200
        self.paiement.refresh_from_db()
        assert self.paiement.resultat == "PAID"
        assert [r.montant for r in self.paiement.reglements.order_by("pk")] == [30, 60]

    @pytest.mark.parametrize(
        "signed, brand, vads_result",
        [(False, "MULTI", "00"), (True, "VISA", "00"), (True, "MULTI", "05")],
    )
    def test_not_promoted_when_a_condition_fails(self, signed, brand, vads_result):
        response = self._post(
            gateway_response(signed=signed),
            {"vads_card_brand": brand, "vads_result": vads_result},
        )
        assert response.status_code == 200
        self.paiement.refresh_from_db()
        assert self.paiement.resultat == "ERROR"
        assert self.paiement.reglements.count() == 0


@pytest.mark.django_db
class TestPartialPaymentLeavesLaterPrestationsUntouched:
    """facturation.py:380->379 (payasso flow) and :587->586 (Enregistrement_reglement): once the credit is used up
    (or a prestation is already settled) the ventilation loop skips the remaining prestations."""

    @pytest.fixture(autouse=True)
    def _setup(
        self, famille_user, set_parametre_portail, reglement_modelimp_workaround
    ):
        self.famille = famille_user[1]
        self.set_parametre_portail = set_parametre_portail

    def _facture_with_two_prestations(self, activite=None):
        facture, first = make_facture(
            self.famille,
            50,
            activite=activite,
            activites=str(activite.pk) if activite else None,
        )
        second = make_prestation(
            self.famille,
            first.activite,
            30,
            date=datetime.date(2024, 4, 1),
            facture=facture,
        )
        facture.total = facture.solde_actuel = 80
        facture.save()
        return facture, first, second

    def test_payasso_partial_payment_only_ventilates_first_prestation(
        self, logged_client
    ):
        configure_paiement_en_ligne(self.set_parametre_portail, "payasso")
        activite = ActiviteFactory(pay="https://payasso.example/pay/abc")
        facture, first, second = self._facture_with_two_prestations(activite)
        response = logged_client.post(
            reverse("portail_ajax_effectuer_paiement_en_ligne"),
            {
                "liste_impayes": "facture##%d##80.00" % facture.pk,
                "montant_reglement": "20.00",
                "paiement_echelonne": 0,
            },
            **AJAX,
        )
        assert response.status_code == 200
        ventilations = {
            v.prestation_id: v.montant
            for v in Ventilation.objects.filter(famille=self.famille)
        }
        assert ventilations == {first.pk: 20}
        assert second.pk not in ventilations

    def test_enregistrement_reglement_partial_payment_only_ventilates_first_prestation(
        self,
    ):
        configure_paiement_en_ligne(self.set_parametre_portail, "payzen")
        facture, first, second = self._facture_with_two_prestations()
        paiement = make_paiement(
            self.famille, "payzen", ventilation="F%d#80.00" % facture.pk, montant=20
        )
        facturation.Enregistrement_reglement(
            paiement=paiement, vads_payment_config="SINGLE"
        )
        ventilations = {
            v.prestation_id: v.montant
            for v in Ventilation.objects.filter(famille=self.famille)
        }
        assert ventilations == {first.pk: 20}

    def test_enregistrement_reglement_skips_already_settled_prestation(self):
        """Second branch of the same condition: `prestation.solde` is 0 for the first prestation."""
        configure_paiement_en_ligne(self.set_parametre_portail, "payzen")
        facture, first, second = self._facture_with_two_prestations()
        from test_portail_facturation_support import make_reglement, ventiler

        ventiler(make_reglement(self.famille, 50), first, 50)
        paiement = make_paiement(
            self.famille, "payzen", ventilation="F%d#30.00" % facture.pk, montant=30
        )
        facturation.Enregistrement_reglement(
            paiement=paiement, vads_payment_config="SINGLE"
        )
        new = Ventilation.objects.filter(famille=self.famille, prestation=second)
        assert [v.montant for v in new] == [30]
        assert Ventilation.objects.filter(prestation=first).count() == 1
