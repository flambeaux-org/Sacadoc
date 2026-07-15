# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import json, logging, time
logger = logging.getLogger(__name__)
from django.http import JsonResponse
from core.views.mydatatableview import MyDatatable, columns
from core.views import crud
from core.models import Rattachement, Activite, Piece
from individus.forms.edition_renseignements import Formulaire
from individus.utils import utils_impression_renseignements, utils_impression_renseignements_pieces

import json
import time
import os
import io
import datetime
from django.http import JsonResponse
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4

def Generer_pdf(request):
    time.sleep(1)

    # Récupération des options
    valeurs_form_options = json.loads(request.POST.get("form_options"))
    form = Formulaire(valeurs_form_options, request=request)
    if not form.is_valid():
        return JsonResponse({"erreur": "Veuillez compléter les paramètres"}, status=401)
    options = form.cleaned_data

    # Récupération des rattachements cochés
    rattachements = json.loads(request.POST.get("rattachements"))
    if not rattachements:
        return JsonResponse({"erreur": "Veuillez cocher au moins une ligne dans la liste"}, status=401)
    options["rattachements"] = rattachements

    # Création du PDF
    impression = utils_impression_renseignements.Impression(titre="Renseignements", dict_donnees=options, request=request)
    if impression.erreurs:
        return JsonResponse({"erreur": impression.erreurs[0]}, status=401)
    nom_fichier = impression.Get_nom_fichier()
    return JsonResponse({"nom_fichier": nom_fichier})

def Generer_pdf_pieces(request):
    # 1. Récupération et validation des options
    valeurs_form_options = json.loads(request.POST.get("form_options"))
    form = Formulaire(valeurs_form_options, request=request)
    if not form.is_valid():
        return JsonResponse({"erreur": "Veuillez compléter les paramètres"}, status=401)
    options = form.cleaned_data

    # 2. Récupération des rattachements cochés
    rattachements_ids = json.loads(request.POST.get("rattachements"))
    if not rattachements_ids:
        return JsonResponse({"erreur": "Veuillez cocher au moins une ligne dans la liste"}, status=401)

    writer_final = PdfWriter()
    largeur, height = A4

    logger.debug(f"--- DÉBUT DE L'ASSEMBLAGE SÉQUENTIEL ({len(rattachements_ids)} individus) ---")

    # 3. Boucle sur chaque rattachement sélectionné
    for idx, rattachement_id in enumerate(rattachements_ids, start=1):
        # Isolation de l'option pour un seul individu à la fois
        options_unitaire = options.copy()
        options_unitaire["rattachements"] = [int(rattachement_id)]

        # On récupère l'objet en base pour avoir le nom et les pièces
        try:
            rattachement = Rattachement.objects.select_related('individu').get(pk=rattachement_id)
            individu = rattachement.individu
        except Rattachement.DoesNotExist:
            continue

        logger.debug(f"   [{idx}/{len(rattachements_ids)}] Traitement de : {individu.Get_nom().upper()}")

        # A. Génération de la fiche unitaire avec Noethys
        try:
            impression = utils_impression_renseignements.Impression(
                titre="Renseignements",
                dict_donnees=options_unitaire,
                request=request
            )

            # Récupération du fichier unitaire écrit par Noethys
            nom_fichier_virtuel = impression.Get_nom_fichier()
            nom_nettoye = nom_fichier_virtuel.strip('/')

            # Reconstruction du chemin physique sous Windows
            chemin_pdf_unitaire = os.path.normpath(os.path.join(settings.MEDIA_ROOT, nom_nettoye))

            # Lecture et injection de la fiche dans notre compilateur global
            if os.path.exists(chemin_pdf_unitaire):
                with open(chemin_pdf_unitaire, 'rb') as f:
                    reader_unitaire = PdfReader(f)
                    for page in reader_unitaire.pages:
                        writer_final.add_page(page)

                # Optionnel : On nettoie le fichier unitaire pour ne pas encombrer le dossier temp
                try:
                    os.remove(chemin_pdf_unitaire)
                except:
                    pass
            else:
                # Si Noethys n'a pas pu écrire le fichier, on met une page d'erreur
                writer_final.add_page(utils_impression_renseignements_pieces.generer_page_erreur(
                    f"Fiche administrative indisponible pour {individu.Get_nom().upper()}", largeur, height
                ))
        except Exception as e:
            logger.exception(f"Erreur génération Noethys pour {individu.Get_nom()} : {e}")
            continue

        # B. Récupération et ajout immédiat de ses pièces jointes
        pieces = Piece.objects.select_related("type_piece").filter(individu=individu)
        for piece in pieces:
            nom_piece = piece.type_piece.nom if piece.type_piece else "Document"
            try:
                chemin_piece = piece.document.path if hasattr(piece.document, 'path') else os.path.join(
                    settings.MEDIA_ROOT, piece.document.name)
                chemin_piece = os.path.normpath(chemin_piece)

                if os.path.exists(chemin_piece):
                    # Appel de ta fonction de mise en page (bandeau gris + resize d'image)
                    reader_pj = utils_impression_renseignements_pieces.formater_piece_jointe(piece, individu, largeur,
                                                                                             height)
                    for page in reader_pj.pages:
                        writer_final.add_page(page)
                else:
                    # Ajout d'une feuille blanche si le fichier physique est introuvable
                    writer_final.add_page(utils_impression_renseignements_pieces.generer_page_erreur(
                        f"Document absent : {nom_piece.upper()} (Adhérent : {individu.Get_nom().upper()})", largeur,
                        height
                    ))
            except Exception as e:
                writer_final.add_page(utils_impression_renseignements_pieces.generer_page_erreur(
                    f"Erreur de lecture du document : {nom_piece.upper()}", largeur, height
                ))

    # 4. Sauvegarde du livret final unique via default_storage dans un répertoire propre
    buffer_final = io.BytesIO()
    writer_final.write(buffer_final)

    repertoire = "fiches_completes"
    nom_final_livret = f"{repertoire}/Recueil_Fiches_Pieces_{datetime.date.today().strftime('%Y%m%d')}_{int(time.time())}.pdf"

    if default_storage.exists(nom_final_livret):
        default_storage.delete(nom_final_livret)

    # Sauvegarde propre gérée par Django (Valide sur Local et sur Serveur de production)
    chemin_final_web = default_storage.save(nom_final_livret, ContentFile(buffer_final.getvalue()))

    logger.debug(f"[SUCCÈS] Livret global créé avec succès : {chemin_final_web}")

    # On renvoie le chemin relatif à Noethys qui saura l'ouvrir côté client
    return JsonResponse({"nom_fichier": "/" + chemin_final_web, "status": "success"})

class Page(crud.Page):
    model = Rattachement
    url_liste = "edition_renseignements"
    menu_code = "edition_renseignements"


class Liste(Page, crud.Liste):
    template_name = "individus/edition_renseignements.html"
    model = Rattachement

    def get_queryset(self):
        # Filtrer les individus ayant une inscription à une activité autorisée
        activites_autorisees = Activite.objects.filter(structure__in=self.request.user.structures.all())

        # Obtenir les rattachements liés à ces individus
        return Rattachement.objects.select_related("famille", "individu").filter(individu__inscription__activite__in=activites_autorisees).filter(self.Get_filtres("Q"))

    def get_context_data(self, **kwargs):
        context = super(Liste, self).get_context_data(**kwargs)
        context["page_titre"] = "Edition des fiches de renseignements"
        context["box_titre"] = "Edition des fiches de renseignements"
        context["box_introduction"] = "Cochez les individus souhaités, précisez si besoin les options et cliquez soit sur le bouton souhaité. Utilisez le bouton Filtrer pour affiner la liste d'individus."
        context["onglet_actif"] = "edition_renseignements"
        context["impression_introduction"] = ""
        context["impression_conclusion"] = ""
        context["active_checkbox"] = True
        context["bouton_supprimer"] = False
        context["hauteur_table"] = "400px"
        context["form_options"] = Formulaire(request=self.request)
        context["afficher_menu_brothers"] = True
        return context

    class datatable_class(MyDatatable):
        filtres = ["ipresent:individu", "fpresent:famille", "famille__nom", "individu__nom", "individu__prenom"]
        check = columns.CheckBoxSelectColumn(label="")
        individu = columns.CompoundColumn("Individu", sources=["individu__nom", "individu__prenom"])
        famille = columns.TextColumn("Famille", sources=["famille__nom"])
        rue_resid = columns.TextColumn("Rue", sources=None, processor="Get_rue_resid")
        cp_resid = columns.TextColumn("CP", sources=None, processor="Get_cp_resid")
        ville_resid = columns.TextColumn("Ville", sources=None, processor="Get_ville_resid")

        class Meta:
            structure_template = MyDatatable.structure_template
            columns = ["check", "idrattachement", "individu", "famille", "rue_resid", "cp_resid", "ville_resid"]
            ordering = ["individu__nom", "individu__prenom"]

        def Get_rue_resid(self, instance, *args, **kwargs):
            return instance.individu.rue_resid

        def Get_cp_resid(self, instance, *args, **kwargs):
            return instance.individu.cp_resid

        def Get_ville_resid(self, instance, *args, **kwargs):
            return instance.individu.ville_resid
