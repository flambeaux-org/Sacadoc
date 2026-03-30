# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import json, time
from django.http import JsonResponse
from django.views.generic import TemplateView
from core.views.base import CustomView
from core.utils import utils_dates
from comptabilite.forms.correction_compte import Formulaire
import io
from datetime import datetime
from django.template.loader import render_to_string
from django.conf import settings
from django.core.files.storage import default_storage
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from core.models import ComptaOperation
from django.utils.html import strip_tags
from django.core.files.base import ContentFile
from PIL import Image  # Pour traiter l'image (si nécessaire)


class View(CustomView, TemplateView):
    template_name = "comptabilite/correction_compte.html"

    def get_context_data(self, **kwargs):
        context = super(View, self).get_context_data(**kwargs)
        context['page_titre'] = "Réimputation comptable"
        if "form" not in kwargs:
            context['form'] = Formulaire(request=self.request)
        return context

    def post(self, request, *args, **kwargs):
        form = Formulaire(request.POST, request=request)
        if form.is_valid():
            operation = form.cleaned_data['operation']
            nouveau_compte = form.cleaned_data['nouveau_compte']

            ancien_compte = operation.compte.nom
            operation.compte = nouveau_compte
            operation.save()

            # Message de succès pour l'utilisateur
            from django.contrib import messages
            messages.success(request,
                             f"L'opération '{operation.libelle}' a été déplacée de ({ancien_compte}) vers ({nouveau_compte.nom}).")

            # On recharge la page avec un formulaire vide
            return self.render_to_response(self.get_context_data(form=Formulaire(request=request)))

        return self.render_to_response(self.get_context_data(form=form))