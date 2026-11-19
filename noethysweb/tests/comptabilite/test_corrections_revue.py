"""
Régressions des points relevés en revue de code de la vérification comptable.
"""

import datetime
import decimal

from core.models import ComptaOperation, ComptaVirement, CompteBancaire, Structure
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from tests.comptabilite.test_verification_compta import ComptaFictiveMixin

D = decimal.Decimal
AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class TestAjaxVerificationRevue(ComptaFictiveMixin, TestCase):

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
        self.url = reverse("ajax_verifier_operation")

    def test_sans_permission_de_la_page_refuse(self):
        """ L'intrus a accès à la structure, mais pas à la page de vérification """
        self.client.force_login(self.intrus)
        reponse = self.client.post(self.url, {"idoperation": self.op_rec_ok.pk, "verification": "true"}, **AJAX)
        self.assertEqual(reponse.status_code, 403)
        self.op_rec_ok.refresh_from_db()
        self.assertFalse(self.op_rec_ok.verification)

    def test_lot_avec_operation_introuvable_ne_modifie_rien(self):
        self.client.force_login(self.comptable)
        ids = [self.op_rec_ok.pk, self.op_dep_ok.pk, 999999]
        reponse = self.client.post(self.url, {"idoperation": ids, "verification": "true"}, **AJAX)
        self.assertEqual(reponse.status_code, 404)
        self.assertEqual(ComptaOperation.objects.filter(verification=True).count(), 0)

    def test_lot_avec_operation_interdite_ne_modifie_rien(self):
        self.client.force_login(self.comptable)
        ids = [self.op_rec_ok.pk, self.op_dep_ok.pk, self.op_interdite.pk]
        reponse = self.client.post(self.url, {"idoperation": ids, "verification": "true"}, **AJAX)
        self.assertEqual(reponse.status_code, 403)
        self.assertEqual(ComptaOperation.objects.filter(verification=True).count(), 0)

    def test_identifiant_invalide(self):
        self.client.force_login(self.comptable)
        reponse = self.client.post(self.url, {"idoperation": "abc", "verification": "true"}, **AJAX)
        self.assertEqual(reponse.status_code, 400)


class TestControlesRevue(ComptaFictiveMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.creer_compta()

    def controle(self, numero):
        from comptabilite.utils import utils_controles
        return next(c for c in utils_controles.Get_controles(self.compte.pk) if c["numero"] == numero)

    def test_avance_a_remb_null_signalee(self):
        """ remb_avance est nullable : NULL n'est pas une régularisation """
        ComptaOperation.objects.filter(pk=self.op_avance.pk).update(remb_avance=None)
        controle = self.controle(5)
        self.assertIn(self.op_avance, controle["detail"])
        self.assertEqual(controle["etat"], "AVERTISSEMENT")

    def test_liens_adaptes_a_la_nature_de_l_operation(self):
        """ Un virement déséquilibré s'ouvre dans l'écran des virements, pas en opération simple """
        ComptaVirement.objects.filter(pk=self.virement.pk).update(montant=D("30.00"))
        controle = self.controle(6)
        urls = {op.pk: op.url_modifier for op in controle["detail"]}
        attendu = reverse("virements_modifier", args=[self.virement.pk])
        self.assertEqual(urls[self.op_vir_debit.pk], attendu)
        self.assertEqual(urls[self.op_vir_credit.pk], attendu)

    def test_lien_operation_simple(self):
        controle = self.controle(1)
        operation = next(op for op in controle["detail"] if op.pk == self.op_dep_mal.pk)
        self.assertEqual(operation.url_modifier,
                         reverse("operations_tresorerie_modifier", args=[self.compte.pk, self.op_dep_mal.pk]))

    def test_nombre_de_requetes_independant_du_volume(self):
        """ Les contrôles ne doivent plus faire une requête par opération ou par virement """
        from comptabilite.utils import utils_controles

        def compter():
            with CaptureQueriesContext(connection) as ctx:
                utils_controles.Get_controles(self.compte.pk)
            return len(ctx.captured_queries)

        avant = compter()
        for i in range(10):
            ComptaOperation.objects.create(compte=self.compte, type="debit", montant=D("1.00"),
                                           date=datetime.date(2026, 4, i + 1), libelle=f"Ajout {i}",
                                           mode=self.mode)
            virement = ComptaVirement.objects.create(date=datetime.date(2026, 4, i + 1), montant=D("2.00"),
                                                     libelle=f"Vir {i}", compte_debit=self.compte,
                                                     compte_credit=self.compte2)
            ComptaOperation.objects.create(compte=self.compte, type="debit", montant=D("2.00"),
                                           date=virement.date, libelle=virement.libelle, virement=virement)
        self.assertEqual(compter(), avant)


class TestSoldeBancaireAnouveau(ComptaFictiveMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.creer_compta()

    def test_solde_bancaire_part_de_l_anouveau(self):
        """ Les rapports doivent donner le même solde que la page de vérification """
        from comptabilite.utils import utils_rapprochement
        from comptabilite.views import verification_compta

        # Opérations anciennes et incomplètes, avant le point de départ
        ComptaOperation.objects.create(compte=self.compte, type="debit", montant=D("999.00"),
                                       date=datetime.date(2025, 1, 1), libelle="Historique faux")
        self.compte.date_anouveau = datetime.date(2026, 1, 1)
        self.compte.solde_anouveau = D("1200.00")
        self.compte.save()

        solde_rapports = utils_rapprochement.Get_solde_bancaire([self.compte])
        solde_verification = verification_compta.Get_totaux_compte(self.compte.pk)["solde_total"]
        self.assertEqual(solde_rapports, solde_verification)

    def test_date_avant_anouveau_utilise_l_historique(self):
        from comptabilite.utils import utils_rapprochement
        self.compte.date_anouveau = datetime.date(2026, 6, 1)
        self.compte.solde_anouveau = D("1200.00")
        self.compte.save()
        solde = utils_rapprochement.Get_solde_bancaire([self.compte], date_fin=datetime.date(2026, 5, 31))
        attendu = utils_rapprochement.Get_solde_bancaire([self.compte.pk], date_fin=datetime.date(2026, 5, 31))
        self.assertEqual(solde, attendu)
        self.assertNotEqual(solde, D("1200.00"))


class TestPermissionsAccordables(TestCase):

    def test_pages_hors_menu_ont_une_permission_declaree(self):
        """ Sans déclaration, la permission ne peut pas être accordée depuis l'écran des droits """
        from core.utils.utils_permissions import GetPermissionsPossibles
        codes = {code for code, _ in GetPermissionsPossibles()}
        for code in ("rapprochements_liste", "operations_budgetaires_liste", "avances_regul", "virements_liste"):
            self.assertIn(code, codes)


class TestNumeroPiece(ComptaFictiveMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.creer_compta()

    def test_lecture_verrouillante_donne_le_meme_numero(self):
        from comptabilite.forms.operations_tresorerie import Get_prochain_num_piece
        from django.db import transaction
        with transaction.atomic():
            self.assertEqual(Get_prochain_num_piece(self.compte.pk, verrou=True),
                             Get_prochain_num_piece(self.compte.pk))
