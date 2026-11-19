"""Individu.mail is NOT NULL since it is no longer encrypted: code paths that
used to clear it with None must write an empty string instead."""

import json

import pytest
from core.models import Individu, PortailRenseignement
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory
from individus.views import effacer_familles
from outils.views.demandes_portail import Traiter_demande
from tests.unit.factories import (
    FamilleFactory,
    IndividuFactory,
    RattachementFactory,
    UtilisateurFactory,
)


def make_request(data=None):
    request = RequestFactory().post("/", data or {})
    SessionMiddleware(lambda r: None).process_request(request)
    request._messages = FallbackStorage(request)
    request.user = UtilisateurFactory()
    return request


@pytest.mark.django_db
def test_effacer_famille_vide_le_mail_des_individus(monkeypatch):
    monkeypatch.setattr(effacer_familles.time, "sleep", lambda _s: None)
    famille = FamilleFactory()
    individu = IndividuFactory(mail="parent@example.org")
    RattachementFactory(individu=individu, famille=famille, categorie=1)

    response = effacer_familles.Effacer(make_request({"coches": json.dumps([famille.pk])}))

    assert response.status_code == 200
    individu.refresh_from_db()
    assert individu.nom == "Individu effacé"
    assert individu.mail == ""


@pytest.mark.django_db
@pytest.mark.parametrize("nouvelle_valeur, attendu", [(None, ""), ("", ""), ("new@example.org", "new@example.org")])
def test_validation_demande_portail_mail(nouvelle_valeur, attendu):
    famille = FamilleFactory()
    individu = IndividuFactory(mail="old@example.org")
    demande = PortailRenseignement.objects.create(
        famille=famille,
        individu=individu,
        categorie="individu_coords",
        code="mail",
        nouvelle_valeur=json.dumps(nouvelle_valeur) if nouvelle_valeur is not None else None,
    )

    Traiter_demande(request=make_request(), demande=demande, etat="VALIDE")

    assert Individu.objects.get(pk=individu.pk).mail == attendu
