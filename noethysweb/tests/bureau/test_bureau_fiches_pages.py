"""Smoke + access-control tests for every GET page of the fiche famille and fiche individu.

Routes are discovered from fiche_famille.urls / fiche_individu.urls so a new onglet
is covered automatically. Only routes whose kwargs can be filled from the fixture
family (idfamille / idindividu) are exercised here; routes needing another object
(pk, idfacture...) are covered by the CRUD test modules.
"""

import pytest
from django.urls import reverse
from fiche_famille import urls as famille_urls
from fiche_individu import urls as individu_urls
from tests.bureau.conftest import AJAX
from tests.unit.factories import create_famille_user


def _routes(urlpatterns, kwargs_names):
    routes = []
    for pattern in urlpatterns:
        callback_module = getattr(pattern.callback, "__module__", "")
        if callback_module == "core.decorators":
            continue  # secure_ajax views — tested separately
        if set(pattern.pattern.converters) == set(kwargs_names):
            routes.append(pattern.name)
    return sorted(set(routes))


ROUTES_FAMILLE = _routes(famille_urls.urlpatterns, {"idfamille"})
ROUTES_INDIVIDU = _routes(
    individu_urls.urlpatterns + famille_urls.urlpatterns, {"idfamille", "idindividu"}
)
ROUTES_SANS_ARGS = ["famille_liste", "famille_ajouter", "individu_liste"]

# Pages that stream a file or redirect instead of rendering a template.
NON_HTML = {
    "famille_export_xml",
    "individu_medical_telecharger_pdf",
}

# Known failures, pinned with a strict xfail so they show up as XPASS once fixed.
BUGS = {
    "famille_reglements_ajouter": (
        "BUG: fiche_famille/forms/famille_reglements.py hard-codes Payeur.objects.get(idpayeur=3) "
        "as the default payeur; the page crashes (DoesNotExist) on any database without that row, "
        "and elsewhere offers another family's payeur."
    ),
}


def _avec_bugs(names):
    return [
        pytest.param(n, marks=pytest.mark.xfail(strict=True, reason=BUGS[n])) if n in BUGS else n
        for n in names
    ]


def _url(name, famille, individu=None):
    kwargs = {"idfamille": famille.pk}
    if individu is not None:
        kwargs["idindividu"] = individu.pk
    return reverse(name, kwargs=kwargs)


@pytest.mark.django_db
class TestPagesDirecteur:
    @pytest.mark.parametrize("name", ROUTES_SANS_ARGS)
    def test_pages_sans_argument(self, directeur_client, famille_bureau, name):
        assert directeur_client.get(reverse(name)).status_code == 200

    @pytest.mark.parametrize("name", _avec_bugs(ROUTES_FAMILLE))
    def test_pages_fiche_famille(self, directeur_client, famille_bureau, name):
        famille, _titulaire, _enfant = famille_bureau
        response = directeur_client.get(_url(name, famille))
        assert response.status_code == 200, name
        if name not in NON_HTML and "famille" in response.context:
            assert response.context["famille"] == famille

    @pytest.mark.parametrize("name", ROUTES_INDIVIDU)
    def test_pages_fiche_individu(self, directeur_client, famille_bureau, name):
        famille, _titulaire, enfant = famille_bureau
        response = directeur_client.get(_url(name, famille, enfant))
        assert response.status_code == 200, name
        if name not in NON_HTML and "individu" in response.context:
            assert response.context["individu"] == enfant

    def test_resume_famille_affiche_les_membres(self, directeur_client, famille_bureau):
        famille, titulaire, enfant = famille_bureau
        response = directeur_client.get(reverse("famille_resume", args=[famille.pk]))
        rattachements = {r.individu_id for r in response.context["rattachements"]}
        assert rattachements == {titulaire.pk, enfant.pk}
        assert enfant.pk in response.context["inscriptions_actuelles"]

    def test_liste_familles_limitee_aux_structures(self, directeur_client, famille_bureau):
        """famille_liste only returns families inscribed on the director's activities."""
        from fiche_famille.views.famille import Liste
        from django.test import RequestFactory

        famille, _t, _e = famille_bureau
        _user, autre_famille = create_famille_user(username="hors_structure")

        request = RequestFactory().get(reverse("famille_liste"))
        request.user = directeur_client.get(reverse("famille_liste")).wsgi_request.user
        view = Liste()
        view.setup(request)
        ids = set(view.get_queryset().values_list("pk", flat=True))
        assert famille.pk in ids
        assert autre_famille.pk not in ids


@pytest.mark.django_db
class TestAccesRefuse:
    """The bureau must be closed to anonymous visitors and to portail (famille) accounts."""

    PAGES = ["famille_resume", "famille_divers", "famille_notes_ajouter"]
    PAGES_INDIVIDU = ["individu_resume", "individu_identite", "individu_medical_liste"]

    @pytest.mark.parametrize("name", PAGES)
    def test_anonyme_redirige(self, client, famille_bureau, name):
        famille, _t, _e = famille_bureau
        response = client.get(_url(name, famille))
        assert response.status_code == 302
        assert "connexion" in response["Location"]

    @pytest.mark.parametrize("name", PAGES_INDIVIDU)
    def test_anonyme_redirige_individu(self, client, famille_bureau, name):
        famille, _t, enfant = famille_bureau
        response = client.get(_url(name, famille, enfant))
        assert response.status_code == 302
        assert "connexion" in response["Location"]

    @pytest.mark.parametrize("name", PAGES)
    def test_compte_famille_refuse(self, client, famille_bureau, name):
        famille, _t, _e = famille_bureau
        client.force_login(famille.utilisateur)
        assert client.get(_url(name, famille)).status_code == 403

    @pytest.mark.parametrize("name", PAGES_INDIVIDU)
    def test_compte_famille_refuse_individu(self, client, famille_bureau, name):
        famille, _t, enfant = famille_bureau
        client.force_login(famille.utilisateur)
        assert client.get(_url(name, famille, enfant)).status_code == 403

    def test_compte_famille_refuse_sur_suppression(self, client, famille_bureau):
        from core.models import Famille

        famille, _t, _e = famille_bureau
        client.force_login(famille.utilisateur)
        response = client.post(reverse("famille_supprimer", args=[famille.pk]))
        assert response.status_code == 403
        assert Famille.objects.filter(pk=famille.pk).exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: CustomView.test_func only checks has_perm() when menu_code is set; CRUD pages "
        "(famille.Liste, individu.Liste...) leave it empty and the url_liste fallback sits in "
        "an unreachable branch, so any staff account can open them without the permission."
    ))
    def test_staff_sans_permission_refuse_sur_liste(self, client, organisateur):
        from tests.unit.factories import UtilisateurFactory

        user = UtilisateurFactory(username="sans_droits", is_superuser=False)
        client.force_login(user)
        assert client.get(reverse("famille_liste")).status_code == 403
        assert client.get(reverse("individu_liste")).status_code == 403


@pytest.mark.django_db
class TestSecureAjax:
    def test_requete_non_ajax_rejetee(self, directeur_client, famille_bureau):
        _f, titulaire, _e = famille_bureau
        response = directeur_client.post(
            reverse("ajax_definir_titulaire"), {"idrattachement": titulaire.pk}
        )
        assert response.status_code == 400

    def test_anonyme_rejete(self, client, famille_bureau):
        response = client.post(reverse("ajax_definir_titulaire"), {}, **AJAX)
        assert response.status_code == 403

    def test_compte_famille_rejete(self, client, famille_bureau):
        famille, _t, _e = famille_bureau
        client.force_login(famille.utilisateur)
        response = client.post(reverse("ajax_definir_titulaire"), {}, **AJAX)
        assert response.status_code == 403
