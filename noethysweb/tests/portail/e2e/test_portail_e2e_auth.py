"""E2E: login / logout / password-reset forms driven through a real browser."""

import re

import pytest
from playwright.sync_api import Page, expect
from tests.unit.factories import AdresseMailFactory


@pytest.mark.django_db
def test_login_good_credentials(famille_user, live_server, page: Page):
    user, _famille, _ratt = famille_user
    page.goto(f"{live_server.url}/connexion")

    page.get_by_placeholder("Identifiant").fill(user.username)
    page.get_by_placeholder("Mot de passe").fill("testpassword")
    page.get_by_role("button", name="Se connecter").click()

    expect(page).to_have_url(f"{live_server.url}/")
    expect(page.locator(".main-sidebar")).to_be_visible()


@pytest.mark.django_db
def test_login_bad_password_shows_error(famille_user, live_server, page: Page):
    user, _famille, _ratt = famille_user
    page.goto(f"{live_server.url}/connexion")

    page.get_by_placeholder("Identifiant").fill(user.username)
    page.get_by_placeholder("Mot de passe").fill("mauvais-mot-de-passe")
    page.get_by_role("button", name="Se connecter").click()

    expect(page).to_have_url(f"{live_server.url}/connexion")
    expect(page.locator(".alert-danger")).to_be_visible()
    expect(page.locator(".alert-danger")).to_contain_text(
        "Saisissez un nom d’utilisateur"
    )


@pytest.mark.django_db
def test_login_unknown_user_shows_error(organisateur, live_server, page: Page):
    page.goto(f"{live_server.url}/connexion")
    page.get_by_placeholder("Identifiant").fill("personne")
    page.get_by_placeholder("Mot de passe").fill("xxx")
    page.get_by_role("button", name="Se connecter").click()
    expect(page.locator(".alert-danger")).to_be_visible()


@pytest.mark.django_db
def test_protected_page_redirects_anonymous_to_login(
    organisateur, live_server, page: Page
):
    page.goto(f"{live_server.url}/renseignements")
    expect(page).to_have_url(re.compile(r"/connexion"))
    expect(page.get_by_role("button", name="Se connecter")).to_be_visible()


@pytest.mark.django_db
def test_logout_via_ui(auto_login_user, famille_user, live_server, page: Page):
    user, _famille, _ratt = famille_user
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/")

    page.locator("a.btn-deconnexion").click()
    expect(page).to_have_url(f"{live_server.url}/connexion")

    # Session is gone: a protected page now bounces back to the login form.
    page.goto(f"{live_server.url}/renseignements")
    expect(page).to_have_url(re.compile(r"/connexion"))


@pytest.mark.django_db
def test_forgot_password_link_hidden_without_sender(
    organisateur, live_server, page: Page
):
    page.goto(f"{live_server.url}/connexion")
    expect(page.get_by_role("link", name="Mot de passe oublié")).to_have_count(0)


@pytest.mark.django_db
def test_password_reset_request_submission(
    famille_user, set_parametre_portail, live_server, page: Page, mailoutbox
):
    user, _famille, ratt = famille_user
    titulaire = ratt[0].individu
    titulaire.mail = "parent@test.org"
    titulaire.save()
    adresse = AdresseMailFactory()
    set_parametre_portail("connexion_adresse_exp", adresse.pk)

    page.goto(f"{live_server.url}/connexion")
    page.get_by_role("link", name="Mot de passe oublié").click()
    expect(page).to_have_url(f"{live_server.url}/reset_password/")

    page.locator("#id_identifiant").fill(user.username)
    page.locator("#id_email").fill("parent@test.org")
    page.get_by_role("button", name="Envoyer").click()

    expect(page).to_have_url(f"{live_server.url}/reset_password_sent/")


@pytest.mark.django_db
def test_password_reset_request_unknown_identifiant(
    organisateur, set_parametre_portail, live_server, page: Page
):
    adresse = AdresseMailFactory()
    set_parametre_portail("connexion_adresse_exp", adresse.pk)

    page.goto(f"{live_server.url}/reset_password/")
    page.locator("#id_identifiant").fill("inconnu")
    page.locator("#id_email").fill("x@test.org")
    page.get_by_role("button", name="Envoyer").click()

    expect(page.locator(".alert-danger")).to_contain_text(
        "Il n'existe pas de compte actif"
    )


@pytest.mark.django_db
def test_password_reset_request_wrong_email(
    famille_user, set_parametre_portail, live_server, page: Page
):
    user, _famille, _ratt = famille_user
    adresse = AdresseMailFactory()
    set_parametre_portail("connexion_adresse_exp", adresse.pk)

    page.goto(f"{live_server.url}/reset_password/")
    page.locator("#id_identifiant").fill(user.username)
    page.locator("#id_email").fill("autre@test.org")
    page.get_by_role("button", name="Envoyer").click()

    expect(page.locator(".alert-danger")).to_contain_text("Adresse email non valide")
