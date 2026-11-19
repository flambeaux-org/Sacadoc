"""Tests for portail/views/planning.py (reservation planning page + grid save + confirmation mail)."""

import datetime
import json
from unittest import mock

import pytest
from core.models import (
    AdresseMail,
    CategorieCompteInternet,
    Consommation,
    Destinataire,
    Ferie,
    Mail,
    ModeleEmail,
    Ouverture,
    PortailPeriode,
    Unite,
    Vacance,
)
from django.urls import reverse
from portail.views.planning import View
from tests.unit.factories import (
    ActiviteFactory,
    AdresseMailFactory,
    InscriptionFactory,
    RattachementFactory,
)

URL = "portail_planning"
TODAY = datetime.date.today()


def rng(debut, fin):
    return f"{debut};{fin}"


def d(days):
    return TODAY + datetime.timedelta(days=days)


def make_periode(activite, **kwargs):
    defaults = {
        "nom": "Periode",
        "date_debut": TODAY,
        "date_fin": d(30),
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


def make_unite(activite, **kwargs):
    kwargs.setdefault("ordre", 1)
    kwargs.setdefault("nom", "Journee")
    kwargs.setdefault("abrege", "J")
    return Unite.objects.create(activite=activite, **kwargs)


def make_ouvertures(insc, unite, days):
    Ouverture.objects.bulk_create(
        [
            Ouverture(
                activite=insc.activite, unite=unite, groupe=insc.groupe, date=d(n)
            )
            for n in days
        ]
    )


def make_vacance(debut, fin, nom="Vacances de la Toussaint"):
    return Vacance.objects.create(
        nom=nom, annee=debut.year, date_debut=debut, date_fin=fin
    )


def url_for(insc, periode, individu=None):
    return reverse(
        URL, args=[(individu or insc.individu).pk, insc.activite.pk, periode.pk]
    )


@pytest.fixture(autouse=True)
def certified(famille_user):
    """The family sheets are certified, so that no approbation blocks the planning page."""
    _u, famille, ratt = famille_user
    now = datetime.datetime.now()
    famille.certification_date = now
    famille.save()
    for r in ratt:
        r.certification_date = now
        r.save()


@pytest.fixture
def insc(famille_user):
    _u, famille, ratt = famille_user
    return make_inscription(famille, ratt[1].individu)


@pytest.fixture
def periode(insc):
    return make_periode(insc.activite)


@pytest.fixture
def page(logged_client, insc, periode):
    return logged_client.get(url_for(insc, periode))


# --------------------------------------------------------------------------- access


@pytest.mark.django_db
class TestPlanningAccess:
    def test_anonymous_redirected_to_login(self, client, insc, periode):
        r = client.get(url_for(insc, periode))
        assert r.status_code == 302 and "connexion" in r.url

    def test_anonymous_post_redirected_to_login(self, client, insc, periode):
        r = client.post(url_for(insc, periode), {"donnees": "{}"})
        assert r.status_code == 302 and "connexion" in r.url

    @pytest.mark.xfail(
        reason="BUG: portail/views/planning.py:33 dispatch reads request.user.famille before the categorie check -> RelatedObjectDoesNotExist (500) for staff users",
        strict=True,
    )
    def test_staff_cannot_access(self, client, staff_user, insc, periode):
        """A staff user must never see a family planning (dispatch dereferences user.famille first)."""
        client.force_login(staff_user)
        r = client.get(url_for(insc, periode))
        assert r.status_code in (302, 403)

    def test_authorized_family_gets_page(self, page):
        assert page.status_code == 200
        assert "portail/planning.html" in [t.name for t in page.templates]

    def test_other_family_child_forbidden(
        self, logged_client, other_famille, periode, insc
    ):
        """idindividu of another family's child: no inscription for the logged family -> 403."""
        _u, _f, ratt_b = other_famille
        r = logged_client.get(
            reverse(URL, args=[ratt_b[1].individu.pk, insc.activite.pk, periode.pk])
        )
        assert r.status_code == 403

    def test_child_not_inscribed_to_activity_forbidden(
        self, logged_client, famille_user, insc
    ):
        _u, _f, ratt = famille_user
        other_act = ActiviteFactory(portail_reservations_affichage="TOUJOURS")
        p = make_periode(other_act)
        r = logged_client.get(
            reverse(URL, args=[ratt[1].individu.pk, other_act.pk, p.pk])
        )
        assert r.status_code == 403

    def test_inscription_without_internet_reservations_forbidden(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        i = make_inscription(famille, ratt[1].individu, internet_reservations=False)
        p = make_periode(i.activite)
        assert logged_client.get(url_for(i, p)).status_code == 403

    def test_family_without_internet_reservations_forbidden(
        self, logged_client, famille_user, insc, periode
    ):
        _u, famille, _ratt = famille_user
        famille.internet_reservations = False
        famille.save()
        assert logged_client.get(url_for(insc, periode)).status_code == 403

    def test_inactive_periode_forbidden(self, logged_client, insc):
        p = make_periode(
            insc.activite,
            affichage="PERIODE",
            affichage_date_debut=datetime.datetime.now() + datetime.timedelta(days=1),
            affichage_date_fin=datetime.datetime.now() + datetime.timedelta(days=2),
        )
        assert logged_client.get(url_for(insc, p)).status_code == 403

    @pytest.mark.xfail(
        reason="BUG: core/models.py:3361 PortailPeriode.Is_active_today compares datetime to None when affichage=JAMAIS -> TypeError (500) instead of False (reached from planning.py:62)",
        strict=True,
    )
    def test_periode_never_displayed_forbidden(self, logged_client, insc):
        """affichage=JAMAIS: Is_active_today compares datetime with None -> TypeError instead of False."""
        p = make_periode(insc.activite, affichage="JAMAIS")
        assert logged_client.get(url_for(insc, p)).status_code == 403

    def test_active_window_periode_allowed(self, logged_client, insc):
        p = make_periode(
            insc.activite,
            affichage="PERIODE",
            affichage_date_debut=datetime.datetime.now() - datetime.timedelta(days=1),
            affichage_date_fin=datetime.datetime.now() + datetime.timedelta(days=1),
        )
        assert logged_client.get(url_for(insc, p)).status_code == 200

    def test_periode_city_not_authorized_forbidden(
        self, logged_client, famille_user, insc
    ):
        _u, famille, _ratt = famille_user
        famille.ville_resid = "Paris"
        famille.save()
        p = make_periode(insc.activite, types_villes="SELECTION", villes="Lyon, Nantes")
        assert logged_client.get(url_for(insc, p)).status_code == 403

    def test_periode_category_not_authorized_forbidden(self, logged_client, insc):
        cat = CategorieCompteInternet.objects.create(nom="VIP")
        p = make_periode(insc.activite, types_categories="SELECTION")
        p.categories.add(cat)
        assert logged_client.get(url_for(insc, p)).status_code == 403

    @pytest.mark.xfail(
        reason="BUG: portail/views/planning.py:61 PortailPeriode.objects.get raises DoesNotExist (500) for unknown idperiode; the `not periode` guard on line 62 is unreachable",
        strict=True,
    )
    def test_unknown_periode_is_forbidden_or_404(self, logged_client, insc):
        """An unknown idperiode must not crash with a 500 (PortailPeriode.DoesNotExist)."""
        r = logged_client.get(
            reverse(URL, args=[insc.individu.pk, insc.activite.pk, 999999])
        )
        assert r.status_code in (403, 404)

    @pytest.mark.xfail(
        reason="BUG: portail/views/planning.py:32 Activite.objects.get raises DoesNotExist (500) for unknown idactivite",
        strict=True,
    )
    def test_unknown_activite_is_404_or_403(self, logged_client, insc, periode):
        """An unknown idactivite must not crash with a 500 (Activite.DoesNotExist in dispatch)."""
        r = logged_client.get(reverse(URL, args=[insc.individu.pk, 999999, periode.pk]))
        assert r.status_code in (403, 404)

    @pytest.mark.xfail(
        reason="BUG: portail/views/planning.py:54-61 test_func checks the inscription of URL idactivite but never that periode.activite_id == idactivite, so authorisation is evaluated on another activity than the one displayed",
        strict=True,
    )
    def test_periode_of_other_activity_with_valid_inscription(
        self, logged_client, insc
    ):
        """A periode that belongs to another activity must not give access to this activity planning."""
        other = ActiviteFactory(portail_reservations_affichage="TOUJOURS")
        p = make_periode(other)
        r = logged_client.get(
            reverse(URL, args=[insc.individu.pk, insc.activite.pk, p.pk])
        )
        assert r.status_code in (403, 404)


# ------------------------------------------------------------------------ approbations


@pytest.mark.django_db
class TestPlanningApprobations:
    def test_pending_approbation_redirects_to_renseignements(
        self, logged_client, insc, periode
    ):
        from core.models import TypeConsentement, UniteConsentement

        tc = TypeConsentement.objects.create(nom="Reglement")
        UniteConsentement.objects.create(
            type_consentement=tc, date_debut=d(-10), document="x.pdf"
        )
        insc.activite.types_consentements.add(tc)
        r = logged_client.get(url_for(insc, periode))
        assert r.status_code == 302
        assert r.url == reverse("portail_renseignements")
        msgs = [str(m) for m in r.wsgi_request._messages]
        assert any("approbation" in m for m in msgs)

    def test_no_approbation_required_passes(self, page):
        assert page.status_code == 200


# --------------------------------------------------------------------------- context


@pytest.mark.django_db
class TestPlanningContext:
    def test_basic_context(self, page, insc, periode):
        assert str(page.context["page_titre"]) == "Planning"
        assert page.context["jours_complets_semaine"]
        assert page.context["form_appliquer_semaine_type"] is not None
        data = page.context["data"]
        assert data["mode"] == "portail"
        assert data["idfamille"] == insc.famille.pk
        assert data["individu"] == insc.individu
        assert data["periode_reservation"] == periode
        assert data["selection_activite"] == insc.activite
        assert json.loads(data["dict_suppressions_json"]) == {
            "consommations": [],
            "prestations": [],
            "memos": [],
        }

    def test_dates_default_hide_past_dates(self, logged_client, insc):
        p = make_periode(insc.activite, date_debut=d(-10), date_fin=d(5))
        data = logged_client.get(url_for(insc, p)).context["data"]
        assert data["date_min"] == TODAY
        assert data["date_max"] == d(5)
        assert json.loads(data["periode_json"])["periodes"] == [rng(TODAY, d(5))]

    def test_dates_with_limited_past_days(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        act = ActiviteFactory(
            portail_reservations_affichage="TOUJOURS",
            portail_afficher_dates_passees="3",
        )
        i = make_inscription(famille, ratt[1].individu, activite=act)
        p = make_periode(act, date_debut=d(-10), date_fin=d(5))
        data = logged_client.get(url_for(i, p)).context["data"]
        assert data["date_min"] == d(-3)

    def test_dates_past_limit_before_periode_start(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        act = ActiviteFactory(
            portail_reservations_affichage="TOUJOURS",
            portail_afficher_dates_passees="30",
        )
        i = make_inscription(famille, ratt[1].individu, activite=act)
        p = make_periode(act, date_debut=d(-5), date_fin=d(5))
        data = logged_client.get(url_for(i, p)).context["data"]
        assert data["date_min"] == d(-5)

    def test_dates_all_past_dates_shown_with_9999(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        act = ActiviteFactory(
            portail_reservations_affichage="TOUJOURS",
            portail_afficher_dates_passees="9999",
        )
        i = make_inscription(famille, ratt[1].individu, activite=act)
        p = make_periode(act, date_debut=d(-100), date_fin=d(5))
        data = logged_client.get(url_for(i, p)).context["data"]
        assert data["date_min"] == d(-100)
        assert data["date_max"] == d(5)

    def test_vacances_and_feries_in_context(self, logged_client, insc, periode):
        v = make_vacance(d(5), d(8))
        make_vacance(d(100), d(110), nom="Vacances d'ete")  # outside the periode
        f = Ferie.objects.create(
            nom="Ferie", jour=TODAY.day, mois=TODAY.month, type="fixe"
        )
        data = logged_client.get(url_for(insc, periode)).context["data"]
        assert list(data["liste_vacances"]) == [v]
        assert f in list(data["liste_feries"])

    def test_inscription_listed(self, page, insc):
        assert page.context["data"]["liste_inscriptions"] == [insc]

    def test_inscription_ended_before_periode_not_listed(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        i = make_inscription(famille, ratt[1].individu, date_fin=d(-1))
        p = make_periode(i.activite)
        assert (
            logged_client.get(url_for(i, p)).context["data"]["liste_inscriptions"] == []
        )

    def test_inscription_starting_after_periode_not_listed(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        i = make_inscription(famille, ratt[1].individu, date_debut=d(60))
        p = make_periode(i.activite)
        assert (
            logged_client.get(url_for(i, p)).context["data"]["liste_inscriptions"] == []
        )

    def test_inscription_of_other_family_for_same_child_not_listed(
        self, logged_client, famille_user, other_famille, insc, periode
    ):
        _u, _f, ratt_b = other_famille
        RattachementFactory(individu=insc.individu, famille=ratt_b[0].famille)
        InscriptionFactory(
            famille=ratt_b[0].famille,
            individu=insc.individu,
            activite=insc.activite,
            internet_reservations=True,
        )
        data = logged_client.get(url_for(insc, periode)).context["data"]
        assert data["liste_inscriptions"] == [insc]


@pytest.mark.django_db
class TestPlanningTypeDate:
    """periodes computed from the VACANCES / SCOLAIRES type_date."""

    def periodes(self, client, insc, p):
        return json.loads(client.get(url_for(insc, p)).context["data"]["periode_json"])[
            "periodes"
        ]

    def test_toutes_single_period(self, logged_client, insc, periode):
        assert self.periodes(logged_client, insc, periode) == [rng(TODAY, d(30))]

    def test_vacances_clipped_to_periode(self, logged_client, insc):
        make_vacance(d(-5), d(3))  # starts before periode
        make_vacance(d(20), d(40), nom="Vacances d'hiver")  # ends after periode
        make_vacance(d(10), d(12), nom="Vacances de printemps")
        p = make_periode(insc.activite, type_date="VACANCES")
        assert self.periodes(logged_client, insc, p) == [
            rng(TODAY, d(3)),
            rng(d(10), d(12)),
            rng(d(20), d(30)),
        ]

    def test_vacances_none_gives_no_dates(self, logged_client, insc):
        p = make_periode(insc.activite, type_date="VACANCES")
        data = logged_client.get(url_for(insc, p)).context["data"]
        assert json.loads(data["periode_json"])["periodes"] == []
        assert data["liste_dates"] == []

    def test_scolaires_without_vacances(self, logged_client, insc):
        p = make_periode(insc.activite, type_date="SCOLAIRES")
        assert self.periodes(logged_client, insc, p) == [rng(TODAY, d(30))]

    def test_scolaires_vacances_in_the_middle(self, logged_client, insc):
        make_vacance(d(10), d(14))
        p = make_periode(insc.activite, type_date="SCOLAIRES")
        assert self.periodes(logged_client, insc, p) == [
            rng(TODAY, d(9)),
            rng(d(15), d(30)),
        ]

    def test_scolaires_vacances_at_start(self, logged_client, insc):
        make_vacance(d(-3), d(4))
        p = make_periode(insc.activite, type_date="SCOLAIRES")
        assert self.periodes(logged_client, insc, p) == [rng(d(5), d(30))]

    def test_scolaires_vacances_at_end(self, logged_client, insc):
        make_vacance(d(25), d(50))
        p = make_periode(insc.activite, type_date="SCOLAIRES")
        assert self.periodes(logged_client, insc, p) == [rng(TODAY, d(24))]

    def test_scolaires_two_vacances(self, logged_client, insc):
        make_vacance(d(5), d(7))
        make_vacance(d(15), d(17), nom="Vacances d'hiver")
        p = make_periode(insc.activite, type_date="SCOLAIRES")
        assert self.periodes(logged_client, insc, p) == [
            rng(TODAY, d(4)),
            rng(d(8), d(14)),
            rng(d(18), d(30)),
        ]

    def test_scolaires_vacances_covering_whole_periode(self, logged_client, insc):
        make_vacance(d(-5), d(60))
        p = make_periode(insc.activite, type_date="SCOLAIRES")
        data = logged_client.get(url_for(insc, p)).context["data"]
        assert json.loads(data["periode_json"])["periodes"] == []


@pytest.mark.django_db
class TestPlanningModifiableDates:
    def test_all_dates_modifiable_by_default(self, logged_client, insc, periode):
        make_ouvertures(insc, make_unite(insc.activite), range(14))
        data = logged_client.get(url_for(insc, periode)).context["data"]
        assert data["liste_dates"] == [d(n) for n in range(14)]
        assert data["dates_modifiables"] == data["liste_dates"]
        assert data["date_modifiable_min"] == TODAY
        assert data["date_modifiable_max"] == d(13)
        assert sorted(data["jours_semaine_modifiables"]) == [0, 1, 2, 3, 4, 5, 6]

    def test_no_opening_no_dates(self, page):
        data = page.context["data"]
        assert data["liste_dates"] == []
        assert data["dates_modifiables"] == []
        assert "date_modifiable_min" not in data

    def test_consultation_mode_no_modifiable_date(self, logged_client, insc):
        make_ouvertures(insc, make_unite(insc.activite), range(5))
        p = make_periode(insc.activite, mode_consultation=True)
        data = logged_client.get(url_for(insc, p)).context["data"]
        assert data["dates_modifiables"] == []
        assert "date_modifiable_min" not in data
        assert data["jours_semaine_modifiables"] == []

    def test_limit_excludes_near_dates(self, logged_client, famille_user):
        """portail_reservations_limite "J-5 at 00:00": dates within 5 days are locked."""
        _u, famille, ratt = famille_user
        act = ActiviteFactory(
            portail_reservations_affichage="TOUJOURS",
            portail_reservations_limite="5#00:00",
        )
        i = make_inscription(famille, ratt[1].individu, activite=act)
        p = make_periode(act, date_debut=TODAY, date_fin=d(10))
        make_ouvertures(i, make_unite(act), range(11))
        data = logged_client.get(url_for(i, p)).context["data"]
        assert data["dates_modifiables"]
        assert min(data["dates_modifiables"]) > d(3)
        assert data["date_modifiable_min"] == min(data["dates_modifiables"])
        assert data["date_modifiable_max"] == d(10)
        assert TODAY not in data["dates_modifiables"]


# --------------------------------------------------------------------------- POST


def conso_dict(insc, unite, pk="1-1", date=None, **kwargs):
    d_ = {
        "pk": pk,
        "individu": insc.individu_id,
        "famille": insc.famille_id,
        "inscription": insc.pk,
        "activite": insc.activite_id,
        "date": str(date or TODAY),
        "unite": unite.pk,
        "groupe": insc.groupe_id,
        "heure_debut": None,
        "heure_fin": None,
        "etat": "reservation",
        "categorie_tarif": None,
        "prestation": None,
        "quantite": 1,
        "evenement": None,
        "badgeage_debut": None,
        "badgeage_fin": None,
        "dirty": True,
    }
    d_.update(kwargs)
    return d_


def donnees(consos=None, suppr_consos=None):
    return {
        "consommations": {"k": consos or []},
        "prestations": {},
        "memos": {},
        "suppressions": {
            "consommations": suppr_consos or [],
            "prestations": [],
            "memos": [],
        },
    }


@pytest.fixture
def unite(insc):
    return make_unite(insc.activite)


@pytest.fixture
def modele_email(db):
    return ModeleEmail.objects.create(
        categorie="portail_confirmation_reservations",
        nom="Conf",
        objet="Confirmation",
        html="<p>{DETAIL_MODIFICATIONS}</p>",
        defaut=True,
    )


def post(client, insc, periode, payload):
    return client.post(url_for(insc, periode), {"donnees": json.dumps(payload)})


@pytest.mark.django_db
class TestPlanningPost:
    def test_post_adds_consommation_and_redirects(
        self, logged_client, insc, periode, unite
    ):
        r = post(logged_client, insc, periode, donnees([conso_dict(insc, unite)]))
        assert r.status_code == 302
        assert r.url == reverse("portail_reservations")
        c = Consommation.objects.get()
        assert (c.individu_id, c.unite_id, c.date, c.etat) == (
            insc.individu_id,
            unite.pk,
            TODAY,
            "reservation",
        )

    def test_post_removes_consommation(self, logged_client, insc, periode, unite):
        c = Consommation.objects.create(
            individu=insc.individu,
            inscription=insc,
            activite=insc.activite,
            date=TODAY,
            unite=unite,
            groupe=insc.groupe,
            etat="reservation",
        )
        r = post(logged_client, insc, periode, donnees(suppr_consos=[c.pk]))
        assert r.status_code == 302
        assert not Consommation.objects.filter(pk=c.pk).exists()

    def test_post_without_sender_address_sends_no_mail(
        self, logged_client, insc, periode, unite
    ):
        with mock.patch.object(View, "Envoi_mail_confirmation") as envoi:
            post(logged_client, insc, periode, donnees([conso_dict(insc, unite)]))
        envoi.assert_not_called()

    def test_post_with_sender_address_calls_mail_confirmation(
        self, logged_client, insc, periode, unite, set_parametre_portail
    ):
        adresse = AdresseMailFactory()
        set_parametre_portail("reservations_adresse_exp", adresse.pk)
        with mock.patch.object(View, "Envoi_mail_confirmation") as envoi:
            r = post(logged_client, insc, periode, donnees([conso_dict(insc, unite)]))
        assert r.status_code == 302
        envoi.assert_called_once()
        kwargs = envoi.call_args.kwargs
        assert kwargs["idadresse_exp"] == str(adresse.pk)
        assert (
            kwargs["resultat"]["liste_historique"][0]["titre"]
            == "Ajout d'une consommation"
        )

    def test_post_forbidden_for_other_family_child(
        self, logged_client, other_famille, insc, periode, unite
    ):
        _u, _f, ratt_b = other_famille
        r = logged_client.post(
            reverse(URL, args=[ratt_b[1].individu.pk, insc.activite.pk, periode.pk]),
            {"donnees": json.dumps(donnees([conso_dict(insc, unite)]))},
        )
        assert r.status_code == 403
        assert not Consommation.objects.exists()

    @pytest.mark.xfail(
        reason="BUG: portail/views/planning.py:39-48 post() calls Save_grille without checking periode.mode_consultation (only enforced client-side via is_modif_allowed), so a forged POST writes in a read-only periode",
        strict=True,
    )
    def test_post_forbidden_in_consultation_mode(self, logged_client, insc, unite):
        """mode_consultation periodes are read-only: a forged POST must not write consommations."""
        p = make_periode(insc.activite, mode_consultation=True)
        r = post(logged_client, insc, p, donnees([conso_dict(insc, unite)]))
        assert r.status_code == 403
        assert not Consommation.objects.exists()

    @pytest.mark.xfail(
        reason="BUG: portail/views/planning.py:39-48 post() never re-validates dates against activite.portail_reservations_limite (is_modif_allowed is template-only), so a forged POST can add/remove consommations after the deadline",
        strict=True,
    )
    def test_post_forbidden_for_locked_date(self, logged_client, famille_user):
        """A forged POST on a date locked by portail_reservations_limite must be refused."""
        _u, famille, ratt = famille_user
        act = ActiviteFactory(
            portail_reservations_affichage="TOUJOURS",
            portail_reservations_limite="5#00:00",
        )
        i = make_inscription(famille, ratt[1].individu, activite=act)
        u = make_unite(act)
        p = make_periode(act, date_debut=TODAY, date_fin=d(10))
        r = post(logged_client, i, p, donnees([conso_dict(i, u, date=TODAY)]))
        assert r.status_code == 403
        assert not Consommation.objects.exists()


# ------------------------------------------------------------- Envoi_mail_confirmation


def hist(titre, detail):
    return {"titre": titre, "detail": detail}


def view_activite_nom(view):
    from core.models import Activite

    return Activite.objects.get(pk=view.kwargs["idactivite"]).nom


def make_view(client, insc, periode, user):
    view = View()
    view.kwargs = {
        "idindividu": insc.individu_id,
        "idactivite": insc.activite_id,
        "idperiode": periode.pk,
    }
    view.request = mock.Mock(user=user)
    return view


@pytest.fixture
def mail_view(famille_user, insc, periode):
    user, _f, _r = famille_user
    return make_view(None, insc, periode, user), user


@pytest.mark.django_db
class TestEnvoiMailConfirmation:
    def run(self, mail_view, historique, detail_evenements=None, idadresse_exp=None):
        view, _user = mail_view
        resultat = {
            "liste_historique": historique,
            "detail_evenements": detail_evenements or {},
        }
        return view.Envoi_mail_confirmation(
            request=view.request, resultat=resultat, idadresse_exp=idadresse_exp
        )

    def test_no_relevant_history_returns_false(self, mail_view):
        assert (
            self.run(mail_view, [hist("Ajout d'une prestation", "x")], idadresse_exp=1)
            is False
        )
        assert not Mail.objects.exists()

    def test_empty_history_returns_false(self, mail_view):
        assert self.run(mail_view, []) is False

    def test_identical_add_and_remove_cancel_out(self, mail_view):
        h = [
            hist("Ajout d'une consommation", "Journee du 01/01/2030 (Réservation)"),
            hist(
                "Suppression d'une consommation", "Journee du 01/01/2030 (Réservation)"
            ),
        ]
        assert self.run(mail_view, h) is False

    def test_missing_sender_address_logs_error_and_returns_none(
        self, mail_view, caplog
    ):
        h = [hist("Ajout d'une consommation", "A")]
        assert self.run(mail_view, h, idadresse_exp=None) is None
        assert "Aucune adresse d'expédition" in caplog.text
        assert not Mail.objects.exists()

    def test_missing_modele_logs_error_and_returns_none(self, mail_view, caplog):
        adresse = AdresseMailFactory()
        h = [hist("Ajout d'une consommation", "A")]
        assert self.run(mail_view, h, idadresse_exp=adresse.pk) is None
        assert "portail_confirmation_reservations" in caplog.text
        assert not Mail.objects.exists()

    def test_inactive_sender_address_raises_does_not_exist(
        self, mail_view, modele_email
    ):
        """AdresseMail.objects.get(actif=True) raises DoesNotExist for an inactive address (the `if not adresse_exp` guard is unreachable)."""
        adresse = AdresseMailFactory(actif=False)
        h = [hist("Ajout d'une consommation", "A")]
        with pytest.raises(AdresseMail.DoesNotExist):
            self.run(mail_view, h, idadresse_exp=adresse.pk)

    def test_mail_created_and_sent_with_additions_and_removals(
        self, mail_view, modele_email, famille_user
    ):
        view, user = mail_view
        _u, famille, _r = famille_user
        adresse = AdresseMailFactory()
        h = [
            hist("Ajout d'une consommation", "Journee du 02/01/2030 (Réservation)"),
            hist("Ajout d'une consommation", "Repas du 03/01/2030 (Réservation)"),
            hist(
                "Suppression d'une consommation", "Journee du 04/01/2030 (Réservation)"
            ),
            hist("Modification d'une consommation", "ignored"),
        ]
        with mock.patch(
            "portail.views.planning.utils_email.Envoyer_model_mail"
        ) as envoi:
            self.run(
                mail_view,
                h,
                detail_evenements={1: "Detail evt"},
                idadresse_exp=adresse.pk,
            )
        mail = Mail.objects.get()
        assert mail.categorie == "portail_confirmation_reservations"
        assert mail.objet == "Confirmation"
        assert mail.adresse_exp == adresse
        assert mail.selection == "NON_ENVOYE"
        assert mail.utilisateur == user
        envoi.assert_called_once_with(idmail=mail.pk, request=view.request)
        dest = mail.destinataires.get()
        assert dest.famille == famille
        valeurs = json.loads(dest.valeurs)
        detail = valeurs["{DETAIL_MODIFICATIONS}"]
        assert "Ajouts de consommations" in detail
        assert " - Journee du 02/01/2030 (Réservation)<br>" in detail
        assert " - Repas du 03/01/2030 (Réservation) : Detail evt<br>" in detail
        assert "<br><b>Suppressions de consommations" in detail
        assert " - Journee du 04/01/2030 (Réservation)<br>" in detail
        assert "ignored" not in detail
        assert valeurs["{ACTIVITE_NOM}"] == view_activite_nom(view)
        assert valeurs["{PERIODE_NOM}"] == "Periode"

    def test_only_suppressions_has_no_leading_br(self, mail_view, modele_email):
        adresse = AdresseMailFactory()
        h = [
            hist(
                "Suppression d'une consommation", "Journee du 04/01/2030 (Réservation)"
            )
        ]
        with mock.patch("portail.views.planning.utils_email.Envoyer_model_mail"):
            self.run(mail_view, h, idadresse_exp=adresse.pk)
        dest = Destinataire.objects.get()
        detail = json.loads(dest.valeurs)["{DETAIL_MODIFICATIONS}"]
        assert detail.startswith("<b>Suppressions de consommations")
        assert "Ajouts" not in detail

    def test_request_none_creates_mail_without_user(self, mail_view, modele_email):
        view, _user = mail_view
        adresse = AdresseMailFactory()
        h = [hist("Ajout d'une consommation", "A")]
        with mock.patch("portail.views.planning.utils_email.Envoyer_model_mail"):
            view.Envoi_mail_confirmation(
                request=None,
                resultat={"liste_historique": h, "detail_evenements": {}},
                idadresse_exp=adresse.pk,
            )
        assert Mail.objects.get().utilisateur is None
