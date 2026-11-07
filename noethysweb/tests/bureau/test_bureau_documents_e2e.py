"""Documents (pièces justificatives), end to end:

1. the director defines a type of document (Paramétrage > Types de pièces) and requires it on
   an activity (Activité > Renseignements > Pièces à fournir); he can also offer a template to
   download (Paramétrage > Documents du portail);
2. the family of an inscribed child is notified on the portal (home alert "Compléter mon dossier",
   Documents page, Compléter mon dossier > Pièces);
3. the family uploads the document (Documents > Transmettre, or Compléter mon dossier);
4. the alert disappears for the family and for the director (fiche famille, missing documents list),
   and comes back when the document expires or is deleted;
5. the director can email a reminder to the families still missing documents.
"""

import datetime
import io
import json

import pytest
from core.models import Activite, Mail, Piece, PortailDocument, PortailRenseignement, Rattachement, TypePiece, \
    Utilisateur
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from tests.bureau.conftest import AJAX, build_form_data
from tests.unit.factories import ActiviteFactory, IndividuFactory, InscriptionFactory, StructureFactory, \
    create_famille_complete



def _aujourdhui():
    """Today as the application sees it (computed at call time: Django's TIME_ZONE may differ from the
    machine's, so a module-level constant can be off by one day around midnight)."""
    return datetime.date.today()


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


def _pdf(nom="certificat.pdf", texte="Certificat médical"):
    from reportlab.pdfgen import canvas

    contenu = io.BytesIO()
    page = canvas.Canvas(contenu)
    page.drawString(100, 750, texte)
    page.save()
    return SimpleUploadedFile(nom, contenu.getvalue(), content_type="application/pdf")


def _png(nom="scan.png"):
    from PIL import Image

    contenu = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(contenu, format="PNG")
    return SimpleUploadedFile(nom, contenu.getvalue(), content_type="image/png")


# ---------------------------------------------------------------------------
# Director-side helpers (real screens)
# ---------------------------------------------------------------------------

def _creer_type_piece(client, nom="Certificat médical", structure=None, public="individu", validite_type="ILLIMITEE",
                      **extra):
    data = {"nom": nom, "structure": structure.pk if structure else "", "public": public,
            "validite_type": validite_type}
    data.update(extra)
    response = client.post(reverse("types_pieces_ajouter"), data)
    if response.status_code != 302:
        return response
    return TypePiece.objects.get(nom=nom)


def _exiger(client, activite, *types_pieces):
    url = reverse("activites_renseignements_modifier", kwargs={"idactivite": activite.pk})
    data = build_form_data(client.get(url).context["form"], pieces=[t.pk for t in types_pieces])
    response = client.post(url, data)
    assert response.status_code == 302, response.context["form"].errors.as_json() if response.context else response
    return response


@pytest.fixture
def certificat(directeur_client, structure, activite):
    """A medical certificate required for every child inscribed on the director's activity."""
    type_piece = _creer_type_piece(directeur_client, structure=structure)
    _exiger(directeur_client, activite, type_piece)
    return type_piece


# ---------------------------------------------------------------------------
# Family-side helpers
# ---------------------------------------------------------------------------

def _portail(famille):
    client = Client()
    client.force_login(Utilisateur.objects.get(pk=famille.utilisateur_id))
    return client


def _alerte_accueil(famille):
    """Number of missing documents announced on the portal home page."""
    return _portail(famille).get(reverse("portail_accueil")).context["nbre_pieces_manquantes"]


def _a_fournir(famille):
    """Labels of the documents shown with a red cross (still to provide) on the portal Documents page.
    The page lists every required document, the ones already provided with a green tick."""
    response = _portail(famille).get(reverse("portail_documents"))
    assert response.status_code == 200
    return [p["label"] for p in response.context["pieces_fournir"] if not p["valide"]]


def _transmettre(famille, libelle=None, fichier=None, **extra):
    """Documents > Transmettre un document: pick the requested document by its label (or 'Autre type')."""
    client = _portail(famille)
    url = reverse("portail_transmettre_piece")
    form = client.get(url).context["form"]
    if libelle:
        selection = next(i for i, label in form.fields["selection_piece"].choices if label == libelle)
    else:
        selection = 9999
    data = {"selection_piece": selection, "famille": famille.pk, "document": fichier or _pdf(), "titre": "",
            "observations": ""}
    data.update(extra)
    return client.post(url, data)


# ---------------------------------------------------------------------------
# 1. Director: types of documents and activity requirements
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestParametrageDirecteur:
    def test_creer_un_type_de_piece(self, directeur_client, structure):
        type_piece = _creer_type_piece(directeur_client, structure=structure)
        assert (type_piece.public, type_piece.structure, type_piece.duree_validite) == ("individu", structure, None)
        assert type_piece.Get_date_fin_validite() == datetime.date(2999, 1, 1)

    def test_validite_d_un_an(self, directeur_client, structure):
        type_piece = _creer_type_piece(directeur_client, structure=structure, validite_type="DUREE",
                                       validite_annees=1)
        assert type_piece.duree_validite == "j0-m0-a1"

    def test_validite_jusqu_a_une_date(self, directeur_client, structure):
        type_piece = _creer_type_piece(directeur_client, structure=structure, validite_type="DATE",
                                       validite_date="2027-08-31")
        assert type_piece.Get_date_fin_validite() == datetime.date(2027, 8, 31)

    def test_duree_vide_refusee(self, directeur_client, structure):
        response = _creer_type_piece(directeur_client, structure=structure, validite_type="DUREE")
        assert response.status_code == 200
        assert "validite_type" in response.context["form"].errors

    def test_date_manquante_refusee(self, directeur_client, structure):
        response = _creer_type_piece(directeur_client, structure=structure, validite_type="DATE")
        assert "validite_date" in response.context["form"].errors

    def test_piece_de_l_organisateur(self, directeur_client):
        """Without structure, the type is a standard offered to every structure's activities."""
        type_piece = _creer_type_piece(directeur_client, nom="Fiche sanitaire", structure=None)
        assert type_piece.structure is None

    def test_exiger_la_piece_sur_l_activite(self, directeur_client, structure, activite):
        type_piece = _creer_type_piece(directeur_client, structure=structure)
        _exiger(directeur_client, activite, type_piece)
        assert list(Activite.objects.get(pk=activite.pk).pieces.all()) == [type_piece]

    def test_pieces_proposees_pour_l_activite(self, directeur_client, structure, activite):
        mienne = _creer_type_piece(directeur_client, nom="Mienne", structure=structure)
        standard = _creer_type_piece(directeur_client, nom="Standard", structure=None)
        voisine = TypePiece.objects.create(nom="Voisine", public="individu", structure=StructureFactory())
        url = reverse("activites_renseignements_modifier", kwargs={"idactivite": activite.pk})
        queryset = set(directeur_client.get(url).context["form"].fields["pieces"].queryset)
        assert {mienne, standard} <= queryset and voisine not in queryset

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (directors are limited to their structures): the 'Structure' of a type of document lists every "
        "structure, so a director can create document types for another structure."
    ))
    def test_seules_mes_structures_pour_un_type_de_piece(self, directeur_client, structure):
        autre = StructureFactory()
        queryset = directeur_client.get(reverse("types_pieces_ajouter")).context["form"].fields["structure"].queryset
        assert structure in queryset and autre not in queryset


# ---------------------------------------------------------------------------
# 2. The family is notified
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestNotificationFamille:
    def test_alerte_sur_l_accueil(self, famille_bureau, certificat):
        famille, _t, _e = famille_bureau
        assert _alerte_accueil(famille) == 1
        html = _portail(famille).get(reverse("portail_accueil")).content.decode()
        assert "Des informations sont manquantes dans votre dossier familial" in html
        assert reverse("portail_completer_dossier") in html

    def test_pas_d_alerte_sans_piece_exigee(self, famille_bureau):
        famille, _t, _e = famille_bureau
        assert _alerte_accueil(famille) == 0

    def test_piece_listee_sur_la_page_documents(self, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        assert _a_fournir(famille) == [certificat.Get_nom(enfant)]

    def test_piece_listee_dans_completer_mon_dossier(self, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        response = _portail(famille).get(reverse("portail_completer_dossier") + "?etape=pieces")
        etape = next(e for e in response.context["etapes"] if e["code"] == "pieces")
        assert etape["nbre"] == 1
        assert [p["type_piece"] for p in etape["pieces_fournir"]] == [certificat]

    def test_famille_non_inscrite_non_concernee(self, certificat, organisateur):
        _u, famille, _r = create_famille_complete(username="pas_inscrite")
        assert _alerte_accueil(famille) == 0

    def test_piece_individuelle_demandee_pour_chaque_enfant(self, famille_bureau, certificat, activite):
        famille, _t, enfant = famille_bureau
        cadet = IndividuFactory(nom="Enfant", prenom="Cadet")
        Rattachement.objects.create(famille=famille, individu=cadet, categorie=2)
        InscriptionFactory(famille=famille, individu=cadet, activite=activite)
        assert sorted(_a_fournir(famille)) == sorted([certificat.Get_nom(enfant), certificat.Get_nom(cadet)])

    def test_inscription_terminee_non_concernee(self, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        enfant.inscription_set.update(date_fin=_aujourdhui() - datetime.timedelta(days=1))
        assert _alerte_accueil(famille) == 0

    def test_membre_masque_non_concerne(self, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        famille.individus_masques.add(enfant)
        assert _a_fournir(famille) == []


# ---------------------------------------------------------------------------
# 3. The family uploads the document
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDepotPortail:
    def test_transmettre_la_piece_demandee(self, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        response = _transmettre(famille, certificat.Get_nom(enfant))
        assert response["Location"] == reverse("portail_renseignements")

        piece = Piece.objects.get(type_piece=certificat)
        assert (piece.famille, piece.individu) == (famille, enfant)
        assert piece.auteur == famille.utilisateur
        assert (piece.date_debut, piece.date_fin) == (_aujourdhui(), datetime.date(2999, 1, 1))
        assert piece.document.storage.exists(piece.document.name)

    def test_l_alerte_disparait(self, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        _transmettre(famille, certificat.Get_nom(enfant))
        assert _alerte_accueil(famille) == 0
        assert _a_fournir(famille) == []

    def test_le_directeur_est_prevenu(self, directeur_client, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        assert directeur_client.get(reverse("famille_resume", args=[famille.pk])).context["pieces_fournir"]
        _transmettre(famille, certificat.Get_nom(enfant))

        piece = Piece.objects.get(type_piece=certificat)
        assert PortailRenseignement.objects.filter(famille=famille, categorie="famille_pieces", idobjet=piece.pk,
                                                   code="Nouvelle pièce").exists()
        assert directeur_client.get(reverse("famille_resume", args=[famille.pk])).context["pieces_fournir"] == []
        from django.test import RequestFactory
        from fiche_famille.views.famille_pieces import Liste

        request = RequestFactory().get("/")
        request.user = Utilisateur.objects.get(username="directeur")
        view = Liste()
        view.setup(request, idfamille=famille.pk)
        assert piece in view.get_queryset()

    def test_le_pdf_est_filigrane(self, famille_bureau, certificat):
        from pypdf import PdfReader

        famille, _t, enfant = famille_bureau
        _transmettre(famille, certificat.Get_nom(enfant))
        piece = Piece.objects.get(type_piece=certificat)
        texte = "".join(page.extract_text() for page in PdfReader(piece.document.path).pages)
        assert "Sacadoc" in texte

    def test_image_acceptee(self, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        assert _transmettre(famille, certificat.Get_nom(enfant), fichier=_png()).status_code == 302
        assert Piece.objects.filter(type_piece=certificat).exists()

    @pytest.mark.parametrize("nom", ["certificat.docx", "certificat.exe", "page.html"])
    def test_format_interdit_refuse(self, famille_bureau, certificat, nom):
        famille, _t, enfant = famille_bureau
        fichier = SimpleUploadedFile(nom, b"contenu", content_type="application/octet-stream")
        response = _transmettre(famille, certificat.Get_nom(enfant), fichier=fichier)
        assert response.status_code == 200
        assert "document" in response.context["form"].errors
        assert not Piece.objects.exists()

    def test_plusieurs_fichiers(self, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        _transmettre(famille, certificat.Get_nom(enfant), document1=_png("page2.png"))
        assert Piece.objects.filter(type_piece=certificat, individu=enfant).count() == 2

    def test_validite_d_un_an(self, directeur_client, structure, activite, famille_bureau):
        famille, _t, enfant = famille_bureau
        type_piece = _creer_type_piece(directeur_client, nom="Licence", structure=structure,
                                       validite_type="DUREE", validite_annees=1)
        _exiger(directeur_client, activite, type_piece)
        _transmettre(famille, type_piece.Get_nom(enfant))
        assert Piece.objects.get(type_piece=type_piece).date_fin == type_piece.Get_date_fin_validite()
        assert Piece.objects.get(type_piece=type_piece).date_fin.year == _aujourdhui().year + 1

    def test_autre_document(self, famille_bureau):
        famille, _t, enfant = famille_bureau
        response = _transmettre(famille, None, titre="Jugement de garde", choix_individu=enfant.pk)
        assert response.status_code == 302
        piece = Piece.objects.get(titre="Jugement de garde")
        assert (piece.type_piece, piece.individu, piece.famille) == (None, enfant, famille)

    def test_autre_document_sans_titre_refuse(self, famille_bureau):
        famille, _t, _e = famille_bureau
        response = _transmettre(famille, None, titre="")
        assert response.status_code == 200
        assert "titre" in response.context["form"].errors

    @pytest.mark.xfail(strict=True, raises=KeyError, reason=(
        "BUG: an 'Individu concerné' outside the family is rejected by the choice field, but clean() then "
        "reads the missing cleaned_data['choix_individu'] and crashes (500) instead of showing the error. "
        "No document is created."
    ))
    def test_ne_peut_pas_deposer_pour_un_enfant_d_une_autre_famille(self, famille_bureau, organisateur):
        famille, _t, _e = famille_bureau
        _u, _autre, ratt = create_famille_complete(username="voisins")
        response = _transmettre(famille, None, titre="Intrus", choix_individu=ratt[1].individu.pk)
        assert response.status_code == 200
        assert not Piece.objects.filter(titre="Intrus").exists()

    def test_depot_depuis_completer_mon_dossier(self, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        client = _portail(famille)
        url = reverse("portail_completer_dossier")
        form = client.get(url + "?etape=pieces").context["form_piece"]
        selection = next(i for i, label in form.fields["selection_piece"].choices if label == certificat.Get_nom(enfant))
        response = client.post(url, {"selection_piece": selection, "famille": famille.pk, "document": _pdf(),
                                     "titre": "", "observations": ""})
        assert response["Location"] == url + "?etape=pieces"
        assert Piece.objects.filter(type_piece=certificat, individu=enfant).exists()
        assert PortailRenseignement.objects.filter(famille=famille, categorie="famille_pieces").exists()
        assert _alerte_accueil(famille) == 0


# ---------------------------------------------------------------------------
# 4. Expiry, deletion, separated parents
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCycleDeVie:
    def test_piece_expiree_redemandee(self, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        Piece.objects.create(type_piece=certificat, famille=famille, individu=enfant,
                             date_debut=_aujourdhui() - datetime.timedelta(days=400),
                             date_fin=_aujourdhui() - datetime.timedelta(days=1))
        assert _alerte_accueil(famille) == 1

    def test_la_famille_supprime_sa_piece(self, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        _transmettre(famille, certificat.Get_nom(enfant))
        piece = Piece.objects.get(type_piece=certificat)
        response = _portail(famille).post(reverse("supprimer_piece", kwargs={"pk": piece.pk}))
        assert response["Location"] == reverse("portail_documents")
        assert not Piece.objects.filter(pk=piece.pk).exists()
        assert _alerte_accueil(famille) == 1

    def test_ne_peut_pas_supprimer_la_piece_d_une_autre_famille(self, famille_bureau, certificat, organisateur):
        famille, _t, enfant = famille_bureau
        _transmettre(famille, certificat.Get_nom(enfant))
        piece = Piece.objects.get(type_piece=certificat)
        _u, autre, _r = create_famille_complete(username="voisins")
        _portail(autre).post(reverse("supprimer_piece", kwargs={"pk": piece.pk}))
        assert Piece.objects.filter(pk=piece.pk).exists()

    def test_la_famille_remplace_le_document(self, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        _transmettre(famille, certificat.Get_nom(enfant))
        piece = Piece.objects.get(type_piece=certificat)
        ancien = piece.document.name
        client = _portail(famille)
        url = reverse("portail_documents_parents_modifier", kwargs={"pk": piece.pk})
        form = client.get(url).context["form"]
        selection = next(i for i, label in form.fields["selection_piece"].choices if label == certificat.Get_nom(enfant))
        response = client.post(url, {"selection_piece": selection, "famille": famille.pk, "document": _pdf("v2.pdf"),
                                     "titre": "", "observations": "Nouvelle version"})
        assert response.status_code == 302
        piece.refresh_from_db()
        assert piece.document.name != ancien and piece.observations == "Nouvelle version"

    def _parents_separes(self, famille_bureau, activite, valide_rattachement, directeur_client, structure):
        """The child also belongs to a second family (other parent), through which he is inscribed too."""
        famille_a, _t, enfant = famille_bureau
        _u, famille_b, _r = create_famille_complete(username="autre_parent", avec_enfant=False)
        Rattachement.objects.create(famille=famille_b, individu=enfant, categorie=2)
        InscriptionFactory(famille=famille_b, individu=enfant, activite=activite)
        type_piece = _creer_type_piece(directeur_client, nom="Autorisation de sortie", structure=structure,
                                       **({"valide_rattachement": "on"} if valide_rattachement else {}))
        _exiger(directeur_client, activite, type_piece)
        _transmettre(famille_a, type_piece.Get_nom(enfant))
        return famille_b

    def test_piece_valable_pour_l_autre_parent(self, famille_bureau, activite, directeur_client, structure):
        famille_b = self._parents_separes(famille_bureau, activite, True, directeur_client, structure)
        assert _a_fournir(famille_b) == []

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: 'La pièce est également valable pour les familles rattachées à l'individu' unchecked is not "
        "enforced: Get_pieces_manquantes() accepts any piece of the child whatever its famille, so the "
        "other parent's family is never asked for its own copy."
    ))
    def test_piece_non_valable_pour_l_autre_parent(self, famille_bureau, activite, directeur_client, structure):
        famille_b = self._parents_separes(famille_bureau, activite, False, directeur_client, structure)
        assert _a_fournir(famille_b) == ["Autorisation de sortie"]


# ---------------------------------------------------------------------------
# 5. Document templates to download ("Documents du portail")
# ---------------------------------------------------------------------------

def _creer_document_portail(client, structure, activite, type_piece=None, titre="Fiche sanitaire à remplir"):
    data = {"titre": titre, "texte": "Version 2026", "couleur_fond": "primary", "structure": structure.pk,
            "document": _pdf("fiche_sanitaire.pdf"), "activites": [activite.pk],
            "type_piece": type_piece.pk if type_piece else ""}
    response = client.post(reverse("portail_documents_ajouter"), data)
    assert response.status_code == 302, response.context["form"].errors.as_json() if response.context else response
    return PortailDocument.objects.get(titre=titre)


@pytest.mark.django_db
class TestDocumentsATelecharger:
    def test_la_famille_inscrite_peut_telecharger_le_modele(self, directeur_client, structure, activite,
                                                            famille_bureau):
        famille, _t, _e = famille_bureau
        document = _creer_document_portail(directeur_client, structure, activite)
        response = _portail(famille).get(reverse("portail_documents"))
        assert [d["titre"] for d in response.context["liste_documents"]] == ["Fiche sanitaire à remplir"]
        assert document.document.url in response.content.decode()

    def test_famille_d_une_autre_activite_ne_le_voit_pas(self, directeur_client, structure, famille_bureau):
        famille, _t, _e = famille_bureau
        _creer_document_portail(directeur_client, structure, ActiviteFactory(structure=structure))
        assert _portail(famille).get(reverse("portail_documents")).context["liste_documents"] == []

    @pytest.mark.xfail(strict=True, reason=(
        "À CONFIRMER: a 'Document du portail' can be linked to the type of document it lets the family fill "
        "in, but only the inscription wizard uses that link; on the Documents page and in 'Compléter mon "
        "dossier' the missing document does not point to its template (the template is only listed among "
        "the downloadable documents)."
    ))
    def test_le_modele_est_rattache_a_la_piece_a_fournir(self, directeur_client, structure, activite,
                                                         famille_bureau, certificat):
        """'Il faut remplir un document': the missing piece points to the template to fill in."""
        famille, _t, _e = famille_bureau
        document = _creer_document_portail(directeur_client, structure, activite, type_piece=certificat)
        pieces = _portail(famille).get(reverse("portail_documents")).context["pieces_fournir"]
        assert pieces[0].get("document") == document

    def test_seules_mes_activites_sont_proposees(self, directeur_client, activite):
        autre = ActiviteFactory(structure=StructureFactory())
        queryset = directeur_client.get(reverse("portail_documents_ajouter")).context["form"].fields["activites"].queryset
        assert activite in queryset and autre not in queryset


# ---------------------------------------------------------------------------
# 6. Director: missing documents list and email reminder
# ---------------------------------------------------------------------------

def _liste_manquantes(client, activites):
    response = client.post(reverse("liste_pieces_manquantes"), {
        "date": _aujourdhui().isoformat(), "masquer_complets": "on", "presents": "",
        # Fields posted by the activity selection widget (radio + checkboxes)
        "choix_activites": "activites", "liste_activites": [a.pk for a in activites],
    })
    assert response.status_code == 200
    return {ligne[1]: ligne[3] for ligne in response.context["datatable"].lignes}


@pytest.mark.django_db
class TestSuiviDirecteur:
    def test_liste_des_pieces_manquantes(self, directeur_client, activite, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        lignes = _liste_manquantes(directeur_client, [activite])
        assert list(lignes) == [famille.pk]
        assert certificat.nom in lignes[famille.pk]

    def test_famille_a_jour_masquee(self, directeur_client, activite, famille_bureau, certificat):
        famille, _t, enfant = famille_bureau
        _transmettre(famille, certificat.Get_nom(enfant))
        assert _liste_manquantes(directeur_client, [activite]) == {}

    def test_relance_par_email(self, directeur_client, directeur, famille_bureau, certificat):
        famille, _t, _e = famille_bureau
        famille.mail = "parents@test.org"
        famille.save()
        response = directeur_client.post(reverse("ajax_liste_pieces_manquantes_emails"), {
            "familles_coches": json.dumps([[famille.pk, "Certificat médical"]])}, **AJAX)
        mail = Mail.objects.get(categorie="rappel_pieces_manquantes")
        assert response.json()["url"] == reverse("editeur_emails", kwargs={"pk": mail.pk})
        destinataire = mail.destinataires.get()
        assert destinataire.adresse == "parents@test.org"
        assert json.loads(destinataire.valeurs)["{LISTE_PIECES_MANQUANTES}"] == "Certificat médical"

    def test_relance_sans_famille_cochee(self, directeur_client):
        response = directeur_client.post(reverse("ajax_liste_pieces_manquantes_emails"),
                                         {"familles_coches": "[]"}, **AJAX)
        assert response.status_code == 401
        assert not Mail.objects.exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (directors are limited to their structures): the missing documents list accepts any activity "
        "id, so a director can list another structure's families and their missing documents."
    ))
    def test_activites_d_une_autre_structure_interdites(self, directeur_client, organisateur):
        voisine = ActiviteFactory(structure=StructureFactory())
        voisine.pieces.add(TypePiece.objects.create(nom="Pièce voisine", public="individu"))
        _u, famille, ratt = create_famille_complete(username="famille_voisine")
        InscriptionFactory(famille=famille, individu=ratt[1].individu, activite=voisine)
        assert _liste_manquantes(directeur_client, [voisine]) == {}
