"""Inscriptions tab of the fiche individu: the parts not covered by test_bureau_inscriptions.py.

- AJAX helpers filling the "groupe" / "tarifs" dropdowns (ajax_get_groupes, ajax_get_tarifs);
- the datatable of the tab: status labels and the per-row action buttons (edit / invoice / forbidden);
- editing an inscription that already has consommations: the "action_conso" choice moves the
  consommations to the new group (all / from today / from a date / none), refused when the new
  group is closed on those dates, and refused when consommations fall outside the new period;
- moving an inscription to another activity, or removing a tarif: the now-orphan prestations are
  deleted, except the ones already paid (ventilated);
- the inscription questionnaire ("question_<id>" fields) saved as QuestionnaireReponse.
"""

import datetime
from decimal import Decimal

import pytest
from core.models import (
    CategorieTarif,
    CompteBancaire,
    Consommation,
    Facture,
    Inscription,
    ModeleImpression,
    ModeReglement,
    NomTarif,
    Ouverture,
    Payeur,
    Prestation,
    QuestionnaireQuestion,
    QuestionnaireReponse,
    Reglement,
    Tarif,
    TarifLigne,
    Unite,
    Ventilation,
)
from django.urls import reverse
from tests.bureau.conftest import AJAX, build_form_data
from tests.unit.factories import ActiviteFactory, AdresseMailFactory, GroupeFactory, StructureFactory

AUJOURDHUI = datetime.date.today()
DEBUT = AUJOURDHUI - datetime.timedelta(days=30)
HIER = AUJOURDHUI - datetime.timedelta(days=1)
DEMAIN = AUJOURDHUI + datetime.timedelta(days=1)

COLONNES = ["idinscription", "date_debut", "date_fin", "activite", "groupe", "statut", "famille", "actions"]


# ---------------------------------------------------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------------------------------------------------

def assert_redirect(response):
    if response.status_code == 200 and response.context and "form" in response.context:
        pytest.fail("Form invalide : %s / messages : %s" % (response.context["form"].errors.as_json(),
                                                            _messages(response)))
    assert response.status_code in (302, 303), response.status_code


def _messages(response):
    return [str(m) for m in response.context["messages"]]


def _tarif(activite, description, montant="120"):
    nom = NomTarif.objects.create(activite=activite, nom=description)
    tarif = Tarif.objects.create(activite=activite, nom_tarif=nom, type="FORFAIT", date_debut=datetime.date(2026, 1, 1),
                                 description=description)
    tarif.categories_tarifs.add(*CategorieTarif.objects.filter(activite=activite))
    TarifLigne.objects.create(activite=activite, tarif=tarif, montant_unique=Decimal(montant))
    return tarif


def _camp(structure, nom="Camp d'été"):
    activite = ActiviteFactory(structure=structure, nom=nom)
    CategorieTarif.objects.create(activite=activite, nom="Normal")
    return {
        "activite": activite,
        "louveteaux": GroupeFactory(activite=activite, nom="Louveteaux", ordre=2),
        "eclaireurs": GroupeFactory(activite=activite, nom="Éclaireurs", ordre=1),
        "sejour": _tarif(activite, "Séjour complet", "120"),
        "transport": _tarif(activite, "Transport", "30"),
        "unite": Unite.objects.create(activite=activite, ordre=1, nom="Journée", abrege="J"),
    }


@pytest.fixture
def camp(db, structure):
    return _camp(structure)


@pytest.fixture(autouse=True)
def mail_outbox(monkeypatch, set_parametre_portail):
    """Saving a new inscription sends a confirmation email: configure a sender and route it to locmem."""
    from django.core import mail
    from fiche_individu.forms import individu_inscriptions

    adresse = AdresseMailFactory(adresse="noreply@sacadoc.test", moteur="console")
    set_parametre_portail("connexion_adresse_exp", adresse.pk)
    real_get_connection = mail.get_connection
    monkeypatch.setattr(individu_inscriptions.djangomail, "get_connection",
                        lambda *a, **k: real_get_connection("django.core.mail.backends.locmem.EmailBackend"))
    mail.outbox = []
    return mail.outbox


@pytest.fixture
def famille_enfant(famille_bureau):
    famille, _titulaire, enfant = famille_bureau
    famille.mail = "parents@test.org"
    famille.save()
    return famille, enfant


def _inscrire(famille, enfant, camp, groupe="louveteaux", tarifs=("sejour",), **kwargs):
    """Create an inscription the way the form does: inscription + one prestation per tarif."""
    kwargs.setdefault("date_debut", DEBUT)
    inscription = Inscription.objects.create(famille=famille, individu=enfant, activite=camp["activite"],
                                             groupe=camp[groupe], **kwargs)
    for nom in tarifs:
        tarif = camp[nom]
        inscription.tarifs.add(tarif)
        Prestation.objects.create(famille=famille, individu=enfant, activite=camp["activite"], tarif=tarif,
                                  date=DEBUT, label=tarif.description, montant=tarif.tarifligne_set.get().montant_unique,
                                  forfait=1)
    return inscription


def _ouvrir(camp, groupe, *dates):
    for date in dates:
        Ouverture.objects.create(activite=camp["activite"], unite=camp["unite"], groupe=camp[groupe], date=date)


def _conso(inscription, camp, date, groupe="louveteaux"):
    return Consommation.objects.create(individu=inscription.individu, inscription=inscription,
                                       activite=inscription.activite, date=date, unite=camp["unite"],
                                       groupe=camp[groupe], etat="reservation", quantite=1)


def _url_liste(famille, enfant):
    return reverse("individu_inscriptions_liste", kwargs={"idfamille": famille.pk, "idindividu": enfant.pk})


def _url_ajouter(famille, enfant):
    return reverse("individu_inscriptions_ajouter", kwargs={"idfamille": famille.pk, "idindividu": enfant.pk})


def _url_modifier(inscription):
    return reverse("individu_inscriptions_modifier", kwargs={
        "idfamille": inscription.famille_id, "idindividu": inscription.individu_id,
        "idactivite": inscription.activite_id, "idgroupe": inscription.groupe_id,
        "idtarifs": ",".join(str(t.pk) for t in inscription.tarifs.all()) or "1", "pk": inscription.pk,
    })


def _modifier(client, inscription, **overrides):
    """GET the edit form of `inscription`, then POST it back with `overrides`."""
    url = _url_modifier(inscription)
    form = client.get(url).context["form"]
    data = build_form_data(form, tarifs=[t.pk for t in inscription.tarifs.all()])
    data.update(overrides)
    return client.post(url, data)


def _regler(prestation):
    famille = prestation.famille
    reglement = Reglement.objects.create(
        famille=famille, date=DEBUT, montant=prestation.montant,
        mode=ModeReglement.objects.create(label="Chèque"),
        payeur=Payeur.objects.create(famille=famille, nom=famille.nom),
        compte=CompteBancaire.objects.create(nom="Compte courant"),
        modelimp=ModeleImpression.objects.create(categorie="reglement", nom="Reçu"),
    )
    return Ventilation.objects.create(famille=famille, reglement=reglement, prestation=prestation,
                                      montant=prestation.montant)


def _datatable(client, url):
    """Run the DataTables AJAX query of the tab and return its rows as {column name: value} dicts."""
    params = {"draw": "1", "start": "0", "length": "100", "search[value]": "", "search[regex]": "false"}
    for index, name in enumerate(COLONNES):
        params.update({
            f"columns[{index}][data]": str(index), f"columns[{index}][name]": name,
            f"columns[{index}][searchable]": "true", f"columns[{index}][orderable]": "true",
            f"columns[{index}][search][value]": "", f"columns[{index}][search][regex]": "false",
        })
    response = client.get(url, params, **AJAX)
    assert response.status_code == 200
    return {int(ligne["DT_RowId"]): {name: ligne[str(index)] for index, name in enumerate(COLONNES)}
            for ligne in response.json()["data"]}


# ---------------------------------------------------------------------------------------------------------------------
# AJAX dropdowns
# ---------------------------------------------------------------------------------------------------------------------

@pytest.mark.django_db
class TestListesDeroulantesAjax:
    def test_groupes_de_l_activite_tries_par_ordre(self, directeur_client, camp):
        GroupeFactory(activite=ActiviteFactory(structure=camp["activite"].structure), nom="Autre activité")
        response = directeur_client.post(reverse("ajax_get_groupes"), {"idactivite": camp["activite"].pk}, **AJAX)
        assert response.status_code == 200
        html = response.content.decode()
        assert html.index("Éclaireurs") < html.index("Louveteaux")
        assert "Autre activité" not in html
        assert 'value="%d"' % camp["louveteaux"].pk in html

    def test_tarifs_de_l_activite(self, directeur_client, camp):
        response = directeur_client.post(reverse("ajax_get_tarifs"), {"idactivite": camp["activite"].pk}, **AJAX)
        html = response.content.decode()
        assert 'value="%d">Séjour complet' % camp["sejour"].pk in html
        assert 'value="%d">Transport' % camp["transport"].pk in html

    @pytest.mark.parametrize("url", ["ajax_get_groupes", "ajax_get_tarifs"])
    def test_sans_activite_la_liste_est_vide(self, directeur_client, url):
        response = directeur_client.post(reverse(url), {"idactivite": ""}, **AJAX)
        assert response.status_code == 200
        assert response.content == b""

    @pytest.mark.parametrize("url", ["ajax_get_groupes", "ajax_get_tarifs"])
    def test_refuse_aux_familles_et_aux_anonymes(self, client, famille_enfant, camp, url):
        assert client.post(reverse(url), {"idactivite": camp["activite"].pk}, **AJAX).status_code == 403
        client.force_login(famille_enfant[0].utilisateur)
        assert client.post(reverse(url), {"idactivite": camp["activite"].pk}, **AJAX).status_code == 403

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: Get_groupes / Get_tarifs (fiche_individu/views/individu_inscriptions.py:22,39) do not check that "
        "the activity belongs to one of the director's structures: any director can list the groups and "
        "tarifs of every other structure by changing idactivite."
    ))
    @pytest.mark.parametrize("url, nom", [("ajax_get_groupes", "Groupe secret"), ("ajax_get_tarifs", "Tarif secret")])
    def test_activite_d_une_autre_structure_non_listee(self, directeur_client, url, nom):
        autre = _camp(StructureFactory(), nom="Camp voisin")
        GroupeFactory(activite=autre["activite"], nom="Groupe secret")
        _tarif(autre["activite"], "Tarif secret")
        response = directeur_client.post(reverse(url), {"idactivite": autre["activite"].pk}, **AJAX)
        assert nom not in response.content.decode()


# ---------------------------------------------------------------------------------------------------------------------
# Datatable of the tab
# ---------------------------------------------------------------------------------------------------------------------

@pytest.mark.django_db
class TestListeDeLOnglet:
    def test_page_et_bouton_ajouter(self, directeur_client, famille_enfant):
        famille, enfant = famille_enfant
        response = directeur_client.get(_url_liste(famille, enfant))
        assert response.status_code == 200
        assert response.context["onglet_actif"] == "inscriptions"
        assert [b["href"] for b in response.context["boutons_liste"]] == [_url_ajouter(famille, enfant)]

    def test_seules_les_inscriptions_de_l_individu(self, directeur_client, famille_enfant, camp):
        famille, enfant = famille_enfant
        titulaire = famille.rattachement_set.exclude(individu=enfant).first().individu
        mienne = _inscrire(famille, enfant, camp)
        autre = Inscription.objects.create(famille=famille, individu=titulaire, activite=camp["activite"],
                                           groupe=camp["louveteaux"], date_debut=DEBUT)
        lignes = _datatable(directeur_client, _url_liste(famille, enfant))
        assert mienne.pk in lignes
        assert autre.pk not in lignes

    @pytest.mark.parametrize("statut, libelle", [("ok", "Valide"), ("attente", "Attente"), ("refus", "Refus")])
    def test_libelle_du_statut(self, directeur_client, famille_enfant, camp, statut, libelle):
        famille, enfant = famille_enfant
        inscription = _inscrire(famille, enfant, camp, statut=statut)
        assert libelle in _datatable(directeur_client, _url_liste(famille, enfant))[inscription.pk]["statut"]

    def test_inscription_non_facturee_modifiable(self, directeur_client, famille_enfant, camp):
        famille, enfant = famille_enfant
        inscription = _inscrire(famille, enfant, camp, tarifs=("sejour", "transport"))
        actions = _datatable(directeur_client, _url_liste(famille, enfant))[inscription.pk]["actions"]
        assert _url_modifier(inscription) in actions
        assert reverse("individu_inscriptions_supprimer", kwargs={
            "idfamille": famille.pk, "idindividu": enfant.pk, "pk": inscription.pk}) in actions
        assert "Accès interdit" not in actions

    def test_inscription_sans_tarif_modifiable(self, directeur_client, famille_enfant, camp):
        """Without tarif, the edit URL carries the placeholder "1" (the <str:idtarifs> segment cannot be empty)."""
        famille, enfant = famille_enfant
        inscription = _inscrire(famille, enfant, camp, tarifs=())
        actions = _datatable(directeur_client, _url_liste(famille, enfant))[inscription.pk]["actions"]
        assert _url_modifier(inscription) in actions
        assert "/%d/1/%d" % (camp["louveteaux"].pk, inscription.pk) in actions

    def test_inscription_facturee_non_modifiable_avec_lien_vers_la_facture(self, directeur_client, famille_enfant, camp):
        famille, enfant = famille_enfant
        inscription = _inscrire(famille, enfant, camp)
        facture = Facture.objects.create(famille=famille, numero=1, date_edition=DEBUT, date_debut=DEBUT,
                                         date_fin=AUJOURDHUI, individus=str(enfant.pk),
                                         activites=str(camp["activite"].pk))
        Prestation.objects.filter(individu=enfant).update(facture=facture)

        actions = _datatable(directeur_client, _url_liste(famille, enfant))[inscription.pk]["actions"]
        assert _url_modifier(inscription) not in actions
        assert reverse("famille_factures_liste", kwargs={"idfamille": famille.pk}) in actions

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: Get_actions_speciales looks the invoice up with Facture.individus == idindividu and "
        "Facture.activites == idactivite, but both are ';'-joined lists of ids: as soon as the invoice "
        "covers two children (or two activities), the shortcut to the invoice disappears."
    ))
    def test_lien_vers_une_facture_couvrant_deux_enfants(self, directeur_client, famille_enfant, camp):
        famille, enfant = famille_enfant
        titulaire = famille.rattachement_set.exclude(individu=enfant).first().individu
        inscription = _inscrire(famille, enfant, camp)
        facture = Facture.objects.create(famille=famille, numero=1, date_edition=DEBUT, date_debut=DEBUT,
                                         date_fin=AUJOURDHUI, individus="%d;%d" % (titulaire.pk, enfant.pk),
                                         activites=str(camp["activite"].pk))
        Prestation.objects.filter(individu=enfant).update(facture=facture)
        actions = _datatable(directeur_client, _url_liste(famille, enfant))[inscription.pk]["actions"]
        assert reverse("famille_factures_liste", kwargs={"idfamille": famille.pk}) in actions

    def test_inscription_d_une_autre_structure_acces_interdit(self, directeur_client, famille_enfant):
        famille, enfant = famille_enfant
        autre = _camp(StructureFactory(), nom="Camp voisin")
        inscription = _inscrire(famille, enfant, autre)
        actions = _datatable(directeur_client, _url_liste(famille, enfant))[inscription.pk]["actions"]
        assert "Accès interdit" in actions
        assert _url_modifier(inscription) not in actions


# ---------------------------------------------------------------------------------------------------------------------
# Add form: details not covered elsewhere
# ---------------------------------------------------------------------------------------------------------------------

@pytest.mark.django_db
class TestAjouter:
    def test_enregistrer_et_nouveau_revient_sur_le_formulaire(self, directeur_client, famille_enfant, camp):
        famille, enfant = famille_enfant
        url = _url_ajouter(famille, enfant)
        data = build_form_data(directeur_client.get(url).context["form"], individu=enfant.pk, famille=famille.pk,
                               activite=camp["activite"].pk, groupe=camp["louveteaux"].pk,
                               tarifs=[camp["sejour"].pk], date_debut=DEBUT.isoformat(), statut="ok",
                               SaveAndNew="1")
        response = directeur_client.post(url, data)
        assert_redirect(response)
        assert response.url == url

    def test_pas_de_choix_action_conso_a_l_ajout(self, directeur_client, famille_enfant):
        famille, enfant = famille_enfant
        form = directeur_client.get(_url_ajouter(famille, enfant)).context["form"]
        assert form.fields["action_conso"].required is False
        assert form.fields["date_debut"].initial == AUJOURDHUI


# ---------------------------------------------------------------------------------------------------------------------
# Edit with existing consommations
# ---------------------------------------------------------------------------------------------------------------------

@pytest.mark.django_db
class TestModifierAvecConsommations:
    @pytest.fixture
    def inscription(self, famille_enfant, camp):
        famille, enfant = famille_enfant
        inscription = _inscrire(famille, enfant, camp)
        _ouvrir(camp, "louveteaux", HIER, DEMAIN)
        _ouvrir(camp, "eclaireurs", HIER, DEMAIN)
        _conso(inscription, camp, HIER)
        _conso(inscription, camp, DEMAIN)
        return inscription

    def _groupes(self, inscription):
        return dict(Consommation.objects.filter(inscription=inscription).values_list("date", "groupe__nom"))

    def test_le_choix_est_obligatoire(self, directeur_client, inscription, camp):
        form = directeur_client.get(_url_modifier(inscription)).context["form"]
        assert form.fields["action_conso"].required is True
        assert "2 consommations" in form.fields["action_conso"].help_text

        response = _modifier(directeur_client, inscription, groupe=camp["eclaireurs"].pk, action_conso="")
        assert response.status_code == 200
        assert "action_conso" in response.context["form"].errors
        inscription.refresh_from_db()
        assert inscription.groupe == camp["louveteaux"]

    def test_modifier_tout_deplace_toutes_les_consommations(self, directeur_client, inscription, camp):
        assert_redirect(_modifier(directeur_client, inscription, groupe=camp["eclaireurs"].pk,
                                  action_conso="MODIFIER_TOUT"))
        inscription.refresh_from_db()
        assert inscription.groupe == camp["eclaireurs"]
        assert self._groupes(inscription) == {HIER: "Éclaireurs", DEMAIN: "Éclaireurs"}

    def test_modifier_a_partir_d_aujourd_hui(self, directeur_client, inscription, camp):
        assert_redirect(_modifier(directeur_client, inscription, groupe=camp["eclaireurs"].pk,
                                  action_conso="MODIFIER_AUJOURDHUI"))
        assert self._groupes(inscription) == {HIER: "Louveteaux", DEMAIN: "Éclaireurs"}

    def test_modifier_a_partir_d_une_date(self, directeur_client, inscription, camp):
        assert_redirect(_modifier(directeur_client, inscription, groupe=camp["eclaireurs"].pk,
                                  action_conso="MODIFIER_DATE", date_modification=DEMAIN.isoformat()))
        assert self._groupes(inscription) == {HIER: "Louveteaux", DEMAIN: "Éclaireurs"}

    def test_modifier_a_partir_d_une_date_sans_date_refuse(self, directeur_client, inscription, camp):
        response = _modifier(directeur_client, inscription, groupe=camp["eclaireurs"].pk,
                             action_conso="MODIFIER_DATE")
        assert response.status_code == 200
        assert "Vous devez saisir une date d'application" in _messages(response)
        inscription.refresh_from_db()
        assert inscription.groupe == camp["louveteaux"]
        assert self._groupes(inscription) == {HIER: "Louveteaux", DEMAIN: "Louveteaux"}

    def test_ne_rien_modifier_garde_les_consommations(self, directeur_client, inscription, camp):
        assert_redirect(_modifier(directeur_client, inscription, groupe=camp["eclaireurs"].pk,
                                  action_conso="MODIFIER_RIEN"))
        inscription.refresh_from_db()
        assert inscription.groupe == camp["eclaireurs"]
        assert self._groupes(inscription) == {HIER: "Louveteaux", DEMAIN: "Louveteaux"}

    def test_nouveau_groupe_ferme_refuse(self, directeur_client, inscription, camp):
        Ouverture.objects.filter(groupe=camp["eclaireurs"], date=DEMAIN).delete()
        response = _modifier(directeur_client, inscription, groupe=camp["eclaireurs"].pk,
                             action_conso="MODIFIER_TOUT")
        assert response.status_code == 200
        [message] = [m for m in _messages(response) if "unités sont fermées" in m]
        assert DEMAIN.strftime("%d/%m/%Y") in message
        assert HIER.strftime("%d/%m/%Y") not in message
        inscription.refresh_from_db()
        assert inscription.groupe == camp["louveteaux"]
        assert self._groupes(inscription) == {HIER: "Louveteaux", DEMAIN: "Louveteaux"}

    def test_groupe_ferme_ignore_avant_la_date_d_application(self, directeur_client, inscription, camp):
        """Only the consommations actually moved must be open on the new group."""
        Ouverture.objects.filter(groupe=camp["eclaireurs"], date=HIER).delete()
        assert_redirect(_modifier(directeur_client, inscription, groupe=camp["eclaireurs"].pk,
                                  action_conso="MODIFIER_AUJOURDHUI"))
        assert self._groupes(inscription) == {HIER: "Louveteaux", DEMAIN: "Éclaireurs"}

    def test_sans_changement_de_groupe_rien_n_est_deplace(self, directeur_client, inscription, camp):
        Ouverture.objects.filter(groupe=camp["eclaireurs"]).delete()
        assert_redirect(_modifier(directeur_client, inscription, action_conso="MODIFIER_TOUT",
                                  date_fin=(DEMAIN + datetime.timedelta(days=10)).isoformat()))
        assert self._groupes(inscription) == {HIER: "Louveteaux", DEMAIN: "Louveteaux"}

    @pytest.mark.parametrize("champ, valeur", [
        ("date_debut", AUJOURDHUI),
        ("date_fin", AUJOURDHUI),
    ])
    def test_consommations_hors_de_la_nouvelle_periode_refuse(self, directeur_client, inscription, champ, valeur):
        response = _modifier(directeur_client, inscription, action_conso="MODIFIER_RIEN", **{champ: valeur.isoformat()})
        assert response.status_code == 200
        assert any("1 consommations existent déjà hors de la période" in m for m in _messages(response))
        inscription.refresh_from_db()
        assert (inscription.date_debut, inscription.date_fin) == (DEBUT, None)

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: without date_fin, Modifier.form_valid (fiche_individu/views/individu_inscriptions.py:282) "
        "looks for consommations with date__lte=date_debut instead of date__lt: a consommation on the very "
        "first day of the inscription is reported as 'hors de la période' and blocks every edit."
    ))
    def test_consommation_le_premier_jour_ne_bloque_pas(self, directeur_client, inscription, camp):
        response = _modifier(directeur_client, inscription, action_conso="MODIFIER_RIEN",
                             date_debut=HIER.isoformat(), statut="refus")
        assert_redirect(response)
        inscription.refresh_from_db()
        assert inscription.statut == "refus"

    @pytest.mark.xfail(strict=True, raises=AttributeError, reason=(
        "BUG: changing the tarifs of an inscription that has consommations crashes (500): "
        "Modifier.form_valid passes form.cleaned_data['tarifs'].pk to the Grille_virtuelle, but 'tarifs' "
        "is a multiple-choice field (a QuerySet has no .pk). The inscription has already been saved "
        "(self.object.save()) when it crashes."
    ))
    def test_changer_les_tarifs_avec_des_consommations(self, directeur_client, inscription, camp):
        response = _modifier(directeur_client, inscription, action_conso="MODIFIER_TOUT",
                             tarifs=[camp["sejour"].pk, camp["transport"].pk])
        assert_redirect(response)


# ---------------------------------------------------------------------------------------------------------------------
# Edit: prestations follow the activity and the tarifs
# ---------------------------------------------------------------------------------------------------------------------

@pytest.mark.django_db
class TestModifierPrestations:
    def _prestations(self, enfant):
        return sorted(Prestation.objects.filter(individu=enfant).values_list("activite__nom", "label"))

    def test_ajouter_un_tarif_cree_sa_prestation(self, directeur_client, famille_enfant, camp):
        famille, enfant = famille_enfant
        inscription = _inscrire(famille, enfant, camp)
        assert_redirect(_modifier(directeur_client, inscription, tarifs=[camp["sejour"].pk, camp["transport"].pk]))
        assert self._prestations(enfant) == [("Camp d'été", "Séjour complet"), ("Camp d'été", "Transport")]
        assert Prestation.objects.get(individu=enfant, tarif=camp["transport"]).montant == Decimal("30")

    def test_retirer_un_tarif_supprime_sa_prestation(self, directeur_client, famille_enfant, camp):
        famille, enfant = famille_enfant
        inscription = _inscrire(famille, enfant, camp, tarifs=("sejour", "transport"))
        assert_redirect(_modifier(directeur_client, inscription, tarifs=[camp["sejour"].pk]))
        assert self._prestations(enfant) == [("Camp d'été", "Séjour complet")]

    def test_retirer_un_tarif_deja_regle_garde_sa_prestation(self, directeur_client, famille_enfant, camp):
        famille, enfant = famille_enfant
        inscription = _inscrire(famille, enfant, camp, tarifs=("sejour", "transport"))
        ventilation = _regler(Prestation.objects.get(individu=enfant, tarif=camp["transport"]))
        assert_redirect(_modifier(directeur_client, inscription, tarifs=[camp["sejour"].pk]))
        assert Prestation.objects.filter(pk=ventilation.prestation_id).exists()
        assert Ventilation.objects.filter(pk=ventilation.pk).exists()

    def test_pas_de_prestation_en_double_si_les_tarifs_ne_changent_pas(self, directeur_client, famille_enfant, camp):
        famille, enfant = famille_enfant
        inscription = _inscrire(famille, enfant, camp)
        assert_redirect(_modifier(directeur_client, inscription, statut="refus"))
        assert Prestation.objects.filter(individu=enfant).count() == 1

    def test_changer_d_activite_remplace_les_prestations(self, directeur_client, famille_enfant, camp, structure):
        famille, enfant = famille_enfant
        inscription = _inscrire(famille, enfant, camp)
        hiver = _camp(structure, nom="Camp d'hiver")
        assert_redirect(_modifier(directeur_client, inscription, activite=hiver["activite"].pk,
                                  groupe=hiver["louveteaux"].pk, tarifs=[hiver["sejour"].pk]))
        inscription.refresh_from_db()
        assert inscription.activite == hiver["activite"]
        assert self._prestations(enfant) == [("Camp d'hiver", "Séjour complet")]

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: on edit, Formulaire.__init__ pre-selects categorie_tarif from the *URL* idactivite (the old "
        "activity) and save() reuses that initial value: after moving an inscription to another activity, "
        "the inscription and its new prestations keep a categorie_tarif of the old activity."
    ))
    def test_changer_d_activite_change_la_categorie_de_tarif(self, directeur_client, famille_enfant, camp, structure):
        famille, enfant = famille_enfant
        inscription = _inscrire(famille, enfant, camp)
        hiver = _camp(structure, nom="Camp d'hiver")
        assert_redirect(_modifier(directeur_client, inscription, activite=hiver["activite"].pk,
                                  groupe=hiver["louveteaux"].pk, tarifs=[hiver["sejour"].pk]))
        inscription.refresh_from_db()
        assert inscription.categorie_tarif.activite == hiver["activite"]
        assert Prestation.objects.get(individu=enfant, activite=hiver["activite"]).categorie_tarif.activite == hiver["activite"]

    def test_changer_d_activite_garde_les_prestations_reglees(self, directeur_client, famille_enfant, camp, structure):
        famille, enfant = famille_enfant
        inscription = _inscrire(famille, enfant, camp)
        ventilation = _regler(Prestation.objects.get(individu=enfant))
        hiver = _camp(structure, nom="Camp d'hiver")
        assert_redirect(_modifier(directeur_client, inscription, activite=hiver["activite"].pk,
                                  groupe=hiver["louveteaux"].pk, tarifs=[hiver["sejour"].pk]))
        assert Prestation.objects.filter(pk=ventilation.prestation_id).exists()
        assert self._prestations(enfant) == [("Camp d'hiver", "Séjour complet"), ("Camp d'été", "Séjour complet")]

    def test_modification_pas_d_email_de_confirmation(self, directeur_client, famille_enfant, camp, mail_outbox):
        famille, enfant = famille_enfant
        inscription = _inscrire(famille, enfant, camp)
        assert_redirect(_modifier(directeur_client, inscription, statut="refus"))
        assert mail_outbox == []

    def test_activite_archivee_non_modifiable(self, directeur_client, famille_enfant, camp):
        famille, enfant = famille_enfant
        inscription = _inscrire(famille, enfant, camp)
        camp["activite"].actif = False
        camp["activite"].save()
        response = directeur_client.get(_url_modifier(inscription), follow=True)
        assert any("archivée" in m for m in _messages(response))

    @pytest.mark.xfail(strict=True, raises=Inscription.DoesNotExist, reason=(
        "BUG: Modifier.test_func (fiche_individu/views/individu_inscriptions.py:258) does "
        "Inscription.objects.get(pk=...) without handling DoesNotExist: opening the edit page of a deleted "
        "inscription (stale link, second tab) is a 500 instead of a 404."
    ))
    def test_inscription_inexistante_404(self, directeur_client, famille_enfant, camp):
        famille, enfant = famille_enfant
        inscription = _inscrire(famille, enfant, camp)
        url = _url_modifier(inscription)
        Prestation.objects.filter(individu=enfant).delete()
        inscription.delete()
        assert directeur_client.get(url).status_code == 404


# ---------------------------------------------------------------------------------------------------------------------
# Questionnaire
# ---------------------------------------------------------------------------------------------------------------------

@pytest.mark.django_db
class TestQuestionnaire:
    @pytest.fixture
    def questions(self, structure):
        return {
            "regime": QuestionnaireQuestion.objects.create(categorie="inscription", ordre=1, label="Régime",
                                                           controle="ligne_texte", structure=structure),
            "activites": QuestionnaireQuestion.objects.create(categorie="inscription", ordre=2, label="Activités",
                                                              controle="liste_coches", choix="Kayak;Escalade;Vélo",
                                                              structure=structure),
        }

    def _cle(self, question):
        return "question_%d" % question.pk

    def test_questions_de_ma_structure_affichees(self, directeur_client, famille_enfant, questions):
        autre = QuestionnaireQuestion.objects.create(categorie="inscription", ordre=3, label="Autre",
                                                     controle="ligne_texte", structure=StructureFactory())
        cachee = QuestionnaireQuestion.objects.create(categorie="inscription", ordre=4, label="Cachée",
                                                      controle="ligne_texte", structure=questions["regime"].structure,
                                                      visible=False)
        individu = QuestionnaireQuestion.objects.create(categorie="individu", ordre=5, label="Individu",
                                                        controle="ligne_texte", structure=questions["regime"].structure)
        form = directeur_client.get(_url_ajouter(*famille_enfant)).context["form"]
        champs = [f for f in form.fields if f.startswith("question_")]
        assert champs == [self._cle(questions["regime"]), self._cle(questions["activites"])]
        assert self._cle(autre) not in champs and self._cle(cachee) not in champs and self._cle(individu) not in champs

    def test_reponses_enregistrees_a_l_ajout(self, directeur_client, famille_enfant, camp, questions):
        famille, enfant = famille_enfant
        url = _url_ajouter(famille, enfant)
        data = build_form_data(directeur_client.get(url).context["form"], individu=enfant.pk, famille=famille.pk,
                               activite=camp["activite"].pk, groupe=camp["louveteaux"].pk,
                               tarifs=[camp["sejour"].pk], date_debut=DEBUT.isoformat(), statut="ok")
        data[self._cle(questions["regime"])] = "Sans gluten"
        data[self._cle(questions["activites"])] = ["Kayak", "Vélo"]
        assert_redirect(directeur_client.post(url, data))

        inscription = Inscription.objects.get(individu=enfant, activite=camp["activite"])
        reponses = dict(QuestionnaireReponse.objects.filter(donnee=inscription.pk).values_list("question", "reponse"))
        assert reponses == {questions["regime"].pk: "Sans gluten", questions["activites"].pk: "Kayak;Vélo"}

    def test_reponses_rechargees_et_modifiees(self, directeur_client, famille_enfant, camp, questions):
        famille, enfant = famille_enfant
        inscription = _inscrire(famille, enfant, camp)
        QuestionnaireReponse.objects.create(donnee=inscription.pk, question=questions["regime"], reponse="Sans gluten")
        QuestionnaireReponse.objects.create(donnee=inscription.pk, question=questions["activites"], reponse="Kayak")

        form = directeur_client.get(_url_modifier(inscription)).context["form"]
        assert form.fields[self._cle(questions["regime"])].initial == "Sans gluten"
        assert form.fields[self._cle(questions["activites"])].initial == ["Kayak"]

        assert_redirect(_modifier(directeur_client, inscription, **{
            self._cle(questions["regime"]): "Végétarien", self._cle(questions["activites"]): ["Escalade"]}))
        reponses = dict(QuestionnaireReponse.objects.filter(donnee=inscription.pk).values_list("question", "reponse"))
        assert reponses == {questions["regime"].pk: "Végétarien", questions["activites"].pk: "Escalade"}
        assert QuestionnaireReponse.objects.filter(donnee=inscription.pk).count() == 2
