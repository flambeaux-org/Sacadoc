"""Tests for portail/views/cotisations.py (portail_cotisations)."""

import datetime

import pytest
from django.urls import reverse
from tests.unit.factories import ActiviteFactory, InscriptionFactory

URL = "portail_cotisations"


def _type(nom="Adhésion", type_="famille", activite=None):
    from core.models import TypeCotisation

    typ = TypeCotisation.objects.create(nom=nom, type=type_)
    if activite:
        activite.cotisations.add(typ)
    return typ


def _cotisation(
    famille,
    typ,
    individu=None,
    debut=datetime.date(2026, 1, 1),
    fin=datetime.date(2026, 12, 31),
):
    from core.models import Cotisation, UniteCotisation

    unite = UniteCotisation.objects.create(type_cotisation=typ, nom="Annuelle")
    return Cotisation.objects.create(
        famille=famille,
        individu=individu,
        type_cotisation=typ,
        unite_cotisation=unite,
        date_debut=debut,
        date_fin=fin,
    )


@pytest.mark.django_db
class TestCotisationsPage:
    def test_anonymous_redirected_to_login(self, client, organisateur):
        response = client.get(reverse(URL))
        assert response.status_code == 302
        assert reverse("portail_connexion") in response.url

    def test_staff_forbidden(self, client, staff_user, organisateur):
        client.force_login(staff_user)
        assert client.get(reverse(URL)).status_code == 403

    def test_empty_page(self, logged_client):
        response = logged_client.get(reverse(URL))
        assert response.status_code == 200
        assert response.context["page_titre"] == "Adhésions"
        assert response.context["cotisations_fournir"] == []
        assert list(response.context["liste_cotisations"]) == []

    def test_lists_own_cotisations_ordered_by_start_date(
        self, logged_client, famille_user
    ):
        _u, famille, _ratt = famille_user
        typ = _type()
        recente = _cotisation(famille, typ, debut=datetime.date(2026, 1, 1))
        ancienne = _cotisation(
            famille,
            typ,
            debut=datetime.date(2024, 1, 1),
            fin=datetime.date(2024, 12, 31),
        )
        response = logged_client.get(reverse(URL))
        assert list(response.context["liste_cotisations"]) == [ancienne, recente]

    def test_other_familles_cotisations_hidden(self, logged_client, other_famille):
        _cotisation(other_famille[1], _type())
        response = logged_client.get(reverse(URL))
        assert list(response.context["liste_cotisations"]) == []

    def test_missing_cotisation_is_listed_to_provide(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        activite = ActiviteFactory()
        _type(nom="Adhésion annuelle", activite=activite)
        InscriptionFactory(
            famille=famille, individu=ratt[1].individu, activite=activite, date_fin=None
        )
        response = logged_client.get(reverse(URL))
        a_fournir = response.context["cotisations_fournir"]
        assert [c["label"] for c in a_fournir] == ["Adhésion annuelle"]
        assert "Adhésion annuelle" in response.content.decode()

    def test_individual_cotisation_label_names_the_person(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        activite = ActiviteFactory()
        _type(nom="Licence", type_="individu", activite=activite)
        InscriptionFactory(
            famille=famille, individu=ratt[1].individu, activite=activite, date_fin=None
        )
        a_fournir = logged_client.get(reverse(URL)).context["cotisations_fournir"]
        assert a_fournir[0]["label"] == "Licence de Premier"

    def test_valid_cotisation_is_not_requested(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        activite = ActiviteFactory()
        typ = _type(activite=activite)
        InscriptionFactory(
            famille=famille, individu=ratt[1].individu, activite=activite, date_fin=None
        )
        _cotisation(
            famille,
            typ,
            debut=datetime.date(2000, 1, 1),
            fin=datetime.date(2999, 12, 31),
        )
        assert logged_client.get(reverse(URL)).context["cotisations_fournir"] == []

    def test_masked_individu_is_excluded_from_missing_list(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        activite = ActiviteFactory()
        _type(activite=activite)
        enfant = ratt[1].individu
        InscriptionFactory(
            famille=famille, individu=enfant, activite=activite, date_fin=None
        )
        famille.individus_masques.add(enfant)
        assert logged_client.get(reverse(URL)).context["cotisations_fournir"] == []

    def test_other_familles_inscriptions_do_not_leak(
        self, logged_client, other_famille
    ):
        activite = ActiviteFactory()
        _type(nom="Secret", activite=activite)
        InscriptionFactory(
            famille=other_famille[1],
            individu=other_famille[2][1].individu,
            activite=activite,
            date_fin=None,
        )
        response = logged_client.get(reverse(URL))
        assert response.context["cotisations_fournir"] == []
        assert "Secret" not in response.content.decode()
