
import pytest
from playwright.sync_api import Page

from core.models import Utilisateur, AdresseMail, Organisateur


@pytest.mark.django_db
def test_user_register_with_fixture(page: Page, live_server):
    page.goto(f"{live_server.url}/inscription_famille")

    email = "test@test.org"

    previous = Utilisateur.objects.count()

    AdresseMail.objects.create(adresse="test1@test.org")
    Organisateur.objects.create()

    # Use the user from the fixture
    page.get_by_role("textbox", name="Nom", exact=True).fill("Test")
    page.get_by_role("textbox", name="Prénom", exact=True).fill("Test")
    page.get_by_role("textbox", name="Email personnel").fill(email)
    page.get_by_role("textbox", name="Nouveau mot de passe", exact=True).fill("SuperMotDePasse123987")
    page.get_by_role("textbox", name="Confirmation du nouveau mot de passe", exact=True).fill("SuperMotDePasse123987")
    page.get_by_role("button", name="Envoyer").click()

    new = Utilisateur.objects.count()

    assert previous < new
