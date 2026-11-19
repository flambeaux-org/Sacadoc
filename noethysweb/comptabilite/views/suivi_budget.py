# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import json, decimal
from collections import Counter
from django.views.generic import TemplateView
from django.db.models import Q, Sum
from core.views.base import CustomView
from core.models import ComptaVentilation, ComptaOperationBudgetaire, ComptaCategorieBudget, ComptaCategorie, Reglement, Ventilation
from comptabilite.forms.suivi_budget import Formulaire
from comptabilite.utils import utils_rapprochement


def _arrondi(valeur):
    """ Évite les artefacts de calcul flottant dans les montants affichés """
    return decimal.Decimal(str(valeur or 0)).quantize(decimal.Decimal("0.01"))


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

        # 1. BASE DE DÉPART : On récupère TOUTES les catégories comptables
        structures_utilisateurs = self.request.user.structures.all()
        condition_categories = Q(structure__in=structures_utilisateurs) | Q(structure__isnull=True)
        toutes_les_categories = ComptaCategorie.objects.filter(condition_categories)

        # 2. DICTIONNAIRE DU BUDGET : Montants par ID de catégorie pour CE budget
        categories_budget = ComptaCategorieBudget.objects.filter(budget=budget)
        dict_budgete = {cb.categorie_id: cb.montant for cb in categories_budget}

        # 3. DICTIONNAIRE DU RÉALISÉ : Ventilations cumulées par ID de catégorie
        condition_realise = (
                Q(operation__compte__in=comptes) &
                Q(operation__date__gte=budget.date_debut) &
                Q(operation__date__lte=budget.date_fin)
        )
        ventilations_data = ComptaVentilation.objects.filter(condition_realise) \
            .values("categorie") \
            .annotate(total=Sum("montant"))

        dict_realise = {v["categorie"]: v["total"] for v in ventilations_data if v["categorie"]}

        # --- Règlements encaissés par l'organisateur (ligne fictive au crédit) ---
        # Toutes les structures des comptes du budget, et non la première seulement.
        # La structure du budget n'est pas retenue : elle sert au cloisonnement des
        # droits, pas au périmètre d'analyse, qui suit les comptes comme le réalisé.
        structures = [s for s in comptes.values_list("structure", flat=True) if s]

        total_reglements_encaissement = decimal.Decimal("0")

        if structures:
            somme_data = Ventilation.objects.filter(
                reglement__mode__encaissement=True,
                prestation__activite__structure__in=structures,
                reglement__date__gte=budget.date_debut,
                reglement__date__lte=budget.date_fin,
            ).aggregate(total=Sum("montant"))

            total_reglements_encaissement = somme_data["total"] or decimal.Decimal("0")

        # 4. CONSTRUCTION DES LIGNES
        lignes = []
        regroupements = {}

        # Tri des catégories de base par type puis par nom
        categories_triees = sorted(toutes_les_categories, key=lambda x: (x.type, x.nom))

        for categorie in categories_triees:
            budgete = dict_budgete.get(categorie.pk, decimal.Decimal(0))
            realise = dict_realise.get(categorie.pk, decimal.Decimal(0))

            # Si rien en budget ET rien en réalisé, on n'affiche pas la catégorie
            if budgete == 0 and realise == 0:
                continue

            # Initialisation du regroupement parent (Débit ou Crédit)
            if categorie.type not in regroupements:
                regroupements[categorie.type] = {
                    "id": 1000000 + len(regroupements),
                    "pid": 0,
                    "regroupement": True,
                    "label": "Débit" if categorie.type == "debit" else "Crédit",
                    "realise": decimal.Decimal(0),
                    "budgete": decimal.Decimal(0)
                }
                lignes.append(regroupements[categorie.type])

            # Calculs des indicateurs de la ligne enfant
            pourcentage = (float(realise) * 100 / float(budgete)) if budgete else None
            ecart = (budgete - realise) if categorie.type == "debit" else (realise - budgete)

            # Cumul dans le totalisateur parent (Débit ou Crédit)
            regroupements[categorie.type]["realise"] += realise
            regroupements[categorie.type]["budgete"] += budgete

            lignes.append({
                "id": categorie.pk,
                "pid": regroupements[categorie.type]["id"],
                "regroupement": False,
                "label": categorie.nom,
                "realise": float(realise),
                "budgete": float(budgete),
                "pourcentage": pourcentage,
                "ecart": float(ecart),
            })

        # --- INJECTION DE LA LIGNE FICTIVE DANS LES CRÉDITS (Prise en compte dans les totaux) ---
        if total_reglements_encaissement > 0:
            type_fictif = "credit"
            # Sécurité au cas où aucune catégorie "crédit" n'était initialisée
            if type_fictif not in regroupements:
                regroupements[type_fictif] = {
                    "id": 1000000 + len(regroupements),
                    "pid": 0,
                    "regroupement": True,
                    "label": "Crédit",
                    "realise": decimal.Decimal(0),
                    "budgete": decimal.Decimal(0)
                }
                lignes.append(regroupements[type_fictif])

            # On AJOUTE le montant au cumul du total Crédit
            regroupements[type_fictif]["realise"] += total_reglements_encaissement

            # On insère la ligne fictive juste en dessous
            lignes.append({
                "id": 9999,
                "pid": regroupements[type_fictif]["id"],
                "regroupement": False,
                "label": "Règlements encaissés par l'organisateur (Chèque Vacances,...)",
                "realise": float(total_reglements_encaissement),
                "budgete": 0.0,
                "pourcentage": None,
                "ecart": float(total_reglements_encaissement),
            })

        # --- CALCUL ET FORMATTAGE FINAL DES TOTALISATIONS PARENTES ---
        for type_key, reg_line in regroupements.items():
            t_realise = reg_line["realise"]
            t_budgete = reg_line["budgete"]
            t_pourcentage = (float(t_realise) * 100 / float(t_budgete)) if t_budgete else None
            t_ecart = (t_budgete - t_realise) if type_key == "debit" else (t_realise - t_budgete)

            reg_line["realise"] = float(t_realise)
            reg_line["budgete"] = float(t_budgete)
            reg_line["pourcentage"] = t_pourcentage
            reg_line["ecart"] = float(t_ecart)

        # 5. AJOUT DU SOLDE GÉNÉRAL (Maintenant exact car basé sur les totaux à jour)
        total_realise = (regroupements["credit"]["realise"] if "credit" in regroupements else 0.0) - (
            regroupements["debit"]["realise"] if "debit" in regroupements else 0.0)
        total_budgete = (regroupements["credit"]["budgete"] if "credit" in regroupements else 0.0) - (
            regroupements["debit"]["budgete"] if "debit" in regroupements else 0.0)
        total_pourcentage = (float(total_realise) * 100 / float(total_budgete)) if total_budgete else None
        total_ecart = total_realise - total_budgete

        lignes.append({
            "id": 99999998,
            "pid": 99999999,
            "regroupement": False,
            "label": "SOLDE GENERAL",
            "realise": float(total_realise),
            "budgete": float(total_budgete),
            "pourcentage": total_pourcentage,
            "ecart": float(total_ecart)
        })

        # --- Totaux de la page : résultat du projet et contrepoint bancaire ---
        credit = regroupements.get("credit", {})
        debit = regroupements.get("debit", {})
        solde_bancaire = utils_rapprochement.Get_solde_bancaire(comptes, date_fin=budget.date_fin)
        resultat_projet = decimal.Decimal(str(total_realise))
        totaux = {
            "nom_budget": budget.nom,
            "date_debut": budget.date_debut,
            "date_fin": budget.date_fin,
            "total_recettes": _arrondi(credit.get("realise", 0)),
            "total_depenses": _arrondi(debit.get("realise", 0)),
            "recettes_budgetees": _arrondi(credit.get("budgete", 0)),
            "depenses_budgetees": _arrondi(debit.get("budgete", 0)),
            "resultat_projet": _arrondi(resultat_projet),
            "resultat_budgete": _arrondi(total_budgete),
            "ecart_resultat": _arrondi(decimal.Decimal(str(total_ecart))),
            "solde_bancaire": _arrondi(solde_bancaire),
            "ecart_projet_banque": _arrondi(resultat_projet - solde_bancaire),
        }

        return lignes, totaux