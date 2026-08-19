# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

from django import forms
from django.forms import ModelForm
from core.forms.base import FormulaireBase
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Fieldset
from crispy_forms.bootstrap import Field
from core.utils.utils_commandes import Commandes
from core.models import Activite, TypePiece, TypeCotisation, TypeConsentement
from core.forms.select2 import Select2MultipleWidget
from django.db.models import Q, F
from django.urls import reverse
from crispy_forms.layout import HTML


def Get_label_piece(piece):
    """ Met en avant les pièces standard définies par l'organisateur (sans structure), suggérées pour toutes les activités """
    return "★ %s (Organisateur)" % piece.nom if piece.structure_id is None else piece.nom


class Formulaire(FormulaireBase, ModelForm):
    class Meta:
        model = Activite
        fields = ["pieces", "cotisations", "vaccins_obligatoires", "assurance_obligatoire", "types_consentements"]
        widgets = {
            "pieces": Select2MultipleWidget(),
            "cotisations": Select2MultipleWidget(),
            "types_consentements": Select2MultipleWidget(),
         }

    def __init__(self, *args, **kwargs):
        super(Formulaire, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = 'activites_renseignements_form'
        self.helper.form_method = 'post'

        self.helper.form_class = 'form-horizontal'
        self.helper.label_class = 'col-md-2'
        self.helper.field_class = 'col-md-10'

        self.fields['pieces'].queryset = TypePiece.objects.filter(
            Q(structure__in=self.request.user.structures.all()) | Q(structure__isnull=True)
        ).order_by(F("structure_id").asc(nulls_first=True), "nom")
        self.fields['pieces'].label_from_instance = Get_label_piece

        # Création des boutons de commande
        if self.mode == "CONSULTATION":
            commandes = Commandes(modifier_url="activites_renseignements_modifier", modifier_args="idactivite=activite.idactivite", modifier=True, enregistrer=False, annuler=False, ajouter=False)
            self.Set_mode_consultation()
        else:
            commandes = Commandes(annuler_url="{% url 'activites_renseignements' idactivite=activite.idactivite %}", ajouter=False)

        config_url = reverse("types_pieces_ajouter")  # ou utilisez reverse("nom_de_la_vue")
        config_bouton = HTML(f'''
            <div class="form-group row">
                <div class="col-md-10 offset-md-2">
                    <a href="{config_url}" class="btn btn-warning" target="_blank">
                        <i class="fa fa-cog"></i> Configuration d'une nouvelle pièce
                    </a>
                </div>
            </div>
        ''')

        # Affichage
        self.helper.layout = Layout(
            commandes,

            Fieldset("Pièces à fournir par la famille",
                Field("pieces"),
                     config_bouton,

                     ),
            #Fieldset("Adhésions à jour",
            #    Field("cotisations"),
            #),
            #Fieldset("Consentements internet nécessaires",
            #    Field("types_consentements"),
            #),
            Fieldset("Vaccinations",
                Field("vaccins_obligatoires"),
            ),
            #Fieldset("Assurances",
            #    Field("assurance_obligatoire"),
            #),
        )
