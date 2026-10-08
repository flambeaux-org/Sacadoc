"""E2E: a family adds a child through the portal form in a real browser."""

import pytest
from playwright.sync_api import Page, expect

from core.models import Individu


@pytest.mark.django_db
def test_add_child_flow(auto_login_user, famille_user, live_server, page: Page):
    user, famille, _ratt = famille_user
    page = auto_login_user(user)

    page.goto(f"{live_server.url}/individu/ajouter/")

    page.locator("#id_prenom").fill("Lucie")
    page.locator("#id_nom").fill("Browser")
    page.locator("#id_date_naiss").fill("2017-03-04")
    page.get_by_role("button", name="Enregistrer").click()

    # Redirects to the renseignements page on success.
    expect(page).to_have_url(f"{live_server.url}/renseignements")
    assert Individu.objects.filter(prenom="Lucie", nom="Browser").exists()
