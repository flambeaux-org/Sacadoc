# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import json, decimal
from collections import Counter
from django.views.generic import TemplateView
from django.db.models import Q, Sum
from core.views.base import CustomView
from core.models import ComptaVentilation, ComptaOperationBudgetaire, ComptaCategorieBudget, ComptaCategorie, CompteBancaire, Deduction, TypeDeduction, Reglement, Activite, Prestation, Famille
from comptabilite.forms.suivi_compta import Formulaire
from collections import defaultdict



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

        condition_structure = (Q(structure__in=self.request.user.structures.all()) | Q(structure__isnull=True)) & Q(bilan=True)

        # Importation des catégories
        dict_categories = {categorie.pk: categorie for categorie in ComptaCategorie.objects.filter(condition_structure)}

        # Importation des ventilations
        condition = Q(operation__compte__in=comptes) & Q(categorie__bilan=True)
        ventilations_tresorerie = Counter({ventilation["categorie"]: ventilation["total"] for ventilation in ComptaVentilation.objects.values("categorie").filter(condition).annotate(total=Sum("montant"))})
        dict_realise = {dict_categories[idcategorie]: montant for idcategorie, montant in dict(ventilations_tresorerie).items()}

        # Création des lignes de catégories
        categories = {**dict_realise}.keys()
        categories = sorted(categories, key=lambda x: (x.type, x.nom))

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

            # Mémorisation pour ligne de total
            regroupements[categorie.type]["realise"] += realise

            # Création de la ligne
            lignes.append({"id": categorie.pk, "pid": regroupements[categorie.type]["id"], "regroupement": False,
                           "label": categorie.nom,
                           "realise": float(realise),
                           })

        # Ligne de total
        total_realise = (regroupements.get("credit", {}).get("realise", decimal.Decimal(0))
                         - regroupements.get("debit", {}).get("realise", decimal.Decimal(0)))

        lignes.append({
            "id": 99999998,
            "regroupement": True,
            "label": "Total",
            "realise": float(total_realise),  # <-- on injecte le total ici
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
        regroupements = {}

        for type_deduction, deds in deductions_grouped.items():
            # Création du regroupement par type
            if type_deduction.pk not in regroupements:
                regroupements[type_deduction.pk] = {
                    "id": 2000000 + len(regroupements),
                    "total": decimal.Decimal(0)
                }
                # ligne de regroupement
                liste_deductions.append({
                    "id": regroupements[type_deduction.pk]["id"],
                    "pid": 0,
                    "regroupement": True,
                    "label": f"{type_deduction.nom}",
                    "total": 0
                })

            # Ajout des déductions individuelles
            for ded in deds:
                liste_deductions.append({
                    "id": ded.iddeduction,
                    "pid": regroupements[type_deduction.pk]["id"],
                    "regroupement": False,
                    "label": f"{ded.famille.nom} : {ded.montant}€ ({ded.prestation.activite.nom})",
                    "montant": float(ded.montant)
                })
                regroupements[type_deduction.pk]["total"] += ded.montant

            # Mise à jour du total du regroupement
            for ligne in liste_deductions:
                if ligne.get("id") == regroupements[type_deduction.pk]["id"]:
                    ligne["total"] = float(regroupements[type_deduction.pk]["total"])
                    break

        # --- Nouveau bloc : récupère les règlements avec encaissement=True ---
        # --- Ajout des règlements encaissement comme catégorie spéciale ---
        compte = comptes.first()  # récupère le premier compte du queryset
        structure = compte.structure  # structure associée
        reglements_encaissement = Reglement.objects.filter(
            mode__encaissement=True,
            ventilation__prestation__activite__structure=structure
        ).distinct().select_related('famille', 'mode', 'compte').order_by('date')

        # On les regroupe par mode
        reglements_par_mode = defaultdict(list)
        for reglement in reglements_encaissement:
            reglements_par_mode[reglement.mode.label].append({
                "id": reglement.idreglement,
                "date": reglement.date.strftime("%d/%m/%Y") if reglement.date else "",
                "compte": reglement.compte.nom if reglement.compte else "",
                "famille": reglement.famille.nom if reglement.famille else "",
                "montant": float(reglement.montant or 0),
            })

        # Pour l'envoyer au template sous forme triée par mode
        liste_reglements_encaissement = []
        for mode_label in sorted(reglements_par_mode.keys()):
            liste_regs = reglements_par_mode[mode_label]
            total = sum(r["montant"] for r in liste_regs)  # <-- ici on prend la clé "montant"
            liste_reglements_encaissement.append({
                "mode": mode_label,
                "reglements": liste_regs,
                "total": total
            })

        # Retourne le tout avec les autres infos existantes
        return lignes, soldes_hors_bilan, liste_deductions, liste_reglements_encaissement