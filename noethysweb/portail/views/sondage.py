# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging, datetime
logger = logging.getLogger(__name__)
from portail.views.base import CustomView
from django.views.generic import TemplateView
from django.urls import reverse_lazy
from django.http import HttpResponseRedirect
from django.db.models import Q
from django.utils.translation import gettext as _
from core.models import Sondage, SondagePage, SondageQuestion, SondageRepondant, SondageReponse, Rattachement, Individu
from portail.forms.sondage import Formulaire
from portail.utils.utils_sondages_manquants import Get_sondages_manquants


class View_liste(CustomView, TemplateView):
    menu_code = "portail_sondages"
    template_name = "portail/sondages_liste.html"

    def get_context_data(self, **kwargs):
        context = super(View_liste, self).get_context_data(**kwargs)
        context["page_titre"] = _("Sondages manquants")
        context["box_titre"] = _("Liste des sondages à compléter")
        
        # Récupérer les sondages manquants pour la famille
        sondages_manquants = Get_sondages_manquants(famille=self.request.user.famille)
        
        # Organiser les sondages par type
        sondages_famille = []
        sondages_individu = {}
        
        for sondage_info in sondages_manquants:
            if sondage_info['type'] == 'famille':
                if sondage_info not in sondages_famille:
                    sondages_famille.append(sondage_info)
            else:  # type == 'individu'
                code = sondage_info['code']
                if code not in sondages_individu:
                    sondages_individu[code] = {
                        'sondage': sondage_info['sondage'],
                        'article': sondage_info['article'],
                        'titre': sondage_info['titre'],
                        'code': code,
                        'individus': []
                    }
                sondages_individu[code]['individus'].append(sondage_info['individu'])
        
        context['sondages_famille'] = sondages_famille
        context['sondages_individu'] = list(sondages_individu.values())
        
        return context


class View_questions(CustomView, TemplateView):
    menu_code = "portail_sondage"
    template_name = "portail/sondage/sondage_questions.html"

    def test_func(self):
        if not super(View_questions, self).test_func():
            return False
        # Sécurité : uniquement pour un individu rattaché à la famille
        idindividu = self.kwargs.get("idindividu", None)
        if idindividu and not Rattachement.objects.filter(famille=self.request.user.famille, individu_id=idindividu).exists():
            return False
        return True

    def get_context_data(self, **kwargs):
        context = super(View_questions, self).get_context_data(**kwargs)
        sondage = Sondage.objects.get(code=self.kwargs.get("code", None))
        idindividu = self.kwargs.get("idindividu", None)
        individu = Individu.objects.get(pk=idindividu) if idindividu else None

        context["sondage"] = sondage
        context["page_titre"] = "Formulaire"
        context["box_titre"] = sondage.titre
        if individu:
            context["box_titre"] += " - %s" % individu.prenom

        # Création des pages et des formulaires
        liste_pages = []
        questions = SondageQuestion.objects.filter(page__sondage=sondage).order_by("ordre")
        reponses = SondageReponse.objects.select_related("question").filter(repondant__sondage=sondage, repondant__famille=self.request.user.famille, repondant__individu=individu)
        for page in SondagePage.objects.filter(sondage=sondage).order_by("ordre"):
            liste_pages.append((page, Formulaire(request=self.request, page=page, questions=questions, reponses=reponses)))
        context["pages"] = liste_pages

        return context

    def post(self, request, **kwargs):
        idindividu = self.kwargs.get("idindividu", None)

        # Récupération des valeurs des forms
        valeurs = {}
        sondage = Sondage.objects.get(code=self.kwargs.get("code", None))
        questions = SondageQuestion.objects.filter(page__sondage=sondage).order_by("ordre")
        for page in SondagePage.objects.filter(sondage=sondage).order_by("ordre"):
            form = Formulaire(request.POST, request=request, page=page, questions=questions)
            if not form.is_valid():
                print("Form pas valide !")
            valeurs.update(form.cleaned_data)

        # Création ou récupération du répondant
        repondant, created = SondageRepondant.objects.get_or_create(sondage=sondage, famille=request.user.famille, individu_id=idindividu)
        if not created:
            repondant.date_modification = datetime.datetime.now()
            repondant.save()

        # Enregistrement des réponses
        for key, valeur in valeurs.items():
            if key.startswith("question_"):
                idquestion = int(key.split("_")[1])
                objet, created = SondageReponse.objects.update_or_create(repondant=repondant, question_id=idquestion, defaults={"reponse": valeur})

        if sondage.conclusion:
            return HttpResponseRedirect(reverse_lazy("portail_sondage_conclusion", kwargs={"code": sondage.code}))
        else:
            return HttpResponseRedirect(reverse_lazy("portail_accueil"))


class View_introduction(CustomView, TemplateView):
    menu_code = "portail_sondage"
    template_name = "portail/sondage/sondage_introduction.html"

    def get_context_data(self, **kwargs):
        context = super(View_introduction, self).get_context_data(**kwargs)
        sondage = Sondage.objects.get(code=self.kwargs.get("code", None))
        context["sondage"] = sondage
        context["page_titre"] = "Formulaire"
        context["box_titre"] = sondage.titre

        # Importation des sondages existants
        context["sondages_existants"] = SondageRepondant.objects.filter(sondage=sondage, famille=self.request.user.famille)

        # Importation des rattachements
        conditions_rattachements = Q(famille=self.request.user.famille, individu__deces=False)
        if sondage.public == "individu":
            conditions_rattachements &= Q(categorie__in=[int(pk) for pk in sondage.categories_rattachements])
        context['rattachements'] = Rattachement.objects.prefetch_related("individu").filter(conditions_rattachements).order_by("individu__nom", "individu__prenom")
        for rattachement in context['rattachements']:
            for repondant in context["sondages_existants"]:
                if repondant.individu_id == rattachement.individu_id:
                    rattachement.repondant = repondant
        return context


class View_conclusion(CustomView, TemplateView):
    menu_code = "portail_sondage"
    template_name = "portail/sondage/sondage_conclusion.html"

    def get_context_data(self, **kwargs):
        context = super(View_conclusion, self).get_context_data(**kwargs)
        sondage = Sondage.objects.get(code=self.kwargs.get("code", None))
        context["sondage"] = sondage
        context["page_titre"] = "Formulaire"
        context["box_titre"] = sondage.titre
        return context
