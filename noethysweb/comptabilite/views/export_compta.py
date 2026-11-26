# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import unicodedata
from django.http import HttpResponse
from django.views.generic import TemplateView
from core.views.base import CustomView
from comptabilite.forms.export_compta import Formulaire
from comptabilite.utils import utils_export_compta


def Nom_fichier(compte=None, date_debut=None, date_fin=None):
    nom_compte = "".join(c for c in unicodedata.normalize("NFD", compte.nom) if unicodedata.category(c) != "Mn")
    nom_compte = "".join(c if c.isalnum() else "_" for c in nom_compte).strip("_")
    return "Export_compta_%s_%s_%s.xlsx" % (nom_compte, date_debut.strftime("%Y%m%d"), date_fin.strftime("%Y%m%d"))


class View(CustomView, TemplateView):
    menu_code = "export_compta"
    template_name = "comptabilite/export_compta.html"

    def get_context_data(self, **kwargs):
        context = super(View, self).get_context_data(**kwargs)
        context['page_titre'] = "Export compta"
        context['box_titre'] = ""
        context['box_introduction'] = ("Sélectionnez un compte et une période puis cliquez sur le bouton Générer le fichier Excel. "
                                       "Le classeur généré contient une feuille Recettes et une feuille Dépenses reprenant la mise en forme "
                                       "du tableau de suivi du budget, afin de faciliter la retranscription des opérations.")
        if "form" not in kwargs:
            context['form'] = Formulaire(request=self.request)
        return context

    def post(self, request, **kwargs):
        form = Formulaire(request.POST, request=request)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))

        compte = form.cleaned_data["compte"]
        date_debut = form.cleaned_data["date_debut"]
        date_fin = form.cleaned_data["date_fin"]

        exporter = utils_export_compta.Exporter(compte=compte, date_debut=date_debut, date_fin=date_fin,
                                                structures=request.user.structures.all())
        contenu = exporter.Generer()

        response = HttpResponse(contenu, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response["Content-Disposition"] = 'attachment; filename="%s"' % Nom_fichier(compte=compte, date_debut=date_debut, date_fin=date_fin)
        return response
