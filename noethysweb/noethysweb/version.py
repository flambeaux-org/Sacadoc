# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

VERSION = "0.0.0"


def GetVersionTuple(version=""):
    """ Renvoie un numéro de version au format tuple """
    return [int(caract) for caract in version.split(".")]
