# -*- coding: utf-8 -*-
"""
Cohérence du Bilan financier et du Suivi du budget sur une comptabilité fictive.
"""

import datetime
import decimal

from django.test import TestCase, RequestFactory

from core.models import (ComptaAnalytique, ComptaBudget, ComptaCategorie, ComptaCategorieBudget,
                         ComptaOperation, ComptaVentilation, CompteBancaire, ModeReglement,
                         Structure, Utilisateur)

D = decimal.Decimal


class RapportsMixin:

    @classmethod
    def creer_donnees(cls):
        cls.structure = Structure.objects.create(nom="Groupe Rapport", actif=True)
        cls.autre_structure = Structure.objects.create(nom="Groupe Voisin", actif=True)
        cls.compte = CompteBancaire.objects.create(nom="Compte Rapport", structure=cls.structure)
        cls.compte_voisin = CompteBancaire.objects.create(nom="Compte Voisin", structure=cls.autre_structure)

        cls.analytique = ComptaAnalytique.objects.create(nom="GLOBAL")
        cls.mode = ModeReglement.objects.create(label="Virement")

        # Catégories : au bilan, et une hors bilan SANS structure (cas réel du jeu de données)
        cls.cat_dep = ComptaCategorie.objects.create(nom="Alimentation", type="debit", structure=cls.structure)
        cls.cat_rec = ComptaCategorie.objects.create(nom="Pensions", type="credit", structure=cls.structure)
        cls.cat_hors_bilan = ComptaCategorie.objects.create(
            nom="Recettes pour le Mouvement", type="credit", structure=None, bilan=False)

        cls.utilisateur = Utilisateur.objects.create_user(
            username="analyste", password="motdepasse", categorie="utilisateur", is_staff=True)
        cls.utilisateur.structures.add(cls.structure, cls.autre_structure)

        def ecrire(date, type_op, montant, categorie):
            operation = ComptaOperation.objects.create(
                compte=cls.compte, type=type_op, date=date, montant=D(montant),
                libelle="Ope %s" % date, mode=cls.mode)
            ComptaVentilation.objects.create(
                operation=operation, categorie=categorie, analytique=cls.analytique,
                montant=D(montant), date_budget=date)
            return operation

        # --- Exercice 2025 ---
        ecrire(datetime.date(2025, 5, 10), "debit", "100.00", cls.cat_dep)
        ecrire(datetime.date(2025, 6, 15), "credit", "300.00", cls.cat_rec)
        # --- Exercice 2026 ---
        ecrire(datetime.date(2026, 2, 10), "debit", "40.00", cls.cat_dep)
        ecrire(datetime.date(2026, 3, 20), "credit", "90.00", cls.cat_rec)
        # --- Hors bilan, sur 2026 ---
        ecrire(datetime.date(2026, 4, 1), "credit", "25.00", cls.cat_hors_bilan)

        # Budget 2026 uniquement
        cls.budget = ComptaBudget.objects.create(
            nom="Budget 2026", date_debut=datetime.date(2026, 1, 1),
            date_fin=datetime.date(2026, 12, 31), structure=cls.structure)
        cls.budget.compte.add(cls.compte)
        ComptaCategorieBudget.objects.create(budget=cls.budget, categorie=cls.cat_dep, montant=D("500.00"))
        ComptaCategorieBudget.objects.create(budget=cls.budget, categorie=cls.cat_rec, montant=D("1000.00"))

    def requete(self):
        requete = RequestFactory().post("/")
        requete.user = self.utilisateur
        return requete

    def enfants_par_groupe(self, lignes):
        """ Renvoie {label du groupe: [labels des lignes enfants, dans l'ordre d'affichage]} """
        parents = {l["id"]: l["label"] for l in lignes if l.get("regroupement")}
        groupes = {}
        for ligne in lignes:
            if not ligne.get("regroupement") and ligne["pid"] in parents:
                groupes.setdefault(parents[ligne["pid"]], []).append(ligne["label"])
        return groupes

    def creer_categories_orga(self):
        """ Deux catégories liées à l'organisateur, nommées pour arriver en TÊTE si le tri
            ne se faisait que sur le nom : elles doivent malgré tout finir en fin de groupe. """
        for nom, type_op in (("AAA Part organisateur", "credit"), ("AAA Cotisation Mouvement", "debit")):
            categorie = ComptaCategorie.objects.create(
                nom=nom, type=type_op, structure=self.structure, orga=True)
            operation = ComptaOperation.objects.create(
                compte=self.compte, type=type_op, date=datetime.date(2026, 6, 1),
                montant=D("5.00"), libelle=nom, mode=self.mode)
            ComptaVentilation.objects.create(
                operation=operation, categorie=categorie, analytique=self.analytique,
                montant=D("5.00"), date_budget=operation.date)


class TestBilanFinancier(RapportsMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.creer_donnees()

    def resultats(self, periode="1900-01-01;2030-12-31", comptes=None):
        from comptabilite.views import suivi_compta
        vue = suivi_compta.View()
        vue.request = self.requete()
        comptes = comptes if comptes is not None else CompteBancaire.objects.filter(pk=self.compte.pk)
        return vue.Get_resultats({"comptes": comptes, "periode": periode})

    def totaux(self, lignes):
        return {l["label"]: l["realise"] for l in lignes if l.get("regroupement")}

    def solde(self, lignes):
        return [l for l in lignes if l["label"] == "SOLDE GENERAL"][0]["realise"]

    def test_totaux_sur_tout_historique(self):
        lignes, _, _, _, _ = self.resultats()
        self.assertEqual(self.totaux(lignes), {"Débit": 140.0, "Crédit": 390.0})
        self.assertEqual(self.solde(lignes), 250.0)

    def test_filtre_de_periode(self):
        """ La période doit restreindre le bilan au seul exercice demandé """
        lignes, _, _, _, _ = self.resultats(periode="2026-01-01;2026-12-31")
        self.assertEqual(self.totaux(lignes), {"Débit": 40.0, "Crédit": 90.0})
        self.assertEqual(self.solde(lignes), 50.0)

    def test_periode_anterieure_vide(self):
        lignes, _, _, _, _ = self.resultats(periode="2020-01-01;2020-12-31")
        self.assertEqual(self.solde(lignes), 0.0)

    def test_categories_orga_classees_en_fin_de_groupe(self):
        """ Les catégories liées à l'organisateur se lisent après les catégories ordinaires """
        self.creer_categories_orga()
        groupes = self.enfants_par_groupe(self.resultats()[0])
        self.assertEqual(groupes["Crédit"][-1], "AAA Part organisateur")
        self.assertEqual(groupes["Débit"][-1], "AAA Cotisation Mouvement")
        self.assertGreater(len(groupes["Crédit"]), 1)
        self.assertGreater(len(groupes["Débit"]), 1)

    def test_categorie_hors_bilan_exclue_du_solde(self):
        lignes, _, _, _, _ = self.resultats()
        libelles = [l["label"] for l in lignes]
        self.assertNotIn("Recettes pour le Mouvement", libelles)

    def test_solde_hors_bilan_affiche_les_categories_sans_structure(self):
        """ Régression : la requête excluait les catégories partagées, le bloc restait vide """
        _, hors_bilan, _, _, _ = self.resultats()
        self.assertEqual(len(hors_bilan), 1)
        nom, montant, type_cat = hors_bilan[0]
        self.assertEqual(nom, "Recettes pour le Mouvement")
        self.assertEqual(montant, D("25.00"))

    def test_solde_hors_bilan_respecte_la_periode(self):
        _, hors_bilan, _, _, _ = self.resultats(periode="2025-01-01;2025-12-31")
        self.assertEqual(hors_bilan, [])

    def test_solde_sans_artefact_flottant(self):
        """ Les montants ne doivent pas ressortir en 15595.259999999998 """
        from comptabilite.views import suivi_compta
        vue = suivi_compta.View()
        vue.request = self.requete()
        operation = ComptaOperation.objects.create(
            compte=self.compte, type="credit", date=datetime.date(2026, 5, 1),
            montant=D("0.10"), libelle="Centimes", mode=self.mode)
        ComptaVentilation.objects.create(operation=operation, categorie=self.cat_rec,
                                         analytique=self.analytique, montant=D("0.10"),
                                         date_budget=operation.date)
        lignes, _, _, _, _ = self.resultats()
        valeur = self.solde(lignes)
        self.assertEqual(valeur, round(valeur, 2))
        operation.delete()

    def test_compte_sans_operation(self):
        lignes, hors_bilan, _, _, _ = self.resultats(
            comptes=CompteBancaire.objects.filter(pk=self.compte_voisin.pk))
        self.assertEqual(self.solde(lignes), 0.0)
        self.assertEqual(hors_bilan, [])


class TestSuiviBudget(RapportsMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.creer_donnees()

    def resultats(self):
        from comptabilite.views import suivi_budget
        vue = suivi_budget.View()
        vue.request = self.requete()
        return vue.Get_resultats({"budget": self.budget})[0]

    def lignes_par_label(self, lignes):
        return {l["label"]: l for l in lignes}

    def test_realise_limite_a_la_periode_du_budget(self):
        """ Les opérations 2025 ne doivent pas entrer dans le budget 2026 """
        lignes = self.lignes_par_label(self.resultats())
        self.assertEqual(lignes["Alimentation"]["realise"], 40.0)
        self.assertEqual(lignes["Pensions"]["realise"], 90.0)

    def test_montants_budgetes(self):
        lignes = self.lignes_par_label(self.resultats())
        self.assertEqual(lignes["Alimentation"]["budgete"], 500.0)
        self.assertEqual(lignes["Pensions"]["budgete"], 1000.0)

    def test_ecart_depense_positif_si_sous_le_budget(self):
        lignes = self.lignes_par_label(self.resultats())
        self.assertEqual(lignes["Alimentation"]["ecart"], 460.0)

    def test_ecart_recette_negatif_si_sous_le_budget(self):
        lignes = self.lignes_par_label(self.resultats())
        self.assertEqual(lignes["Pensions"]["ecart"], -910.0)

    def test_pourcentage(self):
        lignes = self.lignes_par_label(self.resultats())
        self.assertAlmostEqual(lignes["Alimentation"]["pourcentage"], 8.0)

    def test_pourcentage_absent_si_pas_de_budget(self):
        categorie = ComptaCategorie.objects.create(nom="Imprevu", type="debit", structure=self.structure)
        operation = ComptaOperation.objects.create(
            compte=self.compte, type="debit", date=datetime.date(2026, 5, 5),
            montant=D("10.00"), libelle="Imprevu", mode=self.mode)
        ComptaVentilation.objects.create(operation=operation, categorie=categorie,
                                         analytique=self.analytique, montant=D("10.00"),
                                         date_budget=operation.date)
        lignes = self.lignes_par_label(self.resultats())
        self.assertIsNone(lignes["Imprevu"]["pourcentage"])
        operation.delete()
        categorie.delete()

    def test_categorie_sans_budget_ni_realise_masquee(self):
        ComptaCategorie.objects.create(nom="Jamais utilisee", type="debit", structure=self.structure)
        lignes = self.lignes_par_label(self.resultats())
        self.assertNotIn("Jamais utilisee", lignes)

    def test_solde_general(self):
        lignes = self.lignes_par_label(self.resultats())
        # 90 de recettes + 25 hors bilan - 40 de dépenses.
        # Le Suivi du budget intègre les catégories hors bilan, contrairement au
        # Bilan financier qui les isole : différence de périmètre assumée.
        self.assertEqual(lignes["SOLDE GENERAL"]["realise"], 75.0)
        self.assertEqual(lignes["SOLDE GENERAL"]["budgete"], 500.0)

    def test_categories_orga_classees_en_fin_de_groupe(self):
        """ Les catégories liées à l'organisateur se lisent après les catégories ordinaires """
        self.creer_categories_orga()
        groupes = self.enfants_par_groupe(self.resultats())
        self.assertEqual(groupes["Crédit"][-1], "AAA Part organisateur")
        self.assertEqual(groupes["Débit"][-1], "AAA Cotisation Mouvement")
        self.assertGreater(len(groupes["Crédit"]), 1)
        self.assertGreater(len(groupes["Débit"]), 1)

    def test_categorie_hors_bilan_presente_dans_le_budget(self):
        lignes = self.lignes_par_label(self.resultats())
        self.assertIn("Recettes pour le Mouvement", lignes)

    def test_encaissements_limites_aux_structures_des_comptes(self):
        """ Régression : seule la structure du premier compte était prise en compte.
            On vérifie que la vue transmet bien TOUTES les structures de ses comptes
            à la recherche des règlements encaissés par l'organisateur. """
        from unittest import mock
        from comptabilite.views import suivi_budget

        self.budget.compte.add(self.compte_voisin)
        try:
            vue = suivi_budget.View()
            vue.request = self.requete()
            with mock.patch("comptabilite.views.suivi_budget.utils_compta.Get_reglements_encaissement",
                            return_value=[]) as recherche:
                vue.Get_resultats({"budget": self.budget})
            structures = recherche.call_args.kwargs["structures"]
            self.assertCountEqual(structures, [self.structure.pk, self.autre_structure.pk])
            # Le périmètre suit la période du budget
            self.assertEqual(recherche.call_args.kwargs["date_debut"], self.budget.date_debut)
            self.assertEqual(recherche.call_args.kwargs["date_fin"], self.budget.date_fin)
        finally:
            self.budget.compte.remove(self.compte_voisin)


class TestTotauxRapports(RapportsMixin, TestCase):
    """ Les totaux distinguent bien le résultat du projet du solde bancaire """

    @classmethod
    def setUpTestData(cls):
        cls.creer_donnees()
        # Une avance : réelle pour le projet, absente du compte bancaire
        cls.avance_compta = ComptaOperation.objects.create(
            compte=cls.compte, type="debit", date=datetime.date(2026, 5, 2),
            montant=D("30.00"), libelle="Avance materiel", mode=cls.mode,
            avance=cls.creer_avance(), regul_avance=False)
        ComptaVentilation.objects.create(
            operation=cls.avance_compta, categorie=cls.cat_dep, analytique=cls.analytique,
            montant=D("30.00"), date_budget=cls.avance_compta.date)

    @classmethod
    def creer_avance(cls):
        from core.models import ComptaAvance
        return ComptaAvance.objects.create(nom="Martin", structure=cls.structure)

    def totaux_bilan(self, periode="1900-01-01;2030-12-31"):
        from comptabilite.views import suivi_compta
        vue = suivi_compta.View()
        vue.request = self.requete()
        return vue.Get_resultats({
            "comptes": CompteBancaire.objects.filter(pk=self.compte.pk), "periode": periode})[4]

    def totaux_budget(self):
        from comptabilite.views import suivi_budget
        vue = suivi_budget.View()
        vue.request = self.requete()
        return vue.Get_resultats({"budget": self.budget})[1]

    def test_bilan_resultat_projet_inclut_les_avances(self):
        t = self.totaux_bilan()
        # recettes 390 - dépenses (140 + 30 d'avance) = 220
        self.assertEqual(t["total_recettes"], D("390.00"))
        self.assertEqual(t["total_depenses"], D("170.00"))
        self.assertEqual(t["resultat_projet"], D("220.00"))

    def test_bilan_solde_bancaire_exclut_les_avances(self):
        t = self.totaux_bilan()
        # Le compte bancaire ignore l'avance de 30 et la recette hors bilan de 25
        self.assertEqual(t["solde_bancaire"], D("275.00"))

    def test_bilan_ecart_projet_banque(self):
        t = self.totaux_bilan()
        # Sur tout l'historique, mouvements de la période = solde bancaire
        self.assertEqual(t["mouvements_bancaires"], t["solde_bancaire"])
        self.assertEqual(t["ecart_projet_banque"], t["resultat_projet"] - t["mouvements_bancaires"])
        self.assertEqual(t["ecart_projet_banque"], D("-55.00"))

    def test_bilan_ecart_sur_une_periode_ignore_le_report(self):
        """ Régression : le report 2025 (+200 en banque) gonflait l'écart d'une période 2026 """
        t = self.totaux_bilan(periode="2026-01-01;2026-12-31")
        # Résultat 2026 : 90 - 40 - 30 (avance) = 20 ; banque 2026 : 90 - 40 + 25 (hors bilan) = 75
        self.assertEqual(t["resultat_projet"], D("20.00"))
        self.assertEqual(t["mouvements_bancaires"], D("75.00"))
        self.assertEqual(t["solde_bancaire"], D("275.00"))
        self.assertEqual(t["ecart_projet_banque"], D("-55.00"))

    def test_bilan_total_hors_bilan(self):
        self.assertEqual(self.totaux_bilan()["total_hors_bilan"], D("25.00"))

    def test_budget_totaux(self):
        t = self.totaux_budget()
        self.assertEqual(t["nom_budget"], "Budget 2026")
        self.assertEqual(t["recettes_budgetees"], D("1000.00"))
        self.assertEqual(t["depenses_budgetees"], D("500.00"))

    def test_budget_resultat_et_solde_bancaire_different(self):
        t = self.totaux_budget()
        self.assertNotEqual(t["resultat_projet"], t["solde_bancaire"])
        # L'écart compare le réalisé du budget aux mouvements bancaires de la même période
        self.assertEqual(t["mouvements_bancaires"], D("75.00"))
        self.assertEqual(t["ecart_projet_banque"], t["resultat_projet"] - t["mouvements_bancaires"])
        # Le budget compte aussi la catégorie hors bilan : seul l'écart de l'avance (30) subsiste
        self.assertEqual(t["ecart_projet_banque"], D("-30.00"))
