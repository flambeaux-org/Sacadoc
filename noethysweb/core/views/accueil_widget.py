# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging
logger = logging.getLogger(__name__)
from core.utils import utils_acces_rapides


class Widget:
    code = None
    label = None

    def __init__(self, request=None, context=None):
        self.request = request
        self.context = context or {}

    def init_context_data(self):
        pass


class WidgetAccesRapides(Widget):
    """ Widget d'accès rapides : les boutons sont définis dans core/utils/utils_acces_rapides.py """

    def init_context_data(self):
        user = self.request.user if self.request else None
        self.context[self.code] = utils_acces_rapides.Get_groupe(code=self.code, user=user)
