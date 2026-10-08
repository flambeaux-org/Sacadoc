"""Render-smoke tests for the simple (no-argument) portail pages.

Every page is fetched as a logged-in family and must return 200. These catch
template/context regressions across the whole portal in one cheap sweep.
"""

import pytest
from django.urls import reverse

RENDER_ROUTES = [
    "portail_accueil",
    "portail_renseignements",
    "portail_profil",
    "portail_documents",
    "portail_activites",
    "portail_reservations",
    "portail_facturation",
    "portail_reglements",
    "portail_questionnaires",
    "portail_verifications",
    "portail_contact",
    "portail_mentions",
    "portail_sondages",
]


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", RENDER_ROUTES)
def test_page_renders_200(logged_client, route_name):
    response = logged_client.get(reverse(route_name))
    assert response.status_code == 200


@pytest.mark.django_db
def test_cotisations_page_renders(logged_client):
    # cotisations_afficher_page defaults to False; the page itself still loads.
    response = logged_client.get(reverse("portail_cotisations"))
    assert response.status_code == 200
