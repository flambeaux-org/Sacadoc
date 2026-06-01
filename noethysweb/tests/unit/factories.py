import datetime

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


class FamilleUtilisateurFactory(DjangoModelFactory):
    """Creates a portail (family) user with password 'testpassword'."""

    class Meta:
        model = "core.Utilisateur"

    username = factory.Sequence(lambda n: f"famille{n}")
    password = factory.LazyFunction(lambda: make_password("testpassword"))
    email = factory.Sequence(lambda n: f"famille{n}@test.org")
    categorie = "famille"
    is_staff = False
    is_superuser = False


class FamilleFactory(DjangoModelFactory):
    """Creates a Famille. Pass utilisateur=... to link it to a portail user."""

    class Meta:
        model = "core.Famille"

    nom = factory.Sequence(lambda n: f"Famille {n}")


class IndividuFactory(DjangoModelFactory):
    """Creates an Individu (a person — parent, child or contact)."""

    class Meta:
        model = "core.Individu"

    nom = factory.Sequence(lambda n: f"Nom{n}")
    prenom = factory.Sequence(lambda n: f"Prenom{n}")
    date_naiss = datetime.date(2015, 1, 1)


class RattachementFactory(DjangoModelFactory):
    """Links an Individu to a Famille. categorie: 1=adulte, 2=enfant, 3=contact."""

    class Meta:
        model = "core.Rattachement"

    individu = factory.SubFactory(IndividuFactory)
    famille = factory.SubFactory(FamilleFactory)
    categorie = 2  # CATEGORIE_RATTACHEMENT_ENFANT
    titulaire = False


class ActiviteFactory(DjangoModelFactory):
    class Meta:
        model = "core.Activite"

    nom = factory.Sequence(lambda n: f"Activite {n}")
    abrege = factory.Sequence(lambda n: f"Act{n}")
    structure = factory.SubFactory(StructureFactory)
    visible = True
    portail_inscriptions_affichage = "TOUJOURS"
    portail_reservations_affichage = "TOUJOURS"


class GroupeFactory(DjangoModelFactory):
    class Meta:
        model = "core.Groupe"

    activite = factory.SubFactory(ActiviteFactory)
    nom = factory.Sequence(lambda n: f"Groupe {n}")
    ordre = factory.Sequence(lambda n: n + 1)


class InscriptionFactory(DjangoModelFactory):
    class Meta:
        model = "core.Inscription"

    individu = factory.SubFactory(IndividuFactory)
    famille = factory.SubFactory(FamilleFactory)
    activite = factory.SubFactory(ActiviteFactory)
    groupe = factory.SubFactory(
        GroupeFactory, activite=factory.SelfAttribute("..activite")
    )
    date_debut = datetime.date(2020, 1, 1)
    statut = "ok"


class TypePieceFactory(DjangoModelFactory):
    class Meta:
        model = "core.TypePiece"

    nom = factory.Sequence(lambda n: f"Type piece {n}")


class PieceFactory(DjangoModelFactory):
    class Meta:
        model = "core.Piece"

    type_piece = factory.SubFactory(TypePieceFactory)
    famille = factory.SubFactory(FamilleFactory)
    titre = factory.Sequence(lambda n: f"Piece {n}")


class PortailMessageFactory(DjangoModelFactory):
    """A message in the family <-> structure conversation.

    Pass utilisateur=<staff user> to simulate a staff-sent (incoming) message;
    leave it None for a family-sent message.
    """

    class Meta:
        model = "core.PortailMessage"

    famille = factory.SubFactory(FamilleFactory)
    structure = factory.SubFactory(StructureFactory)
    texte = factory.Sequence(lambda n: f"Message {n}")


class SondageFactory(DjangoModelFactory):
    class Meta:
        model = "core.Sondage"

    titre = factory.Sequence(lambda n: f"Sondage {n}")
    public = "famille"


class FactureFactory(DjangoModelFactory):
    class Meta:
        model = "core.Facture"

    numero = factory.Sequence(lambda n: 1000 + n)
    famille = factory.SubFactory(FamilleFactory)
    date_edition = datetime.date(2024, 1, 1)
    date_debut = datetime.date(2024, 1, 1)
    date_fin = datetime.date(2024, 12, 31)
    total = 100
    solde_actuel = 100


def create_famille_user(username="famille", password="testpassword"):
    """Create a portail user linked to a Famille and return (utilisateur, famille).

    A famille user must have a linked Famille or portail pages raise — see
    portail/views/base.py::CustomView.get_context_data.
    """
    user = FamilleUtilisateurFactory(
        username=username, password=make_password(password)
    )
    famille = FamilleFactory(utilisateur=user)
    return user, famille


def create_famille_complete(username="famille", password="testpassword", avec_enfant=True):
    """Create a fully usable portail family and return (user, famille, rattachements).

    Builds the Famille + a titulaire adult Individu (set as `allocataire`) and,
    by default, one child. Most portail pages iterate on rattachements, so an
    empty famille is not enough to exercise them.
    """
    user, famille = create_famille_user(username=username, password=password)

    titulaire = IndividuFactory(nom="Titulaire", prenom="Adulte", date_naiss=datetime.date(1985, 1, 1))
    rattachements = [
        RattachementFactory(individu=titulaire, famille=famille, categorie=1, titulaire=True)
    ]
    famille.allocataire = titulaire
    famille.save()

    if avec_enfant:
        enfant = IndividuFactory(nom="Enfant", prenom="Premier")
        rattachements.append(
            RattachementFactory(individu=enfant, famille=famille, categorie=2)
        )

    return user, famille, rattachements
