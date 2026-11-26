# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import json, decimal
from django.views.generic import TemplateView
from django.db.models import Q, Sum
from core.views.base import CustomView
from core.models import ComptaVentilation, ComptaCategorieBudget, ComptaCategorie
from comptabilite.forms.suivi_budget import Formulaire
from comptabilite.utils import utils_rapprochement, utils_compta
from comptabilite.utils.utils_compta import Arrondi as _arrondi


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

        liste_lignes, totaux = self.Get_resultats(parametres=form.cleaned_data)
        context = {
            "form_parametres": form,
            "liste_lignes": json.dumps(liste_lignes),
            "totaux": totaux,
        }
        return self.render_to_response(self.get_context_data(**context))

    def Get_resultats(self, parametres={}):
        budget = parametres["budget"]
        comptes = budget.compte.all()

        # 1. DICTIONNAIRE DU BUDGET : Montants par ID de catégorie pour CE budget
        categories_budget = ComptaCategorieBudget.objects.filter(budget=budget)
        dict_budgete = {cb.categorie_id: cb.montant for cb in categories_budget}

        # 2. DICTIONNAIRE DU RÉALISÉ : Ventilations cumulées par ID de catégorie
        condition_realise = (
                Q(operation__compte__in=comptes) &
                Q(operation__date__gte=budget.date_debut) &
                Q(operation__date__lte=budget.date_fin)
        )
        # Les catégories hors bilan restent en dehors du résultat, comme au Suivi des
        # finances : la case "Compte intégré au bilan" doit avoir le même effet partout.
        # Leur montant est calculé à part, pour être affiché sans être compté.
        ventilations_data = ComptaVentilation.objects.filter(condition_realise, categorie__bilan=True) \
            .values("categorie") \
            .annotate(total=Sum("montant"))

        dict_realise = {v["categorie"]: v["total"] for v in ventilations_data if v["categorie"]}

        total_hors_bilan = ComptaVentilation.objects.filter(
            condition_realise, categorie__bilan=False).aggregate(total=Sum("montant"))["total"] or decimal.Decimal(0)

        # 3. CATÉGORIES AFFICHÉES : celles visibles par l'utilisateur, auxquelles on ajoute
        # celles réellement mouvementées ou budgétées. Sans cela, une catégorie rattachée à
        # une autre structure disparaissait du tableau ET de ses totaux, alors que l'argent
        # est bien passé sur les comptes du budget.
        condition_categories = Q(structure__in=self.request.user.structures.all()) | Q(structure__isnull=True)
        condition_utilisee = Q(pk__in=set(dict_realise) | set(dict_budgete))
        toutes_les_categories = ComptaCategorie.objects.filter(
            (condition_categories | condition_utilisee) & Q(bilan=True))

        # --- Règlements encaissés par l'organisateur (chèques vacances, bons CAF...) ---
        # Toutes les structures des comptes du budget, et non la première seulement.
        # La structure du budget n'est pas retenue : elle sert au cloisonnement des
        # droits, pas au périmètre d'analyse, qui suit les comptes comme le réalisé.
        structures = [s for s in comptes.values_list("structure", flat=True) if s]
        liste_reglements_encaissement = utils_compta.Get_reglements_encaissement(
            structures=structures, date_debut=budget.date_debut, date_fin=budget.date_fin)

        # 4. CONSTRUCTION DES LIGNES
        lignes = []
        regroupements = {}

        def Get_regroupement(type_operation, label):
            """ Renvoie la ligne parente du type (débit ou crédit), en la créant au besoin """
            if type_operation not in regroupements:
                regroupements[type_operation] = {
                    "id": 1000000 + len(regroupements),
                    "pid": 0,
                    "regroupement": True,
                    "label": label,
                    "realise": decimal.Decimal(0),
                    "budgete": decimal.Decimal(0),
                }
                lignes.append(regroupements[type_operation])
            return regroupements[type_operation]

        def Ajouter_en_fin_de_groupe(ligne, regroupement):
            """ Insère la ligne après le dernier enfant de son regroupement, pour que
                l'ordre de la liste corresponde à l'ordre d'affichage de l'arbre """
            position = len(lignes)
            for index in range(len(lignes) - 1, -1, -1):
                if lignes[index] is regroupement or lignes[index].get("pid") == regroupement["id"]:
                    position = index + 1
                    break
            lignes.insert(position, ligne)

        def Get_ecart(type_operation, realise, budgete):
            """ Un écart est favorable quand on dépense moins, ou quand on encaisse plus """
            return (budgete - realise) if type_operation == "debit" else (realise - budgete)

        def Get_pourcentage(realise, budgete):
            return (float(realise) * 100 / float(budgete)) if budgete else None

        # Tri par type, puis les catégories liées à l'organisateur en fin de groupe
        categories_triees = sorted(toutes_les_categories, key=utils_compta.Cle_tri_categorie)

        for categorie in categories_triees:
            budgete = dict_budgete.get(categorie.pk, decimal.Decimal(0))
            realise = dict_realise.get(categorie.pk, decimal.Decimal(0))

            # Si rien en budget ET rien en réalisé, on n'affiche pas la catégorie
            if budgete == 0 and realise == 0:
                continue

            regroupement = Get_regroupement(categorie.type, categorie.get_type_display())

            # Cumul dans le totalisateur parent (Débit ou Crédit)
            regroupement["realise"] += realise
            regroupement["budgete"] += budgete

            lignes.append({
                "id": categorie.pk,
                "pid": regroupement["id"],
                "regroupement": False,
                "label": categorie.nom,
                "realise": float(_arrondi(realise)),
                "budgete": float(_arrondi(budgete)),
                "pourcentage": Get_pourcentage(realise, budgete),
                "ecart": float(_arrondi(Get_ecart(categorie.type, realise, budgete))),
            })

        # Les règlements encaissés par l'organisateur n'ont pas de ventilation comptable sur
        # les comptes bancaires, mais ils constituent bien une recette : on les ajoute au
        # crédit, comme le Bilan financier. Ils ne sont jamais budgétés.
        label_encaissement = utils_compta.Get_label_encaissement()
        total_encaissement = decimal.Decimal(0)
        for index, bloc in enumerate(liste_reglements_encaissement):
            montant = bloc["total"]
            if not montant:
                continue
            regroupement = Get_regroupement("credit", "Crédit")
            regroupement["realise"] += montant
            total_encaissement += montant
            Ajouter_en_fin_de_groupe({
                "id": 3000000 + index,
                "pid": regroupement["id"],
                "regroupement": False,
                "label": "%s (%s)" % (bloc["mode"], label_encaissement),
                "realise": float(_arrondi(montant)),
                "budgete": 0.0,
                "pourcentage": None,
                "ecart": float(_arrondi(montant)),
            }, regroupement)

        # Aucune opération des comptes du budget ne doit disparaître des totaux : ce qui
        # n'est ventilé sur aucune catégorie est isolé dans une ligne explicite, comme au
        # Suivi des finances, pour que les deux pages restent comparables à période égale.
        for type_operation, label in (("credit", "Crédit"), ("debit", "Débit")):
            non_ventile = utils_compta.Get_montant_non_ventile(
                comptes=comptes, type_operation=type_operation,
                date_debut=budget.date_debut, date_fin=budget.date_fin)
            if not non_ventile:
                continue
            regroupement = Get_regroupement(type_operation, label)
            regroupement["realise"] += non_ventile
            Ajouter_en_fin_de_groupe({
                "id": 4000000 + (0 if type_operation == "credit" else 1),
                "pid": regroupement["id"],
                "regroupement": False,
                "label": "Opérations non ventilées",
                "realise": float(_arrondi(non_ventile)),
                "budgete": 0.0,
                "pourcentage": None,
                "ecart": float(_arrondi(Get_ecart(type_operation, non_ventile, decimal.Decimal(0)))),
            }, regroupement)

        # --- TOTAUX (en Decimal, avant conversion en float pour le JSON) ---
        total_credit = regroupements.get("credit", {}).get("realise", decimal.Decimal(0))
        total_debit = regroupements.get("debit", {}).get("realise", decimal.Decimal(0))
        budget_credit = regroupements.get("credit", {}).get("budgete", decimal.Decimal(0))
        budget_debit = regroupements.get("debit", {}).get("budgete", decimal.Decimal(0))
        total_realise = total_credit - total_debit
        total_budgete = budget_credit - budget_debit
        total_ecart = total_realise - total_budgete

        # --- FORMATTAGE DES LIGNES PARENTES POUR LE JSON ---
        for type_key, reg_line in regroupements.items():
            t_realise, t_budgete = reg_line["realise"], reg_line["budgete"]
            reg_line["realise"] = float(_arrondi(t_realise))
            reg_line["budgete"] = float(_arrondi(t_budgete))
            reg_line["pourcentage"] = Get_pourcentage(t_realise, t_budgete)
            reg_line["ecart"] = float(_arrondi(Get_ecart(type_key, t_realise, t_budgete)))

        lignes.append({
            "id": 99999998,
            "pid": 99999999,
            "regroupement": False,
            "label": "SOLDE GENERAL",
            "realise": float(_arrondi(total_realise)),
            "budgete": float(_arrondi(total_budgete)),
            "pourcentage": Get_pourcentage(total_realise, total_budgete),
            "ecart": float(_arrondi(total_ecart)),
        })

        # --- Totaux de la page : résultat du projet et contrepoint bancaire ---
        solde_bancaire = utils_rapprochement.Get_solde_bancaire(comptes, date_fin=budget.date_fin)
        # Le réalisé couvre la période du budget : on le compare à la variation
        # du solde bancaire sur cette même période, pas au solde cumulé.
        mouvements_bancaires = utils_rapprochement.Get_mouvements_bancaires(
            comptes, date_debut=budget.date_debut, date_fin=budget.date_fin)
        totaux = {
            "nom_budget": budget.nom,
            "date_debut": budget.date_debut,
            "date_fin": budget.date_fin,
            "total_recettes": _arrondi(total_credit),
            "total_depenses": _arrondi(total_debit),
            "recettes_budgetees": _arrondi(budget_credit),
            "depenses_budgetees": _arrondi(budget_debit),
            "resultat_projet": _arrondi(total_realise),
            "resultat_budgete": _arrondi(total_budgete),
            "ecart_resultat": _arrondi(total_ecart),
            "total_hors_bilan": _arrondi(total_hors_bilan),
            "solde_bancaire": _arrondi(solde_bancaire),
            "mouvements_bancaires": _arrondi(mouvements_bancaires),
            # Comme au Bilan financier : ces recettes comptent dans le résultat mais ne
            # transitent pas par les comptes, on les neutralise pour l'écart bancaire.
            "total_encaissement": _arrondi(total_encaissement),
            "label_encaissement": label_encaissement,
            "ecart_projet_banque": _arrondi(total_realise - total_encaissement - mouvements_bancaires),
        }

        return lignes, totaux