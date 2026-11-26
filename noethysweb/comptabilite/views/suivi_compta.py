# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import json, decimal
from collections import Counter
from django.views.generic import TemplateView
from django.db.models import Q, Sum
from core.views.base import CustomView
from core.models import ComptaVentilation, ComptaCategorie, Deduction
from comptabilite.forms.suivi_compta import Formulaire
from core.utils import utils_dates
from comptabilite.utils import utils_rapprochement, utils_compta
from comptabilite.utils.utils_compta import Arrondi as _arrondi
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

        liste_lignes, soldes_hors_bilan, liste_deductions, liste_reglements_encaissement, totaux = self.Get_resultats(parametres=form.cleaned_data)
        context = {
            "form_parametres": form,
            "liste_lignes": json.dumps(liste_lignes),
            "soldes_hors_bilan": soldes_hors_bilan,
            "liste_deductions": liste_deductions,
            "liste_reglements_encaissement": liste_reglements_encaissement,
            "totaux": totaux,
        }
        return self.render_to_response(self.get_context_data(**context))

    def Get_resultats(self, parametres={}):
        comptes = parametres["comptes"]

        # Période d'analyse (par défaut tout l'historique)
        periode = parametres.get("periode") or ""
        date_debut, date_fin = utils_dates.ConvertDateRangePicker(periode) if ";" in periode else (None, None)
        condition_periode = Q()
        if date_debut:
            condition_periode &= Q(operation__date__gte=date_debut)
        if date_fin:
            condition_periode &= Q(operation__date__lte=date_fin)

        # Structures concernées (utilisées par plusieurs blocs ci-dessous)
        structures_comptes = [s for s in comptes.values_list("structure", flat=True) if s]
        structures_analysees = structures_comptes or list(
            self.request.user.structures.values_list("pk", flat=True))

        # Règlements encaissés par l'organisateur (chèques vacances, bons CAF...).
        # Calculés avant la construction des lignes car ils alimentent les recettes du bilan.
        liste_reglements_encaissement = utils_compta.Get_reglements_encaissement(
            structures=structures_analysees, date_debut=date_debut, date_fin=date_fin)

        condition_structure = (Q(structure__in=self.request.user.structures.all()) | Q(structure__isnull=True)) & Q(
            bilan=True)

        # Importation des catégories
        dict_categories = {categorie.pk: categorie for categorie in ComptaCategorie.objects.filter(condition_structure)}

        # Importation des ventilations
        condition = Q(operation__compte__in=comptes) & Q(categorie__bilan=True) & condition_periode
        ventilations_tresorerie = Counter({ventilation["categorie"]: ventilation["total"] for ventilation in
                                           ComptaVentilation.objects.values("categorie").filter(condition).annotate(
                                               total=Sum("montant"))})
        dict_realise = {dict_categories[idcategorie]: montant for idcategorie, montant in
                        dict(ventilations_tresorerie).items() if idcategorie in dict_categories}

        # Création des lignes de catégories
        categories = {**dict_realise}.keys()
        categories = sorted(categories, key=utils_compta.Cle_tri_categorie)

        # Création des lignes
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
                    "realise": decimal.Decimal(0)
                }
                # On ajoute la ligne parente directement
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

        for categorie in categories:
            # Création du regroupement (débit ou crédit) s'il n'existe pas encore
            Get_regroupement(categorie.type, categorie.get_type_display())

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
                "realise": float(_arrondi(realise)),
            })

        # Les règlements encaissés par l'organisateur (chèques vacances...) n'ont pas de
        # ventilation comptable sur les comptes bancaires, mais ils constituent bien une
        # recette du projet : on les ajoute comme lignes de crédit.
        label_encaissement = utils_compta.Get_label_encaissement()
        total_encaissement = decimal.Decimal(0)
        for index, bloc in enumerate(liste_reglements_encaissement):
            montant = decimal.Decimal(str(bloc["total"]))
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
            }, regroupement)

        # --- CALCUL DU SOLDE GÉNÉRAL (en Decimal, avant conversion en float) ---
        total_credit = regroupements.get("credit", {}).get("realise", decimal.Decimal(0))
        total_debit = regroupements.get("debit", {}).get("realise", decimal.Decimal(0))
        total_realise = total_credit - total_debit

        # --- FORMATTAGE DES LIGNES PARENTES POUR LE JSON ---
        for type_key, reg_line in regroupements.items():
            reg_line["realise"] = float(_arrondi(reg_line["realise"]))

        lignes.append({
            "id": 99999998,
            "pid": 99999999,
            "regroupement": False,
            "label": "SOLDE GENERAL",
            "realise": float(_arrondi(total_realise)),
        })

        # Soldes hors bilan
        # Les catégories partagées (sans structure) doivent être incluses, sinon ce bloc reste vide
        categories_hors_bilan = ComptaCategorie.objects.filter(
            Q(structure__in=structures_comptes) | Q(structure__isnull=True),
            bilan=False
        ).order_by("type", "nom")
        soldes_hors_bilan = []
        for cat in categories_hors_bilan:
            solde = ComptaVentilation.objects.filter(
                condition_periode,
                operation__compte__in=comptes,
                categorie=cat
            ).aggregate(total=Sum("montant"))["total"]
            # On n'affiche que les catégories réellement mouvementées sur la période
            if solde:
                soldes_hors_bilan.append((cat.nom, solde, cat.type))

        # --- Bloc déductions non remboursées ---######

        # Restreint aux structures des comptes analysés, et à la période
        deductions = Deduction.objects.filter(
            label__structure__in=structures_analysees,
            remb=False
        ).select_related("label", "famille", "prestation", "prestation__activite").order_by("label__nom")
        # Un encours : on retient tout ce qui reste dû à la fin de la période,
        # y compris les déductions antérieures, et non les seules de la période.
        if date_fin:
            deductions = deductions.filter(prestation__date__lte=date_fin)

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



        # --- Totaux de la page : résultat du projet et contrepoint bancaire ---
        total_hors_bilan = sum((montant for _, montant, _ in soldes_hors_bilan), decimal.Decimal(0))
        solde_bancaire = utils_rapprochement.Get_solde_bancaire(comptes, date_fin=date_fin)
        # Le résultat ne couvre que la période : on le compare à la variation du solde
        # bancaire sur cette même période, et non au solde cumulé depuis l'origine.
        mouvements_bancaires = utils_rapprochement.Get_mouvements_bancaires(comptes, date_debut=date_debut, date_fin=date_fin)
        totaux = {
            "total_recettes": _arrondi(total_credit),
            "total_depenses": _arrondi(total_debit),
            "resultat_projet": _arrondi(total_realise),
            "total_hors_bilan": _arrondi(total_hors_bilan),
            "solde_bancaire": _arrondi(solde_bancaire),
            "mouvements_bancaires": _arrondi(mouvements_bancaires),
            # Les règlements encaissés par l'organisateur comptent dans le résultat mais ne
            # transitent pas par les comptes : on les neutralise pour que l'écart reste lisible.
            "total_encaissement": _arrondi(total_encaissement),
            "label_encaissement": label_encaissement,
            "ecart_projet_banque": _arrondi(total_realise - total_encaissement - mouvements_bancaires),
            "date_debut": date_debut,
            "date_fin": date_fin,
        }

        # Retourne le tout avec les autres infos existantes
        return lignes, soldes_hors_bilan, liste_deductions, liste_reglements_encaissement, totaux
