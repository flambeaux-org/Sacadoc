"""Branch coverage for the public family self-registration page."""

import json
from unittest import mock

import dns.resolver
import pytest
from core.models import Destinataire, Famille, Individu, Mail, Rattachement, Utilisateur
from django.urls import reverse
from tests.unit.factories import AdresseMailFactory, IndividuFactory

URL = "inscription_famille"
PWD = "SuperMotDePasse123987"


def payload(**over):
    data = {
        "civilite": "1",
        "nom": "Dupont",
        "prenom": "Marie",
        "mail": "marie.dupont@example.org",
        "new_password1": PWD,
        "new_password2": PWD,
    }
    data.update(over)
    return data


@pytest.fixture(autouse=True)
def mx_ok():
    """validate_email_domain_mx does real DNS lookups: stub them out."""
    with mock.patch(
        "core.validators.dns.resolver.resolve", return_value=[object()]
    ) as m:
        yield m


@pytest.fixture
def adresse_1(db):
    return AdresseMailFactory(pk=1, adresse="noreply@test.org")


@pytest.fixture
def envoi():
    with mock.patch("portail.views.inscription_famille.Envoyer_model_mail") as m:
        yield m


@pytest.mark.django_db
class TestInscriptionGet:
    def test_get_renders_form(self, client, organisateur):
        response = client.get(reverse(URL))
        assert response.status_code == 200
        assert "civilite" in response.context["form"].fields
        assert "inscription_ok" not in response.context

    def test_get_404_when_registration_disabled(
        self, client, organisateur, set_parametre_portail
    ):
        set_parametre_portail("autoriser_inscription_famille", False)
        assert client.get(reverse(URL)).status_code == 404

    def test_post_404_when_registration_disabled(
        self, client, organisateur, set_parametre_portail, adresse_1, envoi
    ):
        set_parametre_portail("autoriser_inscription_famille", False)
        before = Utilisateur.objects.count()
        assert client.post(reverse(URL), payload()).status_code == 404
        assert Utilisateur.objects.count() == before
        envoi.assert_not_called()

    def test_unsupported_method_not_allowed(self, client, organisateur):
        assert client.put(reverse(URL)).status_code == 405


@pytest.mark.django_db
class TestInscriptionPostInvalid:
    def test_empty_post_rerenders_with_errors(self, client, organisateur, envoi):
        before = Famille.objects.count()
        response = client.post(reverse(URL), {})
        assert response.status_code == 200
        assert "inscription_ok" not in response.context
        assert Famille.objects.count() == before
        envoi.assert_not_called()

    def test_password_mismatch(self, client, organisateur, envoi):
        response = client.post(reverse(URL), payload(new_password2="Different_123456"))
        assert response.status_code == 200
        assert "new_password2" in response.context["form"].errors

    def test_password_similar_to_user_attributes_rejected(
        self, client, organisateur, envoi
    ):
        """clean_new_password2 builds a fake user so similarity validators see nom/prenom/mail."""
        response = client.post(
            reverse(URL),
            payload(
                new_password1="marie.dupont@example.org",
                new_password2="marie.dupont@example.org",
            ),
        )
        assert response.status_code == 200
        assert "new_password2" in response.context["form"].errors

    def test_weak_password_rejected(self, client, organisateur, envoi):
        response = client.post(
            reverse(URL), payload(new_password1="123", new_password2="123")
        )
        assert response.status_code == 200
        assert "new_password2" in response.context["form"].errors

    def test_invalid_civilite_choice(self, client, organisateur, envoi):
        response = client.post(reverse(URL), payload(civilite="999"))
        assert response.status_code == 200
        assert "civilite" in response.context["form"].errors

    def test_invalid_email_syntax(self, client, organisateur, envoi):
        response = client.post(reverse(URL), payload(mail="not-an-email"))
        assert response.status_code == 200
        assert "mail" in response.context["form"].errors

    def test_email_domain_without_mx_rejected(self, client, organisateur, envoi, mx_ok):
        mx_ok.side_effect = dns.resolver.NXDOMAIN()
        response = client.post(reverse(URL), payload(mail="x@no-such-domain.invalid"))
        assert response.status_code == 200
        assert "mail" in response.context["form"].errors


@pytest.mark.django_db
class TestInscriptionPostMailExists:
    def test_existing_individu_email_blocks_registration(
        self, client, organisateur, adresse_1, envoi
    ):
        IndividuFactory(mail="marie.dupont@example.org")
        before = (Famille.objects.count(), Utilisateur.objects.count())
        response = client.post(reverse(URL), payload())
        assert response.status_code == 200
        assert response.context["mail_exists"] is True
        assert "inscription_ok" not in response.context
        assert (Famille.objects.count(), Utilisateur.objects.count()) == before
        envoi.assert_not_called()

    def test_existing_email_match_is_case_insensitive(
        self, client, organisateur, adresse_1, envoi
    ):
        IndividuFactory(mail="MARIE.DUPONT@EXAMPLE.ORG")
        response = client.post(reverse(URL), payload())
        assert response.context["mail_exists"] is True

    def test_individus_without_email_do_not_block(
        self, client, organisateur, adresse_1, envoi
    ):
        IndividuFactory(mail="")
        response = client.post(reverse(URL), payload())
        assert response.context["inscription_ok"] is True


@pytest.mark.django_db
class TestInscriptionPostSuccess:
    def test_creates_famille_user_individu_rattachement(
        self, client, organisateur, adresse_1, envoi
    ):
        response = client.post(reverse(URL), payload())
        assert response.status_code == 200
        assert response.context["inscription_ok"] is True

        individu = Individu.objects.get(nom="Dupont", prenom="Marie")
        assert individu.mail == "marie.dupont@example.org"
        ratt = Rattachement.objects.get(individu=individu)
        assert ratt.categorie == 1 and ratt.titulaire is True
        famille = ratt.famille
        user = famille.utilisateur
        assert user.categorie == "famille"
        assert user.username == famille.internet_identifiant
        assert famille.internet_mdp == "*****"

    def test_new_user_can_log_in_with_chosen_password(
        self, client, organisateur, adresse_1, envoi
    ):
        client.post(reverse(URL), payload())
        user = Utilisateur.objects.get(categorie="famille")
        assert user.check_password(PWD)

    def test_sends_identifiant_mail_to_famille(
        self, client, organisateur, adresse_1, envoi
    ):
        client.post(reverse(URL), payload())
        mail_obj = Mail.objects.get(categorie="portail")
        assert mail_obj.adresse_exp == adresse_1
        assert mail_obj.verrouillage_destinataires is True
        destinataire = Destinataire.objects.get(famille__isnull=False)
        values = json.loads(destinataire.valeurs)
        famille = Famille.objects.get(pk=destinataire.famille_id)
        assert values == {"{IDENTIFIANT_INTERNET}": famille.internet_identifiant}
        assert mail_obj.destinataires.filter(pk=destinataire.pk).exists()
        envoi.assert_called_once_with(mail_obj.pk)

    @pytest.mark.xfail(
        reason="BUG: inscription_famille creates the Famille/Utilisateur/Individu before "
        "AdresseMail.objects.get(idadresse=1); when no AdresseMail with id 1 exists it "
        "raises DoesNotExist (500) leaving an orphan, un-notified account (view is not atomic).",
        strict=True,
    )
    def test_missing_adresse_1_does_not_leave_orphan_account(
        self, client, organisateur, envoi
    ):
        before = Utilisateur.objects.count()
        try:
            client.post(reverse(URL), payload())
        except Exception:
            pass
        assert Utilisateur.objects.count() == before
