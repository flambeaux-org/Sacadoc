"""Tests for portail/views/attente_paiement.py (payment return page).

All external calls (stripe, requests to HelloAsso, e-mail backends) are mocked.
"""

import datetime
import decimal
from types import SimpleNamespace
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone
from portail.views import attente_paiement as ap
from tests.unit.factories import ActiviteFactory, AdresseMailFactory

URL = "portail_attente_paiement"


# --------------------------------------------------------------------------- helpers
def _fixtures_codes_en_dur(famille):
    """valider_paiement_final() uses hard-coded pks (mode 6, payeur 3, modelimp 2,
    analytique 1, categorie 1): create them."""
    from core.models import (
        ComptaAnalytique,
        ComptaCategorie,
        ModeleImpression,
        ModeReglement,
        Payeur,
    )

    ModeReglement.objects.create(pk=6, label="Paiement en ligne")
    Payeur.objects.create(pk=3, famille=famille, nom="Payeur")
    ModeleImpression.objects.create(
        pk=2, categorie="reglement", nom="Recu", options="{}"
    )
    ComptaAnalytique.objects.create(pk=1, nom="Analytique")
    ComptaCategorie.objects.create(pk=1, type="credit", nom="Categorie")


def _prestation(famille, activite=None, montant=50):
    from core.models import Prestation

    activite = activite or ActiviteFactory()
    return Prestation.objects.create(
        famille=famille,
        activite=activite,
        date=datetime.date(2026, 1, 1),
        label="Camp d'été",
        montant=montant,
        montant_initial=montant,
    )


def _compte(structure=None, pk=None):
    from core.models import CompteBancaire

    kwargs = {"nom": "Compte", "structure": structure}
    if pk:
        kwargs["pk"] = pk
    return CompteBancaire.objects.create(**kwargs)


def _stripe_session(prestation, paid=True, session_id="cs_test_1", total=5000):
    return SimpleNamespace(
        id=session_id,
        payment_status="paid" if paid else "unpaid",
        metadata={"id_prestation": str(prestation.pk)},
        amount_total=total,
    )


def _stripe_compte(activite, actif=True):
    from core.models import StripeCompte

    compte = StripeCompte.objects.create(
        nom="S", secret_key="sk_test", publishable_key="pk_test", actif=actif
    )
    compte.activites.add(activite)
    return compte


def _msgs(response):
    return [str(m) for m in response.wsgi_request._messages]


# --------------------------------------------------------------------------- dispatch of get()
@pytest.mark.django_db
class TestDispatch:
    def test_no_params_redirects_with_error(self, logged_client):
        response = logged_client.get(reverse(URL))
        assert response.status_code == 302
        assert response.url == reverse("portail_facturation")
        assert "Aucune information de paiement reçue." in _msgs(response)

    def test_anonymous_no_params_redirects_to_facturation(self, client, organisateur):
        """The view is not a CustomView: no login wall, it just redirects."""
        response = client.get(reverse(URL))
        assert response.status_code == 302
        assert response.url == reverse("portail_facturation")

    def test_staff_no_params_redirects(self, client, staff_user, organisateur):
        client.force_login(staff_user)
        response = client.get(reverse(URL))
        assert response.status_code == 302
        assert response.url == reverse("portail_facturation")

    def test_unformatted_stripe_placeholder_is_rejected(self, logged_client):
        """compte_id still containing "{" means the success_url was mis-built."""
        with mock.patch.object(ap.stripe.checkout.Session, "retrieve") as retrieve:
            response = logged_client.get(
                reverse(URL), {"session_id": "cs", "compte_id": "{x}"}
            )
        assert response.status_code == 302
        assert response.url == reverse("portail_facturation")
        assert "Erreur de configuration du lien de paiement." in _msgs(response)
        retrieve.assert_not_called()

    def test_only_session_id_falls_through_to_error(self, logged_client):
        response = logged_client.get(reverse(URL), {"session_id": "cs"})
        assert "Aucune information de paiement reçue." in _msgs(response)

    def test_checkout_intent_routes_to_helloasso(self, logged_client):
        with mock.patch.object(
            ap.View,
            "handle_helloasso_logic",
            return_value=ap.redirect("portail_facturation"),
        ) as h:
            logged_client.get(reverse(URL), {"checkoutIntentId": "42", "orderId": "7"})
        h.assert_called_once()
        assert h.call_args.args[1:] == ("42", "7")

    def test_stripe_params_route_to_stripe(self, logged_client):
        with mock.patch.object(
            ap.View,
            "handle_stripe_logic",
            return_value=ap.redirect("portail_facturation"),
        ) as h:
            logged_client.get(reverse(URL), {"session_id": "cs", "compte_id": "3"})
        assert h.call_args.args[1:] == ("cs", "3")

    def test_stripe_takes_priority_over_helloasso(self, logged_client):
        with (
            mock.patch.object(
                ap.View,
                "handle_stripe_logic",
                return_value=ap.redirect("portail_facturation"),
            ) as s,
            mock.patch.object(ap.View, "handle_helloasso_logic") as h,
        ):
            logged_client.get(
                reverse(URL),
                {"session_id": "cs", "compte_id": "3", "checkoutIntentId": "9"},
            )
        s.assert_called_once()
        h.assert_not_called()

    def test_get_context_data(self, rf):
        """get_context_data is unused by get() (the view always redirects) and calls
        super().get_context_data which plain View lacks -> test via a TemplateView-like stub."""
        view = ap.View()
        view.request = rf.get("/", {"checkoutIntentId": "A", "orderId": "B"})

        class Base:
            def get_context_data(self, **kwargs):
                return {}

        view.__class__ = type("V", (ap.View, Base), {})
        # MRO: ap.View -> DjangoBaseView -> Base; DjangoBaseView has no get_context_data
        ctx = view.get_context_data()
        assert ctx["page_titre"] == "Attente du paiement"
        assert ctx["checkout_intent_id"] == "A"
        assert ctx["order_id"] == "B"


# --------------------------------------------------------------------------- Stripe
@pytest.mark.django_db
class TestStripe:
    def _get(self, client, compte, session_id="cs_test_1"):
        return client.get(
            reverse(URL), {"session_id": session_id, "compte_id": compte.pk}
        )

    def test_paid_session_creates_reglement_and_all_records(
        self, logged_client, famille_user
    ):
        from core.models import (
            ComptaOperation,
            ComptaVentilation,
            Paiement,
            Reglement,
            Ventilation,
        )

        _user, famille, _ = famille_user
        _fixtures_codes_en_dur(famille)
        prestation = _prestation(famille)
        _compte(prestation.activite.structure)
        stripe_compte = _stripe_compte(prestation.activite)
        session = _stripe_session(prestation)
        with (
            mock.patch.object(
                ap.stripe.checkout.Session, "retrieve", return_value=session
            ) as retrieve,
            mock.patch.object(ap, "envoyer_email_paiement_stripe") as envoi,
        ):
            response = self._get(logged_client, stripe_compte)

        retrieve.assert_called_once_with("cs_test_1")
        assert ap.stripe.api_key == "sk_test"
        assert response.status_code == 302 and response.url == reverse(
            "portail_facturation"
        )
        assert "Paiement Stripe validé !" in _msgs(response)
        reglement = Reglement.objects.get()
        assert reglement.montant == decimal.Decimal(50)
        assert reglement.observations == "STRIPE_SESSION_cs_test_1"
        assert reglement.famille == famille
        ventil = Ventilation.objects.get()
        assert (ventil.prestation, ventil.reglement, ventil.montant) == (
            prestation,
            reglement,
            decimal.Decimal(50),
        )
        assert ComptaOperation.objects.get().ref_piece == "cs_test_1"
        assert ComptaVentilation.objects.count() == 1
        paiement = Paiement.objects.get()
        assert paiement.systeme_paiement == "STRIPE" and paiement.resultat == "PAID"
        assert list(paiement.reglements.all()) == [reglement]
        envoi.assert_called_once_with(prestation, decimal.Decimal(50), "cs_test_1")

    def test_compte_falls_back_to_first_when_structure_has_none(
        self, logged_client, famille_user
    ):
        from core.models import Reglement

        _user, famille, _ = famille_user
        _fixtures_codes_en_dur(famille)
        prestation = _prestation(famille)
        fallback = _compte(structure=None)
        stripe_compte = _stripe_compte(prestation.activite)
        with (
            mock.patch.object(
                ap.stripe.checkout.Session,
                "retrieve",
                return_value=_stripe_session(prestation),
            ),
            mock.patch.object(ap, "envoyer_email_paiement_stripe"),
        ):
            self._get(logged_client, stripe_compte)
        assert Reglement.objects.get().compte == fallback

    def test_replay_is_idempotent(self, logged_client, famille_user):
        """Reloading the return page must not create a second règlement."""
        from core.models import Reglement

        _user, famille, _ = famille_user
        _fixtures_codes_en_dur(famille)
        prestation = _prestation(famille)
        _compte(prestation.activite.structure)
        stripe_compte = _stripe_compte(prestation.activite)
        with (
            mock.patch.object(
                ap.stripe.checkout.Session,
                "retrieve",
                return_value=_stripe_session(prestation),
            ),
            mock.patch.object(ap, "envoyer_email_paiement_stripe") as envoi,
        ):
            self._get(logged_client, stripe_compte)
            response = self._get(logged_client, stripe_compte)
        assert Reglement.objects.count() == 1
        assert response.status_code == 302
        assert envoi.call_count == 1

    def test_unpaid_session_creates_nothing(self, logged_client, famille_user):
        from core.models import Reglement

        _user, famille, _ = famille_user
        prestation = _prestation(famille)
        stripe_compte = _stripe_compte(prestation.activite)
        with mock.patch.object(
            ap.stripe.checkout.Session,
            "retrieve",
            return_value=_stripe_session(prestation, paid=False),
        ):
            response = self._get(logged_client, stripe_compte)
        assert response.url == reverse("portail_facturation")
        assert not Reglement.objects.exists()

    def test_unknown_stripe_compte(self, logged_client):
        response = logged_client.get(
            reverse(URL), {"session_id": "cs", "compte_id": "999"}
        )
        assert response.url == reverse("portail_facturation")
        assert "Erreur lors de la validation Stripe." in _msgs(response)

    def test_inactive_stripe_compte(self, logged_client, famille_user):
        _user, famille, _ = famille_user
        prestation = _prestation(famille)
        stripe_compte = _stripe_compte(prestation.activite, actif=False)
        with mock.patch.object(ap.stripe.checkout.Session, "retrieve") as retrieve:
            response = self._get(logged_client, stripe_compte)
        assert "Erreur lors de la validation Stripe." in _msgs(response)
        retrieve.assert_not_called()

    def test_non_numeric_compte_id(self, logged_client):
        response = logged_client.get(
            reverse(URL), {"session_id": "cs", "compte_id": "abc"}
        )
        assert "Erreur lors de la validation Stripe." in _msgs(response)

    def test_stripe_api_error(self, logged_client, famille_user):
        _user, famille, _ = famille_user
        prestation = _prestation(famille)
        stripe_compte = _stripe_compte(prestation.activite)
        with mock.patch.object(
            ap.stripe.checkout.Session, "retrieve", side_effect=RuntimeError("boom")
        ):
            response = self._get(logged_client, stripe_compte)
        assert response.url == reverse("portail_facturation")
        assert "Erreur lors de la validation Stripe." in _msgs(response)

    def test_unknown_prestation_in_metadata(self, logged_client, famille_user):
        from core.models import Reglement

        _user, famille, _ = famille_user
        prestation = _prestation(famille)
        stripe_compte = _stripe_compte(prestation.activite)
        session = _stripe_session(prestation)
        session.metadata = {"id_prestation": "99999"}
        with mock.patch.object(
            ap.stripe.checkout.Session, "retrieve", return_value=session
        ):
            response = self._get(logged_client, stripe_compte)
        assert "Erreur lors de la validation Stripe." in _msgs(response)
        assert not Reglement.objects.exists()

    def test_missing_hardcoded_reference_rows_is_handled(
        self, logged_client, famille_user
    ):
        """Without ModeReglement pk=6 etc. the creation fails: the error must be
        reported to the user instead of a 500 (and no Reglement may remain)."""
        from core.models import Reglement

        _user, famille, _ = famille_user
        prestation = _prestation(famille)
        _compte(prestation.activite.structure)
        stripe_compte = _stripe_compte(prestation.activite)
        with (
            mock.patch.object(
                ap.stripe.checkout.Session,
                "retrieve",
                return_value=_stripe_session(prestation),
            ),
            mock.patch.object(
                ap.View, "valider_paiement_final", side_effect=ValueError("fk")
            ),
        ):
            response = self._get(logged_client, stripe_compte)
        assert response.status_code == 302
        assert "Erreur lors de la validation Stripe." in _msgs(response)
        assert not Reglement.objects.exists()


# --------------------------------------------------------------------------- HelloAsso
def _token(prestation, checkout_id="77", expires_in=600, slug="mon-asso"):
    from core.models import TokenHA

    return TokenHA.objects.create(
        prestation=prestation,
        checkout_intent_id=checkout_id,
        organisation_slug=slug,
        access_token="tok",
        expires_at=timezone.now() + datetime.timedelta(seconds=expires_in),
    )


def _ha_config(activite, slug="mon-asso"):
    from core.models import HelloAssoConfig

    config = HelloAssoConfig.objects.create(
        client_id="c", client_secret="s", org_slug=slug
    )
    config.activites.add(activite)
    return config


def _ha_response(payload, raise_exc=None):
    resp = mock.MagicMock()
    resp.json.return_value = payload
    if raise_exc:
        resp.raise_for_status.side_effect = raise_exc
    return resp


def _order(state="Authorized", order_id=555, total=5000, with_payments=True):
    order = {"id": order_id, "amount": {"total": total}}
    if with_payments:
        order["payments"] = [{"state": state}]
    else:
        order["payments"] = []
    return {"order": order}


@pytest.mark.django_db
class TestHelloAsso:
    def _get(self, client, checkout_id="77", order_id="555"):
        return client.get(
            reverse(URL), {"checkoutIntentId": checkout_id, "orderId": order_id}
        )

    def test_unknown_token(self, logged_client):
        response = self._get(logged_client)
        assert response.url == reverse("portail_facturation")
        assert "Token non trouvé ou expiré" in _msgs(response)

    def test_expired_token(self, logged_client, famille_user):
        _user, famille, _ = famille_user
        _token(_prestation(famille), expires_in=-10)
        response = self._get(logged_client)
        assert "Token non trouvé ou expiré" in _msgs(response)

    def test_api_url_and_auth_header(self, logged_client, famille_user):
        _user, famille, _ = famille_user
        _token(_prestation(famille))
        with mock.patch.object(
            ap.requests, "get", return_value=_ha_response({})
        ) as get:
            self._get(logged_client)
        get.assert_called_once_with(
            "https://api.helloasso.com/v5/organizations/mon-asso/checkout-intents/77",
            headers={"Authorization": "Bearer tok"},
        )

    def test_order_missing_means_pending(self, logged_client, famille_user):
        _user, famille, _ = famille_user
        _token(_prestation(famille))
        with mock.patch.object(
            ap.requests, "get", return_value=_ha_response({"order": None})
        ):
            response = self._get(logged_client)
        assert response.url == reverse("portail_facturation")
        assert "Paiement en attente..." in _msgs(response)

    def test_http_error_is_reported(self, logged_client, famille_user):
        from core.models import Reglement

        _user, famille, _ = famille_user
        _token(_prestation(famille))
        with mock.patch.object(
            ap.requests,
            "get",
            return_value=_ha_response({}, raise_exc=RuntimeError("401")),
        ):
            response = self._get(logged_client)
        assert any("Erreur API HelloAsso" in m for m in _msgs(response))
        assert not Reglement.objects.exists()

    def test_no_payments_redirects_silently(self, logged_client, famille_user):
        from core.models import Reglement

        _user, famille, _ = famille_user
        _token(_prestation(famille))
        with mock.patch.object(
            ap.requests, "get", return_value=_ha_response(_order(with_payments=False))
        ):
            response = self._get(logged_client)
        assert response.url == reverse("portail_facturation")
        assert _msgs(response) == []
        assert not Reglement.objects.exists()

    @pytest.mark.parametrize(
        "state", ["Authorized", "authorized", "Success", "succeeded"]
    )
    def test_successful_states_create_reglement(
        self, logged_client, famille_user, state
    ):
        from core.models import Paiement, Reglement

        _user, famille, _ = famille_user
        _fixtures_codes_en_dur(famille)
        prestation = _prestation(famille)
        _compte(prestation.activite.structure)
        _ha_config(prestation.activite)
        _token(prestation)
        with mock.patch.object(
            ap.requests, "get", return_value=_ha_response(_order(state=state))
        ):
            response = self._get(logged_client)
        assert "Paiement HelloAsso validé !" in _msgs(response)
        reglement = Reglement.objects.get()
        assert reglement.observations == "HELLOASSO_555"
        assert reglement.montant == decimal.Decimal(50)
        assert Paiement.objects.get().systeme_paiement == "HELLOASSO"

    def test_compte_falls_back_to_pk_1(self, logged_client, famille_user):
        from core.models import Reglement

        _user, famille, _ = famille_user
        _fixtures_codes_en_dur(famille)
        prestation = _prestation(famille)
        fallback = _compte(structure=None, pk=1)
        _ha_config(prestation.activite)
        _token(prestation)
        with mock.patch.object(ap.requests, "get", return_value=_ha_response(_order())):
            self._get(logged_client)
        assert Reglement.objects.get().compte == fallback

    def test_order_id_from_query_used_as_piece_reference(
        self, logged_client, famille_user
    ):
        from core.models import ComptaOperation

        _user, famille, _ = famille_user
        _fixtures_codes_en_dur(famille)
        prestation = _prestation(famille)
        _compte(prestation.activite.structure)
        _ha_config(prestation.activite)
        _token(prestation)
        with mock.patch.object(ap.requests, "get", return_value=_ha_response(_order())):
            self._get(logged_client, order_id="QS-ORDER")
        assert ComptaOperation.objects.get().ref_piece == "QS-ORDER"

    def test_replay_does_not_duplicate(self, logged_client, famille_user):
        from core.models import Reglement

        _user, famille, _ = famille_user
        _fixtures_codes_en_dur(famille)
        prestation = _prestation(famille)
        _compte(prestation.activite.structure)
        _ha_config(prestation.activite)
        _token(prestation)
        with mock.patch.object(ap.requests, "get", return_value=_ha_response(_order())):
            self._get(logged_client)
            response = self._get(logged_client)
        assert Reglement.objects.count() == 1
        assert response.url == reverse("portail_facturation")

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "BUG: attente_paiement.py:~155 - when the HelloAsso payment state is not successful "
            "(e.g. 'Pending'), `tag` is never assigned -> UnboundLocalError swallowed by the broad "
            "except -> user sees a bogus 'Erreur API HelloAsso' message instead of a 'pending' notice."
        ),
    )
    def test_pending_state_is_not_reported_as_api_error(
        self, logged_client, famille_user
    ):
        _user, famille, _ = famille_user
        _token(_prestation(famille))
        with mock.patch.object(
            ap.requests, "get", return_value=_ha_response(_order(state="Pending"))
        ):
            response = self._get(logged_client)
        assert not any("Erreur API HelloAsso" in m for m in _msgs(response))

    def test_pending_state_creates_no_reglement(self, logged_client, famille_user):
        from core.models import Reglement

        _user, famille, _ = famille_user
        _token(_prestation(famille))
        with mock.patch.object(
            ap.requests, "get", return_value=_ha_response(_order(state="Pending"))
        ):
            response = self._get(logged_client)
        assert response.url == reverse("portail_facturation")
        assert not Reglement.objects.exists()

    def test_missing_config_is_reported(self, logged_client, famille_user):
        from core.models import Reglement

        _user, famille, _ = famille_user
        _fixtures_codes_en_dur(famille)
        _token(_prestation(famille))
        with mock.patch.object(ap.requests, "get", return_value=_ha_response(_order())):
            response = self._get(logged_client)
        assert any("Erreur API HelloAsso" in m for m in _msgs(response))
        assert not Reglement.objects.exists()


# --------------------------------------------------------------------------- e-mail notification
def _setup_mail(
    monkeypatch=None,
    moteur="console",
    organisateur_mail="orga@test.org",
    configure=True,
    actif=True,
    **kw,
):
    from core.models import Organisateur

    adresse = AdresseMailFactory(
        moteur=moteur,
        actif=actif,
        hote="smtp.test",
        port=587,
        utilisateur="u",
        motdepasse="p",
        use_tls=True,
        **kw,
    )
    if configure:
        from core.models import PortailParametre

        PortailParametre.objects.update_or_create(
            code="connexion_adresse_exp", defaults={"valeur": str(adresse.pk)}
        )
        from django.core.cache import cache

        cache.clear()
    Organisateur.objects.update_or_create(
        pk=1, defaults={"nom": "Orga", "mail": organisateur_mail}
    )
    return adresse


@pytest.mark.django_db
class TestEnvoyerEmailPaiementStripe:
    @pytest.fixture
    def prestation(self, famille_user):
        return _prestation(famille_user[1])

    @pytest.fixture
    def conn(self):
        with mock.patch.object(ap.djangomail, "get_connection") as get_connection:
            yield get_connection

    def test_no_sender_address_configured(self, prestation, conn):
        ap.envoyer_email_paiement_stripe(prestation, 50, "cs")
        conn.assert_not_called()

    def test_inactive_sender_address(self, prestation, conn, organisateur):
        _setup_mail(actif=False)
        ap.envoyer_email_paiement_stripe(prestation, 50, "cs")
        conn.assert_not_called()

    def test_no_organisateur_mail(self, prestation, conn, organisateur):
        _setup_mail(organisateur_mail=None)
        ap.envoyer_email_paiement_stripe(prestation, 50, "cs")
        conn.assert_not_called()

    def test_no_organisateur_at_all(self, prestation, conn):
        from core.models import Organisateur, PortailParametre

        adresse = AdresseMailFactory()
        PortailParametre.objects.create(
            code="connexion_adresse_exp", valeur=str(adresse.pk)
        )
        Organisateur.objects.all().delete()
        ap.envoyer_email_paiement_stripe(prestation, 50, "cs")
        conn.assert_not_called()

    def test_debug_uses_console_backend(
        self, prestation, conn, organisateur, monkeypatch
    ):
        _setup_mail(moteur="smtp")
        monkeypatch.setattr(ap.settings, "DEBUG", True)
        ap.envoyer_email_paiement_stripe(prestation, 50, "cs")
        assert (
            conn.call_args.kwargs["backend"]
            == "django.core.mail.backends.console.EmailBackend"
        )
        assert "host" not in conn.call_args.kwargs

    def test_smtp_backend_in_production(
        self, prestation, conn, organisateur, monkeypatch
    ):
        _setup_mail(moteur="smtp")
        monkeypatch.setattr(ap.settings, "DEBUG", False)
        ap.envoyer_email_paiement_stripe(prestation, 50, "cs")
        kwargs = conn.call_args.kwargs
        assert kwargs["backend"] == "django.core.mail.backends.smtp.EmailBackend"
        assert (
            kwargs["host"],
            kwargs["port"],
            kwargs["username"],
            kwargs["use_tls"],
        ) == ("smtp.test", 587, "u", True)

    def test_mailjet_backend_in_production(
        self, prestation, conn, organisateur, monkeypatch
    ):
        _setup_mail(moteur="mailjet", parametres="api_key==K##api_secret==S")
        monkeypatch.setattr(ap.settings, "DEBUG", False)
        ap.envoyer_email_paiement_stripe(prestation, 50, "cs")
        kwargs = conn.call_args.kwargs
        assert kwargs["backend"] == "anymail.backends.mailjet.EmailBackend"
        assert (kwargs["api_key"], kwargs["secret_key"]) == ("K", "S")

    def test_brevo_backend_in_production(
        self, prestation, conn, organisateur, monkeypatch
    ):
        _setup_mail(moteur="brevo", parametres="api_key==K")
        monkeypatch.setattr(ap.settings, "DEBUG", False)
        ap.envoyer_email_paiement_stripe(prestation, 50, "cs")
        kwargs = conn.call_args.kwargs
        assert kwargs["backend"] == "anymail.backends.sendinblue.EmailBackend"
        assert kwargs["api_key"] == "K"

    def test_unknown_engine_in_production_keeps_console(
        self, prestation, conn, organisateur, monkeypatch
    ):
        _setup_mail(moteur="console")
        monkeypatch.setattr(ap.settings, "DEBUG", False)
        ap.envoyer_email_paiement_stripe(prestation, 50, "cs")
        assert (
            conn.call_args.kwargs["backend"]
            == "django.core.mail.backends.console.EmailBackend"
        )

    def test_connection_failure_is_logged_and_nothing_sent(
        self, prestation, conn, organisateur, caplog
    ):
        _setup_mail()
        conn.return_value.open.side_effect = OSError("down")
        ap.envoyer_email_paiement_stripe(prestation, 50, "cs")
        conn.return_value.send_messages.assert_not_called()
        assert "connexion impossible" in caplog.text

    def test_message_content_and_connection_closed(
        self, prestation, conn, organisateur
    ):
        _setup_mail()
        ap.envoyer_email_paiement_stripe(prestation, 50, "cs_abc")
        ((messages,), _) = conn.return_value.send_messages.call_args
        message = messages[0]
        assert message.subject == "Paiement Stripe reçu"
        assert message.to == ["orga@test.org"]
        assert (
            "cs_abc" in message.body
            and "Camp d'été" in message.body
            and "50" in message.body
        )
        conn.return_value.close.assert_called_once()

    def test_send_failure_is_logged_and_connection_closed(
        self, prestation, conn, organisateur, caplog
    ):
        _setup_mail()
        conn.return_value.send_messages.side_effect = RuntimeError("smtp 550")
        ap.envoyer_email_paiement_stripe(prestation, 50, "cs")
        assert "erreur d'envoi" in caplog.text
        conn.return_value.close.assert_called_once()
