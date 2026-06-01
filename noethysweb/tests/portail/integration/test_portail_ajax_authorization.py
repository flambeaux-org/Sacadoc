"""Authorization probes for the 16 `@secure_ajax_portail` AJAX endpoints.

The decorator (core/decorators.py) guarantees, before the view runs:
  - a non-AJAX request           -> 400 Bad Request
  - an unauthenticated request   -> 403 Forbidden
  - a non-"famille" user         -> 403 Forbidden

These probes assert the decorator is wired onto every AJAX endpoint, so none of
them is reachable anonymously, by staff, or via a plain (non-AJAX) request.
"""

import pytest
from django.urls import reverse

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}

AJAX_ROUTES = [
    "portail_ajax_facturer",
    "portail_ajax_get_detail_facture",
    "portail_ajax_imprimer_facture",
    "portail_ajax_effectuer_paiement_en_ligne",
    "portail_ajax_imprimer_recu",
    "portail_ajax_ajouter_regime_alimentaire",
    "portail_ajax_ajouter_maladie",
    "portail_ajax_ajouter_allergie",
    "portail_ajax_ajouter_dispmed",
    "portail_ajax_ajouter_medecin",
    "portail_ajax_ajouter_assureur",
    "portail_ajax_inscrire_get_form_extra",
    "portail_ajax_get_activites_par_structure",
    "portail_ajax_inscrire_valid_form",
    "ajax_annulation_portail",
    "portail_ajax_paiement_tpe",
]


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", AJAX_ROUTES)
class TestAjaxEndpointAuthorization:
    def test_anonymous_forbidden(self, client, organisateur, route_name):
        response = client.post(reverse(route_name), **AJAX)
        assert response.status_code == 403

    def test_staff_forbidden(self, client, staff_user, organisateur, route_name):
        client.force_login(staff_user)
        response = client.post(reverse(route_name), **AJAX)
        assert response.status_code == 403

    def test_non_ajax_bad_request(self, logged_client, route_name):
        # A famille user, but without the AJAX header -> 400 before the view runs.
        response = logged_client.post(reverse(route_name))
        assert response.status_code == 400


@pytest.mark.django_db
def test_famille_passes_decorator(logged_client, famille_user):
    """A famille AJAX call clears the decorator (creates a RegimeAlimentaire),
    proving the 403s above are about identity, not a blanket block."""
    from core.models import RegimeAlimentaire

    response = logged_client.post(
        reverse("portail_ajax_ajouter_regime_alimentaire"),
        {"valeur": "Sans gluten"},
        **AJAX,
    )
    # Not blocked by the decorator (would be 400/403); the view handled it.
    assert response.status_code == 200
    assert RegimeAlimentaire.objects.filter(nom="Sans gluten").exists()
