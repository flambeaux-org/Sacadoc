# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.
import json, datetime
from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, HTML, Fieldset
from crispy_forms.bootstrap import Field
from core.utils.utils_commandes import Commandes
from core.widgets import SelectionActivitesWidget, DateRangePickerWidget
from core.forms.base import FormulaireBase
from core.models import ComptaOperation, Structure, CompteBancaire, ModeReglement
from core.widgets import SelectionActivitesWidget, DateRangePickerWidget, DatePickerWidget
from core.forms.select2 import Select2MultipleWidget
from django.db.models import Q
from core.utils import utils_texte
from core.forms.select2 import Select2Widget


class Formulaire(FormulaireBase, forms.Form):
    date = forms.DateField(label="Date du virement de régularisation", required=True, widget=DatePickerWidget())
    operations = forms.ModelMultipleChoiceField(
        label="Opérations concernées",
        queryset=ComptaOperation.objects.none(),
        widget=Select2MultipleWidget(),
        required=True
        )
    mode_id = forms.ModelChoiceField(
        queryset=ModeReglement.objects.all(),
        required=True,
        label="Mode de règlement"
    )
    def __init__(self, *args, **kwargs):
        super(Formulaire, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = 'form_parametres'
        self.helper.form_method = 'post'
        self.helper.form_class = 'form-horizontal'
        self.helper.label_class = 'col-md-2'
        self.helper.field_class = 'col-md-10'
        self.fields['operations'].queryset = ComptaOperation.objects.filter(
            compte__structure__in=self.request.user.structures.all(),
            avance__isnull=False,
            regul_avance=False,
            remb_avance__in=[None, 0]
        )
        self.fields['operations'].label_from_instance = self.label_from_instance
        self.fields['date'].initial = datetime.date.today()

        self.helper.layout = Layout(
            Commandes(annuler_url="{% url 'operations_tresorerie_liste' %}", enregistrer=False, ajouter=False,
                      commandes_principales=[HTML(
                          """<a type='button' class="btn btn-primary margin-r-5" onclick="exporter()" title="Valider la régularisation"><i class=' margin-r-5'></i>Valider la régularisation</a>"""),
                      ]),
            Field("date"),
            HTML(                "<div id='total_operations' style='margin-bottom:20px; font-weight:bold; text-align:center;'>Montant total : 0,00 €</div>"),
            Field("operations"),
            Field("mode_id")
        )

    @staticmethod
    def label_from_instance(instance):
        date_str = instance.date.strftime('%d/%m/%Y') if instance.date else ""
        avance_nom = instance.avance.nom if instance.avance else "N/A"
        montant = instance.montant if instance.montant is not None else 0.0
        type_str = instance.type  # "credit" ou "debit"
        montant_str = utils_texte.Formate_montant(montant)
        return f"{instance.libelle} payé par {avance_nom} le {date_str} - {montant_str} ({type_str})"
