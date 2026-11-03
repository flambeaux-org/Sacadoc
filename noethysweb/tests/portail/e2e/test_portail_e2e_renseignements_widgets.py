"""E2E: JS widgets of the renseignements fiches (select2 multi-select + "add" modals)."""

import pytest
from core.models import (
    Assurance,
    Assureur,
    Medecin,
    RegimeAlimentaire,
    TypeAllergie,
    TypeMaladie,
)
from playwright.sync_api import Page, expect

MULTI_CASES = [
    # (page slug, select id, model, M2M attribute on Individu, new label)
    (
        "regimes_alimentaires",
        "id_regimes_alimentaires",
        RegimeAlimentaire,
        "regimes_alimentaires",
        "Sans gluten E2E",
    ),
    ("maladies", "id_maladies", TypeMaladie, "maladies", "Varicelle E2E"),
    ("allergies", "id_allergies", TypeAllergie, "allergies", "Arachide E2E"),
]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "slug,select_id,model,attr,label", MULTI_CASES, ids=[c[0] for c in MULTI_CASES]
)
def test_add_item_through_modal_and_save(
    auto_login_user,
    famille_user,
    live_server,
    page: Page,
    slug,
    select_id,
    model,
    attr,
    label,
):
    user, _famille, ratt = famille_user
    enfant = ratt[1].individu
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page = auto_login_user(user)

    page.goto(f"{live_server.url}/renseignements/individu/{slug}/modifier/{ratt[1].pk}")
    expect(page.locator(f"#{select_id}")).to_have_count(1)

    # "Cliquez ici pour ajouter ..." link -> bootbox confirmation -> modal with a text input.
    page.locator("a.ajouter_element").click()
    page.locator(".bootbox").get_by_role("button", name="Oui").click()
    modal = page.locator(f"#{select_id}_modal_modification")
    expect(modal).to_be_visible()

    modal.locator(f"#{select_id}_champ_saisie").fill(label)
    modal.get_by_role("button", name="Valider").click()
    expect(modal).not_to_be_visible()

    # The new item exists in DB and is already selected in the widget.
    nouveau = model.objects.get(nom=label)
    expect(page.locator(f"#{select_id} option[value='{nouveau.pk}']")).to_have_count(1)
    assert str(nouveau.pk) in page.locator(f"#{select_id}").evaluate(
        "el => $(el).val()"
    )

    page.get_by_role("button", name="Enregistrer").click()
    expect(page).to_have_url(
        f"{live_server.url}/renseignements/individu/{slug}/{ratt[1].pk}"
    )
    assert getattr(enfant, attr).filter(pk=nouveau.pk).exists()
    assert not errors, errors


@pytest.mark.django_db
def test_add_regime_empty_name_shows_toast(
    auto_login_user, famille_user, live_server, page: Page
):
    user, _famille, ratt = famille_user
    page = auto_login_user(user)
    page.goto(
        f"{live_server.url}/renseignements/individu/regimes_alimentaires/modifier/{ratt[1].pk}"
    )

    page.locator("a.ajouter_element").click()
    page.locator(".bootbox").get_by_role("button", name="Oui").click()
    modal = page.locator("#id_regimes_alimentaires_modal_modification")
    expect(modal).to_be_visible()
    modal.get_by_role("button", name="Valider").click()

    expect(page.locator(".toast-error")).to_contain_text(
        "Veuillez saisir un nom valide"
    )
    assert RegimeAlimentaire.objects.count() == 0


@pytest.mark.django_db
def test_add_regime_declined_does_not_open_modal(
    auto_login_user, famille_user, live_server, page: Page
):
    user, _famille, ratt = famille_user
    page = auto_login_user(user)
    page.goto(
        f"{live_server.url}/renseignements/individu/regimes_alimentaires/modifier/{ratt[1].pk}"
    )

    page.locator("a.ajouter_element").click()
    page.locator(".bootbox").get_by_role("button", name="Non").click()
    expect(
        page.locator("#id_regimes_alimentaires_modal_modification")
    ).not_to_be_visible()


@pytest.mark.django_db
def test_add_medecin_through_modal_and_save(
    auto_login_user, famille_user, live_server, page: Page
):
    user, _famille, ratt = famille_user
    enfant = ratt[1].individu
    page = auto_login_user(user)
    page.goto(
        f"{live_server.url}/renseignements/individu/medecin/modifier/{ratt[1].pk}"
    )

    page.locator("a.ajouter_element").click()
    page.locator(".bootbox").get_by_role("button", name="Oui").click()
    modal = page.locator("#id_medecin_modal_ajout")
    expect(modal).to_be_visible()
    modal.locator("#id_nom").fill("dupont")
    modal.locator("#id_prenom").fill("jeanne")
    modal.locator("#id_rue_resid").fill("1 rue des tests")
    modal.locator("#id_cp_resid").fill("75001")
    modal.locator("#id_ville_resid").fill("paris")
    modal.locator("#id_medecin_bouton_valider").click()
    expect(modal).not_to_be_visible()

    medecin = Medecin.objects.get(nom="DUPONT")
    assert medecin.ville_resid == "PARIS"
    assert page.locator("#id_medecin").evaluate("el => $(el).val()") == str(medecin.pk)

    page.get_by_role("button", name="Enregistrer").click()
    expect(page).to_have_url(
        f"{live_server.url}/renseignements/individu/medecin/{ratt[1].pk}"
    )
    enfant.refresh_from_db()
    assert enfant.medecin_id == medecin.pk


@pytest.mark.django_db
def test_add_medecin_invalid_shows_error_toast(
    auto_login_user, famille_user, live_server, page: Page
):
    user, _famille, ratt = famille_user
    page = auto_login_user(user)
    page.goto(
        f"{live_server.url}/renseignements/individu/medecin/modifier/{ratt[1].pk}"
    )

    page.locator("a.ajouter_element").click()
    page.locator(".bootbox").get_by_role("button", name="Oui").click()
    modal = page.locator("#id_medecin_modal_ajout")
    expect(modal).to_be_visible()
    # nom is required: server answers 401 + message, shown as a toast; modal stays open.
    modal.locator("#id_medecin_bouton_valider").click()
    expect(page.locator(".toast-error")).to_be_visible()
    expect(modal).to_be_visible()
    assert Medecin.objects.count() == 0


@pytest.mark.django_db
def test_add_assureur_through_modal_and_create_assurance(
    auto_login_user, famille_user, live_server, page: Page
):
    user, _famille, ratt = famille_user
    enfant = ratt[1].individu
    page = auto_login_user(user)
    page.goto(
        f"{live_server.url}/renseignements/individu/assurances/ajouter/{ratt[1].pk}"
    )

    page.locator("a.ajouter_element").click()
    page.locator(".bootbox").get_by_role("button", name="Oui").click()
    modal = page.locator("#id_assureur_modal_ajout")
    expect(modal).to_be_visible()
    modal.locator("#id_nom").fill("maif e2e")
    modal.locator("#id_assureur_bouton_valider").click()
    expect(modal).not_to_be_visible()

    assureur = Assureur.objects.get(nom="MAIF E2E")
    assert page.locator("#id_assureur").evaluate("el => $(el).val()") == str(
        assureur.pk
    )

    page.locator("#id_num_contrat").fill("CONTRAT-E2E-1")
    page.get_by_role("button", name="Enregistrer").click()
    expect(page).to_have_url(
        f"{live_server.url}/renseignements/individu/assurances/liste/{ratt[1].pk}"
    )
    # num_contrat is an encrypted field (no DB lookup): compare in Python.
    assurance = Assurance.objects.get(individu=enfant, assureur=assureur)
    assert assurance.num_contrat == "CONTRAT-E2E-1"
