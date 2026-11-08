# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging
import io
import qrcode
import base64

from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse
from django.views.generic import TemplateView
from django.http import HttpResponseRedirect

from django_otp.plugins.otp_totp.models import TOTPDevice
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken

logger = logging.getLogger(__name__)


def get_base_login_context():
    """Fonction utilitaire pour récupérer le contexte de base pour les templates de login"""
    from core.models import Organisateur
    from django.templatetags.static import static
    organisateur = Organisateur.objects.filter(pk=1).first()
    return {
        'organisateur': organisateur,
        'url_image_fond': static("images/bureau.jpg")
    }


class Setup2FAView(TemplateView):
    """Vue pour configurer la 2FA (afficher le QR code et le secret)"""
    template_name = "core/2fa_setup.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(get_base_login_context())
        
        user = self.request.user
        
        # Vérifier si la 2FA est obligatoire pour cet utilisateur
        context['is_required'] = user.requires_2fa()
        
        # Vérifier si on demande une réinitialisation
        reset_requested = self.request.GET.get('reset') == 'true'
        context['reset_requested'] = reset_requested
        
        # Vérifier si l'utilisateur a déjà un device
        device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
        
        if device and not reset_requested:
            context['already_configured'] = True
            context['device'] = device
        else:
            # Créer un nouveau device non confirmé
            device = TOTPDevice.objects.filter(user=user, confirmed=False).first()
            if not device:
                device = TOTPDevice.objects.create(
                    user=user,
                    name='default',
                    confirmed=False
                )
            
            # Générer le QR code
            otpauth_url = device.config_url
            qr = qrcode.QRCode(version=1, box_size=10, border=5)
            qr.add_data(otpauth_url)
            qr.make(fit=True)
            
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            qr_code_base64 = base64.b64encode(buf.getvalue()).decode()
            
            context['qr_code'] = qr_code_base64
            context['secret_key'] = device.key
            context['already_configured'] = False
        
        return context
    
    def post(self, request, *args, **kwargs):
        """Vérifier le code TOTP et confirmer le device, ou gérer la réinitialisation"""
        
        # Gérer la demande de réinitialisation avec mot de passe
        if 'password' in request.POST:
            password = request.POST.get('password', '').strip()
            
            if not request.user.check_password(password):
                messages.error(request, "Mot de passe incorrect.")
                return HttpResponseRedirect(reverse('2fa_setup') + '?reset=true')
            
            # Mot de passe valide : supprimer tous les anciens devices
            TOTPDevice.objects.filter(user=request.user).delete()
            StaticDevice.objects.filter(user=request.user).delete()
            
            # Supprimer la vérification de session
            if '2fa_verified' in request.session:
                del request.session['2fa_verified']
            
            messages.success(request, "Configuration réinitialisée. Scannez le nouveau QR code.")
            logger.info(f"2FA réinitialisée pour {request.user.username}")
            
            # Rediriger vers la configuration normale
            return redirect('2fa_setup')
        
        # Vérification normale du token
        token = request.POST.get('token', '').strip()
        
        if not token:
            messages.error(request, "Veuillez entrer le code à 6 chiffres.")
            return redirect('2fa_setup')
        
        # Récupérer le device non confirmé
        device = TOTPDevice.objects.filter(user=request.user, confirmed=False).first()
        
        if not device:
            messages.error(request, "Aucun appareil en attente de configuration.")
            return redirect('2fa_setup')
        
        # Vérifier le token
        if device.verify_token(token):
            # Confirmer le device
            device.confirmed = True
            device.save()
            
            # Générer les codes de secours
            static_device = StaticDevice.objects.create(
                user=request.user,
                name='backup_codes',
                confirmed=True
            )
            
            backup_codes = []
            for _ in range(10):
                backup_token = StaticToken.random_token()
                static_token = StaticToken.objects.create(
                    device=static_device,
                    token=backup_token
                )
                backup_codes.append(backup_token)
            
            # Stocker les codes en session pour affichage
            request.session['backup_codes'] = backup_codes
            
            # Marquer la session comme vérifiée pour éviter la redirection vers la page de vérification
            request.session['2fa_verified'] = True
            
            logger.info(f"2FA activée pour l'utilisateur {request.user.username}")
            messages.success(request, "La double authentification a été activée avec succès.")
            
            return redirect('2fa_backup_codes')
        else:
            messages.error(request, "Code incorrect. Vérifiez le code affiché dans votre application.")
            logger.warning(f"Échec d'activation 2FA pour {request.user.username}")
            return redirect('2fa_setup')


class BackupCodesView(TemplateView):
    """Vue pour afficher les codes de secours après activation"""
    template_name = "core/2fa_backup_codes.html"
    
    def dispatch(self, request, *args, **kwargs):
        # Si les codes ne sont pas en session, rediriger vers l'accueil
        if 'backup_codes' not in request.session:
            return redirect('accueil')
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(get_base_login_context())
        
        # Récupérer les codes depuis la session
        backup_codes = self.request.session.get('backup_codes', [])
        context['backup_codes'] = backup_codes
        
        # Supprimer les codes de la session après affichage
        if 'backup_codes' in self.request.session:
            del self.request.session['backup_codes']
        
        return context


class Verify2FAView(TemplateView):
    """Vue pour vérifier le code 2FA après login"""
    template_name = "core/2fa_verify.html"
    
    def dispatch(self, request, *args, **kwargs):
        # Vérifier que l'utilisateur est authentifié
        if not request.user.is_authenticated:
            return redirect('connexion')
        
        # Si déjà vérifié, rediriger vers la page d'origine ou l'accueil
        if request.session.get('2fa_verified', False):
            redirect_url = request.session.pop('2fa_redirect_after', None)
            return redirect(redirect_url or 'accueil')
        
        # Si l'utilisateur n'a pas encore configuré la 2FA, le rediriger vers setup
        if not request.user.has_2fa_enabled():
            return redirect('2fa_setup')
        
        return super().dispatch(request, *args, **kwargs)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(get_base_login_context())
        return context
    
    def post(self, request, *args, **kwargs):
        token = request.POST.get('token', '').strip()
        
        if not token:
            messages.error(request, "Veuillez entrer un code.")
            return redirect('2fa_verify')
        
        user = request.user
        
        # Vérifier avec le device TOTP (code à 6 chiffres)
        totp_device = TOTPDevice.objects.filter(user=user, confirmed=True).first()
        if totp_device and totp_device.verify_token(token):
            request.session['2fa_verified'] = True
            logger.info(f"2FA vérifiée avec succès pour {user.username}")
            messages.success(request, "Authentification réussie.")
            return self._redirect_after_verification(request)
        
        # Vérifier avec un code de secours (normaliser en minuscules pour la comparaison)
        static_device = StaticDevice.objects.filter(user=user, name='backup_codes', confirmed=True).first()
        if static_device:
            token_lower = token.lower()
            for static_token in static_device.token_set.all():
                if static_token.token.lower() == token_lower:
                    # Code valide, le supprimer
                    static_token.delete()
                    request.session['2fa_verified'] = True
                    logger.info(f"2FA vérifiée avec code de secours pour {user.username}")
                    messages.warning(request, f"Code de secours utilisé. Il vous reste {static_device.token_set.count()} codes.")
                    return self._redirect_after_verification(request)
        
        messages.error(request, "Code incorrect. Veuillez réessayer.")
        logger.warning(f"Échec de vérification 2FA pour {user.username}")
        return redirect('2fa_verify')
    
    def _redirect_after_verification(self, request):
        """Utilitaire pour rediriger après vérification 2FA réussie"""
        next_url = request.session.pop('2fa_redirect_after', 'accueil')
        return redirect(next_url)


class Disable2FAView(TemplateView):
    """Vue pour désactiver la 2FA"""
    template_name = "core/2fa_disable.html"
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(get_base_login_context())
        return context
    
    def post(self, request, *args, **kwargs):
        password = request.POST.get('password', '').strip()
        
        if not request.user.check_password(password):
            messages.error(request, "Mot de passe incorrect.")
            return redirect('2fa_disable')
        
        # Supprimer tous les devices
        TOTPDevice.objects.filter(user=request.user).delete()
        StaticDevice.objects.filter(user=request.user).delete()
        
        # Supprimer la vérification de la session
        if '2fa_verified' in request.session:
            del request.session['2fa_verified']
        
        messages.success(request, "La double authentification a été désactivée.")
        logger.info(f"2FA désactivée pour {request.user.username}")
        
        return redirect('accueil')
