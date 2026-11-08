# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging
from django.http import HttpResponseRedirect
from django.urls import reverse
from portail.utils import utils_secquest

logger = logging.getLogger(__name__)


class CustomMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Oblige la famille à changer son mot de passe
        url_change_password = reverse("password_change")
        if request.user.is_authenticated and request.user.categorie == "famille" and request.user.force_reset_password and request.path != url_change_password:
            utils_secquest.Generation_secquest(famille=request.user.famille)
            return HttpResponseRedirect(url_change_password)

        return response


class TwoFactorAuthMiddleware:
    """Middleware pour forcer la vérification 2FA pour les admins et directeurs."""
    
    # URLs qui ne nécessitent pas de vérification 2FA
    EXEMPT_URLS = [
        '/connexion',
        '/deconnexion',
        '/utilisateur/connexion',
        '/utilisateur/deconnexion',
        '/static/',
        '/media/',
    ]
    
    # Patterns d'URLs à exempter (vérification avec 'in' au lieu de 'startswith')
    EXEMPT_PATTERNS = [
        '/core/2fa/',
    ]
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Vérifier si l'URL est exemptée (début du path)
        if any(request.path.startswith(url) for url in self.EXEMPT_URLS):
            return self.get_response(request)
        
        # Vérifier si l'URL contient un pattern exempté
        if any(pattern in request.path for pattern in self.EXEMPT_PATTERNS):
            return self.get_response(request)
        
        # Vérifier si l'utilisateur est authentifié
        if not request.user.is_authenticated:
            return self.get_response(request)
        
        # Vérifier si l'utilisateur nécessite la 2FA
        if not request.user.requires_2fa():
            return self.get_response(request)
        
        # Vérifier si l'utilisateur a configuré la 2FA
        if not request.user.has_2fa_enabled():
            # logger.warning(f"L'utilisateur {request.user.username} doit configurer la 2FA")
            # Stocker l'URL de destination
            if request.path != reverse('2fa_setup'):
                request.session['2fa_redirect_after'] = request.path
                return HttpResponseRedirect(reverse('2fa_setup'))
        else:
            # Vérifier si la 2FA a été validée dans cette session
            if not request.session.get('2fa_verified', False):
                # logger.info(f"Redirection vers la vérification 2FA pour {request.user.username}")
                if request.path != reverse('2fa_verify'):
                    request.session['2fa_redirect_after'] = request.path
                    return HttpResponseRedirect(reverse('2fa_verify'))
        
        response = self.get_response(request)
        return response


class UserInHeaderMiddleware:
    """Ajout du header X-User contenant l'utilisateur connecté pour le rendre disponible dans les logs."""
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated:
            response["X-User"] = request.user.username
        return response
