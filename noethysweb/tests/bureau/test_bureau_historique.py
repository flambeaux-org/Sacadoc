"""Traceability: what the director does on a fiche is recorded in the historique.

The fiche famille "Historique" tab lists the entries whose famille is this family;
each entry records who did it, what, and on which member.
"""

import datetime
from decimal import Decimal

import pytest
from core.models import ContactUrgence, Historique
from django.urls import reverse
from tests.bureau.conftest import build_form_data


def _historique_famille(client, famille):
    """Entries the director sees in the fiche famille Historique tab."""
    from django.test import RequestFactory
    from fiche_famille.views.famille_historique import Liste

    request = RequestFactory().get("/")
    request.user = client.get(reverse("famille_resume", args=[famille.pk])).wsgi_request.user
    view = Liste()
    view.setup(request, idfamille=famille.pk)
    return list(view.get_queryset())


@pytest.mark.django_db
class TestHistorique:
    def test_page_historique(self, directeur_client, famille_bureau):
        famille, _t, _e = famille_bureau
        assert directeur_client.get(reverse("famille_historique", args=[famille.pk])).status_code == 200

    def test_ajout_d_une_note_trace(self, directeur_client, directeur, famille_bureau):
        famille, _t, _e = famille_bureau
        url = reverse("famille_notes_ajouter", args=[famille.pk])
        data = build_form_data(directeur_client.get(url).context["form"], famille=famille.pk,
                               texte="Appel des parents", acces="tous")
        directeur_client.post(url, data)

        entree = Historique.objects.get(famille=famille, titre="Ajouter une note")
        assert entree.utilisateur == directeur
        assert entree in _historique_famille(directeur_client, famille)

    def test_modification_trace_les_champs_modifies(self, directeur_client, directeur, famille_bureau):
        famille, _t, _e = famille_bureau
        url = reverse("famille_divers_modifier", args=[famille.pk])
        data = build_form_data(directeur_client.get(url).context["form"], memo="Garde alternée")
        directeur_client.post(url, data)

        entree = Historique.objects.filter(famille=famille, utilisateur=directeur).latest("pk")
        assert "Garde alternée" in entree.detail

    def test_modification_sans_changement_non_tracee(self, directeur_client, famille_bureau):
        famille, _t, _e = famille_bureau
        avant = Historique.objects.count()
        url = reverse("famille_divers_modifier", args=[famille.pk])
        directeur_client.post(url, build_form_data(directeur_client.get(url).context["form"]))
        assert Historique.objects.count() == avant

    def test_modification_identite_tracee_sur_l_individu(self, directeur_client, directeur, famille_bureau):
        famille, _t, enfant = famille_bureau
        url = reverse("individu_identite_modifier", args=[famille.pk, enfant.pk])
        data = build_form_data(directeur_client.get(url).context["form"], prenom="Corrigé")
        directeur_client.post(url, data)

        entree = Historique.objects.filter(individu=enfant, utilisateur=directeur).latest("pk")
        assert "Corrigé" in entree.detail

    def test_suppression_d_un_contact_tracee(self, directeur_client, famille_bureau):
        famille, _t, enfant = famille_bureau
        contact = ContactUrgence.objects.create(famille=famille, individu=enfant, nom="Voisin", prenom="Paul",
                                                lien="Voisin")
        directeur_client.post(reverse("individu_contacts_supprimer", args=[famille.pk, enfant.pk, contact.pk]))
        entree = Historique.objects.filter(famille=famille, idobjet=contact.pk).latest("pk")
        assert entree.titre.startswith("Supprimer")
        assert entree.individu == enfant

    def test_detachement_trace(self, directeur_client, directeur, famille_bureau):
        famille, _t, enfant = famille_bureau
        enfant.inscription_set.all().delete()
        directeur_client.post(reverse("individu_detacher", args=[famille.pk, enfant.pk]))
        entree = Historique.objects.get(famille=famille, titre="Détachement d'un individu")
        assert entree.utilisateur == directeur
        assert enfant.nom in entree.detail

    def test_historique_d_une_autre_famille_non_affiche(self, directeur_client, famille_bureau, other_famille):
        famille, _t, _e = famille_bureau
        Historique.objects.create(famille=other_famille, titre="Action ailleurs")
        assert all(e.famille_id == famille.pk for e in _historique_famille(directeur_client, famille))

    @pytest.mark.xfail(strict=True, reason=(
        "À CONFIRMER: individu_inscriptions.Ajouter overrides form_valid() without calling "
        "save_historique(), so inscriptions created by a director leave no trace in the historique "
        "(every other crud.Ajouter does)."
    ))
    def test_inscription_tracee(self, directeur_client, directeur, famille_bureau, structure, set_parametre_portail):
        from core.models import CategorieTarif, NomTarif, Tarif, TarifLigne
        from tests.unit.factories import ActiviteFactory, AdresseMailFactory, GroupeFactory

        famille, _t, enfant = famille_bureau
        set_parametre_portail("connexion_adresse_exp", AdresseMailFactory(moteur="console").pk)
        activite = ActiviteFactory(structure=structure)
        groupe = GroupeFactory(activite=activite)
        categorie = CategorieTarif.objects.create(activite=activite, nom="Normal")
        tarif = Tarif.objects.create(activite=activite, date_debut=datetime.date(2026, 1, 1), description="Séjour",
                                     nom_tarif=NomTarif.objects.create(activite=activite, nom="Séjour"))
        tarif.categories_tarifs.add(categorie)
        TarifLigne.objects.create(activite=activite, tarif=tarif, montant_unique=Decimal("10"))

        url = reverse("individu_inscriptions_ajouter", args=[famille.pk, enfant.pk])
        data = build_form_data(directeur_client.get(url).context["form"], individu=enfant.pk, famille=famille.pk,
                               activite=activite.pk, groupe=groupe.pk, tarifs=[tarif.pk],
                               date_debut="2026-07-01", statut="ok")
        assert directeur_client.post(url, data).status_code == 302
        assert Historique.objects.filter(famille=famille, individu=enfant, utilisateur=directeur,
                                         classe="Inscription").exists()


@pytest.fixture
def other_famille(db, organisateur):
    from tests.unit.factories import create_famille_complete

    return create_famille_complete(username="autre_hist")[1]
