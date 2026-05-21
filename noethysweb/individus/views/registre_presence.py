# -*- coding: utf-8 -*-
import html as html_module
import datetime
from datetime import timedelta
from django.shortcuts import get_object_or_404
from django.http import JsonResponse, HttpResponseForbidden
from django.urls import reverse_lazy
import logging

from core.views import crud
from core.views.customdatatable import CustomDatatable, Colonne
from core.models import Registre, Inscription, Pointage
from django.utils.safestring import mark_safe

logger = logging.getLogger(__name__)


def _get_dates(registre):
    """Return the ordered list of DD/MM/YYYY date strings for a registre."""
    if registre.type_date == 'ACT':
        d_deb = registre.activite.date_debut
        if not d_deb:
            return []
        d_fin = registre.activite.date_fin or d_deb
        delta = min((d_fin - d_deb).days, 100)
        return [(d_deb + timedelta(days=i)).strftime('%d/%m/%Y') for i in range(delta + 1)]

    if registre.date_seance:
        dates = [d.strip() for d in registre.date_seance.split(',') if d.strip()]
        try:
            dates.sort(key=lambda x: datetime.datetime.strptime(x, "%d/%m/%Y"))
        except (ValueError, TypeError):
            pass
        return dates

    return []


class Page(crud.Page):
    model = Registre
    url_liste = "registre_presence"
    objet_singulier = "un registre"
    objet_pluriel = "des registres"

    def get_boutons_liste(self):
        return [
            {"label": "Configuration", "classe": "btn btn-primary", "href": reverse_lazy("config_registre_liste"),
             "icone": "fa fa-cog"},
        ]


class Liste(Page, crud.CustomListe):
    template_name = "individus/grille_presence.html"

    def get_registre(self):
        pk = self.kwargs.get("pk")
        if pk and str(pk) != "0":
            # M-1: scope to user's own structures
            return get_object_or_404(
                Registre,
                pk=pk,
                structure__in=self.request.user.structures.all(),
            )
        return None

    def get_dates(self, registre):
        return _get_dates(registre)

    def Get_customdatatable(self):
        registre = self.get_registre()

        if not registre:
            return CustomDatatable(
                colonnes=[Colonne("info", "Statut")],
                lignes=[("Veuillez sélectionner un registre ci-dessus.",)]
            )

        dates = self.get_dates(registre)
        colonnes = [Colonne("individu", "Individu")]

        for d in dates:
            d_safe = html_module.escape(d)  # M-2: escape before mark_safe
            header = mark_safe(
                f'<div class="header-date">{d_safe}<br>'
                f'<input type="checkbox" class="check-all-column" data-date="{d_safe}"></div>'
            )
            colonnes.append(Colonne(f"date_{d_safe}", header, sortable=False))

        inscriptions = Inscription.objects.filter(
            activite=registre.activite
        ).select_related('individu').order_by('individu__nom', 'individu__prenom')

        # L-1: removed present=True filter — Pointage existence is the signal
        pointages = Pointage.objects.filter(registre=registre).values_list('individu_id', 'date_presence')
        set_pointages = set((p[0], p[1].strftime('%d/%m/%Y')) for p in pointages)

        lignes = []
        for ins in inscriptions:
            ind = ins.individu
            ligne = [f"{ind.nom.upper()} {ind.prenom}"]

            for d in dates:
                d_safe = html_module.escape(d)  # M-2
                checked = "checked" if (ind.pk, d) in set_pointages else ""
                symbole_print = "X" if checked == "checked" else ""

                checkbox = mark_safe(
                    f'<div class="cell-presence-wrapper">'
                    f'<span class="print-mark">{symbole_print}</span>'
                    f'<div style="margin-top: 10px;">'
                    f'<input type="checkbox" class="pointage-check"'
                    f' data-individu="{ind.pk}" data-date="{d_safe}"'
                    f' data-registre="{registre.pk}" {checked}>'
                    f'</div>'
                )
                ligne.append(checkbox)

            lignes.append(tuple(ligne))

        return CustomDatatable(colonnes=colonnes, lignes=lignes)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        reg = self.get_registre()

        mes_registres = Registre.objects.filter(
            structure__in=self.request.user.structures.all()
        ).select_related('activite')

        context['liste_activites'] = [(0, "--- Choisir un registre ---")] + [
            (r.pk, f"{r.nom} ({r.activite.nom})") for r in mes_registres
        ]

        context['activite'] = reg.pk if reg else 0
        context['datatable'] = self.Get_customdatatable()
        context['box_titre'] = f"Pointage : {reg.nom}" if reg else "Registre de présences"

        return context


def sauvegarder_pointage(request):
    if request.method != "POST":
        return JsonResponse({"status": "error"}, status=405)

    # C-1: explicit permission check (secure_ajax only validates login category)
    if not request.user.has_perm("core.registre_presence"):
        return HttpResponseForbidden()

    # L-2: validate and parse inputs before touching the DB
    try:
        id_reg = int(request.POST.get("id_registre", ""))
    except (ValueError, TypeError):
        return JsonResponse({"status": "error", "message": "Registre invalide."}, status=400)

    date_str = request.POST.get("date", "")
    try:
        date_obj = datetime.datetime.strptime(date_str, "%d/%m/%Y").date()
    except ValueError:
        return JsonResponse({"status": "error", "message": "Format de date invalide."}, status=400)

    etat = request.POST.get("etat") == "true"
    id_ind = request.POST.get("id_individu")  # "tous" ou entier en string

    registre = get_object_or_404(Registre, pk=id_reg)

    if not request.user.structures.filter(pk=registre.structure_id).exists():
        return HttpResponseForbidden()

    # H-2: reject dates outside the registre's configured date list
    if date_str not in set(_get_dates(registre)):
        return JsonResponse({"status": "error", "message": "Date hors du registre."}, status=400)

    # C-2 / M-5: fetch enrolled individuals once for both validation and symmetry
    ids_inscrits = set(
        Inscription.objects.filter(activite=registre.activite).values_list('individu_id', flat=True)
    )

    if id_ind == "tous":
        if etat:
            for ind_id in ids_inscrits:
                Pointage.objects.get_or_create(
                    registre=registre, individu_id=ind_id, date_presence=date_obj,
                )
        else:
            # M-5: only delete for currently enrolled individuals (symmetric with check-all)
            Pointage.objects.filter(
                registre=registre, date_presence=date_obj, individu_id__in=ids_inscrits
            ).delete()
        return JsonResponse({"status": "ok", "mode": "batch"})

    # Single individual — C-2: validate ownership
    try:
        ind_id = int(id_ind)
    except (ValueError, TypeError):
        return JsonResponse({"status": "error", "message": "Individu invalide."}, status=400)

    if ind_id not in ids_inscrits:
        return JsonResponse({"status": "error", "message": "Individu non inscrit à cette activité."}, status=403)

    if etat:
        Pointage.objects.get_or_create(
            registre=registre, individu_id=ind_id, date_presence=date_obj,
        )
    else:
        Pointage.objects.filter(registre=registre, individu_id=ind_id, date_presence=date_obj).delete()

    return JsonResponse({"status": "ok", "mode": "single"})
