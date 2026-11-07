"""Functional tests for the director's fiche individu
(/utilisateur/individus/individus/<onglet>/<idfamille>/<idindividu>).

Covers the edit-in-place onglets (identité, coordonnées, régimes alimentaires),
the CRUD onglets (notes, contacts, médical, vaccins, assurances, scolarité) and
the "importer depuis une autre fiche" actions.
"""

import datetime

import pytest
from core.models import (
    Assurance,
    Assureur,
    CategorieInformation,
    ContactUrgence,
    Ecole,
    Information,
    Note,
    RegimeAlimentaire,
    Scolarite,
    TypeVaccin,
    Vaccin,
)
from django.urls import reverse
from tests.bureau.conftest import build_form_data


def assert_redirect(response):
    """Assert a form POST succeeded (302), surfacing form errors when it did not."""
    if response.status_code == 200 and response.context and "form" in response.context:
        pytest.fail("Form invalide : %s" % response.context["form"].errors.as_json())
    assert response.status_code in (302, 303), response.status_code


def _url(name, famille, individu, **extra):
    return reverse(name, kwargs={"idfamille": famille.pk, "idindividu": individu.pk, **extra})


def _post_form(client, url, **overrides):
    data = build_form_data(client.get(url).context["form"], **overrides)
    return client.post(url, data)


@pytest.mark.django_db
class TestResumeIndividu:
    def test_resume_liste_les_activites_actuelles(self, directeur_client, famille_bureau, activite):
        famille, _t, enfant = famille_bureau
        response = directeur_client.get(_url("individu_resume", famille, enfant))
        assert response.status_code == 200
        assert activite.nom in response.context["inscriptions"]

    def test_resume_affiche_les_notes(self, directeur_client, famille_bureau, directeur):
        famille, _t, enfant = famille_bureau
        note = Note.objects.create(individu=enfant, texte="Note enfant", utilisateur=directeur,
                                   date_parution=datetime.date.today())
        response = directeur_client.get(_url("individu_resume", famille, enfant))
        assert note in list(response.context["notes"])


@pytest.mark.django_db
class TestIdentite:
    def test_consulter_est_en_lecture_seule(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        response = directeur_client.get(_url("individu_identite", famille, enfant))
        assert response.status_code == 200
        assert response.context["form"].instance == enfant

    def test_modifier_identite(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        url = _url("individu_identite_modifier", famille, enfant)
        response = _post_form(directeur_client, url, prenom="Renommé", date_naiss="2016-03-04")
        assert_redirect(response)
        assert response["Location"] == _url("individu_identite", famille, enfant)
        enfant.refresh_from_db()
        assert enfant.prenom == "Renommé"
        assert enfant.date_naiss == datetime.date(2016, 3, 4)

    def test_modifier_nom_titulaire_met_a_jour_la_famille(self, directeur_client, famille_bureau):
        """Renaming the titulaire refreshes the family's display name (Maj_infos_famille)."""
        famille, titulaire, _e = famille_bureau
        url = _url("individu_identite_modifier", famille, titulaire)
        assert_redirect(_post_form(directeur_client, url, nom="MARTIN"))
        famille.refresh_from_db()
        assert "MARTIN" in famille.nom


@pytest.mark.django_db
class TestCoordonnees:
    def test_modifier_coordonnees(self, directeur_client, famille_bureau):
        famille, titulaire, _e = famille_bureau
        url = _url("individu_coords_modifier", famille, titulaire)
        response = _post_form(
            directeur_client, url,
            type_adresse="PROPRE",
            rue_resid="1 rue des Lilas", cp_resid="75001", ville_resid="PARIS",
            tel_mobile="06.11.22.33.44", mail="titulaire@test.org",
        )
        assert_redirect(response)
        assert response["Location"] == _url("individu_coords", famille, titulaire)
        titulaire.refresh_from_db()
        assert titulaire.ville_resid == "PARIS"
        assert titulaire.mail == "titulaire@test.org"


@pytest.mark.django_db
class TestRegimesAlimentaires:
    def test_modifier_regimes(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        regime = RegimeAlimentaire.objects.create(nom="Sans porc")
        url = _url("individu_regimes_alimentaires_modifier", famille, enfant)
        response = _post_form(directeur_client, url, regimes_alimentaires=[regime.pk])
        assert_redirect(response)
        assert list(enfant.regimes_alimentaires.all()) == [regime]


@pytest.mark.django_db
class TestNotesIndividu:
    def test_crud_note(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        url = _url("individu_notes_ajouter", famille, enfant)
        assert_redirect(_post_form(directeur_client, url, individu=enfant.pk,
                                   texte="Ne fait pas la sieste", acces="tous"))
        note = Note.objects.get(individu=enfant)

        url = _url("individu_notes_modifier", famille, enfant, pk=note.pk)
        assert_redirect(_post_form(directeur_client, url, individu=enfant.pk,
                                   texte="Fait la sieste", acces="tous"))
        note.refresh_from_db()
        assert note.texte == "Fait la sieste"

        assert_redirect(directeur_client.post(_url("individu_notes_supprimer", famille, enfant, pk=note.pk)))
        assert not Note.objects.filter(pk=note.pk).exists()


@pytest.mark.django_db
class TestContacts:
    def test_crud_contact(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        url = _url("individu_contacts_ajouter", famille, enfant)
        response = _post_form(directeur_client, url, famille=famille.pk, individu=enfant.pk,
                              nom="Mamie", prenom="Jeanne", lien="Grand-mère")
        assert_redirect(response)
        assert response["Location"] == _url("individu_contacts_liste", famille, enfant)
        contact = ContactUrgence.objects.get(individu=enfant, famille=famille)

        url = _url("individu_contacts_modifier", famille, enfant, pk=contact.pk)
        assert_redirect(_post_form(directeur_client, url, famille=famille.pk,
                                   individu=enfant.pk, nom="Papi"))
        contact.refresh_from_db()
        assert contact.nom == "Papi"

        assert_redirect(directeur_client.post(_url("individu_contacts_supprimer", famille, enfant, pk=contact.pk)))
        assert not ContactUrgence.objects.filter(pk=contact.pk).exists()

    def test_contact_sans_nom_refuse(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        url = _url("individu_contacts_ajouter", famille, enfant)
        response = _post_form(directeur_client, url, famille=famille.pk, individu=enfant.pk,
                              nom="", prenom="Jeanne", lien="Tante")
        assert response.status_code == 200
        assert "nom" in response.context["form"].errors
        assert not ContactUrgence.objects.filter(individu=enfant).exists()

    def test_importer_contacts_d_un_frere(self, directeur_client, famille_bureau):
        from core.models import Rattachement
        from tests.unit.factories import IndividuFactory

        famille, _t, enfant = famille_bureau
        frere = IndividuFactory(nom="Enfant", prenom="Second")
        Rattachement.objects.create(famille=famille, individu=frere, categorie=2)
        source = ContactUrgence.objects.create(famille=famille, individu=frere, nom="Voisin",
                                               prenom="Paul", lien="Voisin")

        url = _url("individu_contacts_importer", famille, enfant)
        assert directeur_client.get(url).status_code == 200
        # The checktree widget posts the selected contact ids as "id1;id2"
        response = directeur_client.post(url, {"contacts": str(source.pk)})
        assert_redirect(response)
        assert ContactUrgence.objects.filter(individu=frere, nom="Voisin").exists()
        assert ContactUrgence.objects.filter(individu=enfant, nom="Voisin").exists()


@pytest.mark.django_db
class TestMedical:
    def test_crud_information(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        categorie = CategorieInformation.objects.create(nom="Allergies")
        url = _url("individu_informations_ajouter", famille, enfant)
        response = _post_form(directeur_client, url, individu=enfant.pk, categorie=categorie.pk,
                              intitule="Allergie aux arachides")
        assert_redirect(response)
        assert response["Location"] == _url("individu_medical_liste", famille, enfant)
        info = Information.objects.get(individu=enfant)
        assert info.intitule == "Allergie aux arachides"

        url = _url("individu_informations_modifier", famille, enfant, pk=info.pk)
        assert_redirect(_post_form(directeur_client, url, individu=enfant.pk,
                                   categorie=categorie.pk, intitule="Allergie au gluten"))
        info.refresh_from_db()
        assert info.intitule == "Allergie au gluten"

        assert_redirect(directeur_client.post(_url("individu_informations_supprimer", famille, enfant, pk=info.pk)))
        assert not Information.objects.filter(pk=info.pk).exists()

    def test_crud_vaccin(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        type_vaccin = TypeVaccin.objects.create(nom="DTP")
        url = _url("individu_vaccinations_ajouter", famille, enfant)
        assert_redirect(_post_form(directeur_client, url, individu=enfant.pk,
                                   type_vaccin=type_vaccin.pk, date="2020-05-01"))
        vaccin = Vaccin.objects.get(individu=enfant)

        url = _url("individu_vaccinations_modifier", famille, enfant, pk=vaccin.pk)
        assert_redirect(_post_form(directeur_client, url, individu=enfant.pk,
                                   type_vaccin=type_vaccin.pk, date="2021-05-01"))
        vaccin.refresh_from_db()
        assert vaccin.date == datetime.date(2021, 5, 1)

        assert_redirect(directeur_client.post(_url("individu_vaccinations_supprimer", famille, enfant, pk=vaccin.pk)))
        assert not Vaccin.objects.filter(pk=vaccin.pk).exists()

    def test_liste_medicale_affiche_les_donnees(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        categorie = CategorieInformation.objects.create(nom="Traitements")
        Information.objects.create(individu=enfant, categorie=categorie, intitule="Ventoline")
        response = directeur_client.get(_url("individu_medical_liste", famille, enfant))
        assert response.status_code == 200


@pytest.mark.django_db
class TestAssurances:
    def test_crud_assurance(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        assureur = Assureur.objects.create(nom="MAIF")
        url = _url("individu_assurances_ajouter", famille, enfant)
        assert_redirect(_post_form(directeur_client, url, famille=famille.pk, individu=enfant.pk,
                                   assureur=assureur.pk, num_contrat="C-001", date_debut="2026-01-01"))
        assurance = Assurance.objects.get(individu=enfant, famille=famille)
        assert assurance.num_contrat == "C-001"

        url = _url("individu_assurances_modifier", famille, enfant, pk=assurance.pk)
        assert_redirect(_post_form(directeur_client, url, famille=famille.pk, individu=enfant.pk,
                                   assureur=assureur.pk, num_contrat="C-002"))
        assurance.refresh_from_db()
        assert assurance.num_contrat == "C-002"

        assert_redirect(directeur_client.post(_url("individu_assurances_supprimer", famille, enfant, pk=assurance.pk)))
        assert not Assurance.objects.filter(pk=assurance.pk).exists()


@pytest.mark.django_db
class TestScolarite:
    def test_crud_scolarite(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        ecole = Ecole.objects.create(nom="École Jules Ferry")
        url = _url("individu_scolarite_ajouter", famille, enfant)
        assert_redirect(_post_form(directeur_client, url, individu=enfant.pk, ecole=ecole.pk,
                                   date_debut="2025-09-01", date_fin="2026-07-04"))
        scolarite = Scolarite.objects.get(individu=enfant)
        assert scolarite.ecole == ecole

        url = _url("individu_scolarite_modifier", famille, enfant, pk=scolarite.pk)
        assert_redirect(_post_form(directeur_client, url, individu=enfant.pk, ecole=ecole.pk,
                                   date_fin="2026-07-05"))
        scolarite.refresh_from_db()
        assert scolarite.date_fin == datetime.date(2026, 7, 5)

        assert_redirect(directeur_client.post(_url("individu_scolarite_supprimer", famille, enfant, pk=scolarite.pk)))
        assert not Scolarite.objects.filter(pk=scolarite.pk).exists()

    def test_dates_inversees_refusees(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        ecole = Ecole.objects.create(nom="École Jules Ferry")
        url = _url("individu_scolarite_ajouter", famille, enfant)
        response = _post_form(directeur_client, url, individu=enfant.pk, ecole=ecole.pk,
                              date_debut="2026-07-04", date_fin="2025-09-01")
        assert response.status_code == 200
        assert "date_fin" in response.context["form"].errors
        assert not Scolarite.objects.filter(individu=enfant).exists()
