# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import json, decimal
from collections import Counter
from django.views.generic import TemplateView
from django.db.models import Q, Sum
from core.views.base import CustomView
from core.models import ComptaVentilation, ComptaOperationBudgetaire, ComptaCategorieBudget, ComptaCategorie, Reglement, Ventilation
from comptabilite.forms.liste_ventilation import Formulaire
from django.urls import reverse

class View(CustomView, TemplateView):
    menu_code = "liste_ventilation"
    template_name = "comptabilite/liste_ventilation.html"

    def get_context_data(self, **kwargs):
        context = super(View, self).get_context_data(**kwargs)
        context['page_titre'] = "Liste des opérations par catégorie"
        context['afficher_menu_brothers'] = True
        if "form_parametres" not in kwargs:
            context['form_parametres'] = Formulaire(request=self.request)
        return context

    def post(self, request, **kwargs):
        form = Formulaire(request.POST, request=self.request)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form_parametres=form))

        liste_lignes = self.Get_resultats(parametres=form.cleaned_data)
        total_montant = sum(ligne["montant"] for ligne in liste_lignes)
        context = {
            "form_parametres": form,
            "liste_lignes": json.dumps(liste_lignes),
            "total_montant": total_montant,
        }
        return self.render_to_response(self.get_context_data(**context))

    def Get_resultats(self, parametres={}):
        comptes = parametres["comptes"]
        categorie = parametres["categorie"]

        ventilations = (
            ComptaVentilation.objects.filter(
                operation__compte__in=comptes,
                categorie=categorie
            )
            .select_related("categorie", "operation", "operation__compte")
            .order_by("-operation__date")
        )

        lignes = []

        for v in ventilations:
            if not v.categorie_id:
                continue

                # Sécurité : on vérifie que l'opération et le compte existent bien
            url_modifier = ""
            if v.operation and v.operation.compte:
                    id_compte = v.operation.compte.idcompte
                    id_operation = v.operation.idoperation

                    # Génération de l'URL avec les deux paramètres positionnels : <int:categorie> et <int:pk>
                    url_modifier = reverse(
                        'operations_tresorerie_modifier',
                        args=[id_compte, id_operation]
                    )

            lignes.append({
                "id": v.idventilation,
                "nom": v.operation.libelle,
                "date": v.operation.date.strftime("%d/%m/%Y") if v.operation.date else "",
                "compte": v.operation.compte.nom if v.operation.compte else "",
                "montant": float(v.montant or 0),
                "url_modifier": url_modifier,
            })

        return lignes