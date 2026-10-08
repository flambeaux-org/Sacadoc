# -*- coding: utf-8 -*-
import mimetypes
import os

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect
from django.views import View

from core.models import (
    Activite, Assurance, ComptaOperation, Information, Inscription,
    Piece, Photo, PortailDocument, Quotient, Rattachement,
)


class BaseDocumentView(View):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("portail_connexion")
        return super().dispatch(request, *args, **kwargs)

    def get_object(self, pk):
        raise NotImplementedError

    def check_permission(self, user, obj):
        raise NotImplementedError

    def get_file_field(self, obj):
        return obj.document

    def get(self, request, pk):
        obj = self.get_object(pk)
        if not self.check_permission(request.user, obj):
            raise PermissionDenied
        field = self.get_file_field(obj)
        if not field:
            raise Http404
        path = os.path.join(settings.MEDIA_ROOT, field.name)
        if not os.path.exists(path):
            raise Http404
        content_type, _ = mimetypes.guess_type(path)
        response = FileResponse(
            open(path, "rb"),
            content_type=content_type or "application/octet-stream",
        )
        response["Content-Disposition"] = f'inline; filename="{os.path.basename(field.name)}"'
        return response

    def _accessible_activites(self, user):
        return Activite.objects.filter(structure__in=user.structures.all())

    def _famille_accessible(self, famille, user):
        return Inscription.objects.filter(
            famille=famille,
            activite__in=self._accessible_activites(user),
        ).exists()

    def _individu_accessible(self, individu, user):
        famille_ids = Rattachement.objects.filter(individu=individu).values_list("famille_id", flat=True)
        return Inscription.objects.filter(
            famille_id__in=famille_ids,
            activite__in=self._accessible_activites(user),
        ).exists()


class PieceDocumentView(BaseDocumentView):
    def get_object(self, pk):
        return get_object_or_404(Piece.objects.select_related("famille", "individu"), pk=pk)

    def check_permission(self, user, obj):
        if user.categorie == "utilisateur":
            if obj.famille:
                return self._famille_accessible(obj.famille, user)
            if obj.individu:
                return self._individu_accessible(obj.individu, user)
            return False
        if user.categorie == "famille":
            famille = getattr(user, "famille", None)
            if not famille:
                return False
            if obj.famille == famille:
                return True
            if obj.individu:
                return Rattachement.objects.filter(individu=obj.individu, famille=famille).exists()
            return False
        return False


class QuotientDocumentView(BaseDocumentView):
    def get_object(self, pk):
        return get_object_or_404(Quotient.objects.select_related("famille"), pk=pk)

    def check_permission(self, user, obj):
        if user.categorie == "utilisateur":
            return self._famille_accessible(obj.famille, user)
        if user.categorie == "famille":
            famille = getattr(user, "famille", None)
            return famille is not None and obj.famille == famille
        return False


class AssuranceDocumentView(BaseDocumentView):
    def get_object(self, pk):
        return get_object_or_404(Assurance.objects.select_related("individu", "famille"), pk=pk)

    def check_permission(self, user, obj):
        if user.categorie == "utilisateur":
            return self._individu_accessible(obj.individu, user)
        if user.categorie == "famille":
            famille = getattr(user, "famille", None)
            return famille is not None and obj.famille == famille
        return False


class InformationDocumentView(BaseDocumentView):
    def get_object(self, pk):
        return get_object_or_404(Information.objects.select_related("individu"), pk=pk)

    def check_permission(self, user, obj):
        if user.categorie == "utilisateur":
            return self._individu_accessible(obj.individu, user)
        return False


class ComptaOperationDocumentView(BaseDocumentView):
    def get_object(self, pk):
        return get_object_or_404(ComptaOperation.objects.select_related("compte__structure"), pk=pk)

    def check_permission(self, user, obj):
        if user.categorie == "utilisateur":
            return obj.compte.structure in user.structures.all()
        return False


class PortailDocumentView(BaseDocumentView):
    def get_object(self, pk):
        return get_object_or_404(PortailDocument.objects.prefetch_related("activites"), pk=pk)

    def check_permission(self, user, obj):
        if user.categorie == "utilisateur":
            doc_structures = set(obj.activites.values_list("structure_id", flat=True))
            if obj.structure_id:
                doc_structures.add(obj.structure_id)
            user_structure_ids = set(user.structures.values_list("pk", flat=True))
            return bool(doc_structures & user_structure_ids) or not doc_structures
        if user.categorie == "famille":
            famille = getattr(user, "famille", None)
            if not famille:
                return False
            famille_activite_ids = set(
                Inscription.objects.filter(famille=famille).values_list("activite_id", flat=True)
            )
            doc_activite_ids = set(obj.activites.values_list("pk", flat=True))
            return bool(famille_activite_ids & doc_activite_ids)
        return False


class PhotoDocumentView(BaseDocumentView):
    def get_object(self, pk):
        return get_object_or_404(Photo.objects.select_related("album__structure"), pk=pk)

    def get_file_field(self, obj):
        return obj.fichier

    def check_permission(self, user, obj):
        if user.categorie == "utilisateur":
            return obj.album.structure in user.structures.all() if obj.album.structure else True
        if user.categorie == "famille":
            famille = getattr(user, "famille", None)
            if not famille or not obj.album.structure:
                return False
            return Inscription.objects.filter(
                famille=famille,
                activite__structure=obj.album.structure,
            ).exists()
        return False
