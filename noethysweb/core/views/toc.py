# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging
logger = logging.getLogger(__name__)
from django.views.generic import TemplateView
from django.contrib import messages
from django.shortcuts import redirect
from core.views.base import CustomView
from django.conf import settings


class Toc(CustomView, TemplateView):
    template_name = "core/toc.html"

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)

        # Si la rubrique n'existe pas dans le menu de l'utilisateur (aucune permission sur les
        # pages qu'elle contient), elle a été supprimée du menu : inutile d'afficher une page vide.
        if context.get("menu_rubrique") is None:
            logger.debug("Accès refusé à la rubrique '%s' : aucune permission sur son contenu." % self.menu_code)
            messages.add_message(request, messages.ERROR, "Vous n'avez pas l'autorisation d'accéder à cette rubrique")
            return redirect("accueil")

        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        context = super(Toc, self).get_context_data(**kwargs)

        # Recherche le menu actif
        menu_principal = context['menu_principal']
        menu = menu_principal.Find(code=self.menu_code)
        context['menu_rubrique'] = menu

        # Mémorise le nom du menu
        context['page_titre'] = menu.titre if menu else ""
        context['mode_demo'] = settings.MODE_DEMO

        return context
