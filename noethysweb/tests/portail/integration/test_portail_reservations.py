"""Tests for the reservations list and the planning (booking grid) page.

The planning grid POST (Save_grille) needs a full grille JSON payload and is
exercised by the wizard/E2E layer; here we cover the page render and the
ownership/authorization logic in planning.View.test_func.
"""

import datetime

import pytest
from django.urls import reverse

from core.models import PortailPeriode
from tests.unit.factories import ActiviteFactory, InscriptionFactory


def make_periode(activite):
    return PortailPeriode.objects.create(
        activite=activite,
        nom="Période test",
        date_debut=datetime.date(2024, 1, 1),
        date_fin=datetime.date(2030, 12, 31),
        affichage="TOUJOURS",
        type_date="TOUTES",
    )


def certify(famille, rattachements):
    """Clear all pending approbations so planning.View.dispatch lets the request
    through to test_func (otherwise it redirects to renseignements)."""
    now = datetime.datetime(2024, 1, 1, 12, 0)
    famille.certification_date = now
    famille.save(update_fields=["certification_date"])
    for ratt in rattachements:
        ratt.certification_date = now
        ratt.save(update_fields=["certification_date"])


@pytest.mark.django_db
class TestReservationsList:
    def test_page_renders(self, logged_client):
        response = logged_client.get(reverse("portail_reservations"))
        assert response.status_code == 200


@pytest.mark.django_db
class TestPlanning:
    def _url(self, individu, activite, periode):
        return reverse(
            "portail_planning",
            kwargs={
                "idindividu": individu.pk,
                "idactivite": activite.pk,
                "idperiode": periode.pk,
            },
        )

    def test_forbidden_without_inscription(self, logged_client, famille_user):
        _user, famille, ratt = famille_user
        certify(famille, ratt)
        activite = ActiviteFactory(portail_reservations_affichage="TOUJOURS")
        periode = make_periode(activite)
        # No inscription links the child to this activity -> test_func fails.
        response = logged_client.get(self._url(ratt[1].individu, activite, periode))
        assert response.status_code == 403

    def test_renders_with_inscription(self, logged_client, famille_user):
        _user, famille, ratt = famille_user
        certify(famille, ratt)
        enfant = ratt[1].individu
        activite = ActiviteFactory(portail_reservations_affichage="TOUJOURS")
        InscriptionFactory(
            famille=famille, individu=enfant, activite=activite, internet_reservations=True
        )
        periode = make_periode(activite)
        response = logged_client.get(self._url(enfant, activite, periode))
        assert response.status_code == 200

    def test_cross_family_individu_forbidden(self, logged_client, famille_user, other_famille):
        _ua, famille_a, ratt_a = famille_user
        certify(famille_a, ratt_a)
        _ub, _famille_b, ratt_b = other_famille
        activite = ActiviteFactory(portail_reservations_affichage="TOUJOURS")
        # Inscription belongs to family A's child; we request family B's child id.
        InscriptionFactory(
            famille=famille_a, individu=ratt_a[1].individu, activite=activite,
            internet_reservations=True,
        )
        periode = make_periode(activite)
        response = logged_client.get(self._url(ratt_b[1].individu, activite, periode))
        assert response.status_code == 403
