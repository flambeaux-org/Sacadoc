"""Tests for portail/views/paiement_retour.py.

This module is imported by portail/urls.py but NOT routed to any URL, so its View is dead
code. It is exercised directly through RequestFactory. It references fields that do not exist
on Paiement (helloasso_checkout_id, STATUT_*), which is reported below as bugs.
"""

from unittest import mock

import pytest
from django.core.exceptions import FieldError
from portail.views import paiement_retour as pr


def test_module_is_not_routed():
    from portail import urls

    assert not any(
        getattr(getattr(p, "callback", None), "view_class", None) is pr.View
        for p in urls.urlpatterns
    )


def _get(rf, user, **params):
    request = rf.get("/", params)
    request.user = user
    view = pr.View()
    view.request = request
    view.args = ()
    view.kwargs = {}
    return view, request


@pytest.mark.django_db
class TestRetourCheckParams:
    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"checkoutIntentId": "1"},
            {"code": "succeeded"},
        ],
    )
    def test_missing_params_redirect_to_error(self, rf, famille_user, params):
        view, request = _get(rf, famille_user[0], **params)
        with mock.patch.object(pr, "messages") as messages:
            response = view.get(request)
        assert response.status_code == 302
        assert response.url == "/paiement/error/"
        messages.error.assert_called_once_with(request, "Retour de paiement invalide.")

    def test_get_context_data(self, rf, famille_user):
        view, _request = _get(rf, famille_user[0])
        assert view.get_context_data()["page_titre"] == "Facturation"


@pytest.mark.django_db
class TestRetourStatuses:
    """Expected behaviour of the three status branches. They currently crash because the
    model has no `helloasso_checkout_id` field."""

    BUG = (
        "BUG: paiement_retour.py:~48 - Paiement has no `helloasso_checkout_id` field (nor "
        "STATUT_SUCCES/STATUT_ECHEC/statut): the lookup raises FieldError. The view is dead code (unrouted)."
    )

    def test_lookup_raises_field_error_today(self, rf, famille_user):
        view, request = _get(
            rf, famille_user[0], checkoutIntentId="1", code="succeeded"
        )
        with mock.patch.object(pr, "messages"), pytest.raises(FieldError):
            view.get(request)

    @pytest.mark.xfail(strict=True, reason=BUG)
    def test_unknown_paiement_redirects_to_error(self, rf, famille_user):
        view, request = _get(
            rf, famille_user[0], checkoutIntentId="nope", code="succeeded"
        )
        with mock.patch.object(pr, "messages") as messages:
            response = view.get(request)
        assert response.url == "/paiement/error/"
        messages.error.assert_called_once_with(request, "Paiement introuvable.")

    @pytest.mark.xfail(strict=True, reason=BUG)
    def test_succeeded_redirects_to_success(self, rf, famille_user):
        view, request = _get(
            rf, famille_user[0], checkoutIntentId="1", code="succeeded"
        )
        with (
            mock.patch.object(pr, "messages"),
            mock.patch.object(pr.Paiement.objects, "get") as get,
        ):
            get.return_value = mock.MagicMock()
            response = view.get(request)
        assert response.url == "/paiement/success/"

    @pytest.mark.xfail(strict=True, reason=BUG)
    @pytest.mark.parametrize("code", ["failed", "canceled"])
    def test_failed_or_canceled_redirects_to_error(self, rf, famille_user, code):
        view, request = _get(rf, famille_user[0], checkoutIntentId="1", code=code)
        with (
            mock.patch.object(pr, "messages"),
            mock.patch.object(pr.Paiement.objects, "get") as get,
        ):
            get.return_value = mock.MagicMock()
            response = view.get(request)
        assert response.url == "/paiement/error/"

    def test_unknown_code_redirects_to_error(self, rf, famille_user):
        view, request = _get(rf, famille_user[0], checkoutIntentId="1", code="weird")
        with (
            mock.patch.object(pr, "messages") as messages,
            mock.patch.object(pr.Paiement.objects, "get") as get,
        ):
            get.return_value = mock.MagicMock()
            response = view.get(request)
        assert response.url == "/paiement/error/"
        messages.error.assert_called_with(request, "Statut de paiement inconnu.")
