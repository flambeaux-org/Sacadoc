"""Branch tests for portail.views.accueil.Accueil (counters, adhesions, articles, popups)."""

import datetime

import pytest
from core.models import Article, Consommation, Lecture, TypeCotisation, TypeMaladie
from django.urls import reverse
from tests.unit.factories import (
    ActiviteFactory,
    GroupeFactory,
    InscriptionFactory,
    SondageFactory,
    StructureFactory,
)

URL = "portail_accueil"


def article(structure, **kw):
    kw.setdefault("titre", "Titre")
    kw.setdefault("texte", "Texte")
    kw.setdefault("public", "toutes")
    kw.setdefault("statut", "publie")
    kw.setdefault("date_debut", datetime.datetime.now() - datetime.timedelta(days=1))
    return Article.objects.create(structure=structure, **kw)


@pytest.fixture
def struct(db):
    return StructureFactory()


@pytest.mark.django_db
class TestAccess:
    def test_anonymous_redirected_to_login(self, client):
        response = client.get(reverse(URL))
        assert response.status_code == 302 and "connexion" in response.url

    def test_staff_redirected_to_bureau_accueil(self, client, staff_user):
        client.force_login(staff_user)
        response = client.get(reverse(URL))
        assert response.status_code == 302
        assert response.url == reverse("accueil")


@pytest.mark.django_db
class TestCounters:
    def test_defaults_zero(self, logged_client, famille_user):
        ctx = logged_client.get(reverse(URL)).context
        assert ctx["nbre_pieces_manquantes"] == 0
        assert ctx["nbre_questionnaires_manquants"] == 0
        assert ctx["nbre_vaccinations_manquantes"] == 0
        assert ctx["nbre_verifications_manquantes"] == 0
        assert ctx["nbre_sondages_manquants"] == 0
        assert ctx["nbre_messages_non_lus"] == 0
        assert (
            ctx["nbre_renseignements_manquants"] > 0
        )  # raw family has incomplete identity
        assert ctx["articles"] == [] and ctx["articles_popups"] == []

    def test_vaccinations_and_verifications_and_sondages(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        TypeMaladie.objects.create(nom="Tétanos", vaccin_obligatoire=True)
        act = ActiviteFactory()
        InscriptionFactory(
            individu=ratt[1].individu,
            famille=famille,
            activite=act,
            besoin_certification=True,
        )
        SondageFactory(public="famille", structure=act.structure)
        ctx = logged_client.get(reverse(URL)).context
        assert ctx["nbre_vaccinations_manquantes"] == 1
        assert ctx["nbre_verifications_manquantes"] == 1
        assert ctx["nbre_sondages_manquants"] == 1


@pytest.mark.django_db
class TestCotisations:
    def test_absent_when_parameter_disabled(self, logged_client, famille_user):
        assert "cotisations_manquantes" not in logged_client.get(reverse(URL)).context

    def test_present_when_parameter_enabled(
        self, logged_client, famille_user, set_parametre_portail
    ):
        set_parametre_portail("cotisations_afficher_page", True)
        _u, famille, ratt = famille_user
        act = ActiviteFactory()
        act.cotisations.add(
            TypeCotisation.objects.create(nom="Adhésion", type="famille")
        )
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        ctx = logged_client.get(reverse(URL)).context
        assert len(ctx["cotisations_manquantes"]) == 1


@pytest.mark.django_db
class TestArticles:
    def test_published_article_for_all(self, logged_client, famille_user, struct):
        a = article(struct)
        assert logged_client.get(reverse(URL)).context["articles"] == [a]

    def test_filters_unpublished_future_expired_and_hidden_structure(
        self, logged_client, famille_user, struct
    ):
        now = datetime.datetime.now()
        article(struct, statut="non_publie")
        article(struct, date_debut=now + datetime.timedelta(days=2))
        article(struct, date_fin=now - datetime.timedelta(hours=1))
        article(StructureFactory(visible=False))
        ok_open = article(
            struct, date_fin=now + datetime.timedelta(days=2), titre="ouvert"
        )
        assert logged_client.get(reverse(URL)).context["articles"] == [ok_open]

    def test_inscrits_article_requires_matching_activity(
        self, logged_client, famille_user, struct
    ):
        _u, famille, ratt = famille_user
        act = ActiviteFactory(structure=struct)
        other = ActiviteFactory(structure=struct)
        InscriptionFactory(individu=ratt[1].individu, famille=famille, activite=act)
        mine = article(struct, public="inscrits", titre="mine")
        mine.activites.add(act)
        theirs = article(struct, public="inscrits", titre="theirs")
        theirs.activites.add(other)
        assert logged_client.get(reverse(URL)).context["articles"] == [mine]

    def test_articles_ordered_most_recent_first(
        self, logged_client, famille_user, struct
    ):
        now = datetime.datetime.now()
        old = article(struct, date_debut=now - datetime.timedelta(days=5), titre="old")
        new = article(struct, date_debut=now - datetime.timedelta(days=1), titre="new")
        assert logged_client.get(reverse(URL)).context["articles"] == [new, old]

    def test_article_with_survey_still_displayed(
        self, logged_client, famille_user, struct
    ):
        a = article(struct, sondage=SondageFactory(structure=struct))
        assert logged_client.get(reverse(URL)).context["articles"] == [a]


@pytest.mark.django_db
class TestPresentsArticles:
    """'presents' / 'presents_groupes' are no longer offered in the form choices but the view still handles them."""

    def _conso(self, famille, ratt, act, groupe=None, etat="present", date=None):
        insc = (
            InscriptionFactory(
                individu=ratt.individu, famille=famille, activite=act, groupe=groupe
            )
            if groupe
            else InscriptionFactory(
                individu=ratt.individu, famille=famille, activite=act
            )
        )
        return Consommation.objects.create(
            inscription=insc,
            individu=ratt.individu,
            activite=act,
            groupe=insc.groupe,
            date=date or datetime.date.today(),
            etat=etat,
        )

    def test_presents_shown_when_family_present_in_activity(
        self, logged_client, famille_user, struct
    ):
        _u, famille, ratt = famille_user
        act = ActiviteFactory(structure=struct)
        self._conso(famille, ratt[1], act)
        a = article(
            struct,
            public="presents",
            present_debut=datetime.date.today() - datetime.timedelta(days=1),
            present_fin=datetime.date.today() + datetime.timedelta(days=1),
        )
        a.activites.add(act)
        assert logged_client.get(reverse(URL)).context["articles"] == [a]

    def test_presents_hidden_without_consommation(
        self, logged_client, famille_user, struct
    ):
        act = ActiviteFactory(structure=struct)
        a = article(
            struct,
            public="presents",
            present_debut=datetime.date.today(),
            present_fin=datetime.date.today(),
        )
        a.activites.add(act)
        assert logged_client.get(reverse(URL)).context["articles"] == []

    def test_presents_hidden_when_consommation_outside_period_or_state(
        self, logged_client, famille_user, struct
    ):
        _u, famille, ratt = famille_user
        act = ActiviteFactory(structure=struct)
        self._conso(famille, ratt[1], act, etat="absent")
        a = article(
            struct,
            public="presents",
            present_debut=datetime.date.today(),
            present_fin=datetime.date.today(),
        )
        a.activites.add(act)
        assert logged_client.get(reverse(URL)).context["articles"] == []

    def test_presents_groupes_shown_for_matching_group(
        self, logged_client, famille_user, struct
    ):
        _u, famille, ratt = famille_user
        act = ActiviteFactory(structure=struct)
        groupe = GroupeFactory(activite=act)
        self._conso(famille, ratt[1], act, groupe=groupe, etat="reservation")
        a = article(
            struct,
            public="presents_groupes",
            present_debut=datetime.date.today(),
            present_fin=datetime.date.today(),
        )
        a.groupes.add(groupe)
        assert logged_client.get(reverse(URL)).context["articles"] == [a]

    def test_presents_groupes_hidden_for_other_group(
        self, logged_client, famille_user, struct
    ):
        _u, famille, ratt = famille_user
        act = ActiviteFactory(structure=struct)
        self._conso(famille, ratt[1], act, groupe=GroupeFactory(activite=act))
        a = article(
            struct,
            public="presents_groupes",
            present_debut=datetime.date.today(),
            present_fin=datetime.date.today(),
        )
        a.groupes.add(GroupeFactory(activite=act))
        assert logged_client.get(reverse(URL)).context["articles"] == []


@pytest.mark.django_db
class TestPopups:
    def test_popup_shown_once_then_marked_read(
        self, logged_client, famille_user, struct
    ):
        _u, famille, _r = famille_user
        a = article(struct, texte_popup="Important !")
        first = logged_client.get(reverse(URL)).context
        assert first["articles_popups"] == [a]
        assert Lecture.objects.filter(famille=famille, article=a).count() == 1
        second = logged_client.get(reverse(URL)).context
        assert second["articles_popups"] == []
        assert second["articles"] == [a]
        assert Lecture.objects.filter(famille=famille, article=a).count() == 1

    def test_article_without_popup_text_creates_no_lecture(
        self, logged_client, famille_user, struct
    ):
        article(struct)
        logged_client.get(reverse(URL))
        assert Lecture.objects.count() == 0

    def test_read_state_is_per_family(
        self, logged_client, famille_user, other_famille, struct
    ):
        _ub, fam_b, _rb = other_famille
        a = article(struct, texte_popup="Hey")
        Lecture.objects.create(famille=fam_b, article=a)
        assert logged_client.get(reverse(URL)).context["articles_popups"] == [a]
