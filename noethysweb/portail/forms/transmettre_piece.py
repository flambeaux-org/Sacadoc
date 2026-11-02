# -*- coding: utf-8 -*-
#  Copyright (c) 2019-2021 Ivan LUCAS.
#  Noethysweb, application de gestion multi-activités.
#  Distribué sous licence GNU GPL.

import datetime
from django import forms
from django.forms import ModelForm
from django.core.validators import FileExtensionValidator
from django.utils.translation import gettext_lazy as _
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Hidden, HTML
from crispy_forms.bootstrap import Field
from core.models import Piece, Rattachement, Individu
from core.utils.utils_commandes import Commandes
from portail.forms.fiche import FormulaireBase
from individus.utils import utils_pieces_manquantes


class Formulaire(FormulaireBase, ModelForm):
    # Type de pièce
    selection_piece = forms.TypedChoiceField(
        label=_("Type de document"),
        choices=[],
        required=True,
        help_text=_(
            "Sélectionnez un type de document dans la liste. Sélectionnez 'Autre type' s'il ne s'agit pas d'un document prédéfini."
        ),
    )
    choix_individu = forms.TypedChoiceField(
        label=_("Individu concerné"),
        choices=[],
        required=False,
        help_text=_(
            "Sélectionnez le nom de l'individu concerné ou la famille s'il s'agit d'un document qui concerne toute la famille."
        ),
    )
    document = forms.FileField(
        label=_("Document 1"),
        help_text=_("Sélectionnez un document à joindre (pdf, jpg ou png). Poids maximum : 25MB."),
        required=True,
        widget=forms.FileInput(attrs={'class': 'form-control-file', 'accept': '.pdf,.png,.jpg,.jpeg', "data-max-size": 25*1024*1024}),
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "png", "jpg", "jpeg"])],
    )
    document1 = forms.FileField(
        label=_("Document 2"),
        help_text=_("Sélectionnez un document à joindre (pdf, jpg ou png). Poids maximum : 25MB."),
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control-file', 'accept': '.pdf,.png,.jpg,.jpeg', "data-max-size": 25*1024*1024}),
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "png", "jpg", "jpeg"])],
    )
    document2 = forms.FileField(
        label=_("Document 3"),
        help_text=_("Sélectionnez un document à joindre (pdf, jpg ou png). Poids maximum : 25MB."),
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control-file', 'accept': '.pdf,.png,.jpg,.jpeg', "data-max-size": 25*1024*1024}),
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "png", "jpg", "jpeg"])],
    )
    document3 = forms.FileField(
        label=_("Document 4"),
        help_text=_("Sélectionnez un document à joindre (pdf, jpg ou png). Poids maximum : 25MB."),
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control-file', 'accept': '.pdf,.png,.jpg,.jpeg', "data-max-size": 25*1024*1024}),
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "png", "jpg", "jpeg"])],
    )
    document4 = forms.FileField(
        label=_("Document 5"),
        help_text=_("Sélectionnez un document à joindre (pdf, jpg ou png). Poids maximum : 25MB."),
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control-file', 'accept': '.pdf,.png,.jpg,.jpeg', "data-max-size": 25*1024*1024}),
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "png", "jpg", "jpeg"])],
    )

    class Meta:
        model = Piece
        fields = "__all__"
        widgets = {
            "observations": forms.Textarea(attrs={'rows': 3}),
        }
        labels = {
            "titre": _("Titre du document*"),
            "observations": _("Observations"),
        }
        help_texts = {
            "titre": _("Saisissez un titre pour ce document. Ex : Certificat médical de Sophie..."),
            "observations": _("Vous pouvez ajouter des observations si vous le souhaitez."),
        }

    def __init__(self, *args, **kwargs):
        super(Formulaire, self).__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_id = 'portail_transmettre_piece_form'
        self.helper.form_method = 'post'

        self.helper.form_class = 'form-horizontal'
        self.helper.label_class = 'col-md-2 col-form-label'
        self.helper.field_class = 'col-md-10'
        self.helper.use_custom_control = False

        # Pièces à fournir
        self.liste_pieces_fournir = utils_pieces_manquantes.Get_pieces_manquantes(famille=self.request.user.famille, exclure_individus=self.request.user.famille.individus_masques.all())
        self.fields['selection_piece'].choices = [(index, piece["label"]) for index, piece in enumerate(self.liste_pieces_fournir)] + [(9999, "Un autre type de pièce")]
        self.fields['selection_piece'].initial = None

        # Auteur
        if not self.instance.pk:
            self.fields["auteur"].initial = self.request.user

        # Choix de l'individu
        rattachements = Rattachement.objects.select_related("individu").filter(famille=self.request.user.famille).exclude(individu__in=self.request.user.famille.individus_masques.all()).order_by("categorie")
        self.fields['choix_individu'].choices = [(rattachement.individu_id, rattachement.individu.Get_nom()) for rattachement in rattachements]

        if self.instance.pk:  # Modify only if instance exists
            self.fields['document1'].widget = forms.HiddenInput()
            self.fields['document2'].widget = forms.HiddenInput()
            self.fields['document3'].widget = forms.HiddenInput()
            self.fields['document4'].widget = forms.HiddenInput()


        # Affichage
        self.helper.layout = Layout(
            Hidden("famille", value=self.request.user.famille.pk),
            Field("auteur", type="hidden"),
            Field('selection_piece'),
            Field('titre'),
            Field('choix_individu'),
            Field('document'),
            Field('document1'),
            Field('document2'),
            Field('document3'),
            Field('document4'),
            Field('observations'),
            HTML(EXTRA_SCRIPT),
            Commandes(enregistrer_label="<i class='fa fa-send margin-r-5'></i>%s" % _("Envoyer"), annuler_url="{% url 'portail_renseignements' %}", ajouter=False, aide=False, css_class="pull-right"),
        )

    def clean(self):
        # Type de pièce
        if int(self.cleaned_data["selection_piece"]) == 9999:
            if self.cleaned_data["titre"] in ("", None):
                self.add_error('titre', "Vous devez saisir un titre pour cette pièce !")
            piece = None
        else:
            piece = self.liste_pieces_fournir[int(self.cleaned_data["selection_piece"])]

        self.cleaned_data["type_piece"] = piece["type_piece"] if piece else None

        # 1. Détermination de l'individu
        if piece:
            # Si pièce prédéfinie
            individu = None if piece["type_piece"].public == "famille" else piece["individu"]
        else:
            # Si pièce libre
            individu = Individu.objects.get(pk=self.cleaned_data["choix_individu"]) if self.cleaned_data[
                "choix_individu"] else None

        self.cleaned_data["individu"] = individu

        # 2. Détermination AUTOMATIQUE de la famille (Sécurisation)
        # Sur le portail, la pièce est toujours rattachée à la famille connectée :
        # on évite ainsi toute pièce orpheline (sans famille).
        self.cleaned_data["famille"] = self.request.user.famille

        # Durée de validité
        self.cleaned_data["date_debut"] = datetime.date.today()
        self.cleaned_data["date_fin"] = piece["type_piece"].Get_date_fin_validite() if piece else datetime.date(2999, 1,1)

        return self.cleaned_data


EXTRA_SCRIPT = """
<script>

// Sélection pièce
function On_change_selection_piece(event) {
    $('#div_id_titre').hide();
    $('#div_id_choix_individu').hide();
    if (this.value == 9999) {
        $('#div_id_titre').show();
        $('#div_id_choix_individu').show();
    };
}
$(document).ready(function() {
    $('#id_selection_piece').change(On_change_selection_piece);
    On_change_selection_piece.call($('#id_selection_piece').get(0));
});

function On_change_document(event) {
    // Cacher tous les champs de documents
    $('#div_id_document1').hide();
    $('#div_id_document2').hide();
    $('#div_id_document3').hide();
    $('#div_id_document4').hide();

    // Afficher les champs en fonction des documents présents
    if ($('#id_document').val() !== '') {
        $('#div_id_document1').show();
        if ($('#id_document1').val() !== '') {
            $('#div_id_document2').show();
            if ($('#id_document2').val() !== '') {
                $('#div_id_document3').show();
                if ($('#id_document3').val() !== '') {
                    $('#div_id_document4').show();
                }
            }
        }
    }
}

// Appel initial pour mettre à jour l'affichage des champs de documents
$(document).ready(function() {
    On_change_document();

    // Ajouter un événement de changement pour chaque champ de document
    $('#id_document').change(On_change_document);
    $('#id_document1').change(On_change_document);
    $('#id_document2').change(On_change_document);
    $('#id_document3').change(On_change_document);
    $('#id_document4').change(On_change_document);
});

// Check for file size before submitting
$('#portail_transmettre_piece_form').submit(function(e) {
    for (const element of this.elements) {
        if (element.type === "file" && element.files.length > 0 && element.dataset.maxSize) {
            const maxSize = parseInt(element.dataset.maxSize, 10);
            if (element.files[0].size > maxSize) {
                toastr.error(`Le fichier "${element.files[0].name}" dépasse la taille maximale de ${maxSize / (1024 * 1024)}MB.`);
                return false;
            }
        }
    }
});
</script>
"""
