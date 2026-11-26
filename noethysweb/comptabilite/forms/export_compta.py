# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django import forms
from django.db.models import Q
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, HTML, Fieldset
from crispy_forms.bootstrap import Field
from django_select2.forms import Select2Widget
from core.utils.utils_commandes import Commandes
from core.utils import utils_dates
from core.widgets import DateRangePickerWidget
from core.forms.base import FormulaireBase
from core.models import CompteBancaire
import datetime


class Formulaire(FormulaireBase, forms.Form):
    compte = forms.ModelChoiceField(label="Compte", widget=Select2Widget({"lang": "fr", "data-width": "100%", "data-minimum-input-length": 0}), queryset=CompteBancaire.objects.none(), required=True)
    periode = forms.CharField(label="Période", required=True, widget=DateRangePickerWidget(attrs={"afficher_check": False}))

    def __init__(self, *args, **kwargs):
        super(Formulaire, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = 'form_parametres'
        self.helper.form_method = 'post'

        self.helper.form_class = 'form-horizontal'
        self.helper.label_class = 'col-md-2'
        self.helper.field_class = 'col-md-10'

        self.fields["compte"].queryset = CompteBancaire.objects.filter(Q(structure__in=self.request.user.structures.all()) | Q(structure__isnull=True)).order_by("nom")

        # Période par défaut : année civile en cours
        today = datetime.date.today()
        self.fields["periode"].initial = "%s;%s" % (datetime.date(today.year, 1, 1), datetime.date(today.year, 12, 31))

        self.helper.layout = Layout(
            Commandes(annuler_url="{% url 'comptabilite_toc' %}", enregistrer=False, ajouter=False,
                      commandes_principales=[HTML(
                          """<button type="submit" form="form_parametres" class="btn btn-primary margin-r-5" title="Génération du fichier Excel"><i class='fa fa-file-excel-o margin-r-5'></i>Générer le fichier Excel</button>"""),
                      ]),
            Fieldset("Sélection des paramètres",
                Field("compte"),
                Field("periode"),
            ),
        )

    def clean(self):
        cleaned_data = super(Formulaire, self).clean()
        periode = cleaned_data.get("periode")
        if not periode or ";" not in periode:
            self.add_error("periode", "Vous devez sélectionner une période valide")
            return cleaned_data

        date_debut = utils_dates.ConvertDateENGtoDate(periode.split(";")[0])
        date_fin = utils_dates.ConvertDateENGtoDate(periode.split(";")[1])
        if not date_debut or not date_fin:
            self.add_error("periode", "Vous devez sélectionner une période valide")
            return cleaned_data
        if date_debut > date_fin:
            self.add_error("periode", "La date de début doit être antérieure à la date de fin")
            return cleaned_data

        cleaned_data["date_debut"] = date_debut
        cleaned_data["date_fin"] = date_fin
        return cleaned_data
