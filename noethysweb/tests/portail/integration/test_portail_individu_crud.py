"""Functional CRUD tests for individual sub-resources.

Covers add, modify, delete, and importer through the Onglet-based CRUD views,
which also enforce the cross-family ownership check.
"""

import datetime

import pytest
from core.models import ContactUrgence
from django.db.models.fields.files import FieldFile
from django.urls import reverse


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
        url = reverse(
            "portail_individu_contacts_ajouter", kwargs={"idrattachement": ratt[1].pk}
        )

        form = logged_client.get(url).context["form"]
        data = build_form_data(
            form,
            nom="Mamie",
            prenom="Jeanne",
            lien="Grand-mère",
            famille=famille.pk,
            individu=enfant.pk,
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

    def test_modifier_renders(self, logged_client, famille_user):
        _user, famille, ratt = famille_user
        enfant = ratt[1].individu
        contact = ContactUrgence.objects.create(
            individu=enfant,
            famille=famille,
            nom="Original",
            prenom="Contact",
            lien="Oncle",
        )
        url = reverse(
            "portail_individu_contacts_modifier",
            kwargs={"idrattachement": ratt[1].pk, "idcontact": contact.pk},
        )
        assert logged_client.get(url).status_code == 200

    def test_modifier_saves(self, logged_client, famille_user):
        _user, famille, ratt = famille_user
        enfant = ratt[1].individu
        contact = ContactUrgence.objects.create(
            individu=enfant,
            famille=famille,
            nom="AncienNom",
            prenom="Contact",
            lien="Oncle",
        )
        url = reverse(
            "portail_individu_contacts_modifier",
            kwargs={"idrattachement": ratt[1].pk, "idcontact": contact.pk},
        )
        data = build_form_data(logged_client.get(url).context["form"], nom="NouveauNom")
        assert logged_client.post(url, data).status_code == 302
        assert ContactUrgence.objects.get(pk=contact.pk).nom == "NouveauNom"

    def test_importer_renders(self, logged_client, famille_user):
        _user, _famille, ratt = famille_user
        url = reverse(
            "portail_individu_contacts_importer",
            kwargs={"idrattachement": ratt[1].pk},
        )
        assert logged_client.get(url).status_code == 200


# ---------------------------------------------------------------------------
# Phase B: Vaccinations — modify + delete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestVaccinationCrud:
    def test_modifier_renders(self, logged_client, famille_user):
        from core.models import TypeVaccin, Vaccin

        _user, _famille, ratt = famille_user
        tv = TypeVaccin.objects.create(nom="BCG")
        vaccin = Vaccin.objects.create(
            individu=ratt[1].individu, type_vaccin=tv, date=datetime.date(2020, 6, 1)
        )
        url = reverse(
            "portail_individu_vaccinations_modifier",
            kwargs={"idrattachement": ratt[1].pk, "idvaccin": vaccin.pk},
        )
        assert logged_client.get(url).status_code == 200

    def test_modifier_saves(self, logged_client, famille_user):
        from core.models import TypeVaccin, Vaccin

        _user, _famille, ratt = famille_user
        tv = TypeVaccin.objects.create(nom="BCG")
        vaccin = Vaccin.objects.create(
            individu=ratt[1].individu, type_vaccin=tv, date=datetime.date(2020, 6, 1)
        )
        url = reverse(
            "portail_individu_vaccinations_modifier",
            kwargs={"idrattachement": ratt[1].pk, "idvaccin": vaccin.pk},
        )
        data = build_form_data(
            logged_client.get(url).context["form"], date="2021-09-01"
        )
        assert logged_client.post(url, data).status_code == 302
        assert Vaccin.objects.get(pk=vaccin.pk).date == datetime.date(2021, 9, 1)

    def test_supprimer(self, logged_client, famille_user):
        from core.models import TypeVaccin, Vaccin

        _user, _famille, ratt = famille_user
        tv = TypeVaccin.objects.create(nom="BCG")
        vaccin = Vaccin.objects.create(
            individu=ratt[1].individu, type_vaccin=tv, date=datetime.date(2020, 6, 1)
        )
        url = reverse(
            "portail_individu_vaccinations_supprimer",
            kwargs={"idrattachement": ratt[1].pk, "idvaccin": vaccin.pk},
        )
        assert logged_client.post(url).status_code == 302
        assert not Vaccin.objects.filter(pk=vaccin.pk).exists()


# ---------------------------------------------------------------------------
# Phase B: Medical informations — modify + delete
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestInformationCrud:
    def test_modifier_renders(self, logged_client, famille_user):
        from core.models import CategorieInformation, Information

        _user, _famille, ratt = famille_user
        cat = CategorieInformation.objects.create(nom="Allergie")
        info = Information.objects.create(
            individu=ratt[1].individu, categorie=cat, intitule="Original"
        )
        url = reverse(
            "portail_individu_informations_modifier",
            kwargs={"idrattachement": ratt[1].pk, "idinformation": info.pk},
        )
        assert logged_client.get(url).status_code == 200

    def test_modifier_saves(self, logged_client, famille_user):
        from core.models import CategorieInformation, Information

        _user, _famille, ratt = famille_user
        cat = CategorieInformation.objects.create(nom="Allergie")
        info = Information.objects.create(
            individu=ratt[1].individu, categorie=cat, intitule="Ancien intitulé"
        )
        url = reverse(
            "portail_individu_informations_modifier",
            kwargs={"idrattachement": ratt[1].pk, "idinformation": info.pk},
        )
        data = build_form_data(
            logged_client.get(url).context["form"], intitule="Nouvel intitulé"
        )
        assert logged_client.post(url, data).status_code == 302
        assert Information.objects.get(pk=info.pk).intitule == "Nouvel intitulé"

    def test_supprimer(self, logged_client, famille_user):
        from core.models import CategorieInformation, Information

        _user, _famille, ratt = famille_user
        cat = CategorieInformation.objects.create(nom="Allergie")
        info = Information.objects.create(
            individu=ratt[1].individu, categorie=cat, intitule="ASupprimer"
        )
        url = reverse(
            "portail_individu_informations_supprimer",
            kwargs={"idrattachement": ratt[1].pk, "idinformation": info.pk},
        )
        assert logged_client.post(url).status_code == 302
        assert not Information.objects.filter(pk=info.pk).exists()


# ---------------------------------------------------------------------------
# Phase B: Assurances — modify + delete + importer (GET smoke)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAssuranceCrud:
    def _make_assurance(self, famille_user):
        from core.models import Assurance, Assureur

        _user, famille, ratt = famille_user
        assureur = Assureur.objects.create(nom="AXA")
        assurance = Assurance.objects.create(
            individu=ratt[1].individu,
            famille=famille,
            assureur=assureur,
            num_contrat="CONTRAT-001",
            date_debut=datetime.date(2024, 1, 1),
        )
        return ratt, assurance

    def test_modifier_renders(self, logged_client, famille_user):
        ratt, assurance = self._make_assurance(famille_user)
        url = reverse(
            "portail_individu_assurances_modifier",
            kwargs={"idrattachement": ratt[1].pk, "idassurance": assurance.pk},
        )
        assert logged_client.get(url).status_code == 200

    def test_modifier_saves(self, logged_client, famille_user):
        from core.models import Assurance

        ratt, assurance = self._make_assurance(famille_user)
        url = reverse(
            "portail_individu_assurances_modifier",
            kwargs={"idrattachement": ratt[1].pk, "idassurance": assurance.pk},
        )
        data = build_form_data(
            logged_client.get(url).context["form"], num_contrat="CONTRAT-999"
        )
        assert logged_client.post(url, data).status_code == 302
        assert Assurance.objects.get(pk=assurance.pk).num_contrat == "CONTRAT-999"

    def test_supprimer(self, logged_client, famille_user):
        from core.models import Assurance

        ratt, assurance = self._make_assurance(famille_user)
        url = reverse(
            "portail_individu_assurances_supprimer",
            kwargs={"idrattachement": ratt[1].pk, "idassurance": assurance.pk},
        )
        assert logged_client.post(url).status_code == 302
        assert not Assurance.objects.filter(pk=assurance.pk).exists()

    def test_importer_renders(self, logged_client, famille_user):
        _user, _famille, ratt = famille_user
        url = reverse(
            "portail_individu_assurances_importer",
            kwargs={"idrattachement": ratt[1].pk},
        )
        assert logged_client.get(url).status_code == 200
