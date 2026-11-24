"""Ouvrir un onglet de la fiche d'une famille qui n'existe plus (supprimée, favori, retour
arrière…) doit renvoyer une 404 et non une 500 (DoesNotExist dans Onglet.get_context_data
ou dans get_object)."""

import pytest
from django.urls import reverse
from tests.unit.factories import UtilisateurFactory

IDFAMILLE_INEXISTANT = 999999


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url_name",
    [
        "famille_resume",
        "famille_pieces_liste",
        "famille_reglements_liste",
        "famille_outils",
        "famille_historique",
    ],
)
def test_onglet_famille_inexistante_renvoie_404(client, url_name):
    client.force_login(UtilisateurFactory())
    response = client.get(reverse(url_name, kwargs={"idfamille": IDFAMILLE_INEXISTANT}))
    assert response.status_code == 404
