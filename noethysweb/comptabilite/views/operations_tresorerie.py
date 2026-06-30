# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging, decimal, json, datetime
logger = logging.getLogger(__name__)
from django.urls import reverse_lazy, reverse
from django.db.models import Q, Sum, DecimalField, Case, When, F
from django.contrib import messages
from django.http import JsonResponse
from django.template.context_processors import csrf
from crispy_forms.utils import render_crispy_form
from core.views.mydatatableview import MyDatatable, columns, helpers
from core.views import crud
from core.models import ComptaOperation, CompteBancaire, ComptaVentilation, ComptaCategorie, ComptaAvance, Structure
from core.utils import utils_dates, utils_parametres, utils_texte
from comptabilite.forms.operations_tresorerie import Formulaire, FORMSET_CATEGORIES
from comptabilite.forms.ventilation_tresorerie import Formulaire as Formulaire_ventilation
from django.forms.models import inlineformset_factory, BaseInlineFormSet
from core.forms.base import FormulaireBase
from django.forms import ModelForm
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Hidden, Fieldset, Div
from crispy_forms.bootstrap import Field, PrependedText
from core.utils import utils_preferences
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404


@require_POST
def Pointer_operation_ajax(request):
    """
    Vue Ajax pour modifier le statut de pointage (Sauvegarde dans les préférences).
    """
    idoperation = request.POST.get('idoperation')
    pointage = request.POST.get('pointage') == 'true'

    if not idoperation:
        return JsonResponse(
            {"statut": "erreur", "message": "ID manquant"},
            status=400
        )

    operation = get_object_or_404(ComptaOperation, idoperation=idoperation)

    operation.pointage = pointage
    operation.save(update_fields=["pointage"])

    return JsonResponse({"statut": "ok"})


def Get_form_ventilation(request):
    action = request.POST.get("action", None)
    index = request.POST.get("index", None)
    type_operation = request.POST.get("type_operation", None)

    initial_data = {}
    if "valeur" in request.POST:
        initial_data = json.loads(request.POST["valeur"])
        initial_data["date_budget"] = utils_dates.ConvertDateENGtoDate(initial_data["date_budget"])
        initial_data["montant"] = decimal.Decimal(initial_data["montant"])
        initial_data["index"] = index

    if action == "ajouter":
        initial_data["date_budget"] = utils_dates.ConvertDateFRtoDate(request.POST.get("date_operation", None))

    # Création et rendu html du formulaire
    if action in ("ajouter", "modifier"):
        form = Formulaire_ventilation(request=request, type=type_operation, initial=initial_data)
        return JsonResponse({"form_html": render_crispy_form(form, context=csrf(request))})

    # Validation du formulaire
    form = Formulaire_ventilation(request.POST, request=request)
    if not form.is_valid():
        messages_erreurs = ["<b>%s</b> : %s " % (field.title(), erreur[0].message) for field, erreur in form.errors.as_data().items()]
        return JsonResponse({"erreur": messages_erreurs}, status=401)

    # Mémorisation de l'analytique saisie
    utils_parametres.Set(nom="analytique", categorie="ventilation_tresorerie", utilisateur=request.user, valeur=form.cleaned_data["analytique"].pk)

    # Transformation en chaîne
    dict_retour = {
        "idventilation": form.cleaned_data["idventilation"],
        "date_budget": str(form.cleaned_data["date_budget"]),
        "analytique": form.cleaned_data["analytique"].pk,
        "categorie": form.cleaned_data["categorie"].pk,
        "montant": str(form.cleaned_data["montant"]),
    }
    return JsonResponse({"valeur": dict_retour, "index": form.cleaned_data["index"]})




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

class Page(crud.Page):
    model = ComptaOperation
    url_liste = "operations_tresorerie_liste"
    url_modifier = "operations_tresorerie_modifier"
    url_supprimer = "operations_tresorerie_supprimer"
    url_ajouter_debit = "operations_tresorerie_ajouter_debit"
    url_ajouter_credit = "operations_tresorerie_ajouter_credit"
    description_liste = "Voici ci-dessous la liste des opérations de trésorerie."
    description_saisie = "Saisissez toutes les informations concernant l'opération à saisir et cliquez sur le bouton Enregistrer."
    objet_singulier = "une opération de trésorerie"
    objet_pluriel = "des opérations de trésorerie"

    def get_context_data(self, **kwargs):
        """ Context data spécial pour onglet """
        context = super(Page, self).get_context_data(**kwargs)

        # Ajuste le titre selon le type
        if getattr(self, "type", None) == "debit":
            context["box_titre"] += " au débit"
        elif getattr(self, "type", None) == "credit":
            context["box_titre"] += " au crédit"

        # Catégorie et liste des comptes bancaires
        context["categorie"] = self.Get_categorie()
        context['label_categorie'] = "Compte"
        context['liste_categories'] = [
            (item.pk, f"{item.nom} ({item.structure.nom if item.structure else 'Sans structure'})")
            for item in CompteBancaire.objects.filter(
                Q(structure__in=self.request.user.structures.all()) | Q(structure__isnull=True)
            ).order_by("nom")
        ]

        instance = getattr(self, 'object', None)

        # --- Récupération des ventilations existantes ---
        ventilations = ComptaVentilation.objects.filter(
            operation=instance) if instance else ComptaVentilation.objects.none()
        extra_lines = 0 if ventilations.exists() else 1

        # --- Création dynamique du formset ---
        FORMSET_CATEGORIES_DYN = inlineformset_factory(
            ComptaOperation,
            ComptaVentilation,
            form=CategorieForm,
            fk_name="operation",
            formset=BaseCategorieFormSet,
            fields=["categorie", "montant"],
            extra=extra_lines,
            min_num=0,
            can_delete=True,
            validate_max=True,
            can_order=False,
        )

        # Détermination du type à passer au formulaire
        type_for_form = getattr(instance, "type", None) or getattr(self, "type", None)

        if self.request.method == "POST":
            formset_categories = FORMSET_CATEGORIES_DYN(
                self.request.POST,
                instance=instance,
                form_kwargs={"request": self.request, "type": type_for_form}
            )
        else:
            # Préremplissage des ventilations
            initial_data = [{"categorie": vent.categorie, "montant": vent.montant} for vent in ventilations]
            formset_categories = FORMSET_CATEGORIES_DYN(
                instance=instance,
                initial=initial_data,
                form_kwargs={"request": self.request, "type": type_for_form}
            )

        context["formset_categories"] = formset_categories

        if context['liste_categories']:
            context['boutons_liste'] = [
                {"label": "Ajouter une dépense", "classe": "btn btn-primary", "href": reverse_lazy(self.url_ajouter_debit, kwargs={'categorie': self.Get_categorie()}), "icone": "fa fa-plus"},
                {"label": "Ajouter une recette", "classe": "btn btn-primary", "href": reverse_lazy(self.url_ajouter_credit, kwargs={'categorie': self.Get_categorie()}), "icone": "fa fa-plus"},
                {"label": "Ajouter un virement interne", "classe": "btn btn-default", "href": reverse_lazy("virements_ajouter"), "icone": "fa fa-plus"},
                {"label": "Régulariser une avance", "classe": "btn btn-default", "href": reverse_lazy("regul_avances"), "icone": "fa fa-plus"},
            ]
        else:
            context['box_introduction'] = "Vous pouvez saisir ici des opérations de trésorerie.<br><b>Vous devez avoir enregistré au moins un compte bancaire avant de pouvoir ajouter des opérations !</b>"
        return context

    def test_func_page(self):
        # Vérifie que l'utilisateur a une permission d'accéder à ce compte
        idcompte = self.Get_categorie()
        if idcompte and idcompte not in [compte.pk for compte in CompteBancaire.objects.filter(self.Get_condition_structure())]:
            return False
        return True

    def Get_categorie(self):
        idcompte = self.kwargs.get('categorie', None)
        if idcompte:
            return idcompte
        compte = CompteBancaire.objects.filter(self.Get_condition_structure()).order_by("nom")
        return compte[0].pk if compte else 0

    def get_form_kwargs(self, **kwargs):
        form_kwargs = super(Page, self).get_form_kwargs(**kwargs)
        form_kwargs["categorie"] = self.Get_categorie()
        form_kwargs["type"] = getattr(self, "type", None)
        return form_kwargs

    def get_success_url(self):
        """ Renvoie vers la liste après le formulaire """
        if "SaveAndNew" in self.request.POST:
            # Redirection selon le type d'opération
            if getattr(self, "type", None) == "debit":
                url = self.url_ajouter_debit
            else:
                url = self.url_ajouter_credit
        else:
            url = self.url_liste
        return reverse_lazy(url, kwargs={'categorie': self.Get_categorie()})

    def form_valid(self, form):
        from decimal import Decimal
        import datetime
        from core.utils import utils_dates

        # --- Création du formset lié à l'opération (instance existante ou nouvelle) ---
        formset_categories = FORMSET_CATEGORIES(
            self.request.POST or None,
            instance=self.object,
            form_kwargs={
                "request": self.request,
                "type": getattr(self.object, "type", None)
            }
        )
        form.formset_categories = formset_categories

        # --- Validation du formulaire et du formset ---
        if not (form.is_valid() and formset_categories.is_valid()):
            return self.render_to_response(
                self.get_context_data(form=form, formset_categories=formset_categories)
            )

        # --- Extraction et préparation des données du formset ---
        ventilations_data = []
        for f in formset_categories.forms:
            data = f.cleaned_data
            if data and not data.get("DELETE", False):
                ventilations_data.append({
                    "categorie_id": data.get("categorie").pk if data.get("categorie") else None,
                    "montant": Decimal(data.get("montant") or 0),
                    "date_budget": str(datetime.date.today()),
                    "analytique": 1,
                    "libelle": ""
                })

        # --- Vérification des montants ---
        total_montant = form.cleaned_data.get("montant") or Decimal(0)
        montant_ventilation = sum([v["montant"] for v in ventilations_data])
        if total_montant != montant_ventilation:
            form.add_error(
                None,
                f"La somme des catégories ({montant_ventilation}) ne correspond pas au montant total ({total_montant})."
            )
            return self.form_invalid(form)

        # --- Vérification des doublons de catégorie ---
        categories_ids = [v["categorie_id"] for v in ventilations_data]
        duplicates = set([x for x in categories_ids if categories_ids.count(x) > 1])
        if duplicates:
            noms = [str(ComptaCategorie.objects.get(pk=c).nom) for c in duplicates]
            form.add_error(None, f"Vous ne pouvez pas saisir deux fois la même catégorie : {', '.join(noms)}.")
            return self.form_invalid(form)

        # --- Sauvegarde du formulaire principal ---
        self.object = form.save(commit=False)

        # --- Si une déduction est sélectionnée ---
        deduction = form.cleaned_data.get("deduction")
        if deduction:
            # 1️⃣ On marque la déduction comme remboursée
            deduction.remb = True
            deduction.save(update_fields=["remb"])

            # 2️⃣ On modifie le libellé de l'opération pour ajouter "(Déduction XX€)"
            montant_deduction = deduction.montant
            famille_nom = deduction.famille.nom
            self.object.libelle = f"{self.object.libelle} (Famille : {famille_nom})"

        # --- Sauvegarde définitive ---
        self.object.save()

        # --- Récupération des ventilations existantes liées à cette opération ---
        ventilations_existantes = {
            v.categorie_id: v
            for v in ComptaVentilation.objects.filter(operation=self.object)
        }

        # --- Création ou mise à jour des ventilations ---
        categories_formset = set()
        for v in ventilations_data:
            categories_formset.add(v["categorie_id"])
            if v["categorie_id"] in ventilations_existantes:
                # Mise à jour de la ventilation existante
                vent = ventilations_existantes[v["categorie_id"]]
                vent.date_budget = utils_dates.ConvertDateENGtoDate(v["date_budget"])
                vent.analytique_id = v["analytique"]
                vent.montant = v["montant"]
                vent.libelle = v["libelle"]
                vent.save()
            else:
                # Création d'une nouvelle ventilation
                ComptaVentilation.objects.create(
                    operation=self.object,
                    categorie_id=v["categorie_id"],
                    date_budget=utils_dates.ConvertDateENGtoDate(v["date_budget"]),
                    analytique_id=v["analytique"],
                    montant=v["montant"],
                    libelle=v["libelle"],
                )

        # --- Suppression des ventilations supprimées ---
        for cat_id, vent in ventilations_existantes.items():
            if cat_id not in categories_formset:
                vent.delete()

        return super().form_valid(form)

class Liste(Page, crud.Liste):
    model = ComptaOperation
    template_name = "core/crud/liste_avec_categorie.html"

    def get_queryset(self):
        return ComptaOperation.objects.select_related("tiers", "mode").filter(
            Q(compte=self.Get_categorie()) & self.Get_filtres("Q"))

    def get_context_data(self, **kwargs):
        context = super(Liste, self).get_context_data(**kwargs)
        context['impression_introduction'] = ""
        context['impression_conclusion'] = ""
        context['afficher_menu_brothers'] = True

        from django.db.models import Sum, Case, When, F, DecimalField, Q

        # 1. On cible les opérations du compte courant
        operations = ComptaOperation.objects.filter(compte_id=self.Get_categorie())

        # 2. CORRECTION STRICTE DU DOUBLE COMPTAGE (PRODUIT CARTÉSIEN)
        ids_operations_orga = ComptaVentilation.objects.filter(
            categorie__orga=True
        ).values_list('operation_id', flat=True)

        operations = operations.exclude(pk__in=ids_operations_orga)

        # 3. EXCLUSION DES AVANCES
        operations = operations.exclude(
            avance__isnull=False,
            regul_avance=False
        )

        # 4. Calcul de l'agrégation saine
        stats = operations.aggregate(
            total_debit=Sum(
                Case(
                    When(type="debit", then=F("montant")),
                    output_field=DecimalField(),
                    default=0
                )
            ),
            total_credit=Sum(
                Case(
                    When(type="credit", then=F("montant")),
                    output_field=DecimalField(),
                    default=0
                )
            )
        )

        total_debit = stats["total_debit"] or 0
        total_credit = stats["total_credit"] or 0
        solde_final = total_credit - total_debit

        # --- Totaux par avance ---
        from django.db.models import F, Value

        avances_stats = (
            ComptaOperation.objects
            .filter(
                compte=self.Get_categorie(),
                avance__isnull=False,
                regul_avance=False,
                remb_avance=0
            )
            .values('avance__idcompta_avance', 'avance__nom')
            .annotate(
                total_montant=Sum(
                    Case(
                        When(type='debit', then=F('montant') * Value(-1)),
                        When(type='credit', then=F('montant')),
                        output_field=DecimalField(),
                    )
                )
            )
            .order_by('avance__nom')
        )

        html_avances = ""
        if avances_stats:
            html_avances = "<br><b>État des avances à régulariser :</b><br><table>"
            for avance in avances_stats:
                html_avances += f"<tr><td>{avance['avance__nom']} :</td><td style='padding-left:10px;'>{utils_texte.Formate_montant(avance['total_montant'])}</td></tr>"
            html_avances += "</table>"

        context['box_introduction'] = f"""
            <center>
                <table style="font-weight:bold;">
                    <tr><td>Solde du compte :</td><td style='padding-left:10px;'>{utils_texte.Formate_montant(solde_final)}</td></tr>
                </table>
                <table style="font-weight:normal;">
                    <tr><td>Somme des débits sur le compte :</td><td style='padding-left:10px;'>{utils_texte.Formate_montant(total_debit)}</td></tr>
                    <tr><td>Somme des crédits sur le compte :</td><td style='padding-left:10px;'>{utils_texte.Formate_montant(total_credit)}</td></tr>
                </table>
                {html_avances}
            </center>
        """
        return context

    class datatable_class(MyDatatable):
        filtres = ["idoperation", "type", "date", "libelle", "mode", "releve", "num_piece", "debit", "credit",
                   "montant"]

        pointage = columns.TextColumn("Pointage", sources=["idoperation"], processor="Get_checkbox_pointage")
        debit = columns.TextColumn("Débit", sources=["montant"], processor="Get_montant_debit")
        credit = columns.TextColumn("Crédit", sources=["montant"], processor="Get_montant_credit")
        actions = columns.TextColumn("Actions", sources=None, processor='Get_actions_speciales')

        class Meta:
            structure_template = MyDatatable.structure_template
            columns = ["pointage", "date", "num_piece", "libelle", "mode", "debit", "credit", "actions"]
            ordering = ["date"]
            processors = {
                "date": helpers.format_date('%d/%m/%Y'),
                "libelle": "Get_libelle_avance",
            }
            labels = {
                "mode": "Mode",
                "num_piece": "N° Pièce",
                "releve": "Relevé",
            }

        def Get_checkbox_pointage(self, instance, **kwargs):
            checked = "checked" if instance.pointage else ""
            return (
                f'<center>'
                f'<input type="checkbox" class="action-pointage" '
                f'data-idoperation="{instance.pk}" {checked}>'
                f'</center>'
            )

        def Get_libelle_avance(self, instance, **kwargs):
            avance_nom = f" - (Avance de {instance.avance.nom})" if instance.avance else ""
            regul = ""
            if not instance.regul_avance and instance.remb_avance:
                regul = " - régularisée"
            return f"{instance.libelle}{avance_nom}{regul}"

        def Get_montant_debit(self, instance, **kwargs):
            if instance.type == "debit":
                return "%0.2f" % instance.montant
            return None

        def Get_montant_credit(self, instance, **kwargs):
            if instance.type == "credit":
                return "%0.2f" % instance.montant
            return None

        def Get_actions_speciales(self, instance, *args, **kwargs):
            html = []
            if instance.virement:
                html = [
                    self.Create_bouton_modifier(url=reverse("virements_modifier", args=[instance.virement_id])),
                    self.Create_bouton_supprimer(url=reverse("virements_supprimer", args=[instance.virement_id])),
                ]
            else:
                if instance.regul_avance:
                    modifier_url = reverse("regul_avances_modifier", args=[instance.pk])
                    supprimer_url = reverse("regul_avances_supprimer", args=[instance.pk])
                else:
                    modifier_url = reverse(kwargs["view"].url_modifier, args=[instance.compte_id, instance.pk])
                    supprimer_url = reverse(kwargs["view"].url_supprimer, args=[instance.compte_id, instance.pk])

                html = [
                    self.Create_bouton_modifier(url=modifier_url),
                    self.Create_bouton_supprimer(url=supprimer_url),
                ]
                if instance.document:
                    html.append(self.Create_bouton_ouvrir(url=instance.document.url))
            return self.Create_boutons_actions(html)

class Ajouter(Page, crud.Ajouter):
    form_class = Formulaire
    type = None
    def dispatch(self, request, *args, **kwargs):
        self.type = kwargs.pop('type', getattr(self, 'type', 'debit'))
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self, **kwargs):
        form_kwargs = super().get_form_kwargs(**kwargs)
        form_kwargs['type'] = self.type
        return form_kwargs
class Modifier(Page, crud.Modifier):
    form_class = Formulaire


class Supprimer(Page, crud.Supprimer):
    form_class = Formulaire