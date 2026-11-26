# -*- coding: utf-8 -*-
"""
Jeu de comptabilité fictive couvrant tous les cas de figure du module,
et vérification de la cohérence du rapprochement et des contrôles.

Écrit en django.test.TestCase pour être exécutable à la fois par
`manage.py test` et par la suite pytest du projet.
"""

import datetime
import decimal

from django.test import TestCase
from django.urls import reverse

from core.models import (ComptaAnalytique, ComptaAvance, ComptaCategorie, ComptaOperation,
                         ComptaVentilation, ComptaVirement, CompteBancaire, Deduction, Famille,
                         ModeReglement, Prestation, Structure, TypeDeduction, Utilisateur)

D = decimal.Decimal


class ComptaFictiveMixin:
    """ Construit une comptabilité fictive couvrant tous les cas de figure """

    @classmethod
    def creer_compta(cls):
        cls.structure = Structure.objects.create(nom="Groupe Test", actif=True)
        cls.compte = CompteBancaire.objects.create(nom="Compte Test", structure=cls.structure)
        cls.compte2 = CompteBancaire.objects.create(nom="Compte Second", structure=cls.structure)

        cls.analytique = ComptaAnalytique.objects.create(nom="GLOBAL")
        cls.cat_dep = ComptaCategorie.objects.create(nom="Alimentation", type="debit", structure=cls.structure)
        cls.cat_rec = ComptaCategorie.objects.create(nom="Pensions", type="credit", structure=cls.structure)
        cls.cat_orga = ComptaCategorie.objects.create(nom="Part Mouvement", type="credit",
                                                      structure=cls.structure, orga=True)
        cls.mode = ModeReglement.objects.create(label="Virement")
        cls.avance = ComptaAvance.objects.create(nom="Dupont", structure=cls.structure)

        jour = datetime.date(2026, 3, 10)

        def operation(**kwargs):
            kwargs.setdefault("compte", cls.compte)
            kwargs.setdefault("date", jour)
            kwargs.setdefault("mode", cls.mode)
            return ComptaOperation.objects.create(**kwargs)

        def ventiler(op, categorie, montant):
            return ComptaVentilation.objects.create(
                operation=op, categorie=categorie, analytique=cls.analytique,
                montant=D(montant), date_budget=op.date)

        # --- Opérations bancaires correctement tenues ---
        cls.op_dep_ok = operation(type="debit", montant=D("100.00"), libelle="Courses",
                                  num_piece="1", document="justifs/courses.pdf")
        ventiler(cls.op_dep_ok, cls.cat_dep, "100.00")

        cls.op_rec_ok = operation(type="credit", montant=D("200.00"), libelle="Pension famille A")
        ventiler(cls.op_rec_ok, cls.cat_rec, "200.00")

        # --- Dépense mal ventilée (30 au lieu de 50) ---
        cls.op_dep_mal = operation(type="debit", montant=D("50.00"), libelle="Materiel",
                                   num_piece="2", document="justifs/materiel.pdf")
        ventiler(cls.op_dep_mal, cls.cat_dep, "30.00")

        # --- Recette sans aucune ventilation ---
        cls.op_rec_sans_vent = operation(type="credit", montant=D("40.00"), libelle="Don anonyme")

        # --- Hors relevé : encaissé par le Mouvement ---
        cls.op_orga = operation(type="credit", montant=D("60.00"), libelle="Part Mouvement")
        ventiler(cls.op_orga, cls.cat_orga, "60.00")

        # --- Hors relevé : avance payée personnellement ---
        cls.op_avance = operation(type="debit", montant=D("80.00"), libelle="Avance Dupont",
                                  avance=cls.avance, regul_avance=False)
        ventiler(cls.op_avance, cls.cat_dep, "80.00")

        # --- Mouvement bancaire : régularisation de l'avance (sans ventilation, normal) ---
        cls.op_regul = operation(type="debit", montant=D("80.00"), libelle="Regularisation avances",
                                 avance=cls.avance, regul_avance=True, remb_avance=1)

        # --- Virement interne (sans ventilation, normal) ---
        cls.virement = ComptaVirement.objects.create(
            date=jour, montant=D("25.00"), libelle="Virement interne",
            compte_debit=cls.compte, compte_credit=cls.compte2)
        cls.op_vir_debit = operation(type="debit", montant=D("25.00"), libelle="Virement interne",
                                     virement=cls.virement)
        cls.op_vir_credit = operation(type="credit", montant=D("25.00"), libelle="Virement interne",
                                      compte=cls.compte2, virement=cls.virement)
        cls.virement.operation_debit = cls.op_vir_debit
        cls.virement.operation_credit = cls.op_vir_credit
        cls.virement.save()

        # --- Doublons probables (aucune référence externe) ---
        cls.op_doublon_a = operation(type="credit", montant=D("10.00"), libelle="Reglement famille B")
        ventiler(cls.op_doublon_a, cls.cat_rec, "10.00")
        cls.op_doublon_b = operation(type="credit", montant=D("10.00"), libelle="Reglement famille B")
        ventiler(cls.op_doublon_b, cls.cat_rec, "10.00")

        # --- Faux doublons : références de paiement distinctes ---
        cls.op_stripe_a = operation(type="credit", montant=D("5.00"), libelle="Paiement en ligne",
                                    ref_piece="cs_aaa")
        ventiler(cls.op_stripe_a, cls.cat_rec, "5.00")
        cls.op_stripe_b = operation(type="credit", montant=D("5.00"), libelle="Paiement en ligne",
                                    ref_piece="cs_bbb")
        ventiler(cls.op_stripe_b, cls.cat_rec, "5.00")

        # --- Opération sans mode de règlement ---
        cls.op_sans_mode = operation(type="credit", montant=D("15.00"), libelle="Espece trouvee", mode=None)
        ventiler(cls.op_sans_mode, cls.cat_rec, "15.00")

        # --- Dépense sans pièce justificative ---
        cls.op_sans_justif = operation(type="debit", montant=D("20.00"), libelle="Essence", num_piece="3")
        ventiler(cls.op_sans_justif, cls.cat_dep, "20.00")

    @classmethod
    def creer_utilisateurs(cls):
        cls.comptable = Utilisateur.objects.create_user(
            username="comptable", password="motdepasse", categorie="utilisateur", is_staff=True)
        cls.comptable.structures.add(cls.structure)
        cls.intrus = Utilisateur.objects.create_user(
            username="intrus", password="motdepasse", categorie="utilisateur", is_staff=True)
        cls.intrus.structures.add(cls.structure)

        from django.contrib.auth.models import Permission
        from django.contrib.contenttypes.models import ContentType
        ct = ContentType.objects.get_for_model(Utilisateur)
        for codename in ("verification_compta_liste", "operations_tresorerie_liste", "virements_liste",
                         "comptabilite_liste_comptes", "suivi_compta", "liste_ventilation",
                         "correction_compte", "avances_regul", "edition_justifs", "suivi_budget"):
            perm, _ = Permission.objects.get_or_create(
                codename=codename, content_type=ct, defaults={"name": codename})
            cls.comptable.user_permissions.add(perm)


class TestPerimetreRapprochement(ComptaFictiveMixin, TestCase):
    """ Étape 1 : seules les opérations réellement passées en banque sont rapprochées """

    @classmethod
    def setUpTestData(cls):
        cls.creer_compta()

    def setUp(self):
        from comptabilite.utils import utils_rapprochement
        self.ur = utils_rapprochement

    def test_operations_hors_releve_identifiees(self):
        hors = set(self.ur.Get_ids_hors_releve(self.compte.pk))
        self.assertEqual(hors, {self.op_orga.pk, self.op_avance.pk})

    def test_regularisation_avance_reste_bancaire(self):
        """ La régularisation est le vrai mouvement bancaire, elle doit rester à rapprocher """
        hors = self.ur.Get_ids_hors_releve(self.compte.pk)
        self.assertNotIn(self.op_regul.pk, hors)

    def test_virement_interne_reste_bancaire(self):
        hors = self.ur.Get_ids_hors_releve(self.compte.pk)
        self.assertNotIn(self.op_vir_debit.pk, hors)

    def test_solde_bancaire(self):
        """ crédits 285 - débits 275 = 10 """
        bancaires, _ = self.ur.Get_operations(self.compte.pk)
        _, _, solde = self.ur.Agreger(bancaires)
        self.assertEqual(solde, D("10.00"))

    def test_solde_hors_releve(self):
        """ 60 de crédit orga - 80 d'avance = -20 """
        _, hors = self.ur.Get_operations(self.compte.pk)
        _, _, solde = self.ur.Agreger(hors)
        self.assertEqual(solde, D("-20.00"))

    def test_anouveau_reduit_le_perimetre(self):
        self.compte.date_anouveau = datetime.date(2026, 6, 1)
        self.compte.solde_anouveau = D("10.00")
        self.compte.save()
        p = self.ur.Get_perimetre(self.compte.pk)
        self.assertEqual(p["perimetre"].count(), 0)
        self.assertEqual(p["anterieures"].count(), 12)
        self.compte.date_anouveau = None
        self.compte.solde_anouveau = D("0.00")
        self.compte.save()


class TestTotauxVerification(ComptaFictiveMixin, TestCase):
    """ Étape 1 : cohérence des soldes affichés et de l'écart avec le relevé """

    @classmethod
    def setUpTestData(cls):
        cls.creer_compta()

    def setUp(self):
        from comptabilite.views import verification_compta
        self.vue = verification_compta

    def test_solde_total_est_bancaire(self):
        t = self.vue.Get_totaux_compte(self.compte.pk)
        self.assertEqual(t["solde_total"], D("10.00"))
        self.assertEqual(t["nbre_hors_releve"], 2)

    def test_ecart_nul_quand_tout_verifie(self):
        from comptabilite.utils import utils_rapprochement
        utils_rapprochement.Get_perimetre(self.compte.pk)["perimetre"].update(verification=True)
        t = self.vue.Get_totaux_compte(self.compte.pk, solde_releve=D("10.00"))
        self.assertEqual(t["solde_verification"], D("10.00"))
        self.assertEqual(t["ecart"], D("0.00"))
        ComptaOperation.objects.all().update(verification=False)

    def test_ecart_signale_une_operation_manquante(self):
        from comptabilite.utils import utils_rapprochement
        perimetre = utils_rapprochement.Get_perimetre(self.compte.pk)["perimetre"]
        perimetre.update(verification=True)
        ComptaOperation.objects.filter(pk=self.op_rec_ok.pk).update(verification=False)
        t = self.vue.Get_totaux_compte(self.compte.pk, solde_releve=D("10.00"))
        self.assertEqual(t["ecart"], D("200.00"))
        ComptaOperation.objects.all().update(verification=False)

    def test_anouveau_entre_dans_le_solde_verifie(self):
        self.compte.date_anouveau = datetime.date(2026, 6, 1)
        self.compte.solde_anouveau = D("10.00")
        self.compte.save()
        t = self.vue.Get_totaux_compte(self.compte.pk, solde_releve=D("10.00"))
        self.assertEqual(t["solde_verification"], D("10.00"))
        self.assertEqual(t["ecart"], D("0.00"))
        self.compte.date_anouveau = None
        self.compte.solde_anouveau = D("0.00")
        self.compte.save()

    def test_montant_saisi_avec_virgule(self):
        self.assertEqual(self.vue.Convert_montant("1 234,56"), D("1234.56"))
        self.assertIsNone(self.vue.Convert_montant("abc"))
        self.assertIsNone(self.vue.Convert_montant(""))

    def test_date_saisie_invalide(self):
        self.assertEqual(self.vue.Convert_date("2026-03-10"), datetime.date(2026, 3, 10))
        self.assertIsNone(self.vue.Convert_date("10/03/2026"))
        self.assertIsNone(self.vue.Convert_date(""))


class TestControles(ComptaFictiveMixin, TestCase):
    """ Étape 2 et 3 : les contrôles détectent les bonnes anomalies, et seulement elles """

    @classmethod
    def setUpTestData(cls):
        cls.creer_compta()

    def setUp(self):
        from comptabilite.utils import utils_controles
        self.controles = {c["numero"]: c for c in utils_controles.Get_controles(self.compte.pk)}
        self.utils_controles = utils_controles

    def test_ventilation_depenses_detecte_ecart(self):
        c = self.controles[1]
        # débits ventilables : 100 + 50 + 80(avance) + 20 = 250, ventilé 100+30+80+20 = 230
        self.assertEqual(c["theorique"], D("250.00"))
        self.assertEqual(c["reel"], D("230.00"))
        self.assertEqual(c["etat"], "ERREUR")
        self.assertIn(self.op_dep_mal, c["detail"])

    def test_ventilation_ignore_virements_et_regularisations(self):
        """ Elles n'ont pas de ventilation par construction : pas de faux positif """
        c = self.controles[1]
        self.assertNotIn(self.op_regul, c["detail"])
        self.assertNotIn(self.op_vir_debit, c["detail"])

    def test_ventilation_recettes_detecte_operation_sans_categorie(self):
        c = self.controles[2]
        self.assertEqual(c["etat"], "ERREUR")
        self.assertIn(self.op_rec_sans_vent, c["detail"])

    def test_justificatifs(self):
        c = self.controles[4]
        self.assertEqual(c["etat"], "ERREUR")
        self.assertIn(self.op_sans_justif, c["detail"])
        self.assertNotIn(self.op_dep_ok, c["detail"])

    def test_justificatifs_ignorent_virements_et_regularisations(self):
        c = self.controles[4]
        self.assertNotIn(self.op_vir_debit, c["detail"])
        self.assertNotIn(self.op_regul, c["detail"])

    def test_avances_en_avertissement(self):
        c = self.controles[5]
        self.assertEqual(c["etat"], "AVERTISSEMENT")
        self.assertEqual(c["reel"], D("-80.00"))

    def test_virement_equilibre_est_ok(self):
        self.assertEqual(self.controles[6]["etat"], "OK")

    def test_virement_desequilibre_detecte(self):
        ComptaOperation.objects.filter(pk=self.op_vir_credit.pk).update(montant=D("99.00"))
        c = {x["numero"]: x for x in self.utils_controles.Get_controles(self.compte.pk)}[6]
        self.assertEqual(c["etat"], "ERREUR")
        ComptaOperation.objects.filter(pk=self.op_vir_credit.pk).update(montant=D("25.00"))

    def test_doublons_probables_signales(self):
        c = self.controles[7]
        self.assertEqual(c["etat"], "AVERTISSEMENT")
        self.assertIn(self.op_doublon_a, c["detail"])
        self.assertIn(self.op_doublon_b, c["detail"])

    def test_doublons_avec_references_distinctes_ignores(self):
        c = self.controles[7]
        self.assertNotIn(self.op_stripe_a, c["detail"])
        self.assertNotIn(self.op_stripe_b, c["detail"])

    def creer_deduction(self, montant="20.00", remb=False):
        """ Une déduction accordée à une famille, rattachée à la structure du compte """
        type_deduction = TypeDeduction.objects.create(nom="Fond d'aide", structure=self.structure)
        famille = Famille.objects.create(nom="MARTIN")
        prestation = Prestation.objects.create(date=datetime.date(2026, 3, 1), label="Sejour",
                                               famille=famille, montant=D("100.00"))
        return Deduction.objects.create(
            prestation=prestation, famille=famille, label=type_deduction,
            date=datetime.date(2026, 3, 2), montant=D(montant), remb=remb)

    def controle_deductions(self):
        return {c["numero"]: c for c in self.utils_controles.Get_controles(self.compte.pk)}[8]

    def test_deduction_non_regularisee_signalee(self):
        deduction = self.creer_deduction()
        c = self.controle_deductions()
        self.assertEqual(c["etat"], "AVERTISSEMENT")
        self.assertEqual(c["reel"], D("20.00"))
        self.assertIn(deduction, c["detail"])
        # Le gabarit affiche le détail comme une opération : les attributs doivent exister
        self.assertIn("MARTIN", c["detail"][0].libelle)
        self.assertTrue(c["detail"][0].url_modifier)

    def test_deduction_regularisee_non_signalee(self):
        self.creer_deduction(remb=True)
        c = self.controle_deductions()
        self.assertEqual(c["etat"], "OK")
        self.assertEqual(c["detail"], [])

    def test_deduction_d_une_autre_structure_ignoree(self):
        autre = Structure.objects.create(nom="Autre", actif=True)
        type_deduction = TypeDeduction.objects.create(nom="Hors perimetre", structure=autre)
        famille = Famille.objects.create(nom="DURAND")
        prestation = Prestation.objects.create(date=datetime.date(2026, 3, 1), label="Sejour",
                                               famille=famille, montant=D("100.00"))
        Deduction.objects.create(prestation=prestation, famille=famille, label=type_deduction,
                                 date=datetime.date(2026, 3, 2), montant=D("50.00"), remb=False)
        self.assertEqual(self.controle_deductions()["etat"], "OK")

    def test_compte_sans_structure_controle_inactif(self):
        compte = CompteBancaire.objects.create(nom="Sans structure", structure=None)
        c = {x["numero"]: x for x in self.utils_controles.Get_controles(compte.pk)}[8]
        self.assertIsNone(c["etat"])
        self.assertEqual(c["detail"], [])

    def test_controle_mode_reglement_supprime(self):
        """ Le contrôle du mode de règlement a été retiré : plus aucun ne le mentionne """
        libelles = [c["libelle"] for c in self.controles.values()]
        self.assertNotIn("Mode de règlement renseigné", libelles)

    def test_synthese(self):
        liste = list(self.controles.values())
        ok, erreurs, avertissements, etat = self.utils_controles.Get_synthese(liste)
        self.assertEqual(erreurs, 3)          # ventilations débit, crédit, justificatifs
        self.assertEqual(avertissements, 2)   # avances, doublons
        self.assertEqual(etat, "ERREUR")

    def test_compta_saine_ne_remonte_aucune_erreur(self):
        """ Une comptabilité parfaitement tenue doit être intégralement verte """
        compte = CompteBancaire.objects.create(nom="Compte Sain", structure=self.structure)
        op = ComptaOperation.objects.create(
            compte=compte, type="debit", montant=D("42.00"), date=datetime.date(2026, 3, 1),
            libelle="Achat", mode=self.mode, num_piece="1", document="justifs/ok.pdf")
        ComptaVentilation.objects.create(operation=op, categorie=self.cat_dep,
                                         analytique=self.analytique, montant=D("42.00"),
                                         date_budget=op.date)
        liste = self.utils_controles.Get_controles(compte.pk, solde_releve=D("-42.00"))
        op.verification = True
        op.save()
        liste = self.utils_controles.Get_controles(compte.pk, solde_releve=D("-42.00"))
        ok, erreurs, avertissements, etat = self.utils_controles.Get_synthese(liste)
        self.assertEqual(erreurs, 0, [c["libelle"] for c in liste if c["etat"] == "ERREUR"])
        self.assertEqual(avertissements, 0, [c["libelle"] for c in liste if c["etat"] == "AVERTISSEMENT"])
        self.assertEqual(etat, "OK")

    def test_compte_vide_ne_plante_pas(self):
        compte = CompteBancaire.objects.create(nom="Compte Vide", structure=self.structure)
        liste = self.utils_controles.Get_controles(compte.pk)
        ok, erreurs, avertissements, etat = self.utils_controles.Get_synthese(liste)
        self.assertEqual(erreurs, 0)
        self.assertEqual(etat, "OK")


class TestPagesComptabilite(ComptaFictiveMixin, TestCase):
    """ Le module compta complet répond, et seulement aux utilisateurs autorisés """

    @classmethod
    def setUpTestData(cls):
        cls.creer_compta()
        cls.creer_utilisateurs()

    def urls(self):
        return {
            "verification": reverse("verification_compta_liste", kwargs={"categorie": self.compte.pk}),
            "tresorerie": reverse("operations_tresorerie_liste", kwargs={"categorie": self.compte.pk}),
            "comptes": reverse("comptabilite_liste_comptes"),
            "virements": reverse("virements_liste"),
            "bilan": reverse("suivi_compta"),
            "ventilation": reverse("liste_ventilation"),
            "correction": reverse("correction_compte"),
            "avances": reverse("regul_avances"),
            "justifs": reverse("edition_justifs"),
            "budget": reverse("suivi_budget"),
        }

    def test_acces_autorise(self):
        self.client.force_login(self.comptable)
        for nom, url in self.urls().items():
            with self.subTest(page=nom):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_acces_refuse_sans_permission(self):
        self.client.force_login(self.intrus)
        for nom, url in self.urls().items():
            with self.subTest(page=nom):
                self.assertEqual(self.client.get(url).status_code, 403)

    def test_page_verification_affiche_les_controles(self):
        self.client.force_login(self.comptable)
        reponse = self.client.get(self.urls()["verification"])
        contenu = reponse.content.decode("utf-8")
        self.assertIn("tat de la comptabilit", contenu)
        self.assertIn("action-verification", contenu)
        self.assertIn("date_anouveau", contenu)

    def test_page_verification_masque_les_operations_hors_releve(self):
        from comptabilite.views.verification_compta import Liste
        self.client.force_login(self.comptable)
        reponse = self.client.get(self.urls()["verification"])
        queryset = reponse.context["view"].get_queryset()
        self.assertNotIn(self.op_orga, queryset)
        self.assertNotIn(self.op_avance, queryset)
        self.assertIn(self.op_regul, queryset)


class TestAjaxVerification(ComptaFictiveMixin, TestCase):
    """ Le pointage Ajax fonctionne et refuse les comptes hors structure """

    @classmethod
    def setUpTestData(cls):
        cls.creer_compta()
        cls.creer_utilisateurs()
        cls.autre_structure = Structure.objects.create(nom="Autre groupe", actif=True)
        cls.compte_interdit = CompteBancaire.objects.create(nom="Interdit", structure=cls.autre_structure)
        cls.op_interdite = ComptaOperation.objects.create(
            compte=cls.compte_interdit, type="debit", montant=D("1.00"),
            date=datetime.date(2026, 3, 10), libelle="Secret")

    def setUp(self):
        self.client.force_login(self.comptable)
        self.url = reverse("ajax_verifier_operation")

    def test_cocher_une_operation(self):
        reponse = self.client.post(self.url, {"idoperation": self.op_rec_ok.pk, "verification": "true"},
                                   HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.json()["statut"], "ok")
        self.op_rec_ok.refresh_from_db()
        self.assertTrue(self.op_rec_ok.verification)

    def test_cocher_plusieurs_operations(self):
        ids = [self.op_rec_ok.pk, self.op_dep_ok.pk]
        self.client.post(self.url, {"idoperation": ids, "verification": "true"},
                         HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(ComptaOperation.objects.filter(pk__in=ids, verification=True).count(), 2)

    def test_decocher(self):
        ComptaOperation.objects.filter(pk=self.op_rec_ok.pk).update(verification=True)
        self.client.post(self.url, {"idoperation": self.op_rec_ok.pk, "verification": "false"},
                         HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.op_rec_ok.refresh_from_db()
        self.assertFalse(self.op_rec_ok.verification)

    def test_sans_identifiant(self):
        reponse = self.client.post(self.url, {"verification": "true"},
                                   HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(reponse.status_code, 400)

    def test_requete_non_ajax_refusee(self):
        reponse = self.client.post(self.url, {"idoperation": self.op_rec_ok.pk, "verification": "true"})
        self.assertEqual(reponse.status_code, 400)

    def test_compte_hors_structure_refuse(self):
        reponse = self.client.post(self.url, {"idoperation": self.op_interdite.pk, "verification": "true"},
                                   HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(reponse.status_code, 403)
        self.op_interdite.refresh_from_db()
        self.assertFalse(self.op_interdite.verification)

    def test_pointage_directeur_est_independant(self):
        """ Les deux pointages coexistent sans interférer """
        self.client.post(self.url, {"idoperation": self.op_rec_ok.pk, "verification": "true"},
                         HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.client.post(reverse("Pointer_operation_ajax"),
                         {"idoperation": self.op_dep_ok.pk, "pointage": "true"},
                         HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.op_rec_ok.refresh_from_db()
        self.op_dep_ok.refresh_from_db()
        self.assertTrue(self.op_rec_ok.verification)
        self.assertFalse(self.op_rec_ok.pointage)
        self.assertTrue(self.op_dep_ok.pointage)
        self.assertFalse(self.op_dep_ok.verification)

    def test_pointage_compte_hors_structure_refuse(self):
        reponse = self.client.post(reverse("Pointer_operation_ajax"),
                                   {"idoperation": self.op_interdite.pk, "pointage": "true"},
                                   HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(reponse.status_code, 403)


class TestParametresPage(ComptaFictiveMixin, TestCase):
    """ Période, solde du relevé et à-nouveau sont correctement mémorisés """

    @classmethod
    def setUpTestData(cls):
        cls.creer_compta()
        cls.creer_utilisateurs()

    def setUp(self):
        self.client.force_login(self.comptable)
        self.url = reverse("verification_compta_liste", kwargs={"categorie": self.compte.pk})

    def test_memorise_periode_et_solde(self):
        self.client.post(self.url, {"date_debut": "2026-03-01", "date_fin": "2026-03-31",
                                    "solde_releve": "10,00"})
        from comptabilite.views.verification_compta import Get_parametres
        p = Get_parametres(self.comptable, self.compte.pk)
        self.assertEqual(p["date_debut"], "2026-03-01")
        self.assertEqual(p["solde_releve"], "10,00")

    def test_periode_filtre_la_liste(self):
        self.client.post(self.url, {"date_debut": "2026-01-01", "date_fin": "2026-01-31",
                                    "solde_releve": ""})
        reponse = self.client.get(self.url)
        self.assertEqual(reponse.context["view"].get_queryset().count(), 0)

    def test_reinitialiser(self):
        self.client.post(self.url, {"date_debut": "2026-01-01", "date_fin": "2026-01-31"})
        self.client.post(self.url, {"action": "reinitialiser"})
        reponse = self.client.get(self.url)
        # 14 opérations sur le compte, moins les 2 hors relevé
        self.assertEqual(reponse.context["view"].get_queryset().count(), 12)

    def test_enregistre_anouveau(self):
        self.client.post(self.url, {"action": "anouveau", "date_anouveau": "2026-06-01",
                                    "solde_anouveau": "123,45"})
        self.compte.refresh_from_db()
        self.assertEqual(self.compte.date_anouveau, datetime.date(2026, 6, 1))
        self.assertEqual(self.compte.solde_anouveau, D("123.45"))

    def test_anouveau_vide_remet_a_zero(self):
        self.compte.date_anouveau = datetime.date(2026, 6, 1)
        self.compte.solde_anouveau = D("50.00")
        self.compte.save()
        self.client.post(self.url, {"action": "anouveau", "date_anouveau": "", "solde_anouveau": ""})
        self.compte.refresh_from_db()
        self.assertIsNone(self.compte.date_anouveau)
        self.assertEqual(self.compte.solde_anouveau, D("0"))

    def test_anouveau_compte_hors_structure_ignore(self):
        autre = Structure.objects.create(nom="Autre", actif=True)
        compte_interdit = CompteBancaire.objects.create(nom="Interdit", structure=autre)
        url = reverse("verification_compta_liste", kwargs={"categorie": compte_interdit.pk})
        reponse = self.client.post(url, {"action": "anouveau", "date_anouveau": "2026-06-01",
                                         "solde_anouveau": "999"})
        self.assertEqual(reponse.status_code, 403)
        compte_interdit.refresh_from_db()
        self.assertIsNone(compte_interdit.date_anouveau)


class TestComptaClassique(ComptaFictiveMixin, TestCase):
    """ La saisie classique d'opérations reste fonctionnelle """

    @classmethod
    def setUpTestData(cls):
        cls.creer_compta()
        cls.creer_utilisateurs()

    def setUp(self):
        self.client.force_login(self.comptable)

    def test_ajout_depense_date_budget_suit_la_date_operation(self):
        url = reverse("operations_tresorerie_ajouter_debit", kwargs={"categorie": self.compte.pk})
        donnees = {
            "compte": self.compte.pk, "type": "debit", "date": "15/02/2026",
            "libelle": "Nouvelle depense", "mode": self.mode.pk, "montant": "30.00",
            "num_piece": "99", "observation": "",
            "comptaventilation_set-TOTAL_FORMS": "1", "comptaventilation_set-INITIAL_FORMS": "0",
            "comptaventilation_set-MIN_NUM_FORMS": "0", "comptaventilation_set-MAX_NUM_FORMS": "1000",
            "comptaventilation_set-0-categorie": self.cat_dep.pk,
            "comptaventilation_set-0-montant": "30.00",
        }
        reponse = self.client.post(url, donnees)
        self.assertEqual(reponse.status_code, 302)
        operation = ComptaOperation.objects.get(libelle="Nouvelle depense")
        ventilation = ComptaVentilation.objects.get(operation=operation)
        self.assertEqual(operation.date, datetime.date(2026, 2, 15))
        self.assertEqual(ventilation.date_budget, operation.date,
                         "La ventilation doit porter la date de l'opération, pas celle du jour")

    def test_ventilation_incoherente_refusee(self):
        url = reverse("operations_tresorerie_ajouter_debit", kwargs={"categorie": self.compte.pk})
        donnees = {
            "compte": self.compte.pk, "type": "debit", "date": "15/02/2026",
            "libelle": "Depense incoherente", "mode": self.mode.pk, "montant": "30.00",
            "num_piece": "98", "observation": "",
            "comptaventilation_set-TOTAL_FORMS": "1", "comptaventilation_set-INITIAL_FORMS": "0",
            "comptaventilation_set-MIN_NUM_FORMS": "0", "comptaventilation_set-MAX_NUM_FORMS": "1000",
            "comptaventilation_set-0-categorie": self.cat_dep.pk,
            "comptaventilation_set-0-montant": "10.00",
        }
        reponse = self.client.post(url, donnees)
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(ComptaOperation.objects.filter(libelle="Depense incoherente").exists())

    def test_liste_virements_cloisonnee_par_structure(self):
        autre = Structure.objects.create(nom="Autre", actif=True)
        compte_a = CompteBancaire.objects.create(nom="A", structure=autre)
        compte_b = CompteBancaire.objects.create(nom="B", structure=autre)
        virement_etranger = ComptaVirement.objects.create(
            date=datetime.date(2026, 3, 1), montant=D("5.00"),
            compte_debit=compte_a, compte_credit=compte_b)
        reponse = self.client.get(reverse("virements_liste"))
        queryset = reponse.context["view"].get_queryset()
        self.assertIn(self.virement, queryset)
        self.assertNotIn(virement_etranger, queryset)

    def test_solde_liste_comptes(self):
        reponse = self.client.get(reverse("comptabilite_liste_comptes"))
        comptes = {c.pk: c for c in reponse.context["view"].get_queryset()}
        # Liste des comptes : solde brut de toutes les opérations (10 bancaire - 20 hors relevé)
        self.assertEqual(comptes[self.compte.pk].solde_final, D("-10.00"))


class TestFluxSaisieOperations(ComptaFictiveMixin, TestCase):
    """ Flux de saisie des opérations de trésorerie """

    @classmethod
    def setUpTestData(cls):
        cls.creer_compta()
        cls.creer_utilisateurs()

    def setUp(self):
        self.client.force_login(self.comptable)
        self.url_ajout = reverse("operations_tresorerie_ajouter_debit",
                                 kwargs={"categorie": self.compte.pk})

    def donnees(self, libelle, montant, montant_ventile=None, num_piece="900"):
        return {
            "compte": self.compte.pk, "type": "debit", "date": "01/04/2026",
            "libelle": libelle, "mode": self.mode.pk, "montant": montant,
            "num_piece": num_piece, "observation": "",
            "comptaventilation_set-TOTAL_FORMS": "1", "comptaventilation_set-INITIAL_FORMS": "0",
            "comptaventilation_set-MIN_NUM_FORMS": "0", "comptaventilation_set-MAX_NUM_FORMS": "1000",
            "comptaventilation_set-0-categorie": self.cat_dep.pk,
            "comptaventilation_set-0-montant": montant_ventile or montant,
        }

    def test_numero_de_piece_attribue_a_l_enregistrement(self):
        """ Le numéro posté par le formulaire est ignoré au profit du suivant réel """
        from comptabilite.forms.operations_tresorerie import Get_prochain_num_piece
        attendu = Get_prochain_num_piece(self.compte.pk)
        self.client.post(self.url_ajout, self.donnees("Depense A", "10.00", num_piece="999"))
        operation = ComptaOperation.objects.get(libelle="Depense A")
        self.assertEqual(operation.num_piece, str(attendu))

    def test_deux_saisies_simultanees_ne_partagent_pas_le_numero(self):
        """ Régression : le numéro était figé à l'ouverture du formulaire """
        from comptabilite.forms.operations_tresorerie import Get_prochain_num_piece
        fige = str(Get_prochain_num_piece(self.compte.pk))
        self.client.post(self.url_ajout, self.donnees("Depense B", "10.00", num_piece=fige))
        self.client.post(self.url_ajout, self.donnees("Depense C", "20.00", num_piece=fige))
        numeros = [ComptaOperation.objects.get(libelle=l).num_piece for l in ("Depense B", "Depense C")]
        self.assertNotEqual(numeros[0], numeros[1])

    def test_numero_de_piece_inchange_en_modification(self):
        self.client.post(self.url_ajout, self.donnees("Depense D", "10.00"))
        operation = ComptaOperation.objects.get(libelle="Depense D")
        numero = operation.num_piece
        url = reverse("operations_tresorerie_modifier",
                      kwargs={"categorie": self.compte.pk, "pk": operation.pk})
        donnees = self.donnees("Depense D modifiee", "10.00", num_piece=numero)
        donnees["comptaventilation_set-INITIAL_FORMS"] = "1"
        donnees["comptaventilation_set-0-idventilation"] = ComptaVentilation.objects.get(operation=operation).pk
        reponse = self.client.post(url, donnees)
        self.assertEqual(reponse.status_code, 302, "La modification doit aboutir")
        operation.refresh_from_db()
        self.assertEqual(operation.libelle, "Depense D modifiee")
        self.assertEqual(operation.num_piece, numero)

    def test_ventilation_insuffisante_message_explicite(self):
        reponse = self.client.post(self.url_ajout, self.donnees("Depense E", "50.00", montant_ventile="20.00"))
        self.assertEqual(reponse.status_code, 200)
        contenu = reponse.content.decode("utf-8")
        self.assertIn("reste", contenu.lower())
        self.assertFalse(ComptaOperation.objects.filter(libelle="Depense E").exists())

    def test_ventilation_excedentaire_message_explicite(self):
        reponse = self.client.post(self.url_ajout, self.donnees("Depense F", "20.00", montant_ventile="50.00"))
        contenu = reponse.content.decode("utf-8")
        self.assertIn("passe", contenu.lower())
        self.assertFalse(ComptaOperation.objects.filter(libelle="Depense F").exists())

    def test_aide_ventilation_presente_sur_le_formulaire(self):
        contenu = self.client.get(self.url_ajout).content.decode("utf-8")
        self.assertIn("aide_ventilation", contenu)
        self.assertIn("compta_maj_ventilation", contenu)

    def test_champs_morts_retires_du_formulaire(self):
        """ Les champs ventilation / categorie_rapide n'étaient jamais affichés """
        from django.test import RequestFactory
        from comptabilite.forms.operations_tresorerie import Formulaire
        requete = RequestFactory().get("/")
        requete.user = self.comptable
        formulaire = Formulaire(request=requete, categorie=self.compte.pk, type="debit")
        self.assertNotIn("ventilation", formulaire.fields)
        self.assertNotIn("categorie_rapide", formulaire.fields)


class TestPreservationChampsNonAffiches(ComptaFictiveMixin, TestCase):
    """ Modifier une opération ne doit pas réinitialiser ce que le formulaire n'affiche pas """

    @classmethod
    def setUpTestData(cls):
        cls.creer_compta()
        cls.creer_utilisateurs()

    def test_modification_preserve_pointage_verification_et_tiers(self):
        from core.models import ComptaTiers
        tiers = ComptaTiers.objects.create(nom="Fournisseur X", structure=self.structure)
        operation = self.op_dep_ok
        ComptaOperation.objects.filter(pk=operation.pk).update(
            pointage=True, verification=True, tiers=tiers,
            ref_piece="REF123", observations="note interne")
        operation.refresh_from_db()
        ventilation = ComptaVentilation.objects.get(operation=operation)

        self.client.force_login(self.comptable)
        url = reverse("operations_tresorerie_modifier",
                      kwargs={"categorie": self.compte.pk, "pk": operation.pk})
        reponse = self.client.post(url, {
            "compte": self.compte.pk, "type": "debit", "date": "10/03/2026",
            "libelle": "Courses modifiees", "mode": self.mode.pk, "montant": "100.00",
            "num_piece": operation.num_piece, "observation": "",
            "comptaventilation_set-TOTAL_FORMS": "1", "comptaventilation_set-INITIAL_FORMS": "1",
            "comptaventilation_set-MIN_NUM_FORMS": "0", "comptaventilation_set-MAX_NUM_FORMS": "1000",
            "comptaventilation_set-0-idventilation": ventilation.pk,
            "comptaventilation_set-0-categorie": self.cat_dep.pk,
            "comptaventilation_set-0-montant": "100.00",
        })

        self.assertEqual(reponse.status_code, 302)
        operation.refresh_from_db()
        self.assertEqual(operation.libelle, "Courses modifiees")
        self.assertTrue(operation.pointage, "Le pointage directeur ne doit pas être perdu")
        self.assertTrue(operation.verification, "La vérification bancaire ne doit pas être perdue")
        self.assertEqual(operation.tiers, tiers)
        self.assertEqual(operation.ref_piece, "REF123")
        self.assertEqual(operation.observations, "note interne")


class TestFiltrePeriodeTresorerie(ComptaFictiveMixin, TestCase):
    """ Filtre de période sur la liste des opérations de trésorerie """

    @classmethod
    def setUpTestData(cls):
        cls.creer_compta()
        cls.creer_utilisateurs()

    def setUp(self):
        self.client.force_login(self.comptable)
        self.url = reverse("operations_tresorerie_liste", kwargs={"categorie": self.compte.pk})

    def test_filtre_restreint_la_liste(self):
        self.client.post(self.url, {"date_debut": "2026-01-01", "date_fin": "2026-01-31"})
        reponse = self.client.get(self.url)
        self.assertEqual(reponse.context["view"].get_queryset().count(), 0)

    def test_reinitialisation(self):
        self.client.post(self.url, {"date_debut": "2026-01-01", "date_fin": "2026-01-31"})
        self.client.post(self.url, {"action": "reinitialiser"})
        reponse = self.client.get(self.url)
        self.assertEqual(reponse.context["view"].get_queryset().count(), 14)

    def test_periode_memorisee_par_compte(self):
        self.client.post(self.url, {"date_debut": "2026-01-01", "date_fin": "2026-01-31"})
        autre = reverse("operations_tresorerie_liste", kwargs={"categorie": self.compte2.pk})
        reponse = self.client.get(autre)
        self.assertEqual(reponse.context["periode"]["date_debut"], "")

    def test_date_invalide_ignoree(self):
        self.client.post(self.url, {"date_debut": "pas une date", "date_fin": ""})
        reponse = self.client.get(self.url)
        self.assertEqual(reponse.context["view"].get_queryset().count(), 14)

    def test_liste_budgetaire_na_pas_le_filtre(self):
        """ Le template est partagé : le filtre ne doit apparaître que là où il est fourni """
        reponse = self.client.get(reverse("operations_budgetaires_liste",
                                          kwargs={"categorie": self.compte.pk}))
        self.assertNotIn("filtre_periode", reponse.context or {})
