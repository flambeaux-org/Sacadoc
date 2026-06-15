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


# ---------------------------------------------------------------------------
# Phase A: Modifier POST handlers — verify form saves reach the database
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_coords_modifier_saves(logged_client, famille_user):
    """POST to coords modifier persists the address change on Individu."""
    from core.models import Individu

    _user, _famille, ratt = famille_user
    enfant = ratt[1].individu
    url = reverse("portail_individu_coords_modifier", kwargs={"idrattachement": ratt[1].pk})
    data = form_post_data(logged_client.get(url).context["form"])
    data["rue_resid"] = "1 rue de la Paix"
    assert logged_client.post(url, data).status_code == 302
    assert Individu.objects.get(pk=enfant.pk).rue_resid == "1 rue de la Paix"


@pytest.mark.django_db
def test_regimes_alimentaires_modifier_saves(logged_client, famille_user):
    """POST with a RegimeAlimentaire PK links it to the individu via M2M."""
    from core.models import Individu, RegimeAlimentaire

    _user, _famille, ratt = famille_user
    enfant = ratt[1].individu
    regime = RegimeAlimentaire.objects.create(nom="Végétarien")
    url = reverse(
        "portail_individu_regimes_alimentaires_modifier",
        kwargs={"idrattachement": ratt[1].pk},
    )
    data = form_post_data(logged_client.get(url).context["form"])
    data["regimes_alimentaires"] = [regime.pk]
    assert logged_client.post(url, data).status_code == 302
    assert Individu.objects.get(pk=enfant.pk).regimes_alimentaires.filter(pk=regime.pk).exists()


@pytest.mark.django_db
def test_maladies_modifier_saves(logged_client, famille_user):
    """POST with a TypeMaladie PK links it to the individu via M2M."""
    from core.models import Individu, TypeMaladie

    _user, _famille, ratt = famille_user
    enfant = ratt[1].individu
    maladie = TypeMaladie.objects.create(nom="Varicelle")
    url = reverse("portail_individu_maladies_modifier", kwargs={"idrattachement": ratt[1].pk})
    data = form_post_data(logged_client.get(url).context["form"])
    data["maladies"] = [maladie.pk]
    assert logged_client.post(url, data).status_code == 302
    assert Individu.objects.get(pk=enfant.pk).maladies.filter(pk=maladie.pk).exists()


@pytest.mark.django_db
def test_allergies_modifier_saves(logged_client, famille_user):
    """POST to allergies modifier persists the free-text conduct field."""
    from core.models import Individu

    _user, _famille, ratt = famille_user
    enfant = ratt[1].individu
    url = reverse("portail_individu_allergies_modifier", kwargs={"idrattachement": ratt[1].pk})
    data = form_post_data(logged_client.get(url).context["form"])
    data["allergies_detail"] = "Éviter le gluten"
    assert logged_client.post(url, data).status_code == 302
    assert Individu.objects.get(pk=enfant.pk).allergies_detail == "Éviter le gluten"


@pytest.mark.django_db
def test_dispmed_modifier_saves(logged_client, famille_user):
    """POST to dispmed modifier persists the free-text conduct field."""
    from core.models import Individu

    _user, _famille, ratt = famille_user
    enfant = ratt[1].individu
    url = reverse("portail_individu_dispmed_modifier", kwargs={"idrattachement": ratt[1].pk})
    data = form_post_data(logged_client.get(url).context["form"])
    data["dispmed_detail"] = "Lunettes correctrices obligatoires"
    assert logged_client.post(url, data).status_code == 302
    assert Individu.objects.get(pk=enfant.pk).dispmed_detail == "Lunettes correctrices obligatoires"


@pytest.mark.django_db
def test_medecin_modifier_saves(logged_client, famille_user):
    """POST with a Medecin PK sets it as the individu's treating physician."""
    from core.models import Individu, Medecin

    _user, _famille, ratt = famille_user
    enfant = ratt[1].individu
    medecin = Medecin.objects.create(nom="Dupont")
    url = reverse("portail_individu_medecin_modifier", kwargs={"idrattachement": ratt[1].pk})
    data = form_post_data(logged_client.get(url).context["form"])
    data["medecin"] = medecin.pk
    assert logged_client.post(url, data).status_code == 302
    assert Individu.objects.get(pk=enfant.pk).medecin_id == medecin.pk


@pytest.mark.django_db
def test_individu_questionnaire_modifier_submits(logged_client, famille_user):
    """POST to the individu questionnaire modifier returns 302 (no questions configured → no-op)."""
    _user, _famille, ratt = famille_user
    url = reverse("portail_individu_questionnaire_modifier", kwargs={"idrattachement": ratt[1].pk})
    assert logged_client.get(url).status_code == 200
    assert logged_client.post(url, {}).status_code == 302


@pytest.mark.django_db
def test_famille_questionnaire_modifier_submits(logged_client):
    """POST to the famille questionnaire modifier returns 302 (no questions configured → no-op)."""
    url = reverse("portail_famille_questionnaire_modifier")
    assert logged_client.get(url).status_code == 200
    assert logged_client.post(url, {}).status_code == 302
