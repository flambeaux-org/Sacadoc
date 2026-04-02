# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging, decimal, sys, datetime, re, copy, json
logger = logging.getLogger(__name__)
from django.urls import reverse
from django.http import JsonResponse, HttpResponse
from django.utils.translation import gettext as _
from django.views.generic import TemplateView
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.shortcuts import render, redirect
from django.db.models import Sum, Q
from django.contrib import messages
from eopayment import Payment
from portail.views.base import CustomView
from core.models import Activite, Facture, Prestation, Ventilation, PortailPeriode, Paiement, Reglement, Payeur, TokenHA, ModeReglement, CompteBancaire, PortailRenseignement, ModeleImpression, Mandat, StripeCompte
from core.utils import utils_portail, utils_fichiers, utils_dates, utils_texte
from django.core.serializers import serialize
from django.views.decorators.http import require_POST
from datetime import date
from django.db.models import Sum, Value
from django.db.models.functions import Coalesce
import decimal
from django.db.models import Sum, F, DecimalField, ExpressionWrapper

from django.utils import timezone

from django.core.cache import cache
import time
import requests
import base64

from django.views.decorators.http import require_POST
from django.http import JsonResponse
from core.models import Prestation, HelloAssoConfig
from outils.utils.utils_helloasso import HelloAssoClient
import stripe


@require_POST
def paiement_tpe(request):
    id_prestation = request.POST.get("id_prestation")
    montant_raw = request.POST.get("montant")

    try:
        # Conversion du montant en float (gestion virgule et point)
        montant = float(str(montant_raw).replace(',', '.'))
        prestation = Prestation.objects.get(pk=id_prestation)
        activite = prestation.activite
        # IMPORTANT : On passe en majuscules et on enlève les espaces
        plateforme = str(activite.pay_org_tpe).upper().strip()
    except (Prestation.DoesNotExist, ValueError, TypeError) as e:
        return JsonResponse({"success": False, "erreur": "Données invalides"}, status=400)

    print(f"=== INIT PAIEMENT : {plateforme} ===")

    # --- CAS HELLOASSO ---
    if plateforme == "HELLOASSO":
        HELLOASSO_DEV = False  # POUR DEV
        if HELLOASSO_DEV:
            base_url = "http://127.0.0.1:8000"
        else:
            base_url = "https://sacadoc.flambeaux.org"
        base_url = "https://sacadoc.flambeaux.org"
        #base_url = "https://wizardly-unmasticatory-ali.ngrok-free.dev"
        config = HelloAssoConfig.objects.filter(activites=activite, actif=True).first()
        if not config:
            return JsonResponse({"success": False, "erreur": "Configuration HelloAsso manquante"}, status=400)

        client = HelloAssoClient(config.client_id, config.client_secret, organisation_slug=config.org_slug,
                                 sandbox=False)
        try:
            url_checkout = client.create_checkout(
                total_amount=montant,
                initial_amount=montant,
                item_name=f"Paiement prestation {prestation.idprestation}",
                back_url=f"{base_url}/attente_paiement/",
                error_url=f"{base_url}/attente_paiement/",
                return_url=f"{base_url}/attente_paiement/",
                contains_donation=False,
                reference=f"PRESTA_{prestation.idprestation}"
            )

            TokenHA.objects.create(
                prestation=prestation,
                checkout_intent_id=url_checkout.get("id"),
                organisation_slug=client.organisation_slug,
                access_token=client.token,
                expires_at=timezone.now() + timezone.timedelta(seconds=1500)
            )

            return JsonResponse({
                "success": True,
                "systeme_paiement": "helloasso",
                "url_helloasso": url_checkout.get("redirectUrl")
            })
        except Exception as e:
            return JsonResponse({"success": False, "erreur": str(e)}, status=500)

    # --- CAS STRIPE (BIEN ALIGNÉ SUR LE IF DU DESSUS) ---
    elif plateforme == "STRIPE":

        stripe_compte = StripeCompte.objects.filter(activites=activite, actif=True).first()
        if not stripe_compte:
            return JsonResponse({"success": False, "erreur": "Configuration Stripe manquante"}, status=400)


        STRIPE_DEV = False  # POUR DEV
        if STRIPE_DEV:
            base_url = "http://127.0.0.1:8000"
        else:
            base_url = "https://sacadoc.flambeaux.org"

        # Note : on double les {{ }} pour CHECKOUT_SESSION_ID pour que Python ne les interprète pas
        # mais on garde des simples { } pour stripe_compte.pk
        success_url = f"{base_url}/attente_paiement/?session_id={{CHECKOUT_SESSION_ID}}&compte_id={stripe_compte.pk}"
        cancel_url = f"{base_url}/facturation/"

        stripe.api_key = stripe_compte.secret_key
        try:
            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'eur',
                        'product_data': {'name': f"Prestation {prestation.idprestation}"},
                        'unit_amount': int(montant * 100),
                    },
                    'quantity': 1,
                }],
                mode='payment',
                metadata={'id_prestation': prestation.idprestation},
                # Dans votre vue paiement_tpe
                success_url=success_url,
                cancel_url=cancel_url,
            )

            # Si c'est de l'AJAX (via votre modale JS)
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    "success": True,
                    "systeme_paiement": "stripe",
                    "url_stripe": session.url
                })
            # Si c'est un clic direct via le formulaire <form>
            return redirect(session.url, code=303)

        except Exception as e:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({"success": False, "erreur": str(e)}, status=500)
            messages.error(request, f"Erreur Stripe : {str(e)}")
            return redirect('portail_facturation')

    # --- CAS PAR DÉFAUT ---
    else:
        return JsonResponse({"success": False, "erreur": f"Plateforme '{plateforme}' non reconnue"}, status=400)

class View(CustomView, TemplateView):
    menu_code = "portail_paiement"
    template_name = "portail/paiement_tpe.html"

    def get_context_data(self, **kwargs):
        context = super(View, self).get_context_data(**kwargs)
        context['page_titre'] = "Paiement"

        return context