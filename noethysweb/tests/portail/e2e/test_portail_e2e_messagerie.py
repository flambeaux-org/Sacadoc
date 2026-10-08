"""E2E: a family posts a message to a structure (summernote editor)."""

import pytest
from playwright.sync_api import Page

from core.models import PortailMessage
from tests.unit.factories import StructureFactory


@pytest.mark.django_db
def test_send_message_flow(auto_login_user, famille_user, live_server, page: Page):
    user, famille, _ratt = famille_user
    structure = StructureFactory()
    page = auto_login_user(user)

    page.goto(f"{live_server.url}/contact/messagerie/{structure.pk}")

    # django-summernote renders a contenteditable .note-editable area.
    editor = page.locator(".note-editable")
    editor.click()
    page.keyboard.type("Bonjour depuis le navigateur")

    page.get_by_role("button", name="Envoyer").click()

    # Redirects back to the conversation; the message is persisted.
    page.wait_for_url(f"{live_server.url}/contact/messagerie/{structure.pk}")
    msg = PortailMessage.objects.get(famille=famille, structure=structure)
    assert "Bonjour depuis le navigateur" in msg.texte
