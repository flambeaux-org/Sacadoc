"""Le registre de présence ne sait pointer que des dates : la configuration
doit refuser toute séance qui n'est pas une date JJ/MM/AAAA valide."""

import pytest
from parametrage.forms.config_registre import Formulaire
from tests.unit.factories import ActiviteFactory


def formulaire(date_seance, type_date="LST"):
    return Formulaire(
        data={"nom": "Registre", "activite": ActiviteFactory().pk, "type_date": type_date, "date_seance": date_seance}
    )


@pytest.mark.django_db
@pytest.mark.parametrize("date_seance", ["Week-end 12-13/10", "05/10/2026, samedi", "31/02/2026", "2026-10-05"])
def test_refuse_les_dates_invalides(date_seance):
    form = formulaire(date_seance)

    assert not form.is_valid()
    assert "date_seance" in form.errors


@pytest.mark.django_db
def test_normalise_les_dates():
    form = formulaire("10/10/2026, 5/10/2026,, 05/10/2026 ")

    assert form.is_valid(), form.errors
    assert form.cleaned_data["date_seance"] == "05/10/2026, 10/10/2026"


@pytest.mark.django_db
def test_ignore_le_champ_pour_un_registre_sur_les_dates_de_l_activite():
    form = formulaire("n'importe quoi", type_date="ACT")
    form.is_valid()

    assert "date_seance" not in form.errors
