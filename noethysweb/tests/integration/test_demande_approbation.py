import datetime

import pytest

from core.models import (
    Activite,
    Famille,
    Groupe,
    Individu,
    Inscription,
    Rattachement,
)
from tests.unit.factories import StructureFactory, UtilisateurFactory


def _build_inscription(activite, groupe, nom, certification_date):
    individu = Individu.objects.create(nom=nom)
    famille = Famille.objects.create()
    Rattachement.objects.create(
        individu=individu,
        famille=famille,
        categorie=1,
        titulaire=True,
        certification_date=certification_date,
    )
    return Inscription.objects.create(
        individu=individu,
        famille=famille,
        activite=activite,
        groupe=groupe,
        date_debut=datetime.date(2026, 1, 1),
    )


def _datatable_params(order_dir="asc"):
    """Reproduces the DataTables AJAX query, ordering by the date column."""
    params = {"draw": "2"}
    for index, name in enumerate(
        ["individu", "besoin_certification", "last_approbation", "actions"]
    ):
        params[f"columns[{index}][data]"] = str(index)
        params[f"columns[{index}][name]"] = name
        params[f"columns[{index}][searchable]"] = "true"
        params[f"columns[{index}][orderable]"] = "true"
        params[f"columns[{index}][search][value]"] = ""
        params[f"columns[{index}][search][regex]"] = "false"
    params["order[0][column]"] = "2"  # date-de-derniere-verification
    params["order[0][dir]"] = order_dir
    params["start"] = "0"
    params["length"] = "100"
    params["search[value]"] = ""
    params["search[regex]"] = "false"
    return params


@pytest.mark.django_db
class TestDemandeApprobationSort:
    def _setup(self):
        structure = StructureFactory()
        user = UtilisateurFactory(username="staff_approbation")
        user.structures.add(structure)

        activite = Activite.objects.create(
            nom="Camp", abrege="C", structure=structure, visible=True
        )
        groupe = Groupe.objects.create(activite=activite, nom="Groupe", ordre=1)

        # One individu already verified (datetime), one never verified (None):
        # the mix used to break the Python-side sort of the virtual column.
        _build_inscription(
            activite, groupe, "AVEC", datetime.datetime(2026, 6, 1, 10, 0)
        )
        _build_inscription(activite, groupe, "SANS", None)
        return user, activite

    def test_sort_by_date_does_not_crash(self, client):
        user, activite = self._setup()
        client.force_login(user)
        response = client.get(
            f"/utilisateur/individus/approbation/{activite.pk}",
            data=_datatable_params("asc"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 200

    def test_sort_by_date_desc_does_not_crash(self, client):
        user, activite = self._setup()
        client.force_login(user)
        response = client.get(
            f"/utilisateur/individus/approbation/{activite.pk}",
            data=_datatable_params("desc"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        assert response.status_code == 200
