"""Render-smoke tests for the renseignements fiches (individual + family).

Each individual fiche is parameterized by the family's child rattachement.
"""

import pytest
from django.urls import reverse

# Individual fiche consultation pages (take idrattachement).
INDIVIDU_CONSULTER_ROUTES = [
    "portail_individu_identite",
    "portail_individu_questionnaire",
    "portail_individu_coords",
    "portail_individu_regimes_alimentaires",
    "portail_individu_maladies",
    "portail_individu_allergies",
    "portail_individu_dispmed",
    "portail_individu_traitement",
    "portail_individu_medecin",
    "portail_individu_vaccinations",
    "portail_individu_informations",
    "portail_individu_assurances",
    "portail_individu_contacts",
]

# Individual fiche edit/add pages (take idrattachement).
INDIVIDU_FORM_ROUTES = [
    "portail_individu_identite_modifier",
    "portail_individu_coords_modifier",
    "portail_individu_regimes_alimentaires_modifier",
    "portail_individu_maladies_modifier",
    "portail_individu_allergies_modifier",
    "portail_individu_dispmed_modifier",
    "portail_individu_medecin_modifier",
    "portail_individu_vaccinations_ajouter",
    "portail_individu_informations_ajouter",
    "portail_individu_assurances_ajouter",
    "portail_individu_contacts_ajouter",
]

FAMILLE_ROUTES = [
    "portail_famille_caisse",
    "portail_famille_caisse_modifier",
    "portail_famille_questionnaire",
    "portail_famille_parametres",
]


def form_post_data(form):
    """Build a POST payload from a bound form's initial values.

    Skips file/image fields (empty FieldFiles break multipart encoding) and
    ISO-formats dates so the fr-locale DATE_INPUT_FORMATS accept them.
    """
    from django.db.models.fields.files import FieldFile

    data = {}
    for name in form.fields:
        val = form.initial.get(name, form.fields[name].initial)
        if val is None:
            continue
        if isinstance(val, FieldFile) or hasattr(val, "read"):  # file field
            continue
        if hasattr(val, "isoformat"):  # date / datetime
            val = val.isoformat()
        data[name] = val
    return data


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", INDIVIDU_CONSULTER_ROUTES)
def test_individu_consulter_renders(logged_client, famille_user, route_name):
    _user, _famille, ratt = famille_user
    url = reverse(route_name, kwargs={"idrattachement": ratt[1].pk})
    response = logged_client.get(url)
    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", INDIVIDU_FORM_ROUTES)
def test_individu_form_renders(logged_client, famille_user, route_name):
    _user, _famille, ratt = famille_user
    url = reverse(route_name, kwargs={"idrattachement": ratt[1].pk})
    response = logged_client.get(url)
    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("route_name", FAMILLE_ROUTES)
def test_famille_page_renders(logged_client, route_name):
    response = logged_client.get(reverse(route_name))
    assert response.status_code == 200


@pytest.mark.django_db
def test_identite_modifier_saves_change(logged_client, famille_user):
    """Editing identity (validation_auto=True) persists the change to the Individu."""
    from core.models import Individu

    _user, _famille, ratt = famille_user
    enfant = ratt[1].individu
    url = reverse("portail_individu_identite_modifier", kwargs={"idrattachement": ratt[1].pk})
    response = logged_client.get(url)
    assert response.status_code == 200

    data = form_post_data(response.context["form"])
    data["nom"] = "NouveauNom"

    post = logged_client.post(url, data)
    assert post.status_code == 302
    assert Individu.objects.get(pk=enfant.pk).nom == "NouveauNom"


@pytest.mark.xfail(
    reason="BUG: utils_onglets.py:27 has the 'famille_parametres' onglet commented out, "
    "so Get_onglet returns None and famille_parametres.Modifier.get_context_data "
    "crashes on .validation_auto (500). See TEST_PLAN.md.",
    strict=True,
)
@pytest.mark.django_db
def test_famille_parametres_modifier_renders(logged_client):
    response = logged_client.get(reverse("portail_famille_parametres_modifier"))
    assert response.status_code == 200
