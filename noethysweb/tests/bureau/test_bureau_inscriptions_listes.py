"""Global inscription lists of the bureau and their CRUD routes.

Covers individus/views/inscriptions_liste.py ("Inscriptions" list of all the director's inscriptions)
and individus/views/inscriptions_activite_liste.py ("Inscrits à une activité").

Business rules under test:
- a director only sees, edits and deletes the inscriptions of his own structures;
- the activity list only shows visible activities, can be narrowed to one group, and hides
  obsolete activities unless asked;
- an inscription with invoiced / attached prestations cannot be deleted;
- creating an inscription from these lists follows the same rules as from the fiche individu
  (prestation per tarif, no overlapping inscription).
"""

import datetime
from decimal import Decimal

import pytest
from core.models import CategorieTarif, Facture, Inscription, NomTarif, Prestation, Tarif, TarifLigne
from django.urls import reverse
from tests.bureau.conftest import AJAX, build_form_data
from tests.unit.factories import (
    ActiviteFactory,
    GroupeFactory,
    InscriptionFactory,
    StructureFactory,
    create_famille_complete,
)

COLONNES_LISTE = ["check", "idinscription", "date_debut", "individu", "famille", "activite", "groupe", "tarif",
                  "individu_ville", "famille_ville", "mail_famille", "statut", "actions"]
COLONNES_ACTIVITE = ["check", "idinscription", "date_debut", "date_fin", "individu", "date_naiss", "age", "mail",
                     "portable", "famille", "tel_parents", "mail_parents", "mail_famille", "groupe", "categorie_tarif",
                     "individu_ville", "famille_ville", "num_cotisation", "statut", "solde", "actions"]


def _datatable(client, url, colonnes):
    """Run the DataTables AJAX query of a MyDatatable list and return its rows as {column name: value} dicts."""
    params = {"draw": "1", "start": "0", "length": "100", "search[value]": "", "search[regex]": "false"}
    for index, name in enumerate(colonnes):
        params.update({
            f"columns[{index}][data]": str(index), f"columns[{index}][name]": name,
            f"columns[{index}][searchable]": "true", f"columns[{index}][orderable]": "true",
            f"columns[{index}][search][value]": "", f"columns[{index}][search][regex]": "false",
        })
    response = client.get(url, params, **AJAX)
    assert response.status_code == 200
    return [{name: ligne[str(index)] for index, name in enumerate(colonnes)} | {"pk": ligne["DT_RowId"]}
            for ligne in response.json()["data"]]


def _messages(response):
    return [str(m) for m in response.context["messages"]]


def _facturer(inscription, numero=1, **kwargs):
    facture = Facture.objects.create(famille=inscription.famille, numero=numero, date_edition=datetime.date(2026, 7, 1),
                                     date_debut=datetime.date(2026, 7, 1), date_fin=datetime.date(2026, 7, 31))
    return Prestation.objects.create(famille=inscription.famille, individu=inscription.individu,
                                     activite=inscription.activite, date=datetime.date(2026, 7, 1), label="Séjour",
                                     montant=Decimal("120"), facture=facture, **kwargs)


@pytest.fixture
def camp(db, structure):
    """A current activity of the director's structure with two groups and one 120 € tarif."""
    activite = ActiviteFactory(structure=structure, nom="Camp d'été", date_debut=datetime.date(2026, 1, 1),
                               date_fin=datetime.date(2099, 12, 31))
    louveteaux = GroupeFactory(activite=activite, nom="Louveteaux")
    eclaireurs = GroupeFactory(activite=activite, nom="Eclaireurs")
    categorie = CategorieTarif.objects.create(activite=activite, nom="Normal")
    nom = NomTarif.objects.create(activite=activite, nom="Formule")
    tarif = Tarif.objects.create(activite=activite, nom_tarif=nom, date_debut=datetime.date(2026, 1, 1),
                                 description="Séjour complet")
    tarif.categories_tarifs.add(categorie)
    TarifLigne.objects.create(activite=activite, tarif=tarif, montant_unique=Decimal("120"))
    return activite, louveteaux, eclaireurs, tarif


@pytest.fixture
def inscrits(db, organisateur, famille_bureau, camp):
    """Two children of two families on the camp (one per group), plus one inscription in another structure."""
    famille, _titulaire, enfant = famille_bureau
    activite, louveteaux, eclaireurs, _tarif = camp
    _user, famille2, ratt2 = create_famille_complete(username="famille_2")
    enfant2 = ratt2[1].individu
    louveteau = InscriptionFactory(famille=famille, individu=enfant, activite=activite, groupe=louveteaux,
                                   date_debut=datetime.date(2026, 7, 1))
    eclaireur = InscriptionFactory(famille=famille2, individu=enfant2, activite=activite, groupe=eclaireurs,
                                   date_debut=datetime.date(2026, 7, 1))
    voisine = ActiviteFactory(structure=StructureFactory(), nom="Activité voisine",
                              date_debut=datetime.date(2026, 1, 1), date_fin=datetime.date(2099, 12, 31))
    etrangere = InscriptionFactory(famille=famille, individu=enfant, activite=voisine,
                                   date_debut=datetime.date(2026, 7, 1))
    return {"louveteau": louveteau, "eclaireur": eclaireur, "etrangere": etrangere}


# ---------------------------------------------------------------------------
# "Inscriptions" (all the director's inscriptions)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestListeInscriptions:
    def test_page_accessible(self, directeur_client):
        assert directeur_client.get(reverse("inscriptions_liste")).status_code == 200

    def test_seules_les_inscriptions_de_mes_structures_sont_listees(self, directeur_client, inscrits, activite):
        pks = {ligne["pk"] for ligne in _datatable(directeur_client, reverse("inscriptions_liste"), COLONNES_LISTE)}
        assert inscrits["louveteau"].pk in pks
        assert inscrits["eclaireur"].pk in pks
        assert inscrits["etrangere"].pk not in pks
        # famille_bureau's own inscription on the director's "Centre de loisirs" is listed too
        assert Inscription.objects.get(activite=activite).pk in pks

    def test_contenu_d_une_ligne(self, directeur_client, inscrits, camp):
        inscrits["louveteau"].tarifs.add(camp[3])
        ligne = next(ligne for ligne in _datatable(directeur_client, reverse("inscriptions_liste"), COLONNES_LISTE)
                     if ligne["pk"] == inscrits["louveteau"].pk)
        assert ligne["activite"] == "Camp d'été"
        assert ligne["groupe"] == "Louveteaux"
        assert ligne["tarif"] == "Séjour complet"
        assert ligne["date_debut"] == "01/07/2026"
        assert "Valide" in ligne["statut"]
        assert reverse("inscriptions_supprimer", args=[inscrits["louveteau"].pk]) in ligne["actions"]
        # "Modifier" opens the inscriptions of the individual (fiche_individu's list view)
        assert reverse("inscriptions_modifier", kwargs={
            "idfamille": inscrits["louveteau"].famille_id, "idindividu": inscrits["louveteau"].individu_id,
        }) in ligne["actions"]

    def test_statut_refus_affiche(self, directeur_client, inscrits):
        Inscription.objects.filter(pk=inscrits["eclaireur"].pk).update(statut="refus")
        ligne = next(ligne for ligne in _datatable(directeur_client, reverse("inscriptions_liste"), COLONNES_LISTE)
                     if ligne["pk"] == inscrits["eclaireur"].pk)
        assert "Refus" in ligne["statut"]

    def test_lien_modifier_ouvre_la_fiche_individu(self, directeur_client, inscrits):
        inscription = inscrits["louveteau"]
        url = reverse("inscriptions_modifier", kwargs={"idfamille": inscription.famille_id,
                                                       "idindividu": inscription.individu_id})
        assert directeur_client.get(url).status_code == 200

    @pytest.mark.xfail(strict=True, raises=Exception, reason=(
        "BUG: inscriptions_liste.Ajouter uses fiche_individu's Formulaire without idindividu; "
        "Formulaire.__init__ then runs Individu.objects.get(pk=None) and the 'Ajouter' page crashes "
        "with Individu.DoesNotExist (500)."
    ))
    def test_page_ajouter_accessible(self, directeur_client):
        assert directeur_client.get(reverse("inscriptions_ajouter")).status_code == 200


@pytest.mark.django_db
class TestSupprimerInscription:
    def test_supprimer_une_inscription_sans_prestation(self, directeur_client, inscrits):
        url = reverse("inscriptions_supprimer", args=[inscrits["louveteau"].pk])
        assert directeur_client.get(url).context["erreurs_protection"] == []
        response = directeur_client.post(url)
        assert response.status_code == 302
        assert response["Location"] == reverse("inscriptions_liste")
        assert not Inscription.objects.filter(pk=inscrits["louveteau"].pk).exists()

    def test_suppression_inscription_facturee_signalee(self, directeur_client, inscrits):
        _facturer(inscrits["louveteau"])
        erreurs = directeur_client.get(reverse("inscriptions_supprimer", args=[inscrits["louveteau"].pk])).context[
            "erreurs_protection"]
        assert any("déjà facturées" in e for e in erreurs)

    def test_suppression_avec_prestation_non_facturee_signalee(self, directeur_client, inscrits):
        Prestation.objects.create(famille=inscrits["louveteau"].famille, individu=inscrits["louveteau"].individu,
                                  activite=inscrits["louveteau"].activite, date=datetime.date(2026, 7, 1),
                                  label="Séjour", montant=Decimal("120"), forfait=1)
        erreurs = directeur_client.get(reverse("inscriptions_supprimer", args=[inscrits["louveteau"].pk])).context[
            "erreurs_protection"]
        assert any("déjà associées" in e for e in erreurs)

    def test_les_forfaits_credits_ne_bloquent_pas_la_suppression(self, directeur_client, inscrits):
        Prestation.objects.create(famille=inscrits["louveteau"].famille, individu=inscrits["louveteau"].individu,
                                  activite=inscrits["louveteau"].activite, date=datetime.date(2026, 7, 1),
                                  label="Forfait", montant=Decimal("50"), forfait=2)
        url = reverse("inscriptions_supprimer", args=[inscrits["louveteau"].pk])
        assert directeur_client.get(url).context["erreurs_protection"] == []

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: crud.Supprimer only displays Check_protections() on the confirmation page; delete() never "
        "re-checks them, so a direct POST deletes an inscription whose prestations are invoiced "
        "(the prestation is then orphaned)."
    ))
    def test_suppression_inscription_facturee_refusee_cote_serveur(self, directeur_client, inscrits):
        _facturer(inscrits["louveteau"])
        directeur_client.post(reverse("inscriptions_supprimer", args=[inscrits["louveteau"].pk]))
        assert Inscription.objects.filter(pk=inscrits["louveteau"].pk).exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: inscriptions_liste.Supprimer has no structure check (unlike fiche_individu's Supprimer), "
        "so a director can open and POST the deletion of an inscription of another structure by its pk."
    ))
    def test_supprimer_inscription_d_une_autre_structure_interdit(self, directeur_client, inscrits):
        response = directeur_client.post(reverse("inscriptions_supprimer", args=[inscrits["etrangere"].pk]))
        assert response.status_code == 403
        assert Inscription.objects.filter(pk=inscrits["etrangere"].pk).exists()


@pytest.mark.django_db
class TestSupprimerPlusieursInscriptions:
    def _url(self, *inscriptions):
        return reverse("inscriptions_supprimer_plusieurs", args=[";".join(str(i.pk) for i in inscriptions)])

    def test_page_de_confirmation_liste_la_selection(self, directeur_client, inscrits):
        response = directeur_client.get(self._url(inscrits["louveteau"], inscrits["eclaireur"]))
        assert response.status_code == 200
        assert set(response.context["liste_objets"]) == {inscrits["louveteau"], inscrits["eclaireur"]}
        assert response.context["erreurs_protection"] == []

    def test_suppression_de_la_selection(self, directeur_client, inscrits):
        response = directeur_client.post(self._url(inscrits["louveteau"], inscrits["eclaireur"]))
        assert response.status_code == 302
        assert not Inscription.objects.filter(pk__in=[inscrits["louveteau"].pk, inscrits["eclaireur"].pk]).exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: inscriptions_liste.Supprimer_plusieurs defines no Check_protections(objets=...): the "
        "confirmation page does not warn about invoiced prestations, and the POST deletes the inscriptions."
    ))
    def test_suppression_multiple_protegee_si_facturee(self, directeur_client, inscrits):
        _facturer(inscrits["louveteau"])
        url = self._url(inscrits["louveteau"], inscrits["eclaireur"])
        assert directeur_client.get(url).context["erreurs_protection"] != []
        directeur_client.post(url)
        assert Inscription.objects.filter(pk=inscrits["louveteau"].pk).exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: crud.Supprimer_plusieurs.get_objets() filters on the pks of the URL only, without the "
        "director's structures: inscriptions of another structure can be deleted by forging the URL."
    ))
    def test_suppression_multiple_limitee_a_mes_structures(self, directeur_client, inscrits):
        directeur_client.post(self._url(inscrits["louveteau"], inscrits["etrangere"]))
        assert Inscription.objects.filter(pk=inscrits["etrangere"].pk).exists()


# ---------------------------------------------------------------------------
# "Inscrits à une activité"
# ---------------------------------------------------------------------------

def _url_activite(activite=None, groupe=None, obsoletes=False):
    if activite is None:
        return reverse("inscriptions_activite_liste")
    code = "%s%s" % (activite.pk, "A" if obsoletes else "")
    if groupe is None:
        return reverse("inscriptions_activite_liste", kwargs={"activite": code})
    return reverse("inscriptions_activite_liste", kwargs={"activite": code, "groupe": groupe})


@pytest.mark.django_db
class TestListeInscritsActivite:
    def test_page_sans_activite_selectionnee(self, directeur_client, inscrits):
        response = directeur_client.get(_url_activite())
        assert response.status_code == 200
        assert response.context["activite"] is None
        assert _datatable(directeur_client, _url_activite(), COLONNES_ACTIVITE) == []

    def test_choix_des_activites_limite_a_mes_structures_en_cours(self, directeur_client, inscrits, camp):
        passee = ActiviteFactory(structure=camp[0].structure, nom="Camp 2020", date_debut=datetime.date(2020, 7, 1),
                                 date_fin=datetime.date(2020, 7, 31))
        choix = dict(directeur_client.get(_url_activite()).context["liste_activites"])
        assert camp[0].pk in choix
        assert inscrits["etrangere"].activite_id not in choix
        assert passee.pk not in choix

    def test_activites_obsoletes_affichees_sur_demande(self, directeur_client, camp):
        passee = ActiviteFactory(structure=camp[0].structure, nom="Camp 2020", date_debut=datetime.date(2020, 7, 1),
                                 date_fin=datetime.date(2020, 7, 31))
        response = directeur_client.get(_url_activite(camp[0], obsoletes=True))
        assert response.context["afficher_obsoletes"] is True
        assert dict(response.context["liste_activites"])[passee.pk] == "Camp 2020 - Du 01/07/2020 au 31/07/2020"

    def test_activite_illimitee_libellee(self, directeur_client, camp):
        illimitee = ActiviteFactory(structure=camp[0].structure, nom="Club", date_debut=datetime.date(2020, 1, 1),
                                    date_fin=datetime.date(2999, 1, 1))
        choix = dict(directeur_client.get(_url_activite()).context["liste_activites"])
        assert choix[illimitee.pk] == "Club - Activité illimitée"

    @pytest.mark.xfail(strict=True, raises=AttributeError, reason=(
        "BUG: Liste.get_context_data() reads activite.date_fin.year for every activity of the "
        "structures when 'Afficher les activités obsolètes' is checked; Activite.date_fin is nullable, "
        "so one activity without end date makes the page crash (500)."
    ))
    def test_activite_sans_date_de_fin_avec_obsoletes(self, directeur_client, camp):
        ActiviteFactory(structure=camp[0].structure, nom="Sans fin", date_debut=datetime.date(2020, 1, 1),
                        date_fin=None)
        assert directeur_client.get(_url_activite(camp[0], obsoletes=True)).status_code == 200

    def test_inscrits_de_l_activite(self, directeur_client, inscrits, camp):
        response = directeur_client.get(_url_activite(camp[0]))
        assert response.context["activite"] == camp[0].pk
        assert response.context["impression_titre"] == "Camp d'été"
        assert [nom for _pk, nom in response.context["liste_groupes"]] == ["Tous les groupes", "Louveteaux",
                                                                          "Eclaireurs"]
        pks = {ligne["pk"] for ligne in _datatable(directeur_client, _url_activite(camp[0]), COLONNES_ACTIVITE)}
        assert pks == {inscrits["louveteau"].pk, inscrits["eclaireur"].pk}

    def test_filtre_par_groupe(self, directeur_client, inscrits, camp):
        url = _url_activite(camp[0], groupe=camp[1].pk)
        assert directeur_client.get(url).context["impression_introduction"] == "Louveteaux"
        assert [ligne["pk"] for ligne in _datatable(directeur_client, url, COLONNES_ACTIVITE)] == [
            inscrits["louveteau"].pk]

    def test_groupe_zero_affiche_tous_les_groupes(self, directeur_client, inscrits, camp):
        """The page's JS reloads with '/0' when "Tous les groupes" is selected."""
        url = _url_activite(camp[0], groupe=0)
        assert len(_datatable(directeur_client, url, COLONNES_ACTIVITE)) == 2

    def test_activite_d_une_autre_structure_vide(self, directeur_client, inscrits):
        url = _url_activite(inscrits["etrangere"].activite)
        assert _datatable(directeur_client, url, COLONNES_ACTIVITE) == []

    def test_activite_masquee_non_listee(self, directeur_client, inscrits, camp):
        camp[0].visible = False
        camp[0].save()
        assert _datatable(directeur_client, _url_activite(camp[0]), COLONNES_ACTIVITE) == []

    def test_solde_de_l_inscrit(self, directeur_client, inscrits, camp):
        _facturer(inscrits["louveteau"])
        lignes = {ligne["pk"]: ligne for ligne in _datatable(directeur_client, _url_activite(camp[0]),
                                                             COLONNES_ACTIVITE)}
        assert "badge-danger" in lignes[inscrits["louveteau"].pk]["solde"]
        assert "120" in lignes[inscrits["louveteau"].pk]["solde"]
        assert "badge-success" in lignes[inscrits["eclaireur"].pk]["solde"]

    def test_contacts_des_responsables(self, directeur_client, inscrits, camp):
        titulaire = inscrits["louveteau"].famille.rattachement_set.get(categorie=1).individu
        titulaire.tel_mobile = "06 00 00 00 00"
        titulaire.mail = "titulaire@test.org"
        titulaire.save()
        ligne = next(ligne for ligne in _datatable(directeur_client, _url_activite(camp[0]), COLONNES_ACTIVITE)
                     if ligne["pk"] == inscrits["louveteau"].pk)
        assert ligne["tel_parents"] == "%s : 06 00 00 00 00" % titulaire.prenom
        assert ligne["mail_parents"] == "%s : titulaire@test.org" % titulaire.prenom
        assert ligne["groupe"] == "Louveteaux"
        actions = ligne["actions"]
        assert reverse("inscriptions_activite_modifier", args=[camp[0].pk, inscrits["louveteau"].pk]) in actions
        assert reverse("inscriptions_activite_supprimer", args=[camp[0].pk, inscrits["louveteau"].pk]) in actions

    @pytest.mark.xfail(strict=True, raises=ValueError, reason=(
        "BUG: the 'inscriptions_activite_ajouter' route (individus/inscriptions_activite/ajouter/<activite>) "
        "is shadowed by 'inscriptions_activite/<activite>/<groupe>' declared before it in individus/urls.py: "
        "the list view receives activite='ajouter' and crashes (500)."
    ))
    def test_page_ajouter_inscrit(self, directeur_client, camp):
        response = directeur_client.get(reverse("inscriptions_activite_ajouter", args=[camp[0].pk]))
        assert response.status_code == 200
        assert "form" in response.context


@pytest.mark.django_db
class TestModifierInscritActivite:
    def _url(self, inscription):
        return reverse("inscriptions_activite_modifier", args=[inscription.activite_id, inscription.pk])

    def _post(self, client, inscription, **overrides):
        url = self._url(inscription)
        form = client.get(url).context["form"]
        data = build_form_data(form, **overrides)
        return client.post(url, data)

    def test_changer_de_groupe(self, directeur_client, inscrits, camp):
        inscription = inscrits["louveteau"]
        inscription.tarifs.add(camp[3])
        response = self._post(directeur_client, inscription, groupe=camp[2].pk, tarifs=[camp[3].pk])
        assert response.status_code == 302, response.context and response.context["form"].errors.as_json()
        assert response["Location"] == reverse("inscriptions_activite_liste")
        inscription.refresh_from_db()
        assert inscription.groupe == camp[2]

    def test_date_de_fin_avant_debut_refusee(self, directeur_client, inscrits, camp):
        inscription = inscrits["louveteau"]
        response = self._post(directeur_client, inscription, date_fin="2026-06-01", tarifs=[camp[3].pk])
        assert response.status_code == 200
        assert "date_fin" in response.context["form"].errors
        inscription.refresh_from_db()
        assert inscription.date_fin is None

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: inscriptions_activite_liste.Modifier is a plain crud.Modifier: no structure check "
        "(fiche_individu's Modifier.test_func has one), so a director can open an inscription of another "
        "structure (and, by posting one of his activities, move it into his structure)."
    ))
    def test_modifier_inscription_d_une_autre_structure_interdit(self, directeur_client, inscrits):
        assert directeur_client.get(self._url(inscrits["etrangere"])).status_code == 403

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: inscriptions_activite_liste.Modifier has no Check_protections (fiche_individu's Modifier "
        "refuses an inscription whose prestations are invoiced): an invoiced inscription can be modified here."
    ))
    def test_modifier_inscription_facturee_bloquee(self, directeur_client, inscrits, camp):
        inscription = inscrits["louveteau"]
        _facturer(inscription)
        directeur_client.post(self._url(inscription), {
            "individu": inscription.individu_id, "famille": inscription.famille_id, "activite": camp[0].pk,
            "groupe": camp[2].pk, "tarifs": [camp[3].pk], "date_debut": "2026-07-01", "statut": "ok",
        })
        inscription.refresh_from_db()
        assert inscription.groupe == camp[1]

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: inscriptions_activite_liste.Modifier does not run check_inscriptions_existantes(): "
        "an inscription can be extended over another inscription of the same child on the same activity."
    ))
    def test_chevauchement_refuse(self, directeur_client, inscrits, camp):
        inscription = inscrits["louveteau"]
        Inscription.objects.filter(pk=inscription.pk).update(date_fin=datetime.date(2026, 7, 31))
        InscriptionFactory(famille=inscription.famille, individu=inscription.individu, activite=camp[0],
                           groupe=camp[1], date_debut=datetime.date(2026, 9, 1))
        inscription.refresh_from_db()
        self._post(directeur_client, inscription, date_fin="2026-12-31", tarifs=[camp[3].pk])
        inscription.refresh_from_db()
        assert inscription.date_fin == datetime.date(2026, 7, 31)


@pytest.mark.django_db
class TestSupprimerInscritActivite:
    def _url(self, inscription):
        return reverse("inscriptions_activite_supprimer", args=[inscription.activite_id, inscription.pk])

    def test_supprimer_un_inscrit(self, directeur_client, inscrits):
        response = directeur_client.post(self._url(inscrits["louveteau"]))
        assert response.status_code == 302
        assert response["Location"] == reverse("inscriptions_activite_liste")
        assert not Inscription.objects.filter(pk=inscrits["louveteau"].pk).exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: inscriptions_activite_liste.Supprimer defines no Check_protections at all: the "
        "confirmation page does not warn about invoiced prestations (unlike the other inscription lists)."
    ))
    def test_suppression_inscription_facturee_signalee(self, directeur_client, inscrits):
        _facturer(inscrits["louveteau"])
        assert directeur_client.get(self._url(inscrits["louveteau"])).context["erreurs_protection"] != []

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: inscriptions_activite_liste.Supprimer has no structure check: an inscription of another "
        "structure can be deleted by its pk."
    ))
    def test_supprimer_inscription_d_une_autre_structure_interdit(self, directeur_client, inscrits):
        directeur_client.post(self._url(inscrits["etrangere"]))
        assert Inscription.objects.filter(pk=inscrits["etrangere"].pk).exists()

    def test_supprimer_plusieurs_inscrits(self, directeur_client, inscrits, camp):
        listepk = "%d;%d" % (inscrits["louveteau"].pk, inscrits["eclaireur"].pk)
        url = reverse("inscriptions_activite_supprimer_plusieurs", args=[camp[0].pk, listepk])
        assert set(directeur_client.get(url).context["liste_objets"]) == {inscrits["louveteau"], inscrits["eclaireur"]}
        assert directeur_client.post(url).status_code == 302
        assert not Inscription.objects.filter(activite=camp[0]).exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: inscriptions_activite_liste.Supprimer_plusieurs deletes every pk of the URL, including "
        "inscriptions of another structure (no structure filter in crud.Supprimer_plusieurs.get_objets())."
    ))
    def test_supprimer_plusieurs_limite_a_mes_structures(self, directeur_client, inscrits, camp):
        listepk = "%d;%d" % (inscrits["louveteau"].pk, inscrits["etrangere"].pk)
        directeur_client.post(reverse("inscriptions_activite_supprimer_plusieurs", args=[camp[0].pk, listepk]))
        assert Inscription.objects.filter(pk=inscrits["etrangere"].pk).exists()
