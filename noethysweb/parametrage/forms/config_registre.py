# -*- coding: utf-8 -*-
from django import forms
from django.forms import ModelForm
from core.forms.base import FormulaireBase
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Fieldset, Field, HTML
from core.utils.utils_commandes import Commandes
from core.models import Registre
from core.forms.select2 import Select2Widget
from django.core.exceptions import ValidationError


class Formulaire(FormulaireBase, ModelForm):
    class Meta:
        model = Registre
        # H-3: structure is excluded — set programmatically from the chosen activity
        fields = ["nom", "activite", "type_date", "date_seance"]
        widgets = {
            "activite": Select2Widget(),
            "date_seance": forms.TextInput(attrs={
                'placeholder': '01/05/2024, 03/05/2024, 10/05/2024...',
                'class': 'datepicker-multiple'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.idregistre = kwargs.pop("idregistre", None)
        super(Formulaire, self).__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.form_id = 'config_registre_form'

        self.helper.layout = Layout(
            Commandes(annuler_url="{% url 'config_registre_liste' %}"),

            Fieldset("Paramétrage du registre",
                     Field('nom'),
                     Field('activite'),
                     Field('type_date', onchange="toggle_dates_field();"),

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

                        if (typeof flatpickr !== 'undefined') {
                            flatpickr("#id_date_seance", {
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
        cleaned_data = super().clean()

        type_date = cleaned_data.get("type_date")
        date_seance = cleaned_data.get("date_seance")
        activite = cleaned_data.get("activite")

        if type_date == 'LST' and not date_seance:
            raise ValidationError("Veuillez saisir au moins une date pour ce type de registre.")

        if type_date == 'ACT':
            if not activite:
                raise ValidationError("Veuillez sélectionner une activité.")

            d_deb = activite.date_debut
            d_fin = activite.date_fin

            # M-3: guard against None before attribute access
            if not d_deb:
                raise ValidationError(
                    "L'activité sélectionnée n'a pas de date de début. "
                    "Veuillez choisir 'Liste de dates' ou paramétrer les dates de l'activité."
                )

            if d_deb.year < 2000:
                raise ValidationError(
                    "L'activité sélectionnée n'a pas de dates valides. "
                    "Veuillez choisir 'Liste de dates' ou paramétrer les dates de l'activité."
                )

            # M-4: guard against None date_fin
            if not d_fin:
                raise ValidationError(
                    "L'activité sélectionnée n'a pas de date de fin. "
                    "Veuillez choisir 'Liste de dates' ou définir une date de fin pour l'activité."
                )

            if (d_fin - d_deb).days > 30:
                raise ValidationError(
                    "La période de l'activité est trop large pour générer automatiquement des dates."
                )

        return cleaned_data
