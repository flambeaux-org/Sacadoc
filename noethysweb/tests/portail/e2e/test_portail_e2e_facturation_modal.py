"""E2E: facturation page - detail facture modal (get_detail_facture AJAX)."""

import datetime

import pytest
from core.models import Prestation
from playwright.sync_api import Page, expect
from tests.unit.factories import FactureFactory


@pytest.fixture
def facture_avec_prestation(famille_user, set_parametre_portail):
    _user, famille, ratt = famille_user
    # Known bug #6: /facturation 500s unless this parameter is enabled.
    set_parametre_portail("facturation_afficher_solde_famille", True)
    set_parametre_portail("facturation_autoriser_detail_facture", True)
    facture = FactureFactory(famille=famille, total=120, solde_actuel=120)
    Prestation.objects.create(
        date=datetime.date(2024, 3, 5),
        label="Prestation E2E",
        montant=120,
        montant_initial=120,
        famille=famille,
        individu=ratt[1].individu,
        facture=facture,
    )
    return facture


@pytest.mark.django_db
def test_detail_facture_modal_opens(
    auto_login_user, famille_user, facture_avec_prestation, live_server, page: Page
):
    user, _famille, _ratt = famille_user
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/facturation")

    modal = page.locator("#modal_detail_facture")
    expect(modal).not_to_be_visible()
    page.locator(".bouton_detail_facture").first.click()

    expect(modal).to_be_visible()
    expect(modal.locator("#table-prestations")).to_contain_text("Prestation E2E")
    expect(modal).to_contain_text("Total de la facture")

    modal.get_by_role("button", name="Close").or_(
        modal.locator("button.close")
    ).first.click()
    expect(modal).not_to_be_visible()
    assert not errors, errors


@pytest.mark.django_db
def test_detail_button_hidden_when_not_allowed(
    auto_login_user, famille_user, set_parametre_portail, live_server, page: Page
):
    user, famille, _ratt = famille_user
    set_parametre_portail("facturation_afficher_solde_famille", True)
    set_parametre_portail("facturation_autoriser_detail_facture", False)
    FactureFactory(famille=famille, total=50, solde_actuel=50)
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/facturation")
    expect(page.locator(".bouton_detail_facture")).to_have_count(0)
    assert "Traceback" not in page.locator("body").inner_text()


@pytest.mark.django_db
def test_detail_of_other_famille_facture_is_refused(
    auto_login_user,
    famille_user,
    other_famille,
    set_parametre_portail,
    live_server,
    page: Page,
):
    """The AJAX endpoint must refuse a facture of another family (called from the browser session)."""
    user, _famille, _ratt = famille_user
    set_parametre_portail("facturation_afficher_solde_famille", True)
    autre = FactureFactory(famille=other_famille[1], total=10, solde_actuel=10)
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/facturation")
    token = next(c["value"] for c in page.context.cookies() if c["name"] == "csrftoken")
    status = page.evaluate(
        """async ([id, token]) => {
            const r = await fetch('/facturation/get_detail_facture', {
                method: 'POST',
                headers: {'X-Requested-With': 'XMLHttpRequest', 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': token},
                body: 'idfacture=' + id,
            });
            return r.status;
        }""",
        [autre.pk, token],
    )
    assert status == 401
