"""Tests for portail/views/reglements.py: the règlements page, and the AJAX receipt printing.

PDF generation (fiche_famille.views.reglement_recu.Generer_recu) is mocked.
"""

import datetime
import json
from unittest import mock

import pytest
from django.urls import reverse

URL = "portail_reglements"
URL_RECU = "portail_ajax_imprimer_recu"
AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
GENERER = "fiche_famille.views.reglement_recu.Generer_recu"


def _reglement(
    famille,
    montant=30,
    date=datetime.date(2026, 3, 1),
    numero_piece=None,
    depot=None,
    label="Chèque",
):
    from core.models import (
        CompteBancaire,
        ModeleImpression,
        ModeReglement,
        Payeur,
        Reglement,
    )

    return Reglement.objects.create(
        famille=famille,
        date=date,
        montant=montant,
        numero_piece=numero_piece,
        depot=depot,
        mode=ModeReglement.objects.create(label=label),
        payeur=Payeur.objects.create(famille=famille, nom="Payeur"),
        compte=CompteBancaire.objects.create(nom="Compte"),
        modelimp=ModeleImpression.objects.create(
            categorie="reglement", nom="m", options="{}"
        ),
    )


def _modele(**options):
    from core.models import ModeleImpression

    opts = {"signataire": "Le trésorier", "intro": "Reçu", "afficher_prestations": True}
    opts.update(options)
    return ModeleImpression.objects.create(
        categorie="recu", nom="Reçu", options=json.dumps(opts)
    )


# --------------------------------------------------------------------------- page
@pytest.mark.django_db
class TestReglementsPage:
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
        assert list(response.context["liste_reglements"]) == []
        assert "Aucun règlement." in response.content.decode()
        assert response.context["page_titre"] == "Règlements"

    def test_lists_reglements_most_recent_first(self, logged_client, famille_user):
        famille = famille_user[1]
        old = _reglement(famille, date=datetime.date(2025, 1, 1))
        new = _reglement(famille, date=datetime.date(2026, 6, 1))
        response = logged_client.get(reverse(URL))
        assert list(response.context["liste_reglements"]) == [new, old]
        assert "Aucun règlement." not in response.content.decode()

    def test_other_familles_reglements_hidden(self, logged_client, other_famille):
        _reglement(other_famille[1], montant=999)
        response = logged_client.get(reverse(URL))
        assert list(response.context["liste_reglements"]) == []

    def test_card_number_is_masked(self, logged_client, famille_user):
        _reglement(famille_user[1], numero_piece="1234567890")
        content = logged_client.get(reverse(URL)).content.decode()
        assert "****890" in content
        assert "1234567890" not in content

    def test_encaissement_column_hidden_when_disabled(
        self, logged_client, famille_user, set_parametre_portail
    ):
        set_parametre_portail("reglements_afficher_encaissement", False)
        _reglement(famille_user[1])
        assert "Encaissé" not in logged_client.get(reverse(URL)).content.decode()

    def test_encaissement_column_shown_with_depot(
        self, logged_client, famille_user, set_parametre_portail
    ):
        from core.models import CompteBancaire, Depot
        from tests.unit.factories import ActiviteFactory

        set_parametre_portail("reglements_afficher_encaissement", True)
        depot = Depot.objects.create(
            date=datetime.date(2026, 4, 2),
            nom="D",
            compte=CompteBancaire.objects.create(nom="C2"),
            activite=ActiviteFactory(),  # Depot.activite is NOT NULL since main's migrations
        )
        _reglement(famille_user[1], depot=depot)
        content = logged_client.get(reverse(URL)).content.decode()
        assert "Encaissé" in content
        assert "02/04/2026" in content

    def test_encaissement_column_shows_non_without_depot(
        self, logged_client, famille_user, set_parametre_portail
    ):
        set_parametre_portail("reglements_afficher_encaissement", True)
        _reglement(famille_user[1])
        assert "Non</span>" in logged_client.get(reverse(URL)).content.decode()

    def test_download_button_hidden_by_default(self, logged_client, famille_user):
        _reglement(famille_user[1])
        assert (
            'bouton_imprimer_recu" title'
            not in logged_client.get(reverse(URL)).content.decode()
        )

    def test_download_button_shown_when_enabled(
        self, logged_client, famille_user, set_parametre_portail
    ):
        reglement = _reglement(famille_user[1])
        modele = _modele()
        set_parametre_portail("reglements_autoriser_telechargement_recu", True)
        set_parametre_portail("reglements_modele_impression_recu", modele.pk)
        content = logged_client.get(reverse(URL)).content.decode()
        assert f'data-idreglement="{reglement.pk}"' in content


# --------------------------------------------------------------------------- AJAX receipt
@pytest.mark.django_db
class TestImprimerRecu:
    def _post(self, client, reglement, modele, **extra):
        return client.post(
            reverse(URL_RECU),
            {"idreglement": reglement.pk, "idmodele_impression": modele.pk, **extra},
            **AJAX,
        )

    def test_anonymous_forbidden(self, client, organisateur):
        assert client.post(reverse(URL_RECU), {}, **AJAX).status_code == 403

    def test_staff_forbidden(self, client, staff_user, organisateur):
        client.force_login(staff_user)
        assert client.post(reverse(URL_RECU), {}, **AJAX).status_code == 403

    def test_non_ajax_bad_request(self, logged_client):
        assert logged_client.post(reverse(URL_RECU), {}).status_code == 400

    def test_success_returns_generer_recu_result_and_stores_recu(
        self, logged_client, famille_user
    ):
        from core.models import Recu

        user, famille, _ = famille_user
        reglement = _reglement(famille)
        modele = _modele()
        with mock.patch(
            GENERER, return_value={"nom_fichier": "/media/x.pdf"}
        ) as generer:
            response = self._post(logged_client, reglement, modele)
        assert response.status_code == 200
        assert response.json() == {"nom_fichier": "/media/x.pdf"}
        donnees = generer.call_args.kwargs["donnees"]
        assert donnees["idreglement"] == reglement.pk
        assert donnees["numero"] == 1
        assert donnees["idfamille"] == famille.pk
        assert donnees["signataire"] == "Le trésorier"
        assert donnees["intro"] == "Reçu"
        assert donnees["afficher_prestations"] is True
        assert donnees["date_edition"] == datetime.date.today()
        recu = Recu.objects.get()
        assert (recu.numero, recu.famille, recu.reglement, recu.utilisateur) == (
            1,
            famille,
            reglement,
            user,
        )

    def test_receipt_number_increments(self, logged_client, famille_user):
        from core.models import Recu

        user, famille, _ = famille_user
        reglement = _reglement(famille)
        modele = _modele()
        Recu.objects.create(
            numero=41,
            famille=famille,
            date_edition=datetime.date(2026, 1, 1),
            reglement=reglement,
            utilisateur=user,
        )
        with mock.patch(GENERER, return_value={}) as generer:
            self._post(logged_client, reglement, modele)
        assert generer.call_args.kwargs["donnees"]["numero"] == 42
        assert Recu.objects.count() == 2

    def test_generer_recu_error_is_forwarded(self, logged_client, famille_user):
        reglement = _reglement(famille_user[1])
        with mock.patch(
            GENERER,
            return_value={"erreur": "Modèle d'impression non associé au règlement"},
        ):
            response = self._post(logged_client, reglement, _modele())
        assert response.json() == {
            "erreur": "Modèle d'impression non associé au règlement"
        }

    def test_other_familles_reglement_never_printed(self, logged_client, other_famille):
        from core.models import Recu

        reglement = _reglement(other_famille[1])
        logged_client.raise_request_exception = False
        with mock.patch(GENERER) as generer:
            response = self._post(logged_client, reglement, _modele())
        assert response.status_code != 200
        generer.assert_not_called()
        assert not Recu.objects.exists()

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "BUG: reglements.py:~27 - Reglement.objects.get(pk=..., famille=...) is not guarded: a règlement "
            "that belongs to another family (or does not exist) raises DoesNotExist -> HTTP 500 instead of 403/404."
        ),
    )
    def test_other_familles_reglement_is_404_not_500(
        self, logged_client, other_famille
    ):
        reglement = _reglement(other_famille[1])
        logged_client.raise_request_exception = False
        with mock.patch(GENERER):
            response = self._post(logged_client, reglement, _modele())
        assert response.status_code in (403, 404)

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "BUG: reglements.py:~21 - missing/unknown idmodele_impression raises ModelImpression.DoesNotExist "
            "-> HTTP 500 instead of a 400 JSON error."
        ),
    )
    def test_missing_parameters_is_400(self, logged_client):
        logged_client.raise_request_exception = False
        response = logged_client.post(reverse(URL_RECU), {}, **AJAX)
        assert response.status_code == 400

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "BUG: reglements.py:~19 - int(request.POST[...]) on a non-numeric value raises ValueError "
            "-> HTTP 500 instead of a 400 JSON error."
        ),
    )
    def test_non_numeric_ids_is_400(self, logged_client):
        logged_client.raise_request_exception = False
        response = logged_client.post(
            reverse(URL_RECU),
            {"idreglement": "abc", "idmodele_impression": "x"},
            **AJAX,
        )
        assert response.status_code == 400

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "BUG: reglements.py:~16 - the endpoint ignores the portal setting "
            "`reglements_autoriser_telechargement_recu` (default off): a family can still generate receipts "
            "by POSTing directly, and it trusts the client-supplied idmodele_impression instead of "
            "`reglements_modele_impression_recu`."
        ),
    )
    def test_download_refused_when_feature_disabled(self, logged_client, famille_user):
        reglement = _reglement(famille_user[1])
        with mock.patch(GENERER, return_value={}):
            response = self._post(logged_client, reglement, _modele())
        assert response.status_code in (403, 404)
