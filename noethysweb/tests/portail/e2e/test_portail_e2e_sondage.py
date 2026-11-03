"""E2E: a family answers a multi-page survey (sondage) in the browser."""

import pytest
from core.models import (
    SondagePage,
    SondageQuestion,
    SondageRepondant,
    SondageReponse,
)
from playwright.sync_api import Page, expect
from tests.unit.factories import SondageFactory


@pytest.fixture
def sondage_deux_pages(db):
    sondage = SondageFactory(
        public="famille",
        titre="Enquete E2E",
        conclusion="Merci pour vos reponses E2E",
        description="Introduction E2E",
    )
    page1 = SondagePage.objects.create(sondage=sondage, titre="Page un", ordre=1)
    page2 = SondagePage.objects.create(sondage=sondage, titre="Page deux", ordre=2)
    q_obligatoire = SondageQuestion.objects.create(
        page=page1, label="Votre avis", controle="bloc_texte", ordre=1, obligatoire=True
    )
    q_choix = SondageQuestion.objects.create(
        page=page2,
        label="Votre choix",
        controle="liste_deroulante",
        ordre=1,
        choix="Pommes;Poires",
    )
    return sondage, q_obligatoire, q_choix


@pytest.mark.django_db
def test_sondage_answered_end_to_end(
    auto_login_user, famille_user, live_server, sondage_deux_pages, page: Page
):
    user, famille, _ratt = famille_user
    sondage, q_avis, q_choix = sondage_deux_pages
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page = auto_login_user(user)

    page.goto(f"{live_server.url}/sondage/{sondage.code}")
    expect(page.get_by_text("Introduction E2E")).to_be_visible()
    page.get_by_role("link", name="Commencer").click()
    expect(page).to_have_url(f"{live_server.url}/sondage/questions/{sondage.code}")

    page.locator(f"[name='question_{q_avis.pk}']").fill("Super avis")
    page.get_by_role("button", name="Suivant").click()
    expect(page.locator("#page-2")).to_be_visible()

    page.locator(f"[name='question_{q_choix.pk}']").select_option(label="Poires")
    page.get_by_role("button", name="Envoyer").click()

    expect(page).to_have_url(f"{live_server.url}/sondage/conclusion/{sondage.code}")
    expect(page.get_by_text("Merci pour vos reponses E2E")).to_be_visible()

    assert not errors, errors
    repondant = SondageRepondant.objects.get(sondage=sondage, famille=famille)
    reponses = {
        r.question_id: r.reponse
        for r in SondageReponse.objects.filter(repondant=repondant)
    }
    assert reponses[q_avis.pk] == "Super avis"
    assert reponses[q_choix.pk] == "Poires"


@pytest.mark.django_db
def test_sondage_submit_blocked_when_required_empty(
    auto_login_user, famille_user, live_server, page: Page
):
    user, _famille, _ratt = famille_user
    sondage = SondageFactory(public="famille", conclusion="ok")
    p = SondagePage.objects.create(sondage=sondage, titre="Unique", ordre=1)
    q = SondageQuestion.objects.create(
        page=p, label="Obligatoire", controle="bloc_texte", ordre=1, obligatoire=True
    )
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/sondage/questions/{sondage.code}")

    page.get_by_role("button", name="Envoyer").click()
    # Native HTML5 validation blocks the submit: the field is flagged invalid.
    expect(page.locator(f"[name='question_{q.pk}']:invalid")).to_have_count(1)
    expect(page).to_have_url(f"{live_server.url}/sondage/questions/{sondage.code}")
    assert not SondageRepondant.objects.filter(sondage=sondage).exists()

    page.locator(f"[name='question_{q.pk}']").fill("rempli")
    page.get_by_role("button", name="Envoyer").click()
    expect(page).to_have_url(f"{live_server.url}/sondage/conclusion/{sondage.code}")
    assert SondageReponse.objects.filter(question=q, reponse="rempli").exists()


@pytest.mark.django_db
def test_sondage_individu_per_child(
    auto_login_user, famille_user, live_server, page: Page
):
    user, famille, ratt = famille_user
    enfant = ratt[1].individu
    sondage = SondageFactory(
        public="individu", conclusion="ok", categories_rattachements="2"
    )
    p = SondagePage.objects.create(sondage=sondage, titre="Unique", ordre=1)
    q = SondageQuestion.objects.create(
        page=p, label="Age ?", controle="entier", ordre=1
    )
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/sondage/{sondage.code}")

    page.get_by_role("link", name="Commencer").click()
    page.locator(f"[name='question_{q.pk}']").fill("7")
    page.get_by_role("button", name="Envoyer").click()
    expect(page).to_have_url(f"{live_server.url}/sondage/conclusion/{sondage.code}")

    repondant = SondageRepondant.objects.get(sondage=sondage, famille=famille)
    assert repondant.individu_id == enfant.pk
    assert SondageReponse.objects.get(repondant=repondant, question=q).reponse == "7"


@pytest.mark.django_db
def test_sondage_stepper_blocks_next_when_required_empty(
    auto_login_user, famille_user, live_server, sondage_deux_pages, page: Page
):
    user, _famille, _ratt = famille_user
    sondage, _q_avis, _q_choix = sondage_deux_pages
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/sondage/questions/{sondage.code}")

    page.get_by_role("button", name="Suivant").click()
    expect(page.locator("label.error")).to_contain_text("obligatoire")
    expect(page.locator("#page-2")).not_to_be_visible()


@pytest.mark.django_db
@pytest.mark.xfail(
    reason="BUG: after a failed validation on 'Suivant', bs-stepper's internal index has already "
    "been incremented (next() bumps _currentIndex before show.bs-stepper is cancelled), so "
    "the next click on 'Suivant' after fixing the field does nothing "
    "(portail/templates/portail/sondage/sondage_questions.html, stepper1.next())",
    strict=True,
)
def test_sondage_stepper_next_works_after_fixing_validation_error(
    auto_login_user, famille_user, live_server, sondage_deux_pages, page: Page
):
    user, _famille, _ratt = famille_user
    sondage, q_avis, _q_choix = sondage_deux_pages
    page = auto_login_user(user)
    page.goto(f"{live_server.url}/sondage/questions/{sondage.code}")

    page.get_by_role("button", name="Suivant").click()
    expect(page.locator("label.error")).to_be_visible()

    page.locator(f"[name='question_{q_avis.pk}']").fill("Super avis")
    page.get_by_role("button", name="Suivant").click()
    expect(page.locator("#page-2")).to_be_visible(timeout=2000)
