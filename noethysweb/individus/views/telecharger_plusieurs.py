import zipfile
from io import BytesIO
from django.http import HttpResponse
from django.views import View
from django.shortcuts import get_object_or_404
from core.models import Piece


class Telecharger_plusieurs(View):

    def post(self, request, *args, **kwargs):
        # Récupérer les IDs des fichiers sélectionnés
        file_ids = request.POST.getlist('files')
        print(request.POST.getlist("files"))
        if not file_ids:
            return HttpResponse("Aucun fichier sélectionné", status=400)

        # Créer un objet BytesIO pour stocker le zip en mémoire
        buffer = BytesIO()

        # Créer un fichier zip en mémoire
        with zipfile.ZipFile(buffer, 'w') as zip_file:
            for file_id in file_ids:
                piece = get_object_or_404(Piece, idpiece=file_id)
                document_path = piece.document.path

                # Récupération des informations pertinentes pour le titre du document
                type_piece = piece.type_piece.nom if piece.type_piece else ""
                individu = piece.individu.prenom if piece.individu else ""
                famille = piece.individu.nom if piece.individu else ""

                # Construction du titre du document pour le fichier dans le zip
                titre_document = f"{piece.idpiece} - {type_piece} - {individu} {famille}{document_path[document_path.rfind('.'):]}" # Inclure l'extension du fichier

                # Ajouter le fichier au zip avec le nom modifié
                zip_file.write(document_path, arcname=titre_document)

        # Réinitialiser la position du buffer pour la lecture
        buffer.seek(0)

        # Créer une réponse HTTP avec le fichier zip
        response = HttpResponse(buffer, content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename=fichiers_selectionnes.zip'

        return response
