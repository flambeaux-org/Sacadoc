"""Branch-level tests for portail/views/reservations.py (reservations list page)."""

import datetime
import decimal

import pytest
from core.models import CategorieCompteInternet, PortailPeriode, Prestation, Reglement
from django.urls import reverse
from tests.unit.factories import (
    ActiviteFactory,
    FactureFactory,
    IndividuFactory,
    InscriptionFactory,
    RattachementFactory,
)

URL = "portail_reservations"
TODAY = datetime.date.today()


def make_periode(activite, **kwargs):
    defaults = {
        "nom": "Periode",
        "date_debut": TODAY,
        "date_fin": TODAY + datetime.timedelta(days=30),
        "affichage": "TOUJOURS",
        "type_date": "TOUTES",
    }
    defaults.update(kwargs)
    return PortailPeriode.objects.create(activite=activite, **defaults)


def make_inscription(famille, individu, **kwargs):
    kwargs.setdefault("internet_reservations", True)
    activite = kwargs.pop("activite", None) or ActiviteFactory(
        portail_reservations_affichage="TOUJOURS"
    )
    return InscriptionFactory(
        famille=famille, individu=individu, activite=activite, **kwargs
    )


@pytest.mark.django_db
class TestReservationsAccess:
    def test_anonymous_redirected(self, client):
        r = client.get(reverse(URL))
        assert r.status_code == 302 and "connexion" in r.url

    def test_staff_forbidden(self, client, staff_user):
        client.force_login(staff_user)
        assert client.get(reverse(URL)).status_code in (302, 403)

    def test_page_title(self, logged_client):
        r = logged_client.get(reverse(URL))
        assert r.status_code == 200
        assert "Réservations" in str(r.context["page_titre"])


@pytest.mark.django_db
class TestReservationsFamilleAutorisation:
    def test_family_without_reservation_right_returns_early(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        make_inscription(famille, ratt[1].individu)
        famille.internet_reservations = False
        famille.save()
        r = logged_client.get(reverse(URL))
        assert r.status_code == 200
        assert r.context["liste_individus"] == []
        assert "dict_periodes" not in r.context
        assert "blocage_impayes" not in r.context

    def test_family_with_reservation_right_computes_context(
        self, logged_client, famille_user
    ):
        r = logged_client.get(reverse(URL))
        assert r.context["liste_individus"] == []
        assert r.context["dict_periodes"] == {}
        assert r.context["blocage_impayes"] is False
        assert isinstance(r.context["nbre_approbations_requises"], int)


@pytest.mark.django_db
class TestReservationsInscriptionsFilters:
    def test_inscription_listed_with_activity(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        enfant = ratt[1].individu
        insc = make_inscription(famille, enfant)
        r = logged_client.get(reverse(URL))
        assert r.context["liste_individus"] == [enfant]
        assert r.context["liste_individus"][0].activites == [insc.activite]

    def test_individus_sorted_and_activities_sorted_and_deduplicated(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        zoe = IndividuFactory(prenom="Zoe")
        RattachementFactory(individu=zoe, famille=famille)
        enfant = ratt[1].individu
        enfant.prenom = "Alice"
        enfant.save()
        a_b = ActiviteFactory(nom="B", portail_reservations_affichage="TOUJOURS")
        a_a = ActiviteFactory(nom="A", portail_reservations_affichage="TOUJOURS")
        make_inscription(famille, enfant, activite=a_b)
        make_inscription(famille, enfant, activite=a_a)
        make_inscription(famille, enfant, activite=a_a)  # duplicate on same activity
        make_inscription(
            famille, zoe, activite=a_a
        )  # activity already in liste_activites
        r = logged_client.get(reverse(URL))
        individus = r.context["liste_individus"]
        assert [i.prenom for i in individus] == ["Alice", "Zoe"]
        assert [a.nom for a in individus[0].activites] == ["A", "B"]
        assert [a.nom for a in individus[1].activites] == ["A"]

    def test_waiting_inscription_excluded(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        make_inscription(famille, ratt[1].individu, statut="attente")
        assert logged_client.get(reverse(URL)).context["liste_individus"] == []

    def test_ended_inscription_excluded(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        make_inscription(
            famille, ratt[1].individu, date_fin=TODAY - datetime.timedelta(days=1)
        )
        assert logged_client.get(reverse(URL)).context["liste_individus"] == []

    def test_inscription_ending_today_included(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        make_inscription(famille, ratt[1].individu, date_fin=TODAY)
        assert logged_client.get(reverse(URL)).context["liste_individus"] == [
            ratt[1].individu
        ]

    def test_activity_reservations_not_always_excluded(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        for aff in ("JAMAIS", "PERIODE"):
            make_inscription(
                famille,
                ratt[1].individu,
                activite=ActiviteFactory(portail_reservations_affichage=aff),
            )
        assert logged_client.get(reverse(URL)).context["liste_individus"] == []

    def test_ended_activity_excluded_but_open_ended_or_future_included(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        past = ActiviteFactory(
            portail_reservations_affichage="TOUJOURS",
            date_fin=TODAY - datetime.timedelta(days=1),
        )
        make_inscription(famille, ratt[1].individu, activite=past)
        assert logged_client.get(reverse(URL)).context["liste_individus"] == []
        future = ActiviteFactory(
            portail_reservations_affichage="TOUJOURS",
            date_fin=TODAY + datetime.timedelta(days=1),
        )
        make_inscription(famille, ratt[1].individu, activite=future)
        assert logged_client.get(reverse(URL)).context["liste_individus"] == [
            ratt[1].individu
        ]

    def test_inscription_without_internet_reservations_excluded(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        make_inscription(famille, ratt[1].individu, internet_reservations=False)
        assert logged_client.get(reverse(URL)).context["liste_individus"] == []

    def test_deceased_individu_excluded(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        enfant = ratt[1].individu
        enfant.deces = True
        enfant.save()
        make_inscription(famille, enfant)
        assert logged_client.get(reverse(URL)).context["liste_individus"] == []

    def test_masked_individu_excluded(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        make_inscription(famille, ratt[1].individu)
        famille.individus_masques.add(ratt[1].individu)
        assert logged_client.get(reverse(URL)).context["liste_individus"] == []

    def test_other_family_excluded(self, logged_client, other_famille):
        _u, famille_b, ratt_b = other_famille
        make_inscription(famille_b, ratt_b[1].individu)
        assert logged_client.get(reverse(URL)).context["liste_individus"] == []


@pytest.mark.django_db
class TestReservationsPeriodes:
    @pytest.fixture
    def insc(self, famille_user):
        _u, famille, ratt = famille_user
        return make_inscription(famille, ratt[1].individu)

    def test_always_period_listed_ordered_by_start_date(self, logged_client, insc):
        late = make_periode(
            insc.activite, nom="late", date_debut=TODAY + datetime.timedelta(days=10)
        )
        early = make_periode(insc.activite, nom="early")
        r = logged_client.get(reverse(URL))
        assert r.context["dict_periodes"] == {insc.activite: [early, late]}

    def test_never_period_hidden(self, logged_client, insc):
        make_periode(insc.activite, affichage="JAMAIS")
        assert logged_client.get(reverse(URL)).context["dict_periodes"] == {}

    def test_period_window_in_and_out(self, logged_client, insc):
        now = datetime.datetime.now()
        make_periode(
            insc.activite,
            affichage="PERIODE",
            nom="out",
            affichage_date_debut=now + datetime.timedelta(days=1),
            affichage_date_fin=now + datetime.timedelta(days=2),
        )
        assert logged_client.get(reverse(URL)).context["dict_periodes"] == {}
        inside = make_periode(
            insc.activite,
            affichage="PERIODE",
            nom="in",
            affichage_date_debut=now - datetime.timedelta(days=1),
            affichage_date_fin=now + datetime.timedelta(days=1),
        )
        assert logged_client.get(reverse(URL)).context["dict_periodes"] == {
            insc.activite: [inside]
        }

    def test_period_of_activity_without_inscription_not_listed(
        self, logged_client, insc
    ):
        make_periode(ActiviteFactory(portail_reservations_affichage="TOUJOURS"))
        assert logged_client.get(reverse(URL)).context["dict_periodes"] == {}

    def test_period_not_authorized_for_family_city(
        self, logged_client, famille_user, insc
    ):
        _u, famille, _ratt = famille_user
        famille.ville_resid = "Paris"
        famille.save()
        make_periode(
            insc.activite, nom="lyon", types_villes="SELECTION", villes="Lyon, Nantes"
        )
        ok = make_periode(
            insc.activite, nom="paris", types_villes="SELECTION", villes="paris"
        )
        assert logged_client.get(reverse(URL)).context["dict_periodes"] == {
            insc.activite: [ok]
        }

    def test_period_not_authorized_for_internet_category(
        self, logged_client, famille_user, insc
    ):
        _u, famille, _ratt = famille_user
        cat = CategorieCompteInternet.objects.create(nom="VIP")
        famille.internet_categorie = cat
        famille.save()
        make_periode(insc.activite, nom="aucune", types_categories="AUCUNE")
        p_sel = make_periode(insc.activite, nom="sel", types_categories="SELECTION")
        p_sel.categories.add(cat)
        make_periode(insc.activite, nom="autre_sel", types_categories="SELECTION")
        r = logged_client.get(reverse(URL))
        assert r.context["dict_periodes"] == {insc.activite: [p_sel]}

    def test_period_link_rendered(self, logged_client, famille_user, insc):
        _u, _famille, ratt = famille_user
        p = make_periode(insc.activite, nom="Vacances ete")
        content = logged_client.get(reverse(URL)).content.decode()
        assert "Vacances ete" in content
        assert (
            reverse(
                "portail_planning", args=[ratt[1].individu.pk, insc.activite.pk, p.pk]
            )
            in content
        )


@pytest.mark.django_db
class TestReservationsBlocageImpayes:
    @pytest.fixture
    def famille(self, famille_user):
        return famille_user[1]

    @staticmethod
    def dette(famille, montant, date=None):
        Prestation.objects.create(
            famille=famille,
            date=date or (TODAY - datetime.timedelta(days=1)),
            label="x",
            montant=montant,
            montant_initial=montant,
        )

    def test_parameter_off_means_no_blocage(self, logged_client, famille):
        self.dette(famille, 10000)
        assert logged_client.get(reverse(URL)).context["blocage_impayes"] is False

    def test_unpaid_below_threshold_not_blocked(
        self, logged_client, famille, set_parametre_portail
    ):
        set_parametre_portail("reservations_blocage_impayes", 100)
        self.dette(famille, 99)
        assert logged_client.get(reverse(URL)).context["blocage_impayes"] is False

    def test_unpaid_at_threshold_is_blocked(
        self, logged_client, famille, set_parametre_portail
    ):
        set_parametre_portail("reservations_blocage_impayes", 100)
        self.dette(famille, 100)
        assert logged_client.get(reverse(URL)).context["blocage_impayes"] is True

    def test_prestation_of_today_not_counted(
        self, logged_client, famille, set_parametre_portail
    ):
        """Get_solde_famille filters date__lt=today."""
        set_parametre_portail("reservations_blocage_impayes", 100)
        self.dette(famille, 500, date=TODAY)
        assert logged_client.get(reverse(URL)).context["blocage_impayes"] is False

    def test_payment_reduces_unpaid(
        self, logged_client, famille, set_parametre_portail
    ):
        from core.models import CompteBancaire, ModeleImpression, ModeReglement, Payeur

        set_parametre_portail("reservations_blocage_impayes", 100)
        self.dette(famille, 150)
        mode = ModeReglement.objects.create(label="Cheque")
        payeur = Payeur.objects.create(famille=famille, nom="P")
        compte = CompteBancaire.objects.create(nom="C")
        Reglement.objects.create(
            famille=famille,
            date=TODAY,
            mode=mode,
            montant=100,
            payeur=payeur,
            compte=compte,
            modelimp=ModeleImpression.objects.create(categorie="reglement", nom="m"),
        )
        assert logged_client.get(reverse(URL)).context["blocage_impayes"] is False

    def test_invoiced_mode_below_threshold(
        self, logged_client, famille, set_parametre_portail
    ):
        set_parametre_portail(
            "reservations_blocage_impayes", 10050
        )  # unpaid invoices >= 50
        FactureFactory(famille=famille, solde_actuel=49, etat=None)
        self.dette(famille, 1000)  # raw prestations must be ignored in this mode
        assert logged_client.get(reverse(URL)).context["blocage_impayes"] is False

    def test_invoiced_mode_at_threshold_blocked(
        self, logged_client, famille, set_parametre_portail
    ):
        set_parametre_portail("reservations_blocage_impayes", 10050)
        FactureFactory(famille=famille, solde_actuel=50, etat=None)
        assert logged_client.get(reverse(URL)).context["blocage_impayes"] is True

    def test_invoiced_mode_cancelled_invoice_ignored(
        self, logged_client, famille, set_parametre_portail
    ):
        set_parametre_portail("reservations_blocage_impayes", 10050)
        FactureFactory(famille=famille, solde_actuel=500, etat="annulation")
        assert logged_client.get(reverse(URL)).context["blocage_impayes"] is False

    def test_blocage_flag_changes_rendering(
        self, logged_client, famille, set_parametre_portail
    ):
        set_parametre_portail("reservations_blocage_impayes", 100)
        self.dette(famille, 500)
        r = logged_client.get(reverse(URL))
        assert r.status_code == 200 and r.context["blocage_impayes"] is True
        assert (
            decimal.Decimal(
                r.context["parametres_portail"]["reservations_blocage_impayes"]
            )
            == 100
        )
