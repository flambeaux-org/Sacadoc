"""E2E: the reservation planning grid renders in a real browser.

This exercises the heavy Get_data_planning + grille_tableau rendering end-to-end.
The cell-toggle + Save_grille submission needs the Unite/tariff object graph and
the grille JS internals — that interaction is left deferred (see TEST_PLAN.md).
"""

import datetime

import pytest
from playwright.sync_api import Page, expect

from core.models import PortailPeriode
from tests.unit.factories import ActiviteFactory, InscriptionFactory


@pytest.mark.django_db
def test_planning_grid_renders(auto_login_user, famille_user, live_server, page: Page):
    user, famille, ratt = famille_user
    enfant = ratt[1].individu

    # Clear pending approbations so planning.View.dispatch lets us through.
    now = datetime.datetime(2024, 1, 1, 12, 0)
    famille.certification_date = now
    famille.save(update_fields=["certification_date"])
    for r in ratt:
        r.certification_date = now
        r.save(update_fields=["certification_date"])

    activite = ActiviteFactory(portail_reservations_affichage="TOUJOURS")
    InscriptionFactory(
        famille=famille, individu=enfant, activite=activite, internet_reservations=True
    )
    periode = PortailPeriode.objects.create(
        activite=activite, nom="Période E2E",
        date_debut=datetime.date(2024, 1, 1), date_fin=datetime.date(2030, 12, 31),
        affichage="TOUJOURS", type_date="TOUTES",
    )

    page = auto_login_user(user)
    page.goto(f"{live_server.url}/planning/{enfant.pk}/{activite.pk}/{periode.pk}")

    # The grid table and its save form are rendered.
    expect(page.locator("#table-grille")).to_have_count(1)
    expect(page.locator("#form-maj")).to_have_count(1)
    assert "Traceback" not in page.locator("body").inner_text()
