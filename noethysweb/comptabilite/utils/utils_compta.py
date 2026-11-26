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


def Cle_tri_num_piece(operation):
    """
    Tri des numéros de pièce dans l'ordre humain : 1, 2, 10 et non 1, 10, 2.

    Le numéro est stocké en texte, car il peut être alphanumérique selon le mode de
    règlement : un tri SQL le classe donc caractère par caractère. Les numéros purement
    numériques passent d'abord, par valeur croissante ; les autres suivent, par ordre
    alphabétique. Les opérations sans numéro ferment la marche.
    """
    numero = (operation.num_piece or "").strip()
    if not numero:
        return (2, 0, "")
    if numero.isdigit():
        return (0, int(numero), "")
    return (1, 0, numero.lower())


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


def Get_montant_non_ventile(comptes=None, type_operation=None, date_debut=None, date_fin=None):
    """
    Part des opérations qui n'est ventilée sur aucune catégorie, par type.

    Les totaux des rapports sont bâtis sur les ventilations : une opération saisie mais
    non ventilée disparaîtrait donc des résultats alors que l'argent est bien passé sur
    le compte. On mesure ici ce reliquat pour pouvoir l'afficher et le compter.

    Les virements internes et les régularisations d'avance sont exclus : ils n'ont pas
    de ventilation par construction, ce ne sont ni des dépenses ni des recettes.
    """
    from core.models import ComptaOperation, ComptaVentilation

    conditions = Q(compte__in=comptes) & Q(virement__isnull=True) & Q(regul_avance=False)
    if type_operation:
        conditions &= Q(type=type_operation)
    if date_debut:
        conditions &= Q(date__gte=date_debut)
    if date_fin:
        conditions &= Q(date__lte=date_fin)

    operations = ComptaOperation.objects.filter(conditions)
    total_operations = operations.aggregate(total=Sum("montant"))["total"] or ZERO
    total_ventile = ComptaVentilation.objects.filter(
        operation__in=operations).aggregate(total=Sum("montant"))["total"] or ZERO
    return Arrondi(total_operations) - Arrondi(total_ventile)


def Get_resultat_projet(comptes=None, structures=None, date_debut=None, date_fin=None):
    """
    Résultat du projet pour une sélection de comptes, sur une période.

    Même périmètre que le Bilan financier : ventilations des catégories au bilan,
    auxquelles s'ajoutent les règlements encaissés par l'organisateur, qui ne
    transitent pas par les comptes mais constituent bien une recette.
    Renvoie (total_credit, total_debit, total_encaissement, resultat).
    """
    from core.models import ComptaVentilation

    conditions = Q(operation__compte__in=comptes) & Q(categorie__bilan=True)
    if date_debut:
        conditions &= Q(operation__date__gte=date_debut)
    if date_fin:
        conditions &= Q(operation__date__lte=date_fin)

    totaux = ComptaVentilation.objects.filter(conditions).values("categorie__type").annotate(total=Sum("montant"))
    par_type = {ligne["categorie__type"]: ligne["total"] or ZERO for ligne in totaux}
    total_credit = par_type.get("credit", ZERO)
    total_debit = par_type.get("debit", ZERO)

    total_encaissement = sum(
        (bloc["total"] for bloc in Get_reglements_encaissement(
            structures=structures, date_debut=date_debut, date_fin=date_fin)),
        ZERO)
    total_credit += total_encaissement

    return Arrondi(total_credit), Arrondi(total_debit), Arrondi(total_encaissement), Arrondi(total_credit - total_debit)


def Get_total_categorie(categorie, comptes=None, date_debut=None, date_fin=None):
    """ Total ventilé sur une catégorie, pour une sélection de comptes et une période """
    from core.models import ComptaVentilation

    conditions = Q(operation__compte__in=comptes) & Q(categorie=categorie)
    if date_debut:
        conditions &= Q(operation__date__gte=date_debut)
    if date_fin:
        conditions &= Q(operation__date__lte=date_fin)
    return Arrondi(ComptaVentilation.objects.filter(conditions).aggregate(total=Sum("montant"))["total"] or ZERO)


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
