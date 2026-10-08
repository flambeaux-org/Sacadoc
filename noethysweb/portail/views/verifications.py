from django.shortcuts import redirect, get_object_or_404
from portail.views.base import CustomView
from django.views.generic import TemplateView
from django.utils.translation import gettext as _
from django.contrib import messages
from django.http import Http404, HttpResponse
from core.models import Inscription, Rattachement, Individu, Information
from individus.utils import utils_impression_renseignements
import io, datetime
from django.http import JsonResponse


class View(CustomView, TemplateView):
    """Affiche les onglets pour tous les individus à vérifier"""
    menu_code = "portail_verifications"
    template_name = "portail/verifications_manquants.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        famille = self.request.user.famille

        # Récupérer les inscriptions nécessitant une vérification
        inscriptions = Inscription.objects.filter(
            famille=famille, besoin_certification=True, activite__actif=True,
        ).select_related("individu")

        # Préparer la liste pour le template
        inscriptions_rattachements = []
        for ins in inscriptions:
            rattachement = Rattachement.objects.filter(individu=ins.individu).first()
            buffer = io.BytesIO()
            impression = utils_impression_renseignements.Impression(
                dict_donnees={"rattachements": [rattachement.pk], "tri": "classe", "mode_condense": True}, request=self.request)
            # Vérifier les erreurs éventuelles
            if impression.erreurs:
                return JsonResponse({"erreur": impression.erreurs[0]}, status=401)

            # Récupérer le nom du fichier généré
            nom_fichier = impression.Get_nom_fichier()
            nom_fichier = "/media" + nom_fichier
            if rattachement:
                inscriptions_rattachements.append({
                    "inscription": ins,
                    "individu": ins.individu,
                    "rattachement": rattachement,
                    "nom_fichier": nom_fichier,
                    "aucune_information_medicale": not Information.objects.filter(individu=ins.individu).exists(),
                })

        context["inscriptions_rattachements"] = inscriptions_rattachements
        return context

    def post(self, request, *args, **kwargs):
        inscription_id = request.POST.get("inscription_id")
        if not inscription_id:
            messages.error(request, "Inscription non spécifiée.")
            return redirect(request.path)

        inscription = get_object_or_404(Inscription, pk=inscription_id)
        individu = get_object_or_404(Individu, pk=inscription.individu.pk)

        # Double sécurité : si aucune information médicale n'est renseignée, la famille doit attester explicitement le RAS
        if not Information.objects.filter(individu=individu).exists() and request.POST.get("confirmation_ras") != "on":
            messages.error(request, "Veuillez cocher la case attestant l'absence d'information médicale (RAS) avant de valider.")
            return redirect(request.path)

        inscription.besoin_certification = False
        inscription.save()

        rattachement = get_object_or_404(Rattachement, individu=individu)
        rattachement.certification_date = datetime.datetime.now()
        rattachement.save()

        messages.success(request, f"Vérification validée pour {inscription.individu.prenom} {inscription.individu.nom}.")
        return redirect(request.path)



