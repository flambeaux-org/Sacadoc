# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django.contrib import messages
from django.http import JsonResponse
from django.views.generic import TemplateView
from core.views.base import CustomView
from core.utils import utils_dates
from comptabilite.forms.avances_regul import Formulaire
from core.models import ComptaOperation, Structure, ComptaVentilation, ModeReglement
from django.db import transaction
from django.db.models import Max
from django.db.models import Q

def Exporter(request):
    operation_ids = request.POST.getlist('operations[]')  # Opérations sélectionnées dans le form
    nouvelle_date_str = request.POST.get('date')
    mode_id = request.POST.get('mode_id')
    mode_obj = ModeReglement.objects.get(pk=mode_id) if mode_id else None
    nouvelle_date = utils_dates.ConvertDateTimeFRtoDateTime(nouvelle_date_str)

    if not operation_ids or not nouvelle_date:
        return JsonResponse({'success': False, 'message': "Veuillez sélectionner des opérations et une date."})

    nouvelle_date = nouvelle_date.date()

    operations = ComptaOperation.objects.filter(pk__in=operation_ids)

    # Vérification avance et compte
    avance_ids = set(op.avance_id for op in operations)
    if len(avance_ids) > 1:
        return JsonResponse({'success': False, 'message': "Les opérations concernent plusieurs personnes."})
    avance_type = avance_ids.pop()

    compte_ids = {op.compte_id for op in operations}
    if len(compte_ids) > 1:
        return JsonResponse({'success': False,'message': "Les opérations concernent plusieurs comptes bancaires."})
    compte_type = compte_ids.pop()

    # Récupérer l'opération de régularisation existante, si elle existe
    existing_regul = ComptaOperation.objects.filter(
        regul_avance=True,
        avance_id=avance_type,
        compte_id=compte_type
    ).first()

    with transaction.atomic():
        if existing_regul:
            # ID de régularisation à réutiliser
            regul_id = existing_regul.remb_avance

            # Récupérer toutes les opérations actuellement liées à cette régularisation
            anciennes_ops = ComptaOperation.objects.filter(remb_avance=regul_id, regul_avance=False)

            # Déconnecter celles qui ne sont plus sélectionnées
            ops_to_remove = anciennes_ops.exclude(pk__in=operation_ids)
            ops_to_remove.update(remb_avance=0)

            # Les nouvelles opérations sélectionnées prennent le même ID
            operations.update(remb_avance=regul_id)

            # Mettre à jour l'opération de régularisation
            montant_total = 0
            for op in operations:
                montant_total += op.montant if op.type == "debit" else -op.montant
            inverse_type = "debit" if montant_total > 0 else "credit"
            montant_total_regul = abs(montant_total)

            existing_regul.montant = montant_total_regul
            existing_regul.type = inverse_type
            existing_regul.date = nouvelle_date
            existing_regul.mode = mode_obj
            existing_regul.save()
        else:
            # Pas de régularisation existante → créer une nouvelle
            dernier_id = ComptaOperation.objects.aggregate(Max('remb_avance'))['remb_avance__max'] or 0
            regul_id = dernier_id + 1

            # Assigner ID aux opérations sélectionnées
            operations.update(remb_avance=regul_id)

            # Calcul du montant total
            montant_total = 0
            for op in operations:
                montant_total += op.montant if op.type == "debit" else -op.montant
            inverse_type = "debit" if montant_total > 0 else "credit"
            montant_total_regul = abs(montant_total)

            # Créer l'opération de régularisation
            ComptaOperation.objects.create(
                avance_id=avance_type,
                compte_id=compte_type,
                type=inverse_type,
                montant=montant_total_regul,
                libelle="Opé de régularisation d'avances",
                date=nouvelle_date,
                mode=mode_obj,
                regul_avance=True,
                remb_avance=regul_id
            )

    count = operations.count()
    message = f"{count} opération régularisée." if count == 1 else f"{count} opérations régularisées."
    return JsonResponse({'success': True, 'message': message})




class View(CustomView, TemplateView):
    menu_code = "avances_regul"
    template_name = "comptabilite/avances_regul.html"

    def get_context_data(self, **kwargs):
        context = super(View, self).get_context_data(**kwargs)
        context['page_titre'] = "Régulariser des avances"
        context['box_titre'] = ""
        context['box_introduction'] = "Renseignez les paramètres et cliquez sur le bouton Valider."
        if "form" not in kwargs:
            context['form'] = Formulaire(request=self.request)
        return context


class Modifier(CustomView, TemplateView):
    form_class = Formulaire
    template_name = "comptabilite/avances_regul.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_titre'] = "Modifier une régularisation d'avance"
        context['box_titre'] = ""
        context['box_introduction'] = "Modifiez les informations de la régularisation ci-dessous."

        pk = self.kwargs.get("pk")
        initial_data = {}

        if pk:
            try:
                # Récupère l'opération de régularisation
                regul_op = ComptaOperation.objects.get(idoperation=pk, regul_avance=True)

                # Récupérer toutes les opérations liées par le même remb_avance
                linked_ops = ComptaOperation.objects.filter(
                    avance=regul_op.avance,
                    remb_avance=regul_op.remb_avance
                ).exclude(pk=regul_op.pk)

                linked_ops_ids = list(linked_ops.values_list('pk', flat=True))

                # Étendre le queryset pour inclure ces opérations
                qs = ComptaOperation.objects.filter(
                    compte__structure__in=self.request.user.structures.all(),
                    avance__isnull=False
                ).exclude(pk=regul_op.pk)  # exclut l'opération de régularisation elle-même

                qs = qs | ComptaOperation.objects.filter(pk__in=linked_ops_ids)

                # Crée le formulaire prérempli **avec le queryset mis à jour**
                context['form'] = self.form_class(
                    request=self.request,
                    initial={
                        "date": regul_op.date,
                        "mode_id": regul_op.mode.pk if regul_op.mode else None,
                        "operations": linked_ops_ids,
                    }
                )
                context['form'].fields['operations'].queryset = qs.distinct()

            except ComptaOperation.DoesNotExist:
                context['form'] = self.form_class(request=self.request)

        else:
            context['form'] = self.form_class(request=self.request)

        return context

from django.shortcuts import get_object_or_404, redirect

class SupprimerRegul(CustomView, TemplateView):
    template_name = "comptabilite/avances_regul_supprimer.html"  # template simple avec bouton de confirmation

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        pk = self.kwargs.get("pk")
        print(pk)
        try:
            regul_op = ComptaOperation.objects.get(idoperation=pk, regul_avance=True)
            print(regul_op)
            context['regul_op'] = regul_op  # objet ComptaOperation, utiliser directement dans le template
            context['page_titre'] = "Supprimer une régularisation d'avance"
            context['box_titre'] = "Confirmation de suppression"
            context['box_introduction'] = f"Voulez-vous vraiment supprimer la régularisation '{regul_op.libelle}' ?"
        except ComptaOperation.DoesNotExist:
            context['regul_op'] = None
            context['box_introduction'] = "Cette régularisation n'existe pas."
        return context

    def post(self, request, *args, **kwargs):
        pk = self.kwargs.get("pk")

        try:
            with transaction.atomic():
                regul_op = ComptaOperation.objects.get(idoperation=pk, regul_avance=True)
                regul_id = regul_op.remb_avance

                # Détacher toutes les opérations liées
                ComptaOperation.objects.filter(remb_avance=regul_id, regul_avance=False).update(remb_avance=0)

                # Supprimer la régularisation
                regul_op.delete()

            # Après suppression → redirection
            return redirect("operations_tresorerie_liste")

        except ComptaOperation.DoesNotExist:
            messages.error(request, "La régularisation n'existe pas.")
            return redirect("operations_tresorerie_liste")

        except Exception as e:
            messages.error(request, f"Erreur : {str(e)}")
            return redirect("operations_tresorerie_liste")