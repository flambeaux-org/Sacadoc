"""Functional CRUD tests for an individual sub-resource (emergency contacts).

Covers add (POST creates) and delete (POST removes) through the Onglet-based
CRUD views, which also enforce the cross-family ownership check.
"""

import pytest
from django.db.models.fields.files import FieldFile
from django.urls import reverse

from core.models import ContactUrgence


def build_form_data(form, **overrides):
    data = {}
    for name in form.fields:
        val = form.initial.get(name, form.fields[name].initial)
        if val is None or isinstance(val, FieldFile) or hasattr(val, "read"):
            continue
        data[name] = val.isoformat() if hasattr(val, "isoformat") else val
    data.update(overrides)
    return data


@pytest.mark.django_db
class TestContactsCrud:
    def test_add_contact(self, logged_client, famille_user):
        _user, famille, ratt = famille_user
        enfant = ratt[1].individu
        url = reverse("portail_individu_contacts_ajouter", kwargs={"idrattachement": ratt[1].pk})

        form = logged_client.get(url).context["form"]
        data = build_form_data(
            form, nom="Mamie", prenom="Jeanne", lien="Grand-mère",
            famille=famille.pk, individu=enfant.pk,
        )
        response = logged_client.post(url, data)

        assert response.status_code == 302
        assert ContactUrgence.objects.filter(
            individu=enfant, famille=famille, nom="Mamie"
        ).exists()

    def test_delete_contact(self, logged_client, famille_user):
        _user, famille, ratt = famille_user
        enfant = ratt[1].individu
        contact = ContactUrgence.objects.create(
            individu=enfant, famille=famille, nom="ASupprimer", prenom="Test"
        )
        url = reverse(
            "portail_individu_contacts_supprimer",
            kwargs={"idrattachement": ratt[1].pk, "idcontact": contact.pk},
        )
        response = logged_client.post(url)
        assert response.status_code == 302
        assert not ContactUrgence.objects.filter(pk=contact.pk).exists()
