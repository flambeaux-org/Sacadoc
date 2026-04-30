# -*- coding: utf-8 -*-

from django.urls import reverse_lazy
from core.views.mydatatableview import MyDatatable, columns
from core.views import crud
from core.models import Registre
from parametrage.forms.config_registre import Formulaire

class Page(crud.Page):
    model = Registre
    url_liste = "config_registre_liste"
    url_ajouter = "config_registre_ajouter"
    url_modifier = "config_registre_modifier"
    url_supprimer = "config_registre_supprimer"
    description_liste = "Voici ci-dessous la liste des registres de présence."
    description_saisie = "Saisissez toutes les informations et cliquez sur le bouton Enregistrer."
    objet_singulier = "un registre"
    objet_pluriel = "des registres"
    boutons_liste = [
        {"label": "Ajouter", "classe": "btn btn-success", "href": reverse_lazy(url_ajouter), "icone": "fa fa-plus"},
    ]

class Liste(Page, crud.Liste):
    def get_queryset(self):
        # On filtre par la structure courante si nécessaire (souvent via self.request.user.structure)
        return Registre.objects.filter(self.Get_filtres("Q"))

    def get_context_data(self, **kwargs):
        context = super(Liste, self).get_context_data(**kwargs)
        context['impression_introduction'] = ""
        context['impression_conclusion'] = ""
        context['afficher_menu_brothers'] = True
        return context

    class datatable_class(MyDatatable):
        # Colonnes adaptées au modèle Registre
        activite = columns.TextColumn("Activité", source="activite__nom")
        type_date = columns.TextColumn("Type de date", source="get_type_date_display")
        actions = columns.TextColumn("Actions", sources=None, processor='Get_actions_standard')

        class Meta:
            structure_template = MyDatatable.structure_template
            columns = ["nom","activite", "type_date", "actions"]
            ordering = ["activite"]


class Ajouter(Page, crud.Ajouter):
    form_class = Formulaire

    def get_form_kwargs(self):
        kwargs = super(Ajouter, self).get_form_kwargs()
        kwargs["idregistre"] = None
        return kwargs

    def form_valid(self, form):
        # get structure from activite id
        form.instance.structure_id = form.cleaned_data["activite"].structure_id

        return super(Ajouter, self).form_valid(form)


class Modifier(Page, crud.Modifier):
    form_class = Formulaire

    def get_form_kwargs(self, **kwargs):
        """ Envoie l'idregistre au formulaire si nécessaire """
        form_kwargs = super(Modifier, self).get_form_kwargs(**kwargs)
        # Utilise l'id du registre actuel
        form_kwargs["idregistre"] = self.kwargs.get('pk', None)
        return form_kwargs


class Supprimer(Page, crud.Supprimer):
    pass