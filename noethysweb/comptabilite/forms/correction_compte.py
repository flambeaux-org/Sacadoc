# -*- coding: utf-8 -*-

from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Fieldset, Field, HTML
from core.forms.base import FormulaireBase
from core.models import ComptaOperation, CompteBancaire
from django.db.models import Q
from core.utils.utils_commandes import Commandes


class Formulaire(FormulaireBase, forms.Form):
    # Utilisation d'un Select standard pour afficher tous les choix
    operation = forms.ModelChoiceField(
        label="Sélectionner l'opération",
        queryset=ComptaOperation.objects.none(),
        widget=forms.Select(attrs={'class': 'form-control'}),
        required=True
    )

    nouveau_compte = forms.ModelChoiceField(
        label="Nouveau compte à affecter",
        queryset=CompteBancaire.objects.none(),
        widget=forms.Select(attrs={'class': 'form-control'}),
        required=True
    )

    def __init__(self, *args, **kwargs):
        super(Formulaire, self).__init__(*args, **kwargs)

        # Filtrage des comptes accessibles selon l'utilisateur
        comptes_qs = CompteBancaire.objects.filter(
            Q(structure__in=self.request.user.structures.all()) | Q(structure__isnull=True)
        ).order_by("nom")

        # Chargement des opérations avec le compte lié (pour éviter trop de requêtes SQL)
        operations_qs = ComptaOperation.objects.filter(
            compte__in=comptes_qs
        ).select_related('compte').order_by('-date')

        # Application des querysets
        self.fields["nouveau_compte"].queryset = comptes_qs
        self.fields["operation"].queryset = operations_qs

        # Personnalisation de l'affichage : "Date - Libellé (Compte actuel) - Montant"
        self.fields["operation"].label_from_instance = lambda obj: \
            f"{obj.date.strftime('%d/%m/%Y')} - {obj.libelle[:40]} ({obj.compte.nom}) - {obj.montant}€"

        # Configuration Crispy Forms pour Noethysweb
        self.helper = FormHelper()
        self.helper.form_class = 'form-horizontal'
        self.helper.label_class = 'col-md-3'
        self.helper.field_class = 'col-md-9'

        self.helper.layout = Layout(
            Fieldset("Correction d'affectation",
                     Field("operation"),
                     HTML("<hr>"),
                     Field("nouveau_compte"),
                     ),
            # Bouton enregistrer standard de Noethys
            Commandes(annuler_url="{% url 'comptabilite_toc' %}", enregistrer=True, aide=False, ajouter=False)
        )