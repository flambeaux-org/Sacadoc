"""Shared fixtures for the family portal (`portail`) test suite.

The portal is the only interface exposed to external non-staff users, so these
fixtures build realistic families and keep the per-request caches clean between
tests (portail/views/base.py caches `parametres_portail`, `organisateur` and the
interface options in the Django cache, which would otherwise leak across tests).
"""

import pytest
from django.core.cache import cache

from tests.unit.factories import (
    OrganisateurFactory,
    UtilisateurFactory,
    create_famille_complete,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """base.py caches portail params/organisateur — clear before & after each test."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def organisateur(db):
    """Most portail pages read Organisateur pk=1 (cached in base.py)."""
    return OrganisateurFactory(pk=1)


@pytest.fixture
def famille_user(db, organisateur):
    """A complete portail family: (user, famille, rattachements).

    rattachements[0] is the titulaire adult, rattachements[1] the child.
    """
    return create_famille_complete(username="famille_a")


@pytest.fixture
def other_famille(db, organisateur):
    """A second, unrelated family — used for cross-family authorization tests."""
    return create_famille_complete(username="famille_b")


@pytest.fixture
def staff_user(db):
    """A staff (categorie='utilisateur') user — must be denied on portail routes."""
    return UtilisateurFactory(username="staff_member")


@pytest.fixture
def logged_client(client, famille_user):
    """A Django test client already logged in as the famille portail user."""
    user, _famille, _ratt = famille_user
    client.force_login(user)
    return client
