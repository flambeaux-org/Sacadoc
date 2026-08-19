# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import datetime
from django import forms
from django.forms import ModelForm
from django.db.models import Q
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Hidden, Div, HTML, Fieldset
from crispy_forms.bootstrap import Field
from core.forms.base import FormulaireBase
from core.utils.utils_commandes import Commandes
from core.models import Inscription, PortailRenseignement, Individu, Activite, Consommation, QuestionnaireQuestion, QuestionnaireReponse, Tarif, CategorieTarif, Prestation, TarifLigne, AdresseMail, Utilisateur, Ventilation
from core.widgets import DatePickerWidget
from core.forms.select2 import Select2Widget
from core.widgets import Select_many_avec_plus
from parametrage.forms import questionnaires
from django.utils import timezone
from django.core.mail import send_mail
from django.utils.html import strip_tags
from core.utils import utils_portail
from portail.utils import utils_secquest
from django.core import mail as djangomail
from django.core.mail import EmailMultiAlternatives
import logging
logger = logging.getLogger(__name__)


class Formulaire(FormulaireBase, ModelForm):
    activite = forms.ModelChoiceField(label="Activité", widget=Select2Widget(), queryset=Activite.objects.none(), required=True)
    date_debut = forms.DateField(label="Date d'inscription", required=True, widget=DatePickerWidget())
    date_fin = forms.DateField(label="Date de fin", required=False, widget=DatePickerWidget(), help_text="Laissez vide la date de fin si vous ne connaissez pas la durée de l'inscription.")
    action_conso = forms.ChoiceField(label="Action", required=False, choices=[
        (None, "------"),
        ("MODIFIER_TOUT", "Modifier toutes les consommations existantes"),
        ("MODIFIER_AUJOURDHUI", "Modifier les consommations existantes à partir d'aujourd'hui"),
        ("MODIFIER_DATE", "Modifier les consommations existantes à partir d'une date donnée"),
        ("MODIFIER_RIEN", "Ne pas modifier les consommations existantes"),
    ])
    date_modification = forms.DateField(label="Date", required=False, widget=DatePickerWidget(), help_text="Renseignez la date de début d'application de la modification.")
    tarifs = forms.ModelMultipleChoiceField(label="Tarifs", widget=Select_many_avec_plus({"afficher_bouton_ajouter": False, "url_ajax": "ajax_ajouter_maladie", "textes": {"champ": "Nom de la maladie", "ajouter": "Ajouter une maladie"}}), queryset=Tarif.objects.all(), required=True, help_text="Cliquez sur le champ ci-dessus.")
    class Meta:
        model = Inscription
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        idindividu = kwargs.pop("idindividu", None)
        idfamille = kwargs.pop("idfamille", None)
        idactivite = kwargs.pop("idactivite", None)
        idcategorie_tarif = kwargs.pop("idcategorie_tarif", None)
        idgroupe = kwargs.pop("idgroupe", None)
        self.idtarifs = kwargs.pop("idtarifs", None)
        self.iddemande = kwargs.pop("iddemande", None)
        super(Formulaire, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = 'individu_inscriptions_form'
        self.helper.form_method = 'post'
        self.helper.form_class = 'form-horizontal'
        self.helper.label_class = 'col-md-2'
        self.helper.field_class = 'col-md-10'
        self.request = kwargs.pop('request', None)

        # Définit l'individu associé
        if hasattr(self.instance, "individu") == False:
            individu = Individu.objects.get(pk=idindividu)
        else:
            individu = self.instance.individu

        # Liste les activités visibles (permet la modif si pas lié à structure)
        self.fields['activite'].queryset = Activite.objects.filter(visible=1, structure__in=self.request.user.structures.all()).order_by("nom")

        # Si c'est un ajout avec présélection de l'activité et du groupe
        # (utilisé surtout pour les demandes d'inscription depuis le portail)
        if idactivite:
            self.fields["activite"].initial = idactivite
        if idgroupe:
            self.fields["groupe"].initial = idgroupe

        # Sélection automatique de la catégorie de tarif en fonction de l'activité sélectionnée
        if idactivite:
            activite = Activite.objects.get(pk=idactivite)
            categories_tarif = CategorieTarif.objects.filter(activite=activite)
            if categories_tarif.exists():
                self.fields["categorie_tarif"].queryset = categories_tarif
                premiere_categorie = categories_tarif.order_by('idcategorie_tarif').first()
                self.fields["categorie_tarif"].initial = premiere_categorie.pk
           # print(premiere_categorie)

        idtarifs = self.idtarifs

        if idtarifs:
            # Convertir les identifiants de tarifs en entiers
            idtarifs_int = [int(id_tarif) for id_tarif in idtarifs.split(',')]

            # Récupérer les descriptions correspondantes depuis la base de données
            descriptions_tarifs = Tarif.objects.filter(pk__in=idtarifs_int).values_list('description', flat=True)

            # Récupérer les objets Tarif correspondants aux descriptions
            tarifs_objects = Tarif.objects.filter(description__in=descriptions_tarifs)

            # Pré-sélectionner les options dans le champ "tarifs" avec les objets Tarif récupérés
            self.fields["tarifs"].initial = tarifs_objects
           # print(descriptions_tarifs)

        # Si modification
        nbre_conso = 0
        if self.instance.idinscription != None:
            self.fields['individu'].disabled = True
            self.fields['famille'].disabled = True

            # Recherche si consommations existantes
            nbre_conso = Consommation.objects.filter(inscription=self.instance).count()
            if nbre_conso:
                self.fields["action_conso"].required = True
                self.fields["action_conso"].help_text = "Il existe déjà %d consommations associées à cette inscription. Que souhaitez-vous faire de ces consommations ?" % nbre_conso

        # Période de validité
        if not self.instance.pk:
            self.fields['date_debut'].initial = datetime.date.today()

        # Affichage
        self.helper.layout = Layout(
            Commandes(annuler_url="{{ view.get_success_url }}", ajouter=False),
            Hidden('individu', value=individu.idindividu) if idindividu else Field("individu"),
            Hidden('famille', value=idfamille) if idfamille else Field("famille"),
            Fieldset("Période de validité",
                Field("date_debut"),
            ),
            Fieldset("Activité",
                Field('activite'),
                Field('groupe'),
                Field('tarifs'),
            ),
            Fieldset("Paramètres",
                Field("statut"),
                Field("internet_reservations"),
            ),
            HTML(EXTRA_SCRIPT),
        )

        # Affichage du champ consommations existantes
        if nbre_conso:
            self.helper.layout.insert(3,
                Fieldset("Consommations associées",
                    Div(
                        Field("action_conso"),
                        Field("date_modification"),
                        css_class="alert alert-warning"
                    ),
                ),
            )

        # Création des champs des questionnaires
        condition_structure = Q(structure__in=self.request.user.structures.all()) | Q(structure__isnull=True)
        questions = QuestionnaireQuestion.objects.filter(condition_structure, categorie="inscription", visible=True).order_by("ordre")
        if questions:
            liste_fields = []
            for question in questions:
                nom_controle, ctrl = questionnaires.Get_controle(question)
                if ctrl:
                    self.fields[nom_controle] = ctrl
                    liste_fields.append(Field(nom_controle))
            self.helper.layout.append(Fieldset("Questionnaire", *liste_fields))

            # Importation des réponses
            for reponse in QuestionnaireReponse.objects.filter(donnee=self.instance.pk, question__categorie="inscription"):
                key = "question_%d" % reponse.question_id
                if key in self.fields:
                    self.fields[key].initial = reponse.Get_reponse_for_ctrl()

    def clean(self):
        if self.cleaned_data["date_fin"] and self.cleaned_data["date_debut"] > self.cleaned_data["date_fin"]:
            self.add_error('date_fin', "La date de fin doit être supérieure à la date de début")
            return

        if self.cleaned_data["activite"].date_fin and self.cleaned_data["date_debut"] > self.cleaned_data["activite"].date_fin:
            self.add_error('date_debut', "La date de début doit être inférieure à la date de fin de l'activité")
            return

        # Questionnaires
        for key, valeur in self.cleaned_data.items():
            if key.startswith("question_"):
                if isinstance(valeur, list):
                    self.cleaned_data[key] = ";".join(valeur)

        return self.cleaned_data

    def save(self):
        is_new_instance = self.instance.pk is None
        ancienne_activite = None
        if not is_new_instance:
            # Récupérer l'activité avant modification depuis la base
            ancienne_activite = Inscription.objects.get(pk=self.instance.pk).activite

        instance = super(Formulaire, self).save()

        # Si l'activité a changé, supprimer les prestations associées à l'ancienne activité
        # Sécurité : ne jamais supprimer une prestation déjà ventilée (règlement associé).
        if ancienne_activite and ancienne_activite != instance.activite:
            prestations_ancienne_activite = Prestation.objects.filter(
                individu=instance.individu,
                famille=instance.famille,
                activite=ancienne_activite,
            )
            idprestations_ventilees = set(Ventilation.objects.filter(
                prestation__in=prestations_ancienne_activite
            ).values_list("prestation_id", flat=True))
            if idprestations_ventilees:
                logger.warning("Prestations protégées car déjà ventilées, suppression annulée pour : %s" % idprestations_ventilees)
            prestations_ancienne_activite.exclude(pk__in=idprestations_ventilees).delete()

        # Enregistrement des réponses du questionnaire
        for key, valeur in self.cleaned_data.items():
            if key.startswith("question_"):
                QuestionnaireReponse.objects.update_or_create(donnee=instance.pk, question_id=int(key.split("_")[1]),
                                                              defaults={'reponse': valeur})
        premiere_categorie_id = self.fields["categorie_tarif"].initial
        if not premiere_categorie_id:
            premiere_categorie = CategorieTarif.objects.filter(activite=instance.activite).order_by('idcategorie_tarif').first()
            if premiere_categorie:
                premiere_categorie_id = premiere_categorie.pk
            else:
                raise ValueError("Aucune catégorie de tarif trouvée pour l'activité sélectionnée.")
        #print(premiere_categorie_id)
        premiere_categorie = CategorieTarif.objects.get(pk=premiere_categorie_id)  # Récupérer l'objet CategorieTarif correspondant à partir de l'identifiant
        #print(premiere_categorie)
        tarifs_selectionnes = self.cleaned_data.get('tarifs', None)
        #print(tarifs_selectionnes)
        idtarifs_str = ','.join(str(tarif.idtarif) for tarif in tarifs_selectionnes)

        instance.categorie_tarif = premiere_categorie  # Assigner la première catégorie de tarif à l'instance d'inscription
        instance.save()  # Enregistrer l'instance mise à jour
        # Récupérer les identifiants des tarifs depuis l'URL
        if self.request.resolver_match.url_name == 'individu_inscriptions_ajouter':
            idtarifs = self.idtarifs
        elif self.request.resolver_match.url_name == 'individu_inscriptions_modifier':
            idtarifs = idtarifs_str
        else:
            idtarifs = None

        if ',' in idtarifs_str:
            idtarifs_int = [int(id_tarif) for id_tarif in idtarifs_str.split(',')]
        else:
            idtarifs_int = [int(idtarifs_str)]

        # Récupérer les objets Tarif correspondants
        tarifs_objects = Tarif.objects.filter(pk__in=idtarifs_int)

        # Récupérer les descriptions correspondantes depuis la base de données
        descriptions_tarifs = Tarif.objects.filter(pk__in=idtarifs_int).values_list('description', flat=True)

        # Récupérer les objets Tarif correspondants aux descriptions
        tarifs_objects = Tarif.objects.filter(description__in=descriptions_tarifs)
        tarifs_selectionnes = tarifs_objects.filter(pk__in=idtarifs_int)

        # Obtenir les IDs de prestations déjà enregistrées
        tarifs_prestations_existants = Prestation.objects.filter(
            individu=instance.individu,
            famille=instance.famille,
            activite=instance.activite
        ).values_list('tarif_id', flat=True)

        ids_tarifs_selectionnes = [tarif.idtarif for tarif in tarifs_selectionnes]

        #suppression prestas en trop
        # Sécurité : une prestation déjà réglée (ventilation présente) ne doit jamais être supprimée,
        # même si son tarif ne fait plus partie de la sélection, sous peine de perdre le lien règlement <-> prestation.
        prestations_a_supprimer = Prestation.objects.filter(
            individu=instance.individu,
            famille=instance.famille,
            activite=instance.activite
        ).exclude(tarif__in=ids_tarifs_selectionnes)
        idprestations_ventilees = set(Ventilation.objects.filter(
            prestation__in=prestations_a_supprimer
        ).values_list("prestation_id", flat=True))
        if idprestations_ventilees:
            logger.warning("Prestations protégées car déjà ventilées, suppression annulée pour : %s" % idprestations_ventilees)
        prestations_a_supprimer.exclude(pk__in=idprestations_ventilees).delete()

        #Validation de la demande portail
        if self.iddemande:
            demande = PortailRenseignement.objects.get(idrenseignement=self.iddemande)
            if demande:
                    demande.traitement_date = datetime.datetime.now()
                    demande.traitement_utilisateur = self.request.user
                    demande.etat = "VALIDE"
                    demande.save()
                    logger.debug("Demande portail validée.")

            # Créer une prestation pour chaque tarif
        for tarif in tarifs_selectionnes:
            if tarif.idtarif not in tarifs_prestations_existants:
                tarif_ligne = TarifLigne.objects.get(tarif_id=tarif.pk)
                montant_unique = tarif_ligne.montant_unique
                Prestation.objects.create(
                    date=timezone.now().date(),
                    categorie="consommation",
                    label=tarif.description,
                    forfait=1,
                    montant_initial=montant_unique,
                    montant=montant_unique,
                    quantite=1,
                    tva=0,
                    date_valeur=timezone.now().date(),
                    activite=instance.activite,
                    categorie_tarif=instance.categorie_tarif,
                    famille=instance.famille,
                    individu=instance.individu,
                    tarif=tarif
                )
        if is_new_instance:
            self.envoyer_email_confirmation(instance)
        return instance

    def envoyer_email_confirmation(self, inscription):
        # Importation de l'adresse d'expédition d'emails
        print("demarrage email")
        idadresse_exp = utils_portail.Get_parametre(code="connexion_adresse_exp")
        adresse_exp = None
        if idadresse_exp:
            adresse_exp = AdresseMail.objects.get(pk=idadresse_exp, actif=True)
        if not adresse_exp:
            logger.debug("Erreur : Pas d'adresse d'expédition paramétrée pour l'envoi du mail.")
            return _("L'envoi de l'email a échoué. Merci de signaler cet incident à l'organisateur.")

        # Backend CONSOLE (Par défaut)
        backend = 'django.core.mail.backends.console.EmailBackend'
        backend_kwargs = {}

        # Backend SMTP
        if adresse_exp.moteur == "smtp":
            backend = 'django.core.mail.backends.smtp.EmailBackend'
            backend_kwargs = {"host": adresse_exp.hote, "port": adresse_exp.port, "username": adresse_exp.utilisateur,
                              "password": adresse_exp.motdepasse, "use_tls": adresse_exp.use_tls}

        # Backend MAILJET
        if adresse_exp.moteur == "mailjet":
            backend = 'anymail.backends.mailjet.EmailBackend'
            backend_kwargs = {"api_key": adresse_exp.Get_parametre("api_key"), "secret_key": adresse_exp.Get_parametre("api_secret"), }

        # Backend BREVO
        if adresse_exp.moteur == "brevo":
            backend = 'anymail.backends.sendinblue.EmailBackend'
            backend_kwargs = {"api_key": adresse_exp.Get_parametre("api_key"), }

        # Création de la connexion
        connection = djangomail.get_connection(backend=backend, fail_silently=False, **backend_kwargs)
        try:
            connection.open()
        except Exception as err:
            logger.debug("Erreur : Connexion impossible au serveur de messagerie : %s." % err)
            return "Connexion impossible au serveur de messagerie : %s" % err

        # Création du message
        objet = "Confirmation d'inscription"
        body = f"""
Bonjour,
        
La demande d'inscription de {inscription.individu.prenom} à l'activité {inscription.activite.nom} vient d'être validée par le directeur !
Vous pouvez dès a présent vous rendre sur Sacadoc pour compléter le dossier d'inscription et accéder à toutes les informations concernant l'activité. -> https://sacadoc.flambeaux.org
        
Cordialement,
L'équipe de Sacadoc
        """

        message = EmailMultiAlternatives(subject=objet, body=body, from_email=adresse_exp.adresse, to=[inscription.famille.mail], connection=connection)

        # Envoie le mail
        try:
            resultat = message.send()
        except Exception as err:
            logger.debug("Erreur : Envoi du mail de reset impossible : %s." % err)
            resultat = err

        if resultat == 1:
            logger.debug("Email de confirmation envoyé.")
            return ("L'émail de confirmation a été envoyé à la famille")
        if resultat == 0:
            logger.debug("Email de confirmation non envoyé.")
            return ("L'envoi de l'email a échoué. Merci de signaler cet incident à l'organisateur.")

        connection.close()

    def creer_prestation(idactivite, premier_categorie_pk, idfamille, idindividu, idtarif):
        # Récupérer le tarif et la catégorie de tarif
        tarif = Tarif.objects.get(pk=idtarif)
        print(premier_categorie_pk)
        premier_categorie = CategorieTarif.objects.get(pk=premier_categorie_pk)  # Récupérer l'objet CategorieTarif

        # Créer la prestation
        prestation = Prestation.objects.create(
            categorie="consommation",
            label=tarif.description,
            montant_initial=tarif.montant_unique,
            montant=tarif.montant_unique,
            quantite=1,
            tva=0,
            date_valeur=timezone.now().date(),
            activite_id=idactivite,
            categorie_tarif_id=premier_categorie.pk,
            famille_id=idfamille,
            individu_id=idindividu,
            tarif_id=idtarif
        )
        return prestation

EXTRA_SCRIPT = """
<script>
// Actualise la liste des groupes et des tarifs en fonction de l'activité sélectionnée
function On_change_activite() {
    var idactivite = $("#id_activite").val();
    var idgroupe = $("#id_groupe").val();
    var idtarifs = $("#id_tarifs").val();

    // Requête AJAX pour mettre à jour les groupes
    $.ajax({ 
        type: "POST",
        url: "{% url 'ajax_get_groupes' %}",
        data: {'idactivite': idactivite},
        success: function (data) { 
            $("#id_groupe").html(data); 
            $("#id_groupe").val(idgroupe);
            if (data == '') {
                $("#div_id_groupe").hide()
            } else {
                $("#div_id_groupe").show()
            }
            if ($("#id_groupe").children('option').length === 2) {
                $("#id_groupe").val($("#id_groupe option:eq(1)").val());
            };
        }
    });

    // Requête AJAX pour mettre à jour les tarifs
    $.ajax({ 
        type: "POST",
        url: "{% url 'ajax_get_tarifs' %}",
        data: {'idactivite': idactivite},
        success: function (data) { 
            $("#id_tarifs").html(data); 
            $("#id_tarifs").val(idtarifs);
            if (data == '') {
                $("#div_id_tarifs").hide()
            } else {
                $("#div_id_tarifs").show()
            }
            if ($("#id_tarifs").children('option').length == 2) {
                $("#id_tarifs").val($("#id_tarifs option:eq(1)").val());
            };
        }
    });
};            
$(document).ready(function() {
    $('#id_activite').change(On_change_activite);
    On_change_activite(); // Appel initial pour mettre à jour les champs au chargement de la page
});

// Affichage de la date de modification en fonction de l'action choisie
function On_change_action() {
    $('#div_id_date_modification').hide();
    if ($("#id_action_conso").val() == 'MODIFIER_DATE') {
        $('#div_id_date_modification').show();
    };
}
$(document).ready(function() {
    $('#id_action_conso').on('change', On_change_action);
    On_change_action(); // Appel initial pour afficher ou masquer la date de modification
});
</script>
"""
