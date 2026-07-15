# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import json, decimal
from collections import Counter
from django.views.generic import TemplateView
from django.db.models import Q, Sum
from core.views.base import CustomView
from core.models import ComptaVentilation, ComptaOperationBudgetaire, ComptaCategorieBudget, ComptaCategorie, CompteBancaire, Deduction, TypeDeduction, Reglement, Activite, Prestation, Famille, Ventilation
from comptabilite.forms.suivi_compta import Formulaire
from collections import defaultdict
from collections import defaultdict
import decimal


class View(CustomView, TemplateView):
    menu_code = "suivi_compta"
    template_name = "comptabilite/suivi_compta.html"

    def get_context_data(self, **kwargs):
        context = super(View, self).get_context_data(**kwargs)
        context['page_titre'] = "Suivi des finances"
        context['afficher_menu_brothers'] = True
        if "form_parametres" not in kwargs:
            context['form_parametres'] = Formulaire(request=self.request)
        context.update(kwargs)
        return context

    def post(self, request, **kwargs):
        form = Formulaire(request.POST, request=self.request)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form_parametres=form))

        liste_lignes, soldes_hors_bilan, liste_deductions, liste_reglements_encaissement = self.Get_resultats(parametres=form.cleaned_data)
        context = {
            "form_parametres": form,
            "liste_lignes": json.dumps(liste_lignes),
            "soldes_hors_bilan": soldes_hors_bilan,
            "liste_deductions": liste_deductions,
            "liste_reglements_encaissement": liste_reglements_encaissement,
        }
        return self.render_to_response(self.get_context_data(**context))

    def Get_resultats(self, parametres={}):
        comptes = parametres["comptes"]

        condition_structure = (Q(structure__in=self.request.user.structures.all()) | Q(structure__isnull=True)) & Q(
            bilan=True)

        # Importation des catégories
        dict_categories = {categorie.pk: categorie for categorie in ComptaCategorie.objects.filter(condition_structure)}

        # Importation des ventilations
        condition = Q(operation__compte__in=comptes) & Q(categorie__bilan=True)
        ventilations_tresorerie = Counter({ventilation["categorie"]: ventilation["total"] for ventilation in
                                           ComptaVentilation.objects.values("categorie").filter(condition).annotate(
                                               total=Sum("montant"))})
        dict_realise = {dict_categories[idcategorie]: montant for idcategorie, montant in
                        dict(ventilations_tresorerie).items() if idcategorie in dict_categories}

        # Création des lignes de catégories
        categories = {**dict_realise}.keys()
        categories = sorted(categories, key=lambda x: (x.type, x.nom))

        # Création des lignes
        lignes = []
        regroupements = {}
        for categorie in categories:
            # Création du regroupement (débit ou crédit) s'il n'existe pas encore
            if not categorie.type in regroupements:
                regroupements[categorie.type] = {
                    "id": 1000000 + len(regroupements),
                    "pid": 0,
                    "regroupement": True,
                    "label": categorie.get_type_display(),
                    "realise": decimal.Decimal(0)
                }
                # On ajoute la ligne parente directement
                lignes.append(regroupements[categorie.type])

            # Calcul des données de la ligne enfant
            realise = dict_realise.get(categorie, decimal.Decimal(0))

            # Mémorisation et cumul pour la ligne de total parent
            regroupements[categorie.type]["realise"] += realise

            # Création de la ligne enfant
            lignes.append({
                "id": categorie.pk,
                "pid": regroupements[categorie.type]["id"],
                "regroupement": False,
                "label": categorie.nom,
                "realise": float(realise),
            })

        # --- FORMATTAGE DES LIGNES PARENTES POUR LE JSON ---
        for type_key, reg_line in regroupements.items():
            reg_line["realise"] = float(reg_line["realise"])

        # --- CALCUL ET AJOUT DE LA LIGNE DE SOLDE GÉNÉRAL ---
        total_credit = regroupements.get("credit", {}).get("realise", 0.0)
        total_debit = regroupements.get("debit", {}).get("realise", 0.0)
        total_realise = total_credit - total_debit

        lignes.append({
            "id": 99999998,
            "pid": 99999999,
            "regroupement": False,
            "label": "SOLDE GENERAL",
            "realise": float(total_realise),
        })

        # Soldes hors bilan
        categories_hors_bilan = ComptaCategorie.objects.filter(
            structure__in=comptes.values_list('structure', flat=True),
            bilan=False
        )
        soldes_hors_bilan = []
        for cat in categories_hors_bilan:
            solde = ComptaVentilation.objects.filter(
                operation__compte__in=comptes,
                categorie=cat
            ).aggregate(total=Sum("montant"))["total"] or decimal.Decimal(0)
            soldes_hors_bilan.append((cat.nom, solde, cat.type))  # <-- tuple au lieu de string

        # --- Bloc déductions non remboursées ---######

        deductions = Deduction.objects.filter(
            label__structure__in=self.request.user.structures.all(),
            remb=False
        ).select_related("label", "famille").order_by("label__nom")

        # On regroupe par TypeDeduction (label)
        deductions_grouped = defaultdict(list)
        for ded in deductions:
            deductions_grouped[ded.label].append(ded)

        # Préparation des lignes pour affichage
        liste_deductions = []
        regroupements_deductions = {}  # Changement de nom pour éviter d'écraser la variable précédente

        for type_deduction, deds in deductions_grouped.items():
            # Création du regroupement par type
            if type_deduction.pk not in regroupements_deductions:
                regroupements_deductions[type_deduction.pk] = {
                    "id": 2000000 + len(regroupements_deductions),
                    "total": decimal.Decimal(0)
                }
                # ligne de regroupement
                liste_deductions.append({
                    "id": regroupements_deductions[type_deduction.pk]["id"],
                    "pid": 0,
                    "regroupement": True,
                    "label": f"{type_deduction.nom}",
                    "total": 0
                })

            # Ajout des déductions individuelles
            for ded in deds:
                liste_deductions.append({
                    "id": ded.iddeduction,
                    "pid": regroupements_deductions[type_deduction.pk]["id"],
                    "regroupement": False,
                    "label": f"{ded.famille.nom} : {ded.montant}€ ({ded.prestation.activite.nom})",
                    "montant": float(ded.montant)
                })
                regroupements_deductions[type_deduction.pk]["total"] += ded.montant

            # Mise à jour du total du regroupement
            for ligne in liste_deductions:
                if ligne.get("id") == regroupements_deductions[type_deduction.pk]["id"]:
                    ligne["total"] = float(regroupements_deductions[type_deduction.pk]["total"])
                    break



        # --- Nouveau bloc : récupère les ventilations avec encaissement=True ---
        compte = comptes.first()
        structure = compte.structure if compte else None

        liste_reglements_encaissement = []

        if structure:
            ventilations = (
                Ventilation.objects.filter(
                    reglement__mode__encaissement=True,
                    prestation__activite__structure=structure,
                )
                .select_related(
                    "reglement",
                    "reglement__famille",
                    "reglement__mode",
                    "reglement__compte",
                )
                .order_by("reglement__date")
            )

            # On regroupe par mode de règlement
            reglements_par_mode = defaultdict(list)

            for v in ventilations:
                reglement = v.reglement

                reglements_par_mode[reglement.mode.label].append({
                    "id": reglement.idreglement,
                    "date": reglement.date.strftime("%d/%m/%Y") if reglement.date else "",
                    "compte": reglement.compte.nom if reglement.compte else "",
                    "famille": reglement.famille.nom if reglement.famille else "",
                    "montant": float(v.montant or 0),
                })

            # Format final pour template
            for mode_label in sorted(reglements_par_mode.keys()):
                liste_regs = reglements_par_mode[mode_label]

                total = sum(r["montant"] for r in liste_regs)

                liste_reglements_encaissement.append({
                    "mode": mode_label,
                    "reglements": liste_regs,
                    "total": total
                })

        # Retourne le tout avec les autres infos existantes
        return lignes, soldes_hors_bilan, liste_deductions, liste_reglements_encaissement