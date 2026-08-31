# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import os, io
from django.conf import settings
from django.urls import reverse_lazy, reverse
from django.http import JsonResponse, HttpResponse
from datatableview.views import MultipleDatatableView
from core.views.mydatatableview import MyDatatable, columns, helpers
from core.views import crud
from core.models import Individu, Vaccin, Information, Medecin, TypeMaladie, Vaccin, Rattachement
from fiche_individu.forms.individu_information import Formulaire as Formulaire_information
from fiche_individu.forms.individu_vaccin import Formulaire as Formulaire_vaccin
from fiche_individu.forms.individu_medecin import Formulaire as Formulaire_medecin
from fiche_individu.views.individu import Onglet
from individus.utils import utils_vaccinations, utils_impression_renseignements, utils_impression_renseignements_pieces


def Telecharger_pdf_medical(request, idfamille, idindividu):
    """ Génère un PDF complet des informations médicales de l'individu, avec les pièces jointes """
    from pypdf import PdfReader, PdfWriter
    from reportlab.lib.pagesizes import A4

    individu = Individu.objects.get(pk=idindividu)
    rattachement = Rattachement.objects.filter(individu=individu, famille_id=idfamille).first()
    if not rattachement:
        return HttpResponse("Rattachement introuvable", status=404)

    impression = utils_impression_renseignements.Impression(
        titre="Fiche médicale",
        dict_donnees={"rattachements": [rattachement.pk], "tri": "nom", "mode_condense": False},
        request=request)
    if impression.erreurs:
        return HttpResponse(impression.erreurs[0], status=401)

    largeur, hauteur = A4
    writer_final = PdfWriter()

    nom_fichier_virtuel = impression.Get_nom_fichier()
    chemin_pdf = os.path.normpath(os.path.join(settings.MEDIA_ROOT, nom_fichier_virtuel.strip("/")))
    if os.path.exists(chemin_pdf):
        with open(chemin_pdf, 'rb') as fichier:
            for page in PdfReader(fichier).pages:
                writer_final.add_page(page)
        try:
            os.remove(chemin_pdf)
        except Exception:
            pass

    # Ajout des pièces jointes attachées aux informations médicales
    informations_avec_document = Information.objects.filter(individu=individu).exclude(document="").exclude(document__isnull=True)
    for information in informations_avec_document:
        try:
            chemin_information = information.document.path
            if os.path.exists(chemin_information):
                reader_pj = utils_impression_renseignements_pieces.formater_information_jointe(information, individu, largeur, hauteur)
                for page in reader_pj.pages:
                    writer_final.add_page(page)
            else:
                writer_final.add_page(utils_impression_renseignements_pieces.generer_page_erreur(
                    f"Document absent : {information.intitule.upper()}", largeur, hauteur))
        except Exception:
            writer_final.add_page(utils_impression_renseignements_pieces.generer_page_erreur(
                f"Erreur de lecture du document : {information.intitule.upper()}", largeur, hauteur))

    buffer_final = io.BytesIO()
    writer_final.write(buffer_final)
    response = HttpResponse(buffer_final.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = "attachment; filename=\"Fiche_medicale_%s.pdf\"" % individu.Get_nom().replace(" ", "_")
    return response


def Select_medecin(request):
    # Récupération des données du formulaire
    idindividu = int(request.POST.get("idindividu"))
    idmedecin = request.POST.get("medecin")

    # Enregistrement du médecin
    if idmedecin == "":
        medecin = None
    else:
        medecin = Medecin.objects.get(pk=idmedecin)

    individu = Individu.objects.get(pk=idindividu)
    individu.medecin = medecin
    individu.save()

    return JsonResponse({"success": True})

def Deselect_medecin(request):
    # Récupération des données du formulaire
    idindividu = int(request.POST.get("idindividu"))

    # Suppression du médecin
    individu = Individu.objects.get(pk=idindividu)
    individu.medecin = None
    individu.save()

    return JsonResponse({"success": True})


class Page(Onglet):
    url_liste = "individu_medical_liste"
    description_saisie = "Saisissez toutes les informations et cliquez sur le bouton Enregistrer."
    objet_singulier = ""
    objet_pluriel = ""

    def get_context_data(self, **kwargs):
        """ Context data spécial pour onglet """
        context = super(Page, self).get_context_data(**kwargs)
        context['box_titre'] = "Médical"
        context['onglet_actif'] = "medical"
        context['boutons_liste_informations'] = [
            {"label": "Ajouter", "classe": "btn btn-success", "href": reverse_lazy("individu_informations_ajouter", kwargs={'idindividu': self.Get_idindividu(), 'idfamille': self.Get_idfamille()}), "icone": "fa fa-plus"},
        ]
        context['boutons_liste_vaccinations'] = [
            {"label": "Ajouter", "classe": "btn btn-success", "href": reverse_lazy("individu_vaccinations_ajouter", kwargs={'idindividu': self.Get_idindividu(), 'idfamille': self.Get_idfamille()}), "icone": "fa fa-plus"},
        ]
        context['form_selection_medecin'] = Formulaire_medecin(idindividu=self.Get_idindividu())
        context['vaccins_obligatoires'] = utils_vaccinations.Get_vaccins_obligatoires_individu(individu=context["individu"])
        context['pieces_manquantes'] = [{"label": "Fiche sanitaire", "valide": True}, {"label": "Fiche famille", "valide": False}]
        context['pieces_medicales'] = Information.objects.filter(individu=self.Get_idindividu()).exclude(document="").exclude(document__isnull=True)
        context['url_telecharger_pdf_medical'] = reverse_lazy("individu_medical_telecharger_pdf", kwargs={'idfamille': self.Get_idfamille(), 'idindividu': self.Get_idindividu()})
        return context

    def get_form_kwargs(self, **kwargs):
        """ Envoie l'idindividu au formulaire """
        form_kwargs = super(Page, self).get_form_kwargs(**kwargs)
        form_kwargs["idindividu"] = self.Get_idindividu()
        return form_kwargs

    def get_success_url(self):
        """ Renvoie vers la liste après le formulaire """
        url = self.url_liste
        if "SaveAndNew" in self.request.POST and self.request.POST.get("page") == "info_medicale":
            url = "individu_informations_ajouter"
        if "SaveAndNew" in self.request.POST and self.request.POST.get("page") == "vaccin":
            url = "individu_vaccinations_ajouter"
        return reverse_lazy(url, kwargs={'idindividu': self.Get_idindividu(), 'idfamille': self.kwargs.get('idfamille', None)})



class Liste(Page, MultipleDatatableView):
    template_name = "fiche_individu/individu_medical.html"


    class informations_datatable_class(MyDatatable):
        actions = columns.TextColumn("Actions", sources=None, processor='Get_actions_speciales')
        intitule = columns.TextColumn("Intitulé", processor="Get_intitule")
        categorie = columns.CompoundColumn("Catégorie", sources=['categorie__nom'])
        piece_jointe = columns.TextColumn("Pièce jointe", sources=None, processor="Get_piece_jointe")

        class Meta:
            model = Information
            structure_template = MyDatatable.structure_template
            columns = ['categorie', 'intitule', 'piece_jointe']
            ordering = ['categorie', 'intitule']
            footer = False

        def Get_intitule(self, instance, *args, **kwargs):
            return instance.intitule

        def Get_piece_jointe(self, instance, *args, **kwargs):
            if instance.document:
                return "<a href='%s' target='_blank'><i class='fa fa-paperclip'></i> Consulter</a>" % instance.document.url
            return ""

        def Get_actions_speciales(self, instance, *args, **kwargs):
            """ Inclut l'idindividu dans les boutons d'actions """
            # Récupération idindividu et idfamille
            kwargs = kwargs["view"].kwargs
            # Ajoute l'id de la ligne
            kwargs["pk"] = instance.pk
            html = [
                self.Create_bouton_modifier(url=reverse("individu_informations_modifier", kwargs=kwargs)),
                self.Create_bouton_supprimer(url=reverse("individu_informations_supprimer", kwargs=kwargs)),
            ]
            return self.Create_boutons_actions(html)


    class vaccins_datatable_class(MyDatatable):
        actions = columns.TextColumn("Actions", sources=None, processor='Get_actions_speciales')

        class Meta:
            model = Vaccin
            structure_template = MyDatatable.structure_template
            columns = ['date', 'type_vaccin']
            processors = {
                'date': helpers.format_date('%d/%m/%Y'),
            }
            ordering = ['date']
            footer = False

        def Get_actions_speciales(self, instance, *args, **kwargs):
            """ Inclut l'idindividu dans les boutons d'actions """
            # Récupération idindividu et idfamille
            kwargs = kwargs["view"].kwargs
            # Ajoute l'id de la ligne
            kwargs["pk"] = instance.pk
            html = [
                self.Create_bouton_modifier(url=reverse("individu_vaccinations_modifier", kwargs=kwargs)),
                self.Create_bouton_supprimer(url=reverse("individu_vaccinations_supprimer", kwargs=kwargs)),
            ]
            return self.Create_boutons_actions(html)

    datatable_classes = {
        'informations': informations_datatable_class,
        'vaccins': vaccins_datatable_class,
    }

    def get_informations_datatable_queryset(self):
        return Information.objects.select_related("categorie").filter(individu=self.Get_idindividu())

    def get_vaccins_datatable_queryset(self):
        return Vaccin.objects.select_related("type_vaccin").filter(individu=self.Get_idindividu())

    def get_datatables(self, only=None):
        datatables = super(Liste, self).get_datatables(only)
        return datatables





class Ajouter_information(Page, crud.Ajouter):
    form_class = Formulaire_information
    model = Information
    template_name = "fiche_individu/individu_edit.html"

    def get_context_data(self, **kwargs):
        context = super(Page, self).get_context_data(**kwargs)
        context['box_titre'] = "Informations personnelles"
        context['onglet_actif'] = "medical"
        return context


class Modifier_information(Page, crud.Modifier):
    form_class = Formulaire_information
    model = Information
    template_name = "fiche_individu/individu_edit.html"

    def get_context_data(self, **kwargs):
        context = super(Page, self).get_context_data(**kwargs)
        context['box_titre'] = "Informations personnelles"
        context['onglet_actif'] = "medical"
        return context


class Supprimer_information(Page, crud.Supprimer):
    form_class = Formulaire_information
    model = Information
    template_name = "fiche_individu/individu_delete.html"

    def get_context_data(self, **kwargs):
        context = super(Page, self).get_context_data(**kwargs)
        context['box_titre'] = "Informations personnelles"
        context['onglet_actif'] = "medical"
        return context


class Ajouter_vaccin(Page, crud.Ajouter):
    form_class = Formulaire_vaccin
    model = Vaccin
    template_name = "fiche_individu/individu_edit.html"

    def get_context_data(self, **kwargs):
        context = super(Page, self).get_context_data(**kwargs)
        context['box_titre'] = "Vaccinations"
        context['onglet_actif'] = "medical"
        return context


class Modifier_vaccin(Page, crud.Modifier):
    form_class = Formulaire_vaccin
    model = Vaccin
    template_name = "fiche_individu/individu_edit.html"

    def get_context_data(self, **kwargs):
        context = super(Page, self).get_context_data(**kwargs)
        context['box_titre'] = "Vaccinations"
        context['onglet_actif'] = "medical"
        return context


class Supprimer_vaccin(Page, crud.Supprimer):
    form_class = Formulaire_vaccin
    model = Vaccin
    template_name = "fiche_individu/individu_delete.html"

    def get_context_data(self, **kwargs):
        context = super(Page, self).get_context_data(**kwargs)
        context['box_titre'] = "Vaccinations"
        context['onglet_actif'] = "medical"
        return context
