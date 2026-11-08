# ruff: noqa: RUF012
"""Tests for portail.views.verifications.View (per-individual sheet verification page)."""

import pytest
from core.models import CategorieInformation, Information, Rattachement
from django.urls import reverse
from portail.views import verifications
from tests.unit.factories import ActiviteFactory, IndividuFactory, InscriptionFactory

URL = "portail_verifications"


@pytest.fixture(autouse=True)
def media_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


@pytest.fixture
def insc_a_verifier(famille_user):
    _u, famille, ratt = famille_user
    return InscriptionFactory(
        individu=ratt[1].individu, famille=famille, besoin_certification=True
    )


def add_info(individu):
    cat = CategorieInformation.objects.create(nom="PAI")
    return Information.objects.create(
        individu=individu, categorie=cat, intitule="Asthme"
    )


@pytest.mark.django_db
class TestAuthorization:
    def test_anonymous_get(self, client):
        response = client.get(reverse(URL))
        assert response.status_code == 302 and "connexion" in response.url

    def test_anonymous_post(self, client):
        response = client.post(reverse(URL), {"inscription_id": 1})
        assert response.status_code == 302 and "connexion" in response.url

    def test_staff_denied(self, client, staff_user):
        client.force_login(staff_user)
        assert client.get(reverse(URL)).status_code in (302, 403)

    def test_cannot_validate_other_family_inscription(
        self, logged_client, famille_user, other_famille
    ):
        _u, fam_b, ratt_b = other_famille
        insc = InscriptionFactory(
            individu=ratt_b[1].individu, famille=fam_b, besoin_certification=True
        )
        logged_client.post(
            reverse(URL), {"inscription_id": insc.pk, "confirmation_ras": "on"}
        )
        insc.refresh_from_db()
        assert insc.besoin_certification is True


@pytest.mark.django_db
class TestGet:
    def test_empty_list(self, logged_client, famille_user):
        response = logged_client.get(reverse(URL))
        assert response.status_code == 200
        assert response.context["inscriptions_rattachements"] == []

    def test_lists_inscription_with_pdf(
        self, logged_client, famille_user, insc_a_verifier
    ):
        _u, _f, ratt = famille_user
        response = logged_client.get(reverse(URL))
        assert response.status_code == 200
        items = response.context["inscriptions_rattachements"]
        assert len(items) == 1
        item = items[0]
        assert (
            item["inscription"] == insc_a_verifier and item["rattachement"] == ratt[1]
        )
        assert item["nom_fichier"].startswith("/media") and item[
            "nom_fichier"
        ].endswith(".pdf")
        assert item["aucune_information_medicale"] is True

    def test_flag_false_when_medical_info_exists(
        self, logged_client, famille_user, insc_a_verifier
    ):
        _u, _f, ratt = famille_user
        add_info(ratt[1].individu)
        response = logged_client.get(reverse(URL))
        assert (
            response.context["inscriptions_rattachements"][0][
                "aucune_information_medicale"
            ]
            is False
        )

    def test_inactive_activity_or_already_verified_hidden(
        self, logged_client, famille_user
    ):
        _u, famille, ratt = famille_user
        InscriptionFactory(
            individu=ratt[1].individu,
            famille=famille,
            besoin_certification=True,
            activite=ActiviteFactory(actif=False),
        )
        InscriptionFactory(
            individu=ratt[0].individu, famille=famille, besoin_certification=False
        )
        response = logged_client.get(reverse(URL))
        assert response.context["inscriptions_rattachements"] == []

    def test_other_family_inscription_hidden(
        self, logged_client, famille_user, other_famille
    ):
        _u, fam_b, ratt_b = other_famille
        InscriptionFactory(
            individu=ratt_b[1].individu, famille=fam_b, besoin_certification=True
        )
        response = logged_client.get(reverse(URL))
        assert response.context["inscriptions_rattachements"] == []

    @pytest.mark.xfail(
        reason="BUG: verifications.View.get_context_data builds the PDF with rattachement.pk before checking "
        "`if rattachement`: an inscription whose individu has no rattachement raises AttributeError (500).",
        strict=True,
    )
    def test_inscription_without_rattachement_does_not_crash(
        self, logged_client, famille_user
    ):
        _u, famille, _ratt = famille_user
        InscriptionFactory(
            individu=IndividuFactory(), famille=famille, besoin_certification=True
        )
        response = logged_client.get(reverse(URL))
        assert response.status_code == 200

    @pytest.mark.xfail(
        reason="BUG: when the PDF generator reports errors, get_context_data returns a JsonResponse (401) as the "
        "template *context*; TemplateView.get then fails to render (TypeError/500) instead of returning the JSON error.",
        strict=True,
    )
    def test_pdf_error_returns_json_401(
        self, logged_client, famille_user, insc_a_verifier, monkeypatch
    ):
        class FakeImpression:
            erreurs = ["boom"]

            def __init__(self, *a, **kw):
                pass

        monkeypatch.setattr(
            verifications.utils_impression_renseignements, "Impression", FakeImpression
        )
        response = logged_client.get(reverse(URL))
        assert response.status_code == 401
        assert response.json() == {"erreur": "boom"}


@pytest.mark.django_db
class TestPost:
    def test_missing_inscription_id(self, logged_client, famille_user):
        response = logged_client.post(reverse(URL), {}, follow=True)
        assert response.redirect_chain[-1][0] == reverse(URL)
        assert "Inscription non spécifiée." in [
            str(m) for m in response.context["messages"]
        ]

    def test_unknown_inscription_404(self, logged_client, famille_user):
        assert (
            logged_client.post(reverse(URL), {"inscription_id": 999999}).status_code
            == 404
        )

    def test_ras_confirmation_required_when_no_medical_info(
        self, logged_client, famille_user, insc_a_verifier
    ):
        response = logged_client.post(
            reverse(URL), {"inscription_id": insc_a_verifier.pk}, follow=True
        )
        insc_a_verifier.refresh_from_db()
        assert insc_a_verifier.besoin_certification is True
        assert any(
            "absence d'information médicale" in str(m)
            for m in response.context["messages"]
        )

    def test_wrong_ras_value_rejected(
        self, logged_client, famille_user, insc_a_verifier
    ):
        logged_client.post(
            reverse(URL),
            {"inscription_id": insc_a_verifier.pk, "confirmation_ras": "off"},
        )
        insc_a_verifier.refresh_from_db()
        assert insc_a_verifier.besoin_certification is True

    def test_validates_with_ras_confirmation(
        self, logged_client, famille_user, insc_a_verifier
    ):
        _u, _f, ratt = famille_user
        response = logged_client.post(
            reverse(URL),
            {"inscription_id": insc_a_verifier.pk, "confirmation_ras": "on"},
            follow=True,
        )
        insc_a_verifier.refresh_from_db()
        assert insc_a_verifier.besoin_certification is False
        ratt[1].refresh_from_db()
        assert ratt[1].certification_date is not None
        assert any(
            "Vérification validée pour" in str(m) for m in response.context["messages"]
        )

    def test_validates_without_confirmation_when_medical_info_exists(
        self, logged_client, famille_user, insc_a_verifier
    ):
        _u, _f, ratt = famille_user
        add_info(ratt[1].individu)
        response = logged_client.post(
            reverse(URL), {"inscription_id": insc_a_verifier.pk}, follow=True
        )
        insc_a_verifier.refresh_from_db()
        assert insc_a_verifier.besoin_certification is False
        assert response.redirect_chain[-1][0] == reverse(URL)

    def test_individual_without_rattachement_404_after_flag_cleared(
        self, logged_client, famille_user
    ):
        _u, famille, _ratt = famille_user
        orphelin = IndividuFactory()
        insc = InscriptionFactory(
            individu=orphelin, famille=famille, besoin_certification=True
        )
        response = logged_client.post(
            reverse(URL), {"inscription_id": insc.pk, "confirmation_ras": "on"}
        )
        assert response.status_code == 404
        assert Rattachement.objects.filter(individu=orphelin).count() == 0
