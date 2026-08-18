# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import datetime

from django.db.models import Q
from django.shortcuts import redirect
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from core.models import Article, Consommation, Inscription, Lecture, PortailMessage, SondageRepondant
from cotisations.utils import utils_cotisations_manquantes
from individus.utils import (
    utils_pieces_manquantes,
    utils_vaccinations,
)
from portail.utils import utils_renseignements_manquants, utils_questionnaires_manquants, utils_sondages_manquants
from portail.views.base import CustomView


class Accueil(CustomView, TemplateView):
    template_name = "portail/accueil.html"
    menu_code = "portail_accueil"

    def dispatch(self, request, *args, **kwargs):
        """Redirect to utilisateur if not famille."""
        if self.request.user.is_authenticated and self.request.user.categorie != "famille":
            return redirect("accueil")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(Accueil, self).get_context_data(**kwargs)
        context['page_titre'] = _("Accueil")

        # Pièces manquantes
        context['nbre_pieces_manquantes'] = len(utils_pieces_manquantes.Get_pieces_manquantes(famille=self.request.user.famille, only_invalides=True, exclure_individus=self.request.user.famille.individus_masques.all()))

        # Renseignements manquants
        context['nbre_renseignements_manquants'] = utils_renseignements_manquants.Get_renseignements_manquants(famille=self.request.user.famille)['nbre']

        # Questionnaires manquants (par individu)
        questions_manquantes_famille = utils_questionnaires_manquants.Get_questions_manquantes_famille(famille=self.request.user.famille)
        context['nbre_questionnaires_manquants'] = sum(data["nbre"] for data in questions_manquantes_famille.values())

        # Messages non lus
        context['nbre_messages_non_lus'] = len(PortailMessage.objects.filter(famille=self.request.user.famille, utilisateur__isnull=False, date_lecture__isnull=True))

        # Récupération des activités de la famille
        conditions = Q(famille=self.request.user.famille) & (Q(date_fin__isnull=True) | Q(date_fin__gte=datetime.date.today()))
        inscriptions = Inscription.objects.select_related("activite", "individu").filter(conditions)
        activites = list({inscription.activite: True for inscription in inscriptions}.keys())

        # Vaccins manquants
        context["nbre_vaccinations_manquantes"] = sum([len(liste_vaccinations) for individu, liste_vaccinations in utils_vaccinations.Get_vaccins_obligatoires_by_inscriptions(inscriptions=inscriptions).items()])

        # Vérfications manquantes
        inscriptions = Inscription.objects.filter(famille=self.request.user.famille, besoin_certification=True)
        context["nbre_verifications_manquantes"] = inscriptions.count()

        # Adhésions manquantes
        if context["parametres_portail"].get("cotisations_afficher_page", False):
            context["cotisations_manquantes"] = utils_cotisations_manquantes.Get_cotisations_manquantes(famille=self.request.user.famille, exclure_individus=self.request.user.famille.individus_masques.all())

        # Sondages manquants
        context["nbre_sondages_manquants"] = len(utils_sondages_manquants.Get_sondages_manquants(famille=self.request.user.famille))

            # Articles
        conditions = Q(structure__visible=True) & Q(statut="publie") & Q(date_debut__lte=datetime.datetime.now()) & (Q(date_fin__isnull=True) | Q(date_fin__gte=datetime.datetime.now()))
        conditions &= (Q(public__in=("toutes", "presents", "presents_groupes")) | (Q(public="inscrits") & Q(activites__in=activites)))
        articles = Article.objects.select_related("image_article", "album", "sondage", "auteur").filter(conditions).distinct().order_by("-date_debut")
        selection_articles = []
        popups = []
        for article in articles:
            # Filtre les présents si besoin
            if article.public in ("presents", "presents_groupes"):
                conditions = Q(inscription__famille=self.request.user.famille, date__gte=article.present_debut, date__lte=article.present_fin, etat__in=("reservation", "present"))
                if article.public == "presents":
                    conditions &= Q(activite__in=article.activites.all())
                if article.public == "presents_groupes":
                    conditions &= Q(groupe__in=article.groupes.all())
                valide = Consommation.objects.filter(conditions).exists()
            else:
                valide = True
            if valide:
                selection_articles.append(article)
                if article.texte_popup:
                    popups.append(article)
        # Séparer les articles avec formulaire (sondage) non répondu → alertes
        sondages_des_articles = [a.sondage for a in selection_articles if a.sondage]
        if sondages_des_articles:
            sondages_repondus = set(
                SondageRepondant.objects.filter(
                    sondage__in=sondages_des_articles,
                    famille=self.request.user.famille,
                ).values_list('sondage_id', flat=True)
            )
        else:
            sondages_repondus = set()

        articles_normaux = []
        nbre_formulaires_manquants = 0
        for article in selection_articles:
            if article.sondage and article.sondage.idsondage not in sondages_repondus:
                nbre_formulaires_manquants += 1
            else:
                articles_normaux.append(article)

        context['articles'] = articles_normaux
        context['nbre_formulaires_manquants'] = nbre_formulaires_manquants

        # Popups
        context['articles_popups'] = []
        if popups:
            popups_lus = [lecture.article for lecture in Lecture.objects.filter(article__in=popups, famille=self.request.user.famille)]
            for popup in popups:
                if popup not in popups_lus:
                    context['articles_popups'].append(popup)
                    Lecture.objects.create(famille=self.request.user.famille, article=popup)

        return context
