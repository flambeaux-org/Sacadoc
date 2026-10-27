"""E2E: a family uploads a document (file input) through the portal."""

import base64

import pytest
from playwright.sync_api import Page, expect

from core.models import Piece

# 1x1 transparent PNG.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


@pytest.mark.django_db
def test_upload_document_flow(auto_login_user, famille_user, live_server, page: Page):
    user, famille, _ratt = famille_user
    page = auto_login_user(user)

    page.goto(f"{live_server.url}/documents/transmettre")

    # With no missing pieces, the only choice is "Un autre type de pièce" (value 9999),
    # which reveals the titre field via the page's change handler.
    page.select_option("#id_selection_piece", "9999")
    page.fill("#id_titre", "Certificat E2E")
    page.set_input_files(
        "#id_document",
        files=[{"name": "justif.png", "mimeType": "image/png", "buffer": PNG_BYTES}],
    )
    page.get_by_role("button", name="Envoyer").click()

    expect(page).to_have_url(f"{live_server.url}/renseignements")
    assert Piece.objects.filter(famille=famille, titre="Certificat E2E").exists()
