"""E2E: a family edits a child's identity through the portal in a real browser."""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.django_db
def test_edit_child_identity(auto_login_user, famille_user, live_server, page: Page):
    user, _famille, ratt = famille_user
    enfant = ratt[1].individu
    page = auto_login_user(user)

    page.goto(
        f"{live_server.url}/renseignements/individu/identite/modifier/{ratt[1].pk}"
    )
    page.locator("#id_nom").fill("NomModifieBrowser")
    page.get_by_role("button", name="Enregistrer").click()

    # Leaves the edit form (validation_auto=True persists the change directly).
    expect(page).not_to_have_url(
        f"{live_server.url}/renseignements/individu/identite/modifier/{ratt[1].pk}"
    )
    enfant.refresh_from_db()
    assert enfant.nom == "NomModifieBrowser"
