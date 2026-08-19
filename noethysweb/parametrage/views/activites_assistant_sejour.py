# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django import forms
import datetime, json
from dateutil import rrule
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Fieldset
from core.widgets import DatePickerWidget, DateTimePickerWidget
from core.models import Unite, UniteRemplissage, Ouverture, Remplissage, NomTarif, Tarif, TarifLigne, Structure, Activite, \
                        QuestionnaireQuestion, LISTE_METHODES_TARIFS, DICT_COLONNES_TARIFS
from parametrage.widgets import ParametresTarifs
from parametrage.forms import activites_tarifs
from parametrage.views.activites_assistant import Assistant_base, Page_responsable, Page_responsable, Page_renseignements as Page_renseignements_base, \
                                                    Page_categories, Page_categories_nombre, Page_conclusion, Page_groupes_nombre, Page_groupes_noms, \
                                                    Page_formulaires, Page_documents


class Page_introduction(forms.Form):
    intro = "Bienvenue dans l'assistant de paramétrage d'une activité de type séjour (camp, mini-camp, colo, etc...)<br><br>Cliquez sur le bouton Suite pour commencer la saisie des informations."

class Page_generalites(forms.Form):
    nom_activite = forms.CharField(label="Quel est le nom du séjour ?", required=True, max_length=300, help_text="Exemple: 'Séjour neige - Février 2020'.")
    date_debut = forms.DateField(label="Quelle est la date de début du séjour ?", required=True, widget=DatePickerWidget(), help_text="Saisissez la date de début du séjour.")
    date_fin = forms.DateField(label="Quelle est la date de fin ?", required=True, widget=DatePickerWidget(), help_text="Saisissez la date de fin du séjour.")
    structure = forms.ModelChoiceField(label="Quelle est la structure associée à ce séjour ?", queryset=Structure.objects.all(), required=True, help_text="Sélectionnez une structure dans la liste proposée.")
    public = forms.TypedChoiceField(label="Quel est le public destinataire de ce séjour ?", choices=Activite.public_liste, coerce=int, initial=5, required=True)
    nbre_inscrits_max = forms.IntegerField(label="Quel est le nombre maximal d'inscrits ?", initial=0, min_value=0, required=False, help_text="S'il n'existe aucune limitation du nombre d'inscrits, laisser la valeur à 0.")
    inscriptions_multiples = forms.BooleanField(label="Autoriser plusieurs inscriptions simultanées pour chaque individu", required=False, help_text="Cochez cette case si un même enfant peut être inscrit plusieurs fois à ce séjour.")
    num_decla = forms.CharField(label="Quel est le numéro de déclaration de l'activité ?", max_length=200, required=False, help_text="Laissez vide si non applicable.")
    image = forms.ImageField(label="Image du séjour", required=False, help_text="Cette image sera utilisée sur le portail des familles.")
    choix_visibilite_traitements = [("DEBUT", "Dès le début du séjour"), ("FIN", "À la fin du séjour"), ("PERSONNALISE", "À une date personnalisée")]
    type_visibilite_traitements = forms.TypedChoiceField(label="À partir de quand les traitements médicaux doivent-ils être visibles par l'équipe d'encadrement ?", choices=choix_visibilite_traitements, initial="DEBUT", required=True)
    date_traitements_visibles = forms.DateField(label="Date de visibilité personnalisée", required=False, widget=DatePickerWidget(), help_text="Uniquement si vous avez choisi une date personnalisée ci-dessus.")

    def __init__(self, *args, **kwargs):
        super(Page_generalites, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Fieldset("Généralités", "nom_activite", "structure", "public"),
            Fieldset("Dates et places", "date_debut", "date_fin", "nbre_inscrits_max", "inscriptions_multiples"),
            Fieldset("Déclaration et image", "num_decla", "image"),
            Fieldset("Traitements médicaux", "type_visibilite_traitements", "date_traitements_visibles"),
        )

    def clean(self):
        if self.cleaned_data.get("date_debut") and self.cleaned_data.get("date_fin") and self.cleaned_data["date_debut"] > self.cleaned_data["date_fin"]:
            self.add_error("date_fin", "La date de fin doit être supérieure à la date de début")
            return self.cleaned_data

        # Calcul de la date de visibilité des traitements médicaux
        choix_visibilite = self.cleaned_data.get("type_visibilite_traitements")
        if choix_visibilite == "DEBUT":
            self.cleaned_data["date_traitements_visibles"] = self.cleaned_data.get("date_debut")
        elif choix_visibilite == "FIN":
            self.cleaned_data["date_traitements_visibles"] = self.cleaned_data.get("date_fin")
        elif choix_visibilite == "PERSONNALISE" and not self.cleaned_data.get("date_traitements_visibles"):
            self.add_error("date_traitements_visibles", "Vous devez sélectionner une date")

        return self.cleaned_data

class Page_renseignements(Page_renseignements_base):
    """ Comme l'étape standard, mais sans le champ des adhésions à jour, et avec les vaccinations obligatoires """
    vaccins_obligatoires = forms.BooleanField(label="Vaccinations obligatoires", required=False, initial=True,
                                              help_text="Cochez cette case si les vaccinations sont obligatoires pour participer à ce séjour.")

    def __init__(self, *args, **kwargs):
        super(Page_renseignements, self).__init__(*args, **kwargs)
        del self.fields['cotisations']

class Page_parametres(forms.Form):
    """ Reprend les mêmes options que l'onglet Paramètres d'une activité existante, avec les mêmes valeurs par défaut """
    choix_affichage_inscriptions = [("JAMAIS", "Ne pas autoriser"), ("TOUJOURS", "Autoriser"), ("PERIODE", "Autoriser sur la période suivante")]
    portail_inscriptions_affichage = forms.ChoiceField(label="Inscriptions autorisées sur le portail", choices=choix_affichage_inscriptions, initial="TOUJOURS", required=True,
                                                       help_text="Sélectionnez Autoriser pour permettre aux usagers de demander une inscription à ce séjour depuis le portail.")
    portail_inscriptions_date_debut = forms.DateTimeField(label="Date de début d'affichage", required=False, widget=DateTimePickerWidget())
    portail_inscriptions_date_fin = forms.DateTimeField(label="Date de fin d'affichage", required=False, widget=DateTimePickerWidget())
    portail_inscriptions_bloquer_si_complet = forms.BooleanField(label="Empêcher l'inscription si le séjour est complet", required=False, initial=False)
    portail_inscriptions_imposer_pieces = forms.BooleanField(label="Imposer le téléchargement des pièces à fournir lors de l'inscription", required=False, initial=False)
    visible = forms.BooleanField(label="Visible sur le portail", required=False, initial=True)
    actif = forms.BooleanField(label="Activité active", required=False, initial=True)
    interne = forms.BooleanField(label="Mutualisation questionnaire", required=False, initial=False,
                                 help_text="Cochez cette case si vous souhaitez avoir le questionnaire habituel de Sacadoc destiné aux camps d'été.")
    maitrise = forms.BooleanField(label="Activité avec équipe encadrante", required=False, initial=True,
                                  help_text="Cochez cette case si l'équipe encadrante doit s'inscrire à ce séjour.")
    choix_tpe = [("", "---------"), ("HELLOASSO", "HelloAsso"), ("STRIPE", "Stripe"), ("PAYASSO", "PayAsso"), ("AUTRE", "Divers")]
    pay_org_tpe = forms.ChoiceField(label="Passerelle de paiement", choices=choix_tpe, required=False)
    pay_org = forms.BooleanField(label="Activation paiement par plateforme externe", required=False, initial=False)

    def __init__(self, *args, **kwargs):
        super(Page_parametres, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Fieldset("Inscriptions sur le portail", "portail_inscriptions_affichage", "portail_inscriptions_date_debut", "portail_inscriptions_date_fin",
                     "portail_inscriptions_bloquer_si_complet", "portail_inscriptions_imposer_pieces"),
            Fieldset("Visibilité", "visible", "actif"),
            Fieldset("Divers", "interne", "maitrise"),
            Fieldset("Paiement", "pay_org_tpe", "pay_org"),
        )

    def clean(self):
        if self.cleaned_data.get("portail_inscriptions_affichage") == "PERIODE":
            if not self.cleaned_data.get("portail_inscriptions_date_debut"):
                self.add_error("portail_inscriptions_date_debut", "Vous devez sélectionner une date de début d'affichage")
            if not self.cleaned_data.get("portail_inscriptions_date_fin"):
                self.add_error("portail_inscriptions_date_fin", "Vous devez sélectionner une date de fin d'affichage")
        else:
            self.cleaned_data["portail_inscriptions_date_debut"] = None
            self.cleaned_data["portail_inscriptions_date_fin"] = None
        return self.cleaned_data

class Page_nbre_questions(forms.Form):
    nbre_questions = forms.IntegerField(label="Combien de questions spécifiques à ce séjour souhaitez-vous ajouter ?", initial=0, min_value=0, required=True, help_text="Laissez 0 si aucune question spécifique n'est nécessaire. Les questions déjà posées à toute la structure s'appliqueront de toute façon automatiquement.")

class Page_questionnaires(forms.Form):
    """ Rappelle les questions déjà valables pour toute la structure et permet d'ajouter des questions propres à ce séjour """
    choix_controles = [("bloc_texte", "Texte"), ("entier", "Nombre entier"), ("decimal", "Nombre décimal"), ("montant", "Montant"),
                        ("liste_deroulante", "Liste déroulante"), ("liste_coches", "Sélection multiple"), ("liste_coches_ouinon", "Sélection Oui/Non"), ("date", "Date")]

    def __init__(self, *args, **kwargs):
        structure = kwargs.pop("structure", None)
        nbre_questions = kwargs.pop("nbre_questions", 0)
        super(Page_questionnaires, self).__init__(*args, **kwargs)

        liste_questions = QuestionnaireQuestion.objects.filter(structure=structure, activite__isnull=True).order_by("ordre") if structure else QuestionnaireQuestion.objects.none()
        if liste_questions:
            texte_liste = "<ul>%s</ul>" % "".join("<li>%s</li>" % question.label for question in liste_questions)
        else:
            texte_liste = "<p>Aucune question n'est actuellement configurée pour toute la structure.</p>"
        self.intro = (
            "Les questions suivantes, déjà posées à toute la structure choisie, s'appliqueront automatiquement à ce séjour :" + texte_liste
        )

        liste_fieldsets = []
        for index in range(1, nbre_questions + 1):
            self.fields["label_question_%d" % index] = forms.CharField(label="Intitulé", max_length=250, required=True)
            self.fields["controle_question_%d" % index] = forms.ChoiceField(label="Type de réponse attendue", choices=self.choix_controles, initial="bloc_texte", required=True)
            self.fields["choix_question_%d" % index] = forms.CharField(label="Choix possibles", max_length=500, required=False,
                                                                        help_text="Uniquement pour les types Liste. Séparez les choix par un point-virgule. Exemple : 'Bananes;Pommes;Poires'.")
            liste_fieldsets.append(Fieldset("Question n°%d" % index, "label_question_%d" % index, "controle_question_%d" % index, "choix_question_%d" % index))

        if liste_fieldsets:
            self.helper = FormHelper()
            self.helper.form_tag = False
            self.helper.layout = Layout(*liste_fieldsets)

class Page_groupes(forms.Form):
    has_groupes = forms.ChoiceField(label="Quels sont les différents groupes du séjour ?", choices=[("oui", "Il y a plusieurs groupes"), ("non", "Un seul groupe")], widget=forms.RadioSelect, initial="non", help_text="Exemple : 'Louveteaux' et 'Éclaireurs'. Si le séjour ne comporte qu'un seul groupe, laissez 'Un seul groupe'.")

class Page_nbre_tarifs(forms.Form):
    """ Demande, pour chaque catégorie de tarifs, combien de tarifs différents doivent être proposés """
    def __init__(self, *args, **kwargs):
        nbre_categories = kwargs.pop("nbre_categories", 1)
        if nbre_categories == 0:
            nbre_categories = 1
        super(Page_nbre_tarifs, self).__init__(*args, **kwargs)
        for index in range(1, nbre_categories + 1):
            label = "Combien de tarifs différents souhaitez-vous proposer"
            if nbre_categories > 1:
                label += " pour la catégorie n°%d" % index
            label += " ?"
            self.fields["nbre_tarifs_%d" % index] = forms.IntegerField(label=label, initial=1, min_value=1, required=True,
                                                                        help_text="Exemple : un tarif 'Adhérent' et un tarif 'Non adhérent'. Laissez 1 s'il n'y a qu'un seul tarif.")

class Page_tarifs(forms.Form):
    def __init__(self, *args, **kwargs):
        self.nbre_categories = kwargs.pop("nbre_categories")
        if self.nbre_categories == 0:
            self.nbre_categories = 1
        self.nbre_tarifs_par_categorie = kwargs.pop("nbre_tarifs_par_categorie", {1: 1})
        nom_activite = kwargs.pop("nom_activite", "")
        super(Page_tarifs, self).__init__(*args, **kwargs)

        liste_questionnaires = json.dumps([{"id": question.pk, "name": question.label} for question in QuestionnaireQuestion.objects.filter(controle__in=("decimal", "montant"))])

        liste_fieldsets = []
        for index_categorie in range(1, self.nbre_categories + 1):
            champs_categorie = []
            if self.nbre_categories > 1:
                nom = "nom_categorie_%d" % index_categorie
                self.fields[nom] = forms.CharField(label="Quel est le nom de la catégorie de tarifs n°%d ?" % index_categorie, max_length=300, help_text="")
                champs_categorie.append(nom)

            nbre_tarifs = self.nbre_tarifs_par_categorie.get(index_categorie, 1)
            for index_tarif in range(1, nbre_tarifs + 1):
                cle = "c%d_t%d" % (index_categorie, index_tarif)
                champs_tarif = []

                if nbre_tarifs > 1:
                    label_nom_tarif = "Quel est le nom du tarif n°%d ?" % index_tarif
                    initial_nom_tarif = None
                else:
                    label_nom_tarif = "Quel est le nom de ce tarif ?"
                    initial_nom_tarif = nom_activite
                self.fields["nom_tarif_%s" % cle] = forms.CharField(label=label_nom_tarif, max_length=300, required=True, initial=initial_nom_tarif,
                                                                     help_text="Ce nom apparaîtra sur les factures et prestations. Exemple : 'Séjour', 'Adhérent', 'Non adhérent'...")
                champs_tarif.append("nom_tarif_%s" % cle)

                self.fields["data_tarif_%s" % cle] = forms.CharField(widget=forms.HiddenInput(), required=False)
                self.fields["methode_tarif_%s" % cle] = forms.ChoiceField(label="Méthode de calcul", choices=[(dict_methode["code"], dict_methode["label"]) for dict_methode in LISTE_METHODES_TARIFS[:2]], initial="montant_unique", required=True)
                champs_tarif.append("methode_tarif_%s" % cle)
                attrs = {
                    'liste_methodes_tarifs': LISTE_METHODES_TARIFS[:2],
                    'dict_colonnes_tarifs': DICT_COLONNES_TARIFS,
                    'id_ctrl_methode': "id_tarifs-methode_tarif_%s" % cle,
                    'id': cle,
                    'id_tarifs_lignes_data': "id_tarifs-data_tarif_%s" % cle,
                    'id_form': 'form_assistant',
                    'questionnaires': liste_questionnaires,
                }
                self.fields["parametres_tarif_%s" % cle] = forms.CharField(label="Paramètres du tarif", widget=ParametresTarifs(attrs=attrs), required=False, help_text="")
                champs_tarif.append("parametres_tarif_%s" % cle)

                titre_tarif = "Tarif n°%d" % index_tarif if nbre_tarifs > 1 else "Tarif"
                if self.nbre_categories > 1:
                    titre_tarif += " (catégorie n°%d)" % index_categorie
                liste_fieldsets.append(Fieldset(titre_tarif, *champs_tarif))

            if champs_categorie:
                liste_fieldsets.insert(len(liste_fieldsets) - nbre_tarifs, Fieldset("Catégorie n°%d" % index_categorie, *champs_categorie))

        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(*liste_fieldsets)

    def clean(self):
        for index_categorie in range(1, self.nbre_categories + 1):
            nbre_tarifs = self.nbre_tarifs_par_categorie.get(index_categorie, 1)
            for index_tarif in range(1, nbre_tarifs + 1):
                cle = "c%d_t%d" % (index_categorie, index_tarif)
                key = "data_tarif_%s" % cle
                if self.cleaned_data.get(key, []):
                    liste_lignes_resultats = activites_tarifs.Clean_tarifs_lignes_data(tarifs_lignes_data=json.loads(self.cleaned_data[key]), code_methode=self.cleaned_data["methode_tarif_%s" % cle])
                    self.cleaned_data["tarifs_lignes_data_resultats_%s" % cle] = liste_lignes_resultats
        return self.cleaned_data


class Assistant(Assistant_base):
    form_list = [
        ("introduction", Page_introduction),
        ("generalites", Page_generalites),
        ("responsable", Page_responsable),
        ("renseignements", Page_renseignements),
        ("formulaires", Page_formulaires),
        ("questions_nombre", Page_nbre_questions),
        ("questionnaires", Page_questionnaires),
        ("documents", Page_documents),
        ("parametres", Page_parametres),
        ("groupes", Page_groupes),
        ("nbre_groupes", Page_groupes_nombre),
        ("noms_groupes", Page_groupes_noms),
        ("categories", Page_categories),
        ("nbre_categories", Page_categories_nombre),
        ("nbre_tarifs", Page_nbre_tarifs),
        ("tarifs", Page_tarifs),
        ("conclusion", Page_conclusion),
    ]

    def get_context_data(self, **kwargs):
        context = super(Assistant, self).get_context_data(**kwargs)
        context['page_titre'] = "Activités"
        context['box_titre'] = "Assistant de paramétrage d'un séjour"
        return context

    def Get_nbre_categories(self):
        has_categories = (self.get_cleaned_data_for_step("categories") or {}).get("has_categories", "non")
        data = self.get_cleaned_data_for_step("nbre_categories") if has_categories == "oui" else None
        return data["nbre_categories"] if data else 1

    def get_form_kwargs(self, step=None):
        kwargs = super(Assistant, self).get_form_kwargs(step=step)
        if step == "questionnaires":
            kwargs['nbre_questions'] = (self.get_cleaned_data_for_step("questions_nombre") or {}).get("nbre_questions", 0)
        if step == "nbre_tarifs":
            kwargs['nbre_categories'] = self.Get_nbre_categories()
        if step == "tarifs":
            nbre_categories = self.Get_nbre_categories()
            donnees_nbre_tarifs = self.get_cleaned_data_for_step("nbre_tarifs") or {}
            kwargs['nbre_tarifs_par_categorie'] = {index: donnees_nbre_tarifs.get("nbre_tarifs_%d" % index, 1) for index in range(1, nbre_categories + 1)}
            kwargs['nom_activite'] = (self.get_cleaned_data_for_step("generalites") or {}).get("nom_activite", "")
        return kwargs

    def Generation(self, donnees={}):
        # Enregistrement des données standard
        donnees = self.Enregistrement_donnees_standard(donnees)

        # Enregistrement de l'unité de conso
        unite = Unite.objects.create(activite=donnees["activite"], nom="Journée Camp", abrege="JC", ordre=1, type="Unitaire",
                                     date_debut=datetime.date(1977, 1, 1), date_fin=datetime.date(2999, 1, 1),
                                     equiv_journees=1, equiv_heures=datetime.time(hour=10, minute=0))

        # Enregistrement de l'unité de remplissage
        unite_remplissage = UniteRemplissage.objects.create(activite=donnees["activite"], nom="Journée Camp", abrege="JC", ordre=1,
                                                            date_debut=datetime.date(1977, 1, 1), date_fin=datetime.date(2999, 1, 1))
        unite_remplissage.unites.add(unite)

        # Calendrier
        liste_dates = list(rrule.rrule(rrule.DAILY, dtstart=donnees["date_debut"], until=donnees["date_fin"]))

        # Enregistrement des ouvertures
        for date in liste_dates:
            for groupe in donnees["groupes"]:
                Ouverture.objects.create(activite=donnees["activite"], date=date, groupe=groupe, unite=unite)

        # Enregistrement du remplissage
        if donnees["nbre_inscrits_max"]:
            for date in liste_dates:
                for groupe in donnees["groupes"]:
                    Remplissage.objects.create(activite=donnees["activite"], date=date, groupe=groupe, unite_remplissage=unite_remplissage, places=donnees["nbre_inscrits_max"])

        # Enregistrement des tarifs et lignes de tarifs (chaque catégorie peut avoir un nombre de tarifs différent,
        # chacun avec son propre nom, saisi à l'étape précédente)
        for index_categorie, categorie_tarif in enumerate(donnees["liste_categories"], 1):
            nbre_tarifs = donnees.get("nbre_tarifs_%d" % index_categorie, 1) or 1
            for index_tarif in range(1, nbre_tarifs + 1):
                cle = "c%d_t%d" % (index_categorie, index_tarif)
                nom_tarif = NomTarif.objects.create(activite=donnees["activite"], nom=donnees.get("nom_tarif_%s" % cle) or donnees["nom_activite"])
                tarif = Tarif.objects.create(activite=donnees["activite"], type="FORFAIT", nom_tarif=nom_tarif, date_debut=donnees["date_debut"],
                                             forfait_saisie_auto=True, forfait_suppression_auto=True, label_prestation="nom_tarif", options="calendrier",
                                             methode=donnees["methode_tarif_%s" % cle])
                tarif.categories_tarifs.add(categorie_tarif)

                for index_ligne, dict_ligne in enumerate(donnees.get("tarifs_lignes_data_resultats_%s" % cle, []), 0):
                    if dict_ligne:
                        data_dict = {"activite": donnees["activite"], "tarif": tarif, "code": donnees["methode_tarif_%s" % cle], "num_ligne": index_ligne}
                        data_dict.update(dict_ligne)
                        TarifLigne(**data_dict).save()

        # Enregistrement des questions spécifiques à ce séjour
        nbre_questions = donnees.get("nbre_questions", 0)
        for index in range(1, nbre_questions + 1):
            label_question = donnees.get("label_question_%d" % index)
            if label_question:
                QuestionnaireQuestion.objects.create(
                    structure=donnees["activite"].structure, activite=donnees["activite"], categorie="individu", ordre=index,
                    label=label_question, controle=donnees.get("controle_question_%d" % index, "bloc_texte"),
                    choix=donnees.get("choix_question_%d" % index) or None,
                )
