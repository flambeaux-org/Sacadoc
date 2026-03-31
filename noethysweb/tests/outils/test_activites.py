import pytest
from playwright.sync_api import expect

from core.models import Structure, Activite


@pytest.mark.django_db
class TestActivites:
    @pytest.fixture(autouse=True)
    def setup_data(self, db):
        # db fixture is required so ORM access is allowed inside the fixture
        self.structure = Structure.objects.create(nom="Structure de test")

    def test_create_activite(self, auto_login_user, admin_user, live_server):
        page = auto_login_user(admin_user)

        page.goto(f"{live_server.url}/utilisateur/parametrage/activites/ajouter")

        page.get_by_label("Structure").select_option(str(self.structure.idstructure))
        page.get_by_label("Nom").fill("Activité de test")
        page.get_by_role("button", name="Enregistrer").click()

        activite = Activite.objects.get(
            nom="Activité de test", structure=self.structure
        )

        assert (
            "/utilisateur/parametrage/activites/resume/" + str(activite.idactivite)
            in page.url
        )
        expect(page.get_by_role("heading", name=activite.nom)).to_be_visible()

    def test_modify_activite(self, auto_login_user, admin_user, live_server):
        page = auto_login_user(admin_user)

        activite = Activite.objects.create(
            nom="Activité de test", structure=self.structure
        )

        page.goto(
            f"{live_server.url}/utilisateur/parametrage/activites/generalites/modifier/{activite.idactivite}"
        )

        new_name = "Activité modifiée"
        page.get_by_label("Nom*").fill(new_name)
        page.get_by_role("button", name="Enregistrer").click()

        activite.refresh_from_db()
        assert activite.nom == new_name
        expect(page.get_by_role("heading", name=new_name)).to_be_visible()
