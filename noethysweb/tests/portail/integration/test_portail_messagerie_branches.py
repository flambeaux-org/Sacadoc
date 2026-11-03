"""Branch coverage for portail contact hub, conversation page and messagerie form."""

import datetime
from unittest import mock

import pytest
from core.models import Historique, PortailMessage
from django.urls import reverse
from tests.unit.factories import (
    ActiviteFactory,
    AdresseMailFactory,
    InscriptionFactory,
    PortailMessageFactory,
    StructureFactory,
)


def contact_url(idstructure=None):
    if idstructure is None:
        return reverse("portail_contact")
    return reverse("portail_contact_conversation", kwargs={"idstructure": idstructure})


def messagerie_url(idstructure):
    return reverse("portail_messagerie", kwargs={"idstructure": idstructure})


@pytest.mark.django_db
class TestContactHub:
    def test_anonymous_redirected_to_connexion(self, client, organisateur):
        response = client.get(contact_url())
        assert response.status_code == 302
        assert response.url == reverse("portail_connexion")

    def test_staff_forbidden(self, client, staff_user, organisateur):
        client.force_login(staff_user)
        assert client.get(contact_url()).status_code == 403

    def test_hub_without_structure_has_empty_discussion(self, logged_client):
        response = logged_client.get(contact_url())
        assert response.context["liste_messages_discussion"] == []
        assert "structure" not in response.context
        assert response.context["liste_structures_messagerie"] == []

    def test_structures_come_from_family_inscriptions(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        with_inscription = StructureFactory(nom="Avec")
        without_inscription = StructureFactory(nom="Sans")
        InscriptionFactory(
            famille=famille,
            individu=ratt[1].individu,
            activite=ActiviteFactory(structure=with_inscription),
        )
        ActiviteFactory(structure=without_inscription)
        response = logged_client.get(contact_url())
        assert response.context["liste_structures_messagerie"] == [with_inscription]

    def test_other_family_inscription_not_listed(self, logged_client, other_famille):
        _u, famille_b, ratt_b = other_famille
        InscriptionFactory(
            famille=famille_b,
            individu=ratt_b[1].individu,
            activite=ActiviteFactory(structure=StructureFactory()),
        )
        assert (
            logged_client.get(contact_url()).context["liste_structures_messagerie"]
            == []
        )

    def test_structures_coords_only_when_afficher_coords(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        visible = StructureFactory(nom="A", afficher_coords=True)
        hidden = StructureFactory(nom="B", afficher_coords=False)
        for s in (visible, hidden):
            InscriptionFactory(
                famille=famille,
                individu=ratt[1].individu,
                activite=ActiviteFactory(structure=s),
            )
        response = logged_client.get(contact_url())
        assert response.context["liste_structures_coords"] == [visible]
        assert len(response.context["liste_structures_messagerie"]) == 2

    def test_structure_all_only_visible(self, logged_client):
        shown = StructureFactory(visible=True)
        StructureFactory(visible=False)
        assert list(logged_client.get(contact_url()).context["structure_all"]) == [
            shown
        ]

    def test_unread_counts_grouped_by_structure(
        self, logged_client, famille_user, staff_user
    ):
        _u, famille, _r = famille_user
        s1, s2 = StructureFactory(), StructureFactory()
        PortailMessageFactory(famille=famille, structure=s1, utilisateur=staff_user)
        PortailMessageFactory(famille=famille, structure=s1, utilisateur=staff_user)
        PortailMessageFactory(
            famille=famille,
            structure=s2,
            utilisateur=staff_user,
            date_lecture=datetime.datetime.now(),
        )
        PortailMessageFactory(
            famille=famille, structure=s2
        )  # sent by the family itself
        response = logged_client.get(contact_url())
        assert response.context["dict_messages_non_lus"] == {s1.pk: 2}

    def test_conversation_lists_only_own_family_messages(
        self, logged_client, famille_user, other_famille, staff_user
    ):
        _u, famille, _r = famille_user
        _ub, famille_b, _rb = other_famille
        structure = StructureFactory()
        mine = PortailMessageFactory(famille=famille, structure=structure)
        PortailMessageFactory(famille=famille_b, structure=structure)
        PortailMessageFactory(famille=famille, structure=StructureFactory())
        response = logged_client.get(contact_url(structure.pk))
        assert response.context["structure"] == structure
        assert list(response.context["liste_messages_discussion"]) == [mine]

    def test_conversation_marks_only_own_incoming_unread_as_read(
        self, logged_client, famille_user, other_famille, staff_user
    ):
        _u, famille, _r = famille_user
        _ub, famille_b, _rb = other_famille
        structure = StructureFactory()
        mine = PortailMessageFactory(
            famille=famille, structure=structure, utilisateur=staff_user
        )
        theirs = PortailMessageFactory(
            famille=famille_b, structure=structure, utilisateur=staff_user
        )
        elsewhere = PortailMessageFactory(
            famille=famille, structure=StructureFactory(), utilisateur=staff_user
        )
        logged_client.get(contact_url(structure.pk))
        for m in (mine, theirs, elsewhere):
            m.refresh_from_db()
        assert mine.date_lecture is not None
        assert theirs.date_lecture is None
        assert elsewhere.date_lecture is None

    @pytest.mark.xfail(
        reason="BUG: portail/views/contact.py does Structure.objects.get(pk=idstructure) for "
        "the URL value: an unknown structure id raises DoesNotExist (500) instead of 404.",
        strict=True,
    )
    def test_unknown_structure_gives_404(self, logged_client):
        assert logged_client.get(contact_url(987654)).status_code == 404

    @pytest.mark.xfail(
        reason="BUG: Structure.messagerie_active ('familles autorisées à converser') is never "
        "read by the portail: contact.View puts every structure of the family's activities "
        "in liste_structures_messagerie, and messagerie.Ajouter accepts posts to any structure.",
        strict=True,
    )
    def test_structure_with_messagerie_disabled_not_offered(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        s = StructureFactory(messagerie_active=False)
        InscriptionFactory(
            famille=famille,
            individu=ratt[1].individu,
            activite=ActiviteFactory(structure=s),
        )
        assert (
            s
            not in logged_client.get(contact_url()).context[
                "liste_structures_messagerie"
            ]
        )


@pytest.mark.django_db
class TestMessagerieGet:
    def test_anonymous_redirected(self, client, organisateur):
        structure = StructureFactory()
        response = client.get(messagerie_url(structure.pk))
        assert response.status_code == 302
        assert response.url == reverse("portail_connexion")

    def test_staff_forbidden(self, client, staff_user, organisateur):
        client.force_login(staff_user)
        assert client.get(messagerie_url(StructureFactory().pk)).status_code == 403

    def test_context_and_read_marking(self, logged_client, famille_user, staff_user):
        _u, famille, _r = famille_user
        structure = StructureFactory()
        incoming = PortailMessageFactory(
            famille=famille, structure=structure, utilisateur=staff_user
        )
        own = PortailMessageFactory(famille=famille, structure=structure)
        response = logged_client.get(messagerie_url(structure.pk))
        assert response.status_code == 200
        assert response.context["structure"] == structure
        assert list(response.context["liste_messages"]) == [incoming, own]
        # unread list is a snapshot taken before they are marked read
        assert response.context["liste_messages_non_lus"] == [incoming]
        incoming.refresh_from_db()
        own.refresh_from_db()
        assert incoming.date_lecture is not None
        assert own.date_lecture is None

    def test_other_family_messages_not_exposed(
        self, logged_client, other_famille, staff_user
    ):
        _ub, famille_b, _rb = other_famille
        structure = StructureFactory()
        secret = PortailMessageFactory(
            famille=famille_b, structure=structure, utilisateur=staff_user
        )
        response = logged_client.get(messagerie_url(structure.pk))
        assert list(response.context["liste_messages"]) == []
        secret.refresh_from_db()
        assert secret.date_lecture is None

    @pytest.mark.xfail(
        reason="BUG: portail/views/messagerie.py Page.get_context_data does Structure.objects.get "
        "on the URL id: an unknown structure raises DoesNotExist (500) instead of 404.",
        strict=True,
    )
    def test_unknown_structure_gives_404(self, logged_client):
        assert logged_client.get(messagerie_url(987654)).status_code == 404


@pytest.fixture
def no_notification(set_parametre_portail):
    set_parametre_portail("messagerie_envoyer_notification_admin", False)


@pytest.mark.django_db
class TestMessageriePost:
    def test_valid_post_creates_message_history_and_redirects_back(
        self, logged_client, famille_user, no_notification
    ):
        _u, famille, _r = famille_user
        structure = StructureFactory()
        response = logged_client.post(
            messagerie_url(structure.pk),
            {
                "famille": famille.pk,
                "structure": structure.pk,
                "texte": "<p>Bonjour</p>",
            },
        )
        assert response.status_code == 302
        assert response.url == messagerie_url(structure.pk)
        msg = PortailMessage.objects.get(famille=famille, structure=structure)
        assert msg.texte == "<p>Bonjour</p>" and msg.utilisateur is None
        assert Historique.objects.filter(
            titre="Ajouter un message", famille_id=famille.pk, portail=True
        ).exists()

    def test_flash_message_after_success(
        self, logged_client, famille_user, no_notification
    ):
        _u, famille, _r = famille_user
        structure = StructureFactory()
        response = logged_client.post(
            messagerie_url(structure.pk),
            {"famille": famille.pk, "structure": structure.pk, "texte": "Salut"},
            follow=True,
        )
        assert any("bien été envoyé" in str(m) for m in response.context["messages"])

    def test_emojis_stripped_from_text(
        self, logged_client, famille_user, no_notification
    ):
        _u, famille, _r = famille_user
        structure = StructureFactory()
        logged_client.post(
            messagerie_url(structure.pk),
            {
                "famille": famille.pk,
                "structure": structure.pk,
                "texte": "Salut \U0001f600 ami",
            },
        )
        assert PortailMessage.objects.get(famille=famille).texte == "Salut  ami"

    def test_empty_text_is_invalid(self, logged_client, famille_user, no_notification):
        _u, famille, _r = famille_user
        structure = StructureFactory()
        response = logged_client.post(
            messagerie_url(structure.pk),
            {"famille": famille.pk, "structure": structure.pk, "texte": ""},
        )
        assert response.status_code == 200
        assert "texte" in response.context["form"].errors
        assert not PortailMessage.objects.exists()

    def test_missing_famille_is_invalid(self, logged_client, no_notification):
        structure = StructureFactory()
        response = logged_client.post(
            messagerie_url(structure.pk), {"structure": structure.pk, "texte": "x"}
        )
        assert response.status_code == 200
        assert "famille" in response.context["form"].errors

    def test_unknown_structure_in_form_is_invalid(
        self, logged_client, famille_user, no_notification
    ):
        _u, famille, _r = famille_user
        structure = StructureFactory()
        response = logged_client.post(
            messagerie_url(structure.pk),
            {"famille": famille.pk, "structure": 987654, "texte": "x"},
        )
        assert response.status_code == 200
        assert "structure" in response.context["form"].errors

    def test_anonymous_post_does_not_create_message(
        self, client, famille_user, no_notification
    ):
        _u, famille, _r = famille_user
        structure = StructureFactory()
        response = client.post(
            messagerie_url(structure.pk),
            {"famille": famille.pk, "structure": structure.pk, "texte": "x"},
        )
        assert response.status_code == 302
        assert not PortailMessage.objects.exists()

    def test_staff_post_forbidden(
        self, client, staff_user, famille_user, no_notification
    ):
        _u, famille, _r = famille_user
        client.force_login(staff_user)
        structure = StructureFactory()
        response = client.post(
            messagerie_url(structure.pk),
            {"famille": famille.pk, "structure": structure.pk, "texte": "x"},
        )
        assert response.status_code == 403
        assert not PortailMessage.objects.exists()

    @pytest.mark.xfail(
        reason="BUG (cross-family write): the messagerie form takes the `famille` hidden field "
        "from the POST body and never compares it with request.user.famille — a family can "
        "post messages into another family's conversation by changing the hidden field.",
        strict=True,
    )
    def test_cannot_post_as_another_family(
        self, logged_client, other_famille, no_notification
    ):
        _ub, famille_b, _rb = other_famille
        structure = StructureFactory()
        logged_client.post(
            messagerie_url(structure.pk),
            {"famille": famille_b.pk, "structure": structure.pk, "texte": "usurpation"},
        )
        assert not PortailMessage.objects.filter(famille=famille_b).exists()

    @pytest.mark.xfail(
        reason="BUG: Structure.messagerie_active=False is not enforced server-side: "
        "messagerie.Ajouter creates the message anyway.",
        strict=True,
    )
    def test_cannot_post_to_structure_with_messagerie_disabled(
        self, logged_client, famille_user, no_notification
    ):
        _u, famille, _r = famille_user
        structure = StructureFactory(messagerie_active=False)
        logged_client.post(
            messagerie_url(structure.pk),
            {"famille": famille.pk, "structure": structure.pk, "texte": "x"},
        )
        assert not PortailMessage.objects.filter(structure=structure).exists()


@pytest.mark.django_db
class TestMessagerieNotification:
    """Apres_form_valid: notification email to the structure's address."""

    def _post(self, client, famille, structure):
        return client.post(
            messagerie_url(structure.pk),
            {"famille": famille.pk, "structure": structure.pk, "texte": "Bonjour"},
        )

    def test_param_disabled_sends_nothing(
        self, logged_client, famille_user, no_notification
    ):
        _u, famille, _r = famille_user
        structure = StructureFactory(adresse_exp=AdresseMailFactory())
        with mock.patch(
            "portail.views.messagerie.utils_email.Envoyer_model_mail"
        ) as envoi:
            response = self._post(logged_client, famille, structure)
        assert response.status_code == 302
        envoi.assert_not_called()

    def test_structure_without_adresse_exp_sends_nothing(
        self, logged_client, famille_user
    ):
        _u, famille, _r = famille_user
        structure = StructureFactory(adresse_exp=None)
        with mock.patch(
            "portail.views.messagerie.utils_email.Envoyer_model_mail"
        ) as envoi:
            response = self._post(logged_client, famille, structure)
        assert response.status_code == 302
        envoi.assert_not_called()

    def test_notification_mail_created_and_sent(self, logged_client, famille_user):
        from core.models import Mail

        _u, famille, _r = famille_user
        adresse = AdresseMailFactory(adresse="structure@test.org")
        structure = StructureFactory(adresse_exp=adresse)
        with mock.patch(
            "portail.views.messagerie.utils_email.Envoyer_model_mail"
        ) as envoi:
            response = self._post(logged_client, famille, structure)
        assert response.status_code == 302
        mail_obj = Mail.objects.get(objet="Nouveau message sur le portail")
        assert mail_obj.adresse_exp == adresse
        assert mail_obj.destinataires.get().adresse == "structure@test.org"
        assert str(famille) in mail_obj.html
        envoi.assert_called_once()
        assert envoi.call_args.kwargs["idmail"] == mail_obj.pk

    def test_notification_failure_does_not_break_post(
        self, logged_client, famille_user
    ):
        _u, famille, _r = famille_user
        structure = StructureFactory(adresse_exp=AdresseMailFactory())
        with mock.patch(
            "portail.views.messagerie.utils_email.Envoyer_model_mail",
            side_effect=RuntimeError("smtp"),
        ):
            response = self._post(logged_client, famille, structure)
        assert response.status_code == 302
        assert PortailMessage.objects.filter(famille=famille).exists()
