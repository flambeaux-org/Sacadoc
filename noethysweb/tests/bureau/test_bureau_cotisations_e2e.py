"""Adhésions (cotisations), end to end:

1. the director defines the types of membership (Paramétrage > Types d'adhésions: familiale or
   individuelle, carte d'adhérent) and their units (Paramétrage > Unités d'adhésions: validity period
   or duration, price fixed or depending on the quotient familial, prefacturation);
2. an activity requires an up to date membership (Activite.cotisations);
3. the family is notified (fiche famille alerts, portal home, Adhésions page, Compléter mon dossier);
4. the director records the membership from the fiche famille (with a membership card, billed or
   not), or by batch (Saisir un lot d'adhésions), and the alert disappears;
5. prefactured memberships can be paid on the portal before any invoice;
6. memberships are gathered in deposits (Dépôts d'adhésions);
7. the director follows the families still missing a membership (Liste des adhésions manquantes).
"""

import datetime
import json
from decimal import Decimal

import pytest
from core.models import Cotisation, DepotCotisations, Inscription, Prestation, Quotient, TypeCotisation, \
    TypeQuotient, UniteCotisation, Utilisateur
from dateutil.relativedelta import relativedelta
from django.test import Client
from django.urls import reverse
from tests.bureau.conftest import AJAX, build_form_data
from tests.bureau.test_bureau_prestations import _regler
from tests.unit.factories import ActiviteFactory, InscriptionFactory, StructureFactory, \
    create_famille_complete


def _aujourdhui():
    """Today as the application sees it (computed at call time, see test_bureau_documents_e2e)."""
    return datetime.date.today()


# ---------------------------------------------------------------------------
# Paramétrage (real screens)
# ---------------------------------------------------------------------------

def _creer_type(client, nom="Adhésion familiale", type="famille", structure=None, **extra):
    data = {"nom": nom, "type": type, "structure": structure.pk if structure else ""}
    data.update(extra)
    response = client.post(reverse("types_cotisations_ajouter"), data)
    if response.status_code != 302:
        return response
    return TypeCotisation.objects.get(nom=nom)


def _donnees_unite(type_cotisation, nom="Année 2026", **extra):
    data = {"nom": nom, "type_cotisation": type_cotisation.pk, "validite_type": "PERIODE",
            "date_debut": "2026-01-01", "date_fin": "2026-12-31", "type_tarif": "GRATUIT", "montant": "0",
            "label_type": "DEFAUT"}
    data.update(extra)
    return data


def _creer_unite(client, type_cotisation, nom="Année 2026", **extra):
    url = reverse("unites_cotisations_ajouter", kwargs={"categorie": type_cotisation.pk})
    response = client.post(url, _donnees_unite(type_cotisation, nom=nom, **extra))
    if response.status_code != 302:
        return response
    return UniteCotisation.objects.get(type_cotisation=type_cotisation, nom=nom)


def _erreurs(response):
    assert response.status_code == 200, response
    return response.context["form"].errors


def _unite_en_cours(client, type_cotisation, nom="Année en cours", **extra):
    """A unit valid one year from today (validity by duration)."""
    return _creer_unite(client, type_cotisation, nom=nom, validite_type="DUREE", validite_annees="1", **extra)


@pytest.fixture
def type_familial(directeur_client, structure):
    return _creer_type(directeur_client, nom="Adhésion familiale", type="famille", structure=structure)


@pytest.fixture
def type_individuel(directeur_client, structure):
    return _creer_type(directeur_client, nom="Adhésion", type="individu", structure=structure)


@pytest.fixture
def unite_familiale(directeur_client, type_familial):
    return _unite_en_cours(directeur_client, type_familial)


@pytest.fixture
def unite_individuelle(directeur_client, type_individuel):
    return _unite_en_cours(directeur_client, type_individuel)


@pytest.fixture
def adhesion_requise(activite, type_individuel, unite_individuelle):
    """The activity requires an up to date individual membership. The Renseignements tab no longer
    shows the field (see TestExigenceActivite), so it is set as the activity wizard does."""
    activite.cotisations.add(type_individuel)
    return type_individuel


# ---------------------------------------------------------------------------
# Fiche famille > Adhésions (real screens)
# ---------------------------------------------------------------------------

def _donnees_adhesion(client, famille, unite, individu=None, **overrides):
    """POST data of the 'Ajouter une adhésion' form, as the page's JS fills it once the unit is picked."""
    form = client.get(reverse("famille_cotisations_ajouter", args=[famille.pk])).context["form"]
    debut, fin = unite.Get_dates_validite()
    data = build_form_data(form, famille=famille.pk, type_cotisation=unite.type_cotisation_id,
                           unite_cotisation=unite.pk, individu=individu.pk if individu else "",
                           date_debut=debut.isoformat(), date_fin=fin.isoformat())
    data.update(overrides)
    return {cle: valeur for cle, valeur in data.items() if valeur is not None}


def _ajouter(client, famille, unite, individu=None, **overrides):
    avant = set(Cotisation.objects.values_list("pk", flat=True))
    response = client.post(reverse("famille_cotisations_ajouter", args=[famille.pk]),
                           _donnees_adhesion(client, famille, unite, individu=individu, **overrides))
    if response.status_code != 302:
        return response
    return Cotisation.objects.exclude(pk__in=avant).get()


def _donnees_modification(client, cotisation, **overrides):
    """POST data of the edit form: only the fields actually rendered on the page are posted."""
    url = reverse("famille_cotisations_modifier", args=[cotisation.famille_id, cotisation.pk])
    response = client.get(url)
    form = response.context["form"]
    html = response.content.decode()
    data = build_form_data(form)
    data = {cle: valeur for cle, valeur in data.items() if 'name="%s"' % cle in html}
    data["famille"] = cotisation.famille_id
    data.update(overrides)
    return url, data


def _manquantes_fiche(client, famille):
    """Labels of the missing memberships shown on the fiche famille (résumé)."""
    response = client.get(reverse("famille_resume", args=[famille.pk]))
    return [c["label"] for c in response.context["cotisations_manquantes"]]


# ---------------------------------------------------------------------------
# Portal helpers
# ---------------------------------------------------------------------------

def _portail(famille):
    client = Client()
    client.force_login(Utilisateur.objects.get(pk=famille.utilisateur_id))
    return client


def _a_fournir_portail(famille):
    response = _portail(famille).get(reverse("portail_cotisations"))
    assert response.status_code == 200
    return [c["label"] for c in response.context["cotisations_fournir"] if not c["valide"]]


@pytest.fixture
def page_adhesions(set_parametre_portail):
    set_parametre_portail("cotisations_afficher_page", True)


# ===========================================================================
# 1. Paramétrage
# ===========================================================================

@pytest.mark.django_db
class TestTypesAdhesions:
    def test_creation_type_familial(self, directeur_client, structure):
        type_cotisation = _creer_type(directeur_client, nom="Adhésion familiale", type="famille", carte="on",
                                      structure=structure, code_comptable="706")
        assert type_cotisation.type == "famille"
        assert type_cotisation.carte is True
        assert type_cotisation.code_comptable == "706"
        assert type_cotisation.structure == structure

    def test_le_premier_type_est_le_type_par_defaut(self, directeur_client, structure):
        premier = _creer_type(directeur_client, nom="Premier", structure=structure)
        assert premier.defaut is True

    def test_un_seul_type_par_defaut(self, directeur_client, structure):
        premier = _creer_type(directeur_client, nom="Premier", structure=structure)
        second = _creer_type(directeur_client, nom="Second", structure=structure, defaut="on")
        premier.refresh_from_db()
        assert second.defaut is True
        assert premier.defaut is False

    def test_nature_figee_des_qu_une_adhesion_existe(self, directeur_client, famille_bureau, type_familial,
                                                     unite_familiale):
        """Switching an used type from familiale to individuelle would orphan its memberships."""
        famille, _t, _e = famille_bureau
        _ajouter(directeur_client, famille, unite_familiale)
        url = reverse("types_cotisations_modifier", args=[type_familial.pk])
        form = directeur_client.get(url).context["form"]
        assert form.fields["type"].disabled
        data = build_form_data(form, type="individu")
        directeur_client.post(url, data)
        type_familial.refresh_from_db()
        assert type_familial.type == "famille"

    def test_type_utilise_non_supprimable(self, directeur_client, famille_bureau, type_familial, unite_familiale):
        famille, _t, _e = famille_bureau
        _ajouter(directeur_client, famille, unite_familiale)
        directeur_client.post(reverse("types_cotisations_supprimer", args=[type_familial.pk]))
        assert TypeCotisation.objects.filter(pk=type_familial.pk).exists()

    def test_suppression_reattribue_le_defaut(self, directeur_client, structure):
        premier = _creer_type(directeur_client, nom="Premier", structure=structure)
        second = _creer_type(directeur_client, nom="Second", structure=structure)
        directeur_client.post(reverse("types_cotisations_supprimer", args=[premier.pk]))
        second.refresh_from_db()
        assert second.defaut is True

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the delete page warns that the type is required by an activity (manytomany_associes) but the "
        "POST deletes it anyway: the activity silently stops requiring any membership."
    ))
    def test_type_requis_par_une_activite_non_supprimable(self, directeur_client, activite, type_familial):
        activite.cotisations.add(type_familial)
        page = directeur_client.get(reverse("types_cotisations_supprimer", args=[type_familial.pk]))
        assert page.context["erreurs_protection"]
        directeur_client.post(reverse("types_cotisations_supprimer", args=[type_familial.pk]))
        assert activite.cotisations.filter(pk=type_familial.pk).exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (périmètre): the 'Structure' field of a membership type lists every structure, a director can "
        "attach a type to a structure he does not manage."
    ))
    def test_structure_limitee_a_mes_structures(self, directeur_client, structure):
        autre = StructureFactory(nom="Autre structure")
        form = directeur_client.get(reverse("types_cotisations_ajouter")).context["form"]
        assert autre not in form.fields["structure"].queryset

    def test_types_d_une_autre_structure_non_proposes(self, directeur_client, famille_bureau, type_familial):
        famille, _t, _e = famille_bureau
        autre = TypeCotisation.objects.create(nom="Adhésion d'ailleurs", structure=StructureFactory(nom="Autre"))
        commun = TypeCotisation.objects.create(nom="Adhésion organisateur", structure=None)
        form = directeur_client.get(reverse("famille_cotisations_ajouter", args=[famille.pk])).context["form"]
        proposes = set(form.fields["type_cotisation"].queryset)
        assert type_familial in proposes and commun in proposes
        assert autre not in proposes


@pytest.mark.django_db
class TestUnitesAdhesions:
    def test_unite_sur_une_periode(self, directeur_client, type_familial):
        unite = _creer_unite(directeur_client, type_familial, nom="Saison", date_debut="2026-09-01",
                             date_fin="2027-08-31")
        assert unite.duree is None
        assert unite.Get_dates_validite() == (datetime.date(2026, 9, 1), datetime.date(2027, 8, 31))

    def test_periode_incomplete_ou_inversee_refusee(self, directeur_client, type_familial):
        url = reverse("unites_cotisations_ajouter", kwargs={"categorie": type_familial.pk})
        sans_fin = _erreurs(directeur_client.post(url, _donnees_unite(type_familial, date_fin="")))
        assert "date_fin" in sans_fin
        inversee = _erreurs(directeur_client.post(url, _donnees_unite(type_familial, date_debut="2026-12-31",
                                                                       date_fin="2026-01-01")))
        assert "date_fin" in inversee
        assert not UniteCotisation.objects.exists()

    def test_unite_sur_une_duree(self, directeur_client, type_familial):
        unite = _creer_unite(directeur_client, type_familial, nom="Un an et demi", validite_type="DUREE",
                             validite_annees="1", validite_mois="6")
        assert unite.duree == "j0-m6-a1"
        debut, fin = unite.Get_dates_validite(date_debut=datetime.date(2026, 1, 15))
        assert (debut, fin) == (datetime.date(2026, 1, 15), datetime.date(2027, 7, 15))
        # Without start date, the membership starts today
        assert unite.Get_dates_validite()[0] == _aujourdhui()

    def test_duree_nulle_refusee(self, directeur_client, type_familial):
        url = reverse("unites_cotisations_ajouter", kwargs={"categorie": type_familial.pk})
        erreurs = _erreurs(directeur_client.post(url, _donnees_unite(type_familial, validite_type="DUREE")))
        assert "validite_type" in erreurs

    def test_montant_unique(self, directeur_client, type_familial):
        unite = _creer_unite(directeur_client, type_familial, type_tarif="MONTANT", montant="15.50")
        assert unite.montant == Decimal("15.50")
        assert unite.tarifs is None

    def test_montant_unique_obligatoire(self, directeur_client, type_familial):
        url = reverse("unites_cotisations_ajouter", kwargs={"categorie": type_familial.pk})
        erreurs = _erreurs(directeur_client.post(url, _donnees_unite(type_familial, type_tarif="MONTANT",
                                                                     montant="")))
        assert "montant" in erreurs

    def test_tarifs_selon_le_quotient(self, directeur_client, type_familial):
        tarifs = "0-499=9.50\n500-950=10.05\n951-999999=13.90"
        unite = _creer_unite(directeur_client, type_familial, type_tarif="QF", montant="20", tarifs=tarifs)
        assert unite.tarifs.splitlines() == tarifs.splitlines()
        assert unite.montant == 0

    @pytest.mark.parametrize("tarifs", ["", "0-499:9.50", "abc-499=9.50", "500-100=9.50"])
    def test_tarifs_quotient_mal_saisis_refuses(self, directeur_client, type_familial, tarifs):
        url = reverse("unites_cotisations_ajouter", kwargs={"categorie": type_familial.pk})
        erreurs = _erreurs(directeur_client.post(url, _donnees_unite(type_familial, type_tarif="QF",
                                                                     tarifs=tarifs)))
        assert "tarifs" in erreurs

    def test_label_de_prestation_personnalise(self, directeur_client, type_familial):
        url = reverse("unites_cotisations_ajouter", kwargs={"categorie": type_familial.pk})
        erreurs = _erreurs(directeur_client.post(url, _donnees_unite(type_familial, label_type="PERSO")))
        assert "label_perso" in erreurs
        unite = _creer_unite(directeur_client, type_familial, label_type="PERSO", label_perso="Adhésion annuelle")
        assert unite.label_prestation == "Adhésion annuelle"

    def test_une_seule_unite_par_defaut_par_type(self, directeur_client, type_familial, type_individuel):
        autre_type = _creer_unite(directeur_client, type_individuel, nom="Unité individuelle")
        premiere = _creer_unite(directeur_client, type_familial, nom="Première")
        seconde = _creer_unite(directeur_client, type_familial, nom="Seconde", defaut="on")
        premiere.refresh_from_db()
        autre_type.refresh_from_db()
        assert (premiere.defaut, seconde.defaut) == (False, True)
        # The default unit of another type is untouched
        assert autre_type.defaut is True

    def test_suppression_reattribue_le_defaut_dans_le_type(self, directeur_client, type_familial, type_individuel):
        _creer_unite(directeur_client, type_individuel, nom="Unité individuelle")
        premiere = _creer_unite(directeur_client, type_familial, nom="Première")
        seconde = _creer_unite(directeur_client, type_familial, nom="Seconde")
        directeur_client.post(reverse("unites_cotisations_supprimer", args=[type_familial.pk, premiere.pk]))
        seconde.refresh_from_db()
        assert seconde.defaut is True

    def test_unite_utilisee_non_supprimable(self, directeur_client, famille_bureau, type_familial, unite_familiale):
        famille, _t, _e = famille_bureau
        _ajouter(directeur_client, famille, unite_familiale)
        directeur_client.post(reverse("unites_cotisations_supprimer", args=[type_familial.pk, unite_familiale.pk]))
        assert UniteCotisation.objects.filter(pk=unite_familiale.pk).exists()


@pytest.mark.django_db
class TestExigenceActivite:
    @pytest.mark.xfail(strict=True, reason=(
        "BUG: 'cotisations' is still in the fields of the Activité > Renseignements form but no longer in its "
        "layout. Saving the tab (e.g. to add a required document) posts no value and wipes the memberships "
        "required by the activity (set by the activity wizard)."
    ))
    def test_enregistrer_les_renseignements_conserve_les_adhesions_requises(self, directeur_client, activite,
                                                                           adhesion_requise):
        url = reverse("activites_renseignements_modifier", kwargs={"idactivite": activite.pk})
        response = directeur_client.get(url)
        html = response.content.decode()
        data = build_form_data(response.context["form"])
        data = {cle: valeur for cle, valeur in data.items() if 'name="%s"' % cle in html}
        assert directeur_client.post(url, data).status_code == 302
        assert list(activite.cotisations.all()) == [adhesion_requise]


# ===========================================================================
# 2. Saisie depuis la fiche famille
# ===========================================================================

@pytest.mark.django_db
class TestAideALaSaisie:
    """The 'Ajouter une adhésion' page fills the form through two AJAX calls."""

    def test_unites_du_type_choisi(self, directeur_client, type_familial, type_individuel):
        u1 = _creer_unite(directeur_client, type_familial, nom="2026", date_debut="2026-01-01", date_fin="2026-12-31")
        u2 = _creer_unite(directeur_client, type_familial, nom="2027", date_debut="2027-01-01",
                          date_fin="2027-12-31", defaut="on")
        _creer_unite(directeur_client, type_individuel, nom="Individuelle")
        html = directeur_client.post(reverse("ajax_on_change_type_cotisation"),
                                     {"idtype_cotisation": type_familial.pk}, **AJAX).content.decode()
        assert '<option value="%d" >2026</option>' % u1.pk in html
        assert '<option value="%d" selected>2027</option>' % u2.pk in html
        assert "Individuelle" not in html

    def _infos_unite(self, client, unite, famille=None):
        response = client.post(reverse("ajax_on_change_unite_cotisation"),
                               {"idunite_cotisation": unite.pk, "idfamille": famille.pk if famille else ""}, **AJAX)
        return response.json()

    def test_infos_de_l_unite(self, directeur_client, structure):
        type_cotisation = _creer_type(directeur_client, nom="Adhésion", type="individu", carte="on",
                                      structure=structure)
        unite = _creer_unite(directeur_client, type_cotisation, nom="Saison", type_tarif="MONTANT", montant="12",
                             date_debut="2026-09-01", date_fin="2027-08-31")
        infos = self._infos_unite(directeur_client, unite)
        assert infos["type"] == "individu"
        assert infos["carte"] is True
        assert (infos["date_debut"], infos["date_fin"]) == ("01/09/2026", "31/08/2027")
        assert infos["label_prestation"] == "Adhésion - Saison"
        assert Decimal(str(infos["montant"])) == Decimal("12")
        assert infos["date_creation_carte"] == _aujourdhui().strftime("%d/%m/%Y")

    def test_label_personnalise_propose(self, directeur_client, type_familial):
        unite = _creer_unite(directeur_client, type_familial, label_type="PERSO", label_perso="Cotisation annuelle")
        assert self._infos_unite(directeur_client, unite)["label_prestation"] == "Cotisation annuelle"

    def test_unite_sur_une_duree_commence_aujourd_hui(self, directeur_client, unite_familiale):
        infos = self._infos_unite(directeur_client, unite_familiale)
        debut = _aujourdhui()
        assert infos["date_debut"] == debut.strftime("%d/%m/%Y")
        assert infos["date_fin"] == (debut + relativedelta(years=1)).strftime("%d/%m/%Y")

    @pytest.mark.parametrize("quotient, attendu", [(Decimal("300"), Decimal("9.50")), (Decimal("600"), Decimal("10.05")),
                                                   (Decimal("2000"), Decimal("13.90")), (None, Decimal("13.90"))])
    def test_tarif_selon_le_quotient_de_la_famille(self, directeur_client, famille_bureau, type_familial, quotient,
                                                   attendu):
        """Without a current quotient, the highest price applies."""
        famille, _t, _e = famille_bureau
        unite = _creer_unite(directeur_client, type_familial, type_tarif="QF",
                             tarifs="0-499=9.50\n500-950=10.05\n951-999999=13.90")
        if quotient is not None:
            Quotient.objects.create(famille=famille, quotient=quotient, type_quotient=TypeQuotient.objects.create(nom="CAF"),
                                    date_debut=_aujourdhui() - datetime.timedelta(days=30),
                                    date_fin=_aujourdhui() + datetime.timedelta(days=30))
        infos = self._infos_unite(directeur_client, unite, famille=famille)
        assert Decimal(str(infos["montant"])) == attendu

    def test_quotient_expire_ignore(self, directeur_client, famille_bureau, type_familial):
        famille, _t, _e = famille_bureau
        unite = _creer_unite(directeur_client, type_familial, type_tarif="QF", tarifs="0-499=9.50\n500-999999=20")
        Quotient.objects.create(famille=famille, quotient=Decimal("300"), type_quotient=TypeQuotient.objects.create(nom="CAF"),
                                date_debut=datetime.date(2020, 1, 1), date_fin=datetime.date(2020, 12, 31))
        assert Decimal(str(self._infos_unite(directeur_client, unite, famille=famille)["montant"])) == Decimal("20")

    def test_saisie_rapide_preremplie(self, directeur_client, famille_bureau, type_individuel, unite_individuelle):
        """The link next to a missing membership opens the form with the type and the child already chosen."""
        famille, _t, enfant = famille_bureau
        url = reverse("famille_cotisations_saisie_rapide", args=[famille.pk, type_individuel.pk, enfant.pk])
        form = directeur_client.get(url).context["form"]
        assert str(form.fields["type_cotisation"].initial) == str(type_individuel.pk)
        assert str(form.fields["individu"].initial) == str(enfant.pk)

    def test_seuls_les_membres_de_la_famille_sont_proposes(self, directeur_client, famille_bureau):
        famille, titulaire, enfant = famille_bureau
        _u, _autre, ratt_autre = create_famille_complete(username="autre_famille")
        form = directeur_client.get(reverse("famille_cotisations_ajouter", args=[famille.pk])).context["form"]
        proposes = {valeur for valeur, _label in form.fields["individu"].choices if valeur}
        assert proposes == {titulaire.pk, enfant.pk}
        assert ratt_autre[1].individu.pk not in proposes


@pytest.mark.django_db
class TestSaisieAdhesion:
    def test_adhesion_familiale_gratuite(self, directeur_client, famille_bureau, unite_familiale):
        famille, titulaire, _e = famille_bureau
        # An individual picked by mistake is ignored for a family membership
        cotisation = _ajouter(directeur_client, famille, unite_familiale, individu=titulaire)
        assert cotisation.famille == famille
        assert cotisation.individu is None
        assert cotisation.type_cotisation == unite_familiale.type_cotisation
        assert (cotisation.date_debut, cotisation.date_fin) == unite_familiale.Get_dates_validite()
        assert cotisation.prestation is None
        assert (cotisation.numero, cotisation.date_creation_carte) == (None, None)

    def test_adhesion_individuelle(self, directeur_client, famille_bureau, unite_individuelle):
        famille, _t, enfant = famille_bureau
        cotisation = _ajouter(directeur_client, famille, unite_individuelle, individu=enfant)
        assert (cotisation.famille, cotisation.individu) == (famille, enfant)

    def test_adhesion_individuelle_sans_beneficiaire_refusee(self, directeur_client, famille_bureau,
                                                             unite_individuelle):
        famille, _t, _e = famille_bureau
        erreurs = _erreurs(_ajouter(directeur_client, famille, unite_individuelle))
        assert "individu" in erreurs
        assert not Cotisation.objects.exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: Formulaire.clean() reads cleaned_data['type_cotisation'] without checking it is valid: submitting "
        "the form without a type (or with a type not allowed) crashes with KeyError (500) instead of showing "
        "'Ce champ est obligatoire'."
    ))
    def test_type_non_choisi_message_d_erreur(self, directeur_client, famille_bureau, unite_familiale):
        famille, _t, _e = famille_bureau
        erreurs = _erreurs(_ajouter(directeur_client, famille, unite_familiale, type_cotisation=""))
        assert "type_cotisation" in erreurs

    def test_carte_d_adherent(self, directeur_client, famille_bureau, unite_familiale):
        famille, _t, _e = famille_bureau
        cotisation = _ajouter(directeur_client, famille, unite_familiale, carte="on", numero="000042",
                              date_creation_carte="2026-09-01")
        assert cotisation.numero == "000042"
        assert cotisation.date_creation_carte == datetime.date(2026, 9, 1)

    def test_carte_sans_numero_refusee(self, directeur_client, famille_bureau, unite_familiale):
        famille, _t, _e = famille_bureau
        erreurs = _erreurs(_ajouter(directeur_client, famille, unite_familiale, carte="on", numero=""))
        assert "numero" in erreurs

    def test_numero_de_carte_suivant_propose(self, directeur_client, famille_bureau, unite_familiale):
        famille, _t, _e = famille_bureau
        _ajouter(directeur_client, famille, unite_familiale, carte="on", numero="000042")
        form = directeur_client.get(reverse("famille_cotisations_ajouter", args=[famille.pk])).context["form"]
        assert form.fields["numero"].initial == "000043"

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the next card number is computed from the LAST membership only. A membership without card "
        "(no number) in between makes the numbering restart at 1, so card numbers get duplicated."
    ))
    def test_numero_de_carte_suivant_apres_une_adhesion_sans_carte(self, directeur_client, famille_bureau,
                                                                   unite_familiale):
        famille, _t, _e = famille_bureau
        _ajouter(directeur_client, famille, unite_familiale, carte="on", numero="42")
        _ajouter(directeur_client, famille, unite_familiale)
        form = directeur_client.get(reverse("famille_cotisations_ajouter", args=[famille.pk])).context["form"]
        assert form.fields["numero"].initial == "43"

    def test_adhesion_facturee(self, directeur_client, famille_bureau, structure, activite):
        famille, _t, enfant = famille_bureau
        type_cotisation = _creer_type(directeur_client, nom="Adhésion", type="individu", structure=structure,
                                      activite=activite.pk)
        unite = _unite_en_cours(directeur_client, type_cotisation, type_tarif="MONTANT", montant="15")
        cotisation = _ajouter(directeur_client, famille, unite, individu=enfant, facturer="on",
                              label_prestation="Adhésion - Année en cours", montant="15",
                              date_facturation="2026-09-01")
        prestation = cotisation.prestation
        assert prestation.categorie == "cotisation"
        assert (prestation.famille, prestation.individu, prestation.activite) == (famille, enfant, activite)
        assert prestation.label == "Adhésion - Année en cours"
        assert prestation.montant == prestation.montant_initial == Decimal("15")
        assert prestation.date == datetime.date(2026, 9, 1)

    def test_facturation_sans_label_refusee(self, directeur_client, famille_bureau, unite_familiale):
        famille, _t, _e = famille_bureau
        erreurs = _erreurs(_ajouter(directeur_client, famille, unite_familiale, facturer="on", label_prestation=""))
        assert "label_prestation" in erreurs
        assert not Prestation.objects.exists()

    def test_modifier_le_montant_met_a_jour_la_prestation(self, directeur_client, famille_bureau, unite_familiale):
        famille, _t, _e = famille_bureau
        cotisation = _ajouter(directeur_client, famille, unite_familiale, facturer="on", label_prestation="Adhésion",
                              montant="15")
        url, data = _donnees_modification(directeur_client, cotisation, montant="20")
        assert data["facturer"] is True and data["prestation"] == cotisation.prestation_id
        assert directeur_client.post(url, data).status_code == 302
        cotisation.refresh_from_db()
        assert cotisation.prestation.montant == Decimal("20")
        assert Prestation.objects.count() == 1

    def test_ne_plus_facturer_supprime_la_prestation(self, directeur_client, famille_bureau, unite_familiale):
        famille, _t, _e = famille_bureau
        cotisation = _ajouter(directeur_client, famille, unite_familiale, facturer="on", label_prestation="Adhésion",
                              montant="15")
        url, data = _donnees_modification(directeur_client, cotisation)
        del data["facturer"]
        assert directeur_client.post(url, data).status_code == 302
        cotisation.refresh_from_db()
        assert cotisation.prestation is None
        assert not Prestation.objects.exists()

    def test_suppression_supprime_la_prestation(self, directeur_client, famille_bureau, unite_familiale):
        famille, _t, _e = famille_bureau
        cotisation = _ajouter(directeur_client, famille, unite_familiale, facturer="on", label_prestation="Adhésion",
                              montant="15")
        directeur_client.post(reverse("famille_cotisations_supprimer", args=[famille.pk, cotisation.pk]))
        assert not Cotisation.objects.exists()
        assert not Prestation.objects.exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: deleting a paid membership deletes its prestation, which cascades to the Ventilation: the payment "
        "is silently detached (the family shows a credit). Same issue as famille_prestations.Supprimer, reached "
        "here through Cotisation.delete()."
    ))
    def test_adhesion_reglee_non_supprimable(self, directeur_client, famille_bureau, unite_familiale):
        famille, _t, _e = famille_bureau
        cotisation = _ajouter(directeur_client, famille, unite_familiale, facturer="on", label_prestation="Adhésion",
                              montant="15")
        ventilation = _regler(famille, cotisation.prestation, Decimal("15"))
        directeur_client.post(reverse("famille_cotisations_supprimer", args=[famille.pk, cotisation.pk]))
        assert Cotisation.objects.filter(pk=cotisation.pk).exists()
        assert type(ventilation).objects.filter(pk=ventilation.pk).exists()

    def test_adhesion_deposee_non_supprimable(self, directeur_client, famille_bureau, unite_familiale):
        famille, _t, _e = famille_bureau
        cotisation = _ajouter(directeur_client, famille, unite_familiale)
        cotisation.depot_cotisation = DepotCotisations.objects.create(nom="Dépôt", date=datetime.date(2026, 10, 1))
        cotisation.save()
        response = directeur_client.post(reverse("famille_cotisations_supprimer", args=[famille.pk, cotisation.pk]),
                                         follow=True)
        assert Cotisation.objects.filter(pk=cotisation.pk).exists()
        assert "déjà incluse dans un dépôt" in response.content.decode()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the edit form keeps 'depot_cotisation' in its fields (fields='__all__') but no longer renders it. "
        "Saving a deposited membership (e.g. to fix a typo in the observations) posts no deposit and silently "
        "removes it from its deposit, whose quantity is not updated."
    ))
    def test_modifier_une_adhesion_deposee_la_laisse_dans_son_depot(self, directeur_client, famille_bureau,
                                                                   unite_familiale):
        famille, _t, _e = famille_bureau
        cotisation = _ajouter(directeur_client, famille, unite_familiale)
        depot = DepotCotisations.objects.create(nom="Dépôt", date=datetime.date(2026, 10, 1))
        cotisation.depot_cotisation = depot
        cotisation.save()
        url, data = _donnees_modification(directeur_client, cotisation, observations="Payée en espèces")
        assert directeur_client.post(url, data).status_code == 302
        cotisation.refresh_from_db()
        assert cotisation.observations == "Payée en espèces"
        assert cotisation.depot_cotisation == depot

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (périmètre): the fiche famille list shows 'Accès interdit' instead of the actions for a membership "
        "of another structure's type, but the delete URL is not protected: the director can delete it."
    ))
    def test_adhesion_d_une_autre_structure_non_supprimable(self, directeur_client, famille_bureau):
        famille, _t, _e = famille_bureau
        type_autre = TypeCotisation.objects.create(nom="Adhésion d'ailleurs", structure=StructureFactory(nom="Autre"))
        unite_autre = UniteCotisation.objects.create(type_cotisation=type_autre, nom="2026", duree="j0-m0-a1")
        cotisation = Cotisation.objects.create(famille=famille, type_cotisation=type_autre, unite_cotisation=unite_autre,
                                               date_debut=_aujourdhui(), date_fin=_aujourdhui() + relativedelta(years=1))
        directeur_client.post(reverse("famille_cotisations_supprimer", args=[famille.pk, cotisation.pk]))
        assert Cotisation.objects.filter(pk=cotisation.pk).exists()


# ===========================================================================
# 3. Adhésion à jour exigée : notification de la famille et du directeur
# ===========================================================================

@pytest.mark.django_db
class TestAdhesionManquante:
    def test_adhesion_individuelle_demandee_pour_l_enfant_inscrit(self, directeur_client, famille_bureau,
                                                                  adhesion_requise):
        famille, _t, enfant = famille_bureau
        assert _manquantes_fiche(directeur_client, famille) == ["Adhésion de %s" % enfant.prenom]

    def test_adhesion_familiale_demandee_une_seule_fois(self, directeur_client, famille_bureau, activite,
                                                        type_familial, unite_familiale):
        famille, titulaire, _e = famille_bureau
        InscriptionFactory(famille=famille, individu=titulaire, activite=activite, date_debut=datetime.date(2020, 1, 1))
        activite.cotisations.add(type_familial)
        assert _manquantes_fiche(directeur_client, famille) == ["Adhésion familiale"]

    def test_lien_de_saisie_rapide(self, directeur_client, famille_bureau, adhesion_requise):
        famille, _t, enfant = famille_bureau
        response = directeur_client.get(reverse("famille_resume", args=[famille.pk]))
        manquante = response.context["cotisations_manquantes"][0]
        assert str(manquante["href"]) == reverse("famille_cotisations_saisie_rapide",
                                                 args=[famille.pk, adhesion_requise.pk, enfant.pk])

    def test_l_adhesion_saisie_leve_l_alerte(self, directeur_client, famille_bureau, adhesion_requise,
                                             unite_individuelle):
        famille, _t, enfant = famille_bureau
        _ajouter(directeur_client, famille, unite_individuelle, individu=enfant)
        assert _manquantes_fiche(directeur_client, famille) == []

    def test_l_adhesion_d_un_autre_membre_ne_compte_pas(self, directeur_client, famille_bureau, adhesion_requise,
                                                        unite_individuelle):
        famille, titulaire, enfant = famille_bureau
        _ajouter(directeur_client, famille, unite_individuelle, individu=titulaire)
        assert _manquantes_fiche(directeur_client, famille) == ["Adhésion de %s" % enfant.prenom]

    def test_adhesion_expiree_ou_future_ne_compte_pas(self, directeur_client, famille_bureau, adhesion_requise):
        famille, _t, enfant = famille_bureau
        passee = _creer_unite(directeur_client, adhesion_requise, nom="2020", date_debut="2020-01-01",
                              date_fin="2020-12-31")
        future = _creer_unite(directeur_client, adhesion_requise, nom="2099", date_debut="2099-01-01",
                              date_fin="2099-12-31")
        _ajouter(directeur_client, famille, passee, individu=enfant)
        _ajouter(directeur_client, famille, future, individu=enfant)
        assert _manquantes_fiche(directeur_client, famille) == ["Adhésion de %s" % enfant.prenom]

    def test_une_des_adhesions_requises_suffit(self, directeur_client, famille_bureau, activite, adhesion_requise,
                                               type_familial, unite_familiale):
        """When several types are required, the inscription is in order as soon as one of them is up to date."""
        famille, _t, _e = famille_bureau
        activite.cotisations.add(type_familial)
        assert len(_manquantes_fiche(directeur_client, famille)) == 2
        _ajouter(directeur_client, famille, unite_familiale)
        assert _manquantes_fiche(directeur_client, famille) == []

    def test_pas_d_adhesion_demandee_pour_une_inscription_terminee(self, directeur_client, famille_bureau,
                                                                   adhesion_requise):
        famille, _t, enfant = famille_bureau
        Inscription.objects.filter(famille=famille).update(date_fin=datetime.date(2021, 6, 30))
        assert _manquantes_fiche(directeur_client, famille) == []

    def test_pas_d_adhesion_pour_une_activite_qui_n_en_exige_pas(self, directeur_client, famille_bureau,
                                                                 type_individuel, unite_individuelle):
        famille, _t, _e = famille_bureau
        assert _manquantes_fiche(directeur_client, famille) == []


@pytest.mark.django_db
class TestPortail:
    def test_page_masquee_par_defaut(self, famille_bureau, adhesion_requise):
        famille, _t, _e = famille_bureau
        accueil = _portail(famille).get(reverse("portail_accueil"))
        assert reverse("portail_cotisations") not in accueil.content.decode()
        assert not accueil.context.get("cotisations_manquantes")

    def test_alerte_sur_l_accueil(self, famille_bureau, adhesion_requise, page_adhesions):
        famille, _t, enfant = famille_bureau
        accueil = _portail(famille).get(reverse("portail_accueil"))
        assert [c["label"] for c in accueil.context["cotisations_manquantes"]] == ["Adhésion de %s" % enfant.prenom]
        assert reverse("portail_cotisations") in accueil.content.decode()

    def test_page_adhesions_a_fournir(self, famille_bureau, adhesion_requise, page_adhesions):
        famille, _t, enfant = famille_bureau
        assert _a_fournir_portail(famille) == ["Adhésion de %s" % enfant.prenom]

    def test_etape_completer_mon_dossier(self, famille_bureau, adhesion_requise, page_adhesions):
        famille, _t, enfant = famille_bureau
        response = _portail(famille).get(reverse("portail_completer_dossier"))
        etape = next(e for e in response.context["etapes"] if e["code"] == "cotisations")
        assert etape["nbre"] == 1
        assert [c["label"] for c in etape["cotisations_fournir"]] == ["Adhésion de %s" % enfant.prenom]

    def test_l_adhesion_saisie_par_le_directeur_leve_l_alerte(self, directeur_client, famille_bureau,
                                                              adhesion_requise, unite_individuelle, page_adhesions):
        famille, _t, enfant = famille_bureau
        _ajouter(directeur_client, famille, unite_individuelle, individu=enfant)
        assert _a_fournir_portail(famille) == []
        assert not _portail(famille).get(reverse("portail_accueil")).context["cotisations_manquantes"]

    def test_pas_d_adhesion_demandee_pour_un_membre_masque(self, famille_bureau, adhesion_requise, page_adhesions):
        famille, _t, enfant = famille_bureau
        famille.individus_masques.add(enfant)
        assert _a_fournir_portail(famille) == []

    def test_liste_des_adhesions_de_la_famille(self, directeur_client, famille_bureau, unite_individuelle):
        famille, _t, enfant = famille_bureau
        cotisation = _ajouter(directeur_client, famille, unite_individuelle, individu=enfant, carte="on",
                              numero="000007", facturer="on", label_prestation="Adhésion 2026", montant="10")
        _u, autre, ratt_autre = create_famille_complete(username="autre_famille")
        _ajouter(directeur_client, autre, unite_individuelle, individu=ratt_autre[1].individu)
        response = _portail(famille).get(reverse("portail_cotisations"))
        assert list(response.context["liste_cotisations"]) == [cotisation]
        html = response.content.decode()
        assert "Adhésion 2026" in html and "000007" in html and enfant.prenom in html

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the portal 'Liste des dernières adhésions' shows prestation.label as title: a membership which "
        "is not billed (free membership) has an empty title. The director's lists fall back on "
        "'<type> - <unité>'."
    ))
    def test_adhesion_gratuite_a_un_intitule(self, directeur_client, famille_bureau, unite_familiale):
        famille, _t, _e = famille_bureau
        _ajouter(directeur_client, famille, unite_familiale)
        html = _portail(famille).get(reverse("portail_cotisations")).content.decode()
        assert "Adhésion familiale - Année en cours" in html


@pytest.mark.django_db
class TestPrefacturationPortail:
    """A billed membership whose unit allows 'préfacturation' can be paid on the portal before any invoice."""

    def _a_regler(self, famille):
        response = _portail(famille).get(reverse("portail_facturation"))
        assert response.status_code == 200
        return [(p.label, p.solde) for p in response.context["liste_cotisations_prefacturation"]]

    def _adhesion_facturee(self, client, famille, prefacturation):
        type_cotisation = TypeCotisation.objects.get(nom="Adhésion familiale")
        unite = _unite_en_cours(client, type_cotisation, nom="Unité %s" % prefacturation, type_tarif="MONTANT",
                                montant="25", **({"prefacturation": "on"} if prefacturation else {}))
        return _ajouter(client, famille, unite, facturer="on", label_prestation="Adhésion 2026", montant="25")

    def test_adhesion_prefacturee_a_regler(self, directeur_client, famille_bureau, type_familial):
        famille, _t, _e = famille_bureau
        self._adhesion_facturee(directeur_client, famille, prefacturation=True)
        assert self._a_regler(famille) == [("Adhésion 2026", Decimal("25"))]

    def test_adhesion_sans_prefacturation_attend_la_facture(self, directeur_client, famille_bureau, type_familial):
        famille, _t, _e = famille_bureau
        self._adhesion_facturee(directeur_client, famille, prefacturation=False)
        assert self._a_regler(famille) == []

    def test_reglement_partiel_puis_total(self, directeur_client, famille_bureau, type_familial):
        famille, _t, _e = famille_bureau
        cotisation = self._adhesion_facturee(directeur_client, famille, prefacturation=True)
        _regler(famille, cotisation.prestation, Decimal("10"))
        assert self._a_regler(famille) == [("Adhésion 2026", Decimal("15"))]
        _regler(famille, cotisation.prestation, Decimal("15"))
        assert self._a_regler(famille) == []

    def test_adhesion_d_une_autre_famille_invisible(self, directeur_client, famille_bureau, type_familial):
        famille, _t, _e = famille_bureau
        _u, autre, _r = create_famille_complete(username="autre_famille")
        self._adhesion_facturee(directeur_client, autre, prefacturation=True)
        assert self._a_regler(famille) == []


# ===========================================================================
# 4. Saisie par lot
# ===========================================================================

def _appliquer_lot(client, type_cotisation, unite, lignes, **options):
    debut, fin = unite.Get_dates_validite()
    form_options = {"unite_cotisation": str(unite.pk), "date_debut": debut.strftime("%d/%m/%Y"),
                    "date_fin": fin.strftime("%d/%m/%Y"), "date_creation_carte": _aujourdhui().strftime("%d/%m/%Y"),
                    "numero": "1", "date_facturation": _aujourdhui().strftime("%d/%m/%Y"), "label_prestation": "",
                    "montant": "0.0", "observations": ""}
    form_options.update(options)
    return client.post(reverse("ajax_saisie_lot_cotisations_appliquer"), {
        "idtype_cotisation": type_cotisation.pk, "form_options": json.dumps(form_options),
        "lignes_cochees": json.dumps(lignes)}, **AJAX)


@pytest.mark.django_db
class TestSaisieParLot:
    def test_choix_du_type_oriente_vers_la_bonne_liste(self, directeur_client, type_familial, type_individuel):
        url = reverse("saisie_lot_cotisations")
        familial = directeur_client.post(url, {"type_cotisation": type_familial.pk})
        individuel = directeur_client.post(url, {"type_cotisation": type_individuel.pk})
        assert familial.url == reverse("saisie_lot_cotisations_familles", args=[type_familial.pk])
        assert individuel.url == reverse("saisie_lot_cotisations_individus", args=[type_individuel.pk])

    def test_lot_d_adhesions_familiales_avec_carte_et_facturation(self, directeur_client, famille_bureau,
                                                                  type_familial, unite_familiale):
        famille, _t, _e = famille_bureau
        _u, autre, _r = create_famille_complete(username="autre_famille")
        response = _appliquer_lot(directeur_client, type_familial, unite_familiale, [famille.pk, autre.pk],
                                  carte="on", numero="100", facturer="on", label_prestation="Adhésion", montant="12")
        assert response.json() == {"success": True}
        cotisations = Cotisation.objects.order_by("pk")
        assert [(c.famille, c.individu, c.numero) for c in cotisations] == [(famille, None, "100"), (autre, None, "101")]
        assert all(c.prestation.montant == Decimal("12") and c.prestation.famille == c.famille for c in cotisations)
        assert all((c.date_debut, c.date_fin) == unite_familiale.Get_dates_validite() for c in cotisations)

    def test_lot_d_adhesions_individuelles(self, directeur_client, famille_bureau, type_individuel,
                                           unite_individuelle):
        famille, titulaire, enfant = famille_bureau
        ratt = famille.rattachement_set.get(individu=enfant)
        response = _appliquer_lot(directeur_client, type_individuel, unite_individuelle, [ratt.pk], carte="on",
                                  numero="7")
        assert response.json() == {"success": True}
        cotisation = Cotisation.objects.get()
        assert (cotisation.famille, cotisation.individu, cotisation.numero) == (famille, enfant, "7")
        assert cotisation.prestation is None

    def test_sans_beneficiaire_coche(self, directeur_client, type_familial, unite_familiale):
        response = _appliquer_lot(directeur_client, type_familial, unite_familiale, [])
        assert response.status_code == 401
        assert "cocher au moins un" in response.json()["erreur"]
        assert not Cotisation.objects.exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: for an individual type, the form's clean() stops at the (expected) 'individu' error before "
        "normalising the card fields: memberships created by batch get a card number and date even when "
        "'Carte d'adhérent > Créer' is unchecked (the hidden fields are still posted by the page)."
    ))
    def test_lot_individuel_sans_carte(self, directeur_client, famille_bureau, type_individuel, unite_individuelle):
        famille, _t, enfant = famille_bureau
        ratt = famille.rattachement_set.get(individu=enfant)
        _appliquer_lot(directeur_client, type_individuel, unite_individuelle, [ratt.pk])
        cotisation = Cotisation.objects.get()
        assert (cotisation.numero, cotisation.date_creation_carte) == (None, None)

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the batch form rejects a type of another structure (not in the director's types), but clean() "
        "then reads cleaned_data['type_cotisation'] unguarded: KeyError, 500 instead of the error message."
    ))
    def test_lot_d_un_type_d_une_autre_structure_refuse(self, directeur_client, famille_bureau):
        famille, _t, _e = famille_bureau
        type_autre = TypeCotisation.objects.create(nom="Adhésion d'ailleurs", structure=StructureFactory(nom="Autre"))
        unite_autre = UniteCotisation.objects.create(type_cotisation=type_autre, nom="2026", duree="j0-m0-a1")
        response = _appliquer_lot(directeur_client, type_autre, unite_autre, [famille.pk])
        assert response.status_code == 401
        assert not Cotisation.objects.exists()


# ===========================================================================
# 5. Dépôts d'adhésions
# ===========================================================================

def _creer_depot(client, nom="Dépôt octobre", **extra):
    data = {"nom": nom, "date": "2026-10-15", "observations": ""}
    data.update(extra)
    response = client.post(reverse("depots_cotisations_ajouter"), data)
    depot = DepotCotisations.objects.get(nom=nom)
    assert response.url == reverse("depots_cotisations_consulter", args=[depot.pk])
    return depot


def _deposer(client, depot, *cotisations):
    return client.post(reverse("depots_cotisations_ajouter_cotisation", args=[depot.pk]),
                       {"selections": json.dumps([c.pk for c in cotisations])})


@pytest.fixture
def deux_adhesions(directeur_client, famille_bureau, unite_familiale):
    famille, _t, _e = famille_bureau
    _u, autre, _r = create_famille_complete(username="autre_famille")
    return _ajouter(directeur_client, famille, unite_familiale), _ajouter(directeur_client, autre, unite_familiale)


@pytest.mark.django_db
class TestDepots:
    def test_ajouter_des_adhesions_au_depot(self, directeur_client, deux_adhesions):
        depot = _creer_depot(directeur_client)
        _deposer(directeur_client, depot, *deux_adhesions)
        depot.refresh_from_db()
        assert depot.quantite == 2
        assert set(Cotisation.objects.filter(depot_cotisation=depot)) == set(deux_adhesions)
        consulter = directeur_client.get(reverse("depots_cotisations_consulter", args=[depot.pk]))
        assert "<b>2 adhésions</b>" in consulter.context["stats"]

    def test_seules_les_adhesions_non_deposees_sont_proposees(self, directeur_client, deux_adhesions):
        premiere, seconde = deux_adhesions
        _deposer(directeur_client, _creer_depot(directeur_client), premiere)
        page = directeur_client.get(reverse("depots_cotisations_ajouter_cotisation",
                                            args=[_creer_depot(directeur_client, nom="Second").pk]))
        assert list(page.context["view"].get_queryset()) == [seconde]

    def test_retirer_une_adhesion_du_depot(self, directeur_client, deux_adhesions):
        premiere, seconde = deux_adhesions
        depot = _creer_depot(directeur_client)
        _deposer(directeur_client, depot, premiere, seconde)
        directeur_client.post(reverse("depots_cotisations_supprimer_cotisation", args=[depot.pk, premiere.pk]))
        depot.refresh_from_db()
        premiere.refresh_from_db()
        assert premiere.depot_cotisation is None
        assert Cotisation.objects.filter(pk=premiere.pk).exists()
        assert depot.quantite == 1

    def test_retirer_plusieurs_adhesions(self, directeur_client, deux_adhesions):
        depot = _creer_depot(directeur_client)
        _deposer(directeur_client, depot, *deux_adhesions)
        directeur_client.post(reverse("depots_cotisations_supprimer_plusieurs_cotisations", kwargs={
            "iddepot": depot.pk, "listepk": ";".join(str(c.pk) for c in deux_adhesions)}))
        depot.refresh_from_db()
        assert depot.quantite == 0
        assert Cotisation.objects.count() == 2

    def test_depot_non_vide_non_supprimable(self, directeur_client, deux_adhesions):
        depot = _creer_depot(directeur_client)
        _deposer(directeur_client, depot, deux_adhesions[0])
        directeur_client.post(reverse("depots_cotisations_supprimer", args=[depot.pk]))
        assert DepotCotisations.objects.filter(pk=depot.pk).exists()

    def test_depot_vide_supprimable(self, directeur_client):
        depot = _creer_depot(directeur_client)
        directeur_client.post(reverse("depots_cotisations_supprimer", args=[depot.pk]))
        assert not DepotCotisations.objects.exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the selection page only lists memberships not deposited yet, but its POST accepts any id: a "
        "membership already in deposit A is moved to deposit B and A keeps its old quantity."
    ))
    def test_une_adhesion_ne_change_pas_de_depot_en_douce(self, directeur_client, deux_adhesions):
        premiere, _seconde = deux_adhesions
        depot_a = _creer_depot(directeur_client, nom="A")
        _deposer(directeur_client, depot_a, premiere)
        depot_b = _creer_depot(directeur_client, nom="B")
        _deposer(directeur_client, depot_b, premiere)
        premiere.refresh_from_db()
        depot_a.refresh_from_db()
        assert premiere.depot_cotisation == depot_a
        assert depot_a.quantite == 1

    @pytest.mark.xfail(strict=True, reason=(
        "À CONFIRMER: 'Verrouillage du dépôt' is only displayed (lock icon in the list); a locked deposit can "
        "still receive or lose memberships. Expected: a locked deposit is frozen."
    ))
    def test_depot_verrouille_fige(self, directeur_client, deux_adhesions):
        premiere, seconde = deux_adhesions
        depot = _creer_depot(directeur_client)
        _deposer(directeur_client, depot, premiere)
        depot.verrouillage = True
        depot.save()
        _deposer(directeur_client, depot, seconde)
        directeur_client.post(reverse("depots_cotisations_supprimer_cotisation", args=[depot.pk, premiere.pk]))
        assert list(Cotisation.objects.filter(depot_cotisation=depot)) == [premiere]


# ===========================================================================
# 6. Suivi par le directeur
# ===========================================================================

def _liste_manquantes(client, activites, date=None):
    response = client.post(reverse("liste_cotisations_manquantes"), {
        "date": (date or _aujourdhui()).isoformat(), "masquer_complets": "on", "presents": "",
        "choix_activites": "activites", "liste_activites": [a.pk for a in activites],
    })
    assert response.status_code == 200
    return {ligne[0]: ligne[1] for ligne in response.context["datatable"].lignes}


@pytest.mark.django_db
class TestListeAdhesionsManquantes:
    def test_famille_sans_adhesion_listee(self, directeur_client, activite, famille_bureau, adhesion_requise):
        famille, _t, enfant = famille_bureau
        assert _liste_manquantes(directeur_client, [activite]) == {famille.nom: "Adhésion de %s" % enfant.prenom}

    def test_famille_a_jour_masquee(self, directeur_client, activite, famille_bureau, adhesion_requise,
                                    unite_individuelle):
        famille, _t, enfant = famille_bureau
        _ajouter(directeur_client, famille, unite_individuelle, individu=enfant)
        assert _liste_manquantes(directeur_client, [activite]) == {}

    def test_date_de_reference(self, directeur_client, activite, famille_bureau, adhesion_requise):
        """A membership valid in 2026 does not cover a reference date in 2027."""
        famille, _t, enfant = famille_bureau
        annee = _creer_unite(directeur_client, adhesion_requise, nom="2026", date_debut="2026-01-01",
                             date_fin="2026-12-31")
        _ajouter(directeur_client, famille, annee, individu=enfant)
        assert _liste_manquantes(directeur_client, [activite], date=datetime.date(2026, 6, 1)) == {}
        assert famille.nom in _liste_manquantes(directeur_client, [activite], date=datetime.date(2027, 6, 1))

    def test_autres_activites_ignorees(self, directeur_client, structure, activite, famille_bureau,
                                       adhesion_requise):
        autre_activite = ActiviteFactory(structure=structure, nom="Séjour")
        assert _liste_manquantes(directeur_client, [autre_activite]) == {}

    @pytest.mark.xfail(strict=True, reason=(
        "À CONFIRMER: the director's list ignores the end of the inscriptions (the family page and the portal "
        "do not ask for a membership once the inscription is over), so last years' children stay listed forever."
    ))
    def test_inscription_terminee_non_listee(self, directeur_client, activite, famille_bureau, adhesion_requise):
        famille, _t, _e = famille_bureau
        Inscription.objects.filter(famille=famille).update(date_fin=datetime.date(2021, 6, 30))
        assert _liste_manquantes(directeur_client, [activite]) == {}

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (périmètre): the activity selection is not checked against the director's structures: posting "
        "another structure's activity lists its families and their missing memberships."
    ))
    def test_activite_d_une_autre_structure_refusee(self, directeur_client, adhesion_requise):
        autre_activite = ActiviteFactory(structure=StructureFactory(nom="Autre"), nom="Ailleurs")
        autre_activite.cotisations.add(adhesion_requise)
        _u, autre, ratt = create_famille_complete(username="autre_famille")
        InscriptionFactory(famille=autre, individu=ratt[1].individu, activite=autre_activite,
                           date_debut=datetime.date(2020, 1, 1))
        assert _liste_manquantes(directeur_client, [autre_activite]) == {}
