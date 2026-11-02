# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django.db.models import Q
from core.models import QuestionnaireReponse, Activite, Inscription, Individu, Rattachement, Famille, Inscription, QuestionnaireQuestion, ModeleEmail, Mail, Destinataire
from core.views.customdatatable import CustomDatatable, Colonne
from core.views import crud, liste_questionnaires_base
from django.urls import reverse_lazy, reverse
from django.http import JsonResponse
from django.contrib import messages
import logging, json, time
logger = logging.getLogger(__name__)



class Page(crud.Page):
    model = QuestionnaireReponse
    template_name = "individus/liste_questionnaires_individus.html"
    url_liste = "questionnaires_individus_liste"
    description_liste = "Voici ci-dessous la liste des questionnaires individuels. Commencez par sélectionner une question dans la liste déroulante."
    boutons_liste = [
    ]

class Liste(Page, liste_questionnaires_base.Liste):
    categorie_question = "individu"
    filtres = ["ipresent:individu", "iscolarise:individu", "individu__nom", "individu__prenom", "reponse"]
    colonnes = [
        Colonne(code="individu__nom", label="Nom", classe="CharField", label_filtre="Nom"),
        Colonne(code="individu__prenom", label="Prénom", classe="CharField", label_filtre="Prénom"),
        Colonne(code="reponse", label="Réponse", classe="BooleanField", label_filtre="Valeur"),
    ]

    def get_context_data(self, **kwargs):
        context = super(Liste, self).get_context_data(**kwargs)
        context['page_titre'] = "Questionnaires"
        context['box_titre'] = "Liste des questionnaires individuels"
        return context

    def Get_customdatatable(self):
        lignes = []
        categorie_l = self.kwargs.get('categorie', None)
        categorie = categorie_l.split('/')[-1]
        activite_question1 = QuestionnaireQuestion.objects.get(idquestion=categorie)
        activite_question = activite_question1.activite
        if activite_question is None:
            activites_accessibles = Activite.objects.filter(structure__in=self.request.user.structures.all())
        else:
            activites_accessibles = Activite.objects.filter(idactivite=activite_question.pk)
        inscriptions_accessibles = Inscription.objects.filter(activite__in=activites_accessibles)
        if activite_question is None:
            individus_inscrits = Individu.objects.filter(idindividu__in=inscriptions_accessibles.values('individu'),statut=5)
        else:
            individus_inscrits = Individu.objects.filter(idindividu__in=inscriptions_accessibles.values('individu'))
        for reponse in QuestionnaireReponse.objects.select_related("question", "individu").filter(Q(question=self.Get_categorie(),individu__in=individus_inscrits) & self.Get_filtres("Q")):
            lignes.append([
                reponse.individu.nom,
                reponse.individu.prenom,
                self.Formate_reponse(reponse.Get_reponse_fr()),
            ])
        return CustomDatatable(colonnes=self.colonnes, lignes=lignes)#, filtres=self.Get_filtres())

def traiter_relance(request):
    """ Vue qui exécute une action lorsqu'on clique sur le bouton 'Relance' """
    categorie_l = request.POST.get('categorie') or ""
    categorie = categorie_l.split('/')[-1]
    url_redirect = reverse_lazy('questionnaires_individus_liste')  # Remplace 'some_redirect_url' par l'URL cible souhaitée

    # Aucune question sélectionnée : le dernier segment de l'URL vaut "liste" (et non un idquestion)
    if not categorie.isdigit():
        return JsonResponse({"erreur": "Veuillez d'abord sélectionner une question dans la liste déroulante"}, status=401)

    #Début envoi email
    time.sleep(1)

    # Récupération des familles
    activite_question1 = QuestionnaireQuestion.objects.get(pk=categorie)
    activite_question = activite_question1.activite
    individu_reponses = QuestionnaireReponse.objects.filter(question=categorie).exclude(reponse__isnull=True).exclude(reponse="").values_list('individu', flat=True)
    famille_reponse = Rattachement.objects.filter(individu__in=individu_reponses).values('famille')
    inscriptions_accessibles = Inscription.objects.filter(activite=activite_question)
    individus_inscrits = Individu.objects.filter(idindividu__in=inscriptions_accessibles.values('individu'))
    famille_activite = Rattachement.objects.filter(individu__in=individus_inscrits).values('famille')
    famille_relance = Famille.objects.filter(idfamille__in=famille_activite).exclude(idfamille__in=famille_reponse)

    if not famille_relance:
        return JsonResponse({"erreur": "Aucune famille inscrite à l'activité n'est à relancer"}, status=401)

    rattachements_relance = Rattachement.objects.filter(famille__in=famille_relance, individu__in=individus_inscrits).select_related('individu', 'famille')
    liste_individus_familles = [{"individu": rattachement.individu, "famille": rattachement.famille} for rattachement in rattachements_relance]

    dict_familles = {famille.pk: famille for famille in famille_relance}

    # Création du mail
    logger.debug("Création d'un nouveau mail...")
    modele_email = ModeleEmail.objects.filter(categorie="rappel_reponses_manquantes", defaut=True).first()
    mail = Mail.objects.create(
        categorie="rappel_reponses_manquantes",
        objet=modele_email.objet if modele_email else "",
        html=modele_email.html if modele_email else "",
        adresse_exp=request.user.Get_adresse_exp_defaut(),
        selection="NON_ENVOYE",
        verrouillage_destinataires=True,
        utilisateur=request.user,
    )

    # Création des destinataires et des documents joints
    logger.debug("Enregistrement des destinataires...")
    liste_anomalies = []
    for item in liste_individus_familles:
        individu = item["individu"]
        famille = item["famille"]

        valeurs_fusion = {
            "{NOM_FAMILLE}": famille.nom,
            "{INDIVIDU}": individu.prenom
        }
        if famille.mail:
            destinataire = Destinataire.objects.create(categorie="famille", famille=famille, adresse=famille.mail, valeurs=json.dumps(valeurs_fusion))
            mail.destinataires.add(destinataire)
        else:
            liste_anomalies.append(famille.nom)

    if liste_anomalies:
        messages.add_message(request, messages.ERROR, "Adresses mail manquantes : %s" % ", ".join(liste_anomalies))

    # Création de l'URL pour ouvrir l'éditeur d'emails
    logger.debug("Redirection vers l'éditeur d'emails...")
    url = reverse_lazy("editeur_emails", kwargs={'pk': mail.pk})
    return JsonResponse({"url": url})