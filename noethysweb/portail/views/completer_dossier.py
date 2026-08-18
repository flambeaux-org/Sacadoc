# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import datetime, json
from django.contrib import messages
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.generic import TemplateView

from core.models import Inscription, Piece, PortailRenseignement, QuestionnaireReponse, Rattachement
from cotisations.utils import utils_cotisations_manquantes
from individus.utils import utils_impression_renseignements, utils_pieces_manquantes, utils_vaccinations
from portail.forms.transmettre_piece import Formulaire as FormulairePiece
from portail.utils import utils_questionnaires_manquants, utils_renseignements_manquants, utils_sondages_manquants
from portail.utils.utils_impression import add_watermark
from portail.views.base import CustomView


class View(CustomView, TemplateView):
    """ Assistant de complétion du dossier familial : une étape par catégorie d'informations, terminée par la vérification.
    Tout est traité directement sur cette page (formulaires embarqués), à l'exception des formulaires (sondages) dont
    la structure à plusieurs pages nécessite de rester sur leur propre parcours dédié. """
    menu_code = "portail_renseignements"
    template_name = "portail/completer_dossier.html"

    # ------------------------------------------------------------------ Construction des étapes

    def Get_etapes(self, famille, parametres_portail):
        etapes = []

        rattachements = Rattachement.objects.select_related("individu").filter(famille=famille, individu__deces=False).order_by("individu__nom", "individu__prenom")

        conditions = Q(famille=famille) & (Q(date_fin__isnull=True) | Q(date_fin__gte=datetime.date.today()))
        inscriptions = Inscription.objects.select_related("activite", "individu").filter(conditions)
        vaccins_manquants = utils_vaccinations.Get_vaccins_obligatoires_by_inscriptions(inscriptions=inscriptions)

        # Renseignements et vaccinations : une fiche par individu concerné, avec lien direct de correction
        items_renseignements, items_vaccinations = [], []
        for rattachement in rattachements:
            individu = rattachement.individu

            infos_perso = utils_renseignements_manquants.Get_renseignements_manquants_individu(individu=individu)
            if infos_perso["page_cible"] == "identite":
                items_renseignements.append({"individu": individu, "label": _("Identité incomplète"), "detail": infos_perso["message_manquant"], "url": reverse("portail_individu_identite_modifier", args=[rattachement.pk])})
            elif infos_perso["page_cible"] == "coords":
                items_renseignements.append({"individu": individu, "label": _("Coordonnées incomplètes"), "detail": infos_perso["message_manquant"], "url": reverse("portail_individu_coords_modifier", args=[rattachement.pk])})

            liste_vaccins = vaccins_manquants.get(individu)
            if liste_vaccins:
                items_vaccinations.append({
                    "individu": individu,
                    "label": _("%d vaccination(s) manquante(s)") % len(liste_vaccins),
                    "detail": ", ".join(vaccin["label"] for vaccin in liste_vaccins),
                    "url": reverse("portail_individu_vaccinations", args=[rattachement.pk]),
                })

        etapes.append({"code": "renseignements", "titre": _("Renseignements"), "icone": "id-card-o", "type": "inline", "items": items_renseignements})
        etapes.append({"code": "vaccinations", "titre": _("Vaccinations"), "icone": "medkit", "type": "inline", "items": items_vaccinations})

        # Pièces à fournir (traitées directement sur cette page)
        pieces_fournir = utils_pieces_manquantes.Get_pieces_manquantes(famille=famille, only_invalides=True, exclure_individus=famille.individus_masques.all())
        etapes.append({"code": "pieces", "titre": _("Pièces à fournir"), "icone": "file-text-o", "type": "pieces", "nbre": len(pieces_fournir), "pieces_fournir": pieces_fournir})

        # Questionnaires (traités directement sur cette page)
        questions_manquantes_famille = utils_questionnaires_manquants.Get_questions_manquantes_famille(famille=famille)
        individus_forms = []
        for data in questions_manquantes_famille.values():
            questions = data["questions"]
            if not questions:
                continue
            for question in questions:
                question.is_liste = question.controle.startswith("liste")
                if question.is_liste:
                    question.choix_list = question.choix.split(";")
                reponse_obj = QuestionnaireReponse.objects.filter(individu=data["individu"], question=question).first()
                question.reponse = reponse_obj.Get_reponse_for_ctrl() if reponse_obj else None
            individus_forms.append({"individu": data["individu"], "questions": questions})
        nbre_questionnaires = sum(len(bloc["questions"]) for bloc in individus_forms)
        etapes.append({"code": "questionnaires", "titre": _("Questionnaires"), "icone": "question-circle-o", "type": "questionnaires", "nbre": nbre_questionnaires, "individus_forms": individus_forms})

        # Formulaires (sondages) : parcours à plusieurs pages propre à chaque sondage, on renvoie vers sa page dédiée
        nbre_sondages = len(utils_sondages_manquants.Get_sondages_manquants(famille=famille))
        etapes.append({"code": "sondages", "titre": _("Formulaires"), "icone": "wpforms", "type": "redirect", "nbre": nbre_sondages,
                        "texte": _("Un formulaire est à compléter."), "url": reverse("portail_sondages")})

        # Adhésions (informatif, traité directement sur cette page)
        if parametres_portail.get("cotisations_afficher_page", False):
            cotisations_fournir = utils_cotisations_manquantes.Get_cotisations_manquantes(famille=famille, exclure_individus=famille.individus_masques.all())
            etapes.append({"code": "cotisations", "titre": _("Adhésions"), "icone": "credit-card", "type": "cotisations", "nbre": len(cotisations_fournir), "cotisations_fournir": cotisations_fournir})

        # Calcul du nombre d'éléments manquants et de l'état "complet" de chaque étape précédente
        for etape in etapes:
            if etape["type"] == "inline":
                etape["nbre"] = len(etape["items"])
            etape["complete"] = etape["nbre"] == 0

        # Vérifications (traitées directement sur cette page) : dernière étape, accessible une fois le reste complété
        # Le PDF de chaque fiche n'est généré qu'à l'affichage de cette étape (voir get_context_data), pour ne pas
        # alourdir le calcul des étapes lors de la simple consultation d'une autre étape.
        inscriptions_a_verifier = Inscription.objects.filter(famille=famille, besoin_certification=True, activite__actif=True).select_related("individu")
        inscriptions_rattachements = []
        for inscription in inscriptions_a_verifier:
            rattachement = Rattachement.objects.filter(individu=inscription.individu).first()
            if rattachement:
                inscriptions_rattachements.append({"inscription": inscription, "individu": inscription.individu, "rattachement": rattachement})
        etapes.append({
            "code": "verifications", "titre": _("Vérifications"), "icone": "check-square-o", "type": "verifications",
            "nbre": len(inscriptions_rattachements), "complete": len(inscriptions_rattachements) == 0,
            "inscriptions_rattachements": inscriptions_rattachements,
            "bloquee": not all(etape["complete"] for etape in etapes),
        })

        return etapes

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_titre'] = _("Compléter mon dossier")
        famille = self.request.user.famille

        etapes = self.Get_etapes(famille=famille, parametres_portail=context["parametres_portail"])
        context["etapes"] = etapes
        context["nbre_total_manquants"] = sum(etape["nbre"] for etape in etapes)

        # Détermination de l'étape active : celle demandée, sinon la première incomplète, sinon la dernière
        dict_etapes = {etape["code"]: etape for etape in etapes}
        code_etape = self.request.GET.get("etape")
        if code_etape not in dict_etapes:
            premiere_incomplete = next((etape for etape in etapes if not etape["complete"]), None)
            code_etape = premiere_incomplete["code"] if premiere_incomplete else etapes[-1]["code"]

        index_actif = [etape["code"] for etape in etapes].index(code_etape)
        context["etape_active"] = etapes[index_actif]
        context["etape_precedente"] = etapes[index_actif - 1] if index_actif > 0 else None
        context["etape_suivante"] = etapes[index_actif + 1] if index_actif < len(etapes) - 1 else None
        context["numero_etape"] = index_actif + 1
        context["nbre_etapes"] = len(etapes)

        if context["etape_active"]["type"] == "pieces" and "form_piece" not in context:
            context["form_piece"] = FormulairePiece(request=self.request)

        if context["etape_active"]["type"] == "verifications" and not context["etape_active"]["bloquee"] and not context["etape_active"]["complete"]:
            self.Generer_pdf_verifications(context["etape_active"]["inscriptions_rattachements"])

        return context

    def Generer_pdf_verifications(self, inscriptions_rattachements):
        """ Génère (ou récupère depuis le cache) le PDF de fiche individuelle utilisé pour la vérification """
        for item in inscriptions_rattachements:
            impression = utils_impression_renseignements.Impression(
                dict_donnees={"rattachements": [item["rattachement"].pk], "tri": "classe", "mode_condense": True}, request=self.request)
            if impression.erreurs:
                item["nom_fichier"] = None
                continue
            item["nom_fichier"] = "/media" + impression.Get_nom_fichier()

    # ------------------------------------------------------------------ Traitement des actions

    def post(self, request, *args, **kwargs):
        type_action = request.POST.get("type_action")
        if type_action == "verification":
            return self.Post_verification(request)
        if type_action == "questionnaire":
            return self.Post_questionnaire(request)
        if "selection_piece" in request.POST:
            # Le formulaire de transmission de pièce (réutilisé tel quel) n'a pas de champ "type_action"
            return self.Post_piece(request)
        return HttpResponseRedirect(reverse("portail_completer_dossier"))

    def Redirect_etape(self, code_etape):
        return HttpResponseRedirect(reverse("portail_completer_dossier") + "?etape=%s" % code_etape)

    def Post_verification(self, request):
        """ Reproduit le traitement de portail.views.verifications.View.post """
        inscription_id = request.POST.get("inscription_id")
        inscription = Inscription.objects.filter(pk=inscription_id, famille=self.request.user.famille).first()
        if inscription:
            inscription.besoin_certification = False
            inscription.save()

            rattachement = Rattachement.objects.filter(individu=inscription.individu).first()
            if rattachement:
                rattachement.certification_date = datetime.datetime.now()
                rattachement.save()

            messages.success(request, _("Vérification validée pour %s %s.") % (inscription.individu.prenom, inscription.individu.nom))
        return self.Redirect_etape("verifications")

    def Post_questionnaire(self, request):
        """ Reproduit le traitement de portail.views.questionnaires.View.post """
        individu_pk = request.POST.get("individu_pk")
        question_pk = request.POST.get("question_pk")
        question_ctrl = request.POST.get("question_ctrl")
        valeur = request.POST.get("valeur")

        reponse_valeur = valeur
        if question_ctrl in ("liste_deroulante", "liste_coches"):
            reponse_valeur = valeur or ""
            liste = [c.strip() for c in reponse_valeur.split(";") if c.strip()]
            if "RAS" not in liste:
                liste.append("RAS")
            reponse_valeur = ";".join(liste)

        reponse, created = QuestionnaireReponse.objects.get_or_create(individu_id=individu_pk, question_id=question_pk)
        reponse.reponse = reponse_valeur
        reponse.save()
        return self.Redirect_etape("questionnaires")

    def Post_piece(self, request):
        """ Reproduit le traitement de portail.views.transmettre_piece.Ajouter.form_valid """
        form = FormulairePiece(request.POST, request.FILES, request=self.request)
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form_piece=form))

        instance = form.save()

        # Historique et filigrane sur le document principal
        self.save_historique(instance=instance, titre=_("Ajouter une pièce"), form=form)
        if instance.document and str(instance.document.path).endswith('.pdf'):
            add_watermark(instance.document, "Sacadoc | Mouvement des flambeaux")
        PortailRenseignement.objects.create(famille=self.request.user.famille, individu=instance.individu, categorie="famille_pieces", code="Nouvelle pièce",
                                            validation_auto=True, nouvelle_valeur=json.dumps(instance.Get_nom(), cls=DjangoJSONEncoder), idobjet=instance.pk)

        # Documents complémentaires (2 à 5)
        for field_name in ("document1", "document2", "document3", "document4"):
            fichier = form.cleaned_data.get(field_name)
            if fichier:
                Piece.objects.create(
                    titre=form.cleaned_data.get('titre'), document=fichier, famille=self.request.user.famille,
                    individu=form.cleaned_data.get('individu'), type_piece=form.cleaned_data.get('type_piece'),
                    date_debut=form.cleaned_data.get('date_debut'), date_fin=form.cleaned_data.get('date_fin'), auteur=self.request.user,
                )

        messages.success(request, _("Les pièces ont été ajoutées avec succès."))
        return self.Redirect_etape("pieces")
