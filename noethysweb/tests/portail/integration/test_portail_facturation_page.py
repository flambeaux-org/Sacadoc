"""Facturation page (`facturation.View`) and the payment return pages.

`facturation_afficher_solde_famille` is switched on in most tests because of
KNOWN BUG #6 (the view only returns its context from inside that `if`).
"""

import datetime
import decimal

import pytest
from core.models import Paiement
from django.contrib.messages import get_messages
from django.urls import reverse
from test_portail_facturation_support import (
    make_cotisation,
    make_facture,
    make_paiement,
    make_periode,
    make_prestation,
    make_reglement,
    ventiler,
)
from tests.unit.factories import (
    ActiviteFactory,
    FactureFactory,
)

URL = "portail_facturation"


@pytest.fixture
def page(logged_client, set_parametre_portail):
    """GET the facturation page with bug #6 worked around."""
    set_parametre_portail("facturation_afficher_solde_famille", True)

    def _get():
        response = logged_client.get(reverse(URL))
        assert response.status_code == 200
        return response

    return _get


@pytest.mark.django_db
class TestRetourPaiementPages:
    @pytest.mark.parametrize("etat", ["cancel", "error", "refused", "success"])
    def test_etat_in_context(self, logged_client, etat):
        response = logged_client.get(reverse(f"retour_payzen_{etat}"))
        assert response.status_code == 200
        assert response.context["etat"] == etat
        assert "portail/retour_paiement.html" in [t.name for t in response.templates]

    @pytest.mark.parametrize("etat", ["cancel", "error", "refused", "success"])
    def test_requires_login(self, client, organisateur, etat):
        response = client.get(reverse(f"retour_payzen_{etat}"))
        assert response.status_code in (302, 403)


@pytest.mark.django_db
class TestFacturationPageBasics:
    def test_requires_login(self, client, organisateur):
        response = client.get(reverse(URL))
        assert response.status_code in (302, 403)

    def test_empty_family(self, page):
        response = page()
        ctx = response.context
        assert ctx["prelevement_actif"] is False
        assert ctx["liste_factures"] == []
        assert ctx["liste_factures_impayees"] == []
        assert ctx["liste_periodes_prefacturation"] == []
        assert ctx["liste_cotisations_prefacturation"] == []
        assert ctx["texte_impayes"] is None
        assert ctx["solde_famille"] == 0
        assert ctx["liste_activites_soldes"] == []

    def test_lists_reglements_most_recent_first(self, page, famille_user):
        _u, famille, _r = famille_user
        r_old = make_reglement(famille, 5)
        r_new = make_reglement(famille, 7)
        r_old.date = datetime.date(2023, 1, 1)
        r_old.save()
        r_new.date = datetime.date(2024, 1, 1)
        r_new.save()
        reglements = list(page().context["liste_reglements"])
        assert reglements == [r_new, r_old]

    def test_does_not_leak_other_family_data(self, page, other_famille):
        _u, autre, _r = other_famille
        make_facture(autre)
        make_reglement(autre)
        ctx = page().context
        assert ctx["liste_factures"] == []
        assert list(ctx["liste_reglements"]) == []


@pytest.mark.django_db
class TestPrelevementEtPaiementActif:
    def _mandat(self, famille, actif=True):
        from core.models import Mandat

        return Mandat.objects.create(
            famille=famille,
            rum="RUM1",
            date=datetime.date(2024, 1, 1),
            iban="FR7612345678901234567890123",
            bic="ABCDFRPP",
            actif=actif,
        )

    def test_without_mandat_paiement_actif(self, page):
        ctx = page().context
        assert ctx["prelevement_actif"] is False
        assert ctx["paiement_actif"] is True

    def test_active_mandat_disables_online_payment_by_default(self, page, famille_user):
        self._mandat(famille_user[1])
        ctx = page().context
        assert ctx["prelevement_actif"] is True
        assert ctx["paiement_actif"] is False

    def test_active_mandat_keeps_payment_when_option_off(
        self, page, famille_user, set_parametre_portail
    ):
        set_parametre_portail("paiement_ligne_off_si_prelevement", False)
        self._mandat(famille_user[1])
        ctx = page().context
        assert ctx["prelevement_actif"] is True
        assert ctx["paiement_actif"] is True

    def test_inactive_mandat_is_ignored(self, page, famille_user):
        self._mandat(famille_user[1], actif=False)
        ctx = page().context
        assert ctx["prelevement_actif"] is False
        assert ctx["paiement_actif"] is True


@pytest.mark.django_db
class TestFacturesImpayees:
    def test_unpaid_facture_listed_and_reminder_singular(self, page, famille_user):
        _u, famille, _r = famille_user
        facture, _p = make_facture(famille, 120)
        ctx = page().context
        assert ctx["liste_factures"] == [facture]
        assert ctx["liste_factures_impayees"] == [facture]
        assert "1 facture à régler" in ctx["texte_impayes"]
        assert "<strong>" in ctx["texte_impayes"]

    def test_reminder_plural(self, page, famille_user):
        _u, famille, _r = famille_user
        make_facture(famille, 10)
        make_facture(famille, 20)
        assert "2 factures à régler" in page().context["texte_impayes"]

    def test_paid_facture_listed_but_not_unpaid(self, page, famille_user):
        _u, famille, _r = famille_user
        facture = FactureFactory(famille=famille, total=50, solde_actuel=0)
        ctx = page().context
        assert ctx["liste_factures"] == [facture]
        assert ctx["liste_factures_impayees"] == []
        assert ctx["texte_impayes"] is None

    def test_cancelled_facture_excluded_everywhere(self, page, famille_user):
        _u, famille, _r = famille_user
        FactureFactory(famille=famille, etat="annulation")
        ctx = page().context
        assert ctx["liste_factures"] == []
        assert ctx["liste_factures_impayees"] == []

    def test_expired_date_limite_paiement_not_unpaid(self, page, famille_user):
        _u, famille, _r = famille_user
        facture = FactureFactory(
            famille=famille,
            date_limite_paiement=datetime.date.today() - datetime.timedelta(days=1),
        )
        ctx = page().context
        assert ctx["liste_factures"] == [facture]
        assert ctx["liste_factures_impayees"] == []

    def test_future_date_limite_paiement_still_unpaid(self, page, famille_user):
        _u, famille, _r = famille_user
        facture = FactureFactory(
            famille=famille,
            date_limite_paiement=datetime.date.today() + datetime.timedelta(days=3),
        )
        assert page().context["liste_factures_impayees"] == [facture]

    def test_date_limite_today_still_unpaid(self, page, famille_user):
        _u, famille, _r = famille_user
        facture = FactureFactory(
            famille=famille, date_limite_paiement=datetime.date.today()
        )
        assert page().context["liste_factures_impayees"] == [facture]

    def test_ordered_by_date_edition_desc(self, page, famille_user):
        _u, famille, _r = famille_user
        old = FactureFactory(famille=famille, date_edition=datetime.date(2023, 1, 1))
        new = FactureFactory(famille=famille, date_edition=datetime.date(2024, 6, 1))
        assert page().context["liste_factures"] == [new, old]


@pytest.mark.django_db
class TestPaiementsEnCours:
    """Pending (resultat NULL, < 5 minutes) PAYASSO / PAYFIP payments hide the amounts they cover."""

    def test_pending_payasso_facture_is_considered_paid(self, page, famille_user):
        _u, famille, _r = famille_user
        facture, _p = make_facture(famille, 100)
        make_paiement(famille, "payasso", "F%d#100.00" % facture.pk, montant=100)
        ctx = page().context
        (f,) = ctx["liste_factures"]
        assert f.solde_actuel == 0
        assert f.regle == f.total
        assert ctx["liste_factures_impayees"] == []

    def test_pending_payasso_periode_is_not_unpaid_anymore(self, page, famille_user):
        _u, famille, _r = famille_user
        activite = ActiviteFactory()
        periode = make_periode(activite)
        make_prestation(famille, activite, 40)
        make_paiement(famille, "payasso", "P%d#40.00" % periode.pk, montant=40)
        ctx = page().context
        assert ctx["liste_periodes_prefacturation"] == []
        assert ctx["texte_impayes"] is None

    def test_pending_payasso_cotisation_is_not_unpaid_anymore(self, page, famille_user):
        _u, famille, _r = famille_user
        prestation = make_cotisation(famille, 30)
        make_paiement(famille, "payasso", "C%d#30.00" % prestation.pk, montant=30)
        assert page().context["liste_cotisations_prefacturation"] == []

    def test_pending_payasso_with_several_lines_same_id_accumulates(
        self, page, famille_user
    ):
        _u, famille, _r = famille_user
        facture, _p = make_facture(famille, 100)
        make_paiement(
            famille,
            "payasso",
            "F%d#40.00,F%d#60.00" % (facture.pk, facture.pk),
            montant=100,
        )
        assert page().context["liste_factures_impayees"] == []

    def test_old_pending_payasso_is_ignored(self, page, famille_user):
        _u, famille, _r = famille_user
        facture, _p = make_facture(famille, 100)
        paiement = make_paiement(
            famille, "payasso", "F%d#100.00" % facture.pk, montant=100
        )
        Paiement.objects.filter(pk=paiement.pk).update(
            horodatage=datetime.datetime.now() - datetime.timedelta(minutes=10)
        )
        assert page().context["liste_factures_impayees"] == [facture]

    def test_finished_payasso_is_ignored(self, page, famille_user):
        _u, famille, _r = famille_user
        facture, _p = make_facture(famille, 100)
        make_paiement(
            famille,
            "payasso",
            "F%d#100.00" % facture.pk,
            montant=100,
            resultat="DENIED",
        )
        assert page().context["liste_factures_impayees"] == [facture]

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:682 re-initialises `dict_paiements` for PAYASSO, "
        "discarding the pending PAYFIP payments collected at line 671-678 (the PAYFIP loop is dead code).",
        strict=True,
    )
    def test_pending_payfip_facture_is_considered_paid(self, page, famille_user):
        """A PAYFIP payment still waiting for its notification should hide the facture."""
        _u, famille, _r = famille_user
        facture, _p = make_facture(famille, 100)
        make_paiement(famille, "payfip", "F%d#100.00" % facture.pk, montant=100)
        assert page().context["liste_factures_impayees"] == []

    def test_pending_payfip_ventilation_parsed_without_error(self, page, famille_user):
        """The PAYFIP loop parses F/P/C ventilation (even when the result is overwritten later)."""
        _u, famille, _r = famille_user
        make_paiement(famille, "payfip", "F999#10.00,P998#5.00,C997#1.00", montant=16)
        page()


@pytest.mark.django_db
class TestNotificationsPaiements:
    def _messages(self, response):
        return [(m.level_tag, str(m)) for m in get_messages(response.wsgi_request)]

    @pytest.mark.parametrize(
        "resultat, level, fragment",
        [
            ("PAID", "success", "enregistré avec succès"),
            ("DENIED", "error", "refusé"),
            ("CANCELLED", "error", "annulé"),
            ("ERROR", "error", "rencontré une erreur"),
            (None, "error", "notification de paiement semble absente"),
        ],
    )
    def test_message_per_result_and_notification_timestamp(
        self, page, famille_user, resultat, level, fragment
    ):
        _u, famille, _r = famille_user
        paiement = make_paiement(
            famille, "payzen", "F1#12.00", montant=12, resultat=resultat
        )
        response = page()
        messages_ = [m for m in self._messages(response) if fragment in m[1]]
        assert messages_ and messages_[0][0] == level
        assert "12.00" in messages_[0][1]
        paiement.refresh_from_db()
        assert paiement.notification is not None

    def test_notification_shown_only_once(self, page, famille_user, logged_client):
        _u, famille, _r = famille_user
        make_paiement(famille, "payzen", "F1#12.00", montant=12, resultat="PAID")
        first = page()
        assert any("12.00" in m[1] for m in self._messages(first))
        second = logged_client.get(reverse(URL))
        assert not any("12.00" in m[1] for m in self._messages(second))

    def test_already_notified_payment_is_skipped(self, page, famille_user):
        _u, famille, _r = famille_user
        make_paiement(
            famille,
            "payzen",
            "F1#12.00",
            montant=12,
            resultat="PAID",
            notification=datetime.datetime.now(),
        )
        assert not any("12.00" in m[1] for m in self._messages(page()))

    def test_old_payment_not_notified(self, page, famille_user):
        _u, famille, _r = famille_user
        paiement = make_paiement(
            famille, "payzen", "F1#12.00", montant=12, resultat="PAID"
        )
        Paiement.objects.filter(pk=paiement.pk).update(
            horodatage=datetime.datetime.now() - datetime.timedelta(hours=2)
        )
        assert not any("12.00" in m[1] for m in self._messages(page()))
        paiement.refresh_from_db()
        assert paiement.notification is None

    def test_other_family_payment_not_notified(self, page, other_famille):
        _u, autre, _r = other_famille
        paiement = make_paiement(
            autre, "payzen", "F1#12.00", montant=12, resultat="PAID"
        )
        page()
        paiement.refresh_from_db()
        assert paiement.notification is None


@pytest.mark.django_db
class TestPrefacturationPeriodes:
    def test_unpaid_prestation_in_periode(self, page, famille_user):
        _u, famille, _r = famille_user
        activite = ActiviteFactory()
        periode = make_periode(activite)
        make_prestation(famille, activite, 40)
        make_prestation(famille, activite, 10)
        ctx = page().context
        (p,) = ctx["liste_periodes_prefacturation"]
        assert p == periode
        assert (p.total, p.regle, p.solde) == (50, 0, 50)
        assert "des prestations à régler en avance" in ctx["texte_impayes"]
        assert "factures à régler" not in ctx["texte_impayes"]
        assert "50.00" in ctx["texte_impayes"]

    def test_partially_paid_prestation(self, page, famille_user):
        _u, famille, _r = famille_user
        activite = ActiviteFactory()
        make_periode(activite)
        prestation = make_prestation(famille, activite, 40)
        ventiler(make_reglement(famille, 15), prestation, 15)
        (p,) = page().context["liste_periodes_prefacturation"]
        assert (p.total, p.regle, p.solde) == (40, 15, 25)

    def test_fully_paid_prestation_hides_periode(self, page, famille_user):
        _u, famille, _r = famille_user
        activite = ActiviteFactory()
        make_periode(activite)
        prestation = make_prestation(famille, activite, 40)
        ventiler(make_reglement(famille, 40), prestation, 40)
        assert page().context["liste_periodes_prefacturation"] == []

    def test_prestation_outside_periode_dates_ignored(self, page, famille_user):
        _u, famille, _r = famille_user
        activite = ActiviteFactory()
        make_periode(activite)
        make_prestation(famille, activite, 40, date=datetime.date(2024, 5, 1))
        assert page().context["liste_periodes_prefacturation"] == []

    def test_prestation_on_other_activity_ignored(self, page, famille_user):
        _u, famille, _r = famille_user
        make_periode(ActiviteFactory())
        make_prestation(famille, ActiviteFactory(), 40)
        assert page().context["liste_periodes_prefacturation"] == []

    def test_already_invoiced_prestation_ignored(self, page, famille_user):
        _u, famille, _r = famille_user
        activite = ActiviteFactory()
        make_periode(activite)
        make_facture(
            famille, 40, activite=activite
        )  # prestation dated 2024-03-01 but invoiced
        assert page().context["liste_periodes_prefacturation"] == []

    def test_periode_without_prefacturation_ignored(self, page, famille_user):
        _u, famille, _r = famille_user
        activite = ActiviteFactory()
        make_periode(activite, prefacturation=False)
        make_prestation(famille, activite, 40)
        assert page().context["liste_periodes_prefacturation"] == []

    def test_periode_not_authorized_for_family_ignored(self, page, famille_user):
        _u, famille, _r = famille_user
        famille.ville_resid = "LYON"
        famille.save()
        activite = ActiviteFactory()
        make_periode(activite, types_villes="SELECTION", villes="PARIS")
        make_prestation(famille, activite, 40)
        assert page().context["liste_periodes_prefacturation"] == []

    def test_two_periodes_share_extreme_dates(self, page, famille_user):
        _u, famille, _r = famille_user
        a1, a2 = ActiviteFactory(), ActiviteFactory()
        make_periode(a1, nom="P1")
        make_periode(
            a2,
            nom="P2",
            date_debut=datetime.date(2024, 4, 1),
            date_fin=datetime.date(2024, 4, 30),
        )
        make_prestation(famille, a1, 10, date=datetime.date(2024, 3, 5))
        make_prestation(famille, a2, 20, date=datetime.date(2024, 4, 5))
        periodes = page().context["liste_periodes_prefacturation"]
        assert sorted((p.nom, p.solde) for p in periodes) == [("P1", 10), ("P2", 20)]


@pytest.mark.django_db
class TestPrefacturationCotisations:
    def test_unpaid_cotisation_listed(self, page, famille_user):
        _u, famille, _r = famille_user
        prestation = make_cotisation(famille, 30)
        ctx = page().context
        (c,) = ctx["liste_cotisations_prefacturation"]
        assert c == prestation
        assert (c.total, c.regle, c.solde) == (30, 0, 30)
        assert "des prestations à régler en avance" in ctx["texte_impayes"]

    def test_partially_paid_cotisation(self, page, famille_user):
        _u, famille, _r = famille_user
        prestation = make_cotisation(famille, 30)
        ventiler(make_reglement(famille, 10), prestation, 10)
        (c,) = page().context["liste_cotisations_prefacturation"]
        assert (c.regle, c.solde) == (10, 20)

    def test_fully_paid_cotisation_hidden(self, page, famille_user):
        _u, famille, _r = famille_user
        prestation = make_cotisation(famille, 30)
        ventiler(make_reglement(famille, 30), prestation, 30)
        assert page().context["liste_cotisations_prefacturation"] == []

    def test_cotisation_without_prefacturation_hidden(self, page, famille_user):
        _u, famille, _r = famille_user
        make_cotisation(famille, 30, prefacturation=False)
        assert page().context["liste_cotisations_prefacturation"] == []


@pytest.mark.django_db
class TestTexteImpayes:
    def test_combined_facture_and_prefacturation_total(self, page, famille_user):
        _u, famille, _r = famille_user
        make_facture(famille, 100)
        make_cotisation(famille, 30)
        texte = page().context["texte_impayes"]
        assert "1 facture à régler" in texte
        assert "des prestations à régler en avance" in texte
        assert "130.00" in texte


@pytest.mark.django_db
class TestSoldeFamille:
    def test_grouped_by_activity_sorted_and_summed(self, page, famille_user):
        _u, famille, _r = famille_user
        zumba = ActiviteFactory(nom="Zumba", pay_org_tpe="stripe")
        art = ActiviteFactory(nom="Art")
        p_small = make_prestation(famille, art, 10)
        p_big = make_prestation(famille, art, 60)
        p_z = make_prestation(famille, zumba, 25)
        ventiler(make_reglement(famille, 5), p_small, 5)
        ctx = page().context
        assert ctx["solde_famille"] == decimal.Decimal(90)
        noms = [nom for nom, _ in ctx["liste_activites_soldes"]]
        assert noms == ["Art", "Zumba"]
        info_art = dict(ctx["liste_activites_soldes"])["Art"]
        assert info_art["total_restant"] == 65
        assert info_art["id_premiere_prestation"] == p_small.pk
        assert [p.pk for p in info_art["prestations"]] == [
            p_big.pk,
            p_small.pk,
        ]  # by reste desc
        info_z = dict(ctx["liste_activites_soldes"])["Zumba"]
        assert info_z["pay_org_tpe"] == "stripe"
        assert info_z["prestations"][0].pk == p_z.pk

    def test_invisible_activity_excluded(self, page, famille_user):
        _u, famille, _r = famille_user
        make_prestation(famille, ActiviteFactory(visible=False), 10)
        ctx = page().context
        assert ctx["solde_famille"] == 0
        assert ctx["liste_activites_soldes"] == []

    def test_prestation_without_activity_excluded(self, page, famille_user):
        _u, famille, _r = famille_user
        from core.models import Prestation

        Prestation.objects.create(
            famille=famille,
            activite=None,
            montant=10,
            date=datetime.date(2024, 1, 1),
            label="x",
        )
        assert page().context["solde_famille"] == 0

    def test_other_family_prestations_excluded(self, page, other_famille):
        _u, autre, _r = other_famille
        make_prestation(autre, ActiviteFactory(), 10)
        assert page().context["solde_famille"] == 0


@pytest.mark.django_db
class TestBug6ReturnContext:
    def test_default_parameter_page_renders_with_facture(
        self, logged_client, famille_user
    ):
        _u, famille, _r = famille_user
        make_facture(famille, 10)
        assert logged_client.get(reverse(URL)).status_code == 200
