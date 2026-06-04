import logging
from datetime import datetime

from django.views.generic import TemplateView

from core.models import (
    CATEGORIE_RATTACHEMENT_ADULTE,
    Famille,
    Individu,
    Rattachement,
)
from core.utils import utils_questionnaires
from core.validators import validate_email_domain_mx
from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Div, HTML, Fieldset
from crispy_forms.bootstrap import Field
from portail.views.base import CustomView

logger = logging.getLogger(__name__)


# Widget personnalisé pour le portail qui évite les conflits avec plusieurs widgets sur la même page
from core.widgets import Select_many_avec_plus


class PortailSelectManyAvecPlusParent(Select_many_avec_plus):
    template_name = "portail/widgets/select_many_avec_plus.html"


class IndividuForm(forms.ModelForm):
    prenom = forms.CharField(max_length=200, required=True, label="Prénom")
    nom = forms.CharField(max_length=200, required=False, label="Nom")
    date_naiss = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Date de naissance",
    )

    # Coordonnées
    rue_resid = forms.CharField(
        required=False, label="Rue", widget=forms.Textarea(attrs={"rows": 2})
    )
    cp_resid = forms.CharField(required=False, label="Code postal", max_length=50)
    ville_resid = forms.CharField(required=False, label="Ville", max_length=200)
    tel_domicile = forms.CharField(
        required=False, label="Téléphone domicile", max_length=100
    )
    tel_mobile = forms.CharField(
        required=False, label="Téléphone portable", max_length=100
    )
    mail = forms.EmailField(required=False, label="Email personnel", max_length=300, validators=[validate_email_domain_mx])

    # Numéro de sécurité sociale
    secu = forms.CharField(
        required=False,
        label="Numéro de sécurité sociale",
        max_length=15,
        help_text="15 chiffres (optionnel)",
    )

    class Meta:
        model = Individu
        fields = [
            "civilite",
            "prenom",
            "nom",
            "date_naiss",
            "rue_resid",
            "cp_resid",
            "ville_resid",
            "tel_domicile",
            "tel_mobile",
            "mail",
            "secu",
        ]
        labels = {
            "civilite": "Civilité",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Configuration de crispy forms
        self.helper = FormHelper()
        self.helper.form_id = "famille_parent_form"
        self.helper.form_method = "post"
        self.helper.form_class = "form-horizontal"
        self.helper.label_class = "col-md-3 col-form-label"
        self.helper.field_class = "col-md-9"

        self.helper.layout = Layout(
            Fieldset(
                "Informations générales",
                Field("civilite"),
                Field("prenom"),
                Field("nom"),
                Field("date_naiss"),
            ),
            Fieldset(
                "Coordonnées",
                Field("rue_resid"),
                Field("cp_resid"),
                Field("ville_resid"),
                Field("tel_domicile"),
                Field("tel_mobile"),
                Field("mail"),
            ),
            Fieldset(
                "Informations complémentaires (optionnel)",
                Field("secu"),
            ),
            Div(
                HTML('<div class="col-md-9 offset-md-3">'),
                Submit("submit", "Enregistrer", css_class="btn btn-primary"),
                HTML(
                    '<a href="{% url \'portail_renseignements\' %}" class="btn btn-secondary ml-2">Annuler</a>'
                ),
                HTML("</div>"),
                css_class="form-group row",
            ),
        )

    def save_individu(self, famille: Famille):
        # Sauvegarde de l'objet Individu en base de données
        individu = super().save(commit=False)
        individu.statut = Individu.STATUT_PARENT
        individu.save()

        # Sauvegarde des relations many-to-many
        self.save_m2m()

        # Création des questionnaires de type individu
        utils_questionnaires.Creation_reponses(
            categorie="individu", liste_instances=[individu]
        )

        # Pas de rattachement d'adresse pour les parents, ils ont leur propre adresse

        # Sauvegarde du rattachement
        rattachement = Rattachement(
            famille=famille,
            individu=individu,
            categorie=CATEGORIE_RATTACHEMENT_ADULTE,
            titulaire=True,
            certification_date=datetime.now(),
        )
        rattachement.save()
        individu.Maj_infos()

        return individu


class AjouterParent(CustomView, TemplateView):
    template_name = "portail/famille_parent.html"
    menu_code = "portail_renseignements"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_titre"] = "Ajouter un parent"

        # Le breadcrumb est déjà fourni par CustomView, on peut le compléter si besoin
        if "breadcrumb" in context and context["breadcrumb"]:
            context["breadcrumb"].append(
                {"titre": "Ajouter un parent", "url": "", "code": ""}
            )

        if self.request.method == "POST":
            context["form"] = IndividuForm(self.request.POST)
        else:
            context["form"] = IndividuForm()

        return context

    def post(self, request, *args, **kwargs):
        form = IndividuForm(request.POST)
        logger.debug(f"Données soumises: {request.POST}")

        if form.is_valid():
            famille = request.user.famille
            logger.debug(f"Famille: {famille}")
            individu = form.save_individu(famille)
            logger.debug(f"Individu enregistré: {individu}")

            from django.contrib import messages

            messages.success(
                request, f"Le parent {individu.Get_nom()} a été ajouté avec succès."
            )

            from django.shortcuts import redirect

            return redirect("portail_renseignements")

        # Si le formulaire n'est pas valide, on réaffiche la page avec les erreurs
        context = self.get_context_data()
        context["form"] = form
        return self.render_to_response(context)


# Vue fonction pour compatibilité avec urls.py
ajout = AjouterParent.as_view()
