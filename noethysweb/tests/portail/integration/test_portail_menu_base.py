"""Branch coverage for portail/views/menu.py and portail/views/base.py (CustomView)."""

import datetime

import pytest
from core.models import (
    Famille,
    Historique,
    Parametre,
    PortailMessage,
)
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import RequestFactory
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView
from portail.views.base import CustomView
from portail.views.menu import GetMenuPrincipal, Menu
from tests.unit.factories import (
    PortailMessageFactory,
    StructureFactory,
)

ALL_OFF = {
    k: False
    for k in (
        "renseignements_afficher_page",
        "cotisations_afficher_page",
        "activites_afficher_page",
        "reservations_afficher_page",
        "facturation_afficher_page",
        "contact_afficher_page",
        "mentions_afficher_page",
    )
}


def codes(menu):
    return [child.code for child in menu.GetChildren()]


# --------------------------------------------------------------------------- menu


class TestGetMenuPrincipal:
    def test_no_user_lists_every_entry(self):
        menu = GetMenuPrincipal(parametres_portail=ALL_OFF, user=None)
        assert codes(menu) == [
            "portail_accueil",
            "portail_renseignements",
            "portail_cotisations",
            "portail_activites",
            "portail_reservations",
            "portail_facturation",
            "portail_contact",
            "portail_mentions",
        ]

    @pytest.mark.django_db
    def test_famille_user_all_pages_disabled_only_accueil(self, famille_user):
        user, _f, _r = famille_user
        assert codes(GetMenuPrincipal(parametres_portail=ALL_OFF, user=user)) == [
            "portail_accueil"
        ]

    @pytest.mark.django_db
    def test_famille_user_pages_follow_parameters(self, famille_user):
        user, _f, _r = famille_user
        params = dict(
            ALL_OFF, cotisations_afficher_page=True, contact_afficher_page=True
        )
        assert codes(GetMenuPrincipal(parametres_portail=params, user=user)) == [
            "portail_accueil",
            "portail_cotisations",
            "portail_contact",
        ]

    @pytest.mark.django_db
    def test_missing_parameters_default_to_hidden(self, famille_user):
        user, _f, _r = famille_user
        assert codes(GetMenuPrincipal(parametres_portail={}, user=user)) == [
            "portail_accueil"
        ]

    @pytest.mark.django_db
    def test_superuser_sees_everything_even_when_disabled(self, staff_user):
        assert (
            len(codes(GetMenuPrincipal(parametres_portail=ALL_OFF, user=staff_user)))
            == 8
        )

    def test_user_with_core_permission_sees_entry(self):
        class User:
            def has_perm(self, perm):
                return perm == "core.portail_cotisations"

        assert codes(GetMenuPrincipal(parametres_portail=ALL_OFF, user=User())) == [
            "portail_accueil",
            "portail_cotisations",
        ]


class TestMenuClass:
    def make_tree(self):
        root = Menu(titre="root")
        a = root.Add(code="portail_accueil", titre="A")
        b = root.Add(code="portail_contact", titre="B")
        a1 = a.Add(code="portail_mentions", titre="A1")
        return root, a, b, a1

    def test_repr(self):
        assert repr(Menu(titre="Hello")) == "<Menu 'Hello'>"

    def test_add_wires_parent_and_user(self):
        root, a, _b, a1 = self.make_tree()
        assert a.GetParent() is root
        assert a1.GetParent() is a

    def test_add_without_code_always_added_even_with_user(self):
        root = Menu(user=object())
        child = root.Add(code="", titre="sep")
        assert child in root.GetChildren()

    def test_add_with_code_endswith_toc_always_added(self):
        root = Menu(user=object())
        child = root.Add(code="whatever_toc", titre="toc")
        assert child in root.GetChildren()

    def test_add_hidden_without_permission(self):
        class User:
            def has_perm(self, perm):
                return False

        root = Menu(user=User())
        root.Add(code="portail_x", titre="x")
        assert root.GetChildren() == []
        assert not root.HasChildren()

    def test_has_children(self):
        root, a, b, _a1 = self.make_tree()
        assert root.HasChildren() and a.HasChildren() and not b.HasChildren()

    def test_get_url_without_args(self):
        assert str(Menu(code="portail_accueil").GetUrl()) == reverse("portail_accueil")

    def test_get_url_with_args(self):
        assert str(
            Menu(code="portail_contact_conversation", args=[5]).GetUrl()
        ) == reverse("portail_contact_conversation", args=[5])

    def test_get_children_parts_splits_in_two_columns(self):
        root = Menu()
        items = [root.Add(code="", titre=str(i)) for i in range(5)]
        left, right = list(root.GetChildrenParts())
        assert left == items[0::2] and right == items[1::2]

    def test_get_brothers_excludes_self(self):
        root, a, b, _a1 = self.make_tree()
        assert a.GetBrothers() == [b]
        # original list untouched
        assert len(root.GetChildren()) == 2

    def test_find_top_level_nested_and_missing(self):
        root, a, _b, a1 = self.make_tree()
        assert root.Find(code="portail_accueil") is a
        assert root.Find(code="portail_mentions") is a1
        assert root.Find(code="nope") is None

    def test_breadcrumb_top_level_and_nested(self):
        _root, a, _b, a1 = self.make_tree()
        assert a.GetBreadcrumb() == [a]
        assert a1.GetBreadcrumb() == [a, a1]


# --------------------------------------------------------------------------- base


class DummyView(CustomView, TemplateView):
    template_name = "portail/profil.html"
    menu_code = "portail_accueil"


class UrlListView(CustomView, TemplateView):
    template_name = "portail/profil.html"
    menu_code = ""
    url_liste = "portail_contact"


class UnknownMenuView(CustomView, TemplateView):
    template_name = "portail/profil.html"
    menu_code = "does_not_exist"


def build_context(view_cls, user, **kwargs):
    request = RequestFactory().get("/")
    request.user = user
    view = view_cls()
    view.setup(request, **kwargs)
    return view, view.get_context_data()


@pytest.mark.django_db
class TestCustomViewDispatchAndAccess:
    def test_anonymous_redirected_to_portail_connexion(self, client, organisateur):
        response = client.get(reverse("portail_profil"))
        assert response.status_code == 302
        assert response.url == reverse("portail_connexion")

    def test_staff_user_gets_403(self, client, staff_user, organisateur):
        client.force_login(staff_user)
        assert client.get(reverse("portail_profil")).status_code == 403

    def test_famille_user_gets_200(self, logged_client):
        assert logged_client.get(reverse("portail_profil")).status_code == 200

    def test_dispatch_anonymous_branch_direct(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        response = DummyView.as_view()(request)
        assert response.status_code == 302 and response.url == reverse(
            "portail_connexion"
        )

    def test_test_func_true_only_for_famille(self, famille_user, staff_user):
        user, _f, _r = famille_user
        request = RequestFactory().get("/")
        view = DummyView()
        view.setup(request)
        request.user = user
        assert view.test_func() is True
        request.user = staff_user
        assert view.test_func() is False


@pytest.mark.django_db
class TestCustomViewContext:
    def test_basic_context(self, famille_user, organisateur):
        user, _f, _r = famille_user
        _view, ctx = build_context(DummyView, user)
        assert ctx["organisateur"] == organisateur
        assert ctx["version_application"]
        assert "parametres_portail" in ctx
        assert ctx["menu_actif"].code == "portail_accueil"
        assert ctx["breadcrumb"][-1].code == "portail_accueil"

    def test_menu_code_taken_from_url_liste_when_empty(
        self, famille_user, organisateur
    ):
        user, _f, _r = famille_user
        view, ctx = build_context(UrlListView, user)
        assert view.menu_code == "portail_contact"
        assert ctx["menu_actif"].code == "portail_contact"

    def test_unknown_menu_code_has_no_breadcrumb(self, famille_user, organisateur):
        user, _f, _r = famille_user
        _view, ctx = build_context(UnknownMenuView, user)
        assert ctx["menu_actif"] is None
        assert "breadcrumb" not in ctx

    def test_organisateur_cached_between_calls(self, famille_user, organisateur):
        user, _f, _r = famille_user
        build_context(DummyView, user)
        assert cache.get("organisateur") == organisateur
        organisateur.nom = "Changed"
        organisateur.save()
        _view, ctx = build_context(DummyView, user)
        assert ctx["organisateur"].nom != "Changed"  # served from cache

    def test_parametres_cached_between_calls(
        self, famille_user, organisateur, set_parametre_portail
    ):
        user, _f, _r = famille_user
        set_parametre_portail("mentions_afficher_page", False)
        _v, ctx1 = build_context(DummyView, user)
        assert ctx1["parametres_portail"]["mentions_afficher_page"] is False
        assert cache.get("parametres_portail") is not None

    def test_options_interface_defaults_then_cached(self, famille_user, organisateur):
        user, _f, _r = famille_user
        _v, ctx1 = build_context(DummyView, user)
        assert ctx1["options_interface"]["text-sm"] is True
        assert (
            Parametre.objects.filter(
                categorie="options_interface", utilisateur=user
            ).count()
            == 4
        )
        assert (
            cache.get("options_interface_user%d" % user.pk) == ctx1["options_interface"]
        )
        _v, ctx2 = build_context(DummyView, user)
        assert ctx2["options_interface"] == ctx1["options_interface"]

    def test_options_interface_read_from_cache_when_present(
        self, famille_user, organisateur
    ):
        user, _f, _r = famille_user
        cache.set("options_interface_user%d" % user.pk, {"dark-mode": True})
        _v, ctx = build_context(DummyView, user)
        assert ctx["options_interface"] == {"dark-mode": True}


@pytest.mark.django_db
class TestCustomViewUnreadMessages:
    def _old(self, message, days):
        PortailMessage.objects.filter(pk=message.pk).update(
            date_creation=timezone.now() - datetime.timedelta(days=days)
        )

    def test_no_messages(self, famille_user, organisateur):
        user, _f, _r = famille_user
        _v, ctx = build_context(DummyView, user)
        assert list(ctx["liste_messages_non_lus"]) == []
        assert list(ctx["liste_messages_lus"]) == []

    def test_latest_unread_per_structure_listed_as_non_lus(
        self, famille_user, organisateur, staff_user
    ):
        user, famille, _r = famille_user
        s1 = StructureFactory()
        PortailMessageFactory(famille=famille, structure=s1, utilisateur=staff_user)
        last = PortailMessageFactory(
            famille=famille, structure=s1, utilisateur=staff_user
        )
        _v, ctx = build_context(DummyView, user)
        assert list(ctx["liste_messages_non_lus"]) == [last]
        assert list(ctx["liste_messages_lus"]) == []

    def test_structure_with_unread_not_repeated_in_lus(
        self, famille_user, organisateur, staff_user
    ):
        user, famille, _r = famille_user
        s1 = StructureFactory()
        own = PortailMessageFactory(famille=famille, structure=s1)  # sent by the family
        unread = PortailMessageFactory(
            famille=famille, structure=s1, utilisateur=staff_user
        )
        _v, ctx = build_context(DummyView, user)
        assert list(ctx["liste_messages_non_lus"]) == [unread]
        assert own not in list(ctx["liste_messages_lus"])

    def test_read_conversation_listed_in_lus_with_latest_message(
        self, famille_user, organisateur, staff_user
    ):
        user, famille, _r = famille_user
        s2 = StructureFactory()
        PortailMessageFactory(
            famille=famille,
            structure=s2,
            utilisateur=staff_user,
            date_lecture=datetime.datetime.now(),
        )
        latest = PortailMessageFactory(famille=famille, structure=s2)
        _v, ctx = build_context(DummyView, user)
        assert list(ctx["liste_messages_non_lus"]) == []
        assert list(ctx["liste_messages_lus"]) == [latest]

    def test_conversation_older_than_three_months_ignored(
        self, famille_user, organisateur
    ):
        user, famille, _r = famille_user
        old = PortailMessageFactory(famille=famille, structure=StructureFactory())
        self._old(old, 100)
        _v, ctx = build_context(DummyView, user)
        assert list(ctx["liste_messages_lus"]) == []

    def test_other_family_messages_ignored(
        self, famille_user, other_famille, organisateur, staff_user
    ):
        user, _f, _r = famille_user
        _ub, famille_b, _rb = other_famille
        PortailMessageFactory(
            famille=famille_b, structure=StructureFactory(), utilisateur=staff_user
        )
        _v, ctx = build_context(DummyView, user)
        assert list(ctx["liste_messages_non_lus"]) == []
        assert list(ctx["liste_messages_lus"]) == []


class FormeStub:
    def __init__(self, changed_data, instance, initial=None):
        self.changed_data = changed_data
        self.instance = instance
        self.initial = initial or {}


def make_view(user, **attrs):
    request = RequestFactory().get("/")
    request.user = user
    view = DummyView()
    view.setup(request)
    for k, v in attrs.items():
        setattr(view, k, v)
    return view


@pytest.mark.django_db
class TestFormateHistorique:
    def view(self, famille_user):
        return make_view(famille_user[0])

    def test_model_instance_to_str(self, famille_user):
        _u, famille, _r = famille_user
        assert self.view(famille_user).Formate_historique(famille) == str(famille)

    def test_model_class_to_str(self, famille_user):
        assert self.view(famille_user).Formate_historique(Famille) == str(Famille)

    def test_queryset_joined(self, famille_user):
        _u, famille, _r = famille_user
        result = self.view(famille_user).Formate_historique(
            Famille.objects.filter(pk=famille.pk)
        )
        assert result == str(famille)

    def test_list_of_instances_joined(self, famille_user):
        _u, _famille, ratt = famille_user
        result = self.view(famille_user).Formate_historique(
            [ratt[0].individu, ratt[1].individu]
        )
        assert result == f"{ratt[0].individu}, {ratt[1].individu}"

    def test_list_of_plain_values_joined(self, famille_user):
        assert self.view(famille_user).Formate_historique(["a", "b"]) == "a, b"

    def test_scalar_and_none_unchanged(self, famille_user):
        view = self.view(famille_user)
        assert view.Formate_historique("txt") == "txt"
        assert view.Formate_historique(None) is None
        assert view.Formate_historique(12) == 12


@pytest.mark.django_db
class TestSaveHistorique:
    def last(self):
        return Historique.objects.order_by("-idaction").first()

    def test_explicit_titre_and_detail_for_famille_instance(self, famille_user):
        user, famille, _r = famille_user
        make_view(user).save_historique(instance=famille, titre="T", detail="D")
        h = self.last()
        assert (
            h.titre,
            h.detail,
            h.famille_id,
            h.classe,
            h.idobjet,
            h.portail,
            h.utilisateur,
        ) == (
            "T",
            "D",
            famille.pk,
            "Famille",
            famille.pk,
            True,
            user,
        )
        assert h.individu_id is None

    def test_individu_instance_sets_individu(self, famille_user):
        user, _f, ratt = famille_user
        individu = ratt[1].individu
        make_view(user).save_historique(instance=individu, titre="T", detail="D")
        h = self.last()
        assert (
            h.individu_id == individu.pk
            and h.famille_id is None
            and h.classe == "Individu"
        )

    def test_rattachement_instance_uses_foreign_keys(self, famille_user):
        user, famille, ratt = famille_user
        make_view(user).save_historique(instance=ratt[0], titre="T", detail="D")
        h = self.last()
        assert h.famille_id == famille.pk and h.individu_id == ratt[0].individu_id

    def test_titre_from_get_titre_historique(self, famille_user):
        user, famille, _r = famille_user
        view = make_view(user)
        view.Get_titre_historique = lambda instance: f"Titre {instance.pk}"
        view.save_historique(instance=famille, detail="D")
        assert self.last().titre == "Titre %d" % famille.pk

    def test_titre_from_titre_historique_attribute(self, famille_user):
        user, famille, _r = famille_user
        make_view(user, titre_historique="Attr").save_historique(
            instance=famille, detail="D"
        )
        assert self.last().titre == "Attr"

    def test_titre_from_verbe_action_and_objet(self, famille_user):
        user, famille, _r = famille_user
        make_view(
            user, verbe_action="Modifier", objet_singulier="une famille"
        ).save_historique(instance=famille, detail="D")
        assert self.last().titre == "Modifier une famille"

    def test_detail_from_get_detail_historique(self, famille_user):
        user, famille, _r = famille_user
        view = make_view(user)
        view.Get_detail_historique = lambda instance: "detail-callback"
        view.save_historique(instance=famille, titre="T")
        assert self.last().detail == "detail-callback"

    def test_detail_from_detail_historique_format(self, famille_user):
        user, famille, _r = famille_user
        make_view(user, detail_historique="Famille {0.pk}").save_historique(
            instance=famille, titre="T"
        )
        assert self.last().detail == "Famille %d" % famille.pk

    def test_detail_without_form_is_str_of_instance(self, famille_user):
        user, famille, _r = famille_user
        make_view(user).save_historique(instance=famille, titre="T")
        h = self.last()
        assert h.detail == str(famille)
        assert h.old == ""

    def test_detail_from_form_changed_data_with_old_values(self, famille_user):
        user, famille, _r = famille_user
        famille.nom = "Nouveau"
        form = FormeStub(["nom"], famille, initial={"nom": "Ancien"})
        make_view(user).save_historique(instance=famille, titre="T", form=form)
        h = self.last()
        assert h.detail == "{}=Nouveau".format(
            Famille._meta.get_field("nom").verbose_name
        )
        assert h.old == "{}=Ancien".format(Famille._meta.get_field("nom").verbose_name)

    def test_form_changed_data_unknown_field_is_skipped(self, famille_user):
        user, famille, _r = famille_user
        form = FormeStub(["champ_inexistant"], famille)
        make_view(user).save_historique(instance=famille, titre="T", form=form)
        assert self.last().detail == ""
