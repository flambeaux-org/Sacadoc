"""E2E: toggle cells of the portal planning grid and save (Save_grille)."""

import datetime

import pytest
from core.models import (
    CategorieTarif,
    Consommation,
    Ouverture,
    PortailPeriode,
    Unite,
)
from playwright.sync_api import Page, expect
from tests.unit.factories import ActiviteFactory, GroupeFactory, InscriptionFactory

NOW = datetime.datetime(2024, 1, 1, 12, 0)


def _clear_approbations(famille, ratt):
    famille.certification_date = NOW
    famille.save(update_fields=["certification_date"])
    for r in ratt:
        r.certification_date = NOW
        r.save(update_fields=["certification_date"])


def _build_planning(famille, ratt, nb_jours=10):
    """Activite + Unite + Ouvertures for the next days + inscription + periode."""
    _clear_approbations(famille, ratt)
    enfant = ratt[1].individu
    activite = ActiviteFactory(portail_reservations_affichage="TOUJOURS")
    groupe = GroupeFactory(activite=activite)
    categorie = CategorieTarif.objects.create(activite=activite, nom="Cat E2E")
    unite = Unite.objects.create(
        activite=activite, ordre=1, nom="Journee", abrege="J", type="Unitaire"
    )
    today = datetime.date.today()
    dates = [today + datetime.timedelta(days=i) for i in range(1, nb_jours + 1)]
    for d in dates:
        Ouverture.objects.create(activite=activite, unite=unite, groupe=groupe, date=d)
    inscription = InscriptionFactory(
        famille=famille,
        individu=enfant,
        activite=activite,
        groupe=groupe,
        categorie_tarif=categorie,
        internet_reservations=True,
        date_debut=datetime.date(2020, 1, 1),
    )
    periode = PortailPeriode.objects.create(
        activite=activite,
        nom="Periode save",
        date_debut=today,
        date_fin=today + datetime.timedelta(days=nb_jours + 2),
        affichage="TOUJOURS",
        type_date="TOUTES",
    )
    return enfant, activite, unite, inscription, periode, dates


@pytest.mark.django_db
def test_toggle_cell_and_save_creates_consommation(
    auto_login_user, famille_user, live_server, page: Page
):
    user, famille, ratt = famille_user
    enfant, activite, unite, inscription, periode, dates = _build_planning(
        famille, ratt
    )

    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    page = auto_login_user(user)
    page.goto(f"{live_server.url}/planning/{enfant.pk}/{activite.pk}/{periode.pk}")

    cases = page.locator("#table-grille td.case.ouvert")
    expect(cases.first).to_be_visible()
    assert cases.count() == len(dates)

    cases.nth(0).click()
    cases.nth(2).click()

    page.locator("#enregistrer").click()
    page.wait_for_url(f"{live_server.url}/reservations")

    assert not errors, errors
    consos = Consommation.objects.filter(inscription=inscription, unite=unite)
    assert consos.count() == 2
    assert set(consos.values_list("date", flat=True)) == {dates[0], dates[2]}
    assert all(c.individu_id == enfant.pk for c in consos)


@pytest.mark.django_db
def test_existing_reservation_can_be_removed(
    auto_login_user, famille_user, live_server, page: Page
):
    user, famille, ratt = famille_user
    enfant, activite, unite, inscription, periode, dates = _build_planning(
        famille, ratt
    )
    Consommation.objects.create(
        individu=enfant,
        inscription=inscription,
        activite=activite,
        date=dates[1],
        unite=unite,
        groupe=inscription.groupe,
        etat="reservation",
        categorie_tarif=inscription.categorie_tarif,
        quantite=1,
    )

    page = auto_login_user(user)
    page.goto(f"{live_server.url}/planning/{enfant.pk}/{activite.pk}/{periode.pk}")
    expect(page.locator("#table-grille td.case.ouvert").first).to_be_visible()

    # The reserved cell is rendered by the grid JS (it carries a state class/icon).
    cell = page.locator("#table-grille td.case.ouvert").nth(1)
    cell.click()  # toggles reservation off
    page.locator("#enregistrer").click()
    page.wait_for_url(f"{live_server.url}/reservations")

    assert not Consommation.objects.filter(inscription=inscription).exists()


@pytest.mark.django_db
def test_cancel_button_returns_without_saving(
    auto_login_user, famille_user, live_server, page: Page
):
    user, famille, ratt = famille_user
    enfant, activite, _unite, inscription, periode, _dates = _build_planning(
        famille, ratt
    )

    page = auto_login_user(user)
    page.goto(f"{live_server.url}/planning/{enfant.pk}/{activite.pk}/{periode.pk}")
    cases = page.locator("#table-grille td.case.ouvert")
    expect(cases.first).to_be_visible()
    cases.first.click()

    # The grid asks for confirmation (bootbox) when there are pending changes.
    page.locator("#annuler").click()
    dialog = page.locator(".bootbox")
    expect(dialog).to_contain_text("Fermer le planning")
    # "Non" keeps us on the planning page.
    dialog.get_by_role("button", name="Non, je veux rester").click()
    expect(dialog).to_have_count(0)
    assert "/planning/" in page.url
    page.locator("#annuler").click()
    page.get_by_role("button", name="Oui, je veux fermer").click()
    page.wait_for_url(f"{live_server.url}/reservations")
    assert not Consommation.objects.filter(inscription=inscription).exists()
