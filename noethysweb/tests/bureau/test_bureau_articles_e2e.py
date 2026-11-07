"""Articles, end to end: the director publishes an article in Paramétrage > Articles,
the family sees it (or not) on the home page of the portal.

Business rules under test:
- an article is shown while it is "Publié" and between its publication dates;
- "Toutes les familles" reaches every family (option reserved to staff accounts),
  "Les familles dont un membre est inscrit..." only families with a current inscription
  in one of the selected activities;
- the popup text is shown once per family;
- the attached formulaire / document is offered to the family;
- a director works within his structures (activities, formulaires, albums, structure).
"""

import datetime

import pytest
from core.models import Article, Lecture, Sondage, Utilisateur
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from tests.unit.factories import (
    ActiviteFactory,
    InscriptionFactory,
    StructureFactory,
    UtilisateurFactory,
    create_famille_complete,
)

MAINTENANT = datetime.datetime.now()


def _dt(delta_jours):
    return (MAINTENANT + datetime.timedelta(days=delta_jours)).strftime("%Y-%m-%d %H:%M:%S")


def _creer_article(client, structure, titre="Fête de fin d'année", **overrides):
    """Create an article through Paramétrage > Articles (the real staff form)."""
    form = client.get(reverse("articles_ajouter")).context["form"]
    data = {
        "titre": titre, "texte": "<p>Rendez-vous samedi</p>", "type_image": "aucune",
        "statut": "publie", "date_debut": _dt(-1), "date_fin": "", "couleur_fond": "",
        "document_titre": "Document", "public": "toutes", "structure": structure.pk,
        "auteur": form.fields["auteur"].initial.pk, "periode": "", "texte_popup": "",
    }
    data.update(overrides)
    data = {k: v for k, v in data.items() if v is not None}
    response = client.post(reverse("articles_ajouter"), data)
    if response.status_code != 302:
        return response
    return Article.objects.get(titre=titre)


def _modifier_article(client, article, **overrides):
    form = client.get(reverse("articles_modifier", args=[article.pk])).context["form"]
    data = {
        "titre": article.titre, "texte": article.texte, "type_image": "aucune", "statut": article.statut,
        "date_debut": article.date_debut.strftime("%Y-%m-%d %H:%M:%S"),
        "date_fin": article.date_fin.strftime("%Y-%m-%d %H:%M:%S") if article.date_fin else "",
        "couleur_fond": "", "document_titre": article.document_titre, "public": article.public,
        "activites": [a.pk for a in article.activites.all()], "structure": article.structure_id,
        "auteur": form.initial.get("auteur") or "", "periode": "", "texte_popup": article.texte_popup or "",
    }
    data.update(overrides)
    return client.post(reverse("articles_modifier", args=[article.pk]), data)


def _animateur(structure, username="animateur"):
    """A non-staff account of the structure, granted only the Articles permission."""
    from django.contrib.contenttypes.models import ContentType

    user = UtilisateurFactory(username=username, is_staff=False, is_superuser=False)
    user.structures.add(structure)
    # The test DB is built with --nomigrations: the permission row may not exist yet
    permission, _ = Permission.objects.get_or_create(
        codename="articles_liste", content_type=ContentType.objects.get_for_model(Utilisateur),
        defaults={"name": "Individus | Articles"})
    user.user_permissions.add(permission)
    client = Client()
    client.force_login(user)
    return client


def _portail(famille):
    client = Client()
    client.force_login(Utilisateur.objects.get(pk=famille.utilisateur_id))
    return client


def _accueil(famille):
    response = _portail(famille).get(reverse("portail_accueil"))
    assert response.status_code == 200
    return response


def _articles_vus(famille):
    return [a.titre for a in _accueil(famille).context["articles"]]


@pytest.fixture
def famille_inscrite(famille_bureau):
    famille, _t, enfant = famille_bureau
    return famille


@pytest.fixture
def famille_ailleurs(db, organisateur):
    """A family whose child is only inscribed in another structure."""
    _u, famille, ratt = create_famille_complete(username="famille_ailleurs")
    InscriptionFactory(famille=famille, individu=ratt[1].individu,
                       activite=ActiviteFactory(structure=StructureFactory(nom="Autre structure")))
    return famille


# ---------------------------------------------------------------------------
# 1. Publication and visibility on the portal
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPublication:
    def test_article_publie_visible_par_la_famille(self, directeur_client, directeur, structure, famille_inscrite):
        article = _creer_article(directeur_client, structure)
        assert article.auteur == directeur
        accueil = _accueil(famille_inscrite)
        assert [a.titre for a in accueil.context["articles"]] == ["Fête de fin d'année"]
        html = accueil.content.decode()
        assert "Rendez-vous samedi" in html
        assert "par %s" % (directeur.get_short_name() or directeur) in html

    def test_article_non_publie_masque(self, directeur_client, structure, famille_inscrite):
        _creer_article(directeur_client, structure, statut="non_publie")
        assert _articles_vus(famille_inscrite) == []

    def test_publication_programmee(self, directeur_client, structure, famille_inscrite):
        _creer_article(directeur_client, structure, date_debut=_dt(+2))
        assert _articles_vus(famille_inscrite) == []

    def test_publication_terminee(self, directeur_client, structure, famille_inscrite):
        _creer_article(directeur_client, structure, date_debut=_dt(-10), date_fin=_dt(-1))
        assert _articles_vus(famille_inscrite) == []

    def test_publication_en_cours_avec_date_de_fin(self, directeur_client, structure, famille_inscrite):
        _creer_article(directeur_client, structure, date_debut=_dt(-10), date_fin=_dt(+1))
        assert _articles_vus(famille_inscrite) == ["Fête de fin d'année"]

    def test_le_plus_recent_en_premier(self, directeur_client, structure, famille_inscrite):
        _creer_article(directeur_client, structure, titre="Ancien", date_debut=_dt(-5))
        _creer_article(directeur_client, structure, titre="Récent", date_debut=_dt(-1))
        assert _articles_vus(famille_inscrite) == ["Récent", "Ancien"]

    def test_badge_nouveau_les_trois_premiers_jours(self, directeur_client, structure, famille_inscrite):
        _creer_article(directeur_client, structure, titre="Frais", date_debut=_dt(-1))
        _creer_article(directeur_client, structure, titre="Vieux", date_debut=_dt(-30))
        articles = {a.titre: a for a in _accueil(famille_inscrite).context["articles"]}
        assert articles["Frais"].Get_anciennete() <= 3 < articles["Vieux"].Get_anciennete()

    def test_structure_masquee(self, directeur_client, structure, famille_inscrite):
        _creer_article(directeur_client, structure)
        structure.visible = False
        structure.save()
        assert _articles_vus(famille_inscrite) == []

    def test_depublier_retire_l_article(self, directeur_client, structure, famille_inscrite):
        article = _creer_article(directeur_client, structure)
        assert _modifier_article(directeur_client, article, statut="non_publie").status_code == 302
        assert _articles_vus(famille_inscrite) == []

    def test_supprimer_retire_l_article(self, directeur_client, structure, famille_inscrite):
        article = _creer_article(directeur_client, structure)
        assert directeur_client.post(reverse("articles_supprimer", args=[article.pk])).status_code == 302
        assert _articles_vus(famille_inscrite) == []


# ---------------------------------------------------------------------------
# 2. Target audience
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPublic:
    def test_toutes_les_familles(self, directeur_client, structure, famille_inscrite, famille_ailleurs):
        _creer_article(directeur_client, structure, public="toutes")
        assert _articles_vus(famille_inscrite) == ["Fête de fin d'année"]
        assert _articles_vus(famille_ailleurs) == ["Fête de fin d'année"]

    def test_familles_inscrites_a_l_activite(self, directeur_client, structure, activite, famille_inscrite,
                                             famille_ailleurs):
        _creer_article(directeur_client, structure, public="inscrits", activites=[activite.pk])
        assert _articles_vus(famille_inscrite) == ["Fête de fin d'année"]
        assert _articles_vus(famille_ailleurs) == []

    def test_famille_inscrite_a_une_autre_activite(self, directeur_client, structure, famille_inscrite):
        autre = ActiviteFactory(structure=structure, nom="Camp")
        _creer_article(directeur_client, structure, public="inscrits", activites=[autre.pk])
        assert _articles_vus(famille_inscrite) == []

    def test_inscription_terminee(self, directeur_client, structure, activite, famille_bureau):
        famille, _t, enfant = famille_bureau
        enfant.inscription_set.update(date_fin=datetime.date.today() - datetime.timedelta(days=1))
        _creer_article(directeur_client, structure, public="inscrits", activites=[activite.pk])
        assert _articles_vus(famille) == []

    def test_activite_obligatoire_pour_les_inscrits(self, directeur_client, structure):
        response = _creer_article(directeur_client, structure, public="inscrits")
        assert response.status_code == 200
        assert "public" in response.context["form"].errors
        assert not Article.objects.exists()

    def test_seules_mes_activites_sont_proposees(self, directeur_client, activite):
        autre = ActiviteFactory(structure=StructureFactory())
        queryset = directeur_client.get(reverse("articles_ajouter")).context["form"].fields["activites"].queryset
        assert activite in queryset and autre not in queryset

    def test_toutes_les_familles_reserve_au_staff(self, organisateur, structure):
        """A non-staff director (with the Articles permission) cannot target every family."""
        client = _animateur(structure)
        choix = [c for c, _l in client.get(reverse("articles_ajouter")).context["form"].fields["public"].choices]
        assert "toutes" not in choix and "inscrits" in choix

        response = _creer_article(client, structure, public="toutes")
        assert response.status_code == 200
        assert "public" in response.context["form"].errors


# ---------------------------------------------------------------------------
# 3. Popup, attached formulaire and document
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestContenusJoints:
    def test_popup_affichee_une_seule_fois(self, directeur_client, structure, famille_inscrite):
        article = _creer_article(directeur_client, structure, texte_popup="<p>Réunion importante !</p>")
        premiere = _accueil(famille_inscrite)
        assert premiere.context["articles_popups"] == [article]
        assert "Réunion importante !" in premiere.content.decode()
        assert Lecture.objects.filter(famille=famille_inscrite, article=article).count() == 1

        assert _accueil(famille_inscrite).context["articles_popups"] == []
        assert Lecture.objects.filter(famille=famille_inscrite, article=article).count() == 1

    def test_popup_par_famille(self, directeur_client, structure, famille_inscrite, famille_ailleurs):
        article = _creer_article(directeur_client, structure, texte_popup="Info")
        _accueil(famille_inscrite)
        assert _accueil(famille_ailleurs).context["articles_popups"] == [article]

    def test_formulaire_joint(self, directeur_client, structure, famille_inscrite):
        sondage = Sondage.objects.create(titre="Inscriptions au repas", structure=structure)
        _creer_article(directeur_client, structure, sondage=sondage.pk)
        html = _accueil(famille_inscrite).content.decode()
        assert reverse("portail_sondage", kwargs={"code": sondage.code}) in html
        assert "Inscriptions au repas" in html

    def test_seuls_mes_formulaires_sont_proposes(self, directeur_client, structure):
        mien = Sondage.objects.create(titre="Mien", structure=structure)
        commun = Sondage.objects.create(titre="Commun")
        autre = Sondage.objects.create(titre="Autre", structure=StructureFactory())
        queryset = directeur_client.get(reverse("articles_ajouter")).context["form"].fields["sondage"].queryset
        assert {mien, commun} <= set(queryset) and autre not in queryset

    def test_document_joint(self, directeur_client, structure, famille_inscrite, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        document = SimpleUploadedFile("programme.pdf", b"%PDF-1.4 programme", content_type="application/pdf")
        article = _creer_article(directeur_client, structure, document=document, document_titre="Programme")
        html = _accueil(famille_inscrite).content.decode()
        assert article.document.url in html
        assert "Programme" in html


# ---------------------------------------------------------------------------
# 4. Director's article management
# ---------------------------------------------------------------------------

def _liste(client):
    from django.test import RequestFactory
    from parametrage.views.articles import Liste

    request = RequestFactory().get("/")
    request.user = Utilisateur.objects.get(pk=client.session["_auth_user_id"])
    view = Liste()
    view.setup(request)
    return set(view.get_queryset())


@pytest.mark.django_db
class TestGestionDirecteur:
    def test_liste_des_articles(self, directeur_client, structure):
        article = _creer_article(directeur_client, structure)
        assert directeur_client.get(reverse("articles_liste")).status_code == 200
        assert _liste(directeur_client) == {article}

    def test_articles_d_une_autre_structure_non_listes(self, directeur_client, structure):
        mien = _creer_article(directeur_client, structure)
        Article.objects.create(titre="Ailleurs", texte="x", date_debut=MAINTENANT, public="toutes",
                               structure=StructureFactory())
        assert _liste(directeur_client) == {mien}

    def test_un_animateur_ne_voit_que_ses_articles(self, organisateur, structure, directeur_client):
        client = _animateur(structure)
        sien = _creer_article(client, structure, titre="Article animateur", public="inscrits",
                              activites=[ActiviteFactory(structure=structure).pk])
        _creer_article(directeur_client, structure, titre="Article directeur")
        assert _liste(client) == {sien}

    def test_dupliquer(self, directeur_client, structure, activite):
        article = _creer_article(directeur_client, structure, public="inscrits", activites=[activite.pk])
        response = directeur_client.post(reverse("articles_dupliquer", args=[article.pk]), {"dupliquer_ouvrir": "1"})
        copie = Article.objects.get(titre="Copie de Fête de fin d'année")
        assert response.status_code == 302
        assert copie.texte == article.texte and copie.structure == structure

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: Dupliquer uses deepcopy + save(), which does not copy the many-to-many fields: the copy of "
        "an article for 'familles inscrites' has no activity left and is shown to nobody."
    ))
    def test_dupliquer_conserve_le_public(self, directeur_client, structure, activite, famille_inscrite):
        article = _creer_article(directeur_client, structure, public="inscrits", activites=[activite.pk])
        directeur_client.post(reverse("articles_dupliquer", args=[article.pk]))
        copie = Article.objects.get(titre="Copie de Fête de fin d'année")
        assert list(copie.activites.all()) == [activite]
        assert "Copie de Fête de fin d'année" in _articles_vus(famille_inscrite)

    @pytest.mark.xfail(strict=True, reason=(
        "À CONFIRMER: a duplicate keeps the 'Publié' status and dates, so the copy appears on every "
        "family's home page immediately, next to the original, before the director has edited it."
    ))
    def test_la_copie_n_est_pas_publiee_d_office(self, directeur_client, structure, famille_inscrite):
        article = _creer_article(directeur_client, structure)
        directeur_client.post(reverse("articles_dupliquer", args=[article.pk]))
        assert _articles_vus(famille_inscrite) == ["Fête de fin d'année"]

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the image type offers only 'Aucune image' / 'Importation', while the form also shows the "
        "image bank field and clean() handles 'banque_images': images of Paramétrage > Images d'articles "
        "can never be attached to an article."
    ))
    def test_image_de_la_banque(self, directeur_client, structure, settings, tmp_path):
        from core.models import ImageArticle

        import io

        from PIL import Image

        settings.MEDIA_ROOT = str(tmp_path)
        contenu = io.BytesIO()
        Image.new("RGB", (40, 30), "orange").save(contenu, format="PNG")
        image = ImageArticle.objects.create(titre="Feu de camp", image=SimpleUploadedFile(
            "feu.png", contenu.getvalue(), content_type="image/png"))
        article = _creer_article(directeur_client, structure, type_image="banque_images", image_article=image.pk)
        assert isinstance(article, Article) and article.image_article == image

    def test_importer_une_image_sans_fichier_refuse(self, directeur_client, structure):
        response = _creer_article(directeur_client, structure, type_image="importer")
        assert response.status_code == 200
        assert "type_image" in response.context["form"].errors

    def test_pages_reservees_au_staff(self, structure, famille_inscrite, directeur_client):
        article = _creer_article(directeur_client, structure)
        for url in (reverse("articles_liste"), reverse("articles_ajouter"),
                    reverse("articles_modifier", args=[article.pk])):
            assert Client().get(url).status_code == 302
            assert _portail(famille_inscrite).get(url).status_code == 403

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (directors are limited to their structures): the 'Structure associée' field lists every "
        "structure, so a director can publish an article in the name of another structure."
    ))
    def test_seules_mes_structures_sont_proposees(self, directeur_client, structure):
        autre = StructureFactory()
        queryset = directeur_client.get(reverse("articles_ajouter")).context["form"].fields["structure"].queryset
        assert structure in queryset and autre not in queryset

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (directors are limited to their structures): an article of another structure can be edited "
        "(or deleted) by opening its URL."
    ))
    def test_modifier_un_article_d_une_autre_structure_interdit(self, directeur_client):
        article = Article.objects.create(titre="Ailleurs", texte="x", date_debut=MAINTENANT, public="toutes",
                                         structure=StructureFactory())
        assert directeur_client.get(reverse("articles_modifier", args=[article.pk])).status_code in (403, 404)


# ---------------------------------------------------------------------------
# 5. Photo album, director's home widget
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_album_joint_accessible_a_la_famille(directeur_client, structure, famille_inscrite):
    from core.models import Album

    album = Album.objects.create(titre="Photos du camp", structure=structure)
    _creer_article(directeur_client, structure, album=album.pk)
    url = reverse("portail_album", kwargs={"code": album.code})
    assert url in _accueil(famille_inscrite).content.decode()
    response = _portail(famille_inscrite).get(url)
    assert response.status_code == 200
    assert response.context["album"] == album


@pytest.mark.django_db
def test_seuls_mes_albums_sont_proposes(directeur_client, structure):
    from core.models import Album

    mien = Album.objects.create(titre="Mien", structure=structure)
    autre = Album.objects.create(titre="Autre", structure=StructureFactory())
    queryset = directeur_client.get(reverse("articles_ajouter")).context["form"].fields["album"].queryset
    assert mien in queryset and autre not in queryset


def _widget_articles(user):
    from core.views.accueil_widgets.articles import Widget
    from django.test import RequestFactory

    widget = Widget.__new__(Widget)
    widget.request = RequestFactory().get("/")
    widget.request.user = user
    articles, _popups = widget.Get_articles()
    return [a.titre for a in articles]


@pytest.mark.django_db
class TestWidgetAccueilDirecteur:
    def test_le_directeur_voit_ses_articles_publies(self, directeur_client, directeur, structure, activite):
        _creer_article(directeur_client, structure, titre="Pour tous")
        _creer_article(directeur_client, structure, titre="Pour les inscrits", public="inscrits",
                       activites=[activite.pk])
        _creer_article(directeur_client, structure, titre="Brouillon", statut="non_publie")
        _creer_article(directeur_client, structure, titre="Programmé", date_debut=_dt(+3))
        assert set(_widget_articles(directeur)) == {"Pour tous", "Pour les inscrits"}

    def test_articles_inscrits_d_une_autre_structure_masques(self, directeur):
        voisine = StructureFactory()
        article = Article.objects.create(titre="Voisin", texte="x", date_debut=MAINTENANT - datetime.timedelta(1),
                                         public="inscrits", structure=voisine)
        article.activites.add(ActiviteFactory(structure=voisine))
        assert _widget_articles(directeur) == []
