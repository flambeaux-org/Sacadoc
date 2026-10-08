from django import forms
from django.contrib.auth.forms import SetPasswordForm
from django.utils.translation import gettext_lazy as _
from turnstile.fields import TurnstileField

from core.data import data_civilites
from core.models import Utilisateur
from core.validators import validate_email_domain_mx


class InscriptionFamilleForm(SetPasswordForm):
    civilite = forms.ChoiceField(
        label=_("Civilité"),
        choices=data_civilites.GetListeCivilitesByCategory("ADULTE"),
    )
    nom = forms.CharField(label=_("Nom"), max_length=200)
    prenom = forms.CharField(label=_("Prénom"), max_length=200)
    mail = forms.EmailField(
        label=_("Email personnel"),
        max_length=300,
        validators=[validate_email_domain_mx],
    )
    turnstile = TurnstileField()
    field_order = (
        "civilite",
        "nom",
        "prenom",
        "mail",
        "new_password1",
        "new_password2",
        "turnstile",
    )

    def __init__(self, *args, **kwargs):
        # First None arg is for user
        super().__init__(None, *args, **kwargs)

        for name, field in self.fields.items():
            if not field.widget.is_hidden and name != "turnstile":
                field.widget.attrs["class"] = "form-control"
                field.widget.attrs["placeholder"] = field.label

            if name == "nom":
                field.widget.attrs["autocomplete"] = "family-name"
            elif name == "prenom":
                field.widget.attrs["autocomplete"] = "given-name"
            elif name == "mail":
                field.widget.attrs["autocomplete"] = "email"

    def clean_new_password2(self):
        # Simulate user because super().clean_new_password2() uses it
        self.user = Utilisateur(
            last_name=self.cleaned_data.get("nom"),
            first_name=self.cleaned_data.get("prenom"),
            email=self.cleaned_data.get("mail"),
        )
        try:
            password = super().clean_new_password2()
        finally:
            self.user = None
        return password
