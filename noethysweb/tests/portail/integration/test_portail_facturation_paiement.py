"""`effectuer_paiement_en_ligne` (AJAX): every payment-system branch.

External gateways are never contacted: eopayment's request() only builds a form/URL
locally, and where a response is needed `Payment` is mocked.
"""

import datetime
import decimal
from unittest import mock

import pytest
from core.models import Paiement, PortailRenseignement, Reglement
from django.urls import reverse
from test_portail_facturation_support import (
    AJAX,
    configure_paiement_en_ligne,
    make_compte,
    make_cotisation,
    make_facture,
    make_periode,
    make_prestation,
    make_regie,
    make_reglement,
)
from tests.unit.factories import ActiviteFactory, FactureFactory

URL = "portail_ajax_effectuer_paiement_en_ligne"


def post(client, liste_impayes="", montant="50.00", echelonne=0, **extra):
    data = {
        "liste_impayes": liste_impayes,
        "montant_reglement": montant,
        "paiement_echelonne": echelonne,
    }
    data.update(extra)
    return client.post(reverse(URL), data, **AJAX)


def impaye(type_impaye, pk, solde="50.00"):
    return "%s##%d##%s" % (type_impaye, pk, solde)


@pytest.mark.django_db
class TestValidationMontant:
    def test_zero_amount_rejected(self, logged_client):
        response = post(logged_client, impaye("facture", 1), montant="0")
        assert response.status_code == 401
        assert "supérieur à zéro" in response.json()["erreur"]

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:132 `parametres_portail.paiement_ligne_montant_minimal` -- "
        "Get_dict_parametres() returns a dict so attribute access raises AttributeError (500 instead of the 401 JSON error). "
        "Fix: parametres_portail.get('paiement_ligne_montant_minimal').",
        strict=True,
    )
    def test_amount_below_minimum_rejected(self, logged_client):
        response = post(logged_client, impaye("facture", 1), montant="0.50")
        assert response.status_code == 401
        assert "montant minimal" in response.json()["erreur"]

    def test_amount_at_minimum_is_not_rejected(
        self, logged_client, set_parametre_portail
    ):
        set_parametre_portail("paiement_ligne_systeme", "demo")
        response = post(logged_client, impaye("facture", 1), montant="1.00")
        assert response.status_code == 200


@pytest.mark.django_db
class TestMauvaisesEntrees:
    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:114-116 missing POST fields (liste_impayes / montant_reglement / "
        "paiement_echelonne) raise AttributeError/TypeError -> 500 instead of a 400 JSON error.",
        strict=True,
    )
    def test_missing_fields_is_client_error(self, logged_client):
        response = logged_client.post(reverse(URL), {}, **AJAX)
        assert 400 <= response.status_code < 500

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:137 malformed `liste_impayes` entry (unpack of split('##')) "
        "or unknown type raises ValueError/KeyError -> 500 instead of a 400 JSON error.",
        strict=True,
    )
    @pytest.mark.parametrize("liste", ["", "n'importe quoi", "autre##1##5.00"])
    def test_malformed_liste_impayes_is_client_error(
        self, logged_client, set_parametre_portail, liste
    ):
        set_parametre_portail("paiement_ligne_systeme", "demo")
        response = post(logged_client, liste)
        assert 400 <= response.status_code < 500

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:304 -- no payment system configured (or unknown) falls off the end "
        "of effectuer_paiement_en_ligne, returning None -> 500 instead of a JSON error.",
        strict=True,
    )
    @pytest.mark.parametrize("systeme", [None, "inconnu"])
    def test_no_system_configured_returns_json_error(
        self, logged_client, set_parametre_portail, systeme
    ):
        if systeme:
            set_parametre_portail("paiement_ligne_systeme", systeme)
        response = post(logged_client, impaye("facture", 1))
        assert 400 <= response.status_code < 500


@pytest.mark.django_db
class TestDemo:
    def test_demo_mode_makes_no_payment(self, logged_client, set_parametre_portail):
        set_parametre_portail("paiement_ligne_systeme", "demo")
        response = post(
            logged_client,
            impaye("facture", 1)
            + ","
            + impaye("periode", 2)
            + ","
            + impaye("cotisation", 3),
        )
        assert response.status_code == 200
        assert response.json()["systeme_paiement"] == "demo"
        assert "démo" in response.json()["texte"]
        assert Paiement.objects.count() == 0


@pytest.mark.django_db
class TestPayfip:
    @pytest.fixture(autouse=True)
    def _setup(self, set_parametre_portail, famille_user):
        self.famille = famille_user[1]
        self.famille.mail = "famille@example.org"
        self.famille.save()
        self.set = set_parametre_portail
        set_parametre_portail("paiement_ligne_systeme", "payfip")
        self.regie = make_regie(make_compte())

    def test_several_invoices_refused(self, logged_client):
        f1, _ = make_facture(self.famille, 10, regie=self.regie)
        f2, _ = make_facture(self.famille, 10, regie=self.regie)
        response = post(
            logged_client,
            impaye("facture", f1.pk) + "," + impaye("facture", f2.pk),
            montant="20.00",
        )
        assert response.status_code == 401
        assert "multi-factures" in response.json()["erreur"]
        assert Paiement.objects.count() == 0

    def test_prefacturation_periode_refused(self, logged_client):
        facture, _ = make_facture(self.famille, 10, regie=self.regie)
        periode = make_periode(ActiviteFactory())
        response = post(
            logged_client,
            impaye("facture", facture.pk) + "," + impaye("periode", periode.pk),
        )
        assert response.status_code == 401
        assert "prefacturation" in response.json()["erreur"]

    def test_facture_without_regie_refused(self, logged_client):
        facture, _ = make_facture(self.famille, 10)
        response = post(logged_client, impaye("facture", facture.pk))
        assert response.status_code == 401
        assert "régie" in response.json()["erreur"]
        assert Paiement.objects.count() == 0

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:180 `liste_factures[0]` with no facture in the payment "
        "(e.g. cotisation only) raises IndexError -> 500 instead of a JSON error.",
        strict=True,
    )
    def test_cotisation_only_is_client_error(self, logged_client):
        prestation = make_cotisation(self.famille, 30)
        response = post(
            logged_client, impaye("cotisation", prestation.pk, "30.00"), montant="30.00"
        )
        assert 400 <= response.status_code < 500

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:192 (and :223 for payzen) a famille without e-mail address sends "
        "email=None to eopayment, which raises ValueError('MEL is not a valid email') -> 500 instead of a clean error.",
        strict=True,
    )
    def test_family_without_email_is_handled(self, logged_client):
        self.famille.mail = None
        self.famille.save()
        facture, _ = make_facture(self.famille, 80, regie=self.regie)
        response = post(
            logged_client, impaye("facture", facture.pk, "80.00"), montant="80.00"
        )
        assert response.status_code == 200

    @pytest.mark.parametrize(
        "mode, saisie", [("test", "T"), ("validation", "X"), ("production", "A")]
    )
    def test_success_creates_pending_paiement_and_redirect_url(
        self, logged_client, mode, saisie
    ):
        self.set("payfip_mode", mode)
        facture, _ = make_facture(self.famille, 80, regie=self.regie, numero=42)
        response = post(
            logged_client, impaye("facture", facture.pk, "80.00"), montant="80.00"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["systeme_paiement"] == "payfip"
        assert data["urltoredirect"].startswith(
            "https://www.payfip.gouv.fr/tpa/paiement.web?numcli=123456"
        )
        assert "refdet=000042" in data["urltoredirect"]
        assert "montant=8000" in data["urltoredirect"]
        assert f"saisie={saisie}" in data["urltoredirect"]
        paiement = Paiement.objects.get()
        assert paiement.systeme_paiement == "payfip"
        assert paiement.famille == self.famille
        assert paiement.refdet == "42"
        assert paiement.montant == decimal.Decimal("80.00")
        assert paiement.saisie == saisie
        assert paiement.resultat is None
        assert paiement.ventilation == "F%d#80.00" % facture.pk
        assert paiement.objet == "Paiement Regie Education"  # accents removed
        assert paiement.idtransaction

    def test_payment_object_built_with_regie_client_number(self, logged_client):
        facture, _ = make_facture(self.famille, 80, regie=self.regie)
        with mock.patch("portail.views.facturation.Payment") as payment_cls:
            payment_cls.return_value.request.return_value = (
                "TXN",
                1,
                "https://pay.example/redirect",
            )
            response = post(
                logged_client, impaye("facture", facture.pk, "80.00"), montant="80.00"
            )
        assert response.json()["urltoredirect"] == "https://pay.example/redirect"
        args = payment_cls.call_args[0]
        assert args[0] == "tipi"
        assert args[1]["numcli"] == "123456"
        assert args[1]["automatic_return_url"].endswith(reverse("retour_payfip"))
        assert Paiement.objects.get().idtransaction == "TXN"


@pytest.mark.django_db
class TestPayzen:
    @pytest.fixture(autouse=True)
    def _setup(self, set_parametre_portail, famille_user):
        self.famille = famille_user[1]
        self.famille.mail = "famille@example.org"
        self.famille.save()
        set_parametre_portail("paiement_ligne_systeme", "payzen")
        set_parametre_portail("payzen_site_id", "12345678")
        set_parametre_portail("payzen_certificat_test", "secret")
        set_parametre_portail("payzen_mode", "TEST")

    def _post(self, client, montant="50.00", echelonne=0, liste=None):
        return post(
            client,
            liste
            or (
                impaye("facture", 7)
                + ","
                + impaye("periode", 8)
                + ","
                + impaye("cotisation", 9)
            ),
            montant=montant,
            echelonne=echelonne,
        )

    def test_single_payment_returns_form_and_creates_paiement(self, logged_client):
        response = self._post(logged_client)
        assert response.status_code == 200
        data = response.json()
        assert data["systeme_paiement"] == "payzen"
        assert "<form id='form_paiement' " in data["form_paiement"]
        assert "SINGLE" in data["form_paiement"]
        assert "vads_amount" in data["form_paiement"]
        paiement = Paiement.objects.get()
        assert paiement.systeme_paiement == "payzen"
        assert paiement.famille == self.famille
        assert paiement.montant == decimal.Decimal("50.00")
        assert paiement.saisie == "TEST"
        assert paiement.resultat is None
        assert paiement.ventilation == "F7#50.00,P8#50.00,C9#50.00"
        assert paiement.idtransaction

    def test_return_urls_given_to_payzen(self, logged_client):
        with mock.patch("portail.views.facturation.Payment") as payment_cls:
            payment_cls.return_value.request.return_value = (
                "TX",
                1,
                "<form action='x'></form>",
            )
            self._post(logged_client)
        name, config = payment_cls.call_args[0]
        assert name == "payzen"
        assert config["vads_site_id"] == "12345678"
        assert config["vads_ctx_mode"] == "TEST"
        assert config["secret_test"] == "secret"
        assert config["vads_url_return"].endswith(reverse("portail_facturation"))
        for key, route in [
            ("cancel", "retour_payzen_cancel"),
            ("error", "retour_payzen_error"),
            ("refused", "retour_payzen_refused"),
            ("success", "retour_payzen_success"),
        ]:
            assert config[f"vads_url_{key}"].endswith(reverse(route))
        assert config["vads_contrib"] == "noethys"

    def test_installments_below_minimum_refused(self, logged_client):
        response = self._post(logged_client, montant="29.99", echelonne=1)
        assert response.status_code == 401
        assert "plusieurs fois" in response.json()["erreur"]
        assert Paiement.objects.count() == 0

    def test_installments_build_multi_ext_config(self, logged_client):
        with mock.patch("portail.views.facturation.Payment") as payment_cls:
            payment_cls.return_value.request.return_value = ("TX", 1, "<form></form>")
            response = self._post(logged_client, montant="90.00", echelonne=1)
            assert response.status_code == 200
            kwargs = payment_cls.return_value.request.call_args[1]
        today = datetime.date.today()
        config = kwargs["vads_payment_config"]
        assert config.startswith("MULTI_EXT:{}=3000;".format(today.strftime("%Y%m%d")))
        assert (
            "{}=3000".format((today + datetime.timedelta(days=30)).strftime("%Y%m%d"))
            in config
        )
        assert (
            "{}=3000".format((today + datetime.timedelta(days=60)).strftime("%Y%m%d"))
            in config
        )
        assert config.count(";") == 2

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:220 builds vads_payment_config='MULTI_EXT:...' but the installed "
        "eopayment (payzen/systempayv2 backend) only accepts 'SINGLE' or 'MULTI' -> ValueError, so "
        "'paiement en plusieurs fois' always 500s once the gateway library is really called.",
        strict=True,
    )
    def test_installments_work_with_real_eopayment(self, logged_client):
        response = self._post(logged_client, montant="30.00", echelonne=1)
        assert response.status_code == 200
        assert "MULTI_EXT" in response.json()["form_paiement"]

    def test_windows_platform_uses_temp_directory(self, logged_client):
        with (
            mock.patch("portail.views.facturation.sys") as fake_sys,
            mock.patch(
                "portail.views.facturation.utils_fichiers.GetTempRep",
                return_value="C:/tmp",
            ) as rep,
            mock.patch("portail.views.facturation.Payment") as payment_cls,
        ):
            fake_sys.platform = "win32"
            payment_cls.return_value.request.return_value = ("TX", 1, "<form></form>")
            response = self._post(logged_client)
        assert response.status_code == 200
        rep.assert_called_once()
        assert payment_cls.return_value.backend.PATH == "C:/tmp"


@pytest.mark.django_db
class TestPayasso:
    @pytest.fixture(autouse=True)
    def _setup(self, set_parametre_portail, famille_user):
        self.famille = famille_user[1]
        self.mode, self.compte = configure_paiement_en_ligne(
            set_parametre_portail, "payasso"
        )

    def _facture(
        self, pay="https://payasso.example/pay/abc", activites=None, montant=50
    ):
        activite = ActiviteFactory(pay=pay)
        facture, prestation = make_facture(
            self.famille,
            montant,
            activite=activite,
            activites=str(activite.pk) if activites is None else activites,
        )
        return facture, prestation, activite

    def test_several_invoices_refused(self, logged_client):
        f1, _, _ = self._facture()
        f2, _, _ = self._facture()
        response = post(
            logged_client, impaye("facture", f1.pk) + "," + impaye("facture", f2.pk)
        )
        assert response.status_code == 401
        assert "multi-factures" in response.json()["erreur"]

    def test_multi_activity_invoice_refused(self, logged_client):
        facture, _, _ = self._facture(activites="1;2")
        response = post(logged_client, impaye("facture", facture.pk))
        assert response.status_code == 401
        assert "PayAsso" in response.json()["erreur"]
        assert Paiement.objects.count() == 0

    @pytest.mark.parametrize("pay", [None, ""])
    def test_activity_without_payment_url_refused(self, logged_client, pay):
        facture, _, _ = self._facture(pay=pay)
        response = post(logged_client, impaye("facture", facture.pk))
        assert response.status_code == 401
        assert "PayAsso" in response.json()["erreur"]
        assert Paiement.objects.count() == 0

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:277 `';' in activite_ids[0]` with Facture.activites NULL "
        "raises TypeError -> 500 instead of the 401 'ne peut être payée via PayAsso' error.",
        strict=True,
    )
    def test_invoice_without_activities_refused_cleanly(self, logged_client):
        facture, _ = make_facture(self.famille, 50)
        response = post(logged_client, impaye("facture", facture.pk))
        assert response.status_code == 401

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:257 `Facture.objects.get(pk=factureid)` -- a payasso payment for a "
        "periode/cotisation only (no facture) uses that periode/cotisation ID as a facture ID -> DoesNotExist 500.",
        strict=True,
    )
    def test_periode_only_payment_refused_cleanly(self, logged_client):
        periode = make_periode(ActiviteFactory(pay="https://x"))
        response = post(logged_client, impaye("periode", periode.pk))
        assert 400 <= response.status_code < 500

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:363 (and :570 in Enregistrement_reglement) Reglement.objects.create() "
        "without the mandatory `modelimp` -> IntegrityError 'NOT NULL constraint failed: reglements.modelimp_id'. "
        "No online payment can ever be recorded as a règlement. Fix: pass modelimp=<ModeleImpression> (e.g. a portail parameter / default).",
        strict=True,
    )
    def test_success_records_payment_reglement_and_ventilation(self, logged_client):
        facture, _prestation, _ = self._facture(montant=50)
        response = post(
            logged_client, impaye("facture", facture.pk, "50.00"), montant="50.00"
        )
        assert response.status_code == 200
        data = response.json()
        assert data == {
            "systeme_paiement": "payasso",
            "urlpayasso": "https://payasso.example/pay/abc",
        }
        paiement = Paiement.objects.get()
        assert paiement.systeme_paiement == "payasso"
        assert paiement.resultat == "PAID"
        assert paiement.idtransaction.startswith("PAYASSO")
        assert paiement.refdet == str(facture.pk)
        reglement = Reglement.objects.get()
        assert reglement.montant == 50
        assert reglement.mode == self.mode
        assert reglement.compte == self.compte
        assert list(paiement.reglements.all()) == [reglement]
        assert reglement.ventilation_set.get().montant == 50
        facture.refresh_from_db()
        assert facture.solde_actuel == 0
        assert (
            PortailRenseignement.objects.filter(
                famille=self.famille, code="Nouveau paiement en ligne"
            ).count()
            == 1
        )


@pytest.mark.django_db
class TestPayassoAfterReglementCreation:
    """Same payasso flow with the `modelimp` bug worked around, to cover the recording code."""

    @pytest.fixture(autouse=True)
    def _setup(
        self, set_parametre_portail, famille_user, reglement_modelimp_workaround
    ):
        self.famille = famille_user[1]
        self.mode, self.compte = configure_paiement_en_ligne(
            set_parametre_portail, "payasso"
        )

    def _facture(self, montant=50):
        activite = ActiviteFactory(pay="https://payasso.example/pay/abc")
        facture, prestation = make_facture(
            self.famille, montant, activite=activite, activites=str(activite.pk)
        )
        return facture, prestation, activite

    def test_success_records_payment_reglement_and_ventilation(self, logged_client):
        facture, _prestation, _ = self._facture(montant=50)
        response = post(
            logged_client, impaye("facture", facture.pk, "50.00"), montant="50.00"
        )
        assert response.status_code == 200
        assert response.json() == {
            "systeme_paiement": "payasso",
            "urlpayasso": "https://payasso.example/pay/abc",
        }
        paiement = Paiement.objects.get()
        assert paiement.systeme_paiement == "payasso"
        assert paiement.resultat == "PAID"
        assert paiement.idtransaction.startswith("PAYASSO")
        assert paiement.refdet == str(facture.pk)
        reglement = Reglement.objects.get()
        assert reglement.montant == 50
        assert reglement.mode == self.mode
        assert reglement.compte == self.compte
        assert reglement.payeur.nom == self.famille.nom
        assert list(paiement.reglements.all()) == [reglement]
        assert reglement.ventilation_set.get().montant == 50
        facture.refresh_from_db()
        assert facture.solde_actuel == 0
        assert (
            PortailRenseignement.objects.filter(
                famille=self.famille, code="Nouveau paiement en ligne"
            ).count()
            == 1
        )

    def test_partial_payment_reuses_previous_payeur(self, logged_client):
        facture, _prestation, _ = self._facture(montant=50)
        previous = make_reglement(self.famille, 1)
        response = post(
            logged_client, impaye("facture", facture.pk, "20.00"), montant="20.00"
        )
        assert response.status_code == 200
        reglement = Reglement.objects.exclude(pk=previous.pk).get()
        assert reglement.payeur == previous.payeur
        assert reglement.ventilation_set.get().montant == 20
        facture.refresh_from_db()
        assert facture.solde_actuel == 30

    def test_pk_collision_with_cotisation_and_periode_ventilated_too(
        self, logged_client
    ):
        """The payasso code uses the *last* impayé ID as the facture ID; with a cotisation whose
        prestation ID matches the facture ID the periode/cotisation conditions are exercised."""
        cotisation = make_cotisation(self.famille, 30)
        activite = ActiviteFactory(pay="https://payasso.example/pay/abc")
        facture = FactureFactory(
            pk=cotisation.pk,
            famille=self.famille,
            total=40,
            solde_actuel=40,
            activites=str(activite.pk),
        )
        make_prestation(self.famille, activite, 40, facture=facture)
        periode = make_periode(activite)
        liste = ",".join(
            [
                impaye("facture", facture.pk, "40.00"),
                impaye("periode", periode.pk, "0.00"),
                impaye("cotisation", cotisation.pk, "30.00"),
            ]
        )
        response = post(logged_client, liste, montant="70.00")
        assert response.status_code == 200
        reglement = Reglement.objects.get()
        assert sum(v.montant for v in reglement.ventilation_set.all()) == 70
