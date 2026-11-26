#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.
#
#  Petites fonctions communes aux vues et utilitaires de comptabilité.

import datetime
import decimal
from collections import defaultdict

from django.db.models import Case, DecimalField, F, Q, Sum, When
from django.urls import reverse
from django.utils.http import urlencode

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


def Cle_tri_categorie(categorie):
    """
    Ordre d'affichage des catégories dans les tableaux d'analyse.

    Les catégories liées à l'organisateur (part orga., cotisations...) sont reléguées
    en fin de groupe Crédit ou Débit : ce sont des sommes qui ne relèvent pas de la
    gestion courante du projet, on les lit après les catégories ordinaires.
    """
    return (categorie.type, bool(categorie.orga), categorie.nom)


def Get_label_encaissement():
    """ Libellé de la case "Encaissé par l'organisateur" cochée sur le mode de règlement.
        On le reprend du modèle pour que l'affichage suive si le champ est renommé. """
    from core.models import ModeReglement
    verbose_name = str(ModeReglement._meta.get_field("encaissement").verbose_name)
    return verbose_name[:1].lower() + verbose_name[1:]


def Get_reglements_encaissement(structures=None, date_debut=None, date_fin=None):
    """
    Règlements encaissés par l'organisateur (chèques vacances, bons CAF...), regroupés par mode.

    Ces règlements ne transitent pas par les comptes bancaires mais constituent bien une
    recette du projet : le Bilan financier et le Suivi du budget les comptent tous deux.
    Le périmètre suit les structures passées par l'appelant (celles des comptes analysés),
    et non la structure du premier compte seulement.
    """
    from core.models import Ventilation

    if not structures:
        return []

    conditions = Q(
        reglement__mode__encaissement=True,
        prestation__activite__structure__in=structures,
    )
    if date_debut:
        conditions &= Q(reglement__date__gte=date_debut)
    if date_fin:
        conditions &= Q(reglement__date__lte=date_fin)

    ventilations = (
        Ventilation.objects.filter(conditions)
        .select_related("reglement", "reglement__famille", "reglement__mode", "reglement__compte")
        .order_by("reglement__date")
    )

    reglements_par_mode = defaultdict(list)
    for ventilation in ventilations:
        reglement = ventilation.reglement
        reglements_par_mode[reglement.mode.label].append({
            "id": reglement.idreglement,
            "date": reglement.date.strftime("%d/%m/%Y") if reglement.date else "",
            "compte": reglement.compte.nom if reglement.compte else "",
            "famille": reglement.famille.nom if reglement.famille else "",
            "montant": Arrondi(ventilation.montant),
        })

    resultat = []
    for mode_label in sorted(reglements_par_mode.keys()):
        liste = reglements_par_mode[mode_label]
        resultat.append({
            "mode": mode_label,
            "reglements": liste,
            "total": sum((r["montant"] for r in liste), ZERO),
        })
    return resultat


def Get_url_modifier(operation, retour=None):
    """
    Renvoie l'écran de modification adapté à une opération de trésorerie.
    Un virement ou une régularisation d'avance doit être modifié depuis son propre
    écran : éditer une seule de ses opérations romprait l'équilibre de l'ensemble.

    "retour" est l'adresse de la page appelante : elle est transmise en paramètre
    "next" pour que l'enregistrement y ramène l'utilisateur au lieu de le renvoyer
    systématiquement vers la liste des opérations de trésorerie.
    """
    if operation.virement_id:
        url = reverse("virements_modifier", args=[operation.virement_id])
    elif operation.regul_avance:
        url = reverse("regul_avances_modifier", args=[operation.pk])
    else:
        url = reverse("operations_tresorerie_modifier", args=[operation.compte_id, operation.pk])
    if retour:
        url = "%s?%s" % (url, urlencode({"next": retour}))
    return url
