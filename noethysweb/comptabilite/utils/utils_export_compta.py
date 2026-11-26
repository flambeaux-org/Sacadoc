# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

"""Génération d'un classeur Excel de suivi du budget (feuilles Recettes et Dépenses).

Le classeur reprend la mise en forme du tableau de suivi du budget utilisé par
le Mouvement afin de faciliter la retranscription des opérations de trésorerie.
"""

import io, unicodedata
from collections import defaultdict
from django.db.models import Q
from core.models import ComptaCategorie, ComptaOperation, ComptaVentilation


# Nombre minimum de lignes (formules de cumul incluses) présentes dans chaque feuille
NBRE_LIGNES_MINI = 150

# Index des colonnes fixes (0-based)
COL_DATE = 0
COL_NUM = 1
COL_OBJET = 2
COL_CAISSE_MONTANT = 3
COL_CAISSE_CUMUL = 4
COL_BANQUE_DATE = 5
COL_BANQUE_MONTANT = 6
COL_BANQUE_CUMUL = 7
COL_VENTILATION = 8

# Première ligne de données (0-based) : ligne 1 = totaux, ligne 2 = entêtes
LIGNE_DONNEES = 2


def Sans_accents(texte=""):
    return "".join(c for c in unicodedata.normalize("NFD", texte or "") if unicodedata.category(c) != "Mn").lower()


def Est_especes(operation=None):
    """Une opération réglée en espèces est affectée à la caisse, les autres à la banque"""
    if not operation.mode_id:
        return False
    return "espece" in Sans_accents(operation.mode.label)


class Exporter():
    def __init__(self, compte=None, date_debut=None, date_fin=None, structures=None):
        self.compte = compte
        self.date_debut = date_debut
        self.date_fin = date_fin
        self.structures = structures

    def Get_operations(self, type_operation=""):
        return ComptaOperation.objects.select_related("mode", "releve").filter(
            compte=self.compte, type=type_operation,
            date__gte=self.date_debut, date__lte=self.date_fin,
        ).order_by("date", "num_piece", "idoperation")

    def Get_ventilations(self, operations=[]):
        """Renvoie {idoperation: {idcategorie: montant}}"""
        dict_ventilations = defaultdict(lambda: defaultdict(float))
        for ventilation in ComptaVentilation.objects.filter(operation__in=operations):
            dict_ventilations[ventilation.operation_id][ventilation.categorie_id] += float(ventilation.montant or 0)
        return dict_ventilations

    def Get_categories(self, type_operation="", dict_ventilations={}):
        """Catégories affichées en colonnes : celles visibles par l'utilisateur + celles réellement utilisées"""
        condition = Q(structure__in=self.structures) | Q(structure__isnull=True)
        idcategories = set()
        for ventilations in dict_ventilations.values():
            idcategories.update(ventilations.keys())
        categories = ComptaCategorie.objects.filter(Q(type=type_operation) & (condition | Q(pk__in=idcategories)))
        return sorted(categories, key=lambda categorie: Sans_accents(categorie.nom))

    def Generer(self):
        import xlsxwriter
        from xlsxwriter.utility import xl_col_to_name

        buffer = io.BytesIO()
        classeur = xlsxwriter.Workbook(buffer, {"in_memory": True, "default_date_format": "dd/mm/yyyy"})

        format_titre = classeur.add_format({"bold": True, "align": "center", "valign": "vcenter", "border": 1, "bg_color": "#DDDDDD"})
        format_total = classeur.add_format({"bold": True, "align": "center", "valign": "vcenter", "border": 1, "bg_color": "#DDDDDD", "num_format": "#,##0.00"})
        format_entete = classeur.add_format({"bold": True, "align": "center", "valign": "vcenter", "border": 1, "text_wrap": True, "bg_color": "#EFEFEF"})
        format_date = classeur.add_format({"border": 1, "align": "center", "num_format": "dd/mm/yyyy"})
        format_num = classeur.add_format({"border": 1, "align": "center"})
        format_texte = classeur.add_format({"border": 1})
        format_montant = classeur.add_format({"border": 1, "num_format": "#,##0.00"})
        format_cumul = classeur.add_format({"border": 1, "num_format": "#,##0.00", "bg_color": "#F7F7F7"})
        format_verif = classeur.add_format({"border": 1, "num_format": "#,##0.00", "bg_color": "#FFF7E0"})

        for type_operation, titre_feuille, titre_colonne, largeur_objet in (("credit", "Recettes", "RECETTES", 36), ("debit", "Dépenses", "DEPENSES", 50)):
            operations = list(self.Get_operations(type_operation=type_operation))
            dict_ventilations = self.Get_ventilations(operations=operations)
            categories = self.Get_categories(type_operation=type_operation, dict_ventilations=dict_ventilations)

            feuille = classeur.add_worksheet(titre_feuille)
            col_verif = COL_VENTILATION + len(categories)
            nbre_lignes = max(NBRE_LIGNES_MINI, len(operations))
            derniere_ligne = LIGNE_DONNEES + nbre_lignes - 1

            # Largeurs de colonnes
            feuille.set_column(COL_DATE, COL_DATE, 11.5)
            feuille.set_column(COL_NUM, COL_NUM, 8)
            feuille.set_column(COL_OBJET, COL_OBJET, largeur_objet)
            feuille.set_column(COL_CAISSE_MONTANT, COL_BANQUE_CUMUL, 11.5)
            if categories:
                feuille.set_column(COL_VENTILATION, col_verif, 15.5)
            else:
                feuille.set_column(col_verif, col_verif, 15.5)
            feuille.freeze_panes(LIGNE_DONNEES, COL_CAISSE_MONTANT)

            # Ligne 1 : intitulés des blocs et totaux par catégorie
            feuille.write(0, COL_OBJET, titre_colonne, format_titre)
            feuille.merge_range(0, COL_CAISSE_MONTANT, 0, COL_CAISSE_CUMUL, "CAISSE", format_titre)
            feuille.merge_range(0, COL_BANQUE_DATE, 0, COL_BANQUE_CUMUL, "BANQUE", format_titre)
            for index in range(len(categories)):
                colonne = xl_col_to_name(COL_VENTILATION + index)
                feuille.write_formula(0, COL_VENTILATION + index, "=SUM(%s%d:%s%d)" % (colonne, LIGNE_DONNEES + 1, colonne, derniere_ligne + 1), format_total)

            # Ligne 2 : entêtes de colonnes
            feuille.set_row(1, 60)
            for colonne, label in ((COL_DATE, "Date"), (COL_NUM, "N°"), (COL_OBJET, "Objet"), (COL_CAISSE_MONTANT, "Montant"),
                                   (COL_CAISSE_CUMUL, "Cumul"), (COL_BANQUE_DATE, "Date relevé"), (COL_BANQUE_MONTANT, "Montant"),
                                   (COL_BANQUE_CUMUL, "Cumul")):
                feuille.write(1, colonne, label, format_entete)
            for index, categorie in enumerate(categories):
                feuille.write(1, COL_VENTILATION + index, categorie.nom, format_entete)
            feuille.write(1, col_verif, "Vérification ventilation", format_entete)

            # Lignes de données
            for index_ligne in range(nbre_lignes):
                ligne = LIGNE_DONNEES + index_ligne
                num_ligne = ligne + 1
                operation = operations[index_ligne] if index_ligne < len(operations) else None

                if operation:
                    especes = Est_especes(operation)
                    feuille.write_datetime(ligne, COL_DATE, operation.date, format_date)
                    feuille.write(ligne, COL_NUM, operation.num_piece or index_ligne + 1, format_num)
                    feuille.write(ligne, COL_OBJET, operation.libelle or "", format_texte)
                    montant = float(operation.montant or 0)
                    if especes:
                        feuille.write_number(ligne, COL_CAISSE_MONTANT, montant, format_montant)
                        feuille.write_blank(ligne, COL_BANQUE_DATE, None, format_date)
                        feuille.write_blank(ligne, COL_BANQUE_MONTANT, None, format_montant)
                    else:
                        feuille.write_blank(ligne, COL_CAISSE_MONTANT, None, format_montant)
                        date_releve = operation.releve.date_fin if operation.releve_id else operation.date
                        feuille.write_datetime(ligne, COL_BANQUE_DATE, date_releve, format_date)
                        feuille.write_number(ligne, COL_BANQUE_MONTANT, montant, format_montant)
                    ventilations = dict_ventilations.get(operation.pk, {})
                    for index, categorie in enumerate(categories):
                        if categorie.pk in ventilations:
                            feuille.write_number(ligne, COL_VENTILATION + index, ventilations[categorie.pk], format_montant)
                        else:
                            feuille.write_blank(ligne, COL_VENTILATION + index, None, format_montant)
                else:
                    for colonne in (COL_NUM, COL_OBJET):
                        feuille.write_blank(ligne, colonne, None, format_texte if colonne == COL_OBJET else format_num)
                    for colonne in (COL_DATE, COL_BANQUE_DATE):
                        feuille.write_blank(ligne, colonne, None, format_date)
                    for colonne in [COL_CAISSE_MONTANT, COL_BANQUE_MONTANT] + [COL_VENTILATION + index for index in range(len(categories))]:
                        feuille.write_blank(ligne, colonne, None, format_montant)

                # Cumuls
                if index_ligne == 0:
                    formule_caisse = "=%s%d" % (xl_col_to_name(COL_CAISSE_MONTANT), num_ligne)
                    formule_banque = "=%s%d" % (xl_col_to_name(COL_BANQUE_MONTANT), num_ligne)
                else:
                    formule_caisse = "=%s%d+%s%d" % (xl_col_to_name(COL_CAISSE_MONTANT), num_ligne, xl_col_to_name(COL_CAISSE_CUMUL), num_ligne - 1)
                    formule_banque = "=%s%d+%s%d" % (xl_col_to_name(COL_BANQUE_MONTANT), num_ligne, xl_col_to_name(COL_BANQUE_CUMUL), num_ligne - 1)
                feuille.write_formula(ligne, COL_CAISSE_CUMUL, formule_caisse, format_cumul)
                feuille.write_formula(ligne, COL_BANQUE_CUMUL, formule_banque, format_cumul)

                # Vérification de la ventilation : montant de l'opération - somme des ventilations
                if categories:
                    formule_verif = "=(%s%d+%s%d)-SUM(%s%d:%s%d)" % (
                        xl_col_to_name(COL_CAISSE_MONTANT), num_ligne, xl_col_to_name(COL_BANQUE_MONTANT), num_ligne,
                        xl_col_to_name(COL_VENTILATION), num_ligne, xl_col_to_name(col_verif - 1), num_ligne)
                else:
                    formule_verif = "=%s%d+%s%d" % (xl_col_to_name(COL_CAISSE_MONTANT), num_ligne, xl_col_to_name(COL_BANQUE_MONTANT), num_ligne)
                feuille.write_formula(ligne, col_verif, formule_verif, format_verif)

        classeur.close()
        return buffer.getvalue()
