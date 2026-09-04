"""E2E: a logged-in family can reach the main portal pages in a real browser."""

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.django_db
def test_dashboard_and_navigation(auto_login_user, famille_user, live_server, page: Page):
    user, _famille, _ratt = famille_user
    page = auto_login_user(user)

    # Dashboard loads.
    page.goto(f"{live_server.url}/")
    expect(page).to_have_url(f"{live_server.url}/")

    # The main pages render without error in the browser.
    for path in ["/renseignements", "/activites", "/documents", "/facturation", "/contact"]:
        page.goto(f"{live_server.url}{path}")
        # No Django error page — the debug 500 page has "Traceback" / "Server Error".
        assert "Server Error" not in page.title()
        body = page.locator("body").inner_text()
        assert "Traceback" not in body
