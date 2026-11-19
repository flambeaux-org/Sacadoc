"""E2E: sidebar entries, interface options and mobile viewport rendering."""

import re

import pytest
from playwright.sync_api import Page, expect

MENU_PARAMS = [
    "renseignements_afficher_page",
    "cotisations_afficher_page",
    "activites_afficher_page",
    "reservations_afficher_page",
    "facturation_afficher_page",
    "contact_afficher_page",
    "mentions_afficher_page",
]

MAIN_PAGES = [
    "/",
    "/renseignements",
    "/cotisations",
    "/activites",
    "/activites/inscrire",
    "/reservations",
    "/documents",
    "/facturation",
    "/reglements",
    "/contact",
    "/mentions",
    "/profil",
    "/sondages",
]

# Third-party CDN assets may be unreachable in CI: not an application error.
IGNORED_CONSOLE = ("cloudflare", "googleapis", "gstatic", "net::ERR", "favicon")


@pytest.fixture
def full_menu(set_parametre_portail):
    for code in MENU_PARAMS:
        set_parametre_portail(code, True)
    # Known bug #6: /facturation 500s unless this parameter is enabled.
    set_parametre_portail("facturation_afficher_solde_famille", True)


def _collect_errors(page):
    errors = []
    page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
    page.on(
        "console",
        lambda m: (
            errors.append(f"console: {m.text}")
            if m.type == "error" and not any(i in m.text for i in IGNORED_CONSOLE)
            else None
        ),
    )
    page.on(
        "response",
        lambda r: (
            errors.append(f"{r.status} {r.url}")
            if r.status >= 500 and "localhost" in r.url
            else None
        ),
    )
    return errors


@pytest.mark.django_db
def test_every_sidebar_entry_loads(
    auto_login_user, famille_user, full_menu, live_server, page: Page
):
    user, _famille, _ratt = famille_user
    errors = _collect_errors(page)
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/")

    links = page.locator(".nav-sidebar a.nav-link")
    expect(links).to_have_count(len(MENU_PARAMS) + 1)
    hrefs = [links.nth(i).get_attribute("href") for i in range(links.count())]
    titres = [links.nth(i).inner_text().strip() for i in range(links.count())]
    assert titres == [
        "Accueil",
        "Renseignements",
        "Adhésions",
        "Inscriptions",
        "Réservations",
        "Finances",
        "Messagerie",
        "Mentions légales",
    ]

    for href, titre in zip(hrefs, titres):
        page.goto(f"{live_server.url}/")
        page.locator(f".nav-sidebar a.nav-link[href='{href}']").click()
        expect(page).to_have_url(re.compile(re.escape(href) + r"/?$"))
        assert "Server Error" not in page.title(), titre
        assert "Traceback" not in page.locator("body").inner_text(), titre
        # The clicked entry is highlighted as the active one.
        expect(page.locator(".nav-sidebar a.nav-link.active")).to_have_count(1)
    assert not errors, errors


@pytest.mark.django_db
def test_sidebar_hidden_entries_follow_parameters(
    auto_login_user, famille_user, set_parametre_portail, live_server, page: Page
):
    user, _famille, _ratt = famille_user
    set_parametre_portail("mentions_afficher_page", False)
    set_parametre_portail("contact_afficher_page", False)
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/")
    sidebar = page.locator(".main-sidebar")
    expect(sidebar.get_by_role("link", name="Mentions légales")).to_have_count(0)
    expect(sidebar.get_by_role("link", name="Messagerie")).to_have_count(0)
    expect(sidebar.get_by_role("link", name="Accueil")).to_have_count(1)


@pytest.mark.django_db
def test_pushmenu_collapses_sidebar(
    auto_login_user, famille_user, live_server, page: Page
):
    user, _famille, _ratt = famille_user
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/")
    body = page.locator("body")
    toggle = page.locator("a[data-widget='pushmenu']")
    was_collapsed = "sidebar-collapse" in (body.get_attribute("class") or "")
    toggle.click()
    if was_collapsed:
        expect(body).not_to_have_class(re.compile("sidebar-collapse"))
    else:
        expect(body).to_have_class(re.compile("sidebar-collapse"))


@pytest.mark.django_db
def test_header_user_dropdown_links_to_profile(
    auto_login_user, famille_user, live_server, page: Page
):
    user, _famille, _ratt = famille_user
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/")
    page.locator(".user-menu > a").click()
    page.get_by_role("link", name="Paramètres").click()
    expect(page).to_have_url(f"{live_server.url}/profil")


@pytest.mark.django_db
@pytest.mark.xfail(
    reason="BUG: core/templates/core/control-sidebar.html posts to ajax_memorise_option "
    "(core/urls.py:32, wrapped in @secure_ajax = utilisateur only), so a famille user gets 403 "
    "and the option is never persisted; it should use a secure_ajax_portail endpoint. "
    "(The panel also has no opener in portail/header.html.)",
    strict=True,
)
def test_dark_mode_option_is_persisted(
    auto_login_user, famille_user, live_server, page: Page
):
    """The control-sidebar has no opener in the portail header: the checkbox is clicked via JS
    (what the checkbox handler does once the panel is open)."""
    user, _famille, _ratt = famille_user
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/")
    expect(page.locator("body")).not_to_have_class(re.compile("dark-mode"))

    with page.expect_response(lambda r: "memorise_option" in r.url) as info:
        page.locator("#check_dark_mode").evaluate("el => el.click()")
    assert info.value.status == 200
    expect(page.locator("body")).to_have_class(re.compile("dark-mode"))

    page.reload()
    expect(page.locator("body")).to_have_class(re.compile("dark-mode"))


@pytest.mark.django_db
@pytest.mark.parametrize("path", MAIN_PAGES)
def test_mobile_viewport_has_no_errors(
    auto_login_user, famille_user, full_menu, live_server, page: Page, path
):
    user, _famille, _ratt = famille_user
    errors = _collect_errors(page)
    page.set_viewport_size({"width": 375, "height": 667})
    page = auto_login_user(user)
    page.goto(f"{live_server.url}{path}")
    page.wait_for_load_state("networkidle")

    assert "Server Error" not in page.title()
    assert "Traceback" not in page.locator("body").inner_text()
    expect(page.locator(".main-header")).to_be_visible()
    assert not errors, errors


@pytest.mark.django_db
def test_mobile_sidebar_opens_with_burger(
    auto_login_user, famille_user, full_menu, live_server, page: Page
):
    user, _famille, _ratt = famille_user
    page.set_viewport_size({"width": 375, "height": 667})
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/")
    page.locator("a[data-widget='pushmenu']").click()
    expect(page.locator("body")).to_have_class(re.compile("sidebar-open"))
    page.locator(".nav-sidebar a.nav-link", has_text="Renseignements").click()
    expect(page).to_have_url(f"{live_server.url}/renseignements")
