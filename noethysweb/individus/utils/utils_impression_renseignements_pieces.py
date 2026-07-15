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
from pillow_heif import register_heif_opener
register_heif_opener()

# =========================================================================
# FOUS-FONCTION COMPLÉMENTAIRE POUR LE FORMATAGE DES BANDEROLES DE PJ
# =========================================================================
def formater_piece_jointe(piece, individu, largeur, hauteur):
    """
    Prend un fichier justificatif physique (Image ou PDF) et applique
    un bandeau d'entête professionnel sur une nouvelle page.
    Si le fichier est corrompu, génère une page d'erreur en texte pur.
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

    if doc_name.endswith(('.jpg', '.jpeg', '.png', '.gif', '.heic')):
        try:
            try:
                img = PILImage.open(full_path)
                img = ImageOps.exif_transpose(img)
            except Exception:
                logger.warning("EXIF invalide pour piece")
                img = PILImage.open(full_path)

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
            logger.error(f"Erreur rendu image piece {piece.idpiece}: {e}")
            print(f"      /!\\ Erreur rendu image : {e}")

    elif doc_name.endswith('.pdf'):
        try:
            # DÉFINITION DE LA ZONE DE CONTRAINTE
            cadre_w = largeur - 100
            cadre_h = height = hauteur - 100
            cadre_x = (largeur - cadre_w) / 2
            cadre_y = 40
            can.setStrokeColor(colors.HexColor("#A0A0A0"))
            can.setLineWidth(1)
            can.rect(cadre_x, cadre_y, cadre_w, cadre_h, fill=0, stroke=1)
            can.showPage()
            can.save()

            header_page = PdfReader(io.BytesIO(buffer_header.getvalue())).pages[0]

            # L'ouverture du fichier est encapsulée dans le try
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

                    tx = cadre_x
                    hauteur_reduite_pdf = orig_h * ratio_scale
                    ty = (cadre_y + cadre_h) - hauteur_reduite_pdf
                    nouvelle_page.merge_translated_page(page, tx=tx, ty=ty)
                    nouvelle_page.merge_page(header_page)

            print(f"      -> PDF '{nom_type_piece}' contraint et ajusté.")
        except Exception as e:
            # En cas d'erreur de lecture (startxref, stream end...), on logue mais on ne plante plus
            logger.error(f"Erreur traitement PDF import piece {piece.idpiece}: {e}")
            print(f"      /!\\ Erreur contrainte PDF : {e}")

    # =========================================================================
    # 🌟 CORRECTION CRITIQUE : DU TEXTE PUR SUR UNE PAGE NEUVE EN CAS D'ERREUR
    # =========================================================================
    if len(writer_piece.pages) == 0:
        print(f"      [ZAP LOGIQUE] Fichier illisible. Écriture d'un pavé de texte alternatif.")

        buffer_erreur = io.BytesIO()
        can_err = canvas.Canvas(buffer_erreur, pagesize=(largeur, hauteur))

        # 1. On dessine quand même l'en-tête de base de la pièce jointe
        can_err.setFillColor(colors.HexColor("#1d3557"))
        can_err.rect(0, hauteur - 45, largeur, 45, fill=1, stroke=0)
        can_err.setFillColor(colors.white)
        can_err.setFont("Helvetica-Bold", 10)
        can_err.drawString(25, hauteur - 26, f"PIÈCE JOINTE : {nom_type_piece.upper()} (EN ERREUR)")
        can_err.setFont("Helvetica", 9)
        can_err.drawRightString(largeur - 25, hauteur - 26, f"Adhérent : {individu.Get_nom()}")

        # 2. On dessine un gros encart d'avertissement rouge au milieu de la page
        can_err.setStrokeColor(colors.HexColor("#D32F2F"))
        can_err.setFillColor(colors.HexColor("#FFEBEE"))
        can_err.rect(50, hauteur - 200, largeur - 100, 100, fill=1, stroke=1)

        # 3. Message d'erreur écrit en texte pur (pas d'appel au fichier corrompu)
        can_err.setFillColor(colors.HexColor("#C62828"))
        can_err.setFont("Helvetica-Bold", 12)
        can_err.drawString(70, hauteur - 140, f"ERREUR DOCUMENT (Pièce n°{piece.idpiece})")

        can_err.setFillColor(colors.black)
        can_err.setFont("Helvetica", 10)
        can_err.drawString(70, hauteur - 170,
                           f"Le fichier PDF initial est corrompu ou illisible sur le serveur de stockage.")
        can_err.drawString(70, hauteur - 185, f"Veuillez demander à l'adhérent de renvoyer son justificatif.")

        can_err.showPage()
        can_err.save()

        # On injecte cette page de texte alternative dans le flux d'édition
        buffer_erreur.seek(0)
        writer_piece.add_page(PdfReader(buffer_erreur).pages[0])

    # Envoi final du PDF sain
    buffer_sortie = io.BytesIO()
    writer_piece.write(buffer_sortie)
    buffer_sortie.seek(0)
    return PdfReader(buffer_sortie)

def generer_page_erreur(message, largeur=None, hauteur=None):
    from reportlab.pdfgen import canvas
    from reportlab.lib import colors
    from pypdf import PdfReader
    import io

    if largeur is None or hauteur is None:
        largeur, hauteur = A4

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(largeur, hauteur))

    c.setFillColor(colors.red)
    c.rect(0, hauteur - 50, largeur, 50, fill=1)

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(20, hauteur - 30, "ERREUR DOCUMENT")

    c.setFillColor(colors.black)
    c.setFont("Helvetica", 10)
    c.drawString(20, hauteur - 80, str(message))

    c.showPage()
    c.save()

    buffer.seek(0)
    return PdfReader(buffer).pages[0]