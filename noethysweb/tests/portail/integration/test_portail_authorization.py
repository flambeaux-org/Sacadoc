"""Authorization / access-control suite for the family portal.

This is the highest-value portail suite: the portal is the only externally
exposed interface, so the security guarantees are:

1. Anonymous users are redirected to the login page on every authenticated route.
2. Staff users (categorie='utilisateur') are denied the family interface.
3. A family can never read/edit another family's data (cross-family isolation).
"""

import pytest
from django.urls import reverse

# Authenticated routes that take no URL arguments.
SIMPLE_ROUTES = [
    "portail_accueil",
    "portail_renseignements",
    "portail_profil",
    "portail_cotisations",
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
    "portail_famille_caisse",
    "portail_famille_caisse_modifier",
    "portail_famille_questionnaire",
    "portail_famille_parametres",
]

# Authenticated routes parameterized by a rattachement id (individual fiches).
RATTACHEMENT_ROUTES = [
    "portail_individu_identite",
    "portail_individu_identite_modifier",
    "portail_individu_questionnaire",
    "portail_individu_coords",
    "portail_individu_regimes_alimentaires",
    "portail_individu_maladies",
    "portail_individu_allergies",
    "portail_individu_dispmed",
    "portail_individu_traitement",
    "portail_individu_medecin",
    "portail_individu_vaccinations",
    "portail_individu_vaccinations_ajouter",
    "portail_individu_informations",
    "portail_individu_assurances",
    "portail_individu_contacts",
]


@pytest.mark.django_db
class TestAnonymousRedirected:
    @pytest.mark.parametrize("route_name", SIMPLE_ROUTES)
    def test_simple_route_redirects_to_login(self, client, organisateur, route_name):
        response = client.get(reverse(route_name))
        assert response.status_code == 302
        assert "connexion" in response.url

    @pytest.mark.parametrize("route_name", RATTACHEMENT_ROUTES)
    def test_rattachement_route_redirects_to_login(self, client, famille_user, route_name):
        _user, _famille, ratt = famille_user
        url = reverse(route_name, kwargs={"idrattachement": ratt[1].pk})
        response = client.get(url)
        assert response.status_code == 302
        assert "connexion" in response.url


@pytest.mark.django_db
class TestStaffDenied:
    """A staff user must not be able to use the family portal."""

    def test_staff_redirected_from_accueil(self, client, staff_user, organisateur):
        client.force_login(staff_user)
        response = client.get(reverse("portail_accueil"))
        # Accueil explicitly redirects non-famille users to the staff home.
        assert response.status_code == 302

    @pytest.mark.parametrize(
        "route_name",
        ["portail_renseignements", "portail_facturation", "portail_documents", "portail_contact"],
    )
    def test_staff_forbidden_on_portail_pages(self, client, staff_user, organisateur, route_name):
        client.force_login(staff_user)
        response = client.get(reverse(route_name))
        assert response.status_code == 403


@pytest.mark.django_db
class TestCrossFamilyIsolation:
    """Family A must not reach Family B's individual fiches."""

    @pytest.mark.parametrize("route_name", RATTACHEMENT_ROUTES)
    def test_cannot_access_other_family_rattachement(
        self, client, famille_user, other_famille, route_name
    ):
        user_a, _famille_a, _ratt_a = famille_user
        _user_b, _famille_b, ratt_b = other_famille
        client.force_login(user_a)
        # ratt_b[1] is family B's child rattachement.
        url = reverse(route_name, kwargs={"idrattachement": ratt_b[1].pk})
        response = client.get(url)
        assert response.status_code == 403, (
            f"{route_name} leaked another family's data (got {response.status_code})"
        )

    def test_can_access_own_rattachement(self, client, famille_user):
        user_a, _famille_a, ratt_a = famille_user
        client.force_login(user_a)
        url = reverse("portail_individu_identite", kwargs={"idrattachement": ratt_a[1].pk})
        response = client.get(url)
        assert response.status_code == 200
