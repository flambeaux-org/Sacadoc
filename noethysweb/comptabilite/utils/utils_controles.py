# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.
#
#  Contrôles de cohérence de la comptabilité d'un compte bancaire.
#  Reprend la logique de la feuille "Etat de la comptabilité" du classeur Excel
#  historique : chaque contrôle compare une valeur théorique à une valeur réelle
#  et signale un écart.

from collections import defaultdict
from django.db.models import Q, Sum
from core.models import ComptaOperation, ComptaVentilation, ComptaVirement
from core.utils import utils_texte
from comptabilite.utils import utils_rapprochement
from comptabilite.utils.utils_compta import ZERO, Arrondi, Get_url_modifier

#  Deux natures d'opérations n'ont pas de ventilation par construction, et ne doivent
#  donc pas être signalées comme "non ventilées" :
#    - les virements internes : un transfert entre deux comptes de l'organisme n'est
#      ni une dépense ni une recette ;
#    - les régularisations d'avance : les catégories sont portées par les opérations
#      d'avance elles-mêmes, la régularisation ne fait que solder le compte.
_CONDITION_VENTILABLE = Q(virement__isnull=True) & Q(regul_avance=False)


_arrondi = Arrondi


def _controle(numero, libelle, theorique=None, reel=None, aide="", detail=None,
              comparaison="egal", format="montant", erreur_si_detail=False,
              niveau="erreur"):
    """
    Construit un contrôle.
    comparaison : "egal" (théorique == réel) ou "max" (réel <= théorique)
    erreur_si_detail : signale une erreur dès qu'une opération est listée en détail,
                       même si les totaux se compensent entre eux.
    niveau : "erreur" (bloquant) ou "avertissement" (à examiner, non bloquant)
    """
    detail = detail or []
    etat, difference = None, None
    anomalie = "ERREUR" if niveau == "erreur" else "AVERTISSEMENT"

    if theorique is not None and reel is not None:
        if comparaison == "max":
            etat = "OK" if reel <= theorique else anomalie
            difference = reel - theorique if etat != "OK" else None
        else:
            etat = "OK" if theorique == reel else anomalie
            difference = reel - theorique if etat != "OK" else None

        # Des écarts de signes opposés peuvent s'annuler dans les totaux
        if etat == "OK" and erreur_si_detail and detail:
            etat = anomalie

    def formater(valeur):
        if valeur is None:
            return "—"
        if format == "nombre":
            return str(valeur)
        return utils_texte.Formate_montant(valeur)

    return {
        "numero": numero,
        "libelle": libelle,
        "theorique": theorique,
        "reel": reel,
        "etat": etat,
        "difference": difference,
        "theorique_texte": formater(theorique),
        "reel_texte": formater(reel),
        "difference_texte": formater(difference) if difference is not None else "",
        "aide": aide,
        "detail": detail,
        "format": format,
    }


def Get_controles(idcompte, solde_releve=None, perimetre=None, retour=None):
    """
    Renvoie la liste des contrôles de cohérence d'un compte bancaire.
    perimetre : résultat de utils_rapprochement.Get_perimetre(), s'il est déjà calculé.
    """
    operations = ComptaOperation.objects.filter(compte_id=idcompte).select_related("compte", "avance")
    controles = []

    # Total ventilé par opération, en une seule requête (et non une par opération)
    ventile_par_operation = dict(
        ComptaVentilation.objects.filter(operation__compte_id=idcompte)
        .values("operation").annotate(total=Sum("montant")).values_list("operation", "total")
    )

    # ------------------------------------------------------------------
    # 1. Ventilation des dépenses
    #    Excel : SUM(R:AG) doit égaler Dépense caisse + Dépense banque
    # ------------------------------------------------------------------
    debits = operations.filter(type="debit")
    debits_ventilables = debits.filter(_CONDITION_VENTILABLE)
    total_debits = _arrondi(debits_ventilables.aggregate(t=Sum("montant"))["t"])
    ventile_debits = _arrondi(
        ComptaVentilation.objects.filter(operation__in=debits_ventilables).aggregate(t=Sum("montant"))["t"]
    )
    detail_debits = [op for op in debits_ventilables if ventile_par_operation.get(op.pk) != op.montant]
    controles.append(_controle(
        1, "Ventilation des dépenses",
        theorique=total_debits, reel=ventile_debits,
        aide="La somme des catégories comptables doit couvrir exactement le montant de chaque dépense.",
        detail=detail_debits, erreur_si_detail=True,
    ))

    # ------------------------------------------------------------------
    # 2. Ventilation des recettes
    #    Excel : Recette caisse + Recette banque doit égaler SUM(AH:AT)
    # ------------------------------------------------------------------
    credits = operations.filter(type="credit")
    credits_ventilables = credits.filter(_CONDITION_VENTILABLE)
    total_credits = _arrondi(credits_ventilables.aggregate(t=Sum("montant"))["t"])
    ventile_credits = _arrondi(
        ComptaVentilation.objects.filter(operation__in=credits_ventilables).aggregate(t=Sum("montant"))["t"]
    )
    detail_credits = [op for op in credits_ventilables if ventile_par_operation.get(op.pk) != op.montant]
    controles.append(_controle(
        2, "Ventilation des recettes",
        theorique=total_credits, reel=ventile_credits,
        aide="La somme des catégories comptables doit couvrir exactement le montant de chaque recette.",
        detail=detail_credits, erreur_si_detail=True,
    ))

    # ------------------------------------------------------------------
    # 3. Solde vérifié / solde du relevé bancaire
    #    Excel : le solde banque n'avance que si la date de relevé est saisie
    # ------------------------------------------------------------------
    if perimetre is None:
        perimetre = utils_rapprochement.Get_perimetre(idcompte)
    solde_verifie = _arrondi(perimetre["solde_anouveau"] + _solde(perimetre["perimetre"].filter(verification=True)))
    if solde_releve is not None:
        controles.append(_controle(
            3, "Solde vérifié / solde du relevé",
            theorique=_arrondi(solde_releve), reel=solde_verifie,
            aide="Le total des opérations cochées (à-nouveau inclus) doit correspondre au solde de votre relevé bancaire.",
        ))
    else:
        controles.append(_controle(
            3, "Solde vérifié / solde du relevé",
            aide="Saisissez le solde de votre relevé ci-dessus pour activer ce contrôle.",
        ))

    # ------------------------------------------------------------------
    # 4. Pièces justificatives des dépenses (colonne "PC ?!" du classeur)
    # ------------------------------------------------------------------
    depenses_justifiables = debits.filter(virement__isnull=True, regul_avance=False)
    nbre_depenses = depenses_justifiables.count()
    sans_justif = list(depenses_justifiables.filter(Q(document="") | Q(document__isnull=True)).order_by("date"))
    controles.append(_controle(
        4, "Pièces justificatives des dépenses",
        theorique=nbre_depenses, reel=nbre_depenses - len(sans_justif), format="nombre",
        aide="Chaque dépense doit être accompagnée de sa pièce justificative.",
        detail=sans_justif,
    ))

    # ------------------------------------------------------------------
    # 5. Avances non régularisées (Excel : contrôle 12)
    # ------------------------------------------------------------------
    # remb_avance est nullable : une avance à NULL n'est pas plus régularisée qu'à 0
    avances = operations.filter(Q(remb_avance=0) | Q(remb_avance__isnull=True),
                                avance__isnull=False, regul_avance=False)
    solde_avances = _solde(avances)
    controles.append(_controle(
        5, "Avances restant à régulariser",
        theorique=ZERO, reel=solde_avances, niveau="avertissement",
        aide="Une avance en attente est normale en cours d'exercice ; elle doit être régularisée avant la clôture.",
        detail=list(avances.order_by("date")),
    ))

    # ------------------------------------------------------------------
    # 6. Équilibre des virements internes
    # ------------------------------------------------------------------
    virements = list(ComptaVirement.objects.filter(Q(compte_debit_id=idcompte) | Q(compte_credit_id=idcompte)))
    ops_par_virement = defaultdict(list)
    for op in ComptaOperation.objects.filter(virement__in=virements).order_by("date", "pk"):
        ops_par_virement[op.virement_id].append(op)
    virements_desequilibres = []
    for virement in virements:
        ops = ops_par_virement[virement.pk]
        debit = sum((op.montant for op in ops if op.type == "debit"), ZERO)
        credit = sum((op.montant for op in ops if op.type == "credit"), ZERO)
        if debit != credit or debit != virement.montant:
            virements_desequilibres += ops
    controles.append(_controle(
        6, "Équilibre des virements internes",
        theorique=0, reel=len(virements_desequilibres), format="nombre",
        aide="Chaque virement interne doit générer un débit et un crédit de montant identique.",
        detail=virements_desequilibres,
    ))

    # ------------------------------------------------------------------
    # 7. Doublons probables de saisie (avertissement : indécidable automatiquement)
    # ------------------------------------------------------------------
    groupes = {}
    for operation in operations:
        cle = (operation.date, operation.montant, operation.type, operation.libelle)
        groupes.setdefault(cle, []).append(operation)
    doublons = []
    for cle, ops in groupes.items():
        # Des références de paiement distinctes prouvent des opérations différentes
        references = {op.ref_piece for op in ops if op.ref_piece}
        if len(ops) > 1 and len(references) < len(ops):
            doublons += ops
    controles.append(_controle(
        7, "Doublons probables de saisie",
        theorique=0, reel=len(doublons), format="nombre", niveau="avertissement",
        aide="Opérations de même date, même montant et même libellé : à vérifier, elles peuvent être légitimes.",
        detail=sorted(doublons, key=lambda o: (o.date, o.pk)),
    ))

    # ------------------------------------------------------------------
    # 8. Mode de règlement renseigné
    # ------------------------------------------------------------------
    sans_mode = list(operations.filter(mode__isnull=True).order_by("date"))
    controles.append(_controle(
        8, "Mode de règlement renseigné",
        theorique=0, reel=len(sans_mode), format="nombre", niveau="avertissement",
        aide="Le mode de règlement facilite le rapprochement avec les lignes du relevé.",
        detail=sans_mode,
    ))

    # Lien vers l'écran de modification adapté (virement, régularisation ou opération),
    # en gardant la trace de la page appelante pour y revenir après l'enregistrement
    for controle in controles:
        for operation in controle["detail"]:
            operation.url_modifier = Get_url_modifier(operation, retour=retour)

    return controles


def _solde(queryset):
    stats = queryset.aggregate(
        debit=Sum("montant", filter=Q(type="debit")),
        credit=Sum("montant", filter=Q(type="credit")),
    )
    return _arrondi((stats["credit"] or ZERO) - (stats["debit"] or ZERO))


def Get_synthese(controles):
    """ Renvoie (nbre_ok, nbre_erreurs, nbre_avertissements, etat_global) """
    nbre_ok = len([c for c in controles if c["etat"] == "OK"])
    nbre_erreurs = len([c for c in controles if c["etat"] == "ERREUR"])
    nbre_avertissements = len([c for c in controles if c["etat"] == "AVERTISSEMENT"])
    if nbre_erreurs:
        etat_global = "ERREUR"
    elif nbre_avertissements:
        etat_global = "AVERTISSEMENT"
    else:
        etat_global = "OK"
    return nbre_ok, nbre_erreurs, nbre_avertissements, etat_global
