# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import json, decimal
from collections import Counter
from django.views.generic import TemplateView
from django.db.models import Q, Sum
from core.views.base import CustomView
from core.models import ComptaVentilation, ComptaOperationBudgetaire, ComptaCategorieBudget, ComptaCategorie
from comptabilite.forms.suivi_budget import Formulaire


class View(CustomView, TemplateView):
    menu_code = "suivi_budget"
    template_name = "comptabilite/suivi_budget.html"

    def get_context_data(self, **kwargs):
        context = super(View, self).get_context_data(**kwargs)
        context['page_titre'] = "Suivi du budget"
        context['afficher_menu_brothers'] = True
        if "form_parametres" not in kwargs:
            context['form_parametres'] = Formulaire(request=self.request)
        return context

    def post(self, request, **kwargs):
        form = Formulaire(request.POST, request=self.request)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form_parametres=form))

        liste_lignes = self.Get_resultats(parametres=form.cleaned_data)
        context = {
            "form_parametres": form,
            "liste_lignes": json.dumps(liste_lignes),
        }
        return self.render_to_response(self.get_context_data(**context))

    def Get_resultats(self, parametres={}):
        budget = parametres["budget"]

        comptes = budget.compte.all()
        condition_structure = Q(structure__in=self.request.user.structures.all()) | Q(structure__isnull=True)

        categories_budget = ComptaCategorieBudget.objects.select_related("categorie").filter(budget=budget)
        dict_budgete = {cb.categorie: cb.montant for cb in categories_budget}
        ids_categories_autorisees = [cb.categorie_id for cb in categories_budget]

        # Importation des ventilations
        condition_realise = (
                Q(categorie__in=ids_categories_autorisees) &
                Q(operation__compte__in=comptes) &
                Q(operation__date__gte=budget.date_debut) &
                Q(operation__date__lte=budget.date_fin)
        )
        # On récupère les totaux par ID de catégorie
        ventilations_data = ComptaVentilation.objects.filter(condition_realise) \
            .values("categorie") \
            .annotate(total=Sum("montant"))

        # 3. Extraction de TOUS les IDs de catégories concernés (Budget + Réalisé)
        ids_categories_realise = [v["categorie"] for v in ventilations_data if v["categorie"]]
        ids_categories_budget = [c.pk for c in dict_budgete.keys()]
        tous_les_ids = list(set(ids_categories_realise + ids_categories_budget))

        # 4. Importation unique de tous les objets catégories nécessaires
        # On ne filtre plus par structure ici, mais uniquement par les IDs trouvés
        dict_categories = {c.pk: c for c in ComptaCategorie.objects.filter(pk__in=tous_les_ids)}

        # 5. Construction du dictionnaire du réalisé avec les objets catégories
        dict_realise = {}
        for v in ventilations_data:
            cat_obj = dict_categories.get(v["categorie"])
            if cat_obj:
                dict_realise[cat_obj] = v["total"]

        # 6. Liste finale triée (Union des clés des deux dictionnaires)
        categories = sorted(
            set(list(dict_budgete.keys()) + list(dict_realise.keys())),
            key=lambda x: (x.type, x.nom)
        )

        # Création des lignes
        lignes = []
        regroupements = {}
        for categorie in categories:
            # Création du regroupement (débit ou crédit)
            if not categorie.type in regroupements:
                regroupements[categorie.type] = {"id": 1000000 + len(regroupements), "realise": decimal.Decimal(0), "budgete": decimal.Decimal(0)}
                lignes.append({"id": regroupements[categorie.type]["id"], "pid": 0, "regroupement": True, "label": categorie.get_type_display()})

            # Calcul des données de la ligne
            realise = dict_realise.get(categorie, decimal.Decimal(0))
            budgete = dict_budgete.get(categorie, decimal.Decimal(0))
            pourcentage = (float(realise) * 100 / float(budgete)) if budgete else None
            ecart = (budgete - realise) if categorie.type == "debit" else (realise - budgete)

            # Mémorisation pour ligne de total
            regroupements[categorie.type]["realise"] += realise
            regroupements[categorie.type]["budgete"] += budgete

            # Création de la ligne
            lignes.append({"id": categorie.pk, "pid": regroupements[categorie.type]["id"], "regroupement": False,
                           "label": categorie.nom,
                           "realise": float(realise),
                           "budgete": float(budgete),
                           "pourcentage": pourcentage if pourcentage else None,
                           "ecart": float(ecart),
                           })

        # Ligne de total
        total_realise = (regroupements["credit"]["realise"] if "credit" in regroupements else decimal.Decimal(0)) - (regroupements["debit"]["realise"] if "debit" in regroupements else decimal.Decimal(0))
        total_budgete = (regroupements["credit"]["budgete"] if "credit" in regroupements else decimal.Decimal(0)) - (regroupements["debit"]["budgete"] if "debit" in regroupements else decimal.Decimal(0))
        total_pourcentage = (float(total_realise) * 100 / float(total_budgete)) if total_budgete else None
        total_ecart = total_realise - total_budgete
        lignes.append({"id": 99999998, "pid": 99999999, "regroupement": False, "label": "", "realise": float(total_realise), "budgete": float(total_budgete),
                       "pourcentage": total_pourcentage if total_pourcentage else None, "ecart": float(total_ecart)})

        return lignes
