"""Shared fixtures for the staff ("bureau" / director) test suite.

The bureau lives under /utilisateur/ and is only reachable by users of
categorie='utilisateur'. These fixtures build a director attached to a
structure and a family inscribed on one of that structure's activities, so the
family shows up in the scoped lists (famille_liste only shows families with an
inscription on an activity of the user's structures).
"""

import datetime

# django_select2 registers its default settings (SELECT2_THEME...) on django.conf.settings when its conf
# module is first imported. If that first import happens inside a test using pytest-django's `settings`
# fixture, the fixture removes them on teardown and every later test rendering a Select2 widget crashes.
import django_select2.conf  # noqa: F401
import pytest
from django.core.cache import cache
from django.db.models.fields.files import FieldFile
from tests.unit.factories import (
    ActiviteFactory,
    InscriptionFactory,
    OrganisateurFactory,
    StructureFactory,
    UtilisateurFactory,
    create_famille_complete,
)


AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


def build_form_data(form, **overrides):
    """Build POST data from a bound-less form's initial values, then apply overrides."""
    data = {}
    for name in form.fields:
        val = form.initial.get(name, form.fields[name].initial)
        if val is None or isinstance(val, FieldFile) or hasattr(val, "read"):
            continue
        if hasattr(val, "pk"):
            val = val.pk
        elif isinstance(val, (list, tuple)):
            val = [getattr(v, "pk", v) for v in val]
        elif hasattr(val, "isoformat"):
            val = val.isoformat()
        data[name] = val
    data.update(overrides)
    return data


@pytest.fixture(autouse=True)
def reset_portail_parametres():
    """utils_portail.Get_dict_parametres() writes PortailParametre values onto the module-level
    LISTE_PARAMETRES; restore them so a parameter set in one test does not leak into the next."""
    from core.utils import utils_portail

    parametres = [(p, p.valeur) for p in utils_portail.LISTE_PARAMETRES]
    yield
    for parametre, valeur in parametres:
        parametre.valeur = valeur


@pytest.fixture
def set_parametre_portail(db):
    """Persist a portail parameter, e.g. set_parametre_portail("connexion_adresse_exp", adresse.pk)."""
    from core.models import PortailParametre

    def _set(code, valeur):
        PortailParametre.objects.update_or_create(code=code, defaults={"valeur": str(valeur)})
        cache.clear()

    return _set


@pytest.fixture(autouse=True)
def clear_cache():
    """base.py caches the organisateur and the user interface options."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def organisateur(db):
    return OrganisateurFactory(pk=1)


@pytest.fixture
def structure(db):
    return StructureFactory(nom="Structure du directeur")


@pytest.fixture
def activite(db, structure):
    return ActiviteFactory(structure=structure, nom="Centre de loisirs")


@pytest.fixture
def directeur(db, organisateur, structure):
    """A staff superuser (all permissions) attached to `structure`."""
    user = UtilisateurFactory(username="directeur")
    user.structures.add(structure)
    return user


@pytest.fixture
def directeur_client(client, directeur):
    client.force_login(directeur)
    return client


@pytest.fixture
def famille_bureau(db, organisateur, activite):
    """(famille, titulaire, enfant): a complete family whose child is inscribed on `activite`."""
    _user, famille, ratt = create_famille_complete(username="famille_bureau")
    titulaire, enfant = ratt[0].individu, ratt[1].individu
    InscriptionFactory(
        famille=famille,
        individu=enfant,
        activite=activite,
        date_debut=datetime.date(2020, 1, 1),
    )
    famille.Maj_infos()
    return famille, titulaire, enfant
