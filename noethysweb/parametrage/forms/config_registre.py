# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django import forms
from django.forms import ModelForm
from core.forms.base import FormulaireBase
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Fieldset, Field, HTML
from core.utils.utils_commandes import Commandes
from core.models import Activite, Registre, Structure
from core.forms.select2 import Select2Widget
from django.core.exceptions import ValidationError
from core.widgets import DateRangePickerWidget


class Formulaire(FormulaireBase, ModelForm):
    class Meta:
        model = Registre
        fields = ["nom","activite", "structure", "type_date", "date_seance"]
        widgets = {
            "activite": Select2Widget(),
            "structure": Select2Widget(),
            "date_seance": forms.TextInput(attrs={
                'placeholder': '01/05/2024, 03/05/2024, 10/05/2024...',
                'class': 'datepicker-multiple'  # Classe pour activer un JS si dispo
            }),
        }

    def __init__(self, *args, **kwargs):
        self.idregistre = kwargs.pop("idregistre", None)
        super(Formulaire, self).__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.form_id = 'config_registre_form'
        # ... (config standard du helper) ...

        self.helper.layout = Layout(
            Commandes(annuler_url="{% url 'config_registre_liste' %}"),

            Fieldset("Paramétrage du registre",
                     Field('nom'),
                     Field('activite'),
                     Field('structure'),
                     Field('type_date', onchange="toggle_dates_field();"),

                     # Le champ de dates est affiché/masqué selon le type
                     HTML('<div id="div_liste_dates">'),
                     Field('date_seance'),
                     HTML(
                         '<p class="help-block small" style="margin-left:25%;">Saisissez les dates séparées par des virgules ou sélectionnez-les dans l\'agenda.</p>'),
                     HTML('</div>'),
                     ),

            HTML("""
                <script>
                    function toggle_dates_field() {
                        var val = $('#id_type_date').val();
                        if (val == 'LST') {
                            $('#div_liste_dates').show();
                        } else {
                            $('#div_liste_dates').hide();
                        }
                    }
                    $(document).ready(function() {
                        toggle_dates_field();

                        // Si tu veux activer un sélecteur multi-dates (Flatpickr par exemple)
                        if (typeof flatpickr !== 'undefined') {
                            flatpickr("#id_dates_seance", {
                                mode: "multiple",
                                dateFormat: "d/m/Y",
                                conjunction: ", "
                            });
                        }
                    });
                </script>
            """)
        )

    def clean(self):
        """ Validation du format des dates """
        type_date = self.cleaned_data.get("type_date")
        date_seance = self.cleaned_data.get("date_seance")
        activite = self.cleaned_data.get("activite")

        if type_date == 'LST' and not date_seance:
            raise ValidationError("Veuillez saisir au moins une date pour ce type de registre.")

        if type_date == 'ACT' and not date_seance:
            d_deb = activite.date_debut
            d_fin = activite.date_fin

            # Blocage si dates manquantes (Illimitées)
            if not d_deb or not d_fin:
                raise ValidationError(
                    "L'activité sélectionnée n'a pas de dates de début/fin définies. "
                    "Veuillez choisir 'Liste de dates' (LST) et les saisir manuellement."
                )
        return self.cleaned_data