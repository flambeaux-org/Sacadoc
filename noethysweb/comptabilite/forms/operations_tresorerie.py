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

class Formulaire(FormulaireBase, ModelForm):
    ventilation = forms.CharField(label="        ", required=False, widget=Ventilation_operation(attrs={}))
    categorie_rapide = forms.ModelChoiceField(
        queryset=ComptaCategorie.objects.none(),
        required=False,
        label="Catégorie"
    )

    deduction = forms.ModelChoiceField(
        queryset=TypeDeduction.objects.none(),
        required=False,
        label="Déduction"
    )

    class Meta:
        model = ComptaOperation
        fields = "__all__"
        widgets = {
            "date": DatePickerWidget(),
            "observations": forms.Textarea(attrs={'rows': 3}),
            "tiers": Select_avec_commandes_advanced(attrs={"id_form": "tiers_form", "module_form": "parametrage.forms.tiers", "nom_objet": "un tiers", "champ_nom": "nom"}),
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
                nums = (
                    ComptaOperation.objects
                    .filter(compte_id=idcompte, type="debit")
                    .values_list("num_piece", flat=True)
                )
                max_num = max(
                    (int(n.strip()) for n in nums if n and n.strip().isdigit()),
                    default=0,
                )
                self.fields["num_piece"].initial = max_num + 1
                self.fields["num_piece"].widget.attrs["readonly"] = True

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

        # Tiers
        self.fields["tiers"].queryset = ComptaTiers.objects.filter(Q(structure__in=self.request.user.structures.all()) | Q(structure__isnull=True)).order_by("nom")

        # Ventilation
        self.fields["ventilation"].widget.request = self.request
        self.fields["ventilation"].widget.attrs.update({
            "analytiques": json.dumps({analytique.pk: analytique.nom for analytique in ComptaAnalytique.objects.all()}),
            "categories": json.dumps({categorie.pk: categorie.nom for categorie in ComptaCategorie.objects.all()}),
        })
        ventilations = ComptaVentilation.objects.select_related("analytique", "categorie").filter(operation=self.instance if self.instance else 0)
        self.fields["ventilation"].initial = json.dumps([{"idventilation": v.pk, "date_budget": str(v.date_budget), "analytique": v.analytique_id, "categorie": v.categorie_id, "montant": str(v.montant)} for v in ventilations])

        self.fields["categorie_rapide"].queryset = ComptaCategorie.objects.filter(
            Q(type=type) & (Q(structure__in=self.request.user.structures.all()) | Q(structure__isnull=True))
        ).order_by("nom")

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
                    style="margin-bottom:20px;"
                ),
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

            # Formset invalide
            if not formset.is_valid():
                raise forms.ValidationError("Certaines lignes du formset sont invalides.")

            # Récupère les montants des lignes valides
            for f in formset.forms:
                data = f.cleaned_data
                if data and not data.get("DELETE", False):
                    v_montant = data.get("montant") or 0
                    ventilations.append(v_montant)
        # --- Si une déduction est sélectionnée, vérifier le montant ---
        if deduction:
            if montant != deduction.montant:
                self.add_error(
                    "montant",
                    f"Le montant saisi ({montant}€) doit correspondre au montant de la déduction ({deduction.montant}€)."
                )
        return cleaned_data
