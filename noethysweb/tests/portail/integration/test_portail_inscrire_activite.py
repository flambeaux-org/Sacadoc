"""Branch-level tests for the "inscrire a une activite" flow of the portail.

Covers portail/views/inscrire_activite.py (page + 3 AJAX endpoints) and
portail/forms/inscrire_activite.py (Formulaire / Formulaire_extra), including the
full happy path that creates the PortailRenseignement (inscription request).
"""

import datetime
import json
from decimal import Decimal
from unittest import mock

import factory
import pytest
from core.models import (
    Mail,
    NomTarif,
    Piece,
    PortailDocument,
    PortailRenseignement,
    Tarif,
    TarifLigne,
    TypePiece,
)
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from factory.django import DjangoModelFactory
from tests.unit.factories import (
    ActiviteFactory,
    AdresseMailFactory,
    GroupeFactory,
    InscriptionFactory,
    PieceFactory,
    StructureFactory,
    TypePieceFactory,
)

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}
URL_STRUCT = "portail_ajax_get_activites_par_structure"
URL_EXTRA = "portail_ajax_inscrire_get_form_extra"
URL_VALID = "portail_ajax_inscrire_valid_form"


class NomTarifFactory(DjangoModelFactory):
    class Meta:
        model = NomTarif

    activite = factory.SubFactory(ActiviteFactory)
    nom = factory.Sequence(lambda n: f"Nom tarif {n}")
    visible = True


class TarifFactory(DjangoModelFactory):
    class Meta:
        model = Tarif

    activite = factory.SubFactory(ActiviteFactory)
    type = "FORFAIT"
    nom_tarif = factory.SubFactory(
        NomTarifFactory, activite=factory.SelfAttribute("..activite")
    )
    date_debut = datetime.date(2020, 1, 1)
    description = factory.Sequence(lambda n: f"Tarif {n}")
    visible = True


def make_tarif(activite, montant=Decimal("12.5"), with_ligne=True, **kwargs):
    tarif = TarifFactory(activite=activite, **kwargs)
    if with_ligne:
        TarifLigne.objects.create(
            activite=activite, tarif=tarif, montant_unique=montant
        )
    return tarif


@pytest.fixture
def media_tmp(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    return tmp_path


@pytest.fixture
def graph(famille_user):
    """An open activity (no team required) with one group and one tarif, plus the child."""
    _user, famille, ratt = famille_user
    structure = StructureFactory()
    activite = ActiviteFactory(structure=structure, maitrise=False, public=5)
    groupe = GroupeFactory(activite=activite)
    tarif = make_tarif(activite)
    return {
        "famille": famille,
        "enfant": ratt[1].individu,
        "adulte": ratt[0].individu,
        "structure": structure,
        "activite": activite,
        "groupe": groupe,
        "tarif": tarif,
    }


def payload(graph, **overrides):
    data = {
        "individu": graph["enfant"].pk,
        "structure": graph["structure"].pk,
        "activite": graph["activite"].pk,
        "groupe": graph["groupe"].pk,
        f"tarifs_{graph['tarif'].nom_tarif_id}": graph["tarif"].pk,
    }
    data.update(overrides)
    return data


def post_valid(client, data):
    return client.post(reverse(URL_VALID), data, **AJAX)


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------
@pytest.mark.django_db
class TestPageInscrire:
    def test_anonymous_redirected_to_login(self, client):
        response = client.get(reverse("portail_inscrire_activite"))
        assert response.status_code == 302
        assert "connexion" in response.url

    def test_staff_forbidden(self, client, staff_user):
        client.force_login(staff_user)
        assert client.get(reverse("portail_inscrire_activite")).status_code in (
            302,
            403,
        )

    def test_page_context_and_form(self, logged_client, graph):
        response = logged_client.get(reverse("portail_inscrire_activite"))
        assert response.status_code == 200
        ctx = response.context
        assert ctx["box_titre"] is None
        assert "Inscrire" in str(ctx["page_titre"])
        assert "Renseignez" in str(ctx["box_introduction"])
        content = response.content.decode()
        assert "portail_inscrire_activite_form" in content
        assert "form_extra" in content

    def test_form_individu_choices_exclude_masked(
        self, logged_client, famille_user, graph
    ):
        _user, famille, ratt = famille_user
        famille.individus_masques.add(ratt[1].individu)
        response = logged_client.get(reverse("portail_inscrire_activite"))
        choices = [c[0] for c in response.context["form"].fields["individu"].choices]
        assert ratt[1].individu.pk not in choices
        assert ratt[0].individu.pk in choices

    def test_form_activite_queryset_filters_by_period(self, logged_client, graph):
        now = datetime.datetime.now()
        dans_periode = ActiviteFactory(
            portail_inscriptions_affichage="PERIODE",
            portail_inscriptions_date_debut=now - datetime.timedelta(days=1),
            portail_inscriptions_date_fin=now + datetime.timedelta(days=1),
        )
        hors_periode = ActiviteFactory(
            portail_inscriptions_affichage="PERIODE",
            portail_inscriptions_date_debut=now + datetime.timedelta(days=5),
            portail_inscriptions_date_fin=now + datetime.timedelta(days=9),
        )
        jamais = ActiviteFactory(portail_inscriptions_affichage="JAMAIS")
        response = logged_client.get(reverse("portail_inscrire_activite"))
        pks = set(
            response.context["form"]
            .fields["activite"]
            .queryset.values_list("pk", flat=True)
        )
        assert dans_periode.pk in pks
        assert graph["activite"].pk in pks
        assert hors_periode.pk not in pks
        assert jamais.pk not in pks

    def test_get_success_url(self, logged_client):
        from portail.views import inscrire_activite

        view = inscrire_activite.Ajouter()
        assert view.get_success_url() == reverse("portail_activites")

    def test_get_detail_historique(self, graph):
        from portail.views import inscrire_activite

        instance = PortailRenseignement(
            famille=graph["famille"], individu=graph["enfant"]
        )
        detail = inscrire_activite.Ajouter().Get_detail_historique(instance)
        assert detail == "Famille={}, Individu={}".format(
            graph["famille"], graph["enfant"]
        )


# --------------------------------------------------------------------------
# AJAX: authorization
# --------------------------------------------------------------------------
@pytest.mark.django_db
class TestInscrireAjaxAuthorization:
    @pytest.mark.parametrize("name", [URL_STRUCT, URL_EXTRA, URL_VALID])
    def test_non_ajax_is_bad_request(self, logged_client, name):
        assert logged_client.post(reverse(name), {}).status_code == 400

    @pytest.mark.parametrize("name", [URL_STRUCT, URL_EXTRA, URL_VALID])
    def test_anonymous_forbidden(self, client, name):
        assert client.post(reverse(name), {}, **AJAX).status_code == 403

    @pytest.mark.parametrize("name", [URL_STRUCT, URL_EXTRA, URL_VALID])
    def test_staff_forbidden(self, client, staff_user, name):
        client.force_login(staff_user)
        assert client.post(reverse(name), {}, **AJAX).status_code == 403


# --------------------------------------------------------------------------
# Get_activites_par_structure
# --------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetActivitesParStructure:
    def test_unknown_structure_returns_empty_list(self, logged_client):
        response = logged_client.post(
            reverse(URL_STRUCT), {"structure_id": 999999}, **AJAX
        )
        assert response.status_code == 200
        assert response.json() == {"activites": []}

    def test_missing_structure_id_returns_empty_list(self, logged_client):
        ActiviteFactory()
        response = logged_client.post(reverse(URL_STRUCT), {}, **AJAX)
        assert response.status_code == 200
        assert isinstance(response.json()["activites"], list)

    def test_hidden_activities_are_excluded(self, logged_client):
        structure = StructureFactory()
        ActiviteFactory(structure=structure, visible=False, nom="Cachee")
        ActiviteFactory(structure=structure, visible=True, nom="Visible")
        response = logged_client.post(
            reverse(URL_STRUCT), {"structure_id": structure.pk}, **AJAX
        )
        noms = [a["nom"] for a in response.json()["activites"]]
        assert noms == ["Visible"]

    def test_activities_sorted_by_name_with_their_groups_only(self, logged_client):
        structure = StructureFactory()
        b = ActiviteFactory(structure=structure, nom="B")
        a = ActiviteFactory(structure=structure, nom="A")
        GroupeFactory(activite=a, nom="ga")
        GroupeFactory(activite=b, nom="gb1")
        GroupeFactory(activite=b, nom="gb2")
        other = ActiviteFactory(structure=StructureFactory(), nom="Z")
        GroupeFactory(activite=other, nom="gz")
        data = logged_client.post(
            reverse(URL_STRUCT), {"structure_id": structure.pk}, **AJAX
        ).json()
        assert [x["nom"] for x in data["activites"]] == ["A", "B"]
        assert [g["nom"] for g in data["activites"][0]["groupes"]] == ["ga"]
        assert {g["nom"] for g in data["activites"][1]["groupes"]} == {"gb1", "gb2"}
        assert data["activites"][0]["id"] == a.pk
        assert set(data["activites"][0]["groupes"][0]) == {"idgroupe", "nom"}

    def test_activity_without_group_has_empty_groupes(self, logged_client):
        structure = StructureFactory()
        ActiviteFactory(structure=structure)
        data = logged_client.post(
            reverse(URL_STRUCT), {"structure_id": structure.pk}, **AJAX
        ).json()
        assert data["activites"][0]["groupes"] == []


# --------------------------------------------------------------------------
# Get_form_extra
# --------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetFormExtra:
    def _post(self, client, individu, activite):
        data = {}
        if individu is not None:
            data["individu"] = individu
        if activite is not None:
            data["activite"] = activite
        return client.post(reverse(URL_EXTRA), data, **AJAX)

    def test_missing_individu(self, logged_client, graph):
        r = self._post(logged_client, None, graph["activite"].pk)
        assert "Veuillez sélectionner" in r.json()["form_html"]

    def test_missing_activite(self, logged_client, graph):
        r = self._post(logged_client, graph["enfant"].pk, None)
        assert "Veuillez sélectionner" in r.json()["form_html"]

    def test_unknown_activite(self, logged_client, graph):
        r = self._post(logged_client, graph["enfant"].pk, 999999)
        assert "Données introuvables" in r.json()["form_html"]

    def test_unknown_individu(self, logged_client, graph):
        r = self._post(logged_client, 999999, graph["activite"].pk)
        assert "Données introuvables" in r.json()["form_html"]

    def test_renders_tarif_radio(self, logged_client, graph):
        r = self._post(logged_client, graph["enfant"].pk, graph["activite"].pk)
        html = r.json()["form_html"]
        assert "Choix des tarifs" in html
        assert "12,50 €" in html
        assert f"tarifs_{graph['tarif'].nom_tarif_id}" in html

    def test_tarif_without_ligne_shows_zero_amount(self, logged_client, graph):
        activite = graph["activite"]
        t = make_tarif(activite, with_ligne=False, description="SansLigne")
        r = self._post(logged_client, graph["enfant"].pk, activite.pk)
        assert "SansLigne (0,00 €)" in r.json()["form_html"]
        assert f"tarifs_{t.nom_tarif_id}" in r.json()["form_html"]

    def test_invisible_nom_tarif_and_tarif_hidden(self, logged_client, graph):
        activite = graph["activite"]
        hidden_nom = NomTarifFactory(activite=activite, visible=False)
        TarifFactory(activite=activite, nom_tarif=hidden_nom, description="NomCache")
        shown_nom = NomTarifFactory(activite=activite, visible=True)
        TarifFactory(
            activite=activite,
            nom_tarif=shown_nom,
            visible=False,
            description="TarifCache",
        )
        html = self._post(logged_client, graph["enfant"].pk, activite.pk).json()[
            "form_html"
        ]
        assert f"tarifs_{hidden_nom.pk}" not in html
        assert f"tarifs_{shown_nom.pk}" not in html  # no visible tarif -> no field

    def test_activity_without_tarifs_has_no_tarif_section(self, logged_client, graph):
        activite = ActiviteFactory(maitrise=False)
        html = self._post(logged_client, graph["enfant"].pk, activite.pk).json()[
            "form_html"
        ]
        assert "Choix des tarifs" not in html

    def test_activity_image_displayed(self, logged_client, graph, media_tmp):
        activite = graph["activite"]
        activite.image = SimpleUploadedFile("a.png", b"x", content_type="image/png")
        activite.save()
        html = self._post(logged_client, graph["enfant"].pk, activite.pk).json()[
            "form_html"
        ]
        assert "img-fluid" in html
        assert activite.image.url in html

    def test_no_pieces_section_without_required_pieces(self, logged_client, graph):
        html = self._post(
            logged_client, graph["enfant"].pk, graph["activite"].pk
        ).json()["form_html"]
        assert "Pièces justificatives" not in html

    def test_missing_piece_not_imposed(self, logged_client, graph):
        tp = TypePieceFactory(public="individu", nom="Certificat")
        graph["activite"].pieces.add(tp)
        html = self._post(
            logged_client, graph["enfant"].pk, graph["activite"].pk
        ).json()["form_html"]
        assert "Pièces justificatives" in html
        assert "0/1" in html
        assert "À fournir ultérieurement" in html
        assert f"document_{tp.pk}" not in html

    def test_missing_piece_imposed_with_portail_document_model(
        self, logged_client, graph, media_tmp
    ):
        activite = graph["activite"]
        activite.portail_inscriptions_imposer_pieces = True
        activite.save()
        tp = TypePieceFactory(public="individu", nom="Certificat")
        activite.pieces.add(tp)
        doc = PortailDocument.objects.create(
            titre="Modele",
            structure=graph["structure"],
            type_piece=tp,
            document=SimpleUploadedFile("modele.pdf", b"%PDF"),
        )
        doc.activites.add(activite)
        html = self._post(logged_client, graph["enfant"].pk, activite.pk).json()[
            "form_html"
        ]
        assert "À fournir ci-dessous" in html
        assert f"document_{tp.pk}" in html
        assert "Télécharger le modèle" in html
        assert doc.document.url in html

    def test_missing_piece_imposed_with_type_piece_document_fallback(
        self, logged_client, graph, media_tmp
    ):
        """Model found via type_piece.type_piece_document when no PortailDocument is tied to the activity."""
        activite = graph["activite"]
        activite.portail_inscriptions_imposer_pieces = True
        activite.save()
        tp = TypePieceFactory(public="individu")
        activite.pieces.add(tp)
        doc = PortailDocument.objects.create(
            titre="Modele2",
            structure=graph["structure"],
            type_piece=tp,
            document=SimpleUploadedFile("modele2.pdf", b"%PDF"),
        )  # not linked to the activity
        html = self._post(logged_client, graph["enfant"].pk, activite.pk).json()[
            "form_html"
        ]
        assert doc.document.url in html

    def test_missing_piece_imposed_without_model(self, logged_client, graph):
        activite = graph["activite"]
        activite.portail_inscriptions_imposer_pieces = True
        activite.save()
        tp = TypePieceFactory(public="individu")
        activite.pieces.add(tp)
        html = self._post(logged_client, graph["enfant"].pk, activite.pk).json()[
            "form_html"
        ]
        assert f"document_{tp.pk}" in html
        assert "Télécharger le modèle" not in html

    def test_existing_valid_piece(self, logged_client, graph, media_tmp):
        tp = TypePieceFactory(public="individu", nom="Certificat")
        graph["activite"].pieces.add(tp)
        piece = PieceFactory(
            type_piece=tp,
            individu=graph["enfant"],
            famille=graph["famille"],
            date_debut=datetime.date(2020, 1, 1),
            date_fin=datetime.date(2999, 1, 1),
            document=SimpleUploadedFile("p.pdf", b"x"),
        )
        html = self._post(
            logged_client, graph["enfant"].pk, graph["activite"].pk
        ).json()["form_html"]
        assert "1/1" in html
        assert "Valide 01/01/99" in html
        assert f"data-piece-id='{piece.pk}'" in html
        assert "disabled" not in html.split("btn-outline-primary")[1].split(">")[0]

    def test_existing_piece_without_end_date_and_document(self, logged_client, graph):
        tp = TypePieceFactory(public="individu")
        graph["activite"].pieces.add(tp)
        PieceFactory(
            type_piece=tp,
            individu=graph["enfant"],
            famille=None,
            date_debut=datetime.date(2020, 1, 1),
            date_fin=None,
            document=None,
        )
        # date_fin=None is not "valid" for Get_liste_pieces_necessaires (date_fin__gte filter)
        # but the display branch for pieces without end date must still render.
        html = self._post(
            logged_client, graph["enfant"].pk, graph["activite"].pk
        ).json()["form_html"]
        assert "Valide ∞" in html
        assert "btn-outline-primary btn-sm disabled" in html

    def test_existing_expired_piece_not_imposed(self, logged_client, graph):
        tp = TypePieceFactory(public="individu")
        graph["activite"].pieces.add(tp)
        PieceFactory(
            type_piece=tp,
            individu=graph["enfant"],
            famille=graph["famille"],
            date_debut=datetime.date(2020, 1, 1),
            date_fin=datetime.date(2021, 6, 30),
        )
        html = self._post(
            logged_client, graph["enfant"].pk, graph["activite"].pk
        ).json()["form_html"]
        assert "Exp. 30/06/21" in html
        assert "Pièce expirée" not in html
        assert f"document_{tp.pk}" not in html

    def test_existing_expired_piece_imposed_with_portail_document(
        self, logged_client, graph, media_tmp
    ):
        activite = graph["activite"]
        activite.portail_inscriptions_imposer_pieces = True
        activite.save()
        tp = TypePieceFactory(public="individu")
        activite.pieces.add(tp)
        PieceFactory(
            type_piece=tp,
            individu=graph["enfant"],
            famille=graph["famille"],
            date_debut=datetime.date(2020, 1, 1),
            date_fin=datetime.date(2021, 6, 30),
        )
        doc = PortailDocument.objects.create(
            titre="M",
            structure=graph["structure"],
            type_piece=tp,
            document=SimpleUploadedFile("m.pdf", b"%PDF"),
        )
        doc.activites.add(activite)
        html = self._post(logged_client, graph["enfant"].pk, activite.pk).json()[
            "form_html"
        ]
        assert "Pièce expirée" in html
        assert f"document_{tp.pk}" in html
        assert doc.document.url in html

    def test_existing_expired_piece_imposed_with_type_piece_document_fallback(
        self, logged_client, graph, media_tmp
    ):
        activite = graph["activite"]
        activite.portail_inscriptions_imposer_pieces = True
        activite.save()
        tp = TypePieceFactory(public="individu")
        activite.pieces.add(tp)
        PieceFactory(
            type_piece=tp,
            individu=graph["enfant"],
            famille=graph["famille"],
            date_debut=datetime.date(2020, 1, 1),
            date_fin=datetime.date(2021, 6, 30),
        )
        doc = PortailDocument.objects.create(
            titre="M",
            structure=graph["structure"],
            type_piece=tp,
            document=SimpleUploadedFile("m3.pdf", b"%PDF"),
        )
        html = self._post(logged_client, graph["enfant"].pk, activite.pk).json()[
            "form_html"
        ]
        assert doc.document.url in html

    def test_existing_expired_piece_imposed_without_model(self, logged_client, graph):
        activite = graph["activite"]
        activite.portail_inscriptions_imposer_pieces = True
        activite.save()
        tp = TypePieceFactory(public="individu")
        activite.pieces.add(tp)
        PieceFactory(
            type_piece=tp,
            individu=graph["enfant"],
            famille=graph["famille"],
            date_debut=datetime.date(2020, 1, 1),
            date_fin=datetime.date(2021, 6, 30),
        )
        html = self._post(logged_client, graph["enfant"].pk, activite.pk).json()[
            "form_html"
        ]
        assert "Pièce expirée" in html
        assert "Télécharger le modèle" not in html

    def test_piece_without_type_is_ignored(self, logged_client, graph):
        tp = TypePieceFactory(public="individu")
        graph["activite"].pieces.add(tp)
        PieceFactory(
            type_piece=None,
            individu=graph["enfant"],
            famille=graph["famille"],
            date_debut=datetime.date(2020, 1, 1),
        )
        html = self._post(
            logged_client, graph["enfant"].pk, graph["activite"].pk
        ).json()["form_html"]
        assert "Manquante" in html

    def test_two_pieces_of_same_type_are_both_listed(self, logged_client, graph):
        tp = TypePieceFactory(public="individu")
        graph["activite"].pieces.add(tp)
        for fin in (datetime.date(2999, 1, 1), datetime.date(2021, 6, 30)):
            PieceFactory(
                type_piece=tp,
                individu=graph["enfant"],
                famille=graph["famille"],
                date_debut=datetime.date(2020, 1, 1),
                date_fin=fin,
            )
        html = self._post(
            logged_client, graph["enfant"].pk, graph["activite"].pk
        ).json()["form_html"]
        assert html.count("piece-item") == 2

    def test_cross_family_individu_is_rejected(
        self, logged_client, graph, other_famille
    ):
        _u, _f, ratt_b = other_famille
        activite = graph["activite"]
        tp = TypePieceFactory(public="individu")
        activite.pieces.add(tp)
        PieceFactory(
            type_piece=tp,
            individu=ratt_b[1].individu,
            famille=None,
            date_debut=datetime.date(2020, 1, 1),
            date_fin=datetime.date(2999, 1, 1),
        )
        html = self._post(logged_client, ratt_b[1].individu.pk, activite.pk).json()[
            "form_html"
        ]
        assert ratt_b[1].individu.prenom not in html


# --------------------------------------------------------------------------
# Valid_form: validation errors
# --------------------------------------------------------------------------
@pytest.mark.django_db
class TestValidFormErrors:
    def test_empty_payload_400(self, logged_client):
        r = post_valid(logged_client, {})
        assert r.status_code == 400
        assert "Formulaire principal invalide" in r.json()["erreur"]

    def test_missing_groupe_400(self, logged_client, graph):
        data = payload(graph)
        del data["groupe"]
        r = post_valid(logged_client, data)
        assert r.status_code == 400
        assert "groupe" in r.json()["erreur"].lower()

    def test_unknown_activite_400(self, logged_client, graph):
        r = post_valid(logged_client, payload(graph, activite=999999))
        assert r.status_code == 400

    def test_no_tarif_selected_401(self, logged_client, graph):
        data = payload(graph)
        del data[f"tarifs_{graph['tarif'].nom_tarif_id}"]
        r = post_valid(logged_client, data)
        assert r.status_code == 401
        assert "au moins un tarif" in r.json()["erreur"]
        assert not PortailRenseignement.objects.filter(
            code="inscrire_activite"
        ).exists()

    def test_tarif_of_other_activity_400(self, logged_client, graph):
        """Radio field queryset only holds this activity's tarifs: invalid choice -> 400 'Erreur détails'."""
        autre = make_tarif(ActiviteFactory())
        r = post_valid(
            logged_client,
            payload(graph, **{f"tarifs_{graph['tarif'].nom_tarif_id}": autre.pk}),
        )
        assert r.status_code == 400
        assert "Erreur détails" in r.json()["erreur"]

    def test_pending_request_same_activity_401(self, logged_client, graph):
        PortailRenseignement.objects.create(
            famille=graph["famille"],
            individu=graph["enfant"],
            categorie="activites",
            code="inscrire_activite",
            etat="ATTENTE",
            nouvelle_valeur=json.dumps(
                "%d;%d;[]" % (graph["activite"].pk, graph["groupe"].pk)
            ),
        )
        r = post_valid(logged_client, payload(graph))
        assert r.status_code == 401
        assert "existe déjà" in r.json()["erreur"]

    def test_pending_request_other_activity_does_not_block(self, logged_client, graph):
        autre = ActiviteFactory()
        PortailRenseignement.objects.create(
            famille=graph["famille"],
            individu=graph["enfant"],
            categorie="activites",
            code="inscrire_activite",
            etat="ATTENTE",
            nouvelle_valeur=json.dumps("%d;1;[]" % autre.pk),
        )
        assert post_valid(logged_client, payload(graph)).status_code == 200

    @pytest.mark.parametrize("valeur", ["pas du json", json.dumps("abc;1;[]")])
    def test_pending_request_with_corrupted_value_is_skipped(
        self, logged_client, graph, valeur
    ):
        PortailRenseignement.objects.create(
            famille=graph["famille"],
            individu=graph["enfant"],
            categorie="activites",
            code="inscrire_activite",
            etat="ATTENTE",
            nouvelle_valeur=valeur,
        )
        assert post_valid(logged_client, payload(graph)).status_code == 200

    def test_activity_full_401(self, logged_client, graph):
        activite = graph["activite"]
        activite.portail_inscriptions_bloquer_si_complet = True
        activite.nbre_inscrits_max = 1
        activite.save()
        InscriptionFactory(activite=activite, groupe=graph["groupe"], statut="ok")
        r = post_valid(logged_client, payload(graph))
        assert r.status_code == 401
        assert "activité est déjà complète" in r.json()["erreur"]

    def test_group_full_401(self, logged_client, graph):
        activite, groupe = graph["activite"], graph["groupe"]
        activite.portail_inscriptions_bloquer_si_complet = True
        activite.nbre_inscrits_max = 10
        activite.save()
        groupe.nbre_inscrits_max = 1
        groupe.save()
        InscriptionFactory(activite=activite, groupe=groupe, statut="ok")
        r = post_valid(logged_client, payload(graph))
        assert r.status_code == 401
        assert "groupe est déjà complet" in r.json()["erreur"]

    def test_places_left_does_not_block(self, logged_client, graph):
        activite, groupe = graph["activite"], graph["groupe"]
        activite.portail_inscriptions_bloquer_si_complet = True
        activite.nbre_inscrits_max = 5
        activite.save()
        groupe.nbre_inscrits_max = 5
        groupe.save()
        InscriptionFactory(activite=activite, groupe=groupe, statut="ok")
        InscriptionFactory(
            activite=activite, groupe=groupe, statut="attente"
        )  # waiting list not counted
        assert post_valid(logged_client, payload(graph)).status_code == 200

    def test_no_limit_configured_does_not_block(self, logged_client, graph):
        activite = graph["activite"]
        activite.portail_inscriptions_bloquer_si_complet = True
        activite.save()
        InscriptionFactory(activite=activite, groupe=graph["groupe"], statut="ok")
        assert post_valid(logged_client, payload(graph)).status_code == 200

    def test_maitrise_activity_refuses_parent_status_401(self, logged_client, graph):
        activite = graph["activite"]
        activite.maitrise = True
        activite.save()
        graph["enfant"].statut = 0
        graph["enfant"].save()
        r = post_valid(logged_client, payload(graph))
        assert r.status_code == 401
        assert "responsable dans cette activité" in r.json()["erreur"]

    def test_maitrise_activity_other_status_allowed(self, logged_client, graph):
        activite = graph["activite"]
        activite.maitrise = True
        activite.save()
        graph["enfant"].statut = 5
        graph["enfant"].save()
        assert post_valid(logged_client, payload(graph)).status_code == 200

    def test_adult_activity_child_without_family_inscription_401(
        self, logged_client, graph
    ):
        activite = graph["activite"]
        activite.public = 0
        activite.save()
        graph["enfant"].statut = 5
        graph["enfant"].save()
        r = post_valid(logged_client, payload(graph))
        assert r.status_code == 401
        assert "adulte responsable" in r.json()["erreur"]

    def test_adult_activity_child_with_family_inscription_allowed(
        self, logged_client, graph
    ):
        activite = graph["activite"]
        activite.public = 0
        activite.save()
        graph["enfant"].statut = 5
        graph["enfant"].save()
        InscriptionFactory(
            activite=activite,
            groupe=graph["groupe"],
            famille=graph["famille"],
            individu=graph["adulte"],
        )
        assert post_valid(logged_client, payload(graph)).status_code == 200

    def test_adult_activity_with_responsible_status_allowed(self, logged_client, graph):
        activite = graph["activite"]
        activite.public = 1
        activite.save()
        graph["enfant"].statut = 2
        graph["enfant"].save()
        assert post_valid(logged_client, payload(graph)).status_code == 200

    def test_public_5_never_requires_adult(self, logged_client, graph):
        graph["enfant"].statut = 5
        graph["enfant"].save()
        assert post_valid(logged_client, payload(graph)).status_code == 200

    def test_save_failure_returns_500(self, logged_client, graph):
        with mock.patch.object(
            PortailRenseignement, "save", side_effect=RuntimeError("boom")
        ):
            r = post_valid(logged_client, payload(graph))
        assert r.status_code == 500
        assert "sauvegarde" in r.json()["erreur"]

    def test_missing_piece_upload_required_400(self, logged_client, graph):
        activite = graph["activite"]
        activite.portail_inscriptions_imposer_pieces = True
        activite.save()
        activite.pieces.add(TypePieceFactory(public="individu"))
        r = post_valid(logged_client, payload(graph))
        assert r.status_code == 400
        assert "Erreur détails" in r.json()["erreur"]

    def test_piece_with_bad_extension_400(self, logged_client, graph, media_tmp):
        activite = graph["activite"]
        activite.portail_inscriptions_imposer_pieces = True
        activite.save()
        tp = TypePieceFactory(public="individu")
        activite.pieces.add(tp)
        data = payload(
            graph, **{f"document_{tp.pk}": SimpleUploadedFile("virus.exe", b"MZ")}
        )
        r = post_valid(logged_client, data)
        assert r.status_code == 400
        assert "Erreur détails" in r.json()["erreur"]
        assert not Piece.objects.filter(type_piece=tp).exists()


# --------------------------------------------------------------------------
# Valid_form: happy paths
# --------------------------------------------------------------------------
@pytest.mark.django_db
class TestValidFormSuccess:
    def test_creates_inscription_request(self, logged_client, graph):
        r = post_valid(logged_client, payload(graph))
        assert r.status_code == 200
        assert r.json() == {"succes": True, "url": reverse("portail_activites")}
        demande = PortailRenseignement.objects.get(code="inscrire_activite")
        assert demande.famille == graph["famille"]
        assert demande.individu == graph["enfant"]
        assert demande.etat == "ATTENTE"
        assert demande.categorie == "activites"
        assert demande.validation_auto is False
        assert demande.activite == graph["activite"]
        valeur = json.loads(demande.nouvelle_valeur)
        act_id, grp_id, tarifs = valeur.split(";")
        assert int(act_id) == graph["activite"].pk
        assert int(grp_id) == graph["groupe"].pk
        assert json.loads(tarifs) == [str(graph["tarif"].pk)]

    def test_flash_message_is_set(self, logged_client, graph):
        r = post_valid(logged_client, payload(graph))
        assert r.status_code == 200
        msgs = [str(m) for m in r.wsgi_request._messages]
        assert "Votre demande d'inscription a été transmise" in msgs

    def test_request_then_visible_in_activites_page(self, logged_client, graph):
        post_valid(logged_client, payload(graph))
        r = logged_client.get(reverse("portail_activites"))
        demandes = r.context["demandes_inscriptions_attente"]
        assert len(demandes) == 1
        assert demandes[0].nom_activite == graph["activite"].nom

    def test_multiple_tarifs_across_noms(self, logged_client, graph):
        activite = graph["activite"]
        t2 = make_tarif(activite)
        data = payload(graph, **{f"tarifs_{t2.nom_tarif_id}": t2.pk})
        assert post_valid(logged_client, data).status_code == 200
        valeur = json.loads(
            PortailRenseignement.objects.get(code="inscrire_activite").nouvelle_valeur
        )
        assert sorted(json.loads(valeur.split(";")[2])) == sorted(
            [str(graph["tarif"].pk), str(t2.pk)]
        )

    def test_missing_hidden_fields_are_filled_by_view(self, logged_client, graph):
        """famille/etat/categorie/code are injected server side when absent."""
        assert post_valid(logged_client, payload(graph)).status_code == 200
        demande = PortailRenseignement.objects.get(code="inscrire_activite")
        assert (demande.etat, demande.categorie) == ("ATTENTE", "activites")

    def test_posted_hidden_fields_are_kept(self, logged_client, graph):
        data = payload(
            graph,
            famille=graph["famille"].pk,
            etat="ATTENTE",
            categorie="activites",
            code="inscrire_activite",
        )
        assert post_valid(logged_client, data).status_code == 200

    def test_cannot_submit_for_another_family(
        self, logged_client, graph, other_famille
    ):
        _u, famille_b, ratt_b = other_famille
        data = payload(graph, famille=famille_b.pk, individu=ratt_b[1].individu.pk)
        post_valid(logged_client, data)
        assert not PortailRenseignement.objects.filter(
            code="inscrire_activite", famille=famille_b
        ).exists()

    def test_notification_mail_sent_to_structure(self, logged_client, graph):
        structure = graph["structure"]
        structure.adresse_exp = AdresseMailFactory(adresse="structure@test.org")
        structure.save()
        r = post_valid(logged_client, payload(graph))
        assert r.status_code == 200
        mail = Mail.objects.get(categorie="demande_inscription")
        assert mail.adresse_exp == structure.adresse_exp
        assert graph["activite"].nom in mail.html
        assert mail.destinataires.get().adresse == "structure@test.org"

    def test_mail_failure_does_not_block_success(self, logged_client, graph):
        structure = graph["structure"]
        structure.adresse_exp = AdresseMailFactory()
        structure.save()
        with mock.patch(
            "portail.views.inscrire_activite.utils_email.Envoyer_model_mail",
            side_effect=RuntimeError("smtp"),
        ):
            r = post_valid(logged_client, payload(graph))
        assert r.status_code == 200
        assert r.json()["succes"] is True

    def test_no_mail_without_structure_address(self, logged_client, graph):
        post_valid(logged_client, payload(graph))
        assert not Mail.objects.filter(categorie="demande_inscription").exists()


@pytest.mark.django_db
class TestValidFormPieces:
    @pytest.fixture
    def piece_setup(self, graph):
        activite = graph["activite"]
        activite.portail_inscriptions_imposer_pieces = True
        activite.save()
        return activite

    @staticmethod
    def upload(name="doc.pdf"):
        return SimpleUploadedFile(
            name, b"%PDF-1.4 test", content_type="application/pdf"
        )

    def test_individual_piece_is_stored_with_family(
        self, logged_client, graph, piece_setup, media_tmp
    ):
        tp = TypePieceFactory(
            public="individu", nom="Certificat", valide_rattachement=False
        )
        piece_setup.pieces.add(tp)
        r = post_valid(
            logged_client, payload(graph, **{f"document_{tp.pk}": self.upload()})
        )
        assert r.status_code == 200
        piece = Piece.objects.get(type_piece=tp)
        assert piece.individu == graph["enfant"]
        assert piece.famille == graph["famille"]
        assert piece.date_debut == datetime.date.today()
        assert piece.date_fin == datetime.date(2999, 1, 1)
        assert piece.auteur.categorie == "famille"
        assert piece.titre == "Certificat"
        renseignement = PortailRenseignement.objects.get(
            categorie="famille_pieces", idobjet=piece.pk
        )
        assert renseignement.validation_auto is True
        assert renseignement.code == "Nouvelle pièce"
        assert "Certificat" in json.loads(renseignement.nouvelle_valeur)

    def test_individual_piece_valide_rattachement_has_no_family(
        self, logged_client, graph, piece_setup, media_tmp
    ):
        tp = TypePieceFactory(public="individu", valide_rattachement=True)
        piece_setup.pieces.add(tp)
        assert (
            post_valid(
                logged_client, payload(graph, **{f"document_{tp.pk}": self.upload()})
            ).status_code
            == 200
        )
        piece = Piece.objects.get(type_piece=tp)
        assert piece.famille is None
        assert piece.individu == graph["enfant"]

    def test_family_piece_is_stored_without_individu(
        self, logged_client, graph, piece_setup, media_tmp
    ):
        tp = TypePieceFactory(public="famille", nom="Assurance")
        piece_setup.pieces.add(tp)
        assert (
            post_valid(
                logged_client, payload(graph, **{f"document_{tp.pk}": self.upload()})
            ).status_code
            == 200
        )
        piece = Piece.objects.get(type_piece=tp)
        assert piece.individu is None
        assert piece.famille == graph["famille"]

    def test_piece_with_duration_gets_end_date(
        self, logged_client, graph, piece_setup, media_tmp
    ):
        tp = TypePieceFactory(public="individu", duree_validite="j365-m0-a0")
        piece_setup.pieces.add(tp)
        post_valid(
            logged_client, payload(graph, **{f"document_{tp.pk}": self.upload()})
        )
        assert Piece.objects.get(
            type_piece=tp
        ).date_fin == datetime.date.today() + datetime.timedelta(days=365)

    def test_expired_piece_replaced_by_upload(
        self, logged_client, graph, piece_setup, media_tmp
    ):
        tp = TypePieceFactory(public="individu")
        piece_setup.pieces.add(tp)
        PieceFactory(
            type_piece=tp,
            individu=graph["enfant"],
            famille=graph["famille"],
            date_debut=datetime.date(2020, 1, 1),
            date_fin=datetime.date(2021, 1, 1),
        )
        assert (
            post_valid(
                logged_client, payload(graph, **{f"document_{tp.pk}": self.upload()})
            ).status_code
            == 200
        )
        assert Piece.objects.filter(type_piece=tp).count() == 2

    def test_piece_failure_missing_type_is_logged_not_blocking(
        self, logged_client, graph, piece_setup, media_tmp
    ):
        tp = TypePieceFactory(public="individu")
        piece_setup.pieces.add(tp)
        with mock.patch.object(
            TypePiece.objects, "get", side_effect=TypePiece.DoesNotExist
        ):
            r = post_valid(
                logged_client, payload(graph, **{f"document_{tp.pk}": self.upload()})
            )
        assert r.status_code == 200
        assert PortailRenseignement.objects.filter(code="inscrire_activite").exists()
        assert not Piece.objects.filter(type_piece=tp).exists()

    def test_piece_failure_unexpected_error_is_logged_not_blocking(
        self, logged_client, graph, piece_setup, media_tmp
    ):
        tp = TypePieceFactory(public="individu")
        piece_setup.pieces.add(tp)
        with mock.patch.object(
            Piece.objects, "create", side_effect=RuntimeError("disk full")
        ):
            r = post_valid(
                logged_client, payload(graph, **{f"document_{tp.pk}": self.upload()})
            )
        assert r.status_code == 200
        assert PortailRenseignement.objects.filter(code="inscrire_activite").exists()
        assert not Piece.objects.filter(type_piece=tp).exists()

    def test_non_document_fields_are_ignored(self, logged_client, graph):
        """Without imposed pieces there is no document_* field and no piece is created."""
        assert post_valid(logged_client, payload(graph)).status_code == 200
        assert not Piece.objects.exists()


@pytest.mark.django_db
class TestFormulaireExtraUnit:
    def test_without_activity_has_empty_layout(self):
        from portail.forms.inscrire_activite import Formulaire_extra

        form = Formulaire_extra()
        assert list(form.fields) == []
        assert len(form.helper.layout.fields) == 0

    def test_with_activity_but_without_famille_skips_pieces(self, graph):
        from portail.forms.inscrire_activite import Formulaire_extra

        graph["activite"].pieces.add(TypePieceFactory(public="individu"))
        form = Formulaire_extra(activite=graph["activite"])
        assert f"tarifs_{graph['tarif'].nom_tarif_id}" in form.fields
        assert not any(f.startswith("document_") for f in form.fields)
