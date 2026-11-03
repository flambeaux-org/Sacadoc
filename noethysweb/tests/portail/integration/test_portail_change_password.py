"""Branch coverage for password_change(_done), profil and profil_password_change."""

import datetime

import pytest
from django.contrib.auth.hashers import check_password
from django.urls import reverse

NEW = "NewSecure_Pass123!"


def _data(**extra):
    data = {"new_password1": NEW, "new_password2": NEW, "check_conditions": True}
    data.update(extra)
    return data


@pytest.mark.django_db
class TestPasswordChange:
    def test_anonymous_get_redirects_to_login(self, client, organisateur):
        response = client.get(reverse("password_change"))
        assert response.status_code == 302
        assert "login" in response.url or "connexion" in response.url

    def test_anonymous_done_redirects_to_login(self, client, organisateur):
        response = client.get(reverse("password_change_done"))
        assert response.status_code == 302

    def test_get_renders_form_and_conditions_text(self, logged_client, organisateur):
        response = logged_client.get(reverse("password_change"))
        assert response.status_code == 200
        assert "texte_conditions" in response.context
        assert "check_conditions" in response.context["form"].fields
        assert "secquest" not in response.context["form"].fields

    def test_conditions_text_merges_organisateur_fields(
        self, logged_client, organisateur, set_parametre_portail
    ):
        organisateur.nom, organisateur.rue, organisateur.cp, organisateur.ville = (
            "Asso",
            "1 rue X",
            "75001",
            "Paris",
        )
        organisateur.save()
        set_parametre_portail(
            "mentions_conditions_generales",
            "{ORGANISATEUR_NOM}|{ORGANISATEUR_RUE}|{ORGANISATEUR_CP}|{ORGANISATEUR_VILLE}",
        )
        response = logged_client.get(reverse("password_change"))
        assert response.context["texte_conditions"] == "Asso|1 rue X|75001|Paris"

    def test_conditions_text_blank_organisateur_fields(
        self, logged_client, organisateur, set_parametre_portail
    ):
        organisateur.rue = None
        organisateur.save()
        set_parametre_portail("mentions_conditions_generales", "[{ORGANISATEUR_RUE}]")
        response = logged_client.get(reverse("password_change"))
        assert response.context["texte_conditions"] == "[]"

    def test_valid_post_resets_flags_and_internet_mdp(self, client, famille_user):
        user, famille, _r = famille_user
        user.force_reset_password = True
        user.date_expiration_mdp = datetime.datetime.now() + datetime.timedelta(days=1)
        user.save()
        famille.internet_mdp = "clear-text"
        famille.save()
        client.force_login(user)
        response = client.post(reverse("password_change"), _data())
        assert response.status_code == 302
        assert response.url == reverse("password_change_done")
        user.refresh_from_db()
        famille.refresh_from_db()
        assert check_password(NEW, user.password)
        assert user.force_reset_password is False
        assert user.date_expiration_mdp is None
        assert famille.internet_mdp == "*****"

    def test_session_survives_password_change(self, logged_client):
        logged_client.post(reverse("password_change"), _data())
        assert logged_client.get(reverse("password_change_done")).status_code == 200

    def test_missing_conditions_checkbox_rejected(self, logged_client, famille_user):
        user, _f, _r = famille_user
        response = logged_client.post(
            reverse("password_change"), {"new_password1": NEW, "new_password2": NEW}
        )
        assert response.status_code == 200
        assert "check_conditions" in response.context["form"].errors
        user.refresh_from_db()
        assert not check_password(NEW, user.password)

    def test_password_mismatch_rejected(self, logged_client):
        response = logged_client.post(
            reverse("password_change"), _data(new_password2="other")
        )
        assert response.status_code == 200
        assert response.context["form"].errors

    def test_weak_password_rejected(self, logged_client):
        response = logged_client.post(
            reverse("password_change"), _data(new_password1="123", new_password2="123")
        )
        assert response.status_code == 200
        assert "new_password2" in response.context["form"].errors

    def test_secquest_field_present_when_famille_has_question(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        famille.internet_secquest = "datenaiss_%d" % ratt[0].pk
        famille.save()
        response = logged_client.get(reverse("password_change"))
        assert "secquest" in response.context["form"].fields

    def test_correct_secquest_changes_password(self, logged_client, famille_user):
        user, famille, ratt = famille_user
        famille.internet_secquest = "datenaiss_%d" % ratt[0].pk
        famille.save()
        response = logged_client.post(
            reverse("password_change"),
            _data(secquest=ratt[0].individu.date_naiss.strftime("%d/%m/%Y")),
        )
        assert response.status_code == 302
        user.refresh_from_db()
        assert check_password(NEW, user.password)

    def test_wrong_secquest_rerenders_and_keeps_password(
        self, logged_client, famille_user
    ):
        user, famille, ratt = famille_user
        famille.internet_secquest = "datenaiss_%d" % ratt[0].pk
        famille.save()
        response = logged_client.post(
            reverse("password_change"), _data(secquest="01/01/1900")
        )
        assert response.status_code == 200
        assert "La réponse à la question est erronée" in " ".join(
            response.context["form"].non_field_errors()
        )
        user.refresh_from_db()
        assert not check_password(NEW, user.password)

    def test_done_renders_for_famille(self, logged_client):
        assert logged_client.get(reverse("password_change_done")).status_code == 200

    @pytest.mark.xfail(
        reason="BUG: portail/forms/change_password.py does kwargs['user'].famille without "
        "checking the account type — a logged-in staff (no Famille) opening "
        "/password_change/ gets RelatedObjectDoesNotExist (500).",
        strict=True,
    )
    def test_staff_user_get_does_not_crash(self, client, staff_user, organisateur):
        client.force_login(staff_user)
        response = client.get(reverse("password_change"))
        assert response.status_code < 500


@pytest.mark.django_db
class TestProfil:
    def test_anonymous_redirects_to_connexion(self, client, organisateur):
        response = client.get(reverse("portail_profil"))
        assert response.status_code == 302
        assert response.url == reverse("portail_connexion")

    def test_staff_user_forbidden(self, client, staff_user, organisateur):
        client.force_login(staff_user)
        assert client.get(reverse("portail_profil")).status_code == 403

    def test_context(self, logged_client):
        response = logged_client.get(reverse("portail_profil"))
        assert response.status_code == 200
        assert response.context["box_titre"]
        assert response.context["box_introduction"] == ""


@pytest.mark.django_db
class TestProfilPasswordChange:
    def test_anonymous_redirects(self, client, organisateur):
        response = client.get(reverse("portail_profil_password_change"))
        assert response.status_code == 302
        assert response.url == reverse("portail_connexion")

    def test_staff_forbidden(self, client, staff_user, organisateur):
        client.force_login(staff_user)
        assert client.get(reverse("portail_profil_password_change")).status_code == 403

    def test_get_context_has_validator_help(self, logged_client):
        response = logged_client.get(reverse("portail_profil_password_change"))
        assert response.status_code == 200
        assert response.context["texte_validateurs"]
        assert response.context["page_titre"]

    def test_valid_post_changes_password_and_flashes_message(
        self, logged_client, famille_user
    ):
        user, _f, _r = famille_user
        response = logged_client.post(
            reverse("portail_profil_password_change"),
            {"new_password1": NEW, "new_password2": NEW},
        )
        assert response.status_code == 302
        assert response.url == reverse("portail_profil")
        user.refresh_from_db()
        assert check_password(NEW, user.password)
        page = logged_client.get(response.url)
        assert any("modifié avec succès" in str(m) for m in page.context["messages"])

    def test_mismatch_rejected(self, logged_client, famille_user):
        user, _f, _r = famille_user
        response = logged_client.post(
            reverse("portail_profil_password_change"),
            {"new_password1": NEW, "new_password2": "other"},
        )
        assert response.status_code == 200
        assert response.context["form"].errors
        user.refresh_from_db()
        assert not check_password(NEW, user.password)

    def test_weak_password_rejected(self, logged_client):
        response = logged_client.post(
            reverse("portail_profil_password_change"),
            {"new_password1": "1234", "new_password2": "1234"},
        )
        assert response.status_code == 200
        assert response.context["form"].errors
