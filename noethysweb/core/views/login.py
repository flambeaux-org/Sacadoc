# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging
from importlib import import_module

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.models import update_last_login
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.templatetags.static import static
from django.urls import reverse, reverse_lazy

from core.forms.login import FormLoginUtilisateur
from core.models import Organisateur, Utilisateur
from noethysweb.version import VERSION

logger = logging.getLogger(__name__)


class ClassCommuneLogin:
    def get_context_data(self, **kwargs):
        context = super(ClassCommuneLogin, self).get_context_data(**kwargs)
        # Type de public
        context["public"] = "utilisateur"

        # Version application
        context["version_application"] = VERSION

        # Organisateur
        organisateur = cache.get("organisateur")
        if not organisateur:
            organisateur = Organisateur.objects.filter(pk=1).first()
            cache.set("organisateur", organisateur)
        context["organisateur"] = organisateur

        # Recherche de l'image de fond
        context["url_image_fond"] = static("images/bureau.jpg")

        return context


class LoginViewUtilisateur(ClassCommuneLogin, LoginView):
    form_class = FormLoginUtilisateur
    template_name = "core/login.html"
    redirect_field_name = "accueil"

    def form_valid(self, form):
        update_last_login(None, form.get_user())
        # Enregistre la connexion dans le log
        logger.debug("Connexion de l'utilisateur %s" % form.get_user())
        return super(LoginViewUtilisateur, self).form_valid(form)

    def get_success_url(self):
        next_url = self.get_redirect_url()
        if self.request.user.categorie == "famille":
            return next_url or reverse_lazy("portail_accueil")
        # utilisateur
        return next_url or reverse_lazy("accueil")


def genereate_login_link(request, target_user):
    """Generate a link to login."""
    SessionStore = import_module(settings.SESSION_ENGINE).SessionStore
    s = SessionStore()
    s.set_expiry(300)
    s["source_user"] = request.user.username
    s["target_user"] = target_user.username
    s["ip"] = request.headers.get("X_REAL_IP") or request.META.get("REMOTE_ADDR")
    s.create()
    return reverse("login_as") + f"?session_id={s.session_key}"


def login_as(request):
    """Login as specified user."""
    SessionStore = import_module(settings.SESSION_ENGINE).SessionStore
    s = SessionStore(request.GET["session_id"])
    if "ip" not in s:
        logger.error("Tried to access login_as with invalid session")
        return HttpResponseBadRequest()
    if s["ip"] != (request.headers.get("X_REAL_IP") or request.META.get("REMOTE_ADDR")):
        logger.error(
            "%s tried to login as %s from %s but session id was generated for %s",
            s["source_user"],
            s["target_user"],
            request.headers.get("X_REAL_IP") or request.META.get("REMOTE_ADDR"),
            s["ip"],
        )
        return HttpResponseBadRequest()

    source_user = get_object_or_404(Utilisateur, username=s["source_user"])
    if not source_user.is_superuser:
        return HttpResponseBadRequest()

    target_user = get_object_or_404(Utilisateur, username=s["target_user"])

    logger.info(
        "User %s logging-in as %s on ip %s", s["source_user"], target_user, s["ip"]
    )
    s.flush()
    login(request, target_user, backend="core.backends.EmailModelBackend")
    return redirect("/")
