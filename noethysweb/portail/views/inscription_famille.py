import json
import logging

from core.models import (
    AdresseMail,
    Destinataire,
    Famille,
    Individu,
    Mail,
    Rattachement,
    Utilisateur,
)
from core.utils import utils_questionnaires
from django.http import Http404
from django.shortcuts import render
from django.views.generic.base import ContextMixin, View
from fiche_famille.utils import utils_internet
from outils.utils.utils_email import Envoyer_model_mail

from portail.forms.inscription import InscriptionFamilleForm
from portail.views.login import ClassCommuneLogin

logger = logging.getLogger(__name__)


class InscriptionFamilleView(ClassCommuneLogin, ContextMixin, View):
    form: InscriptionFamilleForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if not context["parametres_portail"]["autoriser_inscription_famille"]:
            raise Http404("Inscription des familles pas activée.")
        self.form = InscriptionFamilleForm(self.request.POST or None)
        context["form"] = self.form
        return context

    def get(self, request):
        context = self.get_context_data()
        return render(request, "portail/inscription_famille.html", context)

    def post(self, request):
        context = self.get_context_data()
        logger.debug(f"Inscription famille avec {request.POST}")
        if not self.form.is_valid():
            return render(request, "portail/inscription_famille.html", context)

        # Vérification que l'adresse mail n'est pas déjà utilisée
        # N'utilise pas Individu.objects.get(mail=...) car le champ est chiffré
        mail = self.form.cleaned_data["mail"]
        existing_individus = Individu.objects.values("idindividu", "mail")
        for indv in existing_individus:
            if indv["mail"] and indv["mail"].lower() == mail.lower():
                # Le mail existe déjà, on prévient sur la page d'inscription
                context["mail_exists"] = True
                return render(self.request, "portail/inscription_famille.html", context)


        # From fiche_famille.views.famille_ajouter.Ajouter.Creation_famille
        famille = Famille.objects.create()
        utils_questionnaires.Creation_reponses(
            categorie="famille", liste_instances=[famille]
        )

        internet_identifiant = utils_internet.CreationIdentifiant(IDfamille=famille.pk)
        famille.internet_identifiant = internet_identifiant
        famille.internet_mdp = "*****"

        utilisateur = Utilisateur(username=internet_identifiant, categorie="famille")
        utilisateur.save()
        utilisateur.set_password(self.form.cleaned_data["new_password1"])
        famille.utilisateur = utilisateur
        famille.save()
        utilisateur.save()

        individu = Individu()
        individu.nom = self.form.cleaned_data["nom"]
        individu.prenom = self.form.cleaned_data["prenom"]
        individu.mail = self.form.cleaned_data["mail"]
        individu.civilite = self.form.cleaned_data["civilite"]
        individu.save()

        utils_questionnaires.Creation_reponses(
            categorie="individu", liste_instances=[individu]
        )
        rattachement = Rattachement(
            famille=famille,
            individu=individu,
            categorie=1,
            titulaire=True,
        )
        rattachement.save()
        famille.Maj_infos()

        # Envoi du mail
        # inspiré de noethysweb/outils/views/editeur_emails_express.py
        # TODO: utiliser un modèle de mail à l'avenir ?
        content = (
            """<p align="left">Bonjour,</p>"""
            """<p align="left"></p>"""
            """<p align="left">Veuillez trouver ci-dessous vos codes d'accès personnels au portail famille.</p>"""
            """<p align="left"></p>"""
            """<p align="left">L'identifiant de connexion est : <b>{IDENTIFIANT_INTERNET}<br></b>"""
            """<p align="left"></p>"""
            """<p align="left">Bonne réception,</p>"""
            """<p align="left"></p>"""
            """<p align="left">L'équipe Sacadoc</p>"""
            """<p align="left">https://sacadoc.flambeaux.org</p>"""
        )
        mail = Mail.objects.create(
            categorie="portail",
            objet="Inscription à Sacadoc | Flambeaux",
            html=content,
            # TODO: il faut définir en adresse n°1 un noreply-sacadoc@flambeaux.org ou une adresse générique pour le support sacdoc
            adresse_exp=AdresseMail.objects.get(idadresse=1),
            selection="NON_ENVOYE",
            verrouillage_destinataires=True,
            utilisateur=utilisateur,
        )
        destinataire = Destinataire.objects.create(
            categorie="famille",
            famille=famille,
            adresse=famille.mail,
            valeurs=json.dumps({"{IDENTIFIANT_INTERNET}": internet_identifiant}),
        )
        mail.destinataires.add(destinataire)
        Envoyer_model_mail(mail.pk)

        # TODO : dans le futur, permettre la connexion via email

        context["inscription_ok"] = True
        return render(self.request, "portail/inscription_famille.html", context)
