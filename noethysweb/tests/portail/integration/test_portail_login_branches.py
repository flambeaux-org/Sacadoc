"""Branch coverage for portail login/logout views, login form and secquest utils."""

import datetime

import pytest
from core.models import Historique, ImageFond, Utilisateur
from django.core.files.uploadedfile import SimpleUploadedFile
from django.forms import ValidationError
from django.urls import reverse
from portail.forms.login import FormLoginFamille
from portail.utils import utils_secquest
from tests.unit.factories import (
    FamilleFactory,
    FamilleUtilisateurFactory,
    IndividuFactory,
    RattachementFactory,
)

PASSWORD = "testpassword"


@pytest.mark.django_db
class TestConnexionGet:
    def test_get_renders_form_for_anonymous(self, client, organisateur):
        response = client.get(reverse("portail_connexion"))
        assert response.status_code == 200
        assert response.context["public"] == "famille"
        assert "form" in response.context

    def test_default_background_image_when_none_configured(self, client, organisateur):
        response = client.get(reverse("portail_connexion"))
        assert response.context["url_image_fond"].endswith("images/portail.jpg")

    def test_custom_background_image_when_configured(
        self, client, organisateur, set_parametre_portail, settings, tmp_path
    ):
        settings.MEDIA_ROOT = str(tmp_path)
        from io import BytesIO

        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (4, 4)).save(buf, format="PNG")
        image = ImageFond.objects.create(
            titre="Fond",
            image=SimpleUploadedFile("f.png", buf.getvalue(), content_type="image/png"),
        )
        set_parametre_portail("connexion_image_fond", image.pk)
        response = client.get(reverse("portail_connexion"))
        assert response.status_code == 200
        assert response.context["url_image_fond"] == image.image.url

    @pytest.mark.xfail(
        reason="BUG: portail/views/login.py ClassCommuneLogin.get_context_data does "
        "ImageFond.objects.filter(pk=...).first().image.url — a dangling "
        "connexion_image_fond id (image deleted) raises AttributeError (500) and "
        "locks everybody out of the login page.",
        strict=True,
    )
    def test_dangling_background_image_does_not_crash(
        self, client, organisateur, set_parametre_portail
    ):
        set_parametre_portail("connexion_image_fond", 987654)
        response = client.get(reverse("portail_connexion"))
        assert response.status_code == 200

    def test_organisateur_missing_still_renders(self, client, db):
        """No Organisateur row: the cache stores None and the page still renders."""
        response = client.get(reverse("portail_connexion"))
        assert response.status_code == 200
        assert response.context["organisateur"] is None


@pytest.mark.django_db
class TestConnexionPost:
    def test_valid_famille_login_redirects_to_accueil_and_logs_history(
        self, client, famille_user
    ):
        user, famille, _ = famille_user
        before = user.last_login
        response = client.post(
            reverse("portail_connexion"),
            {"username": user.username, "password": PASSWORD},
        )
        assert response.status_code == 302
        assert response.url == reverse("portail_accueil")
        assert client.session["_auth_user_id"] == str(user.pk)
        user.refresh_from_db()
        assert user.last_login is not None and user.last_login != before
        assert Historique.objects.filter(
            titre="Connexion au portail", famille_id=famille.pk, portail=True
        ).exists()

    def test_valid_login_honours_safe_next_url(self, client, famille_user):
        user, _f, _r = famille_user
        response = client.post(
            reverse("portail_connexion"),
            {
                "username": user.username,
                "password": PASSWORD,
                "portail_accueil": "/contact",
            },
        )
        assert response.status_code == 302
        assert response.url == "/contact"

    def test_valid_login_ignores_external_next_url(self, client, famille_user):
        """Open-redirect protection: an off-site `next` is dropped."""
        user, _f, _r = famille_user
        response = client.post(
            reverse("portail_connexion"),
            {
                "username": user.username,
                "password": PASSWORD,
                "portail_accueil": "https://evil.example/x",
            },
        )
        assert response.status_code == 302
        assert "evil.example" not in response.url
        assert response.url == reverse("portail_accueil")

    def test_wrong_password_rerenders_with_error(self, client, famille_user):
        user, _f, _r = famille_user
        response = client.post(
            reverse("portail_connexion"),
            {"username": user.username, "password": "nope"},
        )
        assert response.status_code == 200
        assert response.context["form"].errors
        assert "_auth_user_id" not in client.session

    def test_unknown_user_rerenders_with_error(self, client, organisateur):
        response = client.post(
            reverse("portail_connexion"), {"username": "ghost", "password": "x"}
        )
        assert response.status_code == 200
        assert response.context["form"].errors

    def test_missing_fields_invalid(self, client, organisateur):
        response = client.post(reverse("portail_connexion"), {})
        assert response.status_code == 200
        assert response.context["form"].errors

    def test_staff_user_login_redirects_to_staff_accueil_without_history(
        self, client, staff_user
    ):
        """A staff account logging in through the portail form goes to the staff home
        and no famille history entry is written (categorie != famille)."""
        response = client.post(
            reverse("portail_connexion"),
            {"username": staff_user.username, "password": PASSWORD},
        )
        assert response.status_code == 302
        assert response.url == reverse("accueil")
        assert not Historique.objects.filter(titre="Connexion au portail").exists()

    def test_inactive_user_cannot_login(self, client, organisateur):
        user = FamilleUtilisateurFactory(username="inactif", is_active=False)
        FamilleFactory(utilisateur=user)
        response = client.post(
            reverse("portail_connexion"), {"username": "inactif", "password": PASSWORD}
        )
        assert response.status_code == 200
        assert "_auth_user_id" not in client.session

    def test_expired_password_cannot_login(self, client, organisateur):
        user = FamilleUtilisateurFactory(
            username="expire",
            date_expiration_mdp=datetime.datetime.now() - datetime.timedelta(days=1),
        )
        FamilleFactory(utilisateur=user)
        response = client.post(
            reverse("portail_connexion"), {"username": "expire", "password": PASSWORD}
        )
        assert response.status_code == 200
        assert "Ce mot de passe a expiré" in str(response.context["form"].errors)
        assert "_auth_user_id" not in client.session

    def test_future_password_expiry_allows_login(self, client, organisateur):
        user = FamilleUtilisateurFactory(
            username="bientot",
            date_expiration_mdp=datetime.datetime.now() + datetime.timedelta(days=5),
        )
        FamilleFactory(utilisateur=user)
        response = client.post(
            reverse("portail_connexion"), {"username": "bientot", "password": PASSWORD}
        )
        assert response.status_code == 302

    def test_already_logged_in_user_still_sees_login_form(self, logged_client):
        """redirect_authenticated_user is off: no redirect for a logged-in family."""
        response = logged_client.get(reverse("portail_connexion"))
        assert response.status_code == 200


@pytest.mark.django_db
class TestLoginFormConfirmLoginAllowed:
    def _form(self):
        return FormLoginFamille(data={"username": "x", "password": "y"})

    def test_inactive_user_raises_inactive(self):
        user = Utilisateur(username="u", is_active=False)
        with pytest.raises(ValidationError) as exc:
            self._form().confirm_login_allowed(user)
        assert exc.value.code == "inactive"

    def test_expired_password_raises_mdp_expire(self):
        user = Utilisateur(
            username="u",
            is_active=True,
            date_expiration_mdp=datetime.datetime.now() - datetime.timedelta(seconds=1),
        )
        with pytest.raises(ValidationError) as exc:
            self._form().confirm_login_allowed(user)
        assert exc.value.code == "mdp_expire"

    def test_active_no_expiry_ok(self):
        assert (
            self._form().confirm_login_allowed(
                Utilisateur(username="u", is_active=True)
            )
            is None
        )


@pytest.mark.django_db
class TestDeconnexion:
    def test_logout_clears_session_and_redirects(self, logged_client):
        response = logged_client.post(reverse("portail_deconnexion"))
        assert response.status_code == 302
        assert response.url == reverse("portail_connexion")
        assert "_auth_user_id" not in logged_client.session

    def test_logout_anonymous_redirects(self, client, organisateur):
        response = client.post(reverse("portail_deconnexion"))
        assert response.status_code == 302
        assert response.url == reverse("portail_connexion")


@pytest.mark.django_db
class TestSecquest:
    def _famille(self, **kw):
        user = FamilleUtilisateurFactory()
        return FamilleFactory(utilisateur=user, **kw)

    def test_generation_picks_question_for_titulaire(self, organisateur):
        famille = self._famille()
        ratt = RattachementFactory(
            famille=famille,
            individu=IndividuFactory(
                prenom="Alice", date_naiss=datetime.date(1980, 5, 6)
            ),
            categorie=1,
            titulaire=True,
        )
        utils_secquest.Generation_secquest(famille=famille)
        famille.refresh_from_db()
        assert famille.internet_secquest == "datenaiss_%d" % ratt.pk

    def test_generation_includes_children(self, organisateur):
        famille = self._famille()
        ratt = RattachementFactory(famille=famille, categorie=2)
        utils_secquest.Generation_secquest(famille=famille)
        famille.refresh_from_db()
        assert famille.internet_secquest == "datenaiss_%d" % ratt.pk

    def test_generation_skips_individus_without_birthdate_or_firstname(
        self, organisateur
    ):
        famille = self._famille()
        RattachementFactory(
            famille=famille,
            categorie=1,
            titulaire=True,
            individu=IndividuFactory(date_naiss=None),
        )
        RattachementFactory(
            famille=famille, categorie=2, individu=IndividuFactory(prenom="")
        )
        utils_secquest.Generation_secquest(famille=famille)
        famille.refresh_from_db()
        assert not famille.internet_secquest

    def test_generation_skips_non_titulaire_adult(self, organisateur):
        famille = self._famille()
        RattachementFactory(famille=famille, categorie=1, titulaire=False)
        utils_secquest.Generation_secquest(famille=famille)
        famille.refresh_from_db()
        assert not famille.internet_secquest

    def test_generation_disabled_by_parameter_clears_question(
        self, organisateur, set_parametre_portail
    ):
        set_parametre_portail("connexion_question_perso", False)
        famille = self._famille(internet_secquest="datenaiss_1")
        RattachementFactory(famille=famille, categorie=2)
        utils_secquest.Generation_secquest(famille=famille)
        famille.refresh_from_db()
        assert not famille.internet_secquest

    def test_generation_field_label_uses_prenom(self, organisateur):
        famille = self._famille()
        ratt = RattachementFactory(
            famille=famille, individu=IndividuFactory(prenom="Zoe")
        )
        famille.internet_secquest = "datenaiss_%d" % ratt.pk
        field = utils_secquest.Generation_field_secquest(famille=famille)
        assert "Zoe" in field.label
        assert field.required is True

    def test_check_no_question_always_true(self, organisateur):
        famille = self._famille(internet_secquest=None)
        assert (
            utils_secquest.Check_secquest(famille=famille, reponse="anything") is True
        )

    def test_check_correct_answer(self, organisateur):
        famille = self._famille()
        ratt = RattachementFactory(
            famille=famille,
            individu=IndividuFactory(date_naiss=datetime.date(2010, 3, 4)),
        )
        famille.internet_secquest = "datenaiss_%d" % ratt.pk
        assert (
            utils_secquest.Check_secquest(famille=famille, reponse="04/03/2010") is True
        )

    def test_check_wrong_answer(self, organisateur):
        famille = self._famille()
        ratt = RattachementFactory(
            famille=famille,
            individu=IndividuFactory(date_naiss=datetime.date(2010, 3, 4)),
        )
        famille.internet_secquest = "datenaiss_%d" % ratt.pk
        assert (
            utils_secquest.Check_secquest(famille=famille, reponse="01/01/2000")
            is False
        )

    def test_check_individu_without_birthdate_is_false(self, organisateur):
        famille = self._famille()
        ratt = RattachementFactory(
            famille=famille, individu=IndividuFactory(date_naiss=None)
        )
        famille.internet_secquest = "datenaiss_%d" % ratt.pk
        assert (
            utils_secquest.Check_secquest(famille=famille, reponse="01/01/2000")
            is False
        )


@pytest.mark.django_db
class TestEmailBackendLogin:
    """core.backends.EmailModelBackend lets a parent log in with their email."""

    def test_login_with_parent_email(self, client, famille_user):
        user, _famille, ratt = famille_user
        parent = ratt[0].individu
        parent.mail = "parent@example.org"
        parent.save()
        response = client.post(
            reverse("portail_connexion"),
            {"username": "PARENT@example.org", "password": PASSWORD},
        )
        assert response.status_code == 302
        assert client.session["_auth_user_id"] == str(user.pk)

    @pytest.mark.xfail(
        reason="BUG: core/backends.py EmailModelBackend does "
        "individu.rattachement_set.first().famille.utilisateur — an Individu whose "
        "email matches the typed username but who has no Rattachement makes .first() "
        "None -> AttributeError (500) on the login page.",
        strict=True,
    )
    def test_login_with_email_of_orphan_individu_does_not_crash(
        self, client, organisateur
    ):
        IndividuFactory(mail="orphan@example.org")
        response = client.post(
            reverse("portail_connexion"),
            {"username": "orphan@example.org", "password": "x"},
        )
        assert response.status_code == 200
