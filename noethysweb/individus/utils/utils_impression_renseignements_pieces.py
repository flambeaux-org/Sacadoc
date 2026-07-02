# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging
import datetime
import os
import io
from PIL import Image as PILImage, ImageOps
from pypdf import PdfWriter, PdfReader

logger = logging.getLogger(__name__)
logging.getLogger('PIL').setLevel(logging.WARNING)

from django.conf import settings
from django.db.models import Q
from django.core.cache import cache
from django.http import JsonResponse
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from reportlab.platypus import Paragraph, Table, TableStyle, PageBreak, Spacer
from reportlab.platypus.flowables import Image
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from core.models import Lien, Rattachement, ContactUrgence, Information, Assurance, Organisateur, Scolarite, Activite, \
    Inscription, Structure, Piece
from core.data.data_liens import DICT_TYPES_LIENS
from core.data import data_civilites
from core.utils import utils_dates, utils_impression, utils_questionnaires
from individus.utils import utils_vaccinations


# =========================================================================
# FOUS-FONCTION COMPLÉMENTAIRE POUR LE FORMATAGE DES BANDEROLES DE PJ
# =========================================================================
def formater_piece_jointe(piece, individu, largeur, hauteur):
    """
    Prend un fichier justificatif physique (Image ou PDF) et applique
    un bandeau d'entête professionnel sur une nouvelle page.
    """
    writer_piece = PdfWriter()
    full_path = piece.document.path
    doc_name = piece.document.name.lower()
    nom_type_piece = piece.type_piece.nom if piece.type_piece else "Document"

    buffer_header = io.BytesIO()
    can = canvas.Canvas(buffer_header, pagesize=A4)

    can.setFillColor(colors.HexColor("#1d3557"))
    can.rect(0, hauteur - 45, largeur, 45, fill=1, stroke=0)

    can.setFillColor(colors.white)
    can.setFont("Helvetica-Bold", 10)
    can.drawString(25, hauteur - 26, f"PIÈCE JOINTE : {nom_type_piece.upper()}")

    can.setFont("Helvetica", 9)
    can.drawRightString(largeur - 25, hauteur - 26, f"Adhérent : {individu.Get_nom()}")

    if doc_name.endswith(('.jpg', '.jpeg', '.png', '.gif')):
        try:
            img = PILImage.open(full_path)
            img = ImageOps.exif_transpose(img)

            img_w, img_h = img.size
            max_w, max_h = largeur - 50, hauteur - 90
            ratio = min(max_w / img_w, max_h / img_h)
            new_w, new_h = img_w * ratio, img_h * ratio

            x_pos = (largeur - new_w) / 2
            y_pos = (hauteur - 55 - new_h) / 2

            can.drawImage(full_path, x_pos, y_pos, width=new_w, height=new_h, preserveAspectRatio=True)
            can.showPage()
            can.save()

            writer_piece.add_page(PdfReader(io.BytesIO(buffer_header.getvalue())).pages[0])
            print(f"      -> Image '{nom_type_piece}' convertie et ajustée.")
        except Exception as e:
            logger.error(f"Erreur rendu image piece {piece.id}: {e}")
            print(f"      /!\\ Erreur rendu image : {e}")

    elif doc_name.endswith('.pdf'):

        try:

            # 1. DÉFINITION DE LA ZONE DE CONTRAINTE (LE CADRE)

            cadre_w = largeur - 100  # Largeur du cadre (ex: 495 px)
            cadre_h = hauteur - 100  # Hauteur du cadre (ex: 692 px)
            cadre_x = (largeur - cadre_w) / 2
            cadre_y = 40  # Marge basse sécurisée
            can.setStrokeColor(colors.HexColor("#A0A0A0"))
            can.setLineWidth(1)
            can.rect(cadre_x, cadre_y, cadre_w, cadre_h, fill=0, stroke=1)
            can.showPage();
            can.save()

            header_page = PdfReader(io.BytesIO(buffer_header.getvalue())).pages[0]

            with open(full_path, 'rb') as f:

                justif_pdf = PdfReader(f)

                for i, page in enumerate(justif_pdf.pages):
                    nouvelle_page = writer_piece.add_blank_page(width=largeur, height=hauteur)
                    orig_w = float(page.mediabox.width)
                    orig_h = float(page.mediabox.height)
                    ratio_w = cadre_w / orig_w
                    ratio_h = cadre_h / orig_h
                    ratio_scale = min(ratio_w, ratio_h)
                    page.scale_by(ratio_scale)

                    # Calcul des offsets pour centrer le PDF au milieu du cadre
                    tx = cadre_x  # Aligné pile sur le bord gauche du cadre

                    # ty configuré pour coller le haut du PDF sous le haut du cadre
                    hauteur_reduite_pdf = orig_h * ratio_scale
                    ty = (cadre_y + cadre_h) - hauteur_reduite_pdf
                    nouvelle_page.merge_translated_page(page, tx=tx, ty=ty)

                    # Application du fond (En-tête + Cadre)
                    nouvelle_page.merge_page(header_page)

            print(f"      -> PDF '{nom_type_piece}' contraint et ajusté dans son cadre ({len(justif_pdf.pages)} p.).")

        except Exception as e:

            logger.error(f"Erreur traitement PDF import piece {piece.idpiece}: {e}")

            print(f"      /!\\ Erreur contrainte PDF : {e}")

    buffer_sortie = io.BytesIO()
    writer_piece.write(buffer_sortie)
    buffer_sortie.seek(0)
    return PdfReader(buffer_sortie)


def generer_page_erreur(message):
    return PdfReader(buffer_sortie)