# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import datetime, json
from django import forms
from django.forms import ModelForm
from django.db.models import Q
from core.forms.base import FormulaireBase
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Hidden, Fieldset, Div, HTML
from crispy_forms.bootstrap import Field, PrependedText
from core.utils.utils_commandes import Commandes
from core.utils import utils_preferences
from core.models import ComptaOperation, ComptaTiers, ComptaVentilation, ComptaAnalytique, ComptaCategorie
from core.widgets import DatePickerWidget, Select_avec_commandes_advanced
from comptabilite.widgets import Ventilation_operation
from django.forms.models import inlineformset_factory, BaseInlineFormSet
from core.forms.select2 import Select2MultipleWidget
from core.forms.base import FormulaireBase
from core.utils.utils_commandes import Commandes
from core.utils import utils_preferences
from core.models import ComptaBudget, ComptaAnalytique, ComptaCategorieBudget, ComptaCategorie, Deduction, TypeDeduction
from core.widgets import DatePickerWidget, Formset

class CategorieForm(FormulaireBase, ModelForm):
    class Meta:
        model = ComptaOperation
        exclude = []

    def __init__(self, *args, **kwargs):
        self.types = kwargs.pop("type", None)
        super().__init__(*args, **kwargs)

        self.helper = FormHelper()
        self.helper.form_show_labels = False

        # Catégories
        condition_structure =Q(structure__in=self.request.user.structures.all()) | Q(structure__isnull=True)
        condition_type = Q(type=self.types) if self.types else Q()
        self.fields["categorie"].queryset = ComptaCategorie.objects.filter(condition_type & condition_structure).order_by("nom")
        self.fields["categorie"].label_from_instance = self.label_from_instance

        self.helper.layout = Layout(
            Field("categorie"),
            PrependedText("montant", utils_preferences.Get_symbole_monnaie()),
        )

    @staticmethod
    def label_from_instance(instance):
        return "%s" % (instance.nom)

    def clean(self):
        return self.cleaned_data


class BaseCategorieFormSet(BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        super(BaseCategorieFormSet, self).__init__(*args, **kwargs)

    def clean(self):
        for form in self.forms:
            if not self._should_delete_form(form):
                # Vérification de la validité de la ligne
                if not form.is_valid() or len(form.cleaned_data) == 0:
                    for field, erreur in form.errors.as_data().items():
                        message = erreur[0].message
                        form.add_error(field, message)
                        return


FORMSET_CATEGORIES = inlineformset_factory(ComptaOperation, ComptaVentilation, form=CategorieForm, fk_name="operation", formset=BaseCategorieFormSet,
                                            fields=["categorie", "montant"], extra=1, min_num=0,
                                            can_delete=True, validate_max=True, can_order=False)

def Get_prochain_num_piece(idcompte):
    """ Renvoie le prochain numéro de pièce disponible pour les dépenses d'un compte """
    numeros = ComptaOperation.objects.filter(compte_id=idcompte, type="debit").values_list("num_piece", flat=True)
    return max((int(n.strip()) for n in numeros if n and n.strip().isdigit()), default=0) + 1


#  Indicateur de ventilation : affiche en direct ce qu'il reste à répartir, et
#  préremplit la ligne unique avec le montant de l'opération. Évite de découvrir
#  l'erreur de répartition seulement après avoir cliqué sur Enregistrer.
AIDE_VENTILATION = """
<div id="aide_ventilation" class="alert" style="margin-top:10px;padding:8px 12px;"></div>
<script>
    function compta_lire_montant(champ) {
        var valeur = ($(champ).val() || "").toString().replace(",", ".").replace(/\\s/g, "");
        var nombre = parseFloat(valeur);
        return isNaN(nombre) ? 0 : nombre;
    }

    function compta_lignes_ventilation() {
        return $('input[name$="-montant"]').filter(function () {
            var ligne = $(this).closest("tr");
            if (ligne.is(":hidden")) { return false; }
            return !ligne.find('input[name$="-DELETE"]').is(":checked");
        });
    }

    function compta_maj_ventilation() {
        var total = compta_lire_montant("#id_montant");
        var somme = 0;
        compta_lignes_ventilation().each(function () { somme += compta_lire_montant(this); });
        var reste = Math.round((total - somme) * 100) / 100;

        var bloc = $("#aide_ventilation");
        bloc.removeClass("alert-success alert-warning alert-danger");
        if (total === 0 && somme === 0) {
            bloc.addClass("alert-warning").html("<i class='fa fa-info-circle'></i> Saisissez le montant de l'opération, puis répartissez-le entre les catégories.");
        } else if (reste === 0) {
            bloc.addClass("alert-success").html("<i class='fa fa-check'></i> Ventilation complète.");
        } else if (reste > 0) {
            bloc.addClass("alert-warning").html("<i class='fa fa-exclamation-triangle'></i> Reste à ventiler : <b>" + reste.toFixed(2) + "</b>");
        } else {
            bloc.addClass("alert-danger").html("<i class='fa fa-times'></i> Dépassement de <b>" + Math.abs(reste).toFixed(2) + "</b> par rapport au montant de l'opération.");
        }
    }

    function compta_prered_remplir_ligne_unique() {
        var lignes = compta_lignes_ventilation();
        if (lignes.length !== 1) { return; }
        var champ = lignes.first();
        if (compta_lire_montant(champ) === 0) {
            var total = compta_lire_montant("#id_montant");
            if (total !== 0) { champ.val(total.toFixed(2)); }
        }
    }

    // Appelé par le widget de formset à chaque ajout / suppression de ligne
    function formset_apres_ajout(row) { compta_maj_ventilation(); }
    function formset_apres_suppression(row) { compta_maj_ventilation(); }

    $(document).ready(function () {
        $(document).on("input change", "#id_montant", function () {
            compta_prered_remplir_ligne_unique();
            compta_maj_ventilation();
        });
        $(document).on("input change", 'input[name$="-montant"], input[name$="-DELETE"]', compta_maj_ventilation);
        compta_maj_ventilation();
    });
</script>
"""


class Formulaire(FormulaireBase, ModelForm):
    deduction = forms.ModelChoiceField(
        queryset=TypeDeduction.objects.none(),
        required=False,
        label="Déduction"
    )

    class Meta:
        model = ComptaOperation
        #  Uniquement les champs réellement saisis dans ce formulaire.
        #  Avec "__all__", les champs non affichés (pointage, verification, tiers,
        #  ref_piece, observations...) étaient réinitialisés à chaque modification :
        #  corriger un libellé décochait l'opération et cassait le rapprochement.
        fields = ["compte", "type", "date", "libelle", "mode", "num_piece",
                  "document", "avance", "montant", "observation"]
        widgets = {
            "date": DatePickerWidget(),
            "mode": Select_avec_commandes_advanced(attrs={"id_form": "modes_reglements_form", "module_form": "parametrage.forms.modes_reglements", "nom_objet": "un mode de règlement", "champ_nom": "label"}),
            "avance": Select_avec_commandes_advanced(attrs={"id_form": "avance_form", "module_form": "parametrage.forms.avance", "nom_objet": "une personne", "champ_nom": "nom"}),
            "document": forms.ClearableFileInput(),

        }

    def __init__(self, *args, **kwargs):
        self.formset_categories = kwargs.pop("formset_categories", None)
        idcompte = kwargs.pop("categorie")
        type = kwargs.pop("type")
        super(Formulaire, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = "operations_tresorerie_form"
        self.helper.form_method = 'post'

        self.helper.form_class = 'form-horizontal'
        self.helper.label_class = 'col-md-2'
        self.helper.field_class = 'col-md-10'


        # Type
        if self.instance.pk:
            type = self.instance.type

        if "document" in self.fields:
            self.fields["document"].help_text = "Formats acceptés : PDF, JPG, PNG "

        self.fields["deduction"].queryset = Deduction.objects.filter(
            label__remb=True,  # filtre sur le champ remb de TypeDeduction
            label__structure__in=self.request.user.structures.all(),  # filtre par structures
            remb=False
        ).order_by("label")

        self.fields["deduction"].label_from_instance = lambda obj: (
            f"Déduction de {obj.montant}€ pour la famille {obj.famille.nom}"
        )

        # --- Gestion du numéro de pièce ---
        if type == "debit":
            if self.instance.pk:
                # Modification : griser si num_piece rempli
                if self.instance.num_piece:
                    self.fields["num_piece"].widget.attrs["readonly"] = True
            else:
                # Valeur indicative : le numéro définitif est attribué à l'enregistrement
                self.fields["num_piece"].initial = Get_prochain_num_piece(idcompte)
                self.fields["num_piece"].widget.attrs["readonly"] = True
                self.fields["num_piece"].help_text = "Attribué automatiquement à l'enregistrement."

        else:
            # Type recette → ne pas afficher le champ
            if "num_piece" in self.fields:
                self.fields.pop("num_piece")
            if "document" in self.fields:
                self.fields.pop("document")
        #Mode
        self.fields["mode"].required = True
        self.fields["mode"].queryset = self.fields["mode"].queryset.exclude(encaissement=True)

        # Date
        self.fields["date"].initial = datetime.date.today()

        fields_general = []

        if "num_piece" in self.fields:
            fields_general.append(Field("num_piece"))

        fields_general += [
            Field("date"),
            Field("libelle"),
            Field("mode"),
        ]

        if "document" in self.fields:
            fields_general.append(Field("document"))

        fields_general += [
            Field("avance"),
            Field("deduction"),
            PrependedText("montant", utils_preferences.Get_symbole_monnaie()),
        ]


        # Affichage
        self.helper.layout = Layout(
            Commandes(annuler_url="{{ view.get_success_url }}"),
            Hidden("compte", value=idcompte),
            Hidden("type", value=type),

            Fieldset(
                "Généralités",
                *fields_general
            ),

            Fieldset(
                "Ventilation",
                Div(
                    Formset("formset_categories"),
                    HTML(AIDE_VENTILATION),
                    style="margin-bottom:20px;"
                ),
            ),
            Fieldset(
                "Divers",
                Field("observation"),
            ),
        )

    def clean(self):
        cleaned_data = super().clean()
        montant = cleaned_data.get("montant")
        deduction = cleaned_data.get("deduction")

        # --- Vérifie que le montant est renseigné ---
        if not montant:
            self.add_error("montant", "Vous devez saisir un montant.")
            return cleaned_data  # inutile de continuer si pas de montant

        # --- Si une déduction est sélectionnée, vérifier le montant ---
        if deduction:
            if montant != deduction.montant:
                self.add_error(
                    "montant",
                    f"Le montant saisi ({montant}€) doit correspondre au montant de la déduction ({deduction.montant}€)."
                )
        return cleaned_data
