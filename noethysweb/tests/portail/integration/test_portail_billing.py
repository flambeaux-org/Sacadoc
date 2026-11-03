"""Tests for the billing pages (facturation, reglements, payment-return pages).

Payment gateway internals (Payzen/PayFip/HelloAsso/Stripe/TPE endpoints and IPN
callbacks) are intentionally out of scope — see TEST_PLAN.md.
"""

import pytest
from django.urls import reverse
from tests.unit.factories import FactureFactory

FACTURATION_RETURN_BUG = pytest.mark.xfail(
    reason="BUG #6: facturation.View.get_context_data has `return context` indented inside "
    "`if facturation_afficher_solde_famille:` — with the (default) False setting it returns "
    "None and the page 500s. See TEST_PLAN.md.",
    strict=True,
)


@pytest.mark.django_db
class TestFacturation:
    @FACTURATION_RETURN_BUG
    def test_page_renders_empty(self, logged_client):
        response = logged_client.get(reverse("portail_facturation"))
        assert response.status_code == 200

    @FACTURATION_RETURN_BUG
    def test_page_renders_with_facture(self, logged_client, famille_user):
        _user, famille, _ratt = famille_user
        FactureFactory(famille=famille, total=120, solde_actuel=120)
        response = logged_client.get(reverse("portail_facturation"))
        assert response.status_code == 200

    def test_page_renders_when_solde_famille_enabled(
        self, logged_client, set_parametre_portail
    ):
        """The only branch that currently reaches `return context` (see bug #6)."""
        set_parametre_portail("facturation_afficher_solde_famille", True)
        response = logged_client.get(reverse("portail_facturation"))
        assert response.status_code == 200
        assert "solde_famille" in response.context


@pytest.mark.django_db
class TestReglements:
    def test_page_renders(self, logged_client):
        response = logged_client.get(reverse("portail_reglements"))
        assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    "route_name",
    [
        "retour_payzen_cancel",
        "retour_payzen_error",
        "retour_payzen_refused",
        "retour_payzen_success",
    ],
)
def test_payment_return_pages_render(logged_client, route_name):
    """The Payzen return *pages* are plain template renders (no gateway call)."""
    response = logged_client.get(reverse(route_name))
    assert response.status_code == 200
