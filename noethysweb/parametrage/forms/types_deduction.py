# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django import forms
from django.forms import ModelForm
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, HTML, Fieldset
from crispy_forms.bootstrap import Field
from core.forms.base import FormulaireBase
from core.utils.utils_commandes import Commandes
from core.models import TypeDeduction
from core.widgets import DatePickerWidget


class Formulaire(FormulaireBase, ModelForm):
    class Meta:
        model = TypeDeduction
        fields = "__all__"
        widgets = {
        }

    def __init__(self, *args, **kwargs):
        super(Formulaire, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = 'types_allergies_form'
        self.helper.form_method = 'post'

        self.helper.form_class = 'form-horizontal'
        self.helper.label_class = 'col-md-2'
        self.helper.field_class = 'col-md-10'

        # Une déduction sans structure est un mouvement valable pour toutes les structures
        # Seuls les utilisateurs Staff sont autorisés à créer un mouvement sans structure
        if self.request and not self.request.user.is_staff:
            self.fields['structure'].required = True
            self.fields['structure'].empty_label = None
        else:
            self.fields['structure'].required = False
            self.fields['structure'].empty_label = "Mouvement (toutes les structures)"

        # Affichage
        self.helper.layout = Layout(
            Commandes(annuler_url="{% url 'types_deductions_liste' %}"),
            Fieldset("Généralités",
                Field('nom'),
                     Field('structure'),
                     Field('remb'),
            ),
        )

