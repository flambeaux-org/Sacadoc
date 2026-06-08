# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import logging, json
logger = logging.getLogger(__name__)
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, Q, OuterRef, Subquery
from django.http import JsonResponse
from django.conf import settings
from django.core.cache import cache
from core.views.menu import GetMenuPrincipal
from core.models import Organisateur, Parametre, Utilisateur, PortailMessage, PortailRenseignement, Structure, Activite, Famille, Inscription
from core.utils import utils_parametres
from noethysweb.version import VERSION
from django.db.models import OuterRef, Subquery
from django.utils import timezone
from datetime import timedelta
from django.db.models import Max, F, Q


def Memorise_option(request):
    """ Mémorise dans la DB et le cache une option d'interface pour l'utilisateur """
    nom = request.POST.get("nom")
    valeur = json.loads(request.POST.get("valeur"))
    utils_parametres.Set(nom=nom, categorie="options_interface", utilisateur=request.user, valeur=valeur)
    cache.delete("options_interface_user%d" % request.user.pk)
    return JsonResponse({"success": True})

def Memorise_parametre(request):
    """ Mémorise un paramètre dans la DB """
    nom = request.POST.get("nom")
    categorie = request.POST.get("categorie")
    valeur = json.loads(request.POST.get("valeur"))
    utils_parametres.Set(nom=nom, categorie=categorie, utilisateur=request.user, valeur=valeur)
    return JsonResponse({"success": True})

def Memorise_tri_liste(request):
    """ Mémorise le tri d'une liste """
    colonne = request.POST.get("colonne")
    sens = request.POST.get("sens")
    nom_view = request.POST.get("view")
    nom_view = nom_view[4:nom_view.find(" object at ")]
    nom_view = nom_view.replace(".Liste", "")
    if colonne:
        utils_parametres.Set(nom=nom_view, categorie="tri_liste", utilisateur=request.user, valeur="%s;%s" % (colonne, sens))
    return JsonResponse({"success": True})

def Memorise_hidden_columns(request):
    """ Mémorise les colonnes cachées """
    colonnes = request.POST.get("colonnes")
    nom_view = request.POST.get("view")
    nom_view = nom_view[4:nom_view.find(" object at ")]
    nom_view = nom_view.replace(".Liste", "")
    utils_parametres.Set(nom=nom_view, categorie="hidden_columns", utilisateur=request.user, valeur=colonnes)
    return JsonResponse({"success": True})

def Memorise_page_length(request):
    """ Mémorise le page_length """
    page_length = request.POST.get("page_length")
    nom_view = request.POST.get("view")
    nom_view = nom_view[4:nom_view.find(" object at ")]
    nom_view = nom_view.replace(".Liste", "")
    utils_parametres.Set(nom=nom_view, categorie="page_length", utilisateur=request.user, valeur=page_length)
    return JsonResponse({"success": True})


class CustomView(LoginRequiredMixin, UserPassesTestMixin): #, PermissionRequiredMixin):
    """ Implémente les données de la page : menus..."""
    menu_code = ""
    compatible_demo = True

    # Connexion obligatoire
    login_url = 'connexion'
    redirect_field_name = 'accueil'

    def test_func(self):
        # Vérifie que l'utilisateur a une permission
        menu_code = getattr(self, "menu_code", None)
        if menu_code and menu_code != "accueil" and not menu_code.endswith("_toc"):
            if not menu_code and hasattr(self, "url_liste"):
                menu_code = self.url_liste
            if not self.request.user.has_perm("core.%s" % menu_code):
                logger.debug("Interdiction d'accéder à la page 'core.%s' : Pas de permission." % menu_code)
                return False

        # Vérifie que l'utilisateur est de type "utilisateur"
        if self.request.user.categorie != "utilisateur":
            logger.debug("Interdiction d'accéder à cette page : L'utilisateur n'est pas de type 'utilisateur'.")
            return False

        # Vérifie que cette fonction est compatible avec le mode DEMO
        if not self.compatible_demo and settings.MODE_DEMO:
            logger.debug("Interdiction d'accéder à cette page : Fonction incompatible avec le mode démo.")
            return False

        # Vérification spéciale d'une page
        if hasattr(self, "test_func_page"):
            if not self.test_func_page():
                logger.debug("Interdiction d'accéder à la page '%s' : Pas de permission pour cette donnée." % getattr(self, "menu_code", None))
                return False

        return True

    def get_context_data(self, **kwargs):
        context = super(CustomView, self).get_context_data(**kwargs)

        # Version application
        context['version_application'] = VERSION

        # Organisateur
        organisateur = cache.get('organisateur')
        if not organisateur:
            organisateur = Organisateur.objects.filter(pk=1).first()
            cache.set('organisateur', organisateur)
        context['organisateur'] = organisateur

        # Options d'interface
        key_cache = "options_interface_user%d" % self.request.user.pk
        if cache.get(key_cache, None) != None:
            context['options_interface'] = cache.get(key_cache, {})
        else:
            defaut = {
                "dark-mode": False,
                "masquer-sidebar": False,
                "text-sm": True,
                "sidebar-no-expand": True,
                "configuration_accueil": json.dumps(settings.CONFIG_ACCUEIL_DEFAUT),
            }
            parametres = utils_parametres.Get_categorie(categorie='options_interface', utilisateur=self.request.user, parametres=defaut)
            context['options_interface'] = parametres
            cache.set(key_cache, parametres)

        # Mémorise le menu principal
        menu_principal = GetMenuPrincipal(organisateur=organisateur, user=self.request.user)
        context['menu_principal'] = menu_principal

        # Si la page est un CRUD, on récupère l'URL de la liste en tant que menu_code
        if not self.menu_code and hasattr(self, "url_liste"):
            self.menu_code = self.url_liste

        # Mode démo
        context['mode_demo'] = settings.MODE_DEMO

        # Mémorise le menu actif
        menu_actif = menu_principal.Find(code=self.menu_code)
        context['menu_actif'] = menu_actif
        if menu_actif:
            context['menu_brothers'] = menu_actif.GetBrothers()
        context['afficher_menu_brothers'] = False

        # Mémorise le fil d'ariane
        if context['menu_actif'] is not None:
            context['breadcrumb'] = context['menu_actif'].GetBreadcrumb()

        # Date limite : 3 mois
        date_limite = timezone.now() - timedelta(days=90)

        # Messages non lus pour toutes les structures de l'utilisateur
        messages_non_lus = PortailMessage.objects.filter(
            structure__in=self.request.user.structures.all(),
            utilisateur__isnull=True,
            date_lecture__isnull=True
        )

        dernier_messages_non_lus_ids = (
            messages_non_lus
            .values('famille_id', 'structure_id')
            .annotate(dernier_id=Max('idmessage'))
            .values_list('dernier_id', flat=True)
        )

        # Obtenir les couples famille+structure ayant un message non lu
        couples_non_lus = messages_non_lus.values_list('famille_id', 'structure_id')

        # Dernier message par famille+structure dans les 3 derniers mois
        dernier_messages = (
            PortailMessage.objects
            .filter(
                structure__in=self.request.user.structures.all(),
                date_creation__gte=date_limite
            )
            # Exclure les couples qui ont un message non lu
            .exclude(
                Q(famille_id__in=[f for f, s in couples_non_lus]) &
                Q(structure_id__in=[s for f, s in couples_non_lus])
            )
            .values('famille_id', 'structure_id')
            .annotate(dernier_id=Max('idmessage'))
            .values_list('dernier_id', flat=True)
        )

        # Récupérer les objets complets
        context["liste_messages_lus"] = PortailMessage.objects.filter(
            idmessage__in=dernier_messages
        ).select_related('famille', 'structure').order_by('-date_creation')

        # Messages non lus
        context["liste_messages_non_lus"] = PortailMessage.objects.filter(
            idmessage__in=dernier_messages_non_lus_ids
        ).select_related('famille', 'structure').order_by('-date_creation')


        # Filtrage
        structures = self.request.user.structures.all()
        activites_autorisees = Activite.objects.filter(structure__in=structures)
        activites_ids = activites_autorisees.values_list('idactivite', flat=True)
        inscriptions = Inscription.objects.filter(activite__in=activites_autorisees)
        familles_ids = inscriptions.values_list('famille_id', flat=True).distinct()
        familles = Famille.objects.filter(idfamille__in=familles_ids)

        context["familles_liees"] = familles

        premiere_valeur_subquery = PortailRenseignement.objects.filter(
            code='inscrire_activite',
            etat='ATTENTE',
            idrenseignement=OuterRef('idrenseignement')
        ).order_by('date').values('nouvelle_valeur')[:1]

        # Obtenez les lignes de PortailRenseignement où le code est "inscrire_activite"
        portail_renseignement_inscrire_activite = PortailRenseignement.objects.filter(code='inscrire_activite')

        # Exécutez une requête pour obtenir les valeurs filtrées
        resultat = portail_renseignement_inscrire_activite.annotate(
            premiere_valeur=Subquery(premiere_valeur_subquery)
        ).values('idrenseignement', 'premiere_valeur')


        # Créer un ensemble des IDs des activités autorisées pour une recherche plus rapide
        activite_ids_autorisees = set(activites_ids)

        # Décoder les valeurs de premiere_valeur et filtrer les résultats
        resultat_filtre = set()
        for entry in resultat:
            premiere_valeur = entry.get('premiere_valeur')
            if premiere_valeur:
                # Extraire l'ID de l'activité de la nouvelle valeur
                premiere_valeur_strip = premiere_valeur.split(';')[0].strip('"')
                if premiere_valeur_strip.isdigit() and int(premiere_valeur_strip) in activite_ids_autorisees:
                    resultat_filtre.add(entry['idrenseignement'])

        # Filtrage des renseignements en attente
        renseignements_attente = PortailRenseignement.objects.filter(
            etat="ATTENTE",
            validation_auto=False,
            idrenseignement__in=resultat_filtre
        ).count()
        renseignements_attente_false = PortailRenseignement.objects.filter(etat="ATTENTE",famille__in=familles_ids,validation_auto=True).count()

        # Préparer les contextes
        context["nbre_renseignements_attente_validation"] = renseignements_attente
        context["nbre_renseignements_attente_lecture"] = renseignements_attente_false

        return context
