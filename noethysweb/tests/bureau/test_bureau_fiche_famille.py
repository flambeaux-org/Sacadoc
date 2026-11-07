"""Functional tests for the director's fiche famille (/utilisateur/individus/familles/...).

Covers family creation, member management (add / attach / detach / delete),
the titulaire/categorie AJAX actions, and the CRUD onglets (notes, divers,
caisse, quotients).
"""

import datetime

import pytest
from core.models import Famille, Historique, Individu, Note, Quotient, Rattachement, TypeQuotient
from django.urls import reverse
from tests.bureau.conftest import AJAX, build_form_data
from tests.unit.factories import IndividuFactory


def assert_redirect(response):
    """Assert a form POST succeeded (302), surfacing form errors when it did not."""
    if response.status_code == 200 and response.context and "form" in response.context:
        pytest.fail("Form invalide : %s" % response.context["form"].errors.as_json())
    assert response.status_code in (302, 303), response.status_code


@pytest.mark.django_db
class TestCreerFamille:
    def test_creation_famille_avec_representant(self, directeur_client):
        url = reverse("famille_ajouter")
        form = directeur_client.get(url).context["form"]
        data = build_form_data(
            form,
            idfamille=0,
            action="CREER",
            categorie="1",
            titulaire="on",
            civilite=1,
            nom="DUPOND",
            prenom="Jean",
            mail="jean.dupond@test.org",
            statut="0",
        )
        response = directeur_client.post(url, data)
        assert_redirect(response)

        individu = Individu.objects.get(nom="DUPOND", prenom="Jean")
        rattachement = Rattachement.objects.get(individu=individu)
        famille = rattachement.famille
        assert rattachement.categorie == 1 and rattachement.titulaire
        assert response["Location"] == reverse(
            "individu_resume", kwargs={"idfamille": famille.pk, "idindividu": individu.pk}
        )
        # Creating a family also creates its portail account with a forced password reset
        assert famille.utilisateur is not None
        assert famille.utilisateur.categorie == "famille"
        assert famille.utilisateur.force_reset_password
        assert famille.internet_identifiant == famille.utilisateur.username

    def test_creation_sans_nom_refusee(self, directeur_client):
        url = reverse("famille_ajouter")
        nb_familles = Famille.objects.count()
        form = directeur_client.get(url).context["form"]
        data = build_form_data(
            form, idfamille=0, action="CREER", categorie="1", civilite=1,
            nom="", prenom="Jean", mail="a@test.org", statut="0",
        )
        response = directeur_client.post(url, data)
        assert response.status_code == 200
        assert "nom" in response.context["form"].errors
        assert Famille.objects.count() == nb_familles

    def test_representant_sans_mail_refuse(self, directeur_client):
        url = reverse("famille_ajouter")
        form = directeur_client.get(url).context["form"]
        data = build_form_data(
            form, idfamille=0, action="CREER", categorie="1", civilite=1,
            nom="SANSMAIL", prenom="Paul", mail="", statut="0",
        )
        response = directeur_client.post(url, data)
        assert response.status_code == 200
        assert "mail" in response.context["form"].errors
        assert not Individu.objects.filter(nom="SANSMAIL").exists()


@pytest.mark.django_db
class TestMembresFamille:
    def _post_ajouter(self, client, famille, **overrides):
        url = reverse("individu_ajouter", args=[famille.pk])
        form = client.get(url).context["form"]
        data = build_form_data(form, idfamille=famille.pk, **overrides)
        return client.post(url, data)

    def test_ajouter_enfant(self, directeur_client, famille_bureau):
        famille, _t, _e = famille_bureau
        response = self._post_ajouter(
            directeur_client, famille, action="CREER", categorie="2",
            civilite=4, nom="Titulaire", prenom="Cadet", statut="5",
        )
        assert_redirect(response)
        rattachement = Rattachement.objects.get(famille=famille, individu__prenom="Cadet")
        assert rattachement.categorie == 2
        assert not rattachement.titulaire

    def test_rattacher_individu_existant(self, directeur_client, famille_bureau):
        famille, _t, _e = famille_bureau
        existant = IndividuFactory(nom="Externe", prenom="Contact")
        response = self._post_ajouter(
            directeur_client, famille, action="RATTACHER", categorie="3",
            individu=existant.pk, statut="0",
        )
        assert_redirect(response)
        assert response["Location"] == reverse("famille_resume", args=[famille.pk])
        assert Rattachement.objects.filter(famille=famille, individu=existant, categorie=3).exists()

    def test_rattacher_deux_fois_refuse(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        response = self._post_ajouter(
            directeur_client, famille, action="RATTACHER", categorie="2",
            individu=enfant.pk, statut="5",
        )
        assert response.status_code == 200
        assert "individu" in response.context["form"].errors
        assert Rattachement.objects.filter(famille=famille, individu=enfant).count() == 1

    def test_detacher_enfant(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        # Inscriptions are PROTECT-ed: drop the fixture one so detachment is allowed
        enfant.inscription_set.all().delete()
        url = reverse("individu_detacher", args=[famille.pk, enfant.pk])
        assert directeur_client.get(url).status_code == 200

        response = directeur_client.post(url)
        assert_redirect(response)
        assert not Rattachement.objects.filter(famille=famille, individu=enfant).exists()
        assert Individu.objects.filter(pk=enfant.pk).exists()

    def test_supprimer_enfant(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        enfant.inscription_set.all().delete()
        response = directeur_client.post(
            reverse("individu_supprimer", args=[famille.pk, enfant.pk])
        )
        assert_redirect(response)
        assert not Individu.objects.filter(pk=enfant.pk).exists()
        assert Famille.objects.filter(pk=famille.pk).exists()

    def test_supprimer_dernier_titulaire_refuse(self, directeur_client, famille_bureau):
        """The last titulaire cannot be removed while other members remain."""
        famille, titulaire, enfant = famille_bureau
        url = reverse("individu_supprimer", args=[famille.pk, titulaire.pk])
        response = directeur_client.get(url)
        assert any("dernier titulaire" in e for e in response.context["erreurs_protection"])

        directeur_client.post(url)
        assert Individu.objects.filter(pk=titulaire.pk).exists()
        assert Rattachement.objects.filter(famille=famille, individu=titulaire).exists()


@pytest.mark.django_db(transaction=True)
class TestSupprimerDernierMembre:
    """Run without the test transaction (autocommit, like production): Supprimer_individu
    triggers FK violations that production silently swallows (see the xfail below)."""

    def test_supprimer_dernier_membre_supprime_la_famille(self, directeur_client, organisateur):
        from tests.unit.factories import create_famille_complete

        _user, famille, ratt = create_famille_complete(username="solo", avec_enfant=False)
        seul = ratt[0].individu
        response = directeur_client.post(reverse("individu_supprimer", args=[famille.pk, seul.pk]))
        assert response.status_code in (302, 303)
        assert response["Location"] == reverse("famille_liste")
        assert not Famille.objects.filter(pk=famille.pk).exists()
        assert not Individu.objects.filter(pk=seul.pk).exists()


@pytest.mark.django_db
@pytest.mark.xfail(strict=True, reason=(
    "BUG: Supprimer_individu.delete() calls famille.Maj_infos() after the famille was "
    "deleted; Maj_infos() saves the instance (pk=None) and INSERTs a new ghost famille "
    "whose allocataire is the deleted individu."
))
def test_supprimer_dernier_membre_ne_recree_pas_de_famille(directeur_client, organisateur):
    from tests.unit.factories import create_famille_complete

    _user, famille, ratt = create_famille_complete(username="solo", avec_enfant=False)
    seul = ratt[0].individu
    try:
        directeur_client.post(reverse("individu_supprimer", args=[famille.pk, seul.pk]))
        assert not Famille.objects.exists()
    finally:
        # Drop the dangling rows, otherwise the deferred FK check fails at teardown
        Famille.objects.filter(allocataire_id=seul.pk).delete()


@pytest.mark.django_db
class TestAjaxRattachements:
    def test_definir_titulaire_bascule(self, directeur_client, famille_bureau):
        famille, titulaire, _e = famille_bureau
        second = IndividuFactory(nom="Second", prenom="Parent")
        ratt = Rattachement.objects.create(famille=famille, individu=second, categorie=1, titulaire=False)

        response = directeur_client.post(
            reverse("ajax_definir_titulaire"), {"idrattachement": ratt.pk}, **AJAX
        )
        assert response.json() == {"success": True}
        ratt.refresh_from_db()
        assert ratt.titulaire

    def test_definir_titulaire_refuse_dernier(self, directeur_client, famille_bureau):
        famille, titulaire, _e = famille_bureau
        ratt = Rattachement.objects.get(famille=famille, individu=titulaire)
        response = directeur_client.post(
            reverse("ajax_definir_titulaire"), {"idrattachement": ratt.pk}, **AJAX
        )
        assert response.json() == {"success": False}
        ratt.refresh_from_db()
        assert ratt.titulaire

    def test_changer_categorie_enfant_en_representant(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        ratt = Rattachement.objects.get(famille=famille, individu=enfant)
        response = directeur_client.post(
            reverse("ajax_changer_categorie"), {"idrattachement": ratt.pk, "categorie": 1}, **AJAX
        )
        assert response.json() == {"success": True}
        ratt.refresh_from_db()
        enfant.refresh_from_db()
        assert ratt.categorie == 1 and ratt.titulaire
        assert enfant.statut == 0

    def test_changer_categorie_refuse_dernier_titulaire(self, directeur_client, famille_bureau):
        famille, titulaire, _e = famille_bureau
        ratt = Rattachement.objects.get(famille=famille, individu=titulaire)
        response = directeur_client.post(
            reverse("ajax_changer_categorie"), {"idrattachement": ratt.pk, "categorie": 3}, **AJAX
        )
        assert response.json() == {"success": False}
        ratt.refresh_from_db()
        assert ratt.categorie == 1

    def test_individus_existants_signale_doublon(self, directeur_client, famille_bureau):
        _f, _t, enfant = famille_bureau
        response = directeur_client.post(
            reverse("ajax_get_individus_existants"),
            {"nom": enfant.nom, "prenom": enfant.prenom},
            **AJAX,
        )
        assert response.status_code == 200
        assert "Attention au doublon" in response.content.decode()


@pytest.mark.django_db
class TestNotesFamille:
    def test_ajouter_note(self, directeur_client, famille_bureau):
        famille, _t, _e = famille_bureau
        url = reverse("famille_notes_ajouter", args=[famille.pk])
        form = directeur_client.get(url).context["form"]
        data = build_form_data(form, famille=famille.pk, texte="Allergie signalée par téléphone", acces="tous")
        response = directeur_client.post(url, data)
        assert_redirect(response)
        assert response["Location"] == reverse("famille_resume", args=[famille.pk])
        assert Note.objects.filter(famille=famille, texte="Allergie signalée par téléphone").exists()

    def test_note_reservee_a_moi(self, directeur_client, famille_bureau, directeur):
        famille, _t, _e = famille_bureau
        url = reverse("famille_notes_ajouter", args=[famille.pk])
        data = build_form_data(directeur_client.get(url).context["form"], famille=famille.pk, texte="Perso", acces="moi")
        assert_redirect(directeur_client.post(url, data))
        assert Note.objects.get(famille=famille, texte="Perso").utilisateur == directeur

    @pytest.mark.xfail(strict=True, raises=KeyError, reason=(
        "BUG: the 'acces' field defaults to 'automatique', which is not a valid choice; "
        "submitting without picking one makes Formulaire.clean() read the missing "
        "cleaned_data['acces'] and crash with a KeyError (500) instead of a form error."
    ))
    def test_note_sans_acces_affiche_une_erreur(self, directeur_client, famille_bureau):
        famille, _t, _e = famille_bureau
        url = reverse("famille_notes_ajouter", args=[famille.pk])
        data = build_form_data(directeur_client.get(url).context["form"], famille=famille.pk, texte="X", acces="")
        response = directeur_client.post(url, data)
        assert response.status_code == 200
        assert "acces" in response.context["form"].errors

    def test_modifier_et_supprimer_note(self, directeur_client, famille_bureau, directeur):
        famille, _t, _e = famille_bureau
        note = Note.objects.create(famille=famille, texte="Ancienne", utilisateur=directeur,
                                   date_parution=datetime.date.today())
        url = reverse("famille_notes_modifier", args=[famille.pk, note.pk])
        data = build_form_data(directeur_client.get(url).context["form"], texte="Nouvelle")
        assert_redirect(directeur_client.post(url, data))
        note.refresh_from_db()
        assert note.texte == "Nouvelle"

        url = reverse("famille_notes_supprimer", args=[famille.pk, note.pk])
        assert_redirect(directeur_client.post(url))
        assert not Note.objects.filter(pk=note.pk).exists()

    def test_note_visible_sur_resume(self, directeur_client, famille_bureau, directeur):
        famille, _t, _e = famille_bureau
        note = Note.objects.create(famille=famille, texte="Visible", utilisateur=directeur,
                                   date_parution=datetime.date.today())
        response = directeur_client.get(reverse("famille_resume", args=[famille.pk]))
        assert note in list(response.context["notes"])

    def test_note_d_un_autre_utilisateur_masquee(self, directeur_client, famille_bureau):
        from tests.unit.factories import UtilisateurFactory

        famille, _t, _e = famille_bureau
        autre = UtilisateurFactory(username="collegue")
        note = Note.objects.create(famille=famille, texte="Privee", utilisateur=autre,
                                   date_parution=datetime.date.today())
        response = directeur_client.get(reverse("famille_resume", args=[famille.pk]))
        assert note not in list(response.context["notes"])


@pytest.mark.django_db
class TestOngletsEdition:
    def test_divers_modifier(self, directeur_client, famille_bureau):
        famille, _t, _e = famille_bureau
        url = reverse("famille_divers_modifier", args=[famille.pk])
        data = build_form_data(directeur_client.get(url).context["form"],
                               memo="Mémo du directeur", code_compta="411DUP")
        response = directeur_client.post(url, data)
        assert_redirect(response)
        assert response["Location"] == reverse("famille_divers", args=[famille.pk])
        famille.refresh_from_db()
        assert famille.memo == "Mémo du directeur"
        assert famille.code_compta == "411DUP"

    def test_caisse_modifier(self, directeur_client, famille_bureau):
        famille, titulaire, _e = famille_bureau
        url = reverse("famille_caisse_modifier", args=[famille.pk])
        data = build_form_data(directeur_client.get(url).context["form"],
                               num_allocataire="1234567", allocataire=titulaire.pk)
        assert_redirect(directeur_client.post(url, data))
        famille.refresh_from_db()
        assert famille.num_allocataire == "1234567"

    def test_quotients_crud(self, directeur_client, famille_bureau):
        famille, _t, _e = famille_bureau
        type_quotient = TypeQuotient.objects.create(nom="QF CAF")

        url = reverse("famille_quotients_ajouter", args=[famille.pk])
        data = build_form_data(
            directeur_client.get(url).context["form"],
            famille=famille.pk,
            type_quotient=type_quotient.pk,
            date_debut="2026-01-01",
            date_fin="2026-12-31",
            quotient=650,
        )
        assert_redirect(directeur_client.post(url, data))
        quotient = Quotient.objects.get(famille=famille)
        assert quotient.quotient == 650

        url = reverse("famille_quotients_modifier", args=[famille.pk, quotient.pk])
        data = build_form_data(directeur_client.get(url).context["form"], quotient=700)
        assert_redirect(directeur_client.post(url, data))
        quotient.refresh_from_db()
        assert quotient.quotient == 700

        url = reverse("famille_quotients_supprimer", args=[famille.pk, quotient.pk])
        assert_redirect(directeur_client.post(url))
        assert not Quotient.objects.filter(pk=quotient.pk).exists()

    def test_quotient_dates_inversees_refuse(self, directeur_client, famille_bureau):
        famille, _t, _e = famille_bureau
        type_quotient = TypeQuotient.objects.create(nom="QF CAF")
        url = reverse("famille_quotients_ajouter", args=[famille.pk])
        data = build_form_data(
            directeur_client.get(url).context["form"],
            famille=famille.pk,
            type_quotient=type_quotient.pk,
            date_debut="2026-12-31",
            date_fin="2026-01-01",
            quotient=650,
        )
        response = directeur_client.post(url, data)
        assert response.status_code == 200
        assert "date_fin" in response.context["form"].errors
        assert not Quotient.objects.filter(famille=famille).exists()


@pytest.mark.django_db(transaction=True)
class TestSupprimerFamilleAutocommit:
    """Autocommit like production — see test_suppression_famille_historique_sans_reference_morte."""

    def test_supprimer_famille_vide(self, directeur_client, organisateur):
        famille = Famille.objects.create(nom="Vide")
        response = directeur_client.post(reverse("famille_supprimer", args=[famille.pk]))
        assert_redirect(response)
        assert not Famille.objects.filter(pk=famille.pk).exists()


@pytest.mark.django_db
@pytest.mark.xfail(strict=True, reason=(
    "BUG: crud.Supprimer.delete() logs the deletion with famille_id=<deleted famille>; "
    "utils_historique.Ajouter() only nulls a missing individu, not a missing famille, so "
    "the INSERT violates the FK (swallowed + logged in production: the deletion is never "
    "recorded in the historique)."
))
def test_suppression_famille_historique_sans_reference_morte(directeur_client, organisateur):
    famille = Famille.objects.create(nom="Vide")
    pk = famille.pk
    try:
        directeur_client.post(reverse("famille_supprimer", args=[pk]))
        assert not Historique.objects.filter(famille_id=pk).exists()
    finally:
        Historique.objects.filter(famille_id=pk).delete()


@pytest.mark.django_db
class TestSupprimerFamille:
    def test_supprimer_famille_avec_inscription_bloque(self, directeur_client, famille_bureau):
        famille, _t, _e = famille_bureau
        directeur_client.post(reverse("famille_supprimer", args=[famille.pk]))
        assert Famille.objects.filter(pk=famille.pk).exists()
