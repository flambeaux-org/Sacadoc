# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import datetime, decimal, json
from django.urls import reverse_lazy, reverse
from django.db.models import Q, Sum
from core.views.mydatatableview import MyDatatable, columns, helpers
from core.views import crud
from core.models import Inscription, Activite, Rattachement, Cotisation, Groupe, Prestation, Ventilation, Mail, Destinataire
from core.utils import utils_texte
from fiche_individu.forms.individu_inscriptions import Formulaire
from django.shortcuts import redirect
from django.contrib import messages
from django.shortcuts import get_object_or_404
from django.views import View
from outils.utils import utils_email

class Page(crud.Page):
    model = Inscription
    url_liste = "demande_approbation_liste"
    url_modifier = "demande_approbation_modifier"
    url_supprimer = "demande_approbation_supprimer"
    url_supprimer_plusieurs = "inscriptions_activite_supprimer_plusieurs"
    description_liste = "Sélectionnez une activité puis effectuez la demande souhaitée. Vous pouvez soit demander à tous les inscrits de vérifier leurs informations personnelles ou relancer ceux qui ne l'ont pas encore fait."
    description_saisie = "Saisissez toutes les informations concernant l'inscription à saisir et cliquez sur le bouton Enregistrer."
    objet_singulier = "une vérification"
    objet_pluriel = "des vérifications"


class Liste(Page, crud.Liste):
    template_name = "individus/demande_approbation_liste.html"
    model = Inscription

    def get_queryset(self):
        condition = Q(activite__structure__in=self.request.user.structures.all())
        condition &= Q(activite__visible=True)
        qs = Inscription.objects.select_related(
            "famille", "individu", "groupe", "categorie_tarif", "activite", "activite__structure"
        ).filter(self.Get_filtres("Q"), condition, activite=self.Get_activite())

        # Annotation pour le tri
        from django.db.models import Max
        qs = qs.annotate(
            last_certification_date=Max("individu__rattachement__certification_date")
        )

        return qs
    def get_context_data(self, **kwargs):
        context = super(Liste, self).get_context_data(**kwargs)
        context['box_titre'] = "Liste des demandes de vérification"
        context["afficher_menu_brothers"] = True
        context["active_checkbox"] = False

        # Choix de l'activité
        context['activite'] = int(self.Get_activite()) if self.Get_activite() else None
        condition = Q(visible=True)
        liste_activites = []
        for activite in Activite.objects.filter(self.Get_condition_structure(), condition).order_by("-date_fin", "nom"):
            if activite.date_fin.year == 2999:
                liste_activites.append((activite.pk, "%s - Activité illimitée" % activite.nom))
            elif activite.date_fin:
                liste_activites.append((activite.pk, "%s - Du %s au %s" % (activite.nom, activite.date_debut.strftime("%d/%m/%Y"), activite.date_fin.strftime("%d/%m/%Y"))))
            else:
                liste_activites.append((activite.pk, "%s - A partir du %s" % (activite.nom, activite.date_debut.strftime("%d/%m/%Y"))))
        context['liste_activites'] = [(None, "--------")] + liste_activites

        context['url_supprimer_plusieurs'] = reverse_lazy(self.url_supprimer_plusieurs, kwargs={'activite': self.kwargs.get('activite', None), "listepk": "xxx"})
        return context

    def Get_activite(self):
        activite = self.kwargs.get("activite", None)
        if activite:
            activite = activite.replace("A", "")
            return activite
        return None


    def post(self, request, *args, **kwargs):
            action = request.POST.get("action")
            activite_id = self.Get_activite()
            if not activite_id:
                messages.error(request, "Aucune activité sélectionnée.")
                return redirect(request.path)

            erreurs = []
            inscriptions = self.get_queryset()

            # GLOBAL
            if action == "demande_globale":
                mails_crees = 0
                for ins in inscriptions:
                    ins.besoin_certification = True
                    ins.save()

                    act = ins.activite.nom
                    jeune = ins.individu.prenom
                    objet = f"[SACADOC] Demande de vérification des informations personnelles de {jeune}"
                    html = (
                        "<p>Bonjour,&nbsp;</p>"
                        f"<p>Le directeur de l'activité : {act} a effectué une demande de vérification des informations de {jeune}.</p>"
                        "<p>Merci de vous rendre sur Sacadoc ou de suivre ce lien pour effectuer la démarche : "
                        "<a href='https://sacadoc.flambeaux.org/'>Sacadoc</a>.</p>"
                        "<p>Bonne journée,&nbsp;</p>"
                        "<p>L'équipe Sacadoc</p>"
                    )
                    adresse_exp = request.user.adresse_exp
                    rattachement = Rattachement.objects.filter(individu=ins.individu).first()
                    if not rattachement or not rattachement.famille or not rattachement.famille.mail:
                        erreurs.append(f"{jeune} ({ins.individu.nom})")
                        continue  # On ne crée pas de mail pour cette inscription
                    famille = rattachement.famille

                    mail = Mail.objects.create(
                        categorie="saisie_libre",
                        objet=objet,
                        html=html,
                        adresse_exp=adresse_exp,
                        selection="NON_ENVOYE",
                        utilisateur=request.user,
                    )
                    destinataire = Destinataire.objects.create(categorie="famille", famille=famille,
                                                               adresse=famille.mail,)

                    mail.destinataires.add(destinataire)
                    succes = utils_email.Envoyer_model_mail(idmail=mail.pk, request=request)

                    if succes:
                        messages.add_message(request, messages.INFO,
                                             f"Une notification a été envoyé par email à la famille {famille}")
                    else:
                        messages.add_message(request, messages.ERROR,
                                             f"La notification par email n'a pas pu être envoyée à la famille {famille}")

                if erreurs:
                    messages.warning(request,
                                         "Pas de mail créé pour les inscriptions suivantes (informations manquantes) : " + ", ".join(
                                             erreurs))

                messages.success(request, f"{inscriptions.count()} inscriptions mises en demande de vérification.")
                return redirect(request.path)


            # RAPPEL
            elif action == "demande_rappel":
                limite = datetime.datetime.now() - datetime.timedelta(days=180)
                erreurs = []

                # Sélection des inscriptions à rappeler
                a_rappeler = inscriptions.filter().exclude(besoin_certification=False)

                for ins in a_rappeler:
                    act = ins.activite.nom
                    jeune = ins.individu.prenom
                    objet = f"[SACADOC] Rappel : vérification des informations personnelles de {jeune}"
                    html = (
                        "<p>Bonjour,&nbsp;</p>"
                        f"<p>Le directeur de l'activité : {act} vous rappelle de vérifier les informations personnelles de {jeune}.</p>"
                        "<p>Merci de vous rendre sur Sacadoc ou de suivre ce lien pour effectuer la démarche : "
                        "<a href='https://sacadoc.flambeaux.org/'>Sacadoc</a>.</p>"
                        "<p>Bonne journée,&nbsp;</p>"
                        "<p>L'équipe Sacadoc</p>"
                    )

                    adresse_exp = request.user.adresse_exp
                    rattachement = Rattachement.objects.filter(individu=ins.individu).first()
                    if not rattachement or not rattachement.famille or not rattachement.famille.mail:
                        erreurs.append(f"{jeune} ({ins.individu.nom})")
                        continue

                    famille = rattachement.famille

                    mail = Mail.objects.create(
                        categorie="saisie_libre",
                        objet=objet,
                        html=html,
                        adresse_exp=adresse_exp,
                        selection="NON_ENVOYE",
                        utilisateur=request.user,
                    )
                    destinataire = Destinataire.objects.create(
                        categorie="famille",
                        famille=famille,
                        adresse=famille.mail,
                    )
                    mail.destinataires.add(destinataire)

                    succes = utils_email.Envoyer_model_mail(idmail=mail.pk, request=request)
                    if succes:
                        messages.info(request, f"Rappel envoyé par email à la famille {famille}")
                    else:
                        messages.error(request, f"Le rappel n'a pas pu être envoyé à la famille {famille}")

                if erreurs:
                    messages.warning(
                        request,
                        "Pas de mail créé pour les inscriptions suivantes (informations manquantes) : " + ", ".join(
                            erreurs)
                    )

                messages.success(request, f"{a_rappeler.count()} rappels envoyés.")
                return redirect(request.path)

            elif action == "demande_annulation":
                inscriptions.update(besoin_certification=False)
                messages.success(request, f"{inscriptions.count()} inscriptions remises à jour pour le rappel.")
                return redirect(request.path)

    class datatable_class(MyDatatable):
        filtres = [ "individu__nom", "individu__prenom","besoin_certification", "last_approbation"]
        actions = columns.TextColumn("Actions", sources=None, processor="Get_actions_speciales")
        individu = columns.CompoundColumn("Individu", sources=["individu__nom", "individu__prenom"])
        last_approbation = columns.TextColumn("Date de dernière vérification", sources=[lambda instance: instance.last_certification_date or datetime.datetime.min], processor="Get_certification_date")
        besoin_certification = columns.TextColumn("Demande de vérification en attente", sources=["besoin_certification"], processor="Format_bool")
        class Meta:
            structure_template = MyDatatable.structure_template
            columns = [ "individu","besoin_certification","last_approbation"]
            hidden_columns = []
            page_length = 100
            processors = {
            }
            labels = {
            }
            ordering = ["individu"]

        def Format_bool(self, instance, *args, **kwargs):
            # instance = Inscription
            if instance.besoin_certification:
                return "<span style='color: red; font-weight: bold;'>Oui</span>"
            else:
                return "<span style='color: green; font-weight: bold;'>Non</span>"

        def Get_certification_date(self, instance, *args, **kwargs):
            # instance = Inscription
            individu = instance.individu
            if not individu:
                return "-"
            # On récupère le dernier rattachement
            dernier_rattachement = individu.rattachement_set.order_by('-certification_date').first()
            if not dernier_rattachement or not dernier_rattachement.certification_date:
                return "-"
            return dernier_rattachement.certification_date.strftime("%d/%m/%Y")

        def Get_actions_speciales(self, instance, *args, **kwargs):
            view = kwargs["view"]
            html = [
                self.Create_bouton(url=reverse("famille_resume", args=[instance.famille_id]), title="Ouvrir la fiche famille", icone="fa-users"),
                self.Create_bouton(
                    url=reverse("demande_approbation_individuelle", args=[instance.pk]),
                    title="Envoyer une demande de vérification",
                    icone="fa-paper-plane",
                ),
            ]

            return self.Create_boutons_actions(html)


class EnvoyerDemandeIndividuelle(View):
    def get(self, request, pk):
        ins = get_object_or_404(Inscription, pk=pk)

        # Vérification des droits (structure de l'utilisateur)
        if ins.activite.structure not in request.user.structures.all():
            messages.error(request, "Vous n'avez pas les droits sur cette activité.")
            return redirect(reverse("demande_approbation_liste", kwargs={"activite": "A%s" % ins.activite_id}))

        ins.besoin_certification = True
        ins.save()

        act = ins.activite.nom
        jeune = ins.individu.prenom
        objet = f"[SACADOC] Demande de vérification des informations personnelles de {jeune}"
        html = (
            "<p>Bonjour,&nbsp;</p>"
            f"<p>Le directeur de l'activité : {act} a effectué une demande de vérification des informations de {jeune}.</p>"
            "<p>Merci de vous rendre sur Sacadoc ou de suivre ce lien pour effectuer la démarche : "
            "<a href='https://sacadoc.flambeaux.org/'>Sacadoc</a>.</p>"
            "<p>Bonne journée,&nbsp;</p>"
            "<p>L'équipe Sacadoc</p>"
        )

        adresse_exp = request.user.adresse_exp
        rattachement = Rattachement.objects.filter(individu=ins.individu).first()

        if not rattachement or not rattachement.famille or not rattachement.famille.mail:
            messages.error(request, f"Impossible d'envoyer la demande pour {jeune} ({ins.individu.nom}) : informations manquantes.")
            return redirect(reverse("demande_approbation_liste", kwargs={"activite": "A%s" % ins.activite_id}))

        famille = rattachement.famille

        mail = Mail.objects.create(
            categorie="saisie_libre",
            objet=objet,
            html=html,
            adresse_exp=adresse_exp,
            selection="NON_ENVOYE",
            utilisateur=request.user,
        )
        destinataire = Destinataire.objects.create(
            categorie="famille",
            famille=famille,
            adresse=famille.mail,
        )
        mail.destinataires.add(destinataire)

        succes = utils_email.Envoyer_model_mail(idmail=mail.pk, request=request)

        if succes:
            messages.success(request, f"Demande envoyée par email à la famille {famille} pour {jeune}.")
        else:
            messages.error(request, f"La demande n'a pas pu être envoyée à la famille {famille}.")

        return redirect(reverse("demande_approbation_liste", kwargs={"activite": "A%s" % ins.activite_id}))


