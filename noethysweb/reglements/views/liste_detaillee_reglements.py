# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import json
from django.views.generic import TemplateView
from django.db.models import Sum
from core.views.base import CustomView
from core.models import Reglement, Activite, ModeReglement
from reglements.forms.liste_detaillee_reglements import Formulaire
from core.utils import utils_dates


class View(CustomView, TemplateView):
    menu_code = "liste_detaillee_reglements"
    template_name = "reglements/liste_detaillee_reglements.html"

    def get_context_data(self, **kwargs):
        context = super(View, self).get_context_data(**kwargs)
        context['page_titre'] = "Liste détaillée des règlements"
        context['form_parametres'] = Formulaire(request=self.request)
        return context

    def post(self, request, **kwargs):
        form = Formulaire(request.POST, request=self.request)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form_parametres=form))

        # Obtenir les résultats
        liste_lignes = self.Get_resultats(parametres=form.cleaned_data)
        afficher_colonne_objet = any(ligne.get('objet') for ligne in liste_lignes)

        context = {
            "form_parametres": form,
            "liste_lignes": json.dumps(liste_lignes),
            "titre": "Synthèse des prestations",
            "afficher_colonne_objet": afficher_colonne_objet

        }
        return self.render_to_response(self.get_context_data(**context))

    def Get_resultats(self, parametres={}):
        activite_id = parametres.get("activite")
        mode_regl = parametres.get("mode_regl")
        export_compta = parametres.get("export")

        # Filtrer et trier les règlements
        query = Reglement.objects.select_related("famille", "mode", "emetteur", "payeur")
        if activite_id:
            query = query.filter(ventilation__prestation__activite=activite_id)
        if mode_regl:
            query = query.filter(mode=mode_regl)
        if export_compta:
            mode_ids = [1, 5, 2, 6]
            query = query.filter(mode__in=mode_ids)
            reglements = query.order_by('-date').distinct()
            liste_lignes = [
                {
                    "date": utils_dates.ConvertDateToFR(reglement.date),
                    "montant": float(reglement.montant),
                    "objet": f"Pension - {reglement.famille.nom} - {reglement.mode.label}",
                }
                for reglement in reglements
            ]
            return liste_lignes

        else:
            reglements = query.order_by('-date').distinct()
            liste_lignes = [
                {
                    "idreglement": reglement.pk,
                    "date": utils_dates.ConvertDateToFR(reglement.date),
                    "mode": reglement.mode.label,
                    "emetteur": reglement.emetteur.nom if reglement.emetteur else "",
                    "numero_piece": reglement.numero_piece,
                    "famille": reglement.famille.nom,
                    "payeur": reglement.payeur.nom,
                    "montant": float(reglement.montant),
                }
                for reglement in reglements
            ]
            return liste_lignes
