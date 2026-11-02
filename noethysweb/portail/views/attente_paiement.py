# -*- coding: utf-8 -*-
import logging
import decimal
import stripe
import requests
from django.shortcuts import redirect
from django.contrib import messages
from django.utils import timezone
from django.views.generic import View as DjangoBaseView
from django.core import mail as djangomail
from django.core.mail import EmailMultiAlternatives
from core.models import (
    TokenHA, Prestation, HelloAssoConfig, CompteBancaire, Reglement, Ventilation, ComptaOperation,
    ComptaVentilation, StripeCompte, Paiement, Organisateur, AdresseMail
)
from core.utils import utils_portail
from noethysweb import settings

logger = logging.getLogger(__name__)


def envoyer_email_paiement_stripe(prestation, montant, session_id):
    idadresse_exp = utils_portail.Get_parametre(code="connexion_adresse_exp")
    adresse_exp = AdresseMail.objects.filter(pk=idadresse_exp, actif=True).first()
    if not adresse_exp:
        logger.warning("Email paiement Stripe : pas d'adresse d'expédition paramétrée.")
        return

    organisateur = Organisateur.objects.first()
    if not organisateur or not organisateur.mail:
        logger.warning("Email paiement Stripe : pas d'email organisateur configuré.")
        return

    backend = "django.core.mail.backends.console.EmailBackend"
    backend_kwargs = {}

    if not settings.DEBUG:
        if adresse_exp.moteur == "smtp":
            backend = "django.core.mail.backends.smtp.EmailBackend"
            backend_kwargs = {
                "host": adresse_exp.hote,
                "port": adresse_exp.port,
                "username": adresse_exp.utilisateur,
                "password": adresse_exp.motdepasse,
                "use_tls": adresse_exp.use_tls,
            }
        elif adresse_exp.moteur == "mailjet":
            backend = "anymail.backends.mailjet.EmailBackend"
            backend_kwargs = {
                "api_key": adresse_exp.Get_parametre("api_key"),
                "secret_key": adresse_exp.Get_parametre("api_secret"),
            }
        elif adresse_exp.moteur == "brevo":
            backend = "anymail.backends.sendinblue.EmailBackend"
            backend_kwargs = {"api_key": adresse_exp.Get_parametre("api_key")}

    connection = djangomail.get_connection(backend=backend, fail_silently=False, **backend_kwargs)
    try:
        connection.open()
    except Exception as err:
        logger.error(f"Email paiement Stripe : connexion impossible au serveur de messagerie : {err}")
        return

    body = (
        f"Un paiement Stripe a été reçu.\n\n"
        f"Famille : {prestation.famille.nom}\n"
        f"Prestation : {prestation.label}\n"
        f"Montant : {montant} €\n"
        f"Session Stripe : {session_id}\n"
        f"Date : {timezone.now().strftime('%d/%m/%Y %H:%M')}\n"
    )

    message = EmailMultiAlternatives(
        subject="Paiement Stripe reçu",
        body=body,
        from_email=adresse_exp.adresse,
        to=[organisateur.mail],
        connection=connection,
    )

    try:
        message.send()
    except Exception as err:
        logger.error(f"Email paiement Stripe : erreur d'envoi : {err}")
    finally:
        connection.close()


class View(DjangoBaseView):
    menu_code = "portail_attente_paiement"
    template_name = "portail/attente_paiement.html"
    compatible_demo = False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_titre'] = "Attente du paiement"
        context['box_titre'] = "Paiement en cours"
        context['checkout_intent_id'] = self.request.GET.get("checkoutIntentId")
        context['order_id'] = self.request.GET.get("orderId")
        return context

    def get(self, request, *args, **kwargs):
        checkout_intent_id = request.GET.get("checkoutIntentId")
        stripe_session_id = request.GET.get("session_id")
        stripe_compte_id = request.GET.get("compte_id")
        orderId = request.GET.get("orderId")

        if stripe_session_id and stripe_compte_id:
            if "{" in str(stripe_compte_id):
                messages.error(request, "Erreur de configuration du lien de paiement.")
                return redirect('portail_facturation')
            return self.handle_stripe_logic(request, stripe_session_id, stripe_compte_id)

        if checkout_intent_id:
            return self.handle_helloasso_logic(request, checkout_intent_id, orderId)

        messages.error(request, "Aucune information de paiement reçue.")
        return redirect('portail_facturation')

    def handle_helloasso_logic(self, request, checkout_intent_id, orderId):
        token_entry = TokenHA.objects.filter(
            checkout_intent_id=checkout_intent_id,
            expires_at__gt=timezone.now()
        ).order_by('-expires_at').first()

        if not token_entry:
            print("Token non trouvé ou expiré")
            messages.error(request, "Token non trouvé ou expiré")
            return redirect('portail_facturation')

        prestation = token_entry.prestation
        token = token_entry.access_token
        org_slug = token_entry.organisation_slug

        HELLOASSO_FORCE_SANDBOX = False #DEV
        api_base = "https://api.helloasso-sandbox.com/v5/organizations" if HELLOASSO_FORCE_SANDBOX else "https://api.helloasso.com/v5/organizations"

        url = f"{api_base}/{org_slug}/checkout-intents/{checkout_intent_id}"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            resp = requests.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            print(data)
            order = data.get("order")
            if not order:
                messages.info(request, "Paiement en attente...")
                return redirect('portail_facturation')
            print('ici')
            payments = order.get("payments", [])
            if payments:
                # HelloAsso met l'état ici : "Authorized" (vu dans ton debug)
                payment_state = payments[0].get("state")
                print(f"DEBUG: État du paiement trouvé = {payment_state}")
                # 3. On vérifie l'état (insensible à la casse)
                if str(payment_state).lower() in ["authorized", "success", "succeeded"]:
                    montant = decimal.Decimal(order.get("amount", {}).get("total")) / 100
                    tag = f"HELLOASSO_{order.get('id')}"

                    # --- Suite de ton code (création Noethys) ---
                    if not Reglement.objects.filter(observations__icontains=tag).exists():
                        # Ton code de création ici...
                        print("DEBUG: Lancement de la création Noethys !")

                if not Reglement.objects.filter(observations__icontains=tag).exists():
                    # Récupération du compte spécifique à l'organisation HelloAsso
                    config = HelloAssoConfig.objects.get(org_slug=org_slug)
                    activite = config.activites.first()
                    compte = CompteBancaire.objects.filter(
                        structure=activite.structure).first() or CompteBancaire.objects.filter(pk=1).first()
                    systeme = "HELLOASSO"
                    self.valider_paiement_final(prestation, montant, tag, orderId or order.get('id'), compte, systeme)
                    messages.success(request, "Paiement HelloAsso validé !")
                return redirect('portail_facturation')

        except Exception as e:
            logger.error(f"Erreur HelloAsso : {e}")
            print((f"Erreur HelloAsso : {e}"))
            messages.error(request, f"Erreur API HelloAsso: {e}")

        return redirect('portail_facturation')

    def handle_stripe_logic(self, request, session_id, compte_id):
        try:
            stripe_compte = StripeCompte.objects.get(pk=int(compte_id), actif=True)
            stripe.api_key = stripe_compte.secret_key
            session = stripe.checkout.Session.retrieve(session_id)

            if session.payment_status == "paid":
                id_prestation = session.metadata.get('id_prestation')
                prestation = Prestation.objects.get(pk=int(id_prestation))
                montant = decimal.Decimal(session.amount_total) / 100
                tag = f"STRIPE_SESSION_{session.id}"

                if not Reglement.objects.filter(observations__icontains=tag).exists():
                    compte = CompteBancaire.objects.filter(
                        structure=prestation.activite.structure).first() or CompteBancaire.objects.first()
                    systeme = "STRIPE"
                    self.valider_paiement_final(prestation, montant, tag, session.id, compte, systeme)
                    messages.success(request, "Paiement Stripe validé !")
                    envoyer_email_paiement_stripe(prestation, montant, session.id)
                return redirect('portail_facturation')
        except Exception as e:
            logger.error(f"Erreur Stripe : {e}")
            messages.error(request, "Erreur lors de la validation Stripe.")
        return redirect('portail_facturation')

    def valider_paiement_final(self, prestation, montant, tag, piece_id, compte, systeme):
            print("DEBUG: Début règlement créé avec succès !")
            reglement = Reglement.objects.create(
                famille=prestation.famille,
                date=timezone.now().date(),
                montant=montant,
                compte=compte,
                mode_id=6,
                payeur_id=3,
                observations=tag,
                modelimp_id=2,
            )

            # 2. Ventilation
            Ventilation.objects.create(
                famille=prestation.famille,
                reglement=reglement,
                prestation=prestation,
                montant=montant,
            )

            # 3. Comptabilité
            libelle = f"Paiement en ligne - {prestation.label} | Famille : {prestation.famille.nom}"
            operation = ComptaOperation.objects.create(
                type="credit",
                date=timezone.now(),
                libelle=libelle[:100],
                montant=montant,
                compte=compte,
                mode_id=6,
                num_piece=str(reglement.pk),
                ref_piece=str(piece_id)[:20],
                regul_avance=False,
                remb_avance=False,
            )

            # 4. Ventilation Comptable (Le compte n'est pas un argument de ComptaVentilation)
            ventilation = ComptaVentilation.objects.create(
                date_budget=timezone.now().date(),
                montant=montant,
                analytique_id=1,
                categorie_id=1,
                operation=operation,
            )

            # 5. Paiement pour suivi admin
            paiement_obj = Paiement.objects.create(
                famille=prestation.famille,
                idtransaction=str(piece_id)[:20],
                refdet=str(reglement.pk),
                montant=montant,
                systeme_paiement=systeme,
                resultat="PAID",
                message="Paiement validé",
                ventilation=str(ventilation.pk),
                horodatage=timezone.now(),
            )
            # Ajout du règlement dans le ManyToMany
            paiement_obj.reglements.add(reglement)

            # ... ton code de création ...
            print("DEBUG: Règlement créé avec succès !")
