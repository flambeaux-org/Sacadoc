"""Tests for the billing pages (facturation, reglements, payment-return pages).

Payment gateway internals (Payzen/PayFip/HelloAsso/Stripe/TPE endpoints and IPN
callbacks) are intentionally out of scope — see TEST_PLAN.md.
"""

import pytest
from django.urls import reverse
from tests.unit.factories import FactureFactory

@pytest.mark.django_db
class TestFacturation:
    def test_page_renders_empty(self, logged_client):
        response = logged_client.get(reverse("portail_facturation"))
        assert response.status_code == 200

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
