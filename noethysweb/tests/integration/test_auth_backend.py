"""Tests for core.backends.EmailModelBackend.

The backend first looks the identifier up as a username (exact, case-sensitive),
then falls back to a case-insensitive match on Individu.mail (adults only) and
returns the Utilisateur of the individu's famille.
"""

import pytest
from core.backends import EmailModelBackend
from core.models import Individu
from django.core.cache import cache
from django.urls import reverse
from tests.unit.factories import (
    FamilleFactory,
    IndividuFactory,
    OrganisateurFactory,
    RattachementFactory,
    UtilisateurFactory,
    create_famille_user,
)

PASSWORD = "testpassword"


def make_famille_with_parent(username, mail, statut=Individu.STATUT_PARENT, **user_kw):
    user, famille = create_famille_user(username=username)
    for attr, value in user_kw.items():
        setattr(user, attr, value)
    user.save()
    parent = IndividuFactory(mail=mail, statut=statut)
    RattachementFactory(individu=parent, famille=famille, categorie=1, titulaire=True)
    return user, parent


def auth(username, password=PASSWORD):
    return EmailModelBackend().authenticate(None, username=username, password=password)


@pytest.mark.django_db
class TestUsernameLogin:
    def test_exact_username(self):
        user = UtilisateurFactory(username="staff")
        assert auth("staff") == user

    def test_username_is_case_sensitive(self):
        """Usernames are matched exactly; only emails are case-insensitive."""
        UtilisateurFactory(username="staff")
        assert auth("STAFF") is None

    def test_wrong_password(self):
        UtilisateurFactory(username="staff")
        assert auth("staff", "nope") is None

    def test_unknown_identifier(self):
        assert auth("ghost") is None

    def test_username_kwarg_via_username_field(self):
        user = UtilisateurFactory(username="staff")
        assert EmailModelBackend().authenticate(None, password=PASSWORD, username="staff") == user

    def test_inactive_user_rejected(self):
        UtilisateurFactory(username="staff", is_active=False)
        assert auth("staff") is None


@pytest.mark.django_db
class TestEmailLogin:
    def test_exact_email(self):
        user, _ = make_famille_with_parent("fam", "parent@example.org")
        assert auth("parent@example.org") == user

    @pytest.mark.parametrize(
        "stored, typed",
        [
            ("parent@example.org", "PARENT@EXAMPLE.ORG"),
            ("Parent@Example.org", "parent@example.org"),
            ("PARENT@example.ORG", "pArEnT@ExAmPlE.oRg"),
        ],
    )
    def test_email_is_case_insensitive(self, stored, typed):
        user, _ = make_famille_with_parent("fam", stored)
        assert auth(typed) == user

    def test_email_wrong_password(self):
        make_famille_with_parent("fam", "parent@example.org")
        assert auth("parent@example.org", "nope") is None

    def test_email_inactive_user_rejected(self):
        make_famille_with_parent("fam", "parent@example.org", is_active=False)
        assert auth("parent@example.org") is None

    def test_partial_email_does_not_match(self):
        make_famille_with_parent("fam", "parent@example.org")
        assert auth("parent@example") is None
        assert auth("arent@example.org") is None

    @pytest.mark.parametrize("typed", ["%@example.org", "p_rent@example.org", "%", "_%"])
    def test_like_wildcards_are_escaped(self, typed):
        """iexact becomes LIKE on SQLite: % and _ must not act as wildcards."""
        make_famille_with_parent("fam", "parent@example.org")
        assert auth(typed) is None

    def test_jeune_email_is_ignored(self):
        make_famille_with_parent("fam", "jeune@example.org", statut=Individu.STATUT_JEUNE)
        assert auth("jeune@example.org") is None

    def test_null_statut_email_is_accepted(self):
        """exclude(statut=JEUNE) must not drop individus whose statut is NULL."""
        user, _ = make_famille_with_parent("fam", "parent@example.org", statut=None)
        assert auth("parent@example.org") == user

    def test_non_titulaire_adult_email_logs_into_famille(self):
        user, famille = create_famille_user(username="fam")
        second = IndividuFactory(mail="second@example.org")
        RattachementFactory(individu=second, famille=famille, categorie=1, titulaire=False)
        assert auth("second@example.org") == user

    def test_orphan_individu_is_ignored(self):
        """An individu with no Rattachement must not crash the backend."""
        IndividuFactory(mail="orphan@example.org")
        assert auth("orphan@example.org") is None

    def test_famille_without_utilisateur_is_ignored(self):
        parent = IndividuFactory(mail="parent@example.org")
        RattachementFactory(individu=parent, famille=FamilleFactory(), categorie=1)
        assert auth("parent@example.org") is None

    def test_rattachement_with_utilisateur_is_preferred(self):
        """An individu attached to a famille without utilisateur and to one with
        an utilisateur logs into the latter."""
        user, famille = create_famille_user(username="fam")
        parent = IndividuFactory(mail="parent@example.org")
        RattachementFactory(individu=parent, famille=FamilleFactory(), categorie=1)
        RattachementFactory(individu=parent, famille=famille, categorie=1)
        assert auth("parent@example.org") == user

    def test_username_takes_precedence_over_email(self):
        """If the identifier is an existing username, the email fallback is not tried."""
        staff = UtilisateurFactory(username="shared@example.org")
        make_famille_with_parent("fam", "shared@example.org")
        assert auth("shared@example.org") == staff

    def test_duplicate_email_uses_first_individu(self):
        first, _ = make_famille_with_parent("fam1", "dup@example.org")
        make_famille_with_parent("fam2", "DUP@example.org")
        assert auth("dup@example.org") == first

    @pytest.mark.xfail(
        reason="SQLite LIKE is only case-insensitive for ASCII characters, "
        "so non-ASCII letters in an email are matched case-sensitively.",
        strict=True,
    )
    def test_non_ascii_email_is_case_insensitive(self):
        user, _ = make_famille_with_parent("fam", "élodie@example.org")
        assert auth("Élodie@example.org") == user


@pytest.mark.django_db
class TestMissingCredentials:
    @pytest.mark.parametrize("username", [None, ""])
    def test_empty_username_does_not_match_blank_emails(self, username):
        make_famille_with_parent("fam", "")
        assert auth(username) is None

    def test_missing_password(self):
        make_famille_with_parent("fam", "parent@example.org")
        assert auth("parent@example.org", None) is None


@pytest.fixture
def organisateur(db):
    cache.clear()
    yield OrganisateurFactory(pk=1)
    cache.clear()


@pytest.mark.django_db
class TestLoginFormWhitespace:
    """AuthenticationForm strips the username but never the password."""

    def _post(self, client, username, password=PASSWORD):
        return client.post(
            reverse("portail_connexion"),
            {"username": username, "password": password, "turnstile": "dummy"},
        )

    @pytest.mark.parametrize("typed", ["  parent@example.org  ", "\tParent@Example.org\n"])
    def test_email_surrounding_whitespace_is_stripped(self, client, organisateur, typed):
        user, _ = make_famille_with_parent("fam", "parent@example.org")
        response = self._post(client, typed)
        assert response.status_code == 302
        assert client.session["_auth_user_id"] == str(user.pk)

    def test_username_surrounding_whitespace_is_stripped(self, client, organisateur):
        user, _ = make_famille_with_parent("fam", "parent@example.org")
        response = self._post(client, "  fam  ")
        assert response.status_code == 302
        assert client.session["_auth_user_id"] == str(user.pk)

    def test_inner_whitespace_in_email_does_not_match(self, client, organisateur):
        make_famille_with_parent("fam", "parent@example.org")
        response = self._post(client, "parent @example.org")
        assert response.status_code == 200
        assert "_auth_user_id" not in client.session

    def test_password_whitespace_is_not_stripped(self, client, organisateur):
        make_famille_with_parent("fam", "parent@example.org")
        response = self._post(client, "parent@example.org", f" {PASSWORD} ")
        assert response.status_code == 200
        assert "_auth_user_id" not in client.session

    def test_staff_login_page_accepts_family_email(self, client, organisateur):
        user, _ = make_famille_with_parent("fam", "parent@example.org")
        response = self._post_staff(client, "PARENT@example.org")
        assert response.status_code == 302
        assert response.url == reverse("portail_accueil")
        assert client.session["_auth_user_id"] == str(user.pk)

    def _post_staff(self, client, username, password=PASSWORD):
        return client.post(
            "/connexion",
            {"username": username, "password": password, "turnstile": "dummy"},
        )
