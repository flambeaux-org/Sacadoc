# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.
#
#  Détermine quelles opérations sont réellement passées sur le relevé bancaire.
#
#  Deux familles d'opérations ne transitent jamais par le compte bancaire :
#    - les avances non régularisées : la dépense est payée par la personne qui
#      avance les fonds ; seule l'opération de régularisation est un mouvement
#      bancaire ;
#    - les opérations ventilées sur une catégorie "orga" (encaissées par le
#      Mouvement) : l'argent ne transite pas par le compte local.
#
#  Les inclure dans le rapprochement rend l'écart avec le relevé insoluble.

from core.models import ComptaOperation, ComptaVentilation, CompteBancaire
from comptabilite.utils.utils_compta import ZERO, Agreger  # noqa: F401 (Agreger réexporté)


def Get_ids_hors_releve(idcompte):
    """ Renvoie les ids des opérations d'un compte qui ne passent pas sur le relevé """
    ids_orga = set(ComptaVentilation.objects.filter(
        categorie__orga=True, operation__compte_id=idcompte
    ).values_list("operation_id", flat=True))

    ids_avances = set(ComptaOperation.objects.filter(
        compte_id=idcompte, avance__isnull=False, regul_avance=False
    ).values_list("idoperation", flat=True))

    return ids_orga | ids_avances


def Get_operations(idcompte):
    """ Renvoie (operations_bancaires, operations_hors_releve) """
    toutes = ComptaOperation.objects.filter(compte_id=idcompte)
    ids_hors = Get_ids_hors_releve(idcompte)
    return toutes.exclude(pk__in=ids_hors), toutes.filter(pk__in=ids_hors)


def Get_anouveau(idcompte):
    """ Renvoie (date_anouveau, solde_anouveau) du compte """
    compte = CompteBancaire.objects.filter(pk=idcompte).first()
    if not compte:
        return None, ZERO
    return compte.date_anouveau, (compte.solde_anouveau or ZERO)


def _Get_compte(compte):
    """ Accepte une instance de CompteBancaire ou un id """
    if isinstance(compte, CompteBancaire):
        return compte
    return CompteBancaire.objects.filter(pk=compte).first()


def Get_solde_bancaire(comptes, date_fin=None):
    """
    Solde réellement disponible en banque pour une liste de comptes, à une date donnée.
    Sert de contrepoint au résultat "projet" des rapports, qui inclut lui les
    opérations hors banque (avances, part Mouvement).

    Comme la page de vérification, on part de l'à-nouveau du compte s'il est
    renseigné : les opérations antérieures peuvent être incomplètes. Si la date
    demandée précède l'à-nouveau, seul l'historique brut est disponible.
    """
    total = ZERO
    for compte in comptes:
        compte = _Get_compte(compte)
        if not compte:
            continue
        bancaires, _ = Get_operations(compte.pk)
        if date_fin:
            bancaires = bancaires.filter(date__lte=date_fin)
        date_anouveau = compte.date_anouveau
        if date_anouveau and (not date_fin or date_fin >= date_anouveau):
            _, _, mouvements = Agreger(bancaires.filter(date__gte=date_anouveau))
            total += (compte.solde_anouveau or ZERO) + mouvements
        else:
            _, _, solde = Agreger(bancaires)
            total += solde
    return total


def Get_mouvements_bancaires(comptes, date_debut=None, date_fin=None):
    """
    Variation du solde bancaire sur une période (opérations passées en banque).
    C'est la grandeur comparable au résultat d'une période : un solde, lui,
    cumule tout l'historique et les reports des exercices antérieurs.
    """
    total = ZERO
    for compte in comptes:
        bancaires, _ = Get_operations(compte.pk if hasattr(compte, "pk") else compte)
        if date_debut:
            bancaires = bancaires.filter(date__gte=date_debut)
        if date_fin:
            bancaires = bancaires.filter(date__lte=date_fin)
        _, _, mouvements = Agreger(bancaires)
        total += mouvements
    return total


def Get_perimetre(idcompte):
    """
    Renvoie le périmètre du rapprochement : les opérations bancaires postérieures
    à la date d'à-nouveau. Les opérations antérieures sont déjà rapprochées.
    """
    bancaires, hors_releve = Get_operations(idcompte)
    date_anouveau, solde_anouveau = Get_anouveau(idcompte)
    if date_anouveau:
        perimetre = bancaires.filter(date__gte=date_anouveau)
        anterieures = bancaires.filter(date__lt=date_anouveau)
    else:
        perimetre = bancaires
        anterieures = bancaires.none()
    return {
        "bancaires": bancaires,
        "hors_releve": hors_releve,
        "perimetre": perimetre,
        "anterieures": anterieures,
        "date_anouveau": date_anouveau,
        "solde_anouveau": solde_anouveau,
    }
