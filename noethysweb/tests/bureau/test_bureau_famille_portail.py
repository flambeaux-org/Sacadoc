"""The "Portail" tab of the fiche famille: the director manages the family's portal account.

Each setting is checked end-to-end on the portal side (login, réservations page),
not only in the database.
"""

import pytest
from core.models import Utilisateur
from django.contrib.auth import authenticate
from django.test import Client
from django.urls import reverse
from tests.bureau.conftest import AJAX, build_form_data


def assert_redirect(response):
    if response.status_code == 200 and response.context and "form" in response.context:
        pytest.fail("Form invalide : %s" % response.context["form"].errors.as_json())
    assert response.status_code in (302, 303), response.status_code


@pytest.fixture
def compte(famille_bureau):
    """The family with known portal credentials (as Creer_famille would have set them)."""
    famille, titulaire, enfant = famille_bureau
    user = famille.utilisateur
    famille.internet_actif = True
    famille.internet_identifiant = user.username
    famille.internet_mdp = "MotDePasse1"
    famille.save()
    user.set_password("MotDePasse1")
    user.save()
    return famille, titulaire, enfant


def _modifier(client, famille, **overrides):
    url = reverse("famille_portail_modifier", args=[famille.pk])
    form = client.get(url).context["form"]
    data = build_form_data(form, idfamille=famille.pk, **overrides)
    data.setdefault("internet_actif", "on")
    if data.get("internet_actif") is False:
        del data["internet_actif"]
    if data.get("internet_reservations") is False:
        del data["internet_reservations"]
    return client.post(url, data)


def _peut_se_connecter(identifiant, mdp):
    return authenticate(username=identifiant, password=mdp) is not None


def _portail_client(famille):
    client = Client()
    client.force_login(Utilisateur.objects.get(pk=famille.utilisateur_id))
    return client


@pytest.mark.django_db
class TestCompteInternet:
    def test_consulter_affiche_les_codes(self, directeur_client, compte):
        famille, _t, _e = compte
        response = directeur_client.get(reverse("famille_portail", args=[famille.pk]))
        assert response.status_code == 200
        assert response.context["form"].initial["internet_identifiant"] == famille.internet_identifiant
        # A superuser director gets a direct "log in as this family" link
        assert response.context["login_link"]

    def test_desactiver_le_compte_bloque_la_connexion(self, directeur_client, compte):
        famille, _t, _e = compte
        assert _peut_se_connecter(famille.internet_identifiant, "MotDePasse1")

        assert_redirect(_modifier(directeur_client, famille, internet_actif=False))
        famille.refresh_from_db()
        assert not famille.internet_actif
        assert not famille.utilisateur.is_active
        assert not _peut_se_connecter(famille.internet_identifiant, "MotDePasse1")

    def test_reactiver_le_compte(self, directeur_client, compte):
        famille, _t, _e = compte
        _modifier(directeur_client, famille, internet_actif=False)
        assert_redirect(_modifier(directeur_client, famille, internet_actif="on"))
        assert _peut_se_connecter(famille.internet_identifiant, "MotDePasse1")

    def test_changer_le_mot_de_passe(self, directeur_client, compte):
        famille, _t, _e = compte
        assert_redirect(_modifier(directeur_client, famille, internet_mdp="NouveauMdp9"))
        famille.refresh_from_db()
        user = famille.utilisateur
        assert famille.internet_mdp == "NouveauMdp9"
        assert user.force_reset_password, "the family must choose its own password at next login"
        assert _peut_se_connecter(famille.internet_identifiant, "NouveauMdp9")
        assert not _peut_se_connecter(famille.internet_identifiant, "MotDePasse1")

    def test_mot_de_passe_inchange_ne_force_pas_de_reinitialisation(self, directeur_client, compte):
        famille, _t, _e = compte
        assert_redirect(_modifier(directeur_client, famille))
        famille.refresh_from_db()
        assert not famille.utilisateur.force_reset_password
        assert _peut_se_connecter(famille.internet_identifiant, "MotDePasse1")

    def test_changer_l_identifiant(self, directeur_client, compte):
        famille, _t, _e = compte
        assert_redirect(_modifier(directeur_client, famille, internet_identifiant="F999123"))
        famille.refresh_from_db()
        assert famille.internet_identifiant == "F999123"
        assert famille.utilisateur.username == "F999123"
        assert _peut_se_connecter("F999123", "MotDePasse1")

    def test_identifiant_deja_attribue_refuse(self, directeur_client, compte, other_famille_bureau):
        famille, _t, _e = compte
        ancien = famille.internet_identifiant
        pris = other_famille_bureau.utilisateur.username.upper()  # check is case-insensitive
        response = _modifier(directeur_client, famille, internet_identifiant=pris)
        assert response.status_code == 200
        assert any("déjà été attribué" in str(m) for m in response.context["messages"])
        famille.refresh_from_db()
        assert famille.internet_identifiant == ancien
        assert famille.utilisateur.username == ancien


@pytest.fixture
def other_famille_bureau(db, organisateur):
    from tests.unit.factories import create_famille_complete

    _user, famille, _ratt = create_famille_complete(username="autre_famille")
    return famille


@pytest.mark.django_db
class TestImpactSurLePortail:
    def _individus_reservables(self, famille):
        response = _portail_client(famille).get(reverse("portail_reservations"))
        assert response.status_code == 200
        return response.context["liste_individus"]

    def test_l_enfant_inscrit_est_reservable_par_defaut(self, compte):
        famille, _t, enfant = compte
        assert enfant in self._individus_reservables(famille)

    def test_masquer_un_membre_le_retire_du_portail(self, directeur_client, compte):
        famille, _t, enfant = compte
        assert_redirect(_modifier(directeur_client, famille, individus_masques=[enfant.pk]))
        assert list(famille.individus_masques.all()) == [enfant]
        assert enfant not in self._individus_reservables(famille)

    def test_seuls_les_membres_de_la_famille_sont_masquables(self, directeur_client, compte, other_famille_bureau):
        famille, titulaire, enfant = compte
        url = reverse("famille_portail_modifier", args=[famille.pk])
        queryset = directeur_client.get(url).context["form"].fields["individus_masques"].queryset
        assert set(queryset) == {titulaire, enfant}

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the Portail tab displays the 'internet_reservations' checkbox but "
        "famille_portail.Modifier.post() copies every field except this one, so the director "
        "cannot forbid portal reservations from here."
    ))
    def test_interdire_les_reservations(self, directeur_client, compte):
        famille, _t, enfant = compte
        assert_redirect(_modifier(directeur_client, famille, internet_reservations=False))
        famille.refresh_from_db()
        assert not famille.internet_reservations
        assert self._individus_reservables(famille) == []


@pytest.mark.django_db
class TestAjaxCodes:
    def test_regenerer_identifiant_propose_un_identifiant_famille(self, directeur_client, compte):
        famille, _t, _e = compte
        ancien = famille.internet_identifiant
        response = directeur_client.post(reverse("ajax_regenerer_identifiant"), {"idfamille": famille.pk}, **AJAX)
        assert response.json()["identifiant"].startswith("F")
        # Only a proposal: nothing changes until the form is saved
        famille.refresh_from_db()
        assert famille.internet_identifiant == ancien
        assert famille.utilisateur.username == ancien

    def test_regenerer_mdp_propose_un_mot_de_passe(self, directeur_client, compte):
        famille, _t, _e = compte
        response = directeur_client.post(reverse("ajax_regenerer_mdp"), {}, **AJAX)
        mdp = response.json()["mdp"]
        assert len(mdp) == 10
        assert _peut_se_connecter(famille.internet_identifiant, "MotDePasse1")

    def test_envoyer_codes_prepare_les_champs_de_fusion(self, directeur_client, compte):
        famille, _t, _e = compte
        response = directeur_client.post(
            reverse("ajax_codes_internet_envoyer"),
            {"idfamille": famille.pk, "internet_identifiant": "F1", "internet_mdp": "abc"},
            **AJAX,
        )
        data = response.json()
        assert data["idfamille"] == famille.pk
        assert data["champs"]["{IDENTIFIANT_INTERNET}"] == "F1"
        assert data["champs"]["{MOTDEPASSE_INTERNET}"] == "abc"
        assert data["champs"]["{NOM_FAMILLE}"] == famille.nom
