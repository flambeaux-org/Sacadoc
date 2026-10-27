from django.views import View
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from core.models import Activite, Structure
from django.views.generic import TemplateView
from core.views.base import CustomView
from outils.procedures.AR_ACTIVITE import Procedure as AR_ACT
from outils.procedures.AR_STRUCTURE import Procedure as AR_STR
from outils.procedures.DESARCHIVAGE import Procedure as DESAR

class ToggleArchiveView(View):
        """
        Vue pour archiver ou désarchiver une activité.
        """
        procedure_class = None  # La procédure à exécuter
        type_objet = None  # "ACTIVITE" ou "STRUCTURE"

        def get(self, request, idactivite=None, idstructure=None):
            # Récupère l'objet selon le type
            if self.type_objet == "ACTIVITE":
                objet = get_object_or_404(Activite.objects_all, idactivite=idactivite)
                variable_key = "activite"
                redirect_url = "activites_liste"
            elif self.type_objet == "STRUCTURE":
                objet = get_object_or_404(Structure.objects_all, idstructure=idstructure)
                variable_key = "structure"
                redirect_url = "structures_liste"
            else:
                messages.error(request, "Type d'objet non défini.")
                return redirect(request.headers.get("referer", "/"))

            # Exécute la procédure
            proc = self.procedure_class()
            result = proc.Executer(variables={variable_key: objet})

            # Message succès
            messages.success(request, result)

            # Redirection spécifique
            return redirect(redirect_url)


class ToggleArchiveActivite(ToggleArchiveView):
    type_objet = "ACTIVITE"
    procedure_class = AR_ACT

class ToggleDesarchive(ToggleArchiveView):
    type_objet = "ACTIVITE"
    procedure_class = DESAR

class ToggleDesarchiveStructure(ToggleArchiveView):
    type_objet = "STRUCTURE"
    procedure_class = DESAR
class ToggleArchiveStructure(ToggleArchiveView):
    procedure_class = AR_STR
    type_objet = "STRUCTURE"