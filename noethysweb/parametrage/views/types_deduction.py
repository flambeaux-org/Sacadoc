# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django.urls import reverse_lazy, reverse
from django.db.models import Count
from core.views.mydatatableview import MyDatatable, columns, helpers
from core.views import crud
from core.utils import utils_dates
from core.models import TypeDeduction
from parametrage.forms.types_deduction import Formulaire


class Page(crud.Page):
    model = TypeDeduction
    url_liste = "types_deductions_liste"
    url_ajouter = "types_deductions_ajouter"
    url_modifier = "types_deductions_modifier"
    url_supprimer = "types_deduction_supprimer"
    description_liste = "Voici ci-dessous la liste des types de déductions."
    description_saisie = "Saisissez toutes les informations concernant la déduction à saisir et cliquez sur le bouton Enregistrer."
    objet_singulier = "un type de déduction"
    objet_pluriel = "des types de déductions"
    boutons_liste = [
        {"label": "Ajouter", "classe": "btn btn-success", "href": reverse_lazy(url_ajouter), "icone": "fa fa-plus"},
    ]


class Liste(Page, crud.Liste):
    model = TypeDeduction

    def get_queryset(self):
        return TypeDeduction.objects.filter(
            self.Get_filtres("Q"), self.Get_condition_structure()
        ).annotate(
            nbre_individus=Count('deduction')
        )
    def get_context_data(self, **kwargs):
        context = super(Liste, self).get_context_data(**kwargs)
        context['impression_introduction'] = ""
        context['impression_conclusion'] = ""
        context['afficher_menu_brothers'] = True
        return context

    class datatable_class(MyDatatable):
        filtres = ["idtype_deduction", "nom"]
        actions = columns.TextColumn("Actions", sources=None, processor='Get_actions_standard')
        structure = columns.DisplayColumn("Structure", sources="structure", processor='Get_structure')
        nbre_individus = columns.TextColumn("Individus associés", sources="nbre_individus")

        class Meta:
            structure_template = MyDatatable.structure_template
            columns = ["idtype_deduction", "nom", "structure", "nbre_individus"]
            ordering = ["nom"]
            processors = {
            }

        def Get_structure(self, instance, **kwargs):
            return "Mouvement" if instance.structure_id is None else str(instance.structure)


class Ajouter(Page, crud.Ajouter):
    form_class = Formulaire

class Modifier(Page, crud.Modifier):
    form_class = Formulaire

class Supprimer(Page, crud.Supprimer):
    form_class = Formulaire