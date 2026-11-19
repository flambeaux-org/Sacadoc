"""Gateway callbacks and recording: `retour_payfip`, `ipn_payzen`, `Enregistrement_reglement`.

`eopayment.Payment` is mocked wherever a gateway *response* has to be parsed; nothing
touches the network.
"""

import datetime
from types import SimpleNamespace
from unittest import mock

import pytest
from core.models import Payeur, PortailRenseignement, Reglement
from django.test import Client
from django.urls import reverse
from portail.views import facturation
from test_portail_facturation_support import (
    configure_paiement_en_ligne,
    make_compte,
    make_cotisation,
    make_facture,
    make_paiement,
    make_periode,
    make_prestation,
    make_regie,
    make_reglement,
    ventiler,
)
from tests.unit.factories import ActiviteFactory

TODAY = datetime.date.today()


def gateway_response(
    result=3, transaction_id="TX1", bank_status="00", signed=True, order_id=None
):
    return SimpleNamespace(
        result=result,
        transaction_id=transaction_id,
        bank_status=bank_status,
        signed=signed,
        order_id=order_id or transaction_id,
    )


# --------------------------------------------------------------------------- retour_payfip


@pytest.mark.django_db
class TestRetourPayfip:
    url = "retour_payfip"

    @pytest.fixture(autouse=True)
    def _setup(
        self, famille_user, set_parametre_portail, reglement_modelimp_workaround
    ):
        self.famille = famille_user[1]
        self.compte = make_compte()
        self.regie = make_regie(self.compte)
        self.mode, _ = configure_paiement_en_ligne(set_parametre_portail, "payfip")
        self.facture, self.prestation = make_facture(
            self.famille, 100, regie=self.regie
        )

    def _paiement(self, **kwargs):
        kwargs.setdefault("ventilation", "F%d#100.00" % self.facture.pk)
        return make_paiement(self.famille, "payfip", montant=100, **kwargs)

    def _post(self, response=None, data=None, client=None):
        client = client or Client()  # gateway callback: no session
        with mock.patch("portail.views.facturation.Payment") as payment_cls:
            payment_cls.return_value.response.return_value = (
                response or gateway_response()
            )
            result = client.post(
                reverse(self.url),
                data
                or {
                    "resultrans": "P",
                    "numauto": "A1",
                    "dattrans": "01012024",
                    "heurtrans": "1200",
                },
            )
        return result, payment_cls

    def test_get_not_allowed(self, client):
        assert client.get(reverse(self.url)).status_code == 405

    def test_paid_updates_paiement_and_records_reglement(self):
        paiement = self._paiement()
        response, payment_cls = self._post()
        assert response.status_code == 200
        assert response.content == b"Notification processed"
        assert payment_cls.call_args[0][0] == "tipi"
        paiement.refresh_from_db()
        assert paiement.resultat == "PAID"
        assert (
            paiement.resultrans,
            paiement.numauto,
            paiement.dattrans,
            paiement.heurtrans,
        ) == ("P", "A1", "01012024", "1200")
        assert paiement.message == "00"
        reglement = paiement.reglements.get()
        assert reglement.montant == 100
        assert reglement.compte == self.compte  # the régie's account
        self.facture.refresh_from_db()
        assert self.facture.solde_actuel == 0

    def test_csrf_exempt_for_gateway_post(self):
        self._paiement()
        response, _ = self._post(client=Client(enforce_csrf_checks=True))
        assert response.status_code == 200

    @pytest.mark.parametrize(
        "code, etat",
        [
            (4, "DENIED"),
            (5, "CANCELLED"),
            (6, "WAITING"),
            (99, "ERROR"),
            (1, "RECEIVED"),
            (2, "ACCEPTED"),
        ],
    )
    def test_non_paid_results_only_update_paiement(self, code, etat):
        paiement = self._paiement()
        response, _ = self._post(gateway_response(result=code, bank_status="KO"))
        assert response.status_code == 200
        paiement.refresh_from_db()
        assert paiement.resultat == etat
        assert paiement.message == "KO"
        assert paiement.reglements.count() == 0
        assert Reglement.objects.count() == 0

    def test_defaults_when_optional_fields_missing(self):
        paiement = self._paiement()
        response, _ = self._post(data={"x": "y"})
        assert response.status_code == 200
        paiement.refresh_from_db()
        assert paiement.numauto == "0"

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:431 retour_payfip does a bare `return` (None) when the pre-recorded "
        "paiement is not found -> Django 500 ('didn't return an HttpResponse'); should answer 404/200.",
        strict=True,
    )
    def test_unknown_transaction_returns_http_response(self):
        response, _ = self._post(gateway_response(transaction_id="UNKNOWN"))
        assert response.status_code in (200, 404)

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:439 retour_payfip does a bare `return` (None) when the paiement is "
        "already PAID (gateway retries) -> Django 500; should answer 200.",
        strict=True,
    )
    def test_already_paid_returns_http_response_and_is_idempotent(self):
        self._paiement(resultat="PAID")
        response, _ = self._post()
        assert response.status_code == 200

    def test_already_paid_does_not_create_second_reglement(self):
        paiement = self._paiement(resultat="PAID", message="orig")
        with pytest.raises(ValueError):  # the view returns None (see xfail above)
            self._post(client=Client(raise_request_exception=True))
        paiement.refresh_from_db()
        assert paiement.message == "orig"
        assert Reglement.objects.count() == 0

    def test_unknown_unexpected_result_code_keyerror(self):
        """ETATS_PAIEMENTS only knows 1-6 and 99."""
        self._paiement()
        with pytest.raises(KeyError):
            self._post(gateway_response(result=42))


# --------------------------------------------------------------------------- ipn_payzen


@pytest.mark.django_db
class TestIpnPayzen:
    url = "ipn_payzen"

    @pytest.fixture(autouse=True)
    def _setup(
        self, famille_user, set_parametre_portail, reglement_modelimp_workaround
    ):
        self.famille = famille_user[1]
        self.mode, self.compte = configure_paiement_en_ligne(
            set_parametre_portail, "payzen"
        )
        self.facture, self.prestation = make_facture(self.famille, 60)

    def _paiement(self, **kwargs):
        kwargs.setdefault("ventilation", "F%d#60.00" % self.facture.pk)
        kwargs.setdefault("idtransaction", "TX1")
        return make_paiement(self.famille, "payzen", montant=60, **kwargs)

    def _post(self, response=None, data=None, client=None):
        client = client or Client()
        with mock.patch("portail.views.facturation.Payment") as payment_cls:
            payment_cls.return_value.response.return_value = (
                response or gateway_response(order_id="TX1")
            )
            result = client.post(
                reverse(self.url),
                data if data is not None else {"vads_payment_config": "SINGLE"},
            )
        return result, payment_cls

    def test_get_not_allowed(self, client):
        assert client.get(reverse(self.url)).status_code == 405

    def test_paid_single_records_reglement(self):
        paiement = self._paiement()
        response, payment_cls = self._post()
        assert response.status_code == 200
        assert response.content == b"Notification processed"
        assert payment_cls.call_args[0][0] == "payzen"
        paiement.refresh_from_db()
        assert paiement.resultat == "PAID"
        assert paiement.message == "00"
        reglement = paiement.reglements.get()
        assert reglement.montant == 60
        assert reglement.numero_piece == "TX1"
        assert reglement.compte == self.compte
        assert reglement.mode == self.mode
        assert reglement.ventilation_set.get().prestation == self.prestation
        self.facture.refresh_from_db()
        assert self.facture.solde_actuel == 0

    def test_csrf_exempt(self):
        self._paiement()
        response, _ = self._post(client=Client(enforce_csrf_checks=True))
        assert response.status_code == 200

    def test_signature_error_is_logged_but_processing_continues(self, caplog):
        paiement = self._paiement()
        with caplog.at_level("DEBUG", logger="portail.views.facturation"):
            response, _ = self._post(gateway_response(order_id="TX1", signed=False))
        assert response.status_code == 200
        assert any("erreur de signature" in r.getMessage() for r in caplog.records)
        paiement.refresh_from_db()
        assert paiement.resultat == "PAID"

    @pytest.mark.parametrize(
        "code, etat", [(4, "DENIED"), (5, "CANCELLED"), (6, "WAITING")]
    )
    def test_non_paid_results(self, code, etat):
        paiement = self._paiement()
        response, _ = self._post(
            gateway_response(result=code, order_id="TX1", bank_status="KO")
        )
        assert response.status_code == 200
        paiement.refresh_from_db()
        assert paiement.resultat == etat
        assert paiement.message == "KO"
        assert Reglement.objects.count() == 0

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:482-483 `data.get('vads_card_brand', 0, type=str)` -- Django's QueryDict.get() "
        "has no `type` argument (Flask idiom) -> TypeError (500) whenever Payzen reports result ERROR; the 'MULTI paid "
        "in installments' promotion to PAID can never run. Fix: data.get('vads_card_brand', '').",
        strict=True,
    )
    def test_error_result_stays_error(self):
        paiement = self._paiement()
        self._post(
            gateway_response(result=99, order_id="TX1"),
            data={
                "vads_payment_config": "SINGLE",
                "vads_card_brand": "VISA",
                "vads_result": "05",
            },
        )
        paiement.refresh_from_db()
        assert paiement.resultat == "ERROR"
        assert Reglement.objects.count() == 0

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:482-483 `data.get('vads_card_brand', 0, type=str)` -- Django's QueryDict.get() "
        "has no `type` argument (Flask idiom) -> TypeError (500) whenever Payzen reports result ERROR; the 'MULTI paid "
        "in installments' promotion to PAID can never run. Fix: data.get('vads_card_brand', '').",
        strict=True,
    )
    def test_error_result_unsigned_multi_stays_error(self):
        paiement = self._paiement()
        self._post(
            gateway_response(result=99, order_id="TX1", signed=False),
            data={"vads_card_brand": "MULTI", "vads_result": "00"},
        )
        paiement.refresh_from_db()
        assert paiement.resultat == "ERROR"

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:482-483 `data.get('vads_card_brand', 0, type=str)` -- Django's QueryDict.get() "
        "has no `type` argument (Flask idiom) -> TypeError (500) whenever Payzen reports result ERROR; the 'MULTI paid "
        "in installments' promotion to PAID can never run. Fix: data.get('vads_card_brand', '').",
        strict=True,
    )
    def test_error_result_signed_multi_ok_is_promoted_to_paid_with_installments(self):
        paiement = self._paiement()
        today = TODAY
        d2, d3 = (
            today + datetime.timedelta(days=30),
            today + datetime.timedelta(days=60),
        )
        config = "MULTI_EXT:{}=2000;{}=2000;{}=2000".format(
            today.strftime("%Y%m%d"),
            d2.strftime("%Y%m%d"),
            d3.strftime("%Y%m%d"),
        )
        response, _ = self._post(
            gateway_response(result=99, order_id="TX1"),
            data={
                "vads_card_brand": "MULTI",
                "vads_result": "00",
                "vads_payment_config": config,
            },
        )
        assert response.status_code == 200
        paiement.refresh_from_db()
        assert paiement.resultat == "PAID"
        reglements = paiement.reglements.order_by("pk")
        assert [r.montant for r in reglements] == [20, 20, 20]
        assert (
            "(1/3)" in reglements[0].observations
            and "(3/3)" in reglements[2].observations
        )

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:491 `Paiement.objects.get(idtransaction=...)` raises DoesNotExist "
        "for an unknown transaction (and MultipleObjectsReturned on duplicates) -> 500 on the IPN endpoint "
        "instead of a controlled 4xx/200 answer.",
        strict=True,
    )
    def test_unknown_transaction_is_handled(self):
        response, _ = self._post(gateway_response(order_id="NOPE"))
        assert response.status_code in (200, 400, 404)


# --------------------------------------------------------------------------- Enregistrement_reglement


@pytest.mark.django_db
class TestEnregistrementReglement:
    @pytest.fixture(autouse=True)
    def _setup(self, famille_user, set_parametre_portail):
        self.famille = famille_user[1]
        self.mode, self.compte = configure_paiement_en_ligne(
            set_parametre_portail, "payzen"
        )

    def _payzen(self, ventilation, montant, **kwargs):
        return make_paiement(
            self.famille, "payzen", ventilation=ventilation, montant=montant, **kwargs
        )

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:570 Reglement.objects.create() without the mandatory `modelimp` -> "
        "IntegrityError (NOT NULL constraint failed: reglements.modelimp_id): no online payment is ever recorded.",
        strict=True,
    )
    def test_records_reglement_without_workaround(self):
        facture, _ = make_facture(self.famille, 40)
        facturation.Enregistrement_reglement(
            paiement=self._payzen("F%d#40.00" % facture.pk, 40),
            vads_payment_config="SINGLE",
        )
        assert Reglement.objects.count() == 1

    def test_payzen_single_facture(self, reglement_modelimp_workaround):
        facture, _prestation = make_facture(self.famille, 40)
        paiement = self._payzen("F%d#40.00" % facture.pk, 40, idtransaction="SHOP_987")
        facturation.Enregistrement_reglement(
            paiement=paiement, vads_payment_config="SINGLE"
        )
        reglement = paiement.reglements.get()
        assert reglement.numero_piece == "987"  # part after "_"
        assert reglement.date == TODAY
        assert reglement.compte == self.compte
        assert reglement.mode == self.mode
        assert (
            reglement.observations
            == "Transaction n°987 sur payzen (IDpaiement %d)." % paiement.pk
        )
        assert reglement.ventilation_set.get().montant == 40
        facture.refresh_from_db()
        assert (facture.solde_actuel, facture.regle) == (0, 40)
        renseignement = PortailRenseignement.objects.get(famille=self.famille)
        assert renseignement.categorie == "famille_reglements"
        assert renseignement.idobjet == reglement.pk
        assert renseignement.validation_auto is True
        assert (
            "payzen" in renseignement.nouvelle_valeur
            and "40.00" in renseignement.nouvelle_valeur
        )

    def test_creates_payeur_for_first_payment(self, reglement_modelimp_workaround):
        facture, _ = make_facture(self.famille, 40)
        facturation.Enregistrement_reglement(
            paiement=self._payzen("F%d#40.00" % facture.pk, 40),
            vads_payment_config="SINGLE",
        )
        payeur = Payeur.objects.get(famille=self.famille)
        assert payeur.nom == self.famille.nom
        assert Reglement.objects.get().payeur == payeur

    def test_reuses_payeur_of_last_reglement(self, reglement_modelimp_workaround):
        previous = make_reglement(self.famille, 1)
        facture, _ = make_facture(self.famille, 40)
        facturation.Enregistrement_reglement(
            paiement=self._payzen("F%d#40.00" % facture.pk, 40),
            vads_payment_config="SINGLE",
        )
        assert Reglement.objects.exclude(pk=previous.pk).get().payeur == previous.payeur
        assert Payeur.objects.filter(famille=self.famille).count() == 1

    def test_periode_and_cotisation_are_ventilated(self, reglement_modelimp_workaround):
        activite = ActiviteFactory()
        periode = make_periode(activite)
        p_periode = make_prestation(self.famille, activite, 25)
        p_cotisation = make_cotisation(self.famille, 15)
        p_outside = make_prestation(
            self.famille, activite, 99, date=datetime.date(2024, 6, 1)
        )
        paiement = self._payzen(
            "P%d#25.00,C%d#15.00" % (periode.pk, p_cotisation.pk), 40
        )
        facturation.Enregistrement_reglement(
            paiement=paiement, vads_payment_config="SINGLE"
        )
        reglement = paiement.reglements.get()
        ventilated = {
            v.prestation_id: v.montant for v in reglement.ventilation_set.all()
        }
        assert ventilated == {p_periode.pk: 25, p_cotisation.pk: 15}
        assert p_outside.pk not in ventilated

    def test_oldest_prestation_first_and_existing_ventilation_deducted(
        self, reglement_modelimp_workaround
    ):
        facture, p1 = make_facture(self.famille, 30)
        p2 = make_prestation(
            self.famille,
            ActiviteFactory(),
            30,
            date=datetime.date(2024, 4, 1),
            facture=facture,
        )
        facture.total = 60
        facture.solde_actuel = 60
        facture.save()
        ventiler(make_reglement(self.famille, 10), p1, 10)  # p1 has 20 left
        paiement = self._payzen("F%d#50.00" % facture.pk, 25)
        facturation.Enregistrement_reglement(
            paiement=paiement, vads_payment_config="SINGLE"
        )
        ventilated = {
            v.prestation_id: v.montant
            for v in paiement.reglements.get().ventilation_set.all()
        }
        assert ventilated == {p1.pk: 20, p2.pk: 5}

    def test_overpayment_leaves_excess_unventilated(
        self, reglement_modelimp_workaround
    ):
        facture, _ = make_facture(self.famille, 10)
        paiement = self._payzen("F%d#10.00" % facture.pk, 50)
        facturation.Enregistrement_reglement(
            paiement=paiement, vads_payment_config="SINGLE"
        )
        reglement = paiement.reglements.get()
        assert reglement.montant == 50
        assert sum(v.montant for v in reglement.ventilation_set.all()) == 10

    def test_other_family_prestations_never_ventilated(
        self, reglement_modelimp_workaround, other_famille
    ):
        _u, autre, _r = other_famille
        facture_autre, _p_autre = make_facture(autre, 40)
        paiement = self._payzen("F%d#40.00" % facture_autre.pk, 40)
        facturation.Enregistrement_reglement(
            paiement=paiement, vads_payment_config="SINGLE"
        )
        assert paiement.reglements.get().ventilation_set.count() == 0

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:535,585-591 installment amounts are floats (float(montant)/100) while "
        "prestation.solde is a Decimal -> `credit -= ventilation` raises TypeError (float - Decimal). "
        "Fix: decimal.Decimal(montant) / 100 in the MULTI parsing.",
        strict=True,
    )
    def test_payzen_multi_with_prestations_to_ventilate(
        self, reglement_modelimp_workaround
    ):
        facture, _ = make_facture(self.famille, 90)
        paiement = self._payzen("F%d#90.00" % facture.pk, 90)
        config = "MULTI_EXT:20240101>3000;20240131>3000;20240301>3000"
        facturation.Enregistrement_reglement(
            paiement=paiement, vads_payment_config=config
        )
        assert (
            sum(
                v.montant
                for r in paiement.reglements.all()
                for v in r.ventilation_set.all()
            )
            == 90
        )

    def test_payzen_multi_creates_one_reglement_per_installment(
        self, reglement_modelimp_workaround
    ):
        """Without prestation to ventilate (no float/Decimal mix) each installment becomes a reglement."""
        paiement = self._payzen("F99999#90.00", 90)
        config = "MULTI_EXT:20240101>3000;20240131>3000;20240301>3000"
        facturation.Enregistrement_reglement(
            paiement=paiement, vads_payment_config=config
        )
        reglements = list(paiement.reglements.order_by("pk"))
        assert [r.montant for r in reglements] == [30, 30, 30]
        assert (
            "Paiement en 3 fois du" in reglements[1].observations
            and "(2/3)" in reglements[1].observations
        )
        assert PortailRenseignement.objects.filter(famille=self.famille).count() == 3

    def test_payfip_uses_regie_bank_account(self, reglement_modelimp_workaround):
        compte_regie = make_compte("Compte régie")
        regie = make_regie(compte_regie)
        facture, _ = make_facture(self.famille, 40, regie=regie)
        paiement = make_paiement(
            self.famille, "payfip", "F%d#40.00" % facture.pk, montant=40
        )
        facturation.Enregistrement_reglement(paiement=paiement)
        reglement = paiement.reglements.get()
        assert reglement.compte == compte_regie
        assert reglement.numero_piece == ""
        assert reglement.observations.startswith("Transaction n°TX1 sur payfip")

    def test_ventilation_with_unknown_prefix_raises(self):
        """Ventilation is machine-written; an unknown prefix is not silently accepted."""
        paiement = self._payzen("X1#10.00", 10)
        with pytest.raises((UnboundLocalError, KeyError)):
            facturation.Enregistrement_reglement(
                paiement=paiement, vads_payment_config="SINGLE"
            )
