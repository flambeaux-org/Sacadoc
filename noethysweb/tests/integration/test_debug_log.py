import pytest
from django.test import RequestFactory
from django.urls import reverse

from outils.views.debug import DebugLog
from tests.unit.factories import UtilisateurFactory


@pytest.mark.django_db
class TestDebugLogView:
    def test_page_accessible_pour_superuser(self, client):
        """Sans menu_code, url_retour valait reverse_lazy('') et le rendu levait NoReverseMatch."""
        user = UtilisateurFactory(is_superuser=True)
        client.force_login(user)
        response = client.get(reverse("debug_log"))
        assert response.status_code == 200
        assert response.context["menu_actif"].code == "debug_log"

    def test_page_refusee_sans_permission(self, client):
        """Sans menu_code, test_func ne vérifiait aucune permission : tout utilisateur lisait le journal."""
        user = UtilisateurFactory(is_superuser=False, is_staff=False)
        client.force_login(user)
        response = client.get(reverse("debug_log"))
        assert response.status_code in (302, 403)


@pytest.mark.django_db
def test_vue_sans_menu_code_renvoie_vers_accueil():
    """Une vue sans menu_code ne doit pas tomber sur un intitulé de menu sans code (url_retour = reverse(''))."""
    request = RequestFactory().get("/")
    request.user = UtilisateurFactory(is_superuser=True)
    view = DebugLog(menu_code="")
    view.setup(request)
    context = view.get_context_data()
    assert context["menu_actif"] is None
    assert str(context["url_retour"]) == reverse("accueil")
