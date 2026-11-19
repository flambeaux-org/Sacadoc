# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django.urls import reverse_lazy
from django.db.models import Q
from core.views.mydatatableview import MyDatatable, columns, helpers
from core.views import crud
from core.models import ComptaVirement, ComptaOperation, CompteBancaire
from comptabilite.forms.liste_virements import Formulaire


class Page(crud.Page):
    model = ComptaVirement
    menu_code = "virements_liste"
    url_liste = "virements_liste"
    url_ajouter = "virements_ajouter"
    url_modifier = "virements_modifier"
    url_supprimer = "virements_supprimer"
    description_liste = "Voici ci-dessous la liste des virements."
    description_saisie = "Saisissez toutes les informations concernant le virement à saisir et cliquez sur le bouton Enregistrer."
    objet_singulier = "un virement"
    objet_pluriel = "des virements"
    boutons_liste = [
        {"label": "Ajouter", "classe": "btn btn-success", "href": reverse_lazy(url_ajouter), "icone": "fa fa-plus"},
    ]

    def form_valid(self, form):
        # Sauvegarde
        self.object = form.save()

        # Création du libellé du virement
        self.object.libelle = "Virement %s -> %s" % (self.object.compte_debit.nom, self.object.compte_credit.nom)

        # Création ou modification des opérations de trésorerie
        self.object.operation_debit, created = ComptaOperation.objects.update_or_create(virement=self.object, type="debit", defaults={
            "type": "debit", "date": self.object.date, "libelle": self.object.libelle, "compte": self.object.compte_debit,
            "releve": self.object.releve_debit, "montant": self.object.montant, "virement": self.object})

        self.object.operation_credit, created = ComptaOperation.objects.update_or_create(virement=self.object, type="credit", defaults={
            "type": "credit", "date": self.object.date, "libelle": self.object.libelle, "compte": self.object.compte_credit,
            "releve": self.object.releve_credit, "montant": self.object.montant, "virement": self.object})

        # Modification du virement
        self.object.save()

        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("operations_tresorerie_liste")


class Liste(Page, crud.Liste):
    model = ComptaVirement

    def get_queryset(self):
        # Seuls les virements dont l'un des deux comptes est accessible à l'utilisateur
        comptes = CompteBancaire.objects.filter(self.Get_condition_structure())
        return ComptaVirement.objects.filter(
            Q(compte_debit__in=comptes) | Q(compte_credit__in=comptes)
        ).filter(self.Get_filtres("Q"))

    def get_context_data(self, **kwargs):
        context = super(Liste, self).get_context_data(**kwargs)
        context['impression_introduction'] = ""
        context['impression_conclusion'] = ""
        context['afficher_menu_brothers'] = True
        return context

    class datatable_class(MyDatatable):
        filtres = ["idvirement", "date", "montant", "libelle"]
        actions = columns.TextColumn("Actions", sources=None, processor='Get_actions_standard')

        class Meta:
            structure_template = MyDatatable.structure_template
            columns = ["idvirement", "date", "libelle", "montant"]
            ordering = ["date"]
            processors = {
                "date": helpers.format_date("%d/%m/%Y"),
            }


class Ajouter(Page, crud.Ajouter):
    form_class = Formulaire


class Modifier(Page, crud.Modifier):
    form_class = Formulaire


class Supprimer(Page, crud.Supprimer):
    form_class = Formulaire
