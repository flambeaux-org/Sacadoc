# -*- coding: utf-8 -*-
# Copyright (c) 2019-2021 Ivan LUCAS.
# Noethysweb, application de gestion multi-activités.
# Distribué sous licence GNU GPL.

from django.urls import reverse_lazy, reverse
from core.views.mydatatableview import MyDatatable, columns, helpers
from core.views import crud
from core.models import Piece, Activite, Inscription, Famille, Individu
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
import zipfile
from io import BytesIO
from django.http import HttpResponse
from django.views import View
from django.shortcuts import get_object_or_404
from core.models import Piece
from django.db.models import Q


class Page(crud.Page):
    model = Piece
    url_liste = "liste_pieces_fournies"
    description_liste = "Voici ci-dessous la liste des pièces fournies."
    objet_singulier = "une pièce fournie"
    objet_pluriel = "des pièces fournies"
    url_supprimer_plusieurs = "pieces_supprimer_plusieurs"


class Liste(Page, crud.Liste):
    template_name = "individus/liste_pieces_fournies.html"
    search_fields = [
        "famille__nom",
        "individu__prenom",
        "type_piece__nom",
        "titre"
    ]

    def get_queryset(self):
        activites_autorisees = Activite.objects.filter(structure__in=self.request.user.structures.all())
        inscriptions_accessibles = Inscription.objects.filter(activite__in=activites_autorisees)
        individus_inscrits = Individu.objects.filter(idindividu__in=inscriptions_accessibles.values('individu'))
        return Piece.objects.select_related("famille", "individu", "type_piece").filter(individu__in=individus_inscrits).filter(self.Get_filtres("Q"))

    def get_context_data(self, **kwargs):
        context = super(Liste, self).get_context_data(**kwargs)
        context['impression_introduction'] = ""
        context['impression_conclusion'] = ""
        context['active_checkbox'] = True
        context['show_download_button'] = True
        context["bouton_supprimer"] = False
        return context

    class datatable_class(MyDatatable):
        filtres = ["fpresent:famille", "ipresent:individu", "fscolarise:famille", "iscolarise:individu", "famille__nom", "individu__nom", "type_piece__nom"]
        actions = columns.TextColumn("Actions", sources=None, processor='Get_actions_speciales')
        check = columns.CheckBoxSelectColumn(label="")

        class Meta:
            structure_template = MyDatatable.structure_template
            columns = ['check', "individu", "date_debut", "date_fin", "type_piece", "famille", "actions"]
            processors = {
                'date_debut': helpers.format_date('%d/%m/%Y'),
                'date_fin': helpers.format_date('%d/%m/%Y'),
                'type_piece': 'format_type_piece',
            }
            ordering = ["date_debut"]

        def format_type_piece(self, instance, *args, **kwargs):
            result = instance.type_piece.nom if instance.type_piece else f"Autre : {instance.titre}"
            return result

        def Get_actions_speciales(self, instance, *args, **kwargs):
            document_url = f'/media/{instance.document}'

            # Récupération des informations pertinentes pour le titre du document
            type_piece = instance.type_piece.nom if instance.type_piece else instance.titre
            individu = instance.individu.prenom if instance.individu else ""
            famille = instance.individu.nom if instance.famille else ""

            # Construction du titre du document pour le lien de téléchargement
            titre_document = f"{type_piece} - {individu} {famille}"

            # Construction du lien de téléchargement avec l'icône et l'attribut download
            bouton_telecharger = f'<a href="{document_url}" class="btn btn-default btn-xs" download="{titre_document}"><i class="fa fa-download"></i></a>'
            bouton_ouvrir = f'<a href="{document_url}" class="btn btn-default btn-xs" target="_blank"><i class="fa fa-eye"></i></a>'

            html = [
                bouton_ouvrir,
                bouton_telecharger,
                self.Create_bouton_modifier(url=reverse("famille_pieces_modifier", kwargs={"idfamille": instance.famille.pk, "pk": instance.pk})),
            ]

            return self.Create_boutons_actions(html)


class Supprimer_plusieurs(Page, crud.Telecharger_plusieurs):
    pass
