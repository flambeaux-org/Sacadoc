"""Helpers shared by the questionnaire and formulaire (sondage) end-to-end tests."""

import datetime
from decimal import Decimal

from core.models import QuestionnaireQuestion, Utilisateur
from django import forms
from django.test import Client
from django.urls import reverse

# For each answer type: (choices typed by the staff, value posted by the family,
#                        value expected in the database, value the user sees back in the form;
#                        for lists: the options shown as selected)
CAS = {
    "bloc_texte": (None, "Allergique au pollen", "Allergique au pollen", "Allergique au pollen"),
    "entier": (None, "12", "12", 12),
    "decimal": (None, "1.75", "1.75", Decimal("1.75")),
    "montant": (None, "35.50", "35.50", Decimal("35.50")),
    "liste_deroulante": ("Petit;Moyen;Grand", "Moyen", "Moyen", ["Moyen"]),
    "liste_coches": ("Piscine;Vélo;Escalade", ["Piscine", "Escalade"], "Piscine;Escalade", ["Piscine", "Escalade"]),
    "liste_coches_ouinon": (None, ["Oui"], "Oui", ["Oui"]),
    "date": (None, "2026-05-01", "2026-05-01", datetime.date(2026, 5, 1)),
}


def affiche(champ):
    """The value the user sees in a pre-filled field (selected options for a list)."""
    if isinstance(champ, forms.ChoiceField):
        valeurs = champ.widget.format_value(champ.initial)
        selection = [str(v) for v, _label in champ.choices if v not in (None, "") and str(v) in valeurs]
        multiple = isinstance(champ, forms.MultipleChoiceField)
        return selection if multiple else selection[:1]
    if champ.initial in (None, ""):
        return None
    return champ.to_python(champ.initial if not isinstance(champ.initial, (int, Decimal)) else str(champ.initial))


def creer_question(client, structure, activite, controle, label=None, choix=None, **extra):
    """Create a question through Paramétrage > Questionnaires (the real staff form)."""
    url = reverse("questions_ajouter", kwargs={"categorie": "individu"})
    ordre = client.get(url).context["form"].fields["ordre"].initial
    data = {
        "categorie": "individu", "ordre": ordre, "label": label or "Question %s" % controle,
        "controle": controle, "choix": choix or "", "texte_aide": "",
        "structure": structure.pk, "activite": activite.pk if activite else "",
        "visible": "True", "visible_portail": "True", "visible_fiche_renseignement": "True",
    }
    data.update(extra)
    response = client.post(url, data)
    assert response.status_code == 302, response.context["form"].errors.as_json() if response.context else response
    return QuestionnaireQuestion.objects.get(label=data["label"])


def portail(famille):
    client = Client()
    client.force_login(Utilisateur.objects.get(pk=famille.utilisateur_id))
    return client


def ratt_enfant(famille, enfant):
    return famille.rattachement_set.get(individu=enfant)


def form_portail(client, rattachement, edition=False):
    name = "portail_individu_questionnaire_modifier" if edition else "portail_individu_questionnaire"
    response = client.get(reverse(name, kwargs={"idrattachement": rattachement.pk}))
    assert response.status_code == 200
    return response.context["form"]


def repondre_portail(client, rattachement, reponses):
    """Submit the portal questionnaire tab with {question: value} (other fields keep their value)."""
    form = form_portail(client, rattachement, edition=True)
    data = {}
    for name, field in form.fields.items():
        if field.initial not in (None, "", []):
            data[name] = field.initial if not isinstance(field.initial, datetime.date) else field.initial.isoformat()
    for question, valeur in reponses.items():
        data["question_%d" % question.pk] = valeur
    return client.post(reverse("portail_individu_questionnaire_modifier",
                               kwargs={"idrattachement": rattachement.pk}), data)
