"""Photo albums, end to end: the director creates an album and imports photos in
Paramétrage > Albums photos, attaches it to an article, and the family browses it on the portal.

Business rules under test:
- photos are imported (several at once) through the upload widget, only image files;
- photos are sorted by their shooting date (EXIF), which the director can correct;
- deleting a photo removes it from the portal (and from the server: these are photos of children);
- an album still holding photos cannot be deleted;
- a director works within his structures.
"""

import datetime
import io
import os

import pytest
from core.models import Album, Article, Photo, Utilisateur
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from PIL import Image
from tests.bureau.conftest import AJAX
from tests.unit.factories import StructureFactory


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    """Isolated media folder, laid out like production (MEDIA_ROOT = BASE_DIR/media)."""
    settings.BASE_DIR = str(tmp_path)
    settings.MEDIA_ROOT = os.path.join(str(tmp_path), "media")
    return tmp_path


def _jpeg(nom="photo.jpg", couleur="orange", prise_de_vue=None):
    image = Image.new("RGB", (60, 40), couleur)
    contenu = io.BytesIO()
    if prise_de_vue:
        exif = image.getexif()
        exif.get_ifd(0x8769)[36867] = prise_de_vue.strftime("%Y:%m:%d %H:%M:%S")  # DateTimeOriginal
        image.save(contenu, format="JPEG", exif=exif)
    else:
        image.save(contenu, format="JPEG")
    return SimpleUploadedFile(nom, contenu.getvalue(), content_type="image/jpeg")


def _creer_album(client, structure, titre="Camp d'été 2026", description="<p>Les photos du camp</p>"):
    response = client.post(reverse("albums_ajouter"), {"titre": titre, "description": description,
                                                       "structure": structure.pk})
    if response.status_code != 302:
        return response
    album = Album.objects.get(titre=titre)
    assert response["Location"] == reverse("albums_consulter", kwargs={"pk": album.pk})
    return album


def _importer(client, album, *fichiers):
    return client.post(reverse("ajax_importer_photos_album"),
                       {"idalbum": album.pk, "files": list(fichiers)}, **AJAX)


def _publier(album, structure):
    """Attach the album to an article shown to every family."""
    return Article.objects.create(titre="Retour en images", texte="x", public="toutes", structure=structure,
                                  album=album, date_debut=datetime.datetime.now() - datetime.timedelta(days=1))


def _portail(famille):
    client = Client()
    client.force_login(Utilisateur.objects.get(pk=famille.utilisateur_id))
    return client


def _album_portail(famille, album):
    response = _portail(famille).get(reverse("portail_album", kwargs={"code": album.code}))
    assert response.status_code == 200
    return response


@pytest.fixture
def album(directeur_client, structure):
    return _creer_album(directeur_client, structure)


# ---------------------------------------------------------------------------
# 1. Album and photo import (director)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAlbumDirecteur:
    def test_creer_un_album(self, directeur_client, structure):
        album = _creer_album(directeur_client, structure)
        assert album.structure == structure
        assert album.code  # unguessable code used in the portal URL
        assert directeur_client.get(reverse("albums_consulter", kwargs={"pk": album.pk})).status_code == 200

    def test_titre_obligatoire(self, directeur_client, structure):
        response = _creer_album(directeur_client, structure, titre="")
        assert response.status_code == 200
        assert "titre" in response.context["form"].errors

    def test_importer_plusieurs_photos(self, directeur_client, album):
        response = _importer(directeur_client, album, _jpeg("a.jpg"), _jpeg("b.jpg", "blue"))
        assert response.json() == {"action": "redirect",
                                   "url": reverse("albums_consulter", kwargs={"pk": album.pk})}
        photos = Photo.objects.filter(album=album)
        assert photos.count() == 2
        assert all(photo.fichier.storage.exists(photo.fichier.name) for photo in photos)
        consulter = directeur_client.get(reverse("albums_consulter", kwargs={"pk": album.pk}))
        assert list(consulter.context["photos"]) == list(photos.order_by("pk"))

    def test_date_de_prise_de_vue_lue_dans_l_exif(self, directeur_client, album):
        _importer(directeur_client, album, _jpeg(prise_de_vue=datetime.datetime(2026, 7, 14, 10, 30)))
        assert Photo.objects.get(album=album).date_creation == datetime.datetime(2026, 7, 14, 10, 30)

    def test_photo_sans_exif(self, directeur_client, album):
        _importer(directeur_client, album, _jpeg())
        assert Photo.objects.get(album=album).date_creation is None

    def test_fichier_interdit_refuse(self, directeur_client, album):
        programme = SimpleUploadedFile("virus.exe", b"MZ...", content_type="application/octet-stream")
        response = _importer(directeur_client, album, programme)
        assert response.json()["action"] == "replace"
        assert not Photo.objects.filter(album=album).exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: the album upload only restricts types in the browser (accept='image/*'); server-side the "
        "upload_form default list is used, so PDF, Word, Excel, text or video files are stored as "
        "'photos' and show up as broken images on the portal."
    ))
    def test_seules_les_images_sont_acceptees(self, directeur_client, album):
        document = SimpleUploadedFile("compte_rendu.pdf", b"%PDF-1.4", content_type="application/pdf")
        _importer(directeur_client, album, document)
        assert not Photo.objects.filter(album=album).exists()

    def test_modifier_titre_et_date_d_une_photo(self, directeur_client, album):
        _importer(directeur_client, album, _jpeg())
        photo = Photo.objects.get(album=album)
        url = reverse("albums_modifier_photo", kwargs={"idalbum": album.pk, "pk": photo.pk})
        response = directeur_client.post(url, {"titre": "Veillée", "date_creation": "2026-07-15 21:00:00"})
        assert response["Location"] == reverse("albums_consulter", kwargs={"pk": album.pk})
        photo.refresh_from_db()
        assert photo.titre == "Veillée"
        assert photo.date_creation == datetime.datetime(2026, 7, 15, 21, 0)

    def test_supprimer_une_photo(self, directeur_client, album):
        _importer(directeur_client, album, _jpeg())
        photo = Photo.objects.get(album=album)
        url = reverse("albums_supprimer_photo", kwargs={"idalbum": album.pk, "pk": photo.pk})
        assert directeur_client.post(url)["Location"] == reverse("albums_consulter", kwargs={"pk": album.pk})
        assert not Photo.objects.filter(pk=photo.pk).exists()

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (privacy): deleting a photo only removes the database row; the image file stays on the "
        "server and is still served at its /media/ URL. These are photos of children (e.g. image "
        "rights withdrawn by the parents)."
    ))
    def test_supprimer_une_photo_efface_le_fichier(self, directeur_client, album):
        _importer(directeur_client, album, _jpeg())
        photo = Photo.objects.get(album=album)
        stockage, nom = photo.fichier.storage, photo.fichier.name
        directeur_client.post(reverse("albums_supprimer_photo", kwargs={"idalbum": album.pk, "pk": photo.pk}))
        assert not stockage.exists(nom)

    def test_supprimer_plusieurs_photos(self, directeur_client, album):
        _importer(directeur_client, album, _jpeg("a.jpg"), _jpeg("b.jpg"), _jpeg("c.jpg"))
        a, b, c = Photo.objects.filter(album=album).order_by("pk")
        url = reverse("albums_supprimer_plusieurs_photos", kwargs={"idalbum": album.pk, "listepk": "%d;%d" % (a.pk, b.pk)})
        assert directeur_client.get(url).status_code == 200
        directeur_client.post(url)
        assert list(Photo.objects.filter(album=album)) == [c]

    def test_album_avec_photos_non_supprimable(self, directeur_client, album):
        _importer(directeur_client, album, _jpeg())
        directeur_client.post(reverse("albums_supprimer", args=[album.pk]))
        assert Album.objects.filter(pk=album.pk).exists()
        assert Photo.objects.filter(album=album).count() == 1

    def test_supprimer_un_album_vide(self, directeur_client, album):
        assert directeur_client.post(reverse("albums_supprimer", args=[album.pk])).status_code == 302
        assert not Album.objects.filter(pk=album.pk).exists()

    def test_liste_des_albums_de_mes_structures(self, directeur_client, album):
        from django.test import RequestFactory
        from parametrage.views.albums import Liste

        _importer(directeur_client, album, _jpeg("a.jpg"), _jpeg("b.jpg"))
        Album.objects.create(titre="Album voisin", structure=StructureFactory())
        assert directeur_client.get(reverse("albums_liste")).status_code == 200
        request = RequestFactory().get("/")
        request.user = Utilisateur.objects.get(username="directeur")
        view = Liste()
        view.setup(request)
        albums = list(view.get_queryset())
        assert albums == [album]
        assert albums[0].nbre_photos == 2

    def test_pages_reservees_au_staff(self, directeur_client, famille_bureau, album):
        famille, _t, _e = famille_bureau
        for url in (reverse("albums_liste"), reverse("albums_consulter", kwargs={"pk": album.pk})):
            assert Client().get(url).status_code == 302
            assert _portail(famille).get(url).status_code == 403
        assert _portail(famille).post(reverse("ajax_importer_photos_album"),
                                      {"idalbum": album.pk, "files": [_jpeg()]}, **AJAX).status_code == 403
        assert not Photo.objects.exists()


# ---------------------------------------------------------------------------
# 2. The family browses the album
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestAlbumPortail:
    def test_la_famille_ouvre_l_album_depuis_l_article(self, directeur_client, structure, album, famille_bureau):
        famille, _t, _e = famille_bureau
        _importer(directeur_client, album, _jpeg())
        _publier(album, structure)
        accueil = _portail(famille).get(reverse("portail_accueil")).content.decode()
        assert reverse("portail_album", kwargs={"code": album.code}) in accueil

        import html as html_lib

        response = _album_portail(famille, album)
        html = html_lib.unescape(response.content.decode())
        assert "Camp d'été 2026" in html and "Les photos du camp" in html
        photo = Photo.objects.get(album=album)
        assert photo.fichier.url in html

    def test_photos_triees_par_date_de_prise_de_vue(self, directeur_client, structure, album, famille_bureau):
        famille, _t, _e = famille_bureau
        # Imported in the wrong order: the portal follows the shooting date
        _importer(directeur_client, album,
                  _jpeg("soir.jpg", prise_de_vue=datetime.datetime(2026, 7, 14, 21, 0)),
                  _jpeg("matin.jpg", prise_de_vue=datetime.datetime(2026, 7, 14, 8, 0)))
        _publier(album, structure)
        dates = [p.date_creation for p in _album_portail(famille, album).context["photos"]]
        assert dates == [datetime.datetime(2026, 7, 14, 8, 0), datetime.datetime(2026, 7, 14, 21, 0)]

    def test_la_correction_de_date_change_l_ordre(self, directeur_client, structure, album, famille_bureau):
        famille, _t, _e = famille_bureau
        _importer(directeur_client, album,
                  _jpeg("a.jpg", prise_de_vue=datetime.datetime(2026, 7, 14, 8, 0)),
                  _jpeg("b.jpg", prise_de_vue=datetime.datetime(2026, 7, 14, 9, 0)))
        premiere, seconde = Photo.objects.filter(album=album).order_by("date_creation")
        directeur_client.post(reverse("albums_modifier_photo", kwargs={"idalbum": album.pk, "pk": seconde.pk}),
                              {"titre": "Arrivée", "date_creation": "2026-07-13 18:00:00"})
        assert list(_album_portail(famille, album).context["photos"]) == [seconde, premiere]
        assert "Arrivée" in _album_portail(famille, album).content.decode()

    def test_photo_supprimee_disparait_du_portail(self, directeur_client, structure, album, famille_bureau):
        famille, _t, _e = famille_bureau
        _importer(directeur_client, album, _jpeg("a.jpg"), _jpeg("b.jpg"))
        retiree, gardee = Photo.objects.filter(album=album).order_by("pk")
        directeur_client.post(reverse("albums_supprimer_photo", kwargs={"idalbum": album.pk, "pk": retiree.pk}))
        assert list(_album_portail(famille, album).context["photos"]) == [gardee]

    def test_album_reserve_aux_familles_connectees(self, album, famille_bureau):
        url = reverse("portail_album", kwargs={"code": album.code})
        response = Client().get(url)
        assert response.status_code == 302 and "connexion" in response["Location"]

    @pytest.mark.xfail(strict=True, reason=(
        "BUG: an unknown album code raises Album.DoesNotExist (500) instead of a 404 page."
    ))
    def test_code_inconnu(self, famille_bureau):
        famille, _t, _e = famille_bureau
        assert _portail(famille).get(reverse("portail_album", kwargs={"code": "inconnu"})).status_code == 404


# ---------------------------------------------------------------------------
# 3. Director's perimeter
# ---------------------------------------------------------------------------

@pytest.fixture
def album_voisin(db):
    return Album.objects.create(titre="Album voisin", structure=StructureFactory())


@pytest.mark.django_db
class TestPerimetre:
    @pytest.mark.xfail(strict=True, reason=(
        "BUG (directors are limited to their structures): the 'Structure associée' field of an album lists "
        "every structure."
    ))
    def test_seules_mes_structures_sont_proposees(self, directeur_client, structure):
        autre = StructureFactory()
        queryset = directeur_client.get(reverse("albums_ajouter")).context["form"].fields["structure"].queryset
        assert structure in queryset and autre not in queryset

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (directors are limited to their structures): another structure's album (and its photos) "
        "opens by its URL in Paramétrage > Albums."
    ))
    def test_consulter_l_album_d_une_autre_structure_interdit(self, directeur_client, album_voisin):
        response = directeur_client.get(reverse("albums_consulter", kwargs={"pk": album_voisin.pk}))
        assert response.status_code in (403, 404)

    @pytest.mark.xfail(strict=True, reason=(
        "BUG (directors are limited to their structures): the AJAX import trusts the posted idalbum, so a "
        "director can add photos to another structure's album."
    ))
    def test_importer_dans_l_album_d_une_autre_structure_interdit(self, directeur_client, album_voisin):
        _importer(directeur_client, album_voisin, _jpeg())
        assert not Photo.objects.filter(album=album_voisin).exists()
