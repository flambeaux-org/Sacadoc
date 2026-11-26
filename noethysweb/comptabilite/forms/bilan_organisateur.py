# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django import forms
from django.db.models import Q
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Fieldset
from crispy_forms.bootstrap import Field
from core.forms.select2 import Select2MultipleWidget
from core.forms.base import FormulaireBase
from core.utils import utils_dates
from core.widgets import DateRangePickerWidget
from core.models import ComptaCategorie, Structure
import datetime


class Formulaire(FormulaireBase, forms.Form):
    structures = forms.ModelMultipleChoiceField(
        label="Structures", queryset=Structure.objects.none(),
        widget=Select2MultipleWidget(), required=True,
        help_text="Chaque structure sélectionnée apparaît en colonne : tous ses comptes "
                  "(caisse et compte courant) sont agrégés. Les comptes sans structure "
                  "sont ignorés, leur périmètre d'analyse étant indéterminé.")
    categories = forms.ModelMultipleChoiceField(
        label="Catégories détaillées", queryset=ComptaCategorie.objects.none(),
        widget=Select2MultipleWidget(), required=False,
        help_text="Catégories à détailler ligne par ligne. Le résultat du projet est toujours affiché.")
    periode = forms.CharField(label="Période", required=True,
                              widget=DateRangePickerWidget(attrs={"afficher_check": False}))

    def __init__(self, *args, **kwargs):
        super(Formulaire, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = 'form_parametres'
        self.helper.form_method = 'post'

        condition_structure = Q(structure__in=self.request.user.structures.all()) | Q(structure__isnull=True)
        self.fields["structures"].queryset = self.request.user.structures.order_by("nom")
        self.fields["categories"].queryset = ComptaCategorie.objects.filter(condition_structure).order_by("type", "nom")

        # Période par défaut : année civile en cours
        today = datetime.date.today()
        self.fields["periode"].initial = "%s;%s" % (datetime.date(today.year, 1, 1), datetime.date(today.year, 12, 31))

        self.helper.layout = Layout(
            Fieldset("Sélection des paramètres",
                Field("structures"),
                Field("categories"),
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
