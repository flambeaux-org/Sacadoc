# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging
logger = logging.getLogger(__name__)
from django.urls import reverse, NoReverseMatch


# Palette des accès rapides : une clé de couleur par domaine fonctionnel.
COULEURS = {
    "bleu": "#3c8dbc",
    "vert": "#306e47",
    "orange": "#ff851b",
    "rouge": "#c22727",
    "violet": "#6f42c1",
    "gris": "#6c757d",
}

# Catalogue des accès rapides aux fonctions de base de Sacadoc.
# Chaque groupe correspond à un widget du tableau de bord (la clé est le code du widget
# ET le nom de son template dans core/accueil/widgets/).
# Boutons : "url" sert à la fois de nom d'URL et de code de permission ("core.<url>"),
# sauf si "permission" ou "args" sont précisés. "couleur" est héritée du groupe.
GROUPES = {
    "acces_rapides_individus": {
        "label": "Accès rapides : Individus et inscriptions",
        "titre": "Individus et inscriptions",
        "icone": "users",
        "couleur": "bleu",
        "boutons": [
            {"url": "suivi_administratif_liste", "titre": "Suivi administratif", "icone": "table"},
            {"url": "famille_liste", "titre": "Familles", "icone": "users"},
            {"url": "demandes_portail_liste", "titre": "Inscriptions en attentes", "icone": "history"},
            {"url": "inscriptions_liste", "titre": "Inscriptions", "icone": "pencil-square-o"},
            {"url": "edition_renseignements", "titre": "Fiches de renseignements", "icone": "id-card-o"},
            {"url": "demande_approbation_liste", "titre": "Demandes de vérification", "icone": "check-square-o"},
            {"url": "registre_presence", "titre": "Registre de présence", "icone": "book"},
            {"url": "famille_attestations", "titre": "Attestations de présence", "icone": "certificate"},
            {"url": "traitement_liste", "titre": "Traitements sanitaires", "icone": "medkit"},
        ],
    },
    "acces_rapides_portail": {
        "label": "Accès rapides : Portail et communication",
        "titre": "Portail et communication",
        "icone": "globe",
        "couleur": "violet",
        "boutons": [
            {"url": "questionnaires_individus_liste", "titre": "Questionnaires", "icone": "question-circle-o"},
            {"url": "sondages_reponses_resume", "titre": "Formulaires", "icone": "wpforms"},
            {"url": "articles_liste", "titre": "Articles du blog", "icone": "newspaper-o"},
            {"url": "albums_liste", "titre": "Albums photos", "icone": "picture-o"},
            {"url": "liste_pieces_manquantes", "titre": "Pièces à recevoir", "icone": "inbox"},
            {"url": "portail_documents_liste", "titre": "Pièces à diffuser", "icone": "share-square-o"},
            {"url": "messagerie_portail", "titre": "Messagerie", "icone": "comments-o"},
            {"url": "editeur_emails", "titre": "Éditeur d'emails", "icone": "envelope-o"},
        ],
    },
    "acces_rapides_finances": {
        "label": "Accès rapides : Finances et facturation",
        "titre": "Finances et facturation",
        "icone": "money",
        "couleur": "vert",
        "boutons": [
            {"url": "liste_reglements", "titre": "Ajouter un règlement", "icone": "plus-circle"},
            {"url": "liste_soldes", "titre": "Soldes", "icone": "balance-scale"},
            {"url": "liste_prestations", "titre": "Prestations", "icone": "shopping-basket"},
            {"url": "liste_deductions", "titre": "Déductions", "icone": "minus-circle"},
            #{"url": "factures_generation", "titre": "Générer les factures", "icone": "cogs"},
            #{"url": "liste_factures", "titre": "Factures", "icone": "file-text-o"},
        ],
    },
    "acces_rapides_comptabilite": {
        "label": "Accès rapides : Comptabilité",
        "titre": "Comptabilité",
        "icone": "line-chart",
        "couleur": "rouge",
        "boutons": [
            {"url": "operations_tresorerie_liste", "titre": "Opérations de trésorerie", "icone": "exchange"},
            {"url": "suivi_compta", "titre": "Bilan financier", "icone": "line-chart"},
            {"url": "suivi_budget", "titre": "Suivi du budget", "icone": "pie-chart"},
            {"url": "liste_ventilation", "titre": "Opérations par catégorie", "icone": "sitemap"},
            {"url": "edition_justifs", "titre": "Justificatifs PDF", "icone": "file-pdf-o"},
        ],
    },
    "acces_rapides_outils": {
        "label": "Accès rapides : Activités et outils",
        "titre": "Activités et outils",
        "icone": "wrench",
        "couleur": "orange",
        "boutons": [
            {"url": "structures_liste", "titre": "Structures", "icone": "sitemap"},
            {"url": "activites_liste", "titre": "Mes activités", "icone": "calendar"},
            {"url": "procedures", "titre": "Procédures", "icone": "list-ol"},
        ],
    },
}


def Get_groupe(code=None, user=None):
    """ Renvoie un groupe d'accès rapides prêt à afficher, filtré selon les permissions de l'utilisateur """
    groupe = GROUPES.get(code)
    if not groupe:
        return None

    boutons = []
    for bouton in groupe["boutons"]:
        # Vérification de la permission (le code de permission est le nom de l'URL)
        permission = bouton.get("permission", bouton["url"])
        if user and not user.has_perm("core.%s" % permission):
            continue

        # Résolution de l'URL : un bouton dont l'URL n'existe pas est simplement ignoré
        try:
            url = reverse(bouton["url"], args=bouton.get("args"))
        except NoReverseMatch:
            logger.warning("Accès rapide ignoré : URL '%s' introuvable." % bouton["url"])
            continue

        boutons.append({
            "titre": bouton["titre"],
            "icone": bouton.get("icone", "chevron-right"),
            "couleur": COULEURS.get(bouton.get("couleur", groupe["couleur"]), COULEURS["gris"]),
            "url": url,
        })

    return {
        "titre": groupe["titre"],
        "icone": groupe["icone"],
        "couleur": COULEURS.get(groupe["couleur"], COULEURS["gris"]),
        "boutons": boutons,
    }
