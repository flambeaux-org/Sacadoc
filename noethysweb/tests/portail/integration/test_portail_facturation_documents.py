"""AJAX document endpoints: `get_detail_facture`, `imprimer_facture`, `imprimer_recu`.

PDF generation (`Facturation.Impression`, `Generer_recu`) is mocked: only the view logic
(lookups, ownership, option plumbing, JSON answers) is under test.
"""

import datetime
import json
from unittest import mock

import pytest
from core.models import Recu
from django.test import RequestFactory
from django.urls import reverse
from portail.views import facturation
from test_portail_facturation_support import (
    AJAX,
    make_facture,
    make_modele_impression,
    make_prestation,
    make_reglement,
)
from tests.unit.factories import ActiviteFactory

# --------------------------------------------------------------------------- get_detail_facture


@pytest.mark.django_db
class TestGetDetailFacture:
    url = "portail_ajax_get_detail_facture"

    def test_renders_detail_of_own_facture(self, logged_client, famille_user):
        _u, famille, _r = famille_user
        facture, prestation = make_facture(famille, 75)
        autre = make_prestation(
            famille,
            ActiviteFactory(),
            5,
            facture=facture,
            label="Autre ligne",
            date=datetime.date(2024, 2, 1),
        )
        response = logged_client.post(
            reverse(self.url), {"idfacture": facture.pk}, **AJAX
        )
        assert response.status_code == 200
        assert "portail/detail_facture.html" in [t.name for t in response.templates]
        assert response.context["facture"] == facture
        assert [p.pk for p in response.context["prestations"]] == [
            autre.pk,
            prestation.pk,
        ]  # ordered by date
        assert "parametres_portail" in response.context
        assert b"Autre ligne" in response.content

    def test_other_family_facture_forbidden(self, logged_client, other_famille):
        _u, autre, _r = other_famille
        facture, _ = make_facture(autre, 75)
        response = logged_client.post(
            reverse(self.url), {"idfacture": facture.pk}, **AJAX
        )
        assert response.status_code == 401
        assert response.json() == {"texte": "Accès interdit"}

    def test_facture_without_family_forbidden(self, logged_client):
        from tests.unit.factories import FactureFactory

        facture = FactureFactory(famille=None)
        response = logged_client.post(
            reverse(self.url), {"idfacture": facture.pk}, **AJAX
        )
        assert response.status_code == 401

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:608 `Facture.objects.get(pk=idfacture)` -> DoesNotExist (500) for an "
        "unknown/missing idfacture; should be a 404/400 JSON answer.",
        strict=True,
    )
    @pytest.mark.parametrize("data", [{"idfacture": 999999}, {}])
    def test_unknown_facture_is_client_error(self, logged_client, data):
        response = logged_client.post(reverse(self.url), data, **AJAX)
        assert 400 <= response.status_code < 500


# --------------------------------------------------------------------------- imprimer_facture


@pytest.mark.django_db
class TestImprimerFacture:
    url = "portail_ajax_imprimer_facture"
    options = {"signataire": "x", "titre": "Facture"}

    def _post(self, client, idfacture):
        return client.post(reverse(self.url), {"idfacture": idfacture}, **AJAX)

    def test_unknown_facture_400(self, logged_client):
        response = self._post(logged_client, 999999)
        assert response.status_code == 400
        assert "n'existe pas" in response.json()["error"]

    def test_missing_idfacture_defaults_to_zero_and_400(self, logged_client):
        response = logged_client.post(reverse(self.url), {}, **AJAX)
        assert response.status_code == 400

    @pytest.mark.parametrize("modelimp", [None, "Modele inexistant"])
    def test_unknown_print_model_400(self, logged_client, famille_user, modelimp):
        facture, _ = make_facture(famille_user[1], 10, modelimp=modelimp)
        response = self._post(logged_client, facture.pk)
        assert response.status_code == 400
        assert "modèle d'impression" in response.json()["error"]

    def test_success_returns_pdf_filename_and_passes_options(
        self, logged_client, famille_user
    ):
        modele = make_modele_impression(
            nom="Facture standard", options=self.options, categorie="facture"
        )
        facture, _ = make_facture(famille_user[1], 10, modelimp="Facture standard")
        with mock.patch(
            "facturation.utils.utils_facturation.Facturation"
        ) as facturation_cls:
            facturation_cls.return_value.Impression.return_value = {
                "nom_fichier": "temp/facture.pdf"
            }
            response = self._post(logged_client, facture.pk)
        assert response.status_code == 200
        assert response.json() == {"nom_fichier": "temp/facture.pdf"}
        kwargs = facturation_cls.return_value.Impression.call_args[1]
        assert kwargs["liste_factures"] == [facture.pk]
        assert kwargs["dict_options"]["signataire"] == "x"
        assert kwargs["dict_options"]["modele"] == modele.modele_document

    def test_other_family_facture_is_not_printable(self, logged_client, other_famille):
        make_modele_impression(
            nom="Facture standard", options=self.options, categorie="facture"
        )
        facture, _ = make_facture(other_famille[1], 10, modelimp="Facture standard")
        with mock.patch(
            "facturation.utils.utils_facturation.Facturation"
        ) as facturation_cls:
            facturation_cls.return_value.Impression.return_value = {
                "nom_fichier": "temp/facture.pdf"
            }
            response = self._post(logged_client, facture.pk)
        assert response.status_code in (400, 401, 403, 404)
        facturation_cls.return_value.Impression.assert_not_called()


# --------------------------------------------------------------------------- imprimer_recu
# NB: the portail route "portail_ajax_imprimer_recu" points to reglements.imprimer_recu, so the
# copy living in facturation.py is not routed; it is exercised directly here.


@pytest.mark.django_db
class TestImprimerRecuFacturationModule:
    def _call(self, user, **post):
        request = RequestFactory().post("/x", post)
        request.user = user
        return facturation.imprimer_recu(request)

    @pytest.fixture
    def setup(self, famille_user):
        user, famille, _r = famille_user
        modele = make_modele_impression(
            nom="Recu standard",
            options={
                "signataire": "Le maire",
                "intro": "Recu de",
                "afficher_prestations": True,
            },
            categorie="reglement",
        )
        reglement = make_reglement(famille, 30)
        return user, famille, modele, reglement

    def test_creates_first_receipt_number_one_and_returns_generated_pdf(self, setup):
        user, famille, modele, reglement = setup
        with mock.patch(
            "fiche_famille.views.reglement_recu.Generer_recu",
            return_value={"nom_fichier": "temp/recu.pdf"},
        ) as generer:
            response = self._call(
                user, idreglement=reglement.pk, idmodele_impression=modele.pk
            )
        assert response.status_code == 200
        assert json.loads(response.content) == {"nom_fichier": "temp/recu.pdf"}
        recu = Recu.objects.get()
        assert (recu.numero, recu.famille, recu.reglement, recu.utilisateur) == (
            1,
            famille,
            reglement,
            user,
        )
        assert recu.date_edition == datetime.date.today()
        donnees = generer.call_args[1]["donnees"]
        assert donnees["idreglement"] == reglement.pk
        assert donnees["numero"] == 1
        assert donnees["signataire"] == "Le maire"
        assert donnees["intro"] == "Recu de"
        assert donnees["afficher_prestations"] is True
        assert donnees["idfamille"] == famille.pk
        assert donnees["idmodele"] == modele.pk

    def test_numero_increments_from_last_receipt(self, setup):
        user, famille, modele, reglement = setup
        Recu.objects.create(
            numero=41,
            famille=famille,
            date_edition=datetime.date(2024, 1, 1),
            reglement=reglement,
        )
        with mock.patch(
            "fiche_famille.views.reglement_recu.Generer_recu",
            return_value={"nom_fichier": "x"},
        ):
            self._call(user, idreglement=reglement.pk, idmodele_impression=modele.pk)
        assert Recu.objects.order_by("-numero").first().numero == 42

    def test_other_family_reglement_is_refused(self, setup, other_famille):
        user, _f, modele, _r = setup
        autre_reglement = make_reglement(other_famille[1], 5)
        with pytest.raises(Exception) as excinfo:
            self._call(
                user, idreglement=autre_reglement.pk, idmodele_impression=modele.pk
            )
        assert excinfo.type.__name__ == "DoesNotExist"
        assert Recu.objects.count() == 0

    @pytest.mark.xfail(
        reason="BUG: portail/views/facturation.py:21,26 unknown ModeleImpression / Reglement (or another family's "
        "reglement) raise DoesNotExist -> 500 instead of a 4xx JSON answer.",
        strict=True,
    )
    def test_unknown_objects_do_not_raise(self, setup):
        user, _f, _modele, reglement = setup
        self._call(user, idreglement=reglement.pk, idmodele_impression=0)
