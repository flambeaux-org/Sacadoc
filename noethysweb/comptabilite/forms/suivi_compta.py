# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django import forms
from django.db.models import Q
from django_select2.forms import ModelSelect2Widget
from core.forms.select2 import Select2MultipleWidget
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout
from crispy_forms.bootstrap import Field
from datetime import date
from core.models import Structure
from core.forms.base import FormulaireBase
from core.widgets import DateRangePickerWidget

class Formulaire(FormulaireBase, forms.Form):
    #  L'analyse porte sur une structure et non sur un compte : les finances d'un camp
    #  se répartissent souvent entre une caisse et un compte courant, et les règlements
    #  encaissés par l'organisateur se rattachent à la structure, pas à un compte.
    structures = forms.ModelMultipleChoiceField(
        label="Structures",
        queryset=Structure.objects.none(),
        widget=Select2MultipleWidget(),
        required=True,
        help_text="Tous les comptes de la structure (caisse, compte courant...) sont analysés ensemble.",
        )
    periode = forms.CharField(label="Période", required=True,
                              widget=DateRangePickerWidget(attrs={"afficher_check": False}))

    def __init__(self, *args, **kwargs):
        super(Formulaire, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = 'form_parametres'
        self.helper.form_method = 'post'

        self.fields["structures"].queryset = self.request.user.structures.order_by("nom")

        # Par défaut : tout l'historique, pour conserver le comportement habituel
        self.fields["periode"].initial = "%s;%s" % (date(1900, 1, 1), date.today())

        self.helper.layout = Layout(
            Field("structures"),
            Field("periode"),
        )
