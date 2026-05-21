# -*- coding: utf-8 -*-
import datetime
from datetime import timedelta
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.urls import reverse_lazy
import logging
from django.http import HttpResponseForbidden

from core.views import crud
from core.views.customdatatable import CustomDatatable, Colonne
from core.models import Registre, Inscription, Pointage
from django.utils.safestring import mark_safe

logger = logging.getLogger(__name__)

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
        """ Récupère le registre via l'ID dans l'URL """
        pk = self.kwargs.get("pk")
        if pk and str(pk) != "0":
            return get_object_or_404(Registre, pk=pk)
        return None

    def get_dates(self, registre):
        """ Calcule les colonnes de dates basées sur date_seance ou l'activité """
        if not registre:
            return []

        # Cas 1 : Dates automatiques basées sur la période de l'activité
        if registre.type_date == 'ACT' and registre.activite.date_debut:
            d_deb = registre.activite.date_debut
            d_fin = registre.activite.date_fin or d_deb

            # Sécurité : max 100 jours pour éviter de saturer le navigateur
            delta = min((d_fin - d_deb).days, 100)
            return [(d_deb + timedelta(days=i)).strftime('%d/%m/%Y') for i in range(delta + 1)]

        # Cas 2 : Liste manuelle stockée dans date_seance (ex: "01/04/2024, 05/04/2024")
        if registre.date_seance:
            # Nettoyage des espaces et suppression des entrées vides
            dates = [d.strip() for d in registre.date_seance.split(',') if d.strip()]
            try:
                # Tri chronologique pour un affichage cohérent dans la table
                dates.sort(key=lambda x: datetime.datetime.strptime(x, "%d/%m/%Y"))
            except (ValueError, TypeError):
                pass
            return dates

        return []

    def Get_customdatatable(self):
        registre = self.get_registre()

        # État initial : Rien n'est sélectionné
        if not registre:
            return CustomDatatable(
                colonnes=[Colonne("info", "Statut")],
                lignes=[("Veuillez sélectionner un registre ci-dessus.",)]
            )

        # Chargement des dates (colonnes)
        dates = self.get_dates(registre)
        colonnes = [Colonne("individu", "Individu")]

        for d in dates:
            # On utilise mark_safe pour que le HTML soit interprété dans le header
            header = mark_safe(
                f'<div class="header-date">{d}<br><input type="checkbox" class="check-all-column" data-date="{d}"></div>')
            colonnes.append(Colonne(f"date_{d}", header, sortable=False))

        # Récupération des inscrits (Optimisée avec select_related)
        inscriptions = Inscription.objects.filter(
            activite=registre.activite
        ).select_related('individu').order_by('individu__nom', 'individu__prenom')

        # Récupération des pointages existants (Cache pour le rendu)
        pointages = Pointage.objects.filter(registre=registre, present=True).values_list('individu_id', 'date_presence')
        set_pointages = set((p[0], p[1].strftime('%d/%m/%Y')) for p in pointages)

        lignes = []
        for ins in inscriptions:
            ind = ins.individu
            # Première colonne : Nom Prénom
            ligne = [f"{ind.nom.upper()} {ind.prenom}"]

            # Colonnes dynamiques : Checkboxes de pointage
            for d in dates:
                checked = "checked" if (ind.pk, d) in set_pointages else ""

                # On détermine le symbole d'impression (X si coché, vide sinon)
                symbole_print = "X" if checked == "checked" else ""

                # On génère le HTML avec un span pour le design et le texte pour l'imprimante
                checkbox = mark_safe(
                    f'<div class="cell-presence-wrapper">'
                    f'<span class="print-mark">{symbole_print}</span>'
                    f'<div style="margin-top: 10px;">'
                    f'<input type="checkbox" class="pointage-check" data-individu="{ind.pk}" data-date="{d}" data-registre="{registre.pk}" {checked}>'
                    f'</div>'
                )
                ligne.append(checkbox)

            lignes.append(tuple(ligne))

        return CustomDatatable(colonnes=colonnes, lignes=lignes)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        reg = self.get_registre()

        # On récupère les registres avec le nouveau champ 'nom'
        mes_registres = Registre.objects.filter(
            structure__in=self.request.user.structures.all()
        ).select_related('activite')

        # Sélecteur : Nom du registre + (Nom de l'activité)
        context['liste_activites'] = [(0, "--- Choisir un registre ---")] + [
            (r.pk, f"{r.nom} ({r.activite.nom})") for r in mes_registres
        ]

        context['activite'] = reg.pk if reg else 0
        context['datatable'] = self.Get_customdatatable()

        # Mise à jour du titre de la box avec le nom du registre sélectionné
        context['box_titre'] = f"Pointage : {reg.nom}" if reg else "Registre de présences"

        return context


def sauvegarder_pointage(request):
    if request.method == "POST":
        try:
            id_reg = request.POST.get("id_registre")
            date_str = request.POST.get("date")
            etat = request.POST.get("etat") == "true"
            id_ind = request.POST.get("id_individu")  # Peut être "tous"

            date_obj = datetime.datetime.strptime(date_str, "%d/%m/%Y").date()
            registre = get_object_or_404(Registre, pk=id_reg)

            if not request.user.structures.filter(pk=registre.structure_id).exists():
                return HttpResponseForbidden()

            # CAS A : ON COCHE TOUTE LA COLONNE
            if id_ind == "tous":
                # On récupère tous les IDs des individus inscrits à cette activité
                ids_inscrits = Inscription.objects.filter(
                    activite=registre.activite
                ).values_list('individu_id', flat=True)

                if etat:
                    # On crée les pointages manquants (bulk_create est plus rapide)
                    for ind_id in ids_inscrits:
                        Pointage.objects.update_or_create(
                            registre=registre, individu_id=ind_id, date_presence=date_obj,
                            defaults={'present': True}
                        )
                else:
                    # On supprime tous les pointages de cette date pour ce registre
                    Pointage.objects.filter(registre=registre, date_presence=date_obj).delete()

                return JsonResponse({"status": "ok", "mode": "batch"})

            # CAS B : INDIVIDU UNIQUE (ton code actuel)
            else:
                if etat:
                    Pointage.objects.update_or_create(
                        registre=registre, individu_id=id_ind, date_presence=date_obj,
                        defaults={'present': True}
                    )
                else:
                    Pointage.objects.filter(registre=registre, individu_id=id_ind, date_presence=date_obj).delete()

                return JsonResponse({"status": "ok", "mode": "single"})

        except Exception as e:
            logger.exception("Erreur lors de la sauvegarde du pointage")
            return JsonResponse(
                {"status": "error", "message": "Une erreur interne est survenue."},
                status=400,
            )