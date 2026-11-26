# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import decimal
from django.views.generic import TemplateView
from core.views.base import CustomView
from core.models import CompteBancaire
from comptabilite.forms.bilan_organisateur import Formulaire
from comptabilite.utils import utils_compta

ZERO = decimal.Decimal("0.00")


class View(CustomView, TemplateView):
    menu_code = "bilan_organisateur"
    template_name = "comptabilite/bilan_organisateur.html"

    def test_func_page(self):
        """ Page réservée aux membres du staff : elle agrège plusieurs comptes et
            structures, au-delà du périmètre d'un directeur de camp. """
        return self.request.user.is_staff

    def get_context_data(self, **kwargs):
        context = super(View, self).get_context_data(**kwargs)
        context['page_titre'] = "Bilan organisateur"
        context['afficher_menu_brothers'] = True
        if "form_parametres" not in kwargs:
            context['form_parametres'] = Formulaire(request=self.request)
        context.update(kwargs)
        return context

    def post(self, request, **kwargs):
        form = Formulaire(request.POST, request=self.request)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form_parametres=form))

        context = self.Get_resultats(parametres=form.cleaned_data)
        context["form_parametres"] = form
        return self.render_to_response(self.get_context_data(**context))

    def Get_resultats(self, parametres={}):
        structures = sorted(parametres["structures"], key=lambda structure: structure.nom)
        categories = sorted(parametres["categories"], key=utils_compta.Cle_tri_categorie)
        date_debut = parametres["date_debut"]
        date_fin = parametres["date_fin"]

        # Une colonne par structure : tous ses comptes (caisse, compte courant...) sont
        # agrégés. Un compte sans structure n'appartient à aucune colonne, son périmètre
        # d'analyse étant indéterminé.
        colonnes = []
        for structure in structures:
            comptes = list(CompteBancaire.objects.filter(structure=structure).order_by("nom"))
            colonnes.append({
                "structure": structure,
                "nom": structure.nom,
                "comptes": comptes,
                "libelle_comptes": ", ".join(compte.nom for compte in comptes) or "Aucun compte",
            })

        # Détail des catégories sélectionnées : une ligne par catégorie.
        # Les dépenses sont affichées en négatif pour que la colonne s'additionne.
        lignes_categories = []
        for categorie in categories:
            montants = []
            for colonne in colonnes:
                montant = utils_compta.Get_total_categorie(
                    categorie, comptes=colonne["comptes"], date_debut=date_debut, date_fin=date_fin)
                if categorie.type == "debit":
                    montant = -montant
                montants.append(montant)
            lignes_categories.append({
                "label": categorie.nom,
                "type": categorie.get_type_display(),
                "orga": bool(categorie.orga),
                "montants": montants,
                "total": sum(montants, ZERO),
            })

        total_categories = {
            "montants": [sum((ligne["montants"][index] for ligne in lignes_categories), ZERO)
                         for index in range(len(colonnes))],
        }
        total_categories["total"] = sum(total_categories["montants"], ZERO)

        # Résultat du projet, calculé comme au Bilan financier sur les comptes de la structure
        resultats = []
        for colonne in colonnes:
            _, _, _, resultat = utils_compta.Get_resultat_projet(
                comptes=colonne["comptes"], structures=[colonne["structure"].pk],
                date_debut=date_debut, date_fin=date_fin)
            resultats.append(resultat)

        return {
            "colonnes": colonnes,
            "lignes_categories": lignes_categories,
            "total_categories": total_categories,
            "ligne_resultat": {"montants": resultats, "total": sum(resultats, ZERO)},
            "date_debut": date_debut,
            "date_fin": date_fin,
            "nbre_colonnes": len(colonnes),
        }
