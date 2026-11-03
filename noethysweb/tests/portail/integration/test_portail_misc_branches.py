"""Branch coverage for album, mentions legales and the e-mail unsubscribe page."""

import pytest
from core.models import Album, Photo
from django.core import signing
from django.urls import reverse


@pytest.mark.django_db
class TestAlbum:
    def test_anonymous_redirected_to_connexion(self, client, organisateur):
        album = Album.objects.create(titre="A")
        response = client.get(reverse("portail_album", kwargs={"code": album.code}))
        assert response.status_code == 302
        assert response.url == reverse("portail_connexion")

    def test_staff_forbidden(self, client, staff_user, organisateur):
        album = Album.objects.create(titre="A")
        client.force_login(staff_user)
        assert (
            client.get(
                reverse("portail_album", kwargs={"code": album.code})
            ).status_code
            == 403
        )

    def test_valid_code_lists_photos_ordered_by_date(self, logged_client):
        import datetime

        album = Album.objects.create(titre="Camp", description="<p>desc</p>")
        p2 = Photo.objects.create(
            album=album,
            fichier="photos/b.jpg",
            date_creation=datetime.datetime(2024, 2, 1),
        )
        p1 = Photo.objects.create(
            album=album,
            fichier="photos/a.jpg",
            date_creation=datetime.datetime(2024, 1, 1),
        )
        other = Album.objects.create(titre="Autre")
        Photo.objects.create(album=other, fichier="photos/c.jpg")
        response = logged_client.get(
            reverse("portail_album", kwargs={"code": album.code})
        )
        assert response.status_code == 200
        assert response.context["album"] == album
        assert list(response.context["photos"]) == [p1, p2]
        assert "Camp" in response.content.decode()

    def test_empty_album_renders(self, logged_client):
        album = Album.objects.create(titre="Vide")
        response = logged_client.get(
            reverse("portail_album", kwargs={"code": album.code})
        )
        assert response.status_code == 200
        assert list(response.context["photos"]) == []
        assert "Album vide" in response.content.decode()

    @pytest.mark.xfail(
        reason="BUG: portail/views/album.py uses Album.objects.get(code=...): an unknown code "
        "raises Album.DoesNotExist (500) instead of returning 404.",
        strict=True,
    )
    def test_invalid_code_gives_404(self, logged_client):
        response = logged_client.get(
            reverse("portail_album", kwargs={"code": "does-not-exist"})
        )
        assert response.status_code == 404


@pytest.mark.django_db
class TestMentions:
    def test_anonymous_redirected(self, client, organisateur):
        response = client.get(reverse("portail_mentions"))
        assert response.status_code == 302
        assert response.url == reverse("portail_connexion")

    def test_staff_forbidden(self, client, staff_user, organisateur):
        client.force_login(staff_user)
        assert client.get(reverse("portail_mentions")).status_code == 403

    def test_renders_with_placeholders_replaced(
        self, logged_client, organisateur, set_parametre_portail
    ):
        organisateur.nom, organisateur.rue, organisateur.cp, organisateur.ville = (
            "Asso",
            "2 rue Y",
            "69001",
            "Lyon",
        )
        organisateur.save()
        set_parametre_portail(
            "mentions_conditions_generales",
            "{ORGANISATEUR_NOM}/{ORGANISATEUR_RUE}/{ORGANISATEUR_CP}/{ORGANISATEUR_VILLE}",
        )
        response = logged_client.get(reverse("portail_mentions"))
        assert response.status_code == 200
        assert response.context["texte_conditions"] == "Asso/2 rue Y/69001/Lyon"

    def test_none_organisateur_fields_become_empty(
        self, logged_client, organisateur, set_parametre_portail
    ):
        organisateur.cp = None
        organisateur.save()
        set_parametre_portail("mentions_conditions_generales", "<{ORGANISATEUR_CP}>")
        assert (
            logged_client.get(reverse("portail_mentions")).context["texte_conditions"]
            == "<>"
        )

    def test_page_reachable_even_when_menu_entry_hidden(
        self, logged_client, set_parametre_portail
    ):
        """mentions_afficher_page only hides the menu entry; the URL itself still works."""
        set_parametre_portail("mentions_afficher_page", False)
        assert logged_client.get(reverse("portail_mentions")).status_code == 200

    @pytest.mark.xfail(
        reason="BUG: mentions.View (and password_change) call getattr(context['organisateur'], ...) "
        "without handling organisateur=None; with no Organisateur pk=1 row the page raises "
        "AttributeError (500).",
        strict=True,
    )
    def test_without_organisateur_does_not_crash(
        self, logged_client, set_parametre_portail
    ):
        from core.models import Organisateur
        from django.core.cache import cache

        set_parametre_portail("mentions_conditions_generales", "{ORGANISATEUR_NOM}")
        Organisateur.objects.all().delete()  # logged_client pulls in the organisateur fixture
        cache.clear()
        assert logged_client.get(reverse("portail_mentions")).status_code == 200


@pytest.mark.django_db
class TestDesinscription:
    def url(self, valeur):
        return reverse("desinscription", kwargs={"valeur": valeur})

    def test_valid_value_blocks_group_emails(self, client, famille_user):
        _u, famille, _r = famille_user
        famille.mail = "parent@example.org"
        famille.save()
        valeur = signing.dumps({"pk": str(famille.pk), "mail": "parent@example.org"})
        response = client.get(self.url(valeur))
        assert response.status_code == 200
        assert response.context["resultat"] is True
        assert "Désinscription validée" in response.content.decode()
        famille.refresh_from_db()
        assert famille.email_blocage is True

    def test_mail_mismatch_is_refused(self, client, famille_user):
        _u, famille, _r = famille_user
        famille.mail = "parent@example.org"
        famille.save()
        valeur = signing.dumps({"pk": str(famille.pk), "mail": "autre@example.org"})
        response = client.get(self.url(valeur))
        assert response.context["resultat"] is False
        assert "Demande non valide" in response.content.decode()
        famille.refresh_from_db()
        assert famille.email_blocage is False

    def test_garbage_value_is_refused(self, client, db):
        response = client.get(self.url("not-a-signed-value"))
        assert response.status_code == 200
        assert response.context["resultat"] is False

    def test_tampered_signature_is_refused(self, client, famille_user):
        _u, famille, _r = famille_user
        famille.mail = "parent@example.org"
        famille.save()
        valeur = (
            signing.dumps({"pk": str(famille.pk), "mail": "parent@example.org"}) + "x"
        )
        assert client.get(self.url(valeur)).context["resultat"] is False
        famille.refresh_from_db()
        assert famille.email_blocage is False

    def test_unknown_famille_is_refused(self, client, db):
        valeur = signing.dumps({"pk": "999999", "mail": "x@example.org"})
        assert client.get(self.url(valeur)).context["resultat"] is False

    def test_post_not_allowed(self, client, db):
        assert client.post(self.url("abc")).status_code == 405

    def test_works_without_login(self, client, famille_user):
        """Link in e-mails: must work for anonymous visitors (no CSRF/login required)."""
        _u, famille, _r = famille_user
        famille.mail = "p@example.org"
        famille.save()
        valeur = signing.dumps({"pk": str(famille.pk), "mail": "p@example.org"})
        assert client.get(self.url(valeur)).status_code == 200
