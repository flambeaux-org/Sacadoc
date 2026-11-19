"""Modifier un règlement qui n'existe plus (supprimé depuis un autre onglet, retour arrière,
favori…) doit renvoyer une 404 et non une 500 (DoesNotExist dans Modifier.dispatch)."""

import pytest
from django.http import Http404
from django.test import RequestFactory
from fiche_famille.views.famille_reglements import Modifier
from tests.unit.factories import FamilleFactory, UtilisateurFactory


@pytest.mark.django_db
def test_modifier_reglement_inexistant_renvoie_404():
    famille = FamilleFactory()
    request = RequestFactory().get("/")
    request.user = UtilisateurFactory()

    with pytest.raises(Http404):
        Modifier.as_view()(request, idfamille=famille.pk, pk=999999)
