"""E2E: the inscription wizard's structure -> activité AJAX cascade.

The full submission (tarifs + pieces via Valid_form) needs the whole tariff
object graph; this verifies the key in-browser behaviour: choosing a structure
populates the activity dropdown via AJAX (get_activites_par_structure).
"""

import pytest
from playwright.sync_api import Page, expect

from tests.unit.factories import ActiviteFactory, GroupeFactory, StructureFactory


@pytest.mark.django_db
def test_structure_change_populates_activities(
    auto_login_user, famille_user, live_server, page: Page
):
    user, _famille, _ratt = famille_user
    structure = StructureFactory(visible=True)
    activite = ActiviteFactory(structure=structure, visible=True, nom="Camp Été")
    GroupeFactory(activite=activite)

    page = auto_login_user(user)
    page.goto(f"{live_server.url}/activites/inscrire")

    page.select_option("#id_structure", str(structure.pk))

    # The change handler AJAX-loads the activities into #id_activite.
    option = page.locator(f"#id_activite option[value='{activite.pk}']")
    expect(option).to_have_count(1)
    expect(option).to_have_text("Camp Été")
