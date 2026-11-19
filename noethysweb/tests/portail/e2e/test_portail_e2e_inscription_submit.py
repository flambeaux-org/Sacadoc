"""E2E: full inscription wizard in the browser (structure -> activite -> groupe -> tarif -> submit)."""

import datetime
import json

import pytest
from core.models import NomTarif, PortailRenseignement, Tarif
from playwright.sync_api import Page, expect
from tests.unit.factories import ActiviteFactory, GroupeFactory, StructureFactory


@pytest.fixture
def wizard_graph(db):
    structure = StructureFactory(visible=True, nom="Structure Wizard")
    activite = ActiviteFactory(structure=structure, visible=True, nom="Camp Wizard")
    groupe = GroupeFactory(activite=activite, nom="Groupe Wizard")
    nom_tarif = NomTarif.objects.create(activite=activite, nom="Formule", visible=True)
    tarif = Tarif.objects.create(
        activite=activite,
        nom_tarif=nom_tarif,
        type="FORFAIT",
        date_debut=datetime.date(2020, 1, 1),
        description="Semaine complete",
    )
    return structure, activite, groupe, tarif


def _fill_wizard(page, structure, activite):
    page.select_option("#id_structure", str(structure.pk))
    expect(page.locator(f"#id_activite option[value='{activite.pk}']")).to_have_count(1)
    page.select_option("#id_activite", str(activite.pk))
    # Groupe select is filled client-side and the extra form (tarifs) is loaded by AJAX.
    expect(page.locator("#id_groupe option")).to_have_count(1)


@pytest.mark.django_db
def test_inscription_happy_path_creates_demande(
    auto_login_user, famille_user, live_server, wizard_graph, page: Page
):
    user, famille, ratt = famille_user
    enfant = ratt[1].individu
    # Individu.STATUT_JEUNE: parents/staff statuts are refused on a "maitrise" activity.
    enfant.statut = 5
    enfant.save()
    structure, activite, groupe, tarif = wizard_graph
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/activites/inscrire")

    page.select_option("#id_individu", str(enfant.pk))
    _fill_wizard(page, structure, activite)
    expect(page.locator("#id_groupe")).to_have_value(str(groupe.pk))

    # Extra form: choose the tarif radio.
    radio = page.locator(f"#form_extra input[type='radio'][value='{tarif.pk}']")
    expect(radio).to_be_visible()
    expect(page.locator("#form_extra")).to_contain_text("Semaine complete")
    page.locator(f"label[for='{radio.get_attribute('id')}']").click()
    expect(radio).to_be_checked()

    page.get_by_role("button", name="Envoyer la demande").click()
    expect(page).to_have_url(f"{live_server.url}/activites")

    demande = PortailRenseignement.objects.get(
        famille=famille, code="inscrire_activite"
    )
    assert demande.individu_id == enfant.pk
    assert demande.etat == "ATTENTE"
    assert demande.activite_id == activite.pk
    valeur = json.loads(demande.nouvelle_valeur)
    assert valeur.startswith(f"{activite.pk};{groupe.pk};")
    assert str(tarif.pk) in valeur


@pytest.mark.django_db
def test_inscription_submit_without_selection_is_blocked(
    auto_login_user, famille_user, live_server, wizard_graph, page: Page
):
    user, famille, _ratt = famille_user
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/activites/inscrire")

    page.get_by_role("button", name="Envoyer la demande").click()

    # Native HTML5 validation (required select) stops the submit before any request.
    expect(page.locator("#id_structure:invalid")).to_have_count(1)
    expect(page).to_have_url(f"{live_server.url}/activites/inscrire")
    assert not PortailRenseignement.objects.filter(famille=famille).exists()


@pytest.mark.django_db
def test_inscription_submit_without_tarif_shows_server_error(
    auto_login_user, famille_user, live_server, wizard_graph, page: Page
):
    user, famille, _ratt = famille_user
    structure, activite, _groupe, _tarif = wizard_graph
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/activites/inscrire")
    _fill_wizard(page, structure, activite)
    expect(page.locator("#form_extra input[type='radio']")).to_be_visible()

    page.get_by_role("button", name="Envoyer la demande").click()

    expect(page.locator(".toast-error")).to_contain_text("au moins un tarif")
    # The button is re-enabled after the failure so the user can retry.
    expect(page.get_by_role("button", name="Envoyer la demande")).to_be_enabled()
    assert not PortailRenseignement.objects.filter(famille=famille).exists()


@pytest.mark.django_db
def test_inscription_duplicate_pending_request_rejected(
    auto_login_user, famille_user, live_server, wizard_graph, page: Page
):
    user, famille, ratt = famille_user
    enfant = ratt[1].individu
    # Individu.STATUT_JEUNE: parents/staff statuts are refused on a "maitrise" activity.
    enfant.statut = 5
    enfant.save()
    structure, activite, groupe, _tarif = wizard_graph
    PortailRenseignement.objects.create(
        famille=famille,
        individu=enfant,
        etat="ATTENTE",
        code="inscrire_activite",
        categorie="activites",
        activite=activite,
        nouvelle_valeur=json.dumps(f"{activite.pk};{groupe.pk};[]"),
    )
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/activites/inscrire")
    page.select_option("#id_individu", str(enfant.pk))
    _fill_wizard(page, structure, activite)
    page.locator("#form_extra label.custom-control-label").first.click()

    page.get_by_role("button", name="Envoyer la demande").click()

    expect(page.locator(".toast-error")).to_contain_text("demande en attente")
    assert (
        PortailRenseignement.objects.filter(
            famille=famille, code="inscrire_activite"
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_changing_structure_resets_activity_and_group(
    auto_login_user, famille_user, live_server, wizard_graph, page: Page
):
    user, _famille, _ratt = famille_user
    structure, activite, _groupe, _tarif = wizard_graph
    autre = StructureFactory(visible=True, nom="Autre structure")
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/activites/inscrire")
    expect(page.locator("#id_activite")).to_be_disabled()

    _fill_wizard(page, structure, activite)
    expect(page.locator("#form_extra")).not_to_be_empty()

    page.select_option("#id_structure", str(autre.pk))
    # No activity for the other structure: only the placeholder option remains.
    expect(page.locator("#id_activite option:not([value=''])")).to_have_count(0)
    expect(page.locator("#id_groupe")).to_be_disabled()


@pytest.mark.django_db
@pytest.mark.xfail(
    reason="BUG: changing the structure empties the activite/groupe selects but leaves the previous "
    "activity's tarif radios in #form_extra (portail/templates/portail/inscription_activite_custom.html, "
    "'#id_structure' change handler never calls $divExtra.empty() / $placeholder.show())",
    strict=True,
)
def test_changing_structure_clears_stale_tarifs(
    auto_login_user, famille_user, live_server, wizard_graph, page: Page
):
    user, _famille, _ratt = famille_user
    structure, activite, _groupe, _tarif = wizard_graph
    autre = StructureFactory(visible=True, nom="Autre structure")
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/activites/inscrire")
    _fill_wizard(page, structure, activite)
    expect(page.locator("#form_extra input[type='radio']")).to_have_count(1)

    page.select_option("#id_structure", str(autre.pk))
    expect(page.locator("#id_activite option:not([value=''])")).to_have_count(0)
    expect(page.locator("#form_extra input[type='radio']")).to_have_count(
        0, timeout=2000
    )
