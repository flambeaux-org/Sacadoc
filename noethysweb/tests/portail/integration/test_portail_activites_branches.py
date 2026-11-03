"""Branch-level tests for portail/views/activites.py (activities list + cancel-request AJAX)."""

import datetime
import json

import pytest
from core.models import PortailRenseignement
from django.urls import reverse
from tests.unit.factories import (
    ActiviteFactory,
    IndividuFactory,
    InscriptionFactory,
    RattachementFactory,
)

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
URL = "portail_activites"
URL_CANCEL = "ajax_annulation_portail"

TODAY = datetime.date.today()


def make_demande(famille, individu, valeur, **kwargs):
    defaults = {
        "categorie": "activites",
        "code": "inscrire_activite",
        "etat": "ATTENTE",
    }
    defaults.update(kwargs)
    return PortailRenseignement.objects.create(
        famille=famille, individu=individu, nouvelle_valeur=valeur, **defaults
    )


@pytest.mark.django_db
class TestActivitesPageAccess:
    def test_anonymous_redirected(self, client):
        r = client.get(reverse(URL))
        assert r.status_code == 302 and "connexion" in r.url

    def test_staff_forbidden(self, client, staff_user):
        client.force_login(staff_user)
        assert client.get(reverse(URL)).status_code in (302, 403)


@pytest.mark.django_db
class TestActivitesInscriptions:
    def test_context_basics(self, logged_client):
        r = logged_client.get(reverse(URL))
        assert r.status_code == 200
        assert "Liste des inscriptions" in str(r.context["page_titre"])
        assert r.context["liste_individus"] == []
        assert r.context["demandes_inscriptions_attente"] == []
        assert r.context["nbre_verifications_manquantes"] == 0
        assert isinstance(r.context["nbre_approbations_requises"], int)

    def test_individus_sorted_by_prenom_with_sorted_inscriptions(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        zoe = IndividuFactory(prenom="Zoe")
        RattachementFactory(individu=zoe, famille=famille)
        enfant = ratt[1].individu
        enfant.prenom = "Alice"
        enfant.save()
        a_b = ActiviteFactory(nom="B-act")
        a_a = ActiviteFactory(nom="A-act")
        InscriptionFactory(famille=famille, individu=zoe, activite=a_a)
        InscriptionFactory(famille=famille, individu=enfant, activite=a_b)
        InscriptionFactory(famille=famille, individu=enfant, activite=a_a)
        r = logged_client.get(reverse(URL))
        individus = r.context["liste_individus"]
        assert [i.prenom for i in individus] == ["Alice", "Zoe"]
        assert [i.activite.nom for i in individus[0].inscriptions] == ["A-act", "B-act"]
        assert len(individus[1].inscriptions) == 1

    def test_individu_listed_once_with_several_inscriptions(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        enfant = ratt[1].individu
        InscriptionFactory(famille=famille, individu=enfant)
        InscriptionFactory(famille=famille, individu=enfant)
        r = logged_client.get(reverse(URL))
        assert r.context["liste_individus"].count(enfant) == 1

    def test_waiting_inscription_excluded(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        InscriptionFactory(famille=famille, individu=ratt[1].individu, statut="attente")
        assert logged_client.get(reverse(URL)).context["liste_individus"] == []

    def test_ended_inscription_excluded_open_ended_and_future_included(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        enfant = ratt[1].individu
        InscriptionFactory(
            famille=famille,
            individu=enfant,
            date_fin=TODAY - datetime.timedelta(days=1),
        )
        assert logged_client.get(reverse(URL)).context["liste_individus"] == []
        InscriptionFactory(famille=famille, individu=enfant, date_fin=TODAY)
        assert logged_client.get(reverse(URL)).context["liste_individus"] == [enfant]

    def test_open_ended_inscription_included(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        InscriptionFactory(famille=famille, individu=ratt[1].individu, date_fin=None)
        assert logged_client.get(reverse(URL)).context["liste_individus"] == [
            ratt[1].individu
        ]

    def test_deceased_individu_excluded(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        enfant = ratt[1].individu
        enfant.deces = True
        enfant.save()
        InscriptionFactory(famille=famille, individu=enfant)
        assert logged_client.get(reverse(URL)).context["liste_individus"] == []

    def test_inactive_activity_excluded(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        InscriptionFactory(
            famille=famille,
            individu=ratt[1].individu,
            activite=ActiviteFactory(actif=False),
        )
        assert logged_client.get(reverse(URL)).context["liste_individus"] == []

    def test_masked_individu_excluded(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        enfant = ratt[1].individu
        InscriptionFactory(famille=famille, individu=enfant)
        famille.individus_masques.add(enfant)
        assert logged_client.get(reverse(URL)).context["liste_individus"] == []

    def test_other_family_inscription_not_shown(self, logged_client, other_famille):
        _u, famille_b, ratt_b = other_famille
        InscriptionFactory(famille=famille_b, individu=ratt_b[1].individu)
        assert logged_client.get(reverse(URL)).context["liste_individus"] == []

    def test_nbre_verifications_manquantes(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        InscriptionFactory(
            famille=famille, individu=ratt[1].individu, besoin_certification=True
        )
        InscriptionFactory(
            famille=famille, individu=ratt[1].individu, besoin_certification=False
        )
        assert (
            logged_client.get(reverse(URL)).context["nbre_verifications_manquantes"]
            == 1
        )


@pytest.mark.django_db
class TestActivitesDemandesEnAttente:
    def test_pending_request_shows_activity_name(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        act = ActiviteFactory(nom="Judo")
        make_demande(famille, ratt[1].individu, json.dumps("%d;1;[]" % act.pk))
        demandes = logged_client.get(reverse(URL)).context[
            "demandes_inscriptions_attente"
        ]
        assert [d.nom_activite for d in demandes] == ["Judo"]

    def test_unknown_activity_id_gives_question_mark(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        make_demande(famille, ratt[1].individu, json.dumps("999999;1;[]"))
        demandes = logged_client.get(reverse(URL)).context[
            "demandes_inscriptions_attente"
        ]
        assert [d.nom_activite for d in demandes] == ["?"]

    def test_invalid_json_gives_question_mark(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        make_demande(famille, ratt[1].individu, "not-json")
        demandes = logged_client.get(reverse(URL)).context[
            "demandes_inscriptions_attente"
        ]
        assert [d.nom_activite for d in demandes] == ["?"]

    def test_non_numeric_activity_id_gives_question_mark(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        make_demande(famille, ratt[1].individu, json.dumps("abc;1;[]"))
        demandes = logged_client.get(reverse(URL)).context[
            "demandes_inscriptions_attente"
        ]
        assert [d.nom_activite for d in demandes] == ["?"]

    def test_only_waiting_inscrire_activite_of_own_family(
        self, logged_client, famille_user, other_famille
    ):
        _u, famille, ratt = famille_user
        _ub, famille_b, ratt_b = other_famille
        act = ActiviteFactory()
        val = json.dumps("%d;1;[]" % act.pk)
        make_demande(famille, ratt[1].individu, val, etat="VALIDE")
        make_demande(famille, ratt[1].individu, val, code="autre")
        make_demande(famille_b, ratt_b[1].individu, val)
        assert (
            logged_client.get(reverse(URL)).context["demandes_inscriptions_attente"]
            == []
        )

    def test_requests_ordered_by_individu_prenom(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        act = ActiviteFactory()
        val = json.dumps("%d;1;[]" % act.pk)
        make_demande(famille, ratt[1].individu, val)  # "Premier"
        make_demande(famille, ratt[0].individu, val)  # "Adulte"
        demandes = logged_client.get(reverse(URL)).context[
            "demandes_inscriptions_attente"
        ]
        assert [d.individu.prenom for d in demandes] == ["Adulte", "Premier"]


@pytest.mark.django_db
class TestActivitesOuvertesInscription:
    def test_false_without_open_activity(self, logged_client):
        ActiviteFactory(portail_inscriptions_affichage="JAMAIS")
        assert (
            logged_client.get(reverse(URL)).context["activites_ouvertes_inscription"]
            is False
        )

    def test_true_when_always_visible(self, logged_client):
        ActiviteFactory(portail_inscriptions_affichage="TOUJOURS", visible=True)
        assert (
            logged_client.get(reverse(URL)).context["activites_ouvertes_inscription"]
            is True
        )

    def test_false_when_always_but_not_visible(self, logged_client):
        ActiviteFactory(portail_inscriptions_affichage="TOUJOURS", visible=False)
        assert (
            logged_client.get(reverse(URL)).context["activites_ouvertes_inscription"]
            is False
        )

    def test_period_in_and_out(self, logged_client):
        now = datetime.datetime.now()
        ActiviteFactory(
            portail_inscriptions_affichage="PERIODE",
            portail_inscriptions_date_debut=now + datetime.timedelta(days=1),
            portail_inscriptions_date_fin=now + datetime.timedelta(days=2),
        )
        assert (
            logged_client.get(reverse(URL)).context["activites_ouvertes_inscription"]
            is False
        )
        ActiviteFactory(
            portail_inscriptions_affichage="PERIODE",
            portail_inscriptions_date_debut=now - datetime.timedelta(days=1),
            portail_inscriptions_date_fin=now + datetime.timedelta(days=1),
        )
        assert (
            logged_client.get(reverse(URL)).context["activites_ouvertes_inscription"]
            is True
        )

    def test_template_shows_inscription_link_when_open(self, logged_client):
        ActiviteFactory(portail_inscriptions_affichage="TOUJOURS")
        assert (
            reverse("portail_inscrire_activite")
            in logged_client.get(reverse(URL)).content.decode()
        )


@pytest.mark.django_db
class TestAnnulationAjax:
    def test_non_ajax_bad_request(self, logged_client):
        assert (
            logged_client.post(
                reverse(URL_CANCEL), {"iddemande": 1, "etat": "x"}
            ).status_code
            == 400
        )

    def test_anonymous_forbidden(self, client):
        assert (
            client.post(
                reverse(URL_CANCEL), {"iddemande": 1, "etat": "x"}, **AJAX
            ).status_code
            == 403
        )

    def test_staff_forbidden(self, client, staff_user):
        client.force_login(staff_user)
        assert (
            client.post(
                reverse(URL_CANCEL), {"iddemande": 1, "etat": "x"}, **AJAX
            ).status_code
            == 403
        )

    def test_deletes_request_and_redirects(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        d = make_demande(famille, ratt[1].individu, json.dumps("1;1;[]"))
        r = logged_client.post(
            reverse(URL_CANCEL), {"iddemande": d.pk, "etat": "ANNULE"}, **AJAX
        )
        assert r.status_code == 200
        assert r.json() == {"redirection": reverse("portail_activites")}
        assert not PortailRenseignement.objects.filter(pk=d.pk).exists()

    def test_only_targeted_request_is_deleted(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        d1 = make_demande(famille, ratt[1].individu, json.dumps("1;1;[]"))
        d2 = make_demande(famille, ratt[1].individu, json.dumps("2;1;[]"))
        logged_client.post(
            reverse(URL_CANCEL), {"iddemande": d1.pk, "etat": "ANNULE"}, **AJAX
        )
        assert PortailRenseignement.objects.filter(pk=d2.pk).exists()

    def test_unknown_request_returns_404(self, logged_client):
        response = logged_client.post(
            reverse(URL_CANCEL), {"iddemande": 999999, "etat": "x"}, **AJAX
        )
        assert response.status_code == 404

    def test_non_numeric_id_raises_value_error(self, logged_client):
        with pytest.raises(ValueError):
            logged_client.post(
                reverse(URL_CANCEL), {"iddemande": "abc", "etat": "x"}, **AJAX
            )

    def test_missing_parameters_raise(self, logged_client):
        from django.utils.datastructures import MultiValueDictKeyError

        with pytest.raises(MultiValueDictKeyError):
            logged_client.post(reverse(URL_CANCEL), {}, **AJAX)

    def test_cannot_delete_other_family_request(self, logged_client, other_famille):
        _u, famille_b, ratt_b = other_famille
        d = make_demande(famille_b, ratt_b[1].individu, json.dumps("1;1;[]"))
        logged_client.post(
            reverse(URL_CANCEL), {"iddemande": d.pk, "etat": "ANNULE"}, **AJAX
        )
        assert PortailRenseignement.objects.filter(pk=d.pk).exists()

    def test_cannot_delete_processed_request(self, logged_client, famille_user):
        _u, famille, ratt = famille_user
        d = make_demande(famille, ratt[1].individu, json.dumps("1;1;[]"), etat="VALIDE")
        logged_client.post(
            reverse(URL_CANCEL), {"iddemande": d.pk, "etat": "ANNULE"}, **AJAX
        )
        assert PortailRenseignement.objects.filter(pk=d.pk).exists()
