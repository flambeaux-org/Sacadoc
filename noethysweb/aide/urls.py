# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django.urls import include, path
from django.contrib.auth import views as auth_views
from core.decorators import secure_ajax
from core.views import toc
from aide.views import aide


urlpatterns = [

    # Table des matières
    path('aide/', aide.Aide.as_view(menu_code="aide_toc"), name='aide_toc'),
    
    # API pour le chatbot
    path('aide/api/videos/', aide.get_videos_json, name='aide_api_videos'),
]
