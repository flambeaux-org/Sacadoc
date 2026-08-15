# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import json
from decimal import Decimal, ROUND_HALF_UP
from django.urls import reverse_lazy, reverse
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import render
from django.db.models import Sum, Q
from core.views.mydatatableview import MyDatatable, columns, helpers
from core.views import crud
from core.models import Famille, Reglement, Payeur, Emetteur, ModeReglement, Prestation, Ventilation, Mandat, Activite, ComptaOperation, ComptaVentilation
from core.utils import utils_dates, utils_texte
from facturation.utils import utils_factures
from fiche_famille.forms.famille_reglements import Formulaire
from fiche_famille.views.famille import Onglet
import datetime
from django.utils import timezone
from django.shortcuts import redirect
from django.contrib import messages

def Reglement_est_modifiable(reglement):
    """ Retourne False si le règlement est lié à au moins une prestation d'une activité archivée (inactive) """
    ids_prestations = Ventilation.objects.filter(reglement=reglement).values_list("prestation_id", flat=True)
    return not Prestation.objects.filter(pk__in=ids_prestations, activite__actif=False).exists()

def Get_ventilation(request):
    """ Renvoie une liste d'activités """
    mode_regroupement = request.POST.get("regroupement", "mois")
    idfamille = request.POST.get("idfamille", 0)
    idreglement = request.POST.get("idreglement", 0)

    # Importation de la ventilation antérieure
    ventilations_anterieures = Ventilation.objects.values('prestation').filter(famille_id=idfamille).exclude(reglement_id=idreglement).annotate(total=Sum("montant"))
    dict_ventilations_anterieures = {x["prestation"]: x["total"] for x in ventilations_anterieures}

    # Importation de la ventilation du règlement
    ventilations_reglement = Ventilation.objects.values('prestation').filter(reglement_id=idreglement).annotate(total=Sum("montant"))
    dict_ventilations_reglement = {x["prestation"]: x["total"] for x in ventilations_reglement}

    # Importation des prestations de la famille
    activites_autorisees = Activite.objects.filter(structure__in=request.user.structures.all())
    prestations = Prestation.objects.select_related('individu', 'facture').filter(famille_id=idfamille, activite__in=activites_autorisees).order_by("date")
    liste_prestations = []
    for prestation in prestations:
        ventilation_anterieure = dict_ventilations_anterieures.get(prestation.pk, Decimal(0))
        ventilation_reglement = dict_ventilations_reglement.get(prestation.pk, Decimal(0))
        montant_ventile = ventilation_anterieure + ventilation_reglement

        if (prestation.montant >= Decimal(0) and montant_ventile < prestation.montant) or (prestation.montant < Decimal(0) and montant_ventile > prestation.montant) or ventilation_reglement != Decimal(0):
            prestation.ventilation_anterieure = ventilation_anterieure
            prestation.ventilation_reglement = ventilation_reglement
            prestation.reste_ventilation = prestation.montant - ventilation_reglement - ventilation_anterieure
            liste_prestations.append(prestation)

    context = {"prestations": liste_prestations, "mode_regroupement": mode_regroupement, "encaissement": False}
    return render(request, "fiche_famille/widgets/ventilation_ajax.html", context)


def On_selection_mode_reglement(request):
    idmode = request.POST.get("idmode")
    if not idmode or idmode == "None":
        return JsonResponse({"numero_piece": None, "emetteurs": []})

    mode = ModeReglement.objects.get(pk=int(idmode))
    emetteurs = Emetteur.objects.filter(mode_id=int(idmode)).order_by("nom")
    return JsonResponse({
        "numero_piece": mode.numero_piece,
        "emetteurs": [
            {"id": emetteur.pk, "text": emetteur.nom, "image": emetteur.image.name}
            for emetteur in emetteurs
        ],
        "encaissement": mode.encaissement  #
    })

def Modifier_payeur(request):
    action = request.POST.get("action")
    idpayeur = request.POST.get("id")
    nom = request.POST.get("valeur")
    donnees_extra = json.loads(request.POST.get("donnees_extra"))

    # Ajouter un payeur
    if action == "ajouter":
        payeur = Payeur.objects.create(famille_id=int(donnees_extra["idfamille"]), nom=nom)
        return JsonResponse({"action": action, "id": payeur.pk, "valeur": payeur.nom})

    # Modifier un payeur
    if action == "modifier":
        payeur = Payeur.objects.get(idpayeur=int(idpayeur))
        payeur.nom = nom
        payeur.save()
        return JsonResponse({"action": action, "id": payeur.pk, "valeur": payeur.nom})

    # Supprimer un payeur
    if action == "supprimer":
        try:
            payeur = Payeur.objects.get(idpayeur=int(idpayeur))
            payeur.delete()
            return JsonResponse({"action": action, "id": int(idpayeur)})
        except:
            return JsonResponse({"erreur": "Vous ne pouvez pas supprimer cette donnée"}, status=401)

    return JsonResponse({"erreur": "Erreur !"}, status=401)


class Page(Onglet):
    model = Reglement
    url_liste = "famille_reglements_liste"
    url_ajouter = "famille_reglements_ajouter"
    url_modifier = "famille_reglements_modifier"
    url_supprimer = "famille_reglements_supprimer"
    url_supprimer_plusieurs = "famille_reglements_supprimer_plusieurs"
    description_liste = "Saisissez ici les règlements de la famille."
    description_saisie = "Saisissez toutes les informations concernant le règlement et cliquez sur le bouton Enregistrer."
    objet_singulier = "un règlement"
    objet_pluriel = "des règlements"
    format_historique = "Règlement ID{0.pk} Date={0.date} Mode={0.mode} Numéro={0.numero_piece} Montant={0.montant}"

    def get_context_data(self, **kwargs):
        """ Context data spécial pour onglet """
        context = super(Page, self).get_context_data(**kwargs)
        if not hasattr(self, "verbe_action"):
            context['box_titre'] = "Règlements"
        context['onglet_actif'] = "reglements"
        context['boutons_liste'] = [
            {"label": "Ajouter", "classe": "btn btn-success", "href": reverse_lazy(self.url_ajouter, kwargs={'idfamille': self.kwargs.get('idfamille', None)}), "icone": "fa fa-plus"},
        ]
        # Ajout l'idfamille à l'URL de suppression groupée
        context['url_supprimer_plusieurs'] = reverse_lazy(self.url_supprimer_plusieurs, kwargs={'idfamille': self.kwargs.get('idfamille', None), "listepk": "xxx"})
        # Vérifie si le prélèvement est actif
        context['nbre_mandats_actifs'] = Mandat.objects.filter(famille_id=self.kwargs['idfamille'], actif=True).count()
        return context

    def get_form_kwargs(self, **kwargs):
        """ Envoie l'idindividu au formulaire """
        form_kwargs = super(Page, self).get_form_kwargs(**kwargs)
        form_kwargs["idfamille"] = self.Get_idfamille()
        return form_kwargs

    def get_success_url(self):
        """ Renvoie vers la liste après le formulaire """
        url = self.url_liste
        if "SaveAndNew" in self.request.POST:
            url = self.url_ajouter
        return reverse_lazy(url, kwargs={'idfamille': self.kwargs.get('idfamille', None)})



class Liste(Page, crud.Liste):
    model = Reglement
    template_name = "fiche_famille/famille_reglements.html"

    def get_queryset(self):
        limite_date = timezone.now().date() - datetime.timedelta(days=365)
        return Reglement.objects.select_related('mode', 'emetteur', 'payeur', 'depot').annotate(ventile=Sum("ventilation__montant")).filter(Q(famille__pk=self.Get_idfamille()) & Q(date__gte=limite_date) & self.Get_filtres("Q"))

    def get_context_data(self, **kwargs):
        context = super(Liste, self).get_context_data(**kwargs)
        context['impression_introduction'] = ""
        context['impression_conclusion'] = ""
        context['active_checkbox'] = True
        return context

    class datatable_class(MyDatatable):
        filtres = ['idreglement', 'date', 'mode__label', 'emetteur__nom', 'numero_piece', 'payeur__nom', 'montant', 'depot__date']

        check = columns.CheckBoxSelectColumn(label="")
        actions = columns.TextColumn("Actions", sources=None, processor='Get_actions_speciales')
        mode = columns.TextColumn("Mode", sources=['mode__label'])
        # emetteur = columns.TextColumn("Emetteur", sources=['emetteur__nom'])
        payeur = columns.TextColumn("Payeur", sources=['payeur__nom'])
        depot = columns.TextColumn("Dépôt", sources=['depot__date'], processor='Get_date_depot')
        ventile = columns.TextColumn("Ventilé", sources=['ventile'], processor='Formate_ventile')

        class Meta:
            structure_template = MyDatatable.structure_template
            columns = ['check', 'idreglement', 'date', 'mode', 'numero_piece', 'payeur', 'montant', 'ventile', 'depot']
            processors = {
                'date': helpers.format_date('%d/%m/%Y'),
                'depot': helpers.format_date('%d/%m/%Y'),
                'montant': "Formate_montant_standard",
            }
            ordering = ['date']

        def Formate_ventile(self, instance, **kwargs):
            if not instance.ventile:
                instance.ventile = Decimal(0)
            if instance.ventile == Decimal(0):
                classe = "text-red"
            elif instance.ventile == instance.montant:
                classe = "text-green"
            else:
                classe = "text-orange"
            return "<span class='%s'>%s</span>" % (classe, utils_texte.Formate_montant(instance.ventile))

        def Get_date_depot(self, instance, *args, **kwargs):
            if instance.depot:
                return utils_dates.ConvertDateToFR(instance.depot.date)
            return ""

        def Get_actions_speciales(self, instance, *args, **kwargs):
            """ Inclut l'idindividu dans les boutons d'actions """
            view = kwargs["view"]
            # Récupération idfamille
            kwargs = view.kwargs

            # Ajoute l'id de la ligne
            kwargs["pk"] = instance.pk

            html = []
            if Reglement_est_modifiable(instance):
                html.append(self.Create_bouton_modifier(url=reverse(view.url_modifier, kwargs=kwargs)))
            else:
                html.append(self.Create_bouton(
                    url="#",
                    title="Modification impossible : ce règlement est lié à une activité archivée",
                    icone="fa-pencil",
                    args="style=\"pointer-events:none; opacity:0.4;\" onclick=\"return false;\""
                ))
            html.append(self.Create_bouton_supprimer(url=reverse(view.url_supprimer, kwargs=kwargs)))
            html.append(self.Create_bouton_imprimer(url=reverse("famille_recus_ajouter",
                                                                kwargs={"idfamille": kwargs["idfamille"],
                                                                        "idreglement": instance.pk}),
                                                    title="Editer un reçu"))
            return self.Create_boutons_actions(html)


class ClasseCommune(Page):
    form_class = Formulaire
    template_name = "fiche_famille/famille_reglements.html"

    def get_context_data(self, *args, **kwargs):
        context_data = super(ClasseCommune, self).get_context_data(**kwargs)
        return context_data

    def form_valid(self, form):
        try:
            liste_ventilations = json.loads(self.request.POST.get("ventilation"))
            print(liste_ventilations)
        except Exception:
            form.add_error(None, "Erreur de lecture de la ventilation.")
            return self.form_invalid(form)

        # Calcul du total ventilé avec une valeur de départ Decimal
        total_ventilation = sum((Decimal(item["montant"]) for item in liste_ventilations), Decimal('0'))
        montant_reglement = form.cleaned_data["montant"]

        # Arrondir les deux montants à 2 décimales
        total_ventilation = total_ventilation.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        montant_reglement = montant_reglement.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        if abs(total_ventilation - montant_reglement) > Decimal("0.01"):
            form.add_error(None,f"Le total ventilé ({total_ventilation} €) ne correspond pas au montant du règlement ({montant_reglement} €).")
            return self.form_invalid(form)

        # Enregistrement du règlement
        reglement = form.save(commit=True)

        # Enregistrement de la ventilation
        liste_ventilations = json.loads(self.request.POST.get("ventilation"))

        # Importe les ventilations existantes
        ventilations_reglement = Ventilation.objects.filter(reglement_id=reglement.pk)

        # Enregistre les ventilations
        liste_IDtraitees = []
        for dict_temp in liste_ventilations:
            Ventilation.objects.update_or_create(famille=reglement.famille, prestation_id=dict_temp["idprestation"],
                                                 reglement=reglement, defaults={"montant": Decimal(dict_temp["montant"])})
            liste_IDtraitees.append(dict_temp["idprestation"])

        # Supprime les ventilations obsolètes
        liste_ID_prestations = []
        for ventilation in ventilations_reglement:
            liste_ID_prestations.append(ventilation.prestation_id)
            if ventilation.prestation_id not in liste_IDtraitees:
                ventilation.delete()

        # Recalcule le solde des factures associées
        utils_factures.Maj_solde_actuel(liste_idprestation=liste_ID_prestations + liste_IDtraitees)

        # --- Ajout de l'enregistrement comptable ---
        compte_form = form.cleaned_data["compte"]
        if not compte_form:
            compte_form = CompteBancaire.objects.filter(Q(structure__in=self.request.user.structures.all()) | Q(structure__isnull=True)).first()

        # Met à jour ou crée l'opération comptable liée à ce règlement
        compta_op, created = ComptaOperation.objects.update_or_create(
            num_piece=str(reglement.pk),  # critère unique : 1 opération par règlement
            defaults={
                "type": "credit",  # ou "debit" selon ton cas
                "date": reglement.date,
                "libelle": f"Règlement famille {reglement.famille}",
                "mode": reglement.mode,
                "compte": compte_form,
                "montant": reglement.montant,
            }
        )

        # --- Crée ou met à jour les ventilations comptables ---
        for item in liste_ventilations:
            prestation = Prestation.objects.get(pk=item["idprestation"])

            # Choisir la catégorie : spéciale si mode encaissement
            if reglement.mode.encaissement:
                categorie_id = 33  # ID de ta catégorie "Règlements encaissement"
            else:
                categorie_id = 1  # ID normal, à adapter selon ton DB

            ComptaVentilation.objects.update_or_create(
                operation=compta_op,
                defaults={
                    "categorie_id": categorie_id,
                    "analytique_id": 1,  # à adapter
                    "montant": reglement.montant,
                    "date_budget": reglement.date,
                }
            )
        return super().form_valid(form)

class Ajouter(ClasseCommune, crud.Ajouter):
    form_class = Formulaire
    template_name = "fiche_famille/famille_edit.html"

    def get_success_url(self):
        """ Renvoie vers la liste après le formulaire """
        famille = Famille.objects.get(pk=self.kwargs.get('idfamille', None))
        url = self.url_ajouter if "SaveAndNew" in self.request.POST else self.url_liste
        return reverse_lazy(url, kwargs={"idfamille": famille.pk})


class Modifier(ClasseCommune, crud.Modifier):
    form_class = Formulaire
    template_name = "fiche_famille/famille_edit.html"

    def dispatch(self, request, *args, **kwargs):
        reglement = Reglement.objects.get(pk=kwargs.get("pk"))
        if not Reglement_est_modifiable(reglement):
            messages.error(request, "Ce règlement est lié à une activité archivée et ne peut pas être modifié.")
            return redirect(reverse(self.url_liste, kwargs={"idfamille": kwargs.get("idfamille")}))
        return super().dispatch(request, *args, **kwargs)


class Supprimer(Page, crud.Supprimer):
    template_name = "fiche_famille/famille_delete.html"
    liste_idprestation = []

    def Avant_suppression(self, objet=None):
        # Met à jour le solde des factures associées aux prestations du règlement
        print(objet)
        self.liste_idprestation = [ventilation.prestation_id for ventilation in Ventilation.objects.filter(reglement=objet)]
        ComptaOperation.objects.filter(num_piece=objet.idreglement).delete()
        return True

    def Apres_suppression(self, objet=None):
        utils_factures.Maj_solde_actuel(liste_idprestation=self.liste_idprestation)




class Supprimer_plusieurs(Page, crud.Supprimer_plusieurs):
    template_name = "fiche_famille/famille_delete.html"
    liste_idprestation = []

    def Avant_suppression(self, objets=[]):
        # Met à jour le solde des factures associées aux prestations du règlement
        for reglement in objets:
            self.liste_idprestation += [ventilation.prestation_id for ventilation in Ventilation.objects.filter(reglement=reglement)]
            ComptaOperation.objects.filter(num_piece=reglement.idreglement).delete()
        return True

    def Apres_suppression(self, objets=[]):
        utils_factures.Maj_solde_actuel(liste_idprestation=self.liste_idprestation)
