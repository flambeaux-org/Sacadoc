"""Bulk inscription operations of the bureau (director).

Covers:
- individus/views/inscriptions_activite_lot.py: "Créer des inscriptions en lot" (list + inscription_button);
- individus/views/inscriptions_modifier.py: "Modifier des inscriptions par lot" (selection, list, AJAX Appliquer);
- individus/views/inscriptions_changer_groupe.py: "Changer de groupe par lot" (selection, list, AJAX Appliquer);
- fiche_individu/views/individu_appliquer_forfait_date.py: applying a dated forfait from the fiche individu.

Business rules under test: what is written in the database (inscriptions, prestations, consommations),
the director's perimeter (only the activities of his structures, even with forged pks), duplicates and
invalid inputs.
"""

import datetime
import json
from decimal import Decimal

import pytest
from core.models import (
    CategorieTarif,
    CombiTarif,
    Consommation,
    Inscription,
    NomTarif,
    Ouverture,
    Prestation,
    Rattachement,
    Tarif,
    TarifLigne,
    Unite,
)
from django.core.exceptions import MultipleObjectsReturned
from django.test import Client, RequestFactory
from django.urls import reverse
from tests.bureau.conftest import AJAX
from tests.unit.factories import (
    ActiviteFactory,
    GroupeFactory,
    InscriptionFactory,
    StructureFactory,
    create_famille_complete,
)

AUJOURDHUI = datetime.date.today()


def _messages(response):
    return [str(m) for m in response.context["messages"]] if response.context else []


def _queryset(view_class, user, **kwargs):
    """Rows of a crud.Liste as its datatable would get them (the table itself is loaded by AJAX)."""
    request = RequestFactory().get("/")
    request.user = user
    view = view_class()
    view.setup(request, **kwargs)
    return list(view.get_queryset())


@pytest.fixture
def camp(db, structure):
    """An activity of the director's structure: groups A and B, one tarif category, one 120 € tarif."""
    activite = ActiviteFactory(structure=structure, nom="Camp d'été", date_debut=datetime.date(2026, 7, 1),
                               date_fin=datetime.date(2026, 12, 31))
    groupe_a = GroupeFactory(activite=activite, nom="Groupe A", ordre=1)
    groupe_b = GroupeFactory(activite=activite, nom="Groupe B", ordre=2)
    categorie = CategorieTarif.objects.create(activite=activite, nom="Normal")
    nom = NomTarif.objects.create(activite=activite, nom="Séjour")
    tarif = Tarif.objects.create(activite=activite, nom_tarif=nom, date_debut=datetime.date(2026, 1, 1),
                                 description="Séjour complet")
    tarif.categories_tarifs.add(categorie)
    TarifLigne.objects.create(activite=activite, tarif=tarif, montant_unique=Decimal("120"))
    return {"activite": activite, "groupe_a": groupe_a, "groupe_b": groupe_b, "categorie": categorie, "tarif": tarif}


@pytest.fixture
def enfants(famille_bureau, activite):
    """Two children of two families, both already inscribed on the director's `activite`."""
    famille1, _t, enfant1 = famille_bureau
    _user, famille2, ratt = create_famille_complete(username="famille_deux")
    enfant2 = ratt[1].individu
    InscriptionFactory(famille=famille2, individu=enfant2, activite=activite, date_debut=datetime.date(2020, 1, 1))
    return [(famille1, enfant1), (famille2, enfant2)]


@pytest.fixture
def activite_voisine(db):
    """An activity of a structure the director does not belong to, fully configured."""
    activite = ActiviteFactory(structure=StructureFactory(nom="Structure voisine"), nom="Activité voisine")
    groupe = GroupeFactory(activite=activite)
    categorie = CategorieTarif.objects.create(activite=activite, nom="Normal")
    nom = NomTarif.objects.create(activite=activite, nom="Voisin")
    tarif = Tarif.objects.create(activite=activite, nom_tarif=nom, date_debut=datetime.date(2026, 1, 1),
                                 description="Tarif voisin")
    tarif.categories_tarifs.add(categorie)
    TarifLigne.objects.create(activite=activite, tarif=tarif, montant_unique=Decimal("50"))
    return {"activite": activite, "groupe": groupe, "categorie": categorie, "tarif": tarif}


# ---------------------------------------------------------------------------
# Créer des inscriptions en lot
# ---------------------------------------------------------------------------

def _url_lot(activite, groupe, tarifs, individus):
    return reverse("inscription_button", kwargs={
        "activite": str(activite.pk), "groupe": str(groupe.pk),
        "tarif": ",".join(str(t.pk) for t in tarifs),
        "listepk": ",".join(str(getattr(i, "pk", i)) for i in individus),
    })


def _lot(client, camp, individus, tarifs=None, groupe=None):
    url = _url_lot(camp["activite"], groupe or camp["groupe_a"], tarifs or [camp["tarif"]], individus)
    return client.get(url, follow=True)


@pytest.mark.django_db
class TestInscriptionsEnLot:
    def test_la_liste_propose_les_individus_de_mes_structures(self, directeur, enfants, activite_voisine):
        from individus.views.inscriptions_activite_lot import Liste

        _user, famille, ratt = create_famille_complete(username="voisine")
        InscriptionFactory(famille=famille, individu=ratt[1].individu, activite=activite_voisine["activite"])
        individus = {r.individu_id for r in _queryset(Liste, directeur)}
        assert {enfant.pk for _f, enfant in enfants} <= individus
        assert ratt[1].individu.pk not in individus

    def test_la_page_ne_propose_que_mes_activites(self, directeur_client, camp, activite_voisine):
        url = reverse("inscriptions_activite_lot", kwargs={"activite": "A%d" % camp["activite"].pk})
        response = directeur_client.get(url)
        assert response.status_code == 200
        activites = [pk for pk, _nom in response.context["liste_activites"]]
        assert camp["activite"].pk in activites
        assert activite_voisine["activite"].pk not in activites
        assert [pk for pk, _nom in response.context["liste_groupes"]] == [camp["groupe_a"].pk, camp["groupe_b"].pk]
        assert [pk for pk, _nom in response.context["liste_tarifs"]] == [camp["tarif"].pk]

    def test_inscrire_en_lot_cree_les_inscriptions_et_les_prestations(self, directeur_client, enfants, camp):
        response = _lot(directeur_client, camp, [enfant for _f, enfant in enfants])
        assert response.redirect_chain[-1][0] == reverse("inscriptions_activite_lot")
        assert sum("bien été enregistrée" in m for m in _messages(response)) == 2

        for famille, enfant in enfants:
            inscription = Inscription.objects.get(individu=enfant, activite=camp["activite"])
            assert inscription.famille == famille
            assert inscription.groupe == camp["groupe_a"]
            assert inscription.categorie_tarif == camp["categorie"]
            assert inscription.statut == "ok"
            assert inscription.date_debut == AUJOURDHUI
            prestation = Prestation.objects.get(individu=enfant, activite=camp["activite"])
            assert (prestation.famille, prestation.tarif) == (famille, camp["tarif"])
            assert prestation.montant == Decimal("120")
            assert prestation.label == "Séjour complet"
            assert prestation.forfait == 1

    def test_plusieurs_tarifs_creent_une_prestation_chacun(self, directeur_client, enfants, camp):
        nom = NomTarif.objects.create(activite=camp["activite"], nom="Option")
        option = Tarif.objects.create(activite=camp["activite"], nom_tarif=nom, date_debut=datetime.date(2026, 1, 1),
                                      description="Option canoë")
        TarifLigne.objects.create(activite=camp["activite"], tarif=option, montant_unique=Decimal("30"))
        _famille, enfant = enfants[0]
        _lot(directeur_client, camp, [enfant], tarifs=[camp["tarif"], option])
        montants = sorted(Prestation.objects.filter(individu=enfant, activite=camp["activite"])
                          .values_list("montant", flat=True))
        assert montants == [Decimal("30"), Decimal("120")]

    def test_individu_deja_inscrit_n_est_pas_inscrit_deux_fois(self, directeur_client, enfants, camp):
        famille, enfant = enfants[0]
        Inscription.objects.create(famille=famille, individu=enfant, activite=camp["activite"],
                                   groupe=camp["groupe_b"], date_debut=datetime.date(2026, 7, 1))
        response = _lot(directeur_client, camp, [enfant for _f, enfant in enfants])
        assert any("déjà inscrit" in m for m in _messages(response))
        assert Inscription.objects.filter(individu=enfant, activite=camp["activite"]).count() == 1
        assert not Prestation.objects.filter(individu=enfant, activite=camp["activite"]).exists()
        # The other child of the batch is still inscribed
        assert Inscription.objects.filter(individu=enfants[1][1], activite=camp["activite"]).exists()

    def test_inscriptions_multiples_autorisees_par_l_activite(self, directeur_client, enfants, camp):
        camp["activite"].inscriptions_multiples = True
        camp["activite"].save()
        famille, enfant = enfants[0]
        Inscription.objects.create(famille=famille, individu=enfant, activite=camp["activite"],
                                   groupe=camp["groupe_b"], date_debut=datetime.date(2026, 7, 1))
        _lot(directeur_client, camp, [enfant])
        assert Inscription.objects.filter(individu=enfant, activite=camp["activite"]).count() == 2

    @pytest.mark.xfail(strict=True, reason=(
        "À CONFIRMER: the batch refuses any existing inscription on the activity, even one that ended "
        "(check_inscriptions_existantes ignores dates), whereas the fiche individu form accepts a new "
        "inscription after a finished one."
    ))
    def test_inscription_terminee_n_empeche_pas_une_nouvelle_inscription(self, directeur_client, enfants, camp):
        famille, enfant = enfants[0]
        Inscription.objects.create(famille=famille, individu=enfant, activite=camp["activite"],
                                   groupe=camp["groupe_a"], date_debut=datetime.date(2025, 1, 1),
                                   date_fin=datetime.date(2025, 12, 31))
        _lot(directeur_client, camp, [enfant])
        assert Inscription.objects.filter(individu=enfant, activite=camp["activite"]).count() == 2

    def test_activite_sans_categorie_de_tarif_refusee(self, directeur_client, enfants, camp):
        camp["categorie"].delete()
        _famille, enfant = enfants[0]
        response = _lot(directeur_client, camp, [enfant])
        assert any("Aucune catégorie tarifaire" in m for m in _messages(response))
        assert not Inscription.objects.filter(individu=enfant, activite=camp["activite"]).exists()

    def test_individu_inconnu_signale(self, directeur_client, enfants, camp):
        response = _lot(directeur_client, camp, [999999])
        assert any("Merci de selectionner" in m for m in _messages(response))
        assert not Inscription.objects.filter(activite=camp["activite"]).exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: inscription_button (lancer_inscriptions) is a plain function view with no login / "
        "category / permission check, mapped to a GET URL: an anonymous visitor (or a portail family) "
        "can create inscriptions and prestations for any individu by forging the URL."
    ))
    def test_anonyme_ne_peut_pas_inscrire_en_lot(self, enfants, camp):
        _famille, enfant = enfants[0]
        Client().get(_url_lot(camp["activite"], camp["groupe_a"], [camp["tarif"]], [enfant]))
        assert not Inscription.objects.filter(individu=enfant, activite=camp["activite"]).exists()

    @pytest.mark.xfail(strict=True, reason="BUG: same as above for a logged-in portail family.")
    def test_une_famille_du_portail_ne_peut_pas_inscrire_en_lot(self, enfants, camp):
        famille, enfant = enfants[0]
        client = Client()
        client.force_login(famille.utilisateur)
        client.get(_url_lot(camp["activite"], camp["groupe_a"], [camp["tarif"]], [enfant]))
        assert not Inscription.objects.filter(individu=enfant, activite=camp["activite"]).exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: lancer_inscriptions never checks that the activity (nor the group / tarifs) belongs to "
        "the director's structures: a forged URL inscribes children on another structure's activity."
    ))
    def test_activite_d_une_autre_structure_refusee(self, directeur_client, enfants, activite_voisine):
        _famille, enfant = enfants[0]
        directeur_client.get(_url_lot(activite_voisine["activite"], activite_voisine["groupe"],
                                      [activite_voisine["tarif"]], [enfant]))
        assert not Inscription.objects.filter(individu=enfant, activite=activite_voisine["activite"]).exists()

    @pytest.mark.xfail(strict=True, raises=MultipleObjectsReturned, reason=(
        "BUG: lancer_inscriptions finds the family with Rattachement.objects.get(individu=...): a child "
        "attached to two families (separated parents) crashes the batch with a 500."
    ))
    def test_individu_rattache_a_deux_familles(self, directeur_client, enfants, camp):
        famille, enfant = enfants[0]
        _user, autre, _ratt = create_famille_complete(username="autre_parent", avec_enfant=False)
        Rattachement.objects.create(individu=enfant, famille=autre, categorie=2)
        response = _lot(directeur_client, camp, [enfant])
        assert response.status_code == 200

    @pytest.mark.xfail(strict=True, raises=TarifLigne.DoesNotExist, reason=(
        "BUG: a tarif without TarifLigne crashes the batch (TarifLigne.objects.get) with a 500, after "
        "the inscription of the current child was already written."
    ))
    def test_tarif_sans_ligne_de_calcul(self, directeur_client, enfants, camp):
        TarifLigne.objects.filter(tarif=camp["tarif"]).delete()
        _famille, enfant = enfants[0]
        response = _lot(directeur_client, camp, [enfant])
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Modifier des inscriptions par lot
# ---------------------------------------------------------------------------

def _inscrire(famille, enfant, camp, groupe=None, debut=datetime.date(2026, 7, 1), fin=None):
    return Inscription.objects.create(famille=famille, individu=enfant, activite=camp["activite"],
                                      groupe=groupe or camp["groupe_a"], categorie_tarif=camp["categorie"],
                                      date_debut=debut, date_fin=fin)


@pytest.fixture
def inscriptions_camp(enfants, camp):
    return [_inscrire(famille, enfant, camp) for famille, enfant in enfants]


def _consommation(inscription, date, unite):
    return Consommation.objects.create(individu=inscription.individu, inscription=inscription,
                                       activite=inscription.activite, date=date, unite=unite,
                                       groupe=inscription.groupe, etat="reservation",
                                       categorie_tarif=inscription.categorie_tarif)


@pytest.fixture
def unite(camp):
    return Unite.objects.create(activite=camp["activite"], ordre=1, nom="Journée", abrege="J")


def _modifier(client, camp, inscriptions, **options):
    return client.post(reverse("ajax_inscriptions_modifier"), {
        "inscriptions_cochees": json.dumps([i.pk for i in inscriptions]),
        "form_options": json.dumps(options),
        "idactivite": camp["activite"].pk,
    }, **AJAX)


@pytest.mark.django_db
class TestModifierParLot:
    def test_selection_ne_propose_que_mes_activites(self, directeur_client, camp, activite_voisine):
        queryset = directeur_client.get(reverse("inscriptions_modifier")).context["form"].fields["activite"].queryset
        assert camp["activite"] in queryset
        assert activite_voisine["activite"] not in queryset

    def test_selection_redirige_vers_la_liste(self, directeur_client, camp):
        response = directeur_client.post(reverse("inscriptions_modifier"), {"activite": camp["activite"].pk})
        assert response["Location"] == reverse("inscriptions_modifier_liste", args=[camp["activite"].pk])

    def test_liste_des_inscriptions_de_l_activite(self, directeur_client, directeur, inscriptions_camp, camp):
        from individus.views.inscriptions_modifier import Liste

        response = directeur_client.get(reverse("inscriptions_modifier_liste", args=[camp["activite"].pk]))
        assert response.status_code == 200
        # Only the groups / categories of the activity are offered
        options = response.context["form_options"]
        assert list(options.fields["groupe"].queryset) == [camp["groupe_a"], camp["groupe_b"]]
        assert list(options.fields["categorie_tarif"].queryset) == [camp["categorie"]]
        assert set(_queryset(Liste, directeur, idactivite=camp["activite"].pk)) == set(inscriptions_camp)

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: inscriptions_modifier_liste only filters on the idactivite of the URL: a director can list "
        "(and then modify) the inscriptions of another structure's activity."
    ))
    def test_liste_d_une_activite_d_une_autre_structure_interdite(self, directeur_client, activite_voisine):
        url = reverse("inscriptions_modifier_liste", args=[activite_voisine["activite"].pk])
        assert directeur_client.get(url).status_code in (403, 404)

    def test_modifier_la_date_de_fin(self, directeur_client, inscriptions_camp, camp):
        coche, non_coche = inscriptions_camp
        response = _modifier(directeur_client, camp, [coche], modifier_date_fin=True, date_fin="2026-08-31")
        assert response.json() == {"success": True}
        coche.refresh_from_db()
        non_coche.refresh_from_db()
        assert coche.date_fin == datetime.date(2026, 8, 31)
        assert non_coche.date_fin is None

    def test_modifier_la_date_de_debut_et_le_groupe(self, directeur_client, inscriptions_camp, camp):
        response = _modifier(directeur_client, camp, inscriptions_camp, modifier_date_debut=True,
                             date_debut="2026-07-15", modifier_groupe=True, groupe=camp["groupe_b"].pk)
        assert response.status_code == 200
        for inscription in inscriptions_camp:
            inscription.refresh_from_db()
            assert inscription.date_debut == datetime.date(2026, 7, 15)
            assert inscription.groupe == camp["groupe_b"]

    def test_le_groupe_des_consommations_suit_quand_demande(self, directeur_client, inscriptions_camp, camp, unite):
        inscription = inscriptions_camp[0]
        conso = _consommation(inscription, datetime.date(2026, 7, 10), unite)
        Ouverture.objects.create(activite=camp["activite"], unite=unite, groupe=camp["groupe_b"],
                                 date=datetime.date(2026, 7, 10))
        response = _modifier(directeur_client, camp, [inscription], modifier_groupe=True,
                             groupe=camp["groupe_b"].pk, action_conso="MODIFIER_TOUT")
        assert response.status_code == 200
        conso.refresh_from_db()
        assert conso.groupe == camp["groupe_b"]

    def test_consommations_sur_un_groupe_ferme_refusees(self, directeur_client, inscriptions_camp, camp, unite):
        inscription = inscriptions_camp[0]
        conso = _consommation(inscription, datetime.date(2026, 7, 10), unite)
        response = _modifier(directeur_client, camp, [inscription], modifier_groupe=True,
                             groupe=camp["groupe_b"].pk, action_conso="MODIFIER_TOUT")
        assert response.status_code == 401
        assert "10/07/2026" in response.json()["erreur"]
        conso.refresh_from_db()
        assert conso.groupe == camp["groupe_a"]

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: when the consommations cannot be moved, Appliquer returns an error *after* having already "
        "bulk-updated the inscriptions' group: the inscription and its consommations end up in "
        "different groups although the user was told the change was impossible."
    ))
    def test_refus_des_consommations_ne_modifie_pas_l_inscription(self, directeur_client, inscriptions_camp,
                                                                  camp, unite):
        inscription = inscriptions_camp[0]
        _consommation(inscription, datetime.date(2026, 7, 10), unite)
        response = _modifier(directeur_client, camp, [inscription], modifier_groupe=True,
                             groupe=camp["groupe_b"].pk, action_conso="MODIFIER_TOUT")
        assert response.status_code == 401
        inscription.refresh_from_db()
        assert inscription.groupe == camp["groupe_a"]

    def test_date_de_fin_avant_des_consommations_refusee(self, directeur_client, inscriptions_camp, camp, unite):
        inscription = inscriptions_camp[0]
        _consommation(inscription, datetime.date(2026, 9, 10), unite)
        response = _modifier(directeur_client, camp, [inscription], modifier_date_fin=True, date_fin="2026-08-31")
        assert response.status_code == 401
        assert "1 consommations existent après" in response.json()["erreur"]
        inscription.refresh_from_db()
        assert inscription.date_fin is None

    def test_date_de_debut_apres_des_consommations_refusee(self, directeur_client, inscriptions_camp, camp, unite):
        inscription = inscriptions_camp[0]
        _consommation(inscription, datetime.date(2026, 7, 10), unite)
        response = _modifier(directeur_client, camp, [inscription], modifier_date_debut=True,
                             date_debut="2026-07-15")
        assert response.status_code == 401
        assert "avant la période" in response.json()["erreur"]

    def test_aucune_inscription_cochee(self, directeur_client, camp):
        response = _modifier(directeur_client, camp, [], modifier_date_fin=True, date_fin="2026-08-31")
        assert response.status_code == 401
        assert "cocher au moins une inscription" in response.json()["erreur"]

    @pytest.mark.parametrize("options", [
        {},  # no option ticked
        {"modifier_date_debut": True},  # date missing
        {"modifier_groupe": True},  # group missing
        {"modifier_date_fin": True, "date_fin": "2026-08-31", "action_conso": "MODIFIER_DATE"},
    ])
    def test_parametres_invalides_refuses(self, directeur_client, inscriptions_camp, camp, options):
        response = _modifier(directeur_client, camp, inscriptions_camp, **options)
        assert response.status_code == 401
        assert "renseigner correctement" in response.json()["erreur"]

    @pytest.mark.xfail(strict=True, raises=KeyError, reason=(
        "BUG: Formulaire_options.clean() reads cleaned_data['groupe'] without checking the field validated: "
        "a group outside the activity (invalid choice) crashes with a KeyError (500) instead of a 401. "
        "Nothing is modified either way."
    ))
    def test_groupe_d_une_autre_activite_refuse(self, directeur_client, inscriptions_camp, camp, activite_voisine):
        response = _modifier(directeur_client, camp, inscriptions_camp, modifier_groupe=True,
                             groupe=activite_voisine["groupe"].pk)
        assert response.status_code == 401
        inscriptions_camp[0].refresh_from_db()
        assert inscriptions_camp[0].groupe == camp["groupe_a"]

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: Formulaire_options never checks date_fin >= date_debut: a batch can give inscriptions an "
        "end date before their start date."
    ))
    def test_date_de_fin_avant_la_date_de_debut_refusee(self, directeur_client, inscriptions_camp, camp):
        response = _modifier(directeur_client, camp, inscriptions_camp, modifier_date_fin=True, date_fin="2026-06-01")
        assert response.status_code == 401

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: Appliquer modifies every pk of inscriptions_cochees without checking that they belong to "
        "idactivite or to the director's structures: forged pks change other structures' inscriptions."
    ))
    def test_inscription_d_une_autre_structure_non_modifiee(self, directeur_client, camp, inscriptions_camp,
                                                            activite_voisine):
        _user, famille, ratt = create_famille_complete(username="voisine")
        voisine = InscriptionFactory(famille=famille, individu=ratt[1].individu,
                                     activite=activite_voisine["activite"], groupe=activite_voisine["groupe"])
        _modifier(directeur_client, camp, [voisine], modifier_date_fin=True, date_fin="2026-08-31")
        voisine.refresh_from_db()
        assert voisine.date_fin is None

    def test_appel_non_ajax_refuse(self, directeur_client, camp):
        assert directeur_client.post(reverse("ajax_inscriptions_modifier"), {}).status_code == 400

    def test_famille_du_portail_refusee(self, famille_bureau, inscriptions_camp, camp):
        client = Client()
        client.force_login(famille_bureau[0].utilisateur)
        response = _modifier(client, camp, inscriptions_camp, modifier_date_fin=True, date_fin="2026-08-31")
        assert response.status_code == 403
        inscriptions_camp[0].refresh_from_db()
        assert inscriptions_camp[0].date_fin is None


# ---------------------------------------------------------------------------
# Changer de groupe par lot
# ---------------------------------------------------------------------------

def _changer_groupe(client, camp, inscriptions, groupe, date_application="2026-09-01"):
    return client.post(reverse("ajax_inscriptions_changer_groupe"), {
        "inscriptions_cochees": json.dumps([i.pk for i in inscriptions]),
        "form_options": json.dumps({"groupe": getattr(groupe, "pk", groupe), "date_application": date_application}),
        "idactivite": camp["activite"].pk,
    }, **AJAX)


@pytest.mark.django_db
class TestChangerGroupeParLot:
    def test_selection_ne_propose_que_mes_activites(self, directeur_client, camp, activite_voisine):
        url = reverse("inscriptions_changer_groupe")
        queryset = directeur_client.get(url).context["form"].fields["activite"].queryset
        assert camp["activite"] in queryset
        assert activite_voisine["activite"] not in queryset
        response = directeur_client.post(url, {"activite": camp["activite"].pk})
        assert response["Location"] == reverse("inscriptions_changer_groupe_liste", args=[camp["activite"].pk])

    def test_liste_des_inscriptions_de_l_activite(self, directeur_client, directeur, inscriptions_camp, camp):
        from individus.views.inscriptions_changer_groupe import Liste

        response = directeur_client.get(reverse("inscriptions_changer_groupe_liste", args=[camp["activite"].pk]))
        assert response.status_code == 200
        assert list(response.context["form_options"].fields["groupe"].queryset) == [camp["groupe_a"], camp["groupe_b"]]
        assert set(_queryset(Liste, directeur, idactivite=camp["activite"].pk)) == set(inscriptions_camp)

    def test_cloture_l_inscription_et_en_cree_une_nouvelle(self, directeur_client, inscriptions_camp, camp):
        ancienne = inscriptions_camp[0]
        response = _changer_groupe(directeur_client, camp, [ancienne], camp["groupe_b"])
        assert response.json() == {"success": True}

        ancienne.refresh_from_db()
        assert ancienne.groupe == camp["groupe_a"]
        assert ancienne.date_fin == datetime.date(2026, 8, 31)
        nouvelle = Inscription.objects.get(individu=ancienne.individu, activite=camp["activite"],
                                           groupe=camp["groupe_b"])
        assert nouvelle.pk != ancienne.pk
        assert (nouvelle.famille, nouvelle.categorie_tarif) == (ancienne.famille, ancienne.categorie_tarif)
        assert (nouvelle.date_debut, nouvelle.date_fin) == (datetime.date(2026, 9, 1), None)
        # The unticked inscription is untouched
        autre = inscriptions_camp[1]
        autre.refresh_from_db()
        assert (autre.groupe, autre.date_fin) == (camp["groupe_a"], None)
        assert Inscription.objects.filter(individu=autre.individu, activite=camp["activite"]).count() == 1

    def test_les_consommations_suivantes_sont_transferees(self, directeur_client, inscriptions_camp, camp, unite):
        ancienne = inscriptions_camp[0]
        avant = _consommation(ancienne, datetime.date(2026, 8, 20), unite)
        apres = _consommation(ancienne, datetime.date(2026, 9, 2), unite)
        Ouverture.objects.create(activite=camp["activite"], unite=unite, groupe=camp["groupe_b"],
                                 date=datetime.date(2026, 9, 2))
        assert _changer_groupe(directeur_client, camp, [ancienne], camp["groupe_b"]).status_code == 200

        nouvelle = Inscription.objects.get(individu=ancienne.individu, groupe=camp["groupe_b"])
        avant.refresh_from_db()
        apres.refresh_from_db()
        assert (avant.inscription, avant.groupe) == (ancienne, camp["groupe_a"])
        assert (apres.inscription, apres.groupe) == (nouvelle, camp["groupe_b"])

    def test_unite_fermee_sur_le_nouveau_groupe_refusee(self, directeur_client, inscriptions_camp, camp, unite):
        ancienne = inscriptions_camp[0]
        conso = _consommation(ancienne, datetime.date(2026, 9, 2), unite)
        response = _changer_groupe(directeur_client, camp, [ancienne], camp["groupe_b"])
        assert response.status_code == 401
        assert "02/09/2026" in response.json()["erreur"]
        ancienne.refresh_from_db()
        conso.refresh_from_db()
        assert ancienne.date_fin is None
        assert conso.inscription == ancienne
        assert not Inscription.objects.filter(groupe=camp["groupe_b"]).exists()

    def test_date_d_application_avant_le_debut_de_l_inscription_refusee(self, directeur_client, inscriptions_camp,
                                                                        camp):
        response = _changer_groupe(directeur_client, camp, inscriptions_camp, camp["groupe_b"],
                                   date_application="2026-06-01")
        assert response.status_code == 401
        assert "supérieure à la date d'application" in response.json()["erreur"]
        assert not Inscription.objects.filter(groupe=camp["groupe_b"]).exists()

    @pytest.mark.parametrize("groupe, date_application", [(None, "2026-09-01"), ("groupe_b", "")])
    def test_parametres_manquants_refuses(self, directeur_client, inscriptions_camp, camp, groupe, date_application):
        response = _changer_groupe(directeur_client, camp, inscriptions_camp, camp.get(groupe),
                                   date_application=date_application)
        assert response.status_code == 401
        assert "renseigner correctement" in response.json()["erreur"]

    def test_groupe_d_une_autre_activite_refuse(self, directeur_client, inscriptions_camp, camp, activite_voisine):
        response = _changer_groupe(directeur_client, camp, inscriptions_camp, activite_voisine["groupe"])
        assert response.status_code == 401

    def test_aucune_inscription_cochee(self, directeur_client, camp):
        assert _changer_groupe(directeur_client, camp, [], camp["groupe_b"]).status_code == 401

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: an inscription that already ended before the application date is not skipped: its date_fin "
        "is pushed forward to the day before the application date and a new open-ended inscription is "
        "created, re-inscribing a child who had left the activity."
    ))
    def test_inscription_terminee_n_est_pas_reouverte(self, directeur_client, enfants, camp):
        famille, enfant = enfants[0]
        terminee = _inscrire(famille, enfant, camp, debut=datetime.date(2026, 1, 1), fin=datetime.date(2026, 3, 31))
        _changer_groupe(directeur_client, camp, [terminee], camp["groupe_b"])
        terminee.refresh_from_db()
        assert terminee.date_fin == datetime.date(2026, 3, 31)
        assert not Inscription.objects.filter(individu=enfant, groupe=camp["groupe_b"]).exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: Appliquer closes and duplicates every pk of inscriptions_cochees without checking that they "
        "belong to idactivite or to the director's structures."
    ))
    def test_inscription_d_une_autre_structure_non_modifiee(self, directeur_client, camp, activite_voisine):
        _user, famille, ratt = create_famille_complete(username="voisine")
        voisine = InscriptionFactory(famille=famille, individu=ratt[1].individu, activite=activite_voisine["activite"],
                                     groupe=activite_voisine["groupe"], date_debut=datetime.date(2026, 1, 1))
        _changer_groupe(directeur_client, camp, [voisine], camp["groupe_b"])
        voisine.refresh_from_db()
        assert voisine.date_fin is None
        assert Inscription.objects.filter(individu=ratt[1].individu).count() == 1

    def test_appel_non_ajax_refuse(self, directeur_client):
        assert directeur_client.post(reverse("ajax_inscriptions_changer_groupe"), {}).status_code == 400


# ---------------------------------------------------------------------------
# Appliquer un forfait daté (fiche individu)
# ---------------------------------------------------------------------------

JOUR_1 = AUJOURDHUI + datetime.timedelta(days=30)
JOUR_2 = JOUR_1 + datetime.timedelta(days=1)


@pytest.fixture
def forfait(camp, unite):
    """A manual dated forfait (80 €) on the camp, covering two upcoming days of the 'Journée' unit."""
    activite = camp["activite"]
    nom = NomTarif.objects.create(activite=activite, nom="Forfait semaine")
    tarif = Tarif.objects.create(activite=activite, nom_tarif=nom, type="FORFAIT", forfait_saisie_manuelle=True,
                                 forfait_saisie_auto=False, methode="montant_unique",
                                 date_debut=datetime.date(2026, 1, 1), description="Semaine du 20 juillet")
    tarif.categories_tarifs.add(camp["categorie"])
    TarifLigne.objects.create(activite=activite, tarif=tarif, montant_unique=Decimal("80"))
    for jour in (JOUR_1, JOUR_2):
        combi = CombiTarif.objects.create(tarif=tarif, type="FORFAIT", date=jour)
        combi.unites.add(unite)
    return tarif


@pytest.fixture
def enfant_au_camp(enfants, camp):
    famille, enfant = enfants[0]
    inscription = _inscrire(famille, enfant, camp)
    return famille, enfant, inscription


def _url_forfait(famille, enfant):
    return reverse("individu_appliquer_forfait_date", args=[famille.pk, enfant.pk])


@pytest.mark.django_db
class TestAppliquerForfaitDate:
    def test_les_forfaits_de_l_individu_sont_proposes(self, directeur_client, enfant_au_camp, forfait, camp):
        famille, enfant, _i = enfant_au_camp
        response = directeur_client.get(_url_forfait(famille, enfant))
        assert response.status_code == 200
        dict_forfaits = response.context["form"].fields["forfaits"].widget.attrs["dict_forfaits"]
        assert [t.pk for t in dict_forfaits[camp["activite"].pk].tarifs] == [forfait.pk]

    def test_forfait_passe_masque_sauf_a_la_demande(self, directeur_client, enfant_au_camp, forfait, camp):
        CombiTarif.objects.filter(tarif=forfait).update(date=AUJOURDHUI - datetime.timedelta(days=60))
        famille, enfant, _i = enfant_au_camp
        url = _url_forfait(famille, enfant)
        assert directeur_client.get(url).context["form"].fields["forfaits"].widget.attrs["dict_forfaits"] == {}

        response = directeur_client.post(url, {"action": "afficher_forfaits_obsoletes",
                                               "afficher_forfaits_obsoletes": "on"})
        assert response.status_code == 200
        dict_forfaits = response.context["form"].fields["forfaits"].widget.attrs["dict_forfaits"]
        assert [t.pk for t in dict_forfaits[camp["activite"].pk].tarifs] == [forfait.pk]
        assert not Prestation.objects.filter(tarif=forfait).exists()

    def test_forfait_d_une_autre_categorie_non_propose(self, directeur_client, enfant_au_camp, forfait, camp):
        forfait.categories_tarifs.set([CategorieTarif.objects.create(activite=camp["activite"], nom="Réduit")])
        famille, enfant, _i = enfant_au_camp
        response = directeur_client.get(_url_forfait(famille, enfant))
        assert response.context["form"].fields["forfaits"].widget.attrs["dict_forfaits"] == {}

    def test_appliquer_le_forfait_cree_prestation_et_consommations(self, directeur_client, enfant_au_camp, forfait,
                                                                   camp, unite):
        famille, enfant, inscription = enfant_au_camp
        response = directeur_client.post(_url_forfait(famille, enfant), {"forfaits": str(forfait.pk)})
        assert response.status_code == 302
        assert response["Location"] == reverse("individu_inscriptions_liste", args=[famille.pk, enfant.pk])

        prestation = Prestation.objects.get(individu=enfant, tarif=forfait)
        assert prestation.famille == famille
        assert prestation.montant == Decimal("80")
        assert prestation.label == "Forfait semaine"
        assert prestation.forfait == 1
        assert prestation.date == JOUR_1
        consos = Consommation.objects.filter(inscription=inscription).order_by("date")
        assert [(c.date, c.unite, c.groupe, c.prestation) for c in consos] == [
            (JOUR_1, unite, camp["groupe_a"], prestation),
            (JOUR_2, unite, camp["groupe_a"], prestation),
        ]

    def test_forfait_a_suppression_auto(self, directeur_client, enfant_au_camp, forfait):
        forfait.forfait_suppression_auto = True
        forfait.save()
        famille, enfant, _i = enfant_au_camp
        directeur_client.post(_url_forfait(famille, enfant), {"forfaits": str(forfait.pk)})
        assert Prestation.objects.get(individu=enfant, tarif=forfait).forfait == 2

    def test_forfait_deja_applique_refuse(self, directeur_client, enfant_au_camp, forfait):
        famille, enfant, _i = enfant_au_camp
        directeur_client.post(_url_forfait(famille, enfant), {"forfaits": str(forfait.pk)})
        response = directeur_client.post(_url_forfait(famille, enfant), {"forfaits": str(forfait.pk)}, follow=True)
        assert any("des consommations existent déjà" in m for m in _messages(response))
        assert Prestation.objects.filter(individu=enfant, tarif=forfait).count() == 1
        assert Consommation.objects.filter(individu=enfant).count() == 2

    def test_aucun_forfait_coche(self, directeur_client, enfant_au_camp, forfait):
        famille, enfant, _i = enfant_au_camp
        response = directeur_client.post(_url_forfait(famille, enfant), {"forfaits": ""})
        assert response.status_code == 200
        assert any("au moins un forfait" in m for m in _messages(response))
        assert not Prestation.objects.filter(individu=enfant).exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the forfaits offered (and applicable) come from every inscription of the individu, "
        "whatever its structure: a director can bill a forfait of another structure's activity."
    ))
    def test_forfait_d_une_activite_d_une_autre_structure_refuse(self, directeur_client, enfant_au_camp,
                                                                 activite_voisine):
        famille, enfant, _i = enfant_au_camp
        voisine = activite_voisine["activite"]
        voisine.date_debut = datetime.date(2026, 7, 1)
        voisine.save()
        InscriptionFactory(famille=famille, individu=enfant, activite=voisine, groupe=activite_voisine["groupe"],
                           categorie_tarif=activite_voisine["categorie"])
        tarif = activite_voisine["tarif"]
        tarif.type, tarif.forfait_saisie_manuelle = "FORFAIT", True
        tarif.save()
        directeur_client.post(_url_forfait(famille, enfant), {"forfaits": str(tarif.pk)})
        assert not Prestation.objects.filter(individu=enfant, tarif=tarif).exists()
