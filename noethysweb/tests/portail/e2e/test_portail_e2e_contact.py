"""E2E: contact page - conversations, unread messages marked as read."""

import re

import pytest
from core.models import PortailMessage
from playwright.sync_api import Page, expect
from tests.unit.factories import (
    ActiviteFactory,
    InscriptionFactory,
    PortailMessageFactory,
    StructureFactory,
    UtilisateurFactory,
)


@pytest.fixture
def conversation(famille_user, db):
    _user, famille, ratt = famille_user
    structure = StructureFactory(nom="Structure Contact", visible=True)
    activite = ActiviteFactory(structure=structure)
    InscriptionFactory(famille=famille, individu=ratt[1].individu, activite=activite)
    staff = UtilisateurFactory(username="staff_contact")
    message = PortailMessageFactory(
        famille=famille,
        structure=structure,
        utilisateur=staff,
        texte="Bonjour de la structure",
    )
    return structure, message


@pytest.mark.django_db
def test_unread_message_listed_and_marked_read_on_open(
    auto_login_user, famille_user, conversation, live_server, page: Page
):
    user, _famille, _ratt = famille_user
    structure, message = conversation
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/contact")

    # Header badge + "Messages non lus" box show the unread message.
    expect(page.locator(".navbar-badge")).to_have_text("1")
    unread = page.locator(".message-box", has_text="Structure Contact")
    expect(unread.first).to_be_visible()
    assert PortailMessage.objects.get(pk=message.pk).date_lecture is None

    unread.first.get_by_role("link").click()
    expect(page).to_have_url(f"{live_server.url}/contact/{structure.pk}")
    expect(page.get_by_text("Discussion avec 'Structure Contact'")).to_be_visible()
    expect(page.locator("#div_messages")).to_contain_text("Bonjour de la structure")
    assert PortailMessage.objects.get(pk=message.pk).date_lecture is not None

    # After a reload nothing is unread anymore.
    page.goto(f"{live_server.url}/contact")
    expect(page.locator(".navbar-badge")).to_have_count(0)
    expect(page.get_by_text("Aucun message non lu")).to_be_visible()


@pytest.mark.django_db
def test_new_conversation_modal_links_to_messagerie(
    auto_login_user, famille_user, live_server, page: Page
):
    user, _famille, _ratt = famille_user
    structure = StructureFactory(nom="Structure Nouvelle", visible=True)
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/contact")

    page.get_by_role("button", name="Nouvelle conversation").click()
    lien = page.locator("#lienNouvelleConversation")
    expect(lien).to_be_visible()
    expect(lien).to_have_class(re.compile("disabled"))

    page.select_option("#selectStructure", str(structure.pk))
    expect(lien).not_to_have_class(re.compile("disabled"))
    lien.click()
    expect(page).to_have_url(f"{live_server.url}/contact/messagerie/{structure.pk}")


@pytest.mark.django_db
def test_reply_from_conversation(
    auto_login_user, famille_user, conversation, live_server, page: Page
):
    user, famille, _ratt = famille_user
    structure, _message = conversation
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/contact/{structure.pk}")

    page.get_by_role("link", name="Répondre").click()
    expect(page).to_have_url(f"{live_server.url}/contact/messagerie/{structure.pk}")
    page.locator(".note-editable").click()
    page.keyboard.type("Reponse E2E")
    page.get_by_role("button", name="Envoyer").click()
    page.wait_for_url(f"{live_server.url}/contact/messagerie/{structure.pk}")

    assert PortailMessage.objects.filter(
        famille=famille,
        structure=structure,
        utilisateur__isnull=True,
        texte__contains="Reponse E2E",
    ).exists()


@pytest.mark.django_db
def test_messagerie_page_marks_unread_and_shows_badge_once(
    auto_login_user, famille_user, conversation, live_server, page: Page
):
    user, _famille, _ratt = famille_user
    structure, message = conversation
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/contact/messagerie/{structure.pk}")

    expect(page.locator("#div_messages")).to_contain_text("Bonjour de la structure")
    expect(page.locator(".badge", has_text="Nouveau").first).to_be_visible()
    assert PortailMessage.objects.get(pk=message.pk).date_lecture is not None
