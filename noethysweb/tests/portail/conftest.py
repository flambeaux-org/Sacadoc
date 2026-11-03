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
def reset_portail_parametres():
    """Restore module-level portail config objects that the app mutates in place.

    - utils_portail.Get_dict_parametres() writes PortailParametre values onto LISTE_PARAMETRES (From_db).
    - utils_champs.Get_liste_champs() writes PortailChamp values onto LISTE_CHAMPS (shallow copy.copy).

    Without this, a PortailParametre/PortailChamp created in one test keeps its effect in every
    later test even after the DB rollback (see TEST_PLAN.md bug #8)."""
    from core.utils import utils_portail
    from portail.utils import utils_champs

    parametres = [(p, p.valeur) for p in utils_portail.LISTE_PARAMETRES]
    champs_attrs = ("representant", "enfant", "contact", "famille")
    champs = [
        (c, {a: getattr(c, a) for a in champs_attrs}) for c in utils_champs.LISTE_CHAMPS
    ]
    yield
    for parametre, valeur in parametres:
        parametre.valeur = valeur
    for champ, attrs in champs:
        for attr, valeur in attrs.items():
            setattr(champ, attr, valeur)


@pytest.fixture
def set_parametre_portail(db):
    """Persist a portail parameter, e.g. set_parametre_portail("facturation_afficher_solde_famille", True)."""
    from core.models import PortailParametre

    def _set(code, valeur):
        PortailParametre.objects.update_or_create(
            code=code, defaults={"valeur": str(valeur)}
        )
        cache.clear()

    return _set


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


@pytest.fixture
def reglement_modelimp_workaround(monkeypatch, db):
    """Work around the known bug (Reglement.modelimp is NOT NULL but never set by
    facturation.py) so the code *after* Reglement creation can be exercised.

    Wraps `portail.views.facturation.Reglement` so that `.objects.create()` receives a
    default `modelimp`. Tests relying on it do not hide the bug: dedicated xfail tests
    run without the fixture (see TEST_PLAN.md)."""
    import json
    from types import SimpleNamespace

    from core.models import ModeleImpression
    from portail.views import facturation

    modele = ModeleImpression.objects.create(
        categorie="reglement",
        nom="Modele par defaut reglement",
        options=json.dumps(
            {
                "signataire": "Le tresorier",
                "intro": "Recu",
                "afficher_prestations": False,
            }
        ),
    )
    real = facturation.Reglement

    class _Objects:
        def __getattr__(self, name):
            return getattr(real.objects, name)

        def create(self, **kwargs):
            kwargs.setdefault("modelimp", modele)
            return real.objects.create(**kwargs)

    monkeypatch.setattr(facturation, "Reglement", SimpleNamespace(objects=_Objects()))
    return modele
