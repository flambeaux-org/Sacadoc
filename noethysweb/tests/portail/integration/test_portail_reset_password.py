"""Branch coverage for the portail "mot de passe oublié" flow (views + forms)."""

from unittest import mock

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.mail import get_connection as real_get_connection
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from portail.forms.reset_password import MySetPasswordForm
from tests.unit.factories import (
    AdresseMailFactory,
    FamilleFactory,
    FamilleUtilisateurFactory,
    IndividuFactory,
    RattachementFactory,
    UtilisateurFactory,
)

NEW_PASSWORD = "NewSecure_Pass123!"


@pytest.fixture
def adresse_exp(set_parametre_portail):
    adresse = AdresseMailFactory(adresse="noreply@test.org", moteur="console")
    set_parametre_portail("connexion_adresse_exp", adresse.pk)
    return adresse


@pytest.fixture
def locmem_connection():
    """Redirect the form's explicit backend to the in-memory outbox and record the call."""
    calls = []

    def fake(backend=None, fail_silently=False, **kwargs):
        calls.append({"backend": backend, "kwargs": kwargs})
        return real_get_connection("django.core.mail.backends.locmem.EmailBackend")

    with mock.patch(
        "portail.forms.reset_password.djangomail.get_connection", side_effect=fake
    ):
        yield calls


@pytest.fixture
def parent_email(famille_user):
    _user, _famille, ratt = famille_user
    parent = ratt[0].individu
    parent.mail = "parent@example.org"
    parent.save()
    return "parent@example.org"


def _errs(response):
    return " ".join(response.context["form"].non_field_errors())


def post_reset(client, identifiant, email):
    return client.post(
        reverse("reset_password"), {"identifiant": identifiant, "email": email}
    )


@pytest.mark.django_db
class TestResetPasswordForm:
    def test_get_renders(self, client, organisateur):
        response = client.get(reverse("reset_password"))
        assert response.status_code == 200
        assert "identifiant" in response.context["form"].fields

    def test_invalid_form_missing_fields(self, client, organisateur):
        response = client.post(reverse("reset_password"), {})
        assert response.status_code == 200
        assert response.context["form"].errors

    def test_unknown_identifiant_shows_error(
        self, client, organisateur, adresse_exp, locmem_connection
    ):
        response = post_reset(client, "inconnu", "x@example.org")
        assert response.status_code == 200
        assert "Il n'existe pas de compte actif" in _errs(response)
        assert mail.outbox == []

    def test_inactive_account_shows_same_error(
        self, client, organisateur, adresse_exp, locmem_connection
    ):
        user = FamilleUtilisateurFactory(username="inactif", is_active=False)
        FamilleFactory(utilisateur=user)
        response = post_reset(client, "inactif", user.email)
        assert response.status_code == 200
        assert "Il n'existe pas de compte actif" in _errs(response)

    @pytest.mark.xfail(
        reason="BUG (user enumeration): the form returns distinct error messages for "
        "'unknown identifiant' vs 'wrong email for this identifiant', revealing which "
        "identifiants exist.",
        strict=True,
    )
    def test_error_messages_do_not_reveal_account_existence(
        self, client, famille_user, adresse_exp, locmem_connection
    ):
        user, _f, _r = famille_user
        unknown = post_reset(client, "inconnu", "x@example.org").context["form"].errors
        known = (
            post_reset(client, user.username, "mauvais@example.org")
            .context["form"]
            .errors
        )
        assert str(unknown) == str(known)

    def test_famille_wrong_email_shows_error(
        self, client, famille_user, parent_email, adresse_exp, locmem_connection
    ):
        user, _f, _r = famille_user
        response = post_reset(client, user.username, "autre@example.org")
        assert response.status_code == 200
        assert "Adresse email non valide pour la famille" in _errs(response)
        assert mail.outbox == []

    def test_famille_email_of_young_person_is_rejected(
        self, client, famille_user, adresse_exp, locmem_connection
    ):
        """Only non-'jeune' rattachements are valid recipients."""
        user, famille, _r = famille_user
        jeune = IndividuFactory(mail="jeune@example.org", statut=5)
        RattachementFactory(famille=famille, individu=jeune, categorie=2)
        response = post_reset(client, user.username, "jeune@example.org")
        assert "Adresse email non valide pour la famille" in _errs(response)

    def test_staff_wrong_email_shows_error(
        self, client, staff_user, adresse_exp, locmem_connection
    ):
        response = post_reset(client, staff_user.username, "autre@example.org")
        assert response.status_code == 200
        assert "Adresse email non valide pour l'utilisateur" in _errs(response)

    def test_no_adresse_exp_configured_shows_error(
        self, client, famille_user, parent_email
    ):
        user, _f, _r = famille_user
        response = post_reset(client, user.username, parent_email)
        assert response.status_code == 200
        assert "L'envoi de l'email a échoué" in _errs(response)

    def test_success_famille_sends_mail_and_generates_secquest(
        self, client, famille_user, parent_email, adresse_exp, locmem_connection
    ):
        user, famille, _r = famille_user
        response = post_reset(client, user.username.upper(), parent_email.upper())
        assert response.status_code == 302
        assert response.url == reverse("password_reset_done")
        assert len(mail.outbox) >= 1
        message = mail.outbox[0]
        assert message.to == [parent_email.upper()]
        assert message.from_email == "noreply@test.org"
        assert "/reset/" in message.body
        # console engine: no extra kwargs
        assert (
            locmem_connection[0]["backend"]
            == "django.core.mail.backends.console.EmailBackend"
        )
        assert locmem_connection[0]["kwargs"] == {}
        famille.refresh_from_db()
        assert famille.internet_secquest and famille.internet_secquest.startswith(
            "datenaiss_"
        )

    def test_success_staff_sends_mail_without_secquest(
        self, client, staff_user, adresse_exp, locmem_connection
    ):
        response = post_reset(client, staff_user.username, staff_user.email)
        assert response.status_code == 302
        assert len(mail.outbox) >= 1

    @pytest.mark.xfail(
        reason="BUG: portail/views/reset_password.py MyPasswordResetView.form_valid calls "
        "form.save() itself and then super().form_valid() calls form.save() again -> "
        "the reset email is sent twice (and the secquest generated twice).",
        strict=True,
    )
    def test_reset_sends_exactly_one_email(
        self, client, staff_user, adresse_exp, locmem_connection
    ):
        post_reset(client, staff_user.username, staff_user.email)
        assert len(mail.outbox) == 1

    def test_smtp_engine_backend_kwargs(
        self, client, staff_user, set_parametre_portail, locmem_connection
    ):
        adresse = AdresseMailFactory(
            adresse="smtp@test.org",
            moteur="smtp",
            hote="smtp.test",
            port=2525,
            utilisateur="u",
            motdepasse="p",
            use_tls=True,
        )
        set_parametre_portail("connexion_adresse_exp", adresse.pk)
        post_reset(client, staff_user.username, staff_user.email)
        call = locmem_connection[0]
        assert call["backend"] == "django.core.mail.backends.smtp.EmailBackend"
        assert call["kwargs"] == {
            "host": "smtp.test",
            "port": 2525,
            "username": "u",
            "password": "p",
            "use_tls": True,
        }

    def test_mailjet_engine_backend_kwargs(
        self, client, staff_user, set_parametre_portail, locmem_connection
    ):
        adresse = AdresseMailFactory(adresse="mj@test.org", moteur="mailjet")
        set_parametre_portail("connexion_adresse_exp", adresse.pk)
        with mock.patch(
            "core.models.AdresseMail.Get_parametre", side_effect=lambda k: "val_" + k
        ):
            post_reset(client, staff_user.username, staff_user.email)
        call = locmem_connection[0]
        assert call["backend"] == "anymail.backends.mailjet.EmailBackend"
        assert call["kwargs"] == {
            "api_key": "val_api_key",
            "secret_key": "val_api_secret",
        }

    def test_brevo_engine_backend_kwargs(
        self, client, staff_user, set_parametre_portail, locmem_connection
    ):
        adresse = AdresseMailFactory(adresse="bv@test.org", moteur="brevo")
        set_parametre_portail("connexion_adresse_exp", adresse.pk)
        with mock.patch(
            "core.models.AdresseMail.Get_parametre", side_effect=lambda k: "val_" + k
        ):
            post_reset(client, staff_user.username, staff_user.email)
        call = locmem_connection[0]
        assert call["backend"] == "anymail.backends.sendinblue.EmailBackend"
        assert call["kwargs"] == {"api_key": "val_api_key"}

    def test_connection_open_failure_shows_error(self, client, staff_user, adresse_exp):
        broken = mock.Mock()
        broken.open.side_effect = OSError("boom")
        with mock.patch(
            "portail.forms.reset_password.djangomail.get_connection",
            return_value=broken,
        ):
            response = post_reset(client, staff_user.username, staff_user.email)
        assert response.status_code == 200
        assert "Connexion impossible au serveur de messagerie" in _errs(response)

    def test_send_returns_zero_shows_error(
        self, client, staff_user, adresse_exp, locmem_connection
    ):
        with mock.patch(
            "portail.forms.reset_password.EmailMultiAlternatives.send", return_value=0
        ):
            response = post_reset(client, staff_user.username, staff_user.email)
        assert response.status_code == 200
        assert "L'envoi de l'email a échoué" in _errs(response)

    def test_send_exception_is_reported_in_form(
        self, client, staff_user, adresse_exp, locmem_connection
    ):
        """send() raising: the exception object is returned as `resultat` (!= True)."""
        with mock.patch(
            "portail.forms.reset_password.EmailMultiAlternatives.send",
            side_effect=RuntimeError("smtp down"),
        ):
            response = post_reset(client, staff_user.username, staff_user.email)
        assert response.status_code == 200
        assert "smtp down" in _errs(response)

    def test_html_email_template_branch(
        self, adresse_exp, locmem_connection, staff_user
    ):
        """Calling save() with html_email_template_name attaches an HTML alternative."""
        from portail.forms.reset_password import MyPasswordResetForm

        form = MyPasswordResetForm(
            data={"identifiant": staff_user.username, "email": staff_user.email}
        )
        assert form.is_valid(), form.errors
        form.save(
            domain_override="example.org",
            subject_template_name="portail/password_reset_subject.txt",
            email_template_name="portail/password_reset_email.html",
            html_email_template_name="portail/password_reset_email.html",
            use_https=True,
        )
        assert mail.outbox[0].alternatives
        assert "https://example.org" in mail.outbox[0].body


@pytest.mark.django_db
class TestResetPasswordPages:
    def test_done_renders(self, client, organisateur):
        assert client.get(reverse("password_reset_done")).status_code == 200

    def test_complete_renders_for_anonymous(self, client, organisateur):
        response = client.get(reverse("password_reset_complete"))
        assert response.status_code == 200
        assert response.context["user_category"] is None

    def test_complete_exposes_category_for_logged_famille(self, logged_client):
        response = logged_client.get(reverse("password_reset_complete"))
        assert response.context["user_category"] == "famille"


def _confirm_url(user, token=None):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = token or default_token_generator.make_token(user)
    return reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token})


def _enter_confirm_form(client, user):
    """Follow Django's token -> session redirect and return the set-password URL."""
    response = client.get(_confirm_url(user))
    assert response.status_code == 302
    return response.url


@pytest.mark.django_db
class TestResetPasswordConfirm:
    def test_invalid_token_shows_invalid_link_page(self, client, famille_user):
        user, _f, _r = famille_user
        response = client.get(_confirm_url(user, token="abc-def"), follow=True)
        assert response.status_code == 200
        assert response.context["validlink"] is False

    def test_invalid_uid_shows_invalid_link_page(self, client, organisateur):
        url = reverse(
            "password_reset_confirm", kwargs={"uidb64": "!!", "token": "abc-def"}
        )
        response = client.get(url)
        assert response.status_code == 200
        assert response.context["validlink"] is False

    def test_valid_token_renders_form_without_secquest(self, client, famille_user):
        user, _f, _r = famille_user
        url = _enter_confirm_form(client, user)
        response = client.get(url)
        assert response.status_code == 200
        assert response.context["validlink"] is True
        assert "secquest" not in response.context["form"].fields

    def test_valid_token_famille_with_secquest_adds_field(self, client, famille_user):
        user, famille, ratt = famille_user
        famille.internet_secquest = "datenaiss_%d" % ratt[0].pk
        famille.save()
        url = _enter_confirm_form(client, user)
        response = client.get(url)
        assert "secquest" in response.context["form"].fields

    def test_staff_user_form_has_no_secquest(self, client, staff_user):
        url = _enter_confirm_form(client, staff_user)
        response = client.get(url)
        assert response.status_code == 200
        assert "secquest" not in response.context["form"].fields

    def test_post_valid_without_secquest_changes_password(self, client, famille_user):
        user, _f, _r = famille_user
        url = _enter_confirm_form(client, user)
        response = client.post(
            url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD}
        )
        assert response.status_code == 302
        assert response.url == reverse("password_reset_complete")
        user.refresh_from_db()
        assert user.check_password(NEW_PASSWORD)

    def test_post_password_mismatch_rerenders(self, client, famille_user):
        user, _f, _r = famille_user
        url = _enter_confirm_form(client, user)
        response = client.post(
            url, {"new_password1": NEW_PASSWORD, "new_password2": "different"}
        )
        assert response.status_code == 200
        assert response.context["form"].errors
        user.refresh_from_db()
        assert not user.check_password(NEW_PASSWORD)

    def test_post_with_correct_secquest(self, client, famille_user):
        user, famille, ratt = famille_user
        famille.internet_secquest = "datenaiss_%d" % ratt[0].pk
        famille.save()
        url = _enter_confirm_form(client, user)
        response = client.post(
            url,
            {
                "new_password1": NEW_PASSWORD,
                "new_password2": NEW_PASSWORD,
                "secquest": ratt[0].individu.date_naiss.strftime("%d/%m/%Y"),
            },
        )
        assert response.status_code == 302
        user.refresh_from_db()
        assert user.check_password(NEW_PASSWORD)

    def test_post_with_wrong_secquest_rejected(self, client, famille_user):
        user, famille, ratt = famille_user
        famille.internet_secquest = "datenaiss_%d" % ratt[0].pk
        famille.save()
        url = _enter_confirm_form(client, user)
        response = client.post(
            url,
            {
                "new_password1": NEW_PASSWORD,
                "new_password2": NEW_PASSWORD,
                "secquest": "01/01/1900",
            },
        )
        assert response.status_code == 200
        assert "La réponse à la question est erronée" in _errs(response)
        user.refresh_from_db()
        assert not user.check_password(NEW_PASSWORD)

    def test_staff_post_without_secquest_changes_password(self, client, staff_user):
        url = _enter_confirm_form(client, staff_user)
        response = client.post(
            url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD}
        )
        assert response.status_code == 302
        staff_user.refresh_from_db()
        assert staff_user.check_password(NEW_PASSWORD)

    def test_token_cannot_be_reused(self, client, famille_user):
        user, _f, _r = famille_user
        token = default_token_generator.make_token(user)
        url = _enter_confirm_form(client, user)
        client.post(url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD})
        response = client.get(_confirm_url(user, token=token), follow=True)
        assert response.context["validlink"] is False

    def test_set_password_form_secquest_skipped_for_user_without_famille(self, db):
        user = UtilisateurFactory(username="nofam")
        form = MySetPasswordForm(user=user)
        assert "secquest" not in form.fields
