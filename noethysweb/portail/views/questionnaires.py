from django.shortcuts import redirect
from django.contrib import messages
from core.models import QuestionnaireReponse, QuestionnaireQuestion, Rattachement
from portail.utils.utils_questionnaires_manquants import Get_questions_manquantes_famille
from portail.views.base import CustomView
from django.views.generic import TemplateView
from django.utils.translation import gettext as _
import datetime

class View(CustomView, TemplateView):
    menu_code = "portail_questionnaires"
    template_name = "portail/questionnaires_manquants.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_titre'] = _("Réponses manquantes aux questionnaires")

        famille = self.request.user.famille
        questions_famille = Get_questions_manquantes_famille(famille)

        individus_forms = []
        for data in questions_famille.values():
            questions = data["questions"]
            if not questions:
                continue  # ignore les individus sans question manquante

            for question in questions:
                question.is_liste = question.controle.startswith("liste")
                if question.is_liste:
                    question.choix_list = question.choix.split(";")

                # Pré-remplissage avec la réponse existante
                reponse_obj = QuestionnaireReponse.objects.filter(
                    individu=data["individu"], question=question
                ).first()
                question.reponse = reponse_obj.Get_reponse_for_ctrl() if reponse_obj else None

            individus_forms.append({
                "individu": data["individu"],
                "questions": questions,
            })

        context['individus_forms'] = individus_forms
        return context

    def clean_questionnaire(self, question, valeur):
        """Nettoie la valeur d'une question avant enregistrement."""
        if question.controle in ["ligne_texte", "bloc_texte", "codebarres", "couleur"]:
            return valeur or ""

        elif question.controle in ["entier", "slider"]:
            try:
                return int(valeur)
            except (ValueError, TypeError):
                return None

        elif question.controle in ["decimal", "montant"]:
            try:
                return float(valeur)
            except (ValueError, TypeError):
                return None

        elif question.controle == "case_coche":
            return valeur == "on"

        elif question.controle in ["liste_deroulante", "liste_coches"]:
            choix = valeur or ""
            liste = [c.strip() for c in choix.split(";") if c.strip()]
            if "RAS" not in liste:
                liste.append("RAS")
            return ";".join(liste)

        elif question.controle == "liste_coches_ouinon":
            return valeur

        elif question.controle == "date":
            if valeur:
                try:
                    return datetime.datetime.strptime(valeur, "%Y-%m-%d").date()
                except ValueError:
                    return None
            return None

        return valeur

    def post(self, request, *args, **kwargs):
        """
        Enregistre une seule réponse soumise par formulaire.
        """

        individu_pk = request.POST.get("individu_pk")
        question_pk = request.POST.get("question_pk")
        question_ctrl = request.POST.get("question_ctrl")
        valeur = request.POST.get("valeur")

        # Sécurité : uniquement pour un individu rattaché à la famille
        if not Rattachement.objects.filter(famille=request.user.famille, individu_id=individu_pk).exists():
            messages.error(request, _("Vous ne pouvez pas répondre pour cet individu."))
            return redirect("portail_questionnaires")

        reponse_valeur = valeur
        if question_ctrl in ("liste_deroulante", "liste_coches"):
            reponse_valeur = valeur or ""
            liste = [c.strip() for c in reponse_valeur.split(";") if c.strip()]
            if "RAS" not in liste:
                liste.append("RAS")
            reponse_valeur = ";".join(liste)

        elif question_ctrl == "liste_coches_ouinon":
            # Pour ce type, on prend directement la valeur envoyée
            reponse_valeur = valeur

        #Crée la réponse
        try:
            reponse = QuestionnaireReponse.objects.get(
                individu_id=individu_pk,
                question_id=question_pk
            )
        except QuestionnaireReponse.DoesNotExist:
            reponse = QuestionnaireReponse(
                individu_id=individu_pk,
                question_id=question_pk
            )

        # Mettre à jour la valeur
        reponse.reponse = reponse_valeur
        reponse.save()
        return redirect("portail_questionnaires")