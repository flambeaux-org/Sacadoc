"""Director <-> family messaging (fiche famille > Messagerie) and the director's perimeter.

Product rules (confirmed):
- the "Messages" counter of the fiche famille shows the family's messages the staff
  has not read yet;
- a director only works within his own structures: he cannot open the fiche of a
  family that is only inscribed in other structures, nor read or post in another
  structure's conversation; the author and structure of a message are set server-side.
  A family with no inscription at all (e.g. just created) stays reachable.
"""

import datetime

import pytest
from core.models import Mail, PortailMessage, Utilisateur
from django.test import Client
from django.urls import reverse
from tests.unit.factories import (
    ActiviteFactory,
    InscriptionFactory,
    PortailMessageFactory,
    StructureFactory,
    UtilisateurFactory,
    create_famille_complete,
)


def _url_discussion(famille, structure):
    return reverse("famille_messagerie_portail", kwargs={"idfamille": famille.pk, "idstructure": structure.pk})


def _poster(client, famille, structure, texte="Bonjour", **overrides):
    data = {"famille": famille.pk, "structure": structure.pk,
            "utilisateur": client.session.get("_auth_user_id"), "texte": texte}
    data.update(overrides)
    return client.post(_url_discussion(famille, structure), data)


def _portail_client(famille):
    client = Client()
    client.force_login(Utilisateur.objects.get(pk=famille.utilisateur_id))
    return client


@pytest.fixture
def autre_structure(db):
    return StructureFactory(nom="Structure voisine")


@pytest.mark.django_db
class TestDiscussion:
    def test_seules_mes_structures_sont_proposees(self, directeur_client, famille_bureau, structure, autre_structure):
        famille, _t, _e = famille_bureau
        response = directeur_client.get(reverse("famille_messagerie_portail", args=[famille.pk]))
        assert list(response.context["liste_structures"]) == [structure]

    def test_envoyer_un_message_a_la_famille(self, directeur_client, directeur, famille_bureau, structure):
        famille, _t, _e = famille_bureau
        response = _poster(directeur_client, famille, structure, texte="Pensez au certificat médical")
        assert response.status_code == 302
        assert response["Location"] == _url_discussion(famille, structure)

        message = PortailMessage.objects.get(famille=famille)
        assert message.structure == structure
        assert message.utilisateur == directeur
        assert "certificat médical" in message.texte
        assert message.date_lecture is None

    def test_la_famille_lit_le_message_sur_le_portail(self, directeur_client, famille_bureau, structure):
        famille, _t, _e = famille_bureau
        _poster(directeur_client, famille, structure, texte="Réunion de rentrée samedi")

        response = _portail_client(famille).get(reverse("portail_messagerie", args=[structure.pk]))
        assert response.status_code == 200
        assert any("Réunion de rentrée" in m.texte for m in response.context["liste_messages"])
        # Opening the conversation marks the director's message as read
        assert PortailMessage.objects.get(famille=famille).date_lecture is not None

    def test_la_reponse_de_la_famille_apparait_dans_la_discussion(self, directeur_client, famille_bureau, structure):
        famille, _t, _e = famille_bureau
        reponse = PortailMessageFactory(famille=famille, structure=structure, texte="Bien reçu, merci")
        response = directeur_client.get(_url_discussion(famille, structure))
        assert reponse in response.context["liste_messages_discussion"]

    def test_pas_de_notification_email_si_desactivee(self, directeur_client, famille_bureau, structure):
        famille, _t, _e = famille_bureau
        _poster(directeur_client, famille, structure)
        assert not Mail.objects.filter(categorie="portail_notification_message").exists()

    def test_notification_sans_modele_signale_une_erreur(
        self, directeur_client, famille_bureau, structure, set_parametre_portail
    ):
        famille, _t, _e = famille_bureau
        set_parametre_portail("messagerie_envoyer_notification_famille", True)
        response = _poster(directeur_client, famille, structure, texte="Avec notification")
        messages = [str(m) for m in directeur_client.get(_url_discussion(famille, structure)).context["messages"]]
        assert response.status_code == 302
        assert any("Aucun modèle d'email" in m for m in messages)
        # The message itself is still delivered on the portal
        assert PortailMessage.objects.filter(famille=famille, texte__contains="Avec notification").exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: famille.Resume counts nbre_messages_non_lus with utilisateur__isnull=False, i.e. the "
        "staff's own messages the family has not read, instead of the family's messages the staff "
        "has not read (utilisateur__isnull=True), as the header notifications do."
    ))
    def test_compteur_messages_du_resume(self, directeur_client, directeur, famille_bureau, structure):
        famille, _t, _e = famille_bureau
        PortailMessageFactory(famille=famille, structure=structure, texte="Question 1")
        PortailMessageFactory(famille=famille, structure=structure, texte="Question 2")
        PortailMessageFactory(famille=famille, structure=structure, texte="Déjà lue",
                              date_lecture=datetime.datetime(2026, 1, 1))
        PortailMessageFactory(famille=famille, structure=structure, utilisateur=directeur, texte="Réponse")
        response = directeur_client.get(reverse("famille_resume", args=[famille.pk]))
        assert response.context["nbre_messages_non_lus"] == 2


@pytest.mark.django_db
class TestPerimetreMessagerie:
    @pytest.mark.xfail(strict=True, reason=(
        "BUG: famille_messagerie_portail lists the conversation of whatever idstructure is in the URL, "
        "including structures the director does not belong to."
    ))
    def test_lire_la_discussion_d_une_autre_structure_interdit(self, directeur_client, famille_bureau, autre_structure):
        famille, _t, _e = famille_bureau
        prive = PortailMessageFactory(famille=famille, structure=autre_structure, texte="Confidentiel")
        response = directeur_client.get(_url_discussion(famille, autre_structure))
        assert response.status_code in (403, 404) or prive not in response.context["liste_messages_discussion"]

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the 'structure' of a staff message comes from a hidden POST field and is not checked "
        "against the director's structures."
    ))
    def test_poster_au_nom_d_une_autre_structure_interdit(self, directeur_client, famille_bureau, autre_structure):
        famille, _t, _e = famille_bureau
        _poster(directeur_client, famille, autre_structure, texte="Usurpation")
        assert not PortailMessage.objects.filter(structure=autre_structure).exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the author ('utilisateur') of a staff message comes from a hidden POST field, so a "
        "director can post a message attributed to another staff member."
    ))
    def test_l_auteur_du_message_est_toujours_le_directeur(self, directeur_client, directeur, famille_bureau, structure):
        famille, _t, _e = famille_bureau
        collegue = UtilisateurFactory(username="collegue")
        _poster(directeur_client, famille, structure, texte="Signé par un autre", utilisateur=collegue.pk)
        assert PortailMessage.objects.get(famille=famille).utilisateur == directeur


@pytest.fixture
def famille_autre_structure(db, organisateur, autre_structure):
    """A family whose only inscription is on another structure's activity."""
    _user, famille, ratt = create_famille_complete(username="famille_voisine")
    InscriptionFactory(famille=famille, individu=ratt[1].individu,
                       activite=ActiviteFactory(structure=autre_structure),
                       date_debut=datetime.date(2020, 1, 1))
    return famille, ratt[1].individu


@pytest.mark.django_db
class TestPerimetreFiches:
    def test_famille_sans_inscription_accessible(self, directeur_client, organisateur):
        """A freshly created family (no inscription yet) must stay reachable by the director."""
        _user, famille, ratt = create_famille_complete(username="nouvelle")
        assert directeur_client.get(reverse("famille_resume", args=[famille.pk])).status_code == 200
        assert directeur_client.get(
            reverse("individu_resume", args=[famille.pk, ratt[1].individu.pk])
        ).status_code == 200

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: fiche famille pages only check the user category, not the perimeter: any director "
        "can open a family inscribed solely in another structure by changing the id in the URL."
    ))
    def test_fiche_famille_hors_perimetre_interdite(self, directeur_client, famille_autre_structure):
        famille, _enfant = famille_autre_structure
        assert directeur_client.get(reverse("famille_resume", args=[famille.pk])).status_code in (403, 404)

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: same as the fiche famille — the fiche individu of a family outside the director's "
        "structures (including medical data) is readable by URL."
    ))
    def test_fiche_individu_hors_perimetre_interdite(self, directeur_client, famille_autre_structure):
        famille, enfant = famille_autre_structure
        url = reverse("individu_medical_liste", args=[famille.pk, enfant.pk])
        assert directeur_client.get(url).status_code in (403, 404)

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the idfamille / idindividu pair is never checked: a fiche individu can be opened under "
        "any famille id, mixing one family's header with another family's member."
    ))
    def test_individu_d_une_autre_famille_refuse(self, directeur_client, famille_bureau, organisateur):
        famille, _t, _e = famille_bureau
        _user, autre, ratt = create_famille_complete(username="tierce")
        response = directeur_client.get(reverse("individu_resume", args=[famille.pk, ratt[1].individu.pk]))
        assert response.status_code in (403, 404)
