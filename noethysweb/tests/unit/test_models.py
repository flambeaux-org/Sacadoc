import pytest
from tests.unit.factories import (
    AdresseMailFactory,
    OrganisateurFactory,
    StructureFactory,
    UtilisateurFactory,
)


@pytest.mark.django_db
class TestAdresseMailModel:
    def test_str(self):
        adresse = AdresseMailFactory(adresse="contact@flbx.fr")
        assert "contact@flbx.fr" in str(adresse)

    def test_default_actif(self):
        adresse = AdresseMailFactory()
        assert adresse.actif is True

    def test_moteur_console(self):
        adresse = AdresseMailFactory(moteur="console")
        assert adresse.moteur == "console"


@pytest.mark.django_db
class TestOrganisateurModel:
    def test_str_returns_nom(self):
        orga = OrganisateurFactory(nom="FLBX")
        assert str(orga) == "FLBX"

    def test_create_minimal(self):
        orga = OrganisateurFactory()
        assert orga.pk is not None


@pytest.mark.django_db
class TestStructureModel:
    def test_str_returns_nom(self):
        structure = StructureFactory(nom="Groupe Etoile")
        assert "Groupe Etoile" in str(structure)

    def test_actif_manager_excludes_inactive(self):
        from core.models import Structure

        active = StructureFactory(nom="Active", actif=True)
        inactive = StructureFactory(nom="Inactive", actif=False)

        # Default manager (ActifManagerStruct) only returns actif=True
        pks = list(Structure.objects.values_list("pk", flat=True))
        assert active.pk in pks
        assert inactive.pk not in pks

    def test_objects_all_includes_inactive(self):
        from core.models import Structure

        active = StructureFactory(nom="Active", actif=True)
        inactive = StructureFactory(nom="Inactive", actif=False)

        pks = list(Structure.objects_all.values_list("pk", flat=True))
        assert active.pk in pks
        assert inactive.pk in pks


@pytest.mark.django_db
class TestUtilisateurModel:
    def test_create_superuser(self):
        from core.models import Utilisateur

        user = Utilisateur.objects.create_superuser(
            username="admin", password="secret", email="admin@test.org"
        )
        assert user.is_superuser is True
        assert user.is_staff is True
        assert user.check_password("secret")

    def test_factory_creates_user(self):
        user = UtilisateurFactory()
        assert user.pk is not None
        assert user.categorie == "utilisateur"

    def test_password_check(self):
        user = UtilisateurFactory()
        assert user.check_password("testpassword")
