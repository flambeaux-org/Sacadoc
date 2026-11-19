"""Tests for portail/views/paiement_tpe.py (AJAX endpoint starting an online payment).

HelloAssoClient and stripe are always mocked: nothing here touches the network.
"""

import datetime
from types import SimpleNamespace
from unittest import mock

import pytest
from django.urls import reverse
from portail.views import paiement_tpe as tpe
from tests.unit.factories import ActiviteFactory

URL = "portail_ajax_paiement_tpe"
AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


# --------------------------------------------------------------------------- helpers
def _activite(plateforme):
    activite = ActiviteFactory()
    activite.pay_org_tpe = plateforme
    activite.save()
    return activite


def _prestation(famille, activite, montant=100):
    from core.models import Prestation

    return Prestation.objects.create(
        famille=famille,
        activite=activite,
        date=datetime.date(2026, 1, 1),
        label="Prestation",
        montant=montant,
        montant_initial=montant,
    )


def _post(client, prestation, montant, **extra):
    data = {
        "id_prestation": prestation.pk if hasattr(prestation, "pk") else prestation,
        "montant": montant,
    }
    return client.post(reverse(URL), data, **AJAX, **extra)


@pytest.fixture
def activite_stripe(db):
    return _activite("STRIPE")


@pytest.fixture
def prestation_stripe(famille_user, activite_stripe):
    return _prestation(famille_user[1], activite_stripe, 100)


@pytest.fixture
def stripe_compte(activite_stripe):
    from core.models import StripeCompte

    compte = StripeCompte.objects.create(
        nom="S", secret_key="sk_live_x", publishable_key="pk"
    )
    compte.activites.add(activite_stripe)
    return compte


@pytest.fixture
def ha_config(db):
    from core.models import HelloAssoConfig

    def _make(activite, actif=True):
        config = HelloAssoConfig.objects.create(
            client_id="cid", client_secret="sec", org_slug="asso", actif=actif
        )
        config.activites.add(activite)
        return config

    return _make


# --------------------------------------------------------------------------- authorization
@pytest.mark.django_db
class TestAuthorization:
    def test_anonymous_forbidden(self, client, organisateur):
        assert client.post(reverse(URL), {}, **AJAX).status_code == 403

    def test_staff_forbidden(self, client, staff_user, organisateur):
        client.force_login(staff_user)
        assert client.post(reverse(URL), {}, **AJAX).status_code == 403

    def test_non_ajax_rejected(self, logged_client):
        assert logged_client.post(reverse(URL), {}).status_code == 400

    def test_get_not_allowed(self, logged_client):
        assert logged_client.get(reverse(URL), **AJAX).status_code == 405

    def test_staff_cannot_start_stripe_checkout(
        self, client, staff_user, prestation_stripe, stripe_compte
    ):
        client.force_login(staff_user)
        with mock.patch.object(tpe.stripe.checkout.Session, "create") as create:
            _post(client, prestation_stripe, "10")
        create.assert_not_called()

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "BUG: paiement_tpe.py:~46 - the prestation is looked up by pk only: any logged-in family can "
            "open a Stripe/HelloAsso checkout for another family's prestation (IDOR). Expected 403/404."
        ),
    )
    def test_other_familles_prestation_is_refused(
        self, logged_client, other_famille, activite_stripe, stripe_compte
    ):
        prestation = _prestation(other_famille[1], activite_stripe, 100)
        with mock.patch.object(
            tpe.stripe.checkout.Session,
            "create",
            return_value=SimpleNamespace(url="https://s"),
        ):
            response = _post(logged_client, prestation, "10")
        assert response.status_code in (400, 403, 404)


# --------------------------------------------------------------------------- input validation
@pytest.mark.django_db
class TestValidation:
    def test_unknown_prestation(self, logged_client):
        response = logged_client.post(
            reverse(URL), {"id_prestation": "99999", "montant": "10"}, **AJAX
        )
        assert response.status_code == 400
        assert response.json() == {"success": False, "erreur": "Données invalides"}

    def test_missing_prestation(self, logged_client):
        response = logged_client.post(reverse(URL), {"montant": "10"}, **AJAX)
        assert response.status_code == 400

    def test_non_numeric_prestation_id(self, logged_client):
        response = logged_client.post(
            reverse(URL), {"id_prestation": "abc", "montant": "10"}, **AJAX
        )
        assert response.status_code == 400

    def test_non_numeric_montant(self, logged_client, prestation_stripe):
        response = _post(logged_client, prestation_stripe, "abc")
        assert response.status_code == 400
        assert response.json()["erreur"] == "Données invalides"

    def test_missing_montant(self, logged_client, prestation_stripe):
        response = logged_client.post(
            reverse(URL), {"id_prestation": prestation_stripe.pk}, **AJAX
        )
        assert response.status_code == 400

    def test_montant_below_minimum(self, logged_client, prestation_stripe):
        response = _post(logged_client, prestation_stripe, "0.49")
        assert response.status_code == 400
        assert "supérieur à 0,5" in response.json()["erreur"]

    def test_negative_montant(self, logged_client, prestation_stripe):
        assert _post(logged_client, prestation_stripe, "-5").status_code == 400

    def test_montant_above_remaining(
        self, logged_client, prestation_stripe, stripe_compte
    ):
        response = _post(logged_client, prestation_stripe, "100.01")
        assert response.status_code == 400
        assert "dépasse le montant total restant" in response.json()["erreur"]
        assert "100.00" in response.json()["erreur"]

    def test_comma_decimal_separator_accepted(
        self, logged_client, prestation_stripe, stripe_compte
    ):
        with mock.patch.object(
            tpe.stripe.checkout.Session,
            "create",
            return_value=SimpleNamespace(url="https://s"),
        ) as create:
            response = _post(logged_client, prestation_stripe, "12,50")
        assert response.status_code == 200
        assert (
            create.call_args.kwargs["line_items"][0]["price_data"]["unit_amount"]
            == 1250
        )

    def test_remaining_takes_existing_ventilations_into_account(
        self, logged_client, famille_user, prestation_stripe, stripe_compte
    ):
        from core.models import (
            CompteBancaire,
            ModeleImpression,
            ModeReglement,
            Payeur,
            Reglement,
            Ventilation,
        )

        _u, famille, _ = famille_user
        reglement = Reglement.objects.create(
            famille=famille,
            date=datetime.date(2026, 1, 2),
            montant=70,
            mode=ModeReglement.objects.create(label="CB"),
            payeur=Payeur.objects.create(famille=famille, nom="P"),
            compte=CompteBancaire.objects.create(nom="C"),
            modelimp=ModeleImpression.objects.create(
                categorie="reglement", nom="m", options="{}"
            ),
        )
        Ventilation.objects.create(
            famille=famille,
            reglement=reglement,
            prestation=prestation_stripe,
            montant=70,
        )
        too_much = _post(logged_client, prestation_stripe, "30.01")
        assert too_much.status_code == 400 and "30.00" in too_much.json()["erreur"]
        with mock.patch.object(
            tpe.stripe.checkout.Session,
            "create",
            return_value=SimpleNamespace(url="https://s"),
        ):
            assert _post(logged_client, prestation_stripe, "30").status_code == 200

    def test_remaining_covers_all_prestations_of_same_activity(
        self, logged_client, famille_user, prestation_stripe, stripe_compte
    ):
        _prestation(famille_user[1], prestation_stripe.activite, 50)
        with mock.patch.object(
            tpe.stripe.checkout.Session,
            "create",
            return_value=SimpleNamespace(url="https://s"),
        ):
            assert _post(logged_client, prestation_stripe, "150").status_code == 200
        assert _post(logged_client, prestation_stripe, "150.01").status_code == 400

    def test_other_activities_are_not_counted(
        self, logged_client, famille_user, prestation_stripe
    ):
        _prestation(famille_user[1], _activite("STRIPE"), 500)
        assert _post(logged_client, prestation_stripe, "100.01").status_code == 400

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "BUG: paiement_tpe.py:~49 - a prestation without activite makes `activite.pay_org_tpe` raise "
            "AttributeError (not in the except tuple) -> HTTP 500 instead of a 400 JSON error."
        ),
    )
    def test_prestation_without_activity_is_a_400(self, logged_client, famille_user):
        from core.models import Prestation

        prestation = Prestation.objects.create(
            famille=famille_user[1],
            date=datetime.date(2026, 1, 1),
            label="x",
            montant=10,
            montant_initial=10,
        )
        logged_client.raise_request_exception = False
        response = _post(logged_client, prestation, "5")
        assert response.status_code == 400

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "BUG: paiement_tpe.py:~100 - float('nan') passes both `<` and `>` bound checks (comparisons are "
            "False), so a NaN amount bypasses validation and crashes later (ValueError in int(nan*100)) -> 500/JSON error "
            "instead of a clean 400 validation message."
        ),
    )
    def test_nan_montant_is_rejected_with_400(
        self, logged_client, prestation_stripe, stripe_compte
    ):
        with mock.patch.object(
            tpe.stripe.checkout.Session,
            "create",
            return_value=SimpleNamespace(url="https://s"),
        ):
            response = _post(logged_client, prestation_stripe, "nan")
        assert response.status_code == 400

    def test_unknown_platform(self, logged_client, famille_user):
        prestation = _prestation(famille_user[1], _activite("PAYASSO"), 100)
        response = _post(logged_client, prestation, "10")
        assert response.status_code == 400
        assert response.json()["erreur"] == "Plateforme 'PAYASSO' non reconnue"

    def test_platform_not_configured(self, logged_client, famille_user):
        prestation = _prestation(famille_user[1], _activite(None), 100)
        response = _post(logged_client, prestation, "10")
        assert response.status_code == 400
        assert "non reconnue" in response.json()["erreur"]

    def test_platform_is_case_and_space_insensitive(
        self, logged_client, famille_user, ha_config
    ):
        activite = _activite("  helloasso ")
        ha_config(activite)
        prestation = _prestation(famille_user[1], activite, 100)
        client_cls = mock.MagicMock()
        client_cls.return_value.organisation_slug = "asso"
        client_cls.return_value.token = "tok"
        client_cls.return_value.create_checkout.return_value = {
            "id": "chk",
            "redirectUrl": "https://ha",
        }
        with mock.patch.object(tpe, "HelloAssoClient", client_cls):
            response = _post(logged_client, prestation, "10")
        assert response.json()["systeme_paiement"] == "helloasso"


# --------------------------------------------------------------------------- HelloAsso
@pytest.mark.django_db
class TestHelloAsso:
    @pytest.fixture
    def setup(self, famille_user, ha_config):
        activite = _activite("HELLOASSO")
        return activite, _prestation(famille_user[1], activite, 100), ha_config

    def test_no_config(self, logged_client, setup):
        _activite, prestation, _ = setup
        response = _post(logged_client, prestation, "10")
        assert response.status_code == 400
        assert response.json()["erreur"] == "Configuration HelloAsso manquante"

    def test_inactive_config_ignored(self, logged_client, setup):
        activite, prestation, ha_config = setup
        ha_config(activite, actif=False)
        assert (
            _post(logged_client, prestation, "10").json()["erreur"]
            == "Configuration HelloAsso manquante"
        )

    def test_success_creates_checkout_and_token(self, logged_client, setup):
        from core.models import TokenHA

        activite, prestation, ha_config = setup
        ha_config(activite)
        client_cls = mock.MagicMock()
        instance = client_cls.return_value
        instance.organisation_slug = "asso"
        instance.token = "access-tok"
        instance.create_checkout.return_value = {
            "id": "chk-1",
            "redirectUrl": "https://helloasso/pay",
        }
        with mock.patch.object(tpe, "HelloAssoClient", client_cls):
            response = _post(logged_client, prestation, "12.5")

        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "systeme_paiement": "helloasso",
            "url_helloasso": "https://helloasso/pay",
        }
        client_cls.assert_called_once_with(
            "cid", "sec", organisation_slug="asso", sandbox=False
        )
        kwargs = instance.create_checkout.call_args.kwargs
        assert kwargs["total_amount"] == 12.5 and kwargs["initial_amount"] == 12.5
        assert kwargs["reference"] == f"PRESTA_{prestation.pk}"
        assert kwargs["return_url"] == "https://sacadoc.flambeaux.org/attente_paiement/"
        assert kwargs["contains_donation"] is False
        token = TokenHA.objects.get()
        assert (token.prestation, token.checkout_intent_id, token.access_token) == (
            prestation,
            "chk-1",
            "access-tok",
        )
        assert token.expires_at is not None

    def test_checkout_failure_returns_500_json(self, logged_client, setup):
        from core.models import TokenHA

        activite, prestation, ha_config = setup
        ha_config(activite)
        client_cls = mock.MagicMock()
        client_cls.return_value.create_checkout.side_effect = RuntimeError("API down")
        with mock.patch.object(tpe, "HelloAssoClient", client_cls):
            response = _post(logged_client, prestation, "10")
        assert response.status_code == 500
        assert response.json() == {"success": False, "erreur": "API down"}
        assert not TokenHA.objects.exists()

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "BUG: paiement_tpe.py:~112 - HelloAssoClient(...) (which authenticates against the HelloAsso API) is "
            "instantiated outside the try block: an API/auth failure gives an HTML HTTP 500 instead of the JSON "
            "error the front-end expects."
        ),
    )
    def test_client_construction_failure_is_handled(self, logged_client, setup):
        """HelloAssoClient() is built outside the try block: a failure there must not 500."""
        activite, prestation, ha_config = setup
        ha_config(activite)
        logged_client.raise_request_exception = False
        with mock.patch.object(
            tpe, "HelloAssoClient", side_effect=RuntimeError("auth failed")
        ):
            response = _post(logged_client, prestation, "10")
        assert response["Content-Type"] == "application/json"
        assert response.json()["success"] is False


# --------------------------------------------------------------------------- Stripe
@pytest.mark.django_db
class TestStripe:
    def test_no_stripe_compte(self, logged_client, prestation_stripe):
        response = _post(logged_client, prestation_stripe, "10")
        assert response.status_code == 400
        assert response.json()["erreur"] == "Configuration Stripe manquante"

    def test_inactive_stripe_compte_ignored(
        self, logged_client, prestation_stripe, stripe_compte
    ):
        stripe_compte.actif = False
        stripe_compte.save()
        assert (
            _post(logged_client, prestation_stripe, "10").json()["erreur"]
            == "Configuration Stripe manquante"
        )

    def test_ajax_success_returns_stripe_url(
        self, logged_client, prestation_stripe, stripe_compte
    ):
        with mock.patch.object(
            tpe.stripe.checkout.Session,
            "create",
            return_value=SimpleNamespace(url="https://checkout.stripe/x"),
        ) as create:
            response = _post(logged_client, prestation_stripe, "25")
        assert response.status_code == 200
        assert response.json() == {
            "success": True,
            "systeme_paiement": "stripe",
            "url_stripe": "https://checkout.stripe/x",
        }
        assert tpe.stripe.api_key == "sk_live_x"
        kwargs = create.call_args.kwargs
        assert kwargs["mode"] == "payment"
        assert kwargs["metadata"] == {"id_prestation": prestation_stripe.pk}
        assert kwargs["line_items"][0]["price_data"]["currency"] == "eur"
        assert kwargs["line_items"][0]["price_data"]["unit_amount"] == 2500
        assert kwargs["success_url"] == (
            f"https://sacadoc.flambeaux.org/attente_paiement/?session_id={{CHECKOUT_SESSION_ID}}&compte_id={stripe_compte.pk}"
        )
        assert kwargs["cancel_url"] == "https://sacadoc.flambeaux.org/facturation"

    def test_ajax_stripe_error_returns_500_json(
        self, logged_client, prestation_stripe, stripe_compte
    ):
        with mock.patch.object(
            tpe.stripe.checkout.Session,
            "create",
            side_effect=RuntimeError("card_error"),
        ):
            response = _post(logged_client, prestation_stripe, "25")
        assert response.status_code == 500
        assert response.json() == {"success": False, "erreur": "card_error"}

    def test_stripe_error_does_not_leak_secret_key(
        self, logged_client, prestation_stripe, stripe_compte
    ):
        with mock.patch.object(
            tpe.stripe.checkout.Session, "create", side_effect=RuntimeError("bad")
        ):
            response = _post(logged_client, prestation_stripe, "25")
        assert "sk_live_x" not in response.content.decode()


@pytest.mark.django_db
class TestStripeNonAjaxBranches:
    """The route is always AJAX-wrapped, so reach the plain-form branches by calling the
    view function directly with a RequestFactory request."""

    def _request(self, rf, prestation, montant):
        request = rf.post("/", {"id_prestation": prestation.pk, "montant": montant})
        return request

    def test_form_post_redirects_to_stripe(self, rf, prestation_stripe, stripe_compte):
        request = self._request(rf, prestation_stripe, "10")
        with mock.patch.object(
            tpe.stripe.checkout.Session,
            "create",
            return_value=SimpleNamespace(url="https://checkout.stripe/y"),
        ):
            response = tpe.paiement_tpe(request)
        assert response.status_code in (302, 303)
        assert response.url == "https://checkout.stripe/y"

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "BUG: paiement_tpe.py:~170 - `redirect(session.url, code=303)`: django's redirect() has no `code` "
            "argument (it is silently ignored), so a 302 is sent instead of the intended 303 See Other."
        ),
    )
    def test_form_post_redirect_is_303(self, rf, prestation_stripe, stripe_compte):
        request = self._request(rf, prestation_stripe, "10")
        with mock.patch.object(
            tpe.stripe.checkout.Session,
            "create",
            return_value=SimpleNamespace(url="https://checkout.stripe/y"),
        ):
            response = tpe.paiement_tpe(request)
        assert response.status_code == 303

    def test_form_post_error_flashes_message_and_redirects(
        self, rf, prestation_stripe, stripe_compte
    ):
        request = self._request(rf, prestation_stripe, "10")
        with (
            mock.patch.object(
                tpe.stripe.checkout.Session, "create", side_effect=RuntimeError("nope")
            ),
            mock.patch.object(tpe, "messages") as messages,
        ):
            response = tpe.paiement_tpe(request)
        assert response.status_code == 302
        assert response.url == reverse("portail_facturation")
        messages.error.assert_called_once()
        assert "nope" in messages.error.call_args.args[1]

    def test_get_on_function_is_405(self, rf):
        assert tpe.paiement_tpe(rf.get("/")).status_code == 405


# --------------------------------------------------------------------------- legacy page view
@pytest.mark.django_db
class TestPageView:
    def test_view_context(self, rf, famille_user):
        user, _f, _ = famille_user
        request = rf.get("/")
        request.user = user
        view = tpe.View()
        view.request = request
        view.kwargs = {}
        context = view.get_context_data()
        assert context["page_titre"] == "Paiement"
