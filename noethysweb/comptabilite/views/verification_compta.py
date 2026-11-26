# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging, decimal
logger = logging.getLogger(__name__)
from django.urls import reverse
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse, HttpResponseRedirect
from django.views.decorators.http import require_POST
from core.views.mydatatableview import MyDatatable, columns, helpers
from core.views import crud
from core.models import ComptaOperation, ComptaVentilation, CompteBancaire
from core.utils import utils_texte, utils_parametres
from comptabilite.utils import utils_controles, utils_rapprochement
from comptabilite.utils.utils_compta import Agreger, Convert_date, Convert_montant, Get_url_modifier  # noqa: F401

CATEGORIE_PARAMETRES = "verification_compta"
PARAMETRES_DEFAUT = {"date_debut": "", "date_fin": "", "solde_releve": ""}


def Get_parametres(utilisateur, idcompte):
    """ Renvoie les paramètres mémorisés de l'utilisateur pour ce compte """
    parametres = utils_parametres.Get(nom="compte_%s" % idcompte, categorie=CATEGORIE_PARAMETRES,
                                      utilisateur=utilisateur, valeur=dict(PARAMETRES_DEFAUT))
    # Le paramètre peut avoir été enregistré avec moins de clés
    resultat = dict(PARAMETRES_DEFAUT)
    if isinstance(parametres, dict):
        resultat.update(parametres)
    return resultat


def Set_parametres(utilisateur, idcompte, parametres):
    utils_parametres.Set(nom="compte_%s" % idcompte, categorie=CATEGORIE_PARAMETRES,
                         utilisateur=utilisateur, valeur=parametres)


def Get_totaux_compte(idcompte, date_debut=None, date_fin=None, solde_releve=None, perimetre=None):
    """
    Renvoie tous les indicateurs de vérification d'un compte.
    Seules les opérations réellement passées en banque entrent dans le rapprochement,
    à partir de la date d'à-nouveau.
    perimetre : résultat de utils_rapprochement.Get_perimetre(), s'il est déjà calculé.
    """
    p = perimetre if perimetre is not None else utils_rapprochement.Get_perimetre(idcompte)
    perimetre, hors_releve = p["perimetre"], p["hors_releve"]
    solde_anouveau = p["solde_anouveau"]

    # Solde comptable théorique du compte en banque
    _, _, mouvements = Agreger(perimetre)
    solde_total = solde_anouveau + mouvements

    # Solde vérifié : à-nouveau + opérations cochées
    debit_verif, credit_verif, mouvements_verif = Agreger(perimetre.filter(verification=True))
    solde_verification = solde_anouveau + mouvements_verif

    # Indicateurs de la période affichée
    periode = perimetre
    if date_debut:
        periode = periode.filter(date__gte=date_debut)
    if date_fin:
        periode = periode.filter(date__lte=date_fin)
    debit_periode, credit_periode, solde_periode = Agreger(periode)

    _, _, solde_hors_releve = Agreger(hors_releve)

    ecart = None
    if solde_releve is not None:
        ecart = solde_releve - solde_verification

    return {
        "solde_total": solde_total,
        "solde_verification": solde_verification,
        "solde_anouveau": solde_anouveau,
        "date_anouveau": p["date_anouveau"],
        "debit_verification": debit_verif,
        "credit_verification": credit_verif,
        "reste_a_verifier": solde_total - solde_verification,
        "debit_periode": debit_periode,
        "credit_periode": credit_periode,
        "solde_periode": solde_periode,
        "nbre_periode": periode.count(),
        "nbre_periode_verification": periode.filter(verification=True).count(),
        "nbre_total": perimetre.count(),
        "nbre_total_verification": perimetre.filter(verification=True).count(),
        "nbre_hors_releve": hors_releve.count(),
        "solde_hors_releve": solde_hors_releve,
        "nbre_anterieures": p["anterieures"].count(),
        "solde_releve": solde_releve,
        "ecart": ecart,
    }


def Get_html_totaux(idcompte, date_debut=None, date_fin=None, solde_releve=None, perimetre=None):
    """ Renvoie le HTML du tableau récapitulatif d'un compte """
    t = Get_totaux_compte(idcompte, date_debut, date_fin, solde_releve, perimetre=perimetre)
    fm = utils_texte.Formate_montant

    # Ligne d'écart avec le relevé
    if t["ecart"] is None:
        html_ecart = ("<tr><td colspan='2' style='padding-top:6px;'>"
                      "<i>Saisissez le solde de votre relevé ci-dessus pour calculer l'écart.</i></td></tr>")
    elif t["ecart"] == 0:
        html_ecart = ("<tr><td style='padding-top:6px;'>Écart avec le relevé :</td>"
                      "<td style='padding-left:10px;padding-top:6px;' class='text-green'>"
                      "<b><i class='fa fa-check'></i> Aucun écart, la vérification est bonne.</b></td></tr>")
    else:
        html_ecart = ("<tr><td style='padding-top:6px;'>Écart avec le relevé :</td>"
                      "<td style='padding-left:10px;padding-top:6px;' class='text-red'><b>%s</b></td></tr>" % fm(t["ecart"]))

    # Ligne d'à-nouveau
    if t["date_anouveau"]:
        html_anouveau = ("<tr><td>dont à-nouveau au %s :</td><td style='padding-left:10px;'>%s "
                         "<small class='text-muted'>(%d opération(s) antérieure(s) exclue(s))</small></td></tr>" % (
                             t["date_anouveau"].strftime("%d/%m/%Y"), fm(t["solde_anouveau"]), t["nbre_anterieures"]))
    else:
        html_anouveau = ""

    # Ligne des opérations hors relevé
    if t["nbre_hors_releve"]:
        html_hors = ("<tr><td>Hors relevé (avances, part Mouvement) :</td>"
                     "<td style='padding-left:10px;'>%s <small class='text-muted'>(%d opération(s), "
                     "exclues du rapprochement)</small></td></tr>" % (
                         fm(t["solde_hors_releve"]), t["nbre_hors_releve"]))
    else:
        html_hors = ""

    return """
        <table style="margin:0 auto;">
            <tr><td>Solde vérifié (opérations cochées) :</td><td style='padding-left:10px;'><b>%s</b></td></tr>
            <tr><td>Solde du relevé saisi :</td><td style='padding-left:10px;'><b>%s</b></td></tr>
            %s
            <tr><td colspan="2"><hr style="margin:6px 0;"></td></tr>
            <tr><td>Solde bancaire en comptabilité :</td><td style='padding-left:10px;'>%s</td></tr>
            %s
            <tr><td>Reste à vérifier :</td><td style='padding-left:10px;'>%s</td></tr>
            %s
            <tr><td colspan="2"><hr style="margin:6px 0;"></td></tr>
            <tr><td>Période affichée :</td><td style='padding-left:10px;'>%d opération(s), %s vérifiée(s)</td></tr>
            <tr><td>Mouvements de la période :</td><td style='padding-left:10px;'>%s de débits / %s de crédits</td></tr>
            <tr><td>À rapprocher sur ce compte :</td><td style='padding-left:10px;'>%d opération(s), %d vérifiée(s)</td></tr>
        </table>
    """ % (
        fm(t["solde_verification"]),
        fm(t["solde_releve"]) if t["solde_releve"] is not None else "—",
        html_ecart,
        fm(t["solde_total"]),
        html_anouveau,
        fm(t["reste_a_verifier"]),
        html_hors,
        t["nbre_periode"], t["nbre_periode_verification"],
        fm(t["debit_periode"]), fm(t["credit_periode"]),
        t["nbre_total"], t["nbre_total_verification"],
    )


@require_POST
def Verifier_operation_ajax(request):
    """ Vue Ajax pour modifier le statut de vérification d'une ou plusieurs opérations """
    # secure_ajax ne contrôle que la catégorie d'utilisateur : la permission de la page
    # doit être vérifiée ici, comme le fait CustomView.test_func() pour la page elle-même.
    if not request.user.has_perm("core.%s" % Page.menu_code):
        return JsonResponse({"statut": "erreur", "message": "Vous n'avez pas accès à la vérification comptable"}, status=403)

    liste_idoperation = request.POST.getlist("idoperation")
    verification = request.POST.get("verification") == "true"

    if not liste_idoperation:
        return JsonResponse({"statut": "erreur", "message": "ID manquant"}, status=400)
    try:
        liste_idoperation = {int(idoperation) for idoperation in liste_idoperation}
    except (TypeError, ValueError):
        return JsonResponse({"statut": "erreur", "message": "ID invalide"}, status=400)

    # Tout est contrôlé avant la moindre écriture : la requête est appliquée en entier ou pas du tout
    operations = list(ComptaOperation.objects.filter(pk__in=liste_idoperation))
    if len(operations) != len(liste_idoperation):
        return JsonResponse({"statut": "erreur", "message": "Opération introuvable"}, status=404)

    condition_structure = Q(structure__in=request.user.structures.all()) | Q(structure__isnull=True)
    comptes_autorises = set(CompteBancaire.objects.filter(condition_structure).values_list("pk", flat=True))
    comptes = {operation.compte_id for operation in operations}
    if not comptes <= comptes_autorises:
        return JsonResponse({"statut": "erreur", "message": "Accès non autorisé à ce compte"}, status=403)
    if len(comptes) > 1:
        return JsonResponse({"statut": "erreur", "message": "Les opérations doivent appartenir au même compte"}, status=400)

    with transaction.atomic():
        ComptaOperation.objects.filter(pk__in=liste_idoperation).update(verification=verification)

    idcompte = comptes.pop()
    parametres = Get_parametres(request.user, idcompte)
    html_totaux = Get_html_totaux(
        idcompte,
        date_debut=Convert_date(parametres["date_debut"]),
        date_fin=Convert_date(parametres["date_fin"]),
        solde_releve=Convert_montant(parametres["solde_releve"]),
    )
    return JsonResponse({"statut": "ok", "html_totaux": html_totaux})


class Page(crud.Page):
    model = ComptaOperation
    menu_code = "verification_compta_liste"
    url_liste = "verification_compta_liste"
    description_liste = ("Cochez la case Vérifié de chaque opération figurant sur votre relevé bancaire. "
                         "Le solde vérifié doit correspondre au solde du relevé.")
    objet_singulier = "une opération à vérifier"
    objet_pluriel = "la vérification comptable"

    def test_func_page(self):
        # Vérifie que l'utilisateur a une permission d'accéder à ce compte
        idcompte = self.Get_categorie()
        if idcompte and idcompte not in [compte.pk for compte in CompteBancaire.objects.filter(self.Get_condition_structure())]:
            return False
        return True

    def Get_categorie(self):
        idcompte = self.kwargs.get("categorie", None)
        if idcompte:
            return idcompte
        compte = CompteBancaire.objects.filter(self.Get_condition_structure()).order_by("nom")
        return compte[0].pk if compte else 0


class Liste(Page, crud.Liste):
    model = ComptaOperation
    template_name = "comptabilite/verification_compta.html"

    def Get_parametres_compte(self):
        if not hasattr(self, "_parametres_compte"):
            self._parametres_compte = Get_parametres(self.request.user, self.Get_categorie())
        return self._parametres_compte

    def post(self, request, *args, **kwargs):
        """ Enregistre la période, le solde du relevé ou l'à-nouveau, puis réaffiche la liste """
        idcompte = self.Get_categorie()
        action = request.POST.get("action")

        if action == "anouveau":
            # L'à-nouveau est une donnée du compte, partagée par tous les utilisateurs
            compte = CompteBancaire.objects.filter(
                Q(structure__in=request.user.structures.all()) | Q(structure__isnull=True), pk=idcompte).first()
            if compte:
                compte.date_anouveau = Convert_date(request.POST.get("date_anouveau", ""))
                montant = Convert_montant(request.POST.get("solde_anouveau", ""))
                compte.solde_anouveau = montant if montant is not None else decimal.Decimal(0)
                compte.save(update_fields=["date_anouveau", "solde_anouveau"])
        elif action == "reinitialiser":
            Set_parametres(request.user, idcompte, dict(PARAMETRES_DEFAUT))
        else:
            Set_parametres(request.user, idcompte, {
                "date_debut": request.POST.get("date_debut", "") or "",
                "date_fin": request.POST.get("date_fin", "") or "",
                "solde_releve": request.POST.get("solde_releve", "") or "",
            })

        return HttpResponseRedirect(reverse("verification_compta_liste", kwargs={"categorie": idcompte}))

    def get_queryset(self):
        """ Seules les opérations à rapprocher sont listées (cf. utils_rapprochement) """
        parametres = self.Get_parametres_compte()
        perimetre = utils_rapprochement.Get_perimetre(self.Get_categorie())["perimetre"]

        date_debut = Convert_date(parametres["date_debut"])
        date_fin = Convert_date(parametres["date_fin"])
        if date_debut:
            perimetre = perimetre.filter(date__gte=date_debut)
        if date_fin:
            perimetre = perimetre.filter(date__lte=date_fin)

        return perimetre.select_related("tiers", "mode", "compte").filter(self.Get_filtres("Q"))

    def get_context_data(self, **kwargs):
        context = super(Liste, self).get_context_data(**kwargs)
        context["page_titre"] = "Vérification comptable"
        context["box_titre"] = "Vérification comptable"
        context["impression_introduction"] = ""
        context["impression_conclusion"] = ""
        context["afficher_menu_brothers"] = True

        # Sélection du compte bancaire
        idcompte = self.Get_categorie()
        context["categorie"] = idcompte
        context["label_categorie"] = "Compte"
        context["liste_categories"] = [
            (item.pk, "%s (%s)" % (item.nom, item.structure.nom if item.structure else "Sans structure"))
            for item in CompteBancaire.objects.filter(
                Q(structure__in=self.request.user.structures.all()) | Q(structure__isnull=True)
            ).order_by("nom")
        ]

        if not context["liste_categories"]:
            context["box_introduction"] = "<b>Vous devez avoir enregistré au moins un compte bancaire pour utiliser la vérification comptable !</b>"
            return context

        # Point de départ du rapprochement + opérations hors relevé
        # Le périmètre est calculé une seule fois et partagé avec les totaux et les contrôles
        p = utils_rapprochement.Get_perimetre(idcompte)
        context["date_anouveau"] = p["date_anouveau"].strftime("%Y-%m-%d") if p["date_anouveau"] else ""
        context["solde_anouveau"] = p["solde_anouveau"]
        operations_hors_releve = list(p["hors_releve"].select_related("avance").order_by("date"))
        for operation in operations_hors_releve:
            operation.url_modifier = Get_url_modifier(operation, retour=self.request.get_full_path())
        context["operations_hors_releve"] = operations_hors_releve
        _, _, context["solde_hors_releve"] = Agreger(p["hors_releve"])

        parametres = self.Get_parametres_compte()
        context["parametres"] = parametres
        context["box_introduction"] = Get_html_totaux(
            idcompte,
            date_debut=Convert_date(parametres["date_debut"]),
            date_fin=Convert_date(parametres["date_fin"]),
            solde_releve=Convert_montant(parametres["solde_releve"]),
            perimetre=p,
        )
        # État de la comptabilité : tableau de contrôles (cf. classeur Excel historique)
        controles = utils_controles.Get_controles(idcompte, solde_releve=Convert_montant(parametres["solde_releve"]),
                                                  perimetre=p, retour=self.request.get_full_path())
        nbre_ok, nbre_erreurs, nbre_avertissements, etat_global = utils_controles.Get_synthese(controles)
        context["controles"] = controles
        context["controles_nbre_ok"] = nbre_ok
        context["controles_nbre_erreurs"] = nbre_erreurs
        context["controles_nbre_avertissements"] = nbre_avertissements
        context["controles_etat_global"] = etat_global
        return context

    class datatable_class(MyDatatable):
        filtres = ["idoperation", "type", "date", "libelle", "mode", "releve", "num_piece", "debit", "credit",
                   "montant", "pointage", "verification", "observation"]

        verification = columns.TextColumn("Vérifié", sources=["verification"], processor="Get_checkbox_verification")
        pointage = columns.TextColumn("Pointé dir.", sources=["pointage"], processor="Get_icone_pointage")
        debit = columns.TextColumn("Débit", sources=["montant"], processor="Get_montant_debit")
        credit = columns.TextColumn("Crédit", sources=["montant"], processor="Get_montant_credit")
        actions = columns.TextColumn("Actions", sources=None, processor="Get_actions_speciales")

        class Meta:
            structure_template = MyDatatable.structure_template
            columns = ["verification", "date", "num_piece", "libelle", "mode", "debit", "credit", "pointage", "actions"]
            ordering = ["date"]
            processors = {
                "date": helpers.format_date("%d/%m/%Y"),
                "libelle": "Get_libelle_avance",
            }
            labels = {
                "mode": "Mode",
                "num_piece": "N° Pièce",
                "releve": "Relevé",
            }

        def Get_checkbox_verification(self, instance, **kwargs):
            checked = "checked" if instance.verification else ""
            return ('<center><input type="checkbox" class="action-verification" '
                    'data-idoperation="%s" %s title="Opération retrouvée sur le relevé bancaire"></center>'
                    % (instance.pk, checked))

        def Get_icone_pointage(self, instance, **kwargs):
            if instance.pointage:
                return ('<center><i class="fa fa-check text-green" '
                        'title="Pointée par le directeur au fil du camp"></i></center>')
            return ""

        def Get_libelle_avance(self, instance, **kwargs):
            avance_nom = " - (Avance de %s)" % instance.avance.nom if instance.avance else ""
            regul = ""
            if not instance.regul_avance and instance.remb_avance:
                regul = " - régularisée"
            return "%s%s%s" % (instance.libelle, avance_nom, regul)

        def Get_montant_debit(self, instance, **kwargs):
            if instance.type == "debit":
                return "%0.2f" % instance.montant
            return None

        def Get_montant_credit(self, instance, **kwargs):
            if instance.type == "credit":
                return "%0.2f" % instance.montant
            return None

        def Get_actions_speciales(self, instance, *args, **kwargs):
            # On repart vers la page de vérification après l'enregistrement, pas vers
            # la liste des opérations de trésorerie
            vue = kwargs.get("view")
            retour = vue.request.get_full_path() if vue else None
            html = [self.Create_bouton_modifier(url=Get_url_modifier(instance, retour=retour))]
            if instance.document:
                html.append(self.Create_bouton_ouvrir(url=instance.document.url))
            return self.Create_boutons_actions(html)
