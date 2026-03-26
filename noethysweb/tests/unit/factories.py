import factory
from django.contrib.auth.hashers import make_password
from factory.django import DjangoModelFactory


class AdresseMailFactory(DjangoModelFactory):
    class Meta:
        model = "core.AdresseMail"

    adresse = factory.Sequence(lambda n: f"adresse{n}@test.org")
    moteur = "console"


class StructureFactory(DjangoModelFactory):
    class Meta:
        model = "core.Structure"

    nom = factory.Sequence(lambda n: f"Structure {n}")
    actif = True


class OrganisateurFactory(DjangoModelFactory):
    class Meta:
        model = "core.Organisateur"

    nom = factory.Sequence(lambda n: f"Organisateur {n}")


class UtilisateurFactory(DjangoModelFactory):
    """Creates a staff superuser with password 'testpassword'."""

    class Meta:
        model = "core.Utilisateur"

    username = factory.Sequence(lambda n: f"user{n}")
    # Pre-hash the password so no post-generation save is needed.
    password = factory.LazyFunction(lambda: make_password("testpassword"))
    email = factory.Sequence(lambda n: f"user{n}@test.org")
    categorie = "utilisateur"
    is_staff = True
    is_superuser = True
