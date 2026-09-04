# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django.urls import reverse_lazy, reverse
from core.views.mydatatableview import MyDatatable, columns, helpers
from core.views import crud
from core.models import Famille, Individu, Piece, TypePiece, Inscription, Rattachement, Activite
from fiche_famille.forms.famille_pieces import Formulaire
from fiche_famille.views.famille import Onglet
import datetime
from django.views.generic.base import RedirectView
from django.contrib import messages
from individus.utils import utils_pieces_manquantes
from django.db.models import Q
from django.shortcuts import render, redirect



class Page(Onglet):
    model = Piece
    url_liste = "famille_pieces_liste"
    url_ajouter = "famille_pieces_ajouter"
    url_modifier = "famille_pieces_modifier"
    url_supprimer = "famille_pieces_supprimer"
    url_supprimer_plusieurs = "famille_pieces_supprimer_plusieurs"
    description_liste = "Saisissez ici les pièces de la famille. Les pièces d'un enfant sont uniquement visibles si l'enfant est inscrit à l'une de vos activités."
    description_saisie = "Saisissez toutes les informations concernant la pièce et cliquez sur le bouton Enregistrer."
    objet_singulier = "une pièce"
    objet_pluriel = "des pièces"

    def get_context_data(self, **kwargs):
        """ Context data spécial pour onglet """
        context = super(Page, self).get_context_data(**kwargs)
        if not hasattr(self, "verbe_action"):
            context['box_titre'] = "Pièces"
        context['onglet_actif'] = "pieces"
        context['pieces_fournir'] = utils_pieces_manquantes.Get_pieces_manquantes(famille=context['famille'], utilisateur=self.request.user)
        context['boutons_liste'] = [
            {"label": "Ajouter", "classe": "btn btn-success", "href": reverse_lazy(self.url_ajouter, kwargs={'idfamille': self.kwargs.get('idfamille', None)}), "icone": "fa fa-plus"},
        ]
        # Ajout l'idfamille à l'URL de suppression groupée
        context['url_supprimer_plusieurs'] = reverse_lazy(self.url_supprimer_plusieurs, kwargs={'idfamille': self.kwargs.get('idfamille', None), "listepk": "xxx"})
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
    model = Piece
    template_name = "fiche_famille/famille_pieces.html"

    def get_queryset(self):
        structures = self.request.user.structures.all()
        activites_accessibles = Activite.objects.filter(structure__in=self.request.user.structures.all())
        inscriptions_accessibles = Inscription.objects.filter(activite__in=activites_accessibles, famille_id=self.Get_idfamille())
        individus_rattaches = Individu.objects.filter(idindividu__in=Rattachement.objects.filter(categorie=1, famille_id=self.Get_idfamille()).values('individu'))
        individus_inscrits = Individu.objects.filter(
            Q(idindividu__in=inscriptions_accessibles.values('individu')) |
            Q(idindividu__in=Rattachement.objects.filter(categorie=1, famille_id=self.Get_idfamille()).values('individu'))).distinct()
        liste = Piece.objects.select_related('individu', 'type_piece').filter(
            Q(individu__in=individus_inscrits) | Q(individu__isnull=True, famille_id=self.Get_idfamille())
        )
        return liste

    def get_context_data(self, **kwargs):
        context = super(Liste, self).get_context_data(**kwargs)
        context['impression_introduction'] = ""
        context['impression_conclusion'] = ""
        context['active_checkbox'] = True
        return context

    class datatable_class(MyDatatable):
        filtres = ['idpiece', 'date_debut', 'date_fin', "auteur"]

        check = columns.CheckBoxSelectColumn(label="")
        actions = columns.TextColumn("Actions", sources=None, processor='Get_actions_speciales')
        nom = columns.TextColumn("Nom de la pièce", sources=None, processor='Get_nom')
        date_fin = columns.TextColumn("Date de fin", sources=["date_fin"], processor='Get_date_fin')

        class Meta:
            structure_template = MyDatatable.structure_template
            columns = ['check', 'idpiece', 'date_debut', 'individu', 'nom', "auteur","actions"]
            processors = {
                'date_debut': helpers.format_date('%d/%m/%Y'),
            }
            ordering = ['date_debut']

        def Get_nom(self, instance, **kwargs):
            return instance.Get_nom()

        def Get_date_fin(self, instance, **kwargs):
            if instance.date_fin == datetime.date(2999, 1, 1):
                return "Illimitée"
            else:
                return instance.date_fin.strftime('%d/%m/%Y')

        def Get_actions_speciales(self, instance, *args, **kwargs):
            """ Inclut l'idindividu dans les boutons d'actions """
            view = kwargs["view"]
            # Récupération idindividu et idfamille
            kwargs = view.kwargs
            # Ajoute l'id de la ligne
            kwargs["pk"] = instance.pk
            document_url = reverse('serve_piece_document', args=[instance.pk]) if instance.document else None

            # Récupération des informations pertinentes pour le titre du document
            type_piece = instance.type_piece.nom if instance.type_piece else ""
            individu = instance.individu.nom if instance.individu else ""
            famille = instance.famille.nom if instance.famille else ""

            # Construction du titre du document pour le lien de téléchargement
            titre_document = f"{type_piece} - {individu} - {famille}"

            html = [
                self.Create_bouton_modifier(url=reverse(view.url_modifier, kwargs=kwargs)),
                self.Create_bouton_supprimer(url=reverse(view.url_supprimer, kwargs=kwargs)),
            ]
            if document_url:
                bouton_telecharger = f'<a href="{document_url}" class="btn btn-default btn-xs" download="{titre_document}"><i class="fa fa-download"></i></a>'
                html += [self.Create_bouton_ouvrir(url=document_url), bouton_telecharger]
            return self.Create_boutons_actions(html)



class Ajouter(Page, crud.Ajouter):
    form_class = Formulaire
    template_name = "fiche_famille/famille_edit.html"
    def form_valid(self, form):
        # Appel de la méthode parent pour la validation
        response = super().form_valid(form)

        # Gestion des fichiers téléchargés
        documents = {
            'document1': form.cleaned_data.get('document1'),
            'document2': form.cleaned_data.get('document2'),
            'document3': form.cleaned_data.get('document3'),
            'document4': form.cleaned_data.get('document4'),
        }

        for field_name, file in documents.items():
            if file:
                Piece.objects.create(
                    titre=form.cleaned_data.get('titre'),
                    document=file,
                    famille=form.cleaned_data.get('famille'),
                    individu=form.cleaned_data.get('individu'),
                    type_piece=form.cleaned_data.get('type_piece'),
                    date_debut=form.cleaned_data.get('date_debut'),
                    date_fin=form.cleaned_data.get('date_fin'),
                    auteur=self.request.user
                )

        messages.success(self.request, "Les pièces ont été ajoutées avec succès.")
        return redirect(self.get_success_url())

class Modifier(Page, crud.Modifier):
    form_class = Formulaire
    template_name = "fiche_famille/famille_edit.html"


class Supprimer(Page, crud.Supprimer):
    template_name = "fiche_famille/famille_delete.html"


class Supprimer_plusieurs(Page, crud.Supprimer_plusieurs):
    template_name = "fiche_famille/famille_delete.html"
