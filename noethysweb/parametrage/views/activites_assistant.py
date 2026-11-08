# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django.urls import reverse_lazy, reverse
from django.db.models import F
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from core.views.base import CustomView
from django.views.generic import TemplateView
from django.http import HttpResponseRedirect
from formtools.wizard.views import SessionWizardView
from django import forms
from core.forms.select2 import Select2MultipleWidget
from core.models import TypeGroupeActivite, TypePiece, TypeCotisation, TypeQuotient, LISTE_METHODES_TARIFS, DICT_COLONNES_TARIFS, \
                        Activite, Agrement, ResponsableActivite, Groupe, CategorieTarif, TarifLigne, CombiTarif, QuestionnaireQuestion, \
                        Sondage, PortailDocument
from parametrage.widgets import ParametresTarifs
from parametrage.forms import activites_tarifs
from parametrage.forms.activites_renseignements import Get_label_piece
from django.contrib import messages
import os, datetime, json


def CreationAbrege(nom=""):
    for i in " /*-+.,;:_'()":
        nom = nom.replace(i, "")
    return nom[:5].upper()


class Page_responsable(forms.Form):
    nom = forms.CharField(label="Quel est le nom complet du responsable de l'activité (Prénom suivi du nom) ?", max_length=300, help_text="Exemple : Jean-Louis DUPOND")
    fonction = forms.CharField(label="Quelle est sa fonction ?", max_length=300, help_text="Exemples : Directeur, secrétaire...")
    sexe = forms.ChoiceField(label="Homme ou femme ?", choices=[("H", "Homme"), ("F", "Femme")], initial="H")

    def __init__(self, *args, **kwargs):
        super(Page_responsable, self).__init__(*args, **kwargs)
        responsable = ResponsableActivite.objects.last()
        if responsable:
            self.fields["nom"].initial = responsable.nom
            self.fields["fonction"].initial = responsable.fonction
            self.fields["sexe"].initial = responsable.sexe

class Page_renseignements(forms.Form):
    pieces = forms.ModelMultipleChoiceField(label="Pièces à fournir", widget=Select2MultipleWidget(), queryset=TypePiece.objects.all(), required=False)
    cotisations = forms.ModelMultipleChoiceField(label="Adhésions à jour", widget=Select2MultipleWidget(), queryset=TypeCotisation.objects.all(), required=False)

    def __init__(self, *args, **kwargs):
        super(Page_renseignements, self).__init__(*args, **kwargs)
        # Met en avant les pièces standard définies par l'organisateur (sans structure), suggérées pour toutes les activités
        self.fields['pieces'].queryset = self.fields['pieces'].queryset.order_by(F("structure_id").asc(nulls_first=True), "nom")
        self.fields['pieces'].label_from_instance = Get_label_piece

class Page_formulaires(forms.Form):
    """ Étape informative : un formulaire (Sondage) est rattaché à la structure entière, pas à une activité en particulier.
    Ceux déjà configurés pour la structure choisie s'appliqueront donc automatiquement à cette nouvelle activité. """
    def __init__(self, *args, **kwargs):
        structure = kwargs.pop("structure", None)
        super(Page_formulaires, self).__init__(*args, **kwargs)
        liste_sondages = Sondage.objects.filter(structure=structure).order_by("titre") if structure else Sondage.objects.none()
        if liste_sondages:
            texte_liste = "<ul>%s</ul>" % "".join("<li>%s</li>" % sondage.titre for sondage in liste_sondages)
        else:
            texte_liste = "<p>Aucun formulaire n'est actuellement configuré pour cette structure.</p>"
        self.intro = (
            "Les formulaires (autorisations, consentements...) ne se configurent pas par activité : ceux définis pour la "
            "structure choisie s'appliquent automatiquement à toutes ses activités, dont celle-ci." + texte_liste +
            "<a class='btn btn-warning' href='%s' target='_blank'><i class='fa fa-plus margin-r-5'></i>Créer un nouveau formulaire</a>" % reverse("sondages_ajouter")
        )

class Page_questionnaires(forms.Form):
    """ Étape informative : les questions déjà valables pour toute la structure s'appliqueront automatiquement à cette
    activité. Une question spécifique à cette activité pourra être créée une fois celle-ci enregistrée. """
    def __init__(self, *args, **kwargs):
        structure = kwargs.pop("structure", None)
        super(Page_questionnaires, self).__init__(*args, **kwargs)
        liste_questions = QuestionnaireQuestion.objects.filter(structure=structure, activite__isnull=True).order_by("ordre") if structure else QuestionnaireQuestion.objects.none()
        if liste_questions:
            texte_liste = "<ul>%s</ul>" % "".join("<li>%s</li>" % question.label for question in liste_questions)
        else:
            texte_liste = "<p>Aucune question n'est actuellement configurée pour toute la structure.</p>"
        self.intro = (
            "Les questions suivantes, déjà posées à toute la structure choisie, s'appliqueront automatiquement à cette "
            "activité :" + texte_liste +
            "<a class='btn btn-warning' href='%s' target='_blank'><i class='fa fa-list margin-r-5'></i>Gérer les questionnaires</a>"
            "<br><br><i class='fa fa-info-circle margin-r-5'></i>Une question spécifique à cette activité pourra être ajoutée une fois celle-ci créée." % reverse("questions_liste")
        )

class Page_documents(forms.Form):
    documents = forms.ModelMultipleChoiceField(label="Documents à mettre à disposition des familles sur le portail", widget=Select2MultipleWidget(), queryset=PortailDocument.objects.none(), required=False,
                                               help_text="Sélectionnez les documents déjà existants (règlement intérieur, plaquette...) à mettre à disposition pour cette activité.")

    def __init__(self, *args, **kwargs):
        structure = kwargs.pop("structure", None)
        super(Page_documents, self).__init__(*args, **kwargs)
        self.fields['documents'].queryset = PortailDocument.objects.filter(structure=structure).order_by("titre") if structure else PortailDocument.objects.none()
        if not self.fields['documents'].queryset:
            self.intro = (
                "<p>Aucun document n'est actuellement disponible pour cette structure.</p>"
                "<a class='btn btn-warning' href='%s' target='_blank'><i class='fa fa-plus margin-r-5'></i>Créer un nouveau document</a>" % reverse("portail_documents_ajouter")
            )

class Page_groupes(forms.Form):
    has_groupes = forms.ChoiceField(label="L'activité est-elle constituée de groupes distincts ?", choices=[("oui", "Oui"), ("non", "Non")], widget=forms.RadioSelect, initial="non", help_text="Exemple : Les maternels et les primaires. Si vous n'êtes pas sûr, laissez non.")

class Page_groupes_nombre(forms.Form):
    nbre_groupes = forms.IntegerField(label="Combien y a t-il de groupes ?", initial=1, min_value=1, required=True, help_text="")

class Page_groupes_noms(forms.Form):
    def __init__(self, *args, **kwargs):
        nbre_groupes = kwargs.pop("nbre_groupes")
        super(Page_groupes_noms, self).__init__(*args, **kwargs)
        for index in range(1, nbre_groupes+1):
            self.fields["nom_groupe_%d" % index] = forms.CharField(label="Quel est le nom du groupe n°%d ?" % index, max_length=300, help_text="")

class Page_categories(forms.Form):
    has_categories = forms.ChoiceField(label="Avez-vous plusieurs catégories de tarifs ?", choices=[("oui", "Oui"), ("non", "Non")], widget=forms.RadioSelect, initial="non", help_text="")

class Page_categories_nombre(forms.Form):
    nbre_categories = forms.IntegerField(label="Quel est le nombre de catégories de tarifs ?", initial=2, min_value=2, required=True, help_text="")

class Page_tarifs(forms.Form):
    def __init__(self, *args, **kwargs):
        self.nbre_categories = kwargs.pop("nbre_categories")
        if self.nbre_categories == 0:
            self.nbre_categories = 1
        super(Page_tarifs, self).__init__(*args, **kwargs)
        for index in range(1, self.nbre_categories+1):
            if self.nbre_categories > 1:
                self.fields["nom_categorie_%d" % index] = forms.CharField(label="Quel est le nom de la catégorie de tarifs n°%d ?" % index, max_length=300, help_text="")
                texte_categorie = " pour la catégorie n°%d" % index
            else:
                texte_categorie = ""
            self.fields["data_tarif_%d" % index] = forms.CharField(widget=forms.HiddenInput(), required=False)
            self.fields["methode_tarif_%d" % index] = forms.ChoiceField(label="Méthode de calcul%s" % texte_categorie, choices=[(dict_methode["code"], dict_methode["label"]) for dict_methode in LISTE_METHODES_TARIFS[:2]], initial="montant_unique", required=True)
            attrs = {
                'liste_methodes_tarifs': LISTE_METHODES_TARIFS[:2],
                'dict_colonnes_tarifs': DICT_COLONNES_TARIFS,
                'id_ctrl_methode': "id_tarifs-methode_tarif_%d" % index,
                'id': index,
                'id_tarifs_lignes_data': "id_tarifs-data_tarif_%d" % index,
                'id_form': 'form_assistant',
                'questionnaires': json.dumps([{"id": question.pk, "name": question.label} for question in QuestionnaireQuestion.objects.filter(controle__in=("decimal", "montant"))]),
            }
            self.fields["parametres_tarif_%d" % index] = forms.CharField(label="Paramètres du tarif%s" % texte_categorie, widget=ParametresTarifs(attrs=attrs), required=False, help_text="")
            self.fields["type_quotient_tarif_%d" % index] = forms.ModelChoiceField(label="Type de quotient à utiliser%s" % texte_categorie, queryset=TypeQuotient.objects.all(), required=False, help_text="Sélectionnez un type de quotient familial ou laissez le champ vide pour tenir compte de tous les types de quotients.")

    def clean(self):
        for index in range(1, self.nbre_categories + 1):
            key = "data_tarif_%d" % index
            if self.cleaned_data.get(key, []):
                liste_lignes_resultats = activites_tarifs.Clean_tarifs_lignes_data(tarifs_lignes_data=json.loads(self.cleaned_data[key]), code_methode=self.cleaned_data["methode_tarif_%d" % index])
                self.cleaned_data["tarifs_lignes_data_resultats_%s" % index] = liste_lignes_resultats
        return self.cleaned_data

class Page_conclusion(forms.Form):
    intro = "Vous avez terminé de renseigner les paramètres de l'activité.<br><br>Cliquez maintenant sur le bouton Suite pour finaliser la création de l'activité."


def Afficher_page_nbre_groupes(wizard):
    cleaned_data = wizard.get_cleaned_data_for_step("groupes") or {}
    return True if cleaned_data.get("has_groupes", "non") == "oui" else False

def Afficher_page_noms_groupes(wizard):
    cleaned_data = wizard.get_cleaned_data_for_step("groupes") or {}
    afficher = True if cleaned_data.get("has_groupes", "non") == "oui" else False
    if wizard.get_cleaned_data_for_step("groupes") and "has_consommations" in wizard.get_cleaned_data_for_step("groupes"):
        if wizard.get_cleaned_data_for_step("groupes").get("has_consommations", "non") == "oui":
            afficher = True
    return afficher

def Afficher_page_nbre_categories(wizard):
    cleaned_data = wizard.get_cleaned_data_for_step("categories") or {}
    return True if cleaned_data.get("has_categories", "non") == "oui" else False



class Assistant_base(CustomView, SessionWizardView):
    menu_code = "activites_liste"
    template_name = "parametrage/activites_assistant.html"
    file_storage = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, "temp_wizard"))
    condition_dict = {
        "nbre_groupes": Afficher_page_nbre_groupes,
        "noms_groupes": Afficher_page_noms_groupes,
        "nbre_categories": Afficher_page_nbre_categories,
    }

    def get_context_data(self, **kwargs):
        context = super(Assistant_base, self).get_context_data(**kwargs)
        context['page_titre'] = "Activités"
        context['box_titre'] = "Assistant de paramétrage"
        return context

    def get_form_kwargs(self, step=None):
        kwargs = {}
        if step == "noms_groupes":
            has_groupes = self.get_cleaned_data_for_step("groupes")["has_groupes"]
            data = self.get_cleaned_data_for_step("nbre_groupes") if has_groupes == "oui" else None
            kwargs['nbre_groupes'] = data["nbre_groupes"] if data else 0
            if "has_consommations" in self.get_cleaned_data_for_step("groupes"):
                kwargs['has_consommations'] = self.get_cleaned_data_for_step("groupes").get("has_consommations", "non")
        if step == "tarifs":
            has_categories = self.get_cleaned_data_for_step("categories")["has_categories"]
            data = self.get_cleaned_data_for_step("nbre_categories") if has_categories == "oui" else None
            kwargs['nbre_categories'] = data["nbre_categories"] if data else 0
        if step in ("formulaires", "questionnaires", "documents"):
            kwargs['structure'] = (self.get_cleaned_data_for_step("generalites") or {}).get("structure")
        return kwargs

    def done(self, form_list, **kwargs):
        self.Generation(donnees=self.get_all_cleaned_data())
        messages.add_message(self.request, messages.SUCCESS, "L'activité a été créée avec succès")
        return HttpResponseRedirect(reverse_lazy('activites_liste'))

    def Enregistrement_donnees_standard(self, donnees={}):
        nom = donnees["nom_activite"]
        abrege = CreationAbrege(nom)
        date_debut = donnees["date_debut"] if donnees.get("date_debut", None) else datetime.date(1977, 1, 1)
        date_fin = donnees["date_fin"] if donnees.get("date_fin", None) else datetime.date(2999, 1, 1)
        nbre_inscrits_max = donnees["nbre_inscrits_max"] if donnees.get("nbre_inscrits_max", None) else None

        # Date de visibilité des traitements médicaux (DateField dans l'assistant, DateTimeField sur le modèle)
        date_traitements_visibles = donnees.get("date_traitements_visibles")
        if date_traitements_visibles and not isinstance(date_traitements_visibles, datetime.datetime):
            date_traitements_visibles = datetime.datetime.combine(date_traitements_visibles, datetime.time(0, 0))

        # Enregistrement de l'activité (les valeurs par défaut reprennent celles du modèle Activite)
        activite = Activite.objects.create(
            nom=nom, abrege=abrege, date_debut=date_debut, date_fin=date_fin, nbre_inscrits_max=nbre_inscrits_max, structure=donnees.get("structure"),
            public=donnees.get("public", 5), num_decla=donnees.get("num_decla") or None, image=donnees.get("image") or None,
            inscriptions_multiples=donnees.get("inscriptions_multiples", False), date_traitements_visibles=date_traitements_visibles,
            vaccins_obligatoires=donnees.get("vaccins_obligatoires", True),
            portail_inscriptions_affichage=donnees.get("portail_inscriptions_affichage", "TOUJOURS"),
            portail_inscriptions_date_debut=donnees.get("portail_inscriptions_date_debut"),
            portail_inscriptions_date_fin=donnees.get("portail_inscriptions_date_fin"),
            portail_inscriptions_bloquer_si_complet=donnees.get("portail_inscriptions_bloquer_si_complet", False),
            portail_inscriptions_imposer_pieces=donnees.get("portail_inscriptions_imposer_pieces", False),
            visible=donnees.get("visible", True), actif=donnees.get("actif", True),
            interne=donnees.get("interne", False), maitrise=donnees.get("maitrise", True),
            pay_org_tpe=donnees.get("pay_org_tpe") or None, pay=donnees.get("pay") or None, pay_org=donnees.get("pay_org", False),
        )
        donnees["activite"] = activite

        # Enregistrement des groupes d'activités
        for groupe_activites in donnees.get("groupes_activites", []):
            activite.groupes_activites.add(groupe_activites)

        # Enregistrement de l'agrément
        agrement = donnees.get("agrement", None)
        if agrement:
            Agrement.objects.create(activite=activite, agrement=agrement, date_debut=date_debut, date_fin=date_fin)

        # Enregistrement du responsable d'activité
        nom = donnees.get("nom", None)
        fonction = donnees.get("fonction", None)
        sexe = donnees.get("sexe", None)
        if nom:
            ResponsableActivite.objects.create(activite=activite, sexe=sexe, nom=nom, fonction=fonction, defaut=True)

        # Enregistrement des groupes
        donnees["groupes"] = []

        if donnees.get("has_groupes", "non") == "non":
            groupe = Groupe.objects.create(activite=activite, nom="Groupe unique", abrege="UNIQ", ordre=1)
            donnees["groupes"].append(groupe)

        if donnees.get("has_groupes", "non") == "oui":
            nbre_groupes = donnees.get("nbre_groupes", 0)
            for index in range(1, nbre_groupes + 1):
                nom_groupe = donnees.get("nom_groupe_%d" % index, None)
                abrege_groupe = CreationAbrege(nom_groupe)
                nbre_inscrits_max = donnees.get("nbre_inscrits_max_groupe_%d" % index, None)
                groupe = Groupe.objects.create(activite=activite, nom=nom_groupe, abrege=abrege_groupe, ordre=index, nbre_inscrits_max=nbre_inscrits_max)
                donnees["groupes"].append(groupe)

        # Enregistrement des pièces associées
        for piece in donnees.get("pieces", []):
            activite.pieces.add(piece)

        # Association des documents portail déjà existants (formulaires et questionnaires s'appliquent automatiquement via la structure)
        for document in donnees.get("documents", []):
            document.activites.add(activite)

        # Enregistrement des cotisations associées
        for cotisation in donnees.get("cotisations", []):
            activite.cotisations.add(cotisation)

        # Enregistrement des catégories de tarifs
        donnees["liste_categories"] = []
        if donnees.get("has_categories", "non") == "non":
            categorie_tarif = CategorieTarif.objects.create(activite=donnees["activite"], nom="Catégorie unique")
            donnees["liste_categories"].append(categorie_tarif)

        if donnees.get("has_categories", "non") == "oui":
            nbre_categories = donnees.get("nbre_categories", 0)
            for index in range(1, nbre_categories + 1):
                nom_categorie = donnees.get("nom_categorie_%d" % index, None)
                categorie_tarif = CategorieTarif.objects.create(activite=donnees["activite"], nom=nom_categorie)
                donnees["liste_categories"].append(categorie_tarif)

        return donnees

    def Enregistrement_lignes_tarifs(self, index_categorie=None, tarif=None, donnees={}):
        # Enregistrement des lignes de tarifs
        for index_ligne, dict_ligne in enumerate(donnees.get("tarifs_lignes_data_resultats_%d" % index_categorie, []), 0):
            if dict_ligne:
                data_dict = {
                    "activite": donnees["activite"],
                    "tarif": tarif,
                    "code": donnees["methode_tarif_%d" % index_categorie],
                    "num_ligne": index_ligne,
                }
                data_dict.update(dict_ligne)
                ligne = TarifLigne(**data_dict)
                ligne.save()

    def Enregistrement_combi_tarifs(self, liste_combi_tarifs=[], tarif=None):
        # Enregistrement des combinaisons de tarifs
        for dict_combi in liste_combi_tarifs:
            combi_tarifs = CombiTarif.objects.create(tarif=tarif, type=dict_combi["type"])
            for unite in dict_combi["unites"]:
                combi_tarifs.unites.add(unite)



class Liste(CustomView, TemplateView):
    menu_code = "activites_liste"
    template_name = "parametrage/activites_assistant_liste.html"

    def get_context_data(self, **kwargs):
        context = super(Liste, self).get_context_data(**kwargs)
        context['page_titre'] = "Activités"
        context['box_titre'] = "Assistant de paramétrage"
        context['box_introduction'] = "Cliquez sur un assistant de paramétrage dans la liste ci-dessous."
        context['liste_assistants'] = [
            {"label": "Un séjour", "url": "activites_assistant_sejour", "icone": "fa-hotel", "description": "Assistant pour créer un séjour, un camp, une colo...", "disponible": True},
            {"label": "Une activité culturelle ou sportive annuelle", "url": "activites_assistant_annuelle", "icone": "fa-soccer-ball-o", "description": "Assistant pour créer une activité annuelle: club de gym, danse, couture, etc...", "disponible": False},
            {"label": "Un stage", "url": "activites_assistant_stage", "icone": "fa-music", "description": "Assistant pour créer un stage de théâtre, de danse, de guitare, etc...", "disponible": False},
            {"label": "Une cantine", "url": "activites_assistant_cantine", "icone": "fa-cutlery", "description": "Assistant pour créer une cantine avec un ou plusieurs services.", "disponible": False},
            {"label": "Des sorties familiales", "url": "activites_assistant_sorties", "icone": "fa-bus", "description": "Assistant pour créer une activité de gestion de sorties familiales", "disponible": False},
        ]
        return context