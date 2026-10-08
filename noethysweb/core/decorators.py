# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging

from django.urls import reverse_lazy, reverse
from django.http import HttpResponseRedirect, HttpResponseBadRequest, HttpResponseForbidden
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth.decorators import user_passes_test
from reglements.utils import utils_ventilation
from core.models import Prestation, Reglement, Ventilation, Inscription, Famille, Activite

logger = logging.getLogger(__name__)


def Verifie_ventilation(function):
    def _function(request, *args, **kwargs):
        # Laisse la vue gérer la redirection vers la connexion pour les utilisateurs non authentifiés
        if not request.user.is_authenticated:
            return function(request, *args, **kwargs)
        if not request.GET.get("correction_ventilation", None):
            activites_autorisees = Activite.objects.filter(structure__in=request.user.structures.all())
            dict_anomalies = utils_ventilation.GetAnomaliesVentilation(activites_autorisees)
            if dict_anomalies:
                return HttpResponseRedirect(reverse_lazy("corriger_ventilation") + "?next=" + request.path)
        return function(request, *args, **kwargs)
    return _function


def secure_ajax(function):
    """ A associer aux requêtes AJAX """
    def _function(request, *args, **kwargs):
        # Vérifie que c'est une requête AJAX
        if not request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return HttpResponseBadRequest()
        # Vérifie que l'utilisateur est authentifié
        if not request.user.is_authenticated:
            logger.warning("User not authenticated while trying to access %s", request.path)
            return HttpResponseForbidden()
        # Vérifie que c'est un user de type utilisateur
        if request.user.categorie != "utilisateur":
            logger.warning("User not in categorie 'utilisateur' while trying to access %s", request.path)
            return HttpResponseForbidden()
        return function(request, *args, **kwargs)
    return _function


def secure_ajax_portail(function):
    """ A associer aux requêtes AJAX """
    def _function(request, *args, **kwargs):
        # Vérifie que c'est une requête AJAX
        if not request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return HttpResponseBadRequest()
        # Vérifie que l'utilisateur est authentifié
        if not request.user.is_authenticated:
            return HttpResponseForbidden()
        # Vérifie que c'est un user de type utilisateur
        if request.user.categorie != "famille":
            return HttpResponseForbidden()
        return function(request, *args, **kwargs)
    return _function
