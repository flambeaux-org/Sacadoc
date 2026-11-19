#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.
#
#  Petites fonctions communes aux vues et utilitaires de comptabilité.

import datetime
import decimal

from django.db.models import Case, DecimalField, F, Sum, When
from django.urls import reverse

ZERO = decimal.Decimal("0.00")


def Arrondi(valeur):
    """ Arrondit un montant au centime (passage par str pour éviter les artefacts des float) """
    if valeur is None:
        return ZERO
    if not isinstance(valeur, decimal.Decimal):
        valeur = decimal.Decimal(str(valeur))
    return valeur.quantize(decimal.Decimal("0.01"))


def Convert_date(texte):
    """ Convertit une date au format YYYY-MM-DD en date, ou None """
    if not texte:
        return None
    try:
        return datetime.datetime.strptime(texte, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def Convert_montant(texte):
    """ Convertit un montant saisi (virgule ou point) en Decimal, ou None """
    if texte in (None, ""):
        return None
    try:
        return decimal.Decimal(str(texte).replace(",", ".").replace(" ", ""))
    except decimal.InvalidOperation:
        return None


def Agreger(queryset):
    """ Renvoie (total_debit, total_credit, solde) d'un queryset d'opérations """
    stats = queryset.aggregate(
        total_debit=Sum(Case(When(type="debit", then=F("montant")), output_field=DecimalField(), default=0)),
        total_credit=Sum(Case(When(type="credit", then=F("montant")), output_field=DecimalField(), default=0)),
    )
    total_debit = stats["total_debit"] or ZERO
    total_credit = stats["total_credit"] or ZERO
    return total_debit, total_credit, total_credit - total_debit


def Get_url_modifier(operation):
    """
    Renvoie l'écran de modification adapté à une opération de trésorerie.
    Un virement ou une régularisation d'avance doit être modifié depuis son propre
    écran : éditer une seule de ses opérations romprait l'équilibre de l'ensemble.
    """
    if operation.virement_id:
        return reverse("virements_modifier", args=[operation.virement_id])
    if operation.regul_avance:
        return reverse("regul_avances_modifier", args=[operation.pk])
    return reverse("operations_tresorerie_modifier", args=[operation.compte_id, operation.pk])
