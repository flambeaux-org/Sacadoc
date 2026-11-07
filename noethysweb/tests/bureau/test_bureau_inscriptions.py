"""Inscriptions managed by the director from the fiche individu.

Business rules under test:
- inscribing a child on an activity bills one prestation per selected tarif
  (montant_unique) and the amount shows up in the family's balance;
- an individual cannot be inscribed twice on the same activity over overlapping
  periods (unless the activity allows multiple inscriptions);
- a director can only inscribe on, edit or delete inscriptions of his own structures;
- validating a portail request ("demande d'inscription") marks it VALIDE;
- an inscription cannot be deleted while prestations are attached / invoiced.
"""

import datetime
from decimal import Decimal

import pytest
from core.models import (
    CategorieTarif,
    Facture,
    NomTarif,
    Inscription,
    PortailRenseignement,
    Prestation,
    Tarif,
    TarifLigne,
)
from django.urls import reverse
from tests.bureau.conftest import build_form_data
from tests.unit.factories import ActiviteFactory, GroupeFactory, StructureFactory


def assert_redirect(response):
    if response.status_code == 200 and response.context and "form" in response.context:
        pytest.fail("Form invalide : %s" % response.context["form"].errors.as_json())
    assert response.status_code in (302, 303), response.status_code


def _messages(response):
    return [str(m) for m in response.context["messages"]]


def _tarif(activite, description="Tarif"):
    nom = NomTarif.objects.create(activite=activite, nom=description)
    return Tarif.objects.create(activite=activite, nom_tarif=nom, date_debut=datetime.date(2026, 1, 1),
                                description=description)


@pytest.fixture
def camp(db, structure):
    """An activity of the director's structure with one group and one 120 € tarif."""
    activite = ActiviteFactory(structure=structure, nom="Camp d'été")
    groupe = GroupeFactory(activite=activite, nom="Louveteaux")
    categorie = CategorieTarif.objects.create(activite=activite, nom="Normal")
    tarif = _tarif(activite, description="Séjour complet")
    tarif.categories_tarifs.add(categorie)
    TarifLigne.objects.create(activite=activite, tarif=tarif, montant_unique=Decimal("120"))
    return activite, groupe, tarif


@pytest.fixture
def adresse_expedition(db, set_parametre_portail):
    """Configure the sender address used by the inscription confirmation email."""
    from tests.unit.factories import AdresseMailFactory

    adresse = AdresseMailFactory(adresse="noreply@sacadoc.test", moteur="console")
    set_parametre_portail("connexion_adresse_exp", adresse.pk)
    return adresse


@pytest.fixture
def mail_outbox(monkeypatch):
    """The confirmation email opens its own connection (console/smtp...); route it to locmem."""
    from django.core import mail
    from fiche_individu.forms import individu_inscriptions

    real_get_connection = mail.get_connection
    monkeypatch.setattr(
        individu_inscriptions.djangomail, "get_connection",
        lambda *args, **kwargs: real_get_connection("django.core.mail.backends.locmem.EmailBackend"),
    )
    mail.outbox = []
    return mail.outbox


@pytest.fixture
def enfant_sans_inscription(famille_bureau, adresse_expedition, mail_outbox):
    famille, _t, enfant = famille_bureau
    famille.mail = "parents@test.org"
    famille.save()
    return famille, enfant


def _url_ajouter(famille, individu):
    return reverse("individu_inscriptions_ajouter", kwargs={"idfamille": famille.pk, "idindividu": individu.pk})


def _post_inscription(client, famille, individu, activite, groupe, tarifs, url=None, **overrides):
    url = url or _url_ajouter(famille, individu)
    form = client.get(url).context["form"]
    data = build_form_data(
        form,
        individu=individu.pk,
        famille=famille.pk,
        activite=activite.pk,
        groupe=groupe.pk,
        tarifs=[t.pk for t in tarifs],
        date_debut="2026-07-01",
        statut="ok",
        **overrides,
    )
    return client.post(url, data)


@pytest.mark.django_db
class TestAjouterInscription:
    def test_seules_les_activites_de_mes_structures_sont_proposees(
        self, directeur_client, enfant_sans_inscription, camp
    ):
        famille, enfant = enfant_sans_inscription
        autre = ActiviteFactory(structure=StructureFactory(), nom="Activité voisine")
        queryset = directeur_client.get(_url_ajouter(famille, enfant)).context["form"].fields["activite"].queryset
        assert camp[0] in queryset
        assert autre not in queryset

    def test_inscription_cree_la_prestation_du_tarif(self, directeur_client, enfant_sans_inscription, camp):
        famille, enfant = enfant_sans_inscription
        activite, groupe, tarif = camp
        response = _post_inscription(directeur_client, famille, enfant, activite, groupe, [tarif])
        assert_redirect(response)
        assert response["Location"] == reverse(
            "individu_inscriptions_liste", kwargs={"idfamille": famille.pk, "idindividu": enfant.pk}
        )

        inscription = Inscription.objects.get(individu=enfant, activite=activite)
        assert inscription.famille == famille
        assert inscription.groupe == groupe
        assert inscription.categorie_tarif.nom == "Normal"

        prestation = Prestation.objects.get(famille=famille, individu=enfant, activite=activite)
        assert prestation.tarif == tarif
        assert prestation.montant == Decimal("120")
        assert prestation.label == "Séjour complet"

    def test_email_de_confirmation_envoye_a_la_famille(
        self, directeur_client, enfant_sans_inscription, camp, mail_outbox
    ):
        famille, enfant = enfant_sans_inscription
        activite, groupe, tarif = camp
        assert_redirect(_post_inscription(directeur_client, famille, enfant, activite, groupe, [tarif]))
        assert len(mail_outbox) == 1
        email = mail_outbox[0]
        assert email.to == ["parents@test.org"]
        assert email.from_email == "noreply@sacadoc.test"
        assert email.subject == "Confirmation d'inscription"
        assert enfant.prenom in email.body and activite.nom in email.body

    def test_pas_d_email_quand_l_inscription_est_refusee(
        self, directeur_client, enfant_sans_inscription, camp, mail_outbox
    ):
        famille, enfant = enfant_sans_inscription
        activite, groupe, tarif = camp
        _post_inscription(directeur_client, famille, enfant, activite, groupe, [tarif], date_fin="2026-06-01")
        assert mail_outbox == []

    def test_la_prestation_apparait_dans_le_solde_famille(self, directeur_client, enfant_sans_inscription, camp):
        famille, enfant = enfant_sans_inscription
        activite, groupe, tarif = camp
        assert_redirect(_post_inscription(directeur_client, famille, enfant, activite, groupe, [tarif]))

        resume = directeur_client.get(reverse("famille_resume", args=[famille.pk]))
        assert resume.context["solde"] == Decimal("120")
        assert resume.context["solde_famille"] == Decimal("120")
        assert activite.nom in "".join(resume.context["inscriptions_actuelles"][enfant.pk])

    def test_inscription_sur_periode_chevauchante_refusee(self, directeur_client, enfant_sans_inscription, camp):
        famille, enfant = enfant_sans_inscription
        activite, groupe, tarif = camp
        Inscription.objects.create(famille=famille, individu=enfant, activite=activite, groupe=groupe,
                                   date_debut=datetime.date(2026, 6, 1))

        response = _post_inscription(directeur_client, famille, enfant, activite, groupe, [tarif])
        assert response.status_code == 200
        assert any("déjà inscrit" in m for m in _messages(response))
        assert Inscription.objects.filter(individu=enfant, activite=activite).count() == 1
        assert not Prestation.objects.filter(individu=enfant, activite=activite).exists()

    def test_inscription_apres_une_inscription_terminee_acceptee(self, directeur_client, enfant_sans_inscription, camp):
        famille, enfant = enfant_sans_inscription
        activite, groupe, tarif = camp
        Inscription.objects.create(famille=famille, individu=enfant, activite=activite, groupe=groupe,
                                   date_debut=datetime.date(2025, 1, 1), date_fin=datetime.date(2025, 12, 31))

        assert_redirect(_post_inscription(directeur_client, famille, enfant, activite, groupe, [tarif]))
        assert Inscription.objects.filter(individu=enfant, activite=activite).count() == 2

    def test_inscriptions_multiples_autorisees_par_l_activite(self, directeur_client, enfant_sans_inscription, camp):
        famille, enfant = enfant_sans_inscription
        activite, groupe, tarif = camp
        activite.inscriptions_multiples = True
        activite.save()
        Inscription.objects.create(famille=famille, individu=enfant, activite=activite, groupe=groupe,
                                   date_debut=datetime.date(2026, 6, 1))

        assert_redirect(_post_inscription(directeur_client, famille, enfant, activite, groupe, [tarif]))
        assert Inscription.objects.filter(individu=enfant, activite=activite).count() == 2

    def test_date_fin_avant_date_debut_refusee(self, directeur_client, enfant_sans_inscription, camp):
        famille, enfant = enfant_sans_inscription
        activite, groupe, tarif = camp
        response = _post_inscription(directeur_client, famille, enfant, activite, groupe, [tarif],
                                     date_fin="2026-06-01")
        assert response.status_code == 200
        assert "date_fin" in response.context["form"].errors
        assert not Inscription.objects.filter(individu=enfant, activite=activite).exists()

    def test_debut_apres_la_fin_de_l_activite_refuse(self, directeur_client, enfant_sans_inscription, camp):
        famille, enfant = enfant_sans_inscription
        activite, groupe, tarif = camp
        activite.date_fin = datetime.date(2026, 6, 30)
        activite.save()
        response = _post_inscription(directeur_client, famille, enfant, activite, groupe, [tarif])
        assert response.status_code == 200
        assert "date_debut" in response.context["form"].errors

    @pytest.mark.xfail(strict=True, raises=KeyError, reason=(
        "BUG: Formulaire.clean() reads cleaned_data['activite'] without checking it validated; an "
        "activity outside the director's structures (or an empty one) crashes with a KeyError (500) "
        "instead of a form error. No inscription is created either way."
    ))
    def test_activite_d_une_autre_structure_refusee(self, directeur_client, enfant_sans_inscription):
        """Even when forged in the POST, an activity outside the director's structures is rejected."""
        famille, enfant = enfant_sans_inscription
        autre = ActiviteFactory(structure=StructureFactory(), nom="Activité voisine")
        groupe = GroupeFactory(activite=autre)
        tarif = _tarif(autre)
        response = _post_inscription(directeur_client, famille, enfant, autre, groupe, [tarif])
        assert response.status_code == 200
        assert "activite" in response.context["form"].errors
        assert not Inscription.objects.filter(individu=enfant, activite=autre).exists()


@pytest.mark.django_db
@pytest.mark.xfail(strict=True, raises=NameError, reason=(
    "BUG: Formulaire.envoyer_email_confirmation() returns _('...') when no 'connexion_adresse_exp' "
    "is configured, but '_' is never imported: saving any new inscription then crashes (500) "
    "after the inscription and its prestations were already written."
))
def test_inscription_sans_adresse_d_expedition(directeur_client, famille_bureau, camp):
    famille, _t, enfant = famille_bureau
    activite, groupe, tarif = camp
    response = _post_inscription(directeur_client, famille, enfant, activite, groupe, [tarif])
    assert response.status_code == 302


@pytest.mark.django_db
class TestDemandePortail:
    def test_valider_une_demande_d_inscription_du_portail(
        self, directeur_client, directeur, enfant_sans_inscription, camp
    ):
        famille, enfant = enfant_sans_inscription
        activite, groupe, tarif = camp
        demande = PortailRenseignement.objects.create(
            famille=famille, individu=enfant, categorie="activites", code="inscrire_activite",
            nouvelle_valeur='"%d;%d;%d"' % (activite.pk, groupe.pk, tarif.pk), etat="ATTENTE",
        )
        url = reverse(
            "individu_inscriptions_ajouter",
            kwargs={"idfamille": famille.pk, "idindividu": enfant.pk, "idactivite": activite.pk,
                    "idgroupe": groupe.pk, "idstarifs": str(tarif.pk), "iddemande": demande.pk},
        )
        form = directeur_client.get(url).context["form"]
        # The request pre-fills the activity, group and tarif chosen by the family
        assert form.fields["activite"].initial == activite.pk
        assert form.fields["groupe"].initial == groupe.pk
        assert [t.pk for t in form.fields["tarifs"].initial] == [tarif.pk]

        assert_redirect(_post_inscription(directeur_client, famille, enfant, activite, groupe, [tarif], url=url))
        demande.refresh_from_db()
        assert demande.etat == "VALIDE"
        assert demande.traitement_utilisateur == directeur
        assert demande.traitement_date is not None
        assert Inscription.objects.filter(individu=enfant, activite=activite).exists()


@pytest.mark.django_db
class TestModifierSupprimerInscription:
    def _inscription(self, famille, enfant, camp, **kwargs):
        activite, groupe, tarif = camp
        inscription = Inscription.objects.create(famille=famille, individu=enfant, activite=activite,
                                                 groupe=groupe, date_debut=datetime.date(2026, 7, 1), **kwargs)
        inscription.tarifs.add(tarif)
        return inscription

    def _url(self, name, inscription, **extra):
        kwargs = {"idfamille": inscription.famille_id, "idindividu": inscription.individu_id, "pk": inscription.pk}
        kwargs.update(extra)
        return reverse(name, kwargs=kwargs)

    def _url_modifier(self, inscription, tarif):
        return self._url("individu_inscriptions_modifier", inscription, idactivite=inscription.activite_id,
                         idgroupe=inscription.groupe_id, idtarifs=str(tarif.pk))

    def test_modifier_date_de_fin(self, directeur_client, enfant_sans_inscription, camp):
        famille, enfant = enfant_sans_inscription
        inscription = self._inscription(famille, enfant, camp)
        url = self._url_modifier(inscription, camp[2])
        data = build_form_data(directeur_client.get(url).context["form"], date_fin="2026-08-31",
                               tarifs=[camp[2].pk])
        assert_redirect(directeur_client.post(url, data))
        inscription.refresh_from_db()
        assert inscription.date_fin == datetime.date(2026, 8, 31)

    def test_modifier_inscription_facturee_bloquee(self, directeur_client, enfant_sans_inscription, camp):
        famille, enfant = enfant_sans_inscription
        inscription = self._inscription(famille, enfant, camp)
        facture = Facture.objects.create(famille=famille, numero=1, date_edition=datetime.date(2026, 7, 1),
                                         date_debut=datetime.date(2026, 7, 1), date_fin=datetime.date(2026, 7, 31))
        Prestation.objects.create(famille=famille, individu=enfant, activite=camp[0], date=datetime.date(2026, 7, 1),
                                  label="Séjour", montant=Decimal("120"), facture=facture)
        url = self._url_modifier(inscription, camp[2])
        response = directeur_client.get(url, follow=True)
        assert any("déjà facturées" in m for m in _messages(response))

        directeur_client.post(url, {"date_debut": "2026-07-01", "date_fin": "2026-08-31",
                                    "activite": camp[0].pk, "groupe": camp[1].pk, "tarifs": [camp[2].pk]})
        inscription.refresh_from_db()
        assert inscription.date_fin is None

    def test_modifier_inscription_d_une_autre_structure_interdit(self, directeur_client, enfant_sans_inscription):
        famille, enfant = enfant_sans_inscription
        autre = ActiviteFactory(structure=StructureFactory())
        groupe = GroupeFactory(activite=autre)
        tarif = _tarif(autre)
        inscription = self._inscription(famille, enfant, (autre, groupe, tarif))
        assert directeur_client.get(self._url_modifier(inscription, tarif)).status_code == 403

    def test_supprimer_inscription_sans_prestation(self, directeur_client, enfant_sans_inscription, camp):
        famille, enfant = enfant_sans_inscription
        inscription = self._inscription(famille, enfant, camp)
        assert_redirect(directeur_client.post(self._url("individu_inscriptions_supprimer", inscription)))
        assert not Inscription.objects.filter(pk=inscription.pk).exists()

    def _inscription_facturee(self, famille, enfant, camp):
        inscription = self._inscription(famille, enfant, camp)
        facture = Facture.objects.create(famille=famille, numero=2, date_edition=datetime.date(2026, 7, 1),
                                         date_debut=datetime.date(2026, 7, 1), date_fin=datetime.date(2026, 7, 31))
        Prestation.objects.create(famille=famille, individu=enfant, activite=camp[0], date=datetime.date(2026, 7, 1),
                                  label="Séjour", montant=Decimal("120"), forfait=1, facture=facture)
        return inscription

    def test_suppression_inscription_facturee_signalee(self, directeur_client, enfant_sans_inscription, camp):
        famille, enfant = enfant_sans_inscription
        inscription = self._inscription_facturee(famille, enfant, camp)
        url = self._url("individu_inscriptions_supprimer", inscription)
        assert any("déjà facturées" in e for e in directeur_client.get(url).context["erreurs_protection"])

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: crud.Supprimer only *displays* Check_protections() on the confirmation page; "
        "delete() never re-checks them, so a direct POST deletes an inscription whose "
        "prestations are invoiced. Applies to every crud.Supprimer with Check_protections."
    ))
    def test_suppression_inscription_facturee_refusee_cote_serveur(self, directeur_client, enfant_sans_inscription, camp):
        famille, enfant = enfant_sans_inscription
        inscription = self._inscription_facturee(famille, enfant, camp)
        directeur_client.post(self._url("individu_inscriptions_supprimer", inscription))
        assert Inscription.objects.filter(pk=inscription.pk).exists()

    @pytest.mark.xfail(strict=True, reason=(
        "À CONFIRMER (expected behaviour not validated by the product owner): an inscription "
        "mistakenly created by the director cannot be deleted, because the prestation the form "
        "auto-created (forfait=1, neither invoiced nor paid) triggers the 'prestations déjà "
        "associées' protection. Expected: such prestations are deleted with the inscription."
    ))
    def test_annuler_une_inscription_supprime_sa_prestation_non_facturee(
        self, directeur_client, enfant_sans_inscription, camp
    ):
        famille, enfant = enfant_sans_inscription
        activite, groupe, tarif = camp
        assert_redirect(_post_inscription(directeur_client, famille, enfant, activite, groupe, [tarif]))
        inscription = Inscription.objects.get(individu=enfant, activite=activite)

        url = self._url("individu_inscriptions_supprimer", inscription)
        assert directeur_client.get(url).context["erreurs_protection"] == []
        assert_redirect(directeur_client.post(url))
        assert not Inscription.objects.filter(pk=inscription.pk).exists()
        assert not Prestation.objects.filter(individu=enfant, activite=activite).exists()

    def test_supprimer_inscription_supprime_les_forfaits_credits(self, directeur_client, enfant_sans_inscription, camp):
        """Prestations with forfait=2 (forfait crédit) do not block and are removed with the inscription."""
        famille, enfant = enfant_sans_inscription
        inscription = self._inscription(famille, enfant, camp)
        forfait = Prestation.objects.create(famille=famille, individu=enfant, activite=camp[0],
                                            date=datetime.date(2026, 7, 1), label="Forfait",
                                            montant=Decimal("50"), forfait=2)
        assert_redirect(directeur_client.post(self._url("individu_inscriptions_supprimer", inscription)))
        assert not Inscription.objects.filter(pk=inscription.pk).exists()
        assert not Prestation.objects.filter(pk=forfait.pk).exists()

    def test_supprimer_inscription_d_une_autre_structure_interdit(self, directeur_client, enfant_sans_inscription):
        famille, enfant = enfant_sans_inscription
        autre = ActiviteFactory(structure=StructureFactory())
        groupe = GroupeFactory(activite=autre)
        tarif = _tarif(autre)
        inscription = self._inscription(famille, enfant, (autre, groupe, tarif))
        response = directeur_client.post(self._url("individu_inscriptions_supprimer", inscription))
        assert response.status_code == 403
        assert Inscription.objects.filter(pk=inscription.pk).exists()
