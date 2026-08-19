# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging, datetime
logger = logging.getLogger(__name__)
from django.urls import reverse_lazy, reverse
from django.http import HttpResponse, HttpResponseRedirect
from django.template import Template, RequestContext
from django.db.models import Q
from django.contrib import messages
from core.views.mydatatableview import MyDatatable, columns, helpers
from core.views import crud
from core.models import Inscription, Prestation, Groupe, CategorieTarif, Consommation, Ouverture, Tarif, Facture, Deduction
from core.utils import utils_dates
from fiche_individu.forms.individu_inscriptions import Formulaire
from fiche_individu.views.individu import Onglet
from individus.utils import utils_forfaits


def Get_groupes(request):
    idactivite = request.POST.get('idactivite')
    if idactivite == "":
        resultat = ""
    else:
        groupes = Groupe.objects.filter(activite_id=idactivite).order_by('ordre')
        html = """
        <option value="">---------</option>
        {% for groupe in groupes %}
            <option value="{{ groupe.pk }}">{{ groupe.nom }}</option>
        {% endfor %}
        """
        context = {'groupes': groupes}
        resultat = Template(html).render(RequestContext(request, context))
    return HttpResponse(resultat)


def Get_tarifs(request):
    idactivite = request.POST.get('idactivite')
    if idactivite == "":
        resultat = ""
    else:
        tarifs = Tarif.objects.filter(activite_id=idactivite)
        html = """
        <option value="">---------</option>
        {% for tarif in tarifs %}
            <option value="{{ tarif.pk }}">{{ tarif.description }}</option>
        {% endfor %}
        """
        context = {'tarifs': tarifs}
        resultat = Template(html).render(RequestContext(request, context))
    return HttpResponse(resultat)


class Page(Onglet):
    model = Inscription
    url_liste = "individu_inscriptions_liste"
    url_ajouter = "individu_inscriptions_ajouter"
    url_modifier = "individu_inscriptions_modifier"
    url_supprimer = "individu_inscriptions_supprimer"
    description_liste = "Cette page permet de gérer les inscriptions de l'individu. Si une inscription n'est pas modifiable, il faut d'abord supprimer la facture qui est liée. Dans ce cas, un bouton permet d'y accéder directement."
    description_saisie = "Saisissez toutes les informations concernant l'inscription et cliquez sur le bouton Enregistrer."
    objet_singulier = "une inscription"
    objet_pluriel = "des inscriptions"

    def get_context_data(self, **kwargs):
        """ Context data spécial pour onglet """
        context = super(Page, self).get_context_data(**kwargs)
        if not hasattr(self, "verbe_action"):
            context['box_titre'] = "Inscriptions"
        context['onglet_actif'] = "inscriptions"
        context['boutons_liste'] = [
            {"label": "Ajouter", "classe": "btn btn-success", "href": reverse_lazy(self.url_ajouter, kwargs={'idindividu': self.Get_idindividu(), 'idfamille': self.kwargs.get('idfamille', None)}), "icone": "fa fa-plus"},
        ]
        return context

    def get_form_kwargs(self, **kwargs):
        """ Envoie l'idindividu au formulaire et les infos rentrées dans le form par la famille """
        form_kwargs = super(Page, self).get_form_kwargs(**kwargs)
        form_kwargs["idindividu"] = self.Get_idindividu()
        form_kwargs["idfamille"] = self.Get_idfamille()
        form_kwargs["idactivite"] = self.kwargs.get("idactivite", None)
        form_kwargs["idgroupe"] = self.kwargs.get("idgroupe", None)
        form_kwargs["idtarifs"] = self.kwargs.get("idstarifs", None)
        form_kwargs["iddemande"] = self.kwargs.get("iddemande", None)
        return form_kwargs

    def get_success_url(self):
        """ Renvoie vers la liste après le formulaire """
        url = self.url_liste
        if "SaveAndNew" in self.request.POST:
            url = self.url_ajouter
        return reverse_lazy(url, kwargs={'idindividu': self.Get_idindividu(), 'idfamille': self.kwargs.get('idfamille', None)})

    def check_inscriptions_existantes(self, form=None, instance=None):
        # On vérifie si l'individu est déjà inscrit à cette activité sur cette famille
        activite = form.cleaned_data["activite"]
        if not activite.inscriptions_multiples:
            date_debut = form.cleaned_data["date_debut"]
            date_fin = form.cleaned_data["date_fin"] if form.cleaned_data["date_fin"] else datetime.date(2999, 12, 31)
            inscriptions_paralleles = []
            for inscription in Inscription.objects.filter(individu=form.cleaned_data["individu"], famille=form.cleaned_data["famille"], activite=form.cleaned_data["activite"]):
                date_fin_temp = inscription.date_fin if inscription.date_fin else datetime.date(2999, 12, 31)
                if inscription.date_debut <= date_fin and date_fin_temp >= date_debut and inscription != instance:
                    inscriptions_paralleles.append(inscription)
            if inscriptions_paralleles:
                messages.add_message(self.request, messages.ERROR, "Inscription impossible : Cet individu est déjà inscrit à cette activité sur cette période et sur cette famille")
                return False
        return True


class Liste(Page, crud.Liste):
    model = Inscription
    template_name = "fiche_individu/individu_liste.html"

    def get_queryset(self):
        return Inscription.objects.select_related("activite", "groupe", "famille", "activite__structure").filter(Q(individu=self.Get_idindividu()) & self.Get_filtres("Q"))

    def get_context_data(self, **kwargs):
        context = super(Liste, self).get_context_data(**kwargs)
        context['impression_introduction'] = ""
        context['impression_conclusion'] = ""
        return context

    class datatable_class(MyDatatable):
        filtres = ["idinscription", 'date_debut', 'date_fin', 'activite', 'groupe', 'statut']

        actions = columns.TextColumn("Actions", sources=None, processor='Get_actions_speciales')
        activite = columns.TextColumn("Activité", sources=['activite__nom'])
        groupe = columns.TextColumn("Groupe", sources=['groupe__nom'])
        famille = columns.TextColumn("Famille", sources=['famille__nom'])

        class Meta:
            structure_template = MyDatatable.structure_template
            columns = ["idinscription", 'date_debut', 'date_fin', 'activite', 'groupe', 'statut', 'famille']
            processors = {
                'date_debut': helpers.format_date('%d/%m/%Y'),
                'date_fin': helpers.format_date('%d/%m/%Y'),
                'statut': 'Formate_statut',
            }
            ordering = ['date_debut']

        def Formate_statut(self, instance, *args, **kwargs):
            if instance.statut == "attente":
                return "<i class='fa fa-hourglass-2 text-orange'></i> Attente"
            elif instance.statut == "refus":
                return "<i class='fa fa-times-circle text-red'></i> Refus"
            else:
                return "<i class='fa fa-check-circle-o text-green'></i> Valide"

        from django.urls import reverse
        from core.models import Facture  # Assurez-vous que ce modèle est importé correctement

        def Get_actions_speciales(self, instance, *args, **kwargs):
            """ Inclut l'idindividu dans les boutons d'actions """
            view = kwargs["view"]
            kwargs = view.kwargs
            kwargs["idfamille"] = instance.famille.pk if instance.famille else None
            kwargs["idindividu"] = instance.individu.pk if instance.individu else None
            kwargs["pk"] = instance.pk

            # Définir les conditions
            user_can_modify = instance.activite.structure in view.request.user.structures.all()
            nbre_prestations_facturees = Prestation.objects.filter(
                famille=instance.famille,
                individu=instance.individu,
                activite=instance.activite,
                facture__isnull=False
            ).count()

            # Vérifie si une facture existe
            facture = Facture.objects.filter(
                individus=instance.individu.idindividu,
                activites=instance.activite.idactivite
            ).first()

            # Définir les boutons
            modifier_buttons = []
            facture_button = ""
            modif_buttons = ""

            if user_can_modify:
                if nbre_prestations_facturees > 0:
                    modif_buttons = "<a href='#' class='text-red'><i class='fa fa-pencil-alt margin-r-5'></i></a>"

                    if facture:
                        facture_url = reverse('famille_factures_liste', kwargs={'idfamille': instance.famille.pk})
                        modif_buttons = (
                            f"<a href='#' class='text-red'>"
                            "<i class='fa fa-pencil'></i>"
                            "</a>"
                        )

                        facture_button = (
                            f"<a href='{facture_url}' class='btn btn-default btn-xs'>"
                            "<i class='fa fa-file-pdf-o'></i>"
                            "</a>"
                        )
                else:
                    # Bouton pour la modification
                    modifier_kwargs = kwargs.copy()
                    modifier_kwargs["idactivite"] = instance.activite.pk
                    modifier_kwargs["idgroupe"] = instance.groupe.pk if instance.groupe else None
                    modifier_kwargs["idtarifs"] = ','.join(
                        [str(tarif.pk) for tarif in instance.tarifs.all()]) if instance.tarifs.exists() else '1'
                    modifier_url = reverse(view.url_modifier, kwargs=modifier_kwargs)
                    modifier_buttons.append(self.Create_bouton_modifier(url=modifier_url))
            else:
                # Afficher que l'accès est interdit
                modifier_buttons.append(
                    "<span class='text-red'><i class='fa fa-pencil-alt margin-r-5' title='Accès interdit'></i><i class='fa fa-ban' title='Accès interdit'></i> Accès interdit</span>"
                )

            # Définir le bouton pour la suppression
            kwargs_supprimer = kwargs.copy()
            kwargs_supprimer.pop("idactivite", None)
            kwargs_supprimer.pop("idgroupe", None)
            kwargs_supprimer.pop("idtarifs", None)
            supprimer_url = reverse(view.url_supprimer, kwargs=kwargs_supprimer)
            supprimer_button = self.Create_bouton_supprimer(url=supprimer_url)

            # Retourner les boutons correspondants
            return self.Create_boutons_actions(modifier_buttons + [modif_buttons, facture_button, supprimer_button])


class Ajouter(Page, crud.Ajouter):
    form_class = Formulaire
    template_name = "fiche_individu/individu_edit.html"

    def form_valid(self, form):
        # On vérifie si l'individu est déjà inscrit à cette activité sur cette famille
        if self.check_inscriptions_existantes(form, instance=self.object) == False:
            return self.render_to_response(self.get_context_data(form=form))

        # Sauvegarde de l'aide
        self.object = form.save()
        messages.add_message(self.request, messages.SUCCESS, "L'inscription a bien été enregistrée")
        messages.add_message(self.request, messages.SUCCESS, "L'émail de confirmation de l'inscription a bien été envoyé.")
        return HttpResponseRedirect(self.get_success_url())


class Modifier(Page, crud.Modifier):
    form_class = Formulaire
    template_name = "fiche_individu/individu_edit.html"

    def test_func(self):
        """ Vérifie que l'utilisateur peut se connecter à cette page """
        if not super(Modifier, self).test_func():
            return False
        inscription = Inscription.objects.select_related("activite", "activite__structure").get(pk=self.kwargs["pk"])
        if inscription.activite.structure not in self.request.user.structures.all():
            return False
        return True

    def Check_protections(self, objet=None):
        # Une prestation déjà facturée ou avec une déduction n'est jamais modifiable (impact comptable définitif).
        # En revanche, un règlement seul (sans facture) n'empêche plus la modification : les prestations concernées
        # sont recalculées automatiquement (voir form_valid), et le moteur de recalcul protège désormais les
        # prestations déjà ventilées contre toute suppression (consommations/views/grille.py).
        protections = []
        prestations = Prestation.objects.filter(famille=objet.famille.pk, individu=objet.individu.pk, activite=objet.activite.pk)
        nbre_prestations_facturees = Prestation.objects.filter(famille=objet.famille, individu=objet.individu, activite=objet.activite, facture__isnull=False).count()
        if nbre_prestations_facturees:
            protections.append("Vous ne pouvez pas modifier cette inscription car %s prestations associées sont déjà facturées." % nbre_prestations_facturees)
        nbre_deductions = Deduction.objects.filter(prestation__in=prestations).count()
        if nbre_deductions:
            protections.append("Vous ne pouvez pas modifier cette inscription car %s déductions sont déjà associées." % nbre_deductions)
        return protections

    def form_valid(self, form):
        # On vérifie si l'individu est déjà inscrit à cette activité sur cette famille
        if self.check_inscriptions_existantes(form, instance=self.object) == False:
            return self.render_to_response(self.get_context_data(form=form))

        # On vérifie qu'il n'existe pas de consommations associées en dehors de la période de la réservation
        if form.cleaned_data["date_fin"]:
            condition = Q(inscription=self.object) & (Q(date__lt=form.cleaned_data["date_debut"]) | Q(date__gt=form.cleaned_data["date_fin"]))
        else:
            condition = Q(inscription=self.object, date__lte=form.cleaned_data["date_debut"])
        nbre_conso = Consommation.objects.filter(condition).count()
        if nbre_conso:
            messages.add_message(self.request, messages.ERROR, "Modification impossible : %d consommations existent déjà hors de la période d'inscription sélectionnée" % nbre_conso)
            return self.render_to_response(self.get_context_data(form=form))

        # Modification des conso déjà associées
        if form.cleaned_data["action_conso"] in ("MODIFIER_TOUT", "MODIFIER_AUJOURDHUI", "MODIFIER_DATE"):

            # Importation des consommations existantes
            conditions = Q(inscription=self.object)
            if form.cleaned_data["action_conso"] == "MODIFIER_AUJOURDHUI":
                conditions &= Q(date__gte=datetime.date.today())
            if form.cleaned_data["action_conso"] == "MODIFIER_DATE":
                if not form.cleaned_data["date_modification"]:
                    messages.add_message(self.request, messages.ERROR, "Vous devez saisir une date d'application")
                    return self.render_to_response(self.get_context_data(form=form))
                conditions &= Q(date__gte=form.cleaned_data["date_modification"])
            consommations = Consommation.objects.filter(conditions)

            # Changement du groupe
            if "groupe" in form.changed_data and consommations:
                logger.debug("Changement de groupe pour les consommations...")
                # Vérifie que les unités et dates souhaitées sont ouvertes sur le nouveau groupe
                ouvertures = [(ouverture.date, ouverture.unite_id) for ouverture in Ouverture.objects.filter(groupe=form.cleaned_data["groupe"])]
                anomalies = []
                for conso in consommations:
                    if (conso.date, conso.unite_id) not in ouvertures:
                        anomalies.append(utils_dates.ConvertDateToFR(conso.date))
                if anomalies:
                    messages.add_message(self.request, messages.ERROR, "Modification impossible des consommations ! Les consommations ne peuvent pas être transférées sur les dates suivantes car les unités sont fermées : %s." % ", ".join(anomalies))
                    return self.render_to_response(self.get_context_data(form=form))
                # Modifie le groupe des consommations existantes
                nouvelles_conso = []
                for conso in consommations:
                    conso.groupe = form.cleaned_data["groupe"]
                    nouvelles_conso.append(conso)
                Consommation.objects.bulk_update(nouvelles_conso, ["groupe"], batch_size=50)

            # Changement des tarifs
            if "tarifs" in form.changed_data and consommations: #A MODIFIER
                logger.debug("Changement des tarifs pour les consommations...")
                # Enregistre l'inscription modifiée
                self.object.save()
                # Recalcule les prestations
                liste_dates = [conso.date for conso in consommations]
                from consommations.utils.utils_grille_virtuelle import Grille_virtuelle
                grille = Grille_virtuelle(request=self.request, idfamille=form.cleaned_data["famille"].pk, idindividu=form.cleaned_data["individu"].pk,
                                          idactivite=form.cleaned_data["activite"].pk, date_min=min(liste_dates), date_max=max(liste_dates))
                for conso in consommations:
                    grille.Modifier(criteres={"idconso": conso.pk}, modifications={"tarifs": form.cleaned_data["tarifs"].pk})
                grille.Enregistrer()
        return super(Modifier, self).form_valid(form)


class Supprimer(Page, crud.Supprimer):
    template_name = "fiche_individu/individu_delete.html"

    def test_func(self):
        """ Vérifie que l'utilisateur peut se connecter à cette page """
        if not super(Supprimer, self).test_func():
            return False
        inscription = Inscription.objects.select_related("activite", "activite__structure").get(pk=self.kwargs["pk"])
        if inscription.activite.structure not in self.request.user.structures.all():
            return False
        return True

    def Get_objets_supprimables(self, objet=None):
        liste_conso_supprimables = []
        for conso in Consommation.objects.filter(inscription=objet):
            if conso.forfait == 2 and conso.etat == "reservation":
                liste_conso_supprimables.append(conso)
        return liste_conso_supprimables

    def Avant_suppression(self, objet=None):
        """ Suppression des conso forfait supprimables """
        liste_conso = Consommation.objects.filter(inscription=objet)
        nbre_conso_forfait = 0
        for conso in liste_conso:
            if conso.forfait == 2 and conso.etat == "reservation":
                nbre_conso_forfait += 1

        # Si ce sont toutes des conso associées à un forfait supprimable
        if nbre_conso_forfait == len(liste_conso):
            for conso in liste_conso:
                conso.delete()

        # Supprime les prestations associées
        for prestation in Prestation.objects.filter(famille=objet.famille, individu=objet.individu, activite=objet.activite, forfait=2):
            prestation.delete()

        return True

    def Check_protections(self, objet=None):
        protections = []

        nbre_prestations_facturees = Prestation.objects.filter(famille=objet.famille, individu=objet.individu, activite=objet.activite, facture__isnull=False).count()
        if nbre_prestations_facturees:
            protections.append("Vous ne pouvez pas supprimer cette inscription car %s prestations associées sont déjà facturées." % nbre_prestations_facturees)

        nbre_prestations = Prestation.objects.filter(famille=objet.famille, individu=objet.individu, activite=objet.activite).exclude(forfait=2).count()
        if nbre_prestations:
            protections.append("Vous ne pouvez pas supprimer cette inscription car %s prestations sont déjà associées." % nbre_prestations)

        return protections
