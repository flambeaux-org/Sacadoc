# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.
import os

from django.conf import settings

_version = None

def GetVersion():
    """ Recherche du numéro de version """
    global _version
    if _version is None:
        with open(os.path.join(settings.BASE_DIR, "version.txt"), "r") as file:
            _version = file.readlines()[0].strip()
    return _version

def GetVersionTuple(version=""):
    """ Renvoie un numéro de version au format tuple """
    return [int(caract) for caract in version.split(".")]
