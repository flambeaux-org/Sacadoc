import pytest
from django.core.cache import cache
from django.core.mail.backends.console import EmailBackend

from core.models import Destinataire, Mail, SignatureEmail
from tests.unit.factories import AdresseMailFactory, OrganisateurFactory, UtilisateurFactory

URL = "/utilisateur/outils/envoyer_email_express"
HTML_AVEC_SIGNATURE = "<p>Bonjour,</p><p>{UTILISATEUR_SIGNATURE}</p>"


@pytest.mark.django_db
class TestEnvoyerEmailExpress:
    @pytest.fixture(autouse=True)
    def setup_data(self, db):
        # Envoyer_model_mail met l'organisateur en cache : on repart d'un cache vide
        cache.clear()
        OrganisateurFactory(pk=1)
        self.adresse_exp = AdresseMailFactory()
        self.user = UtilisateurFactory()
        yield
        cache.clear()

    def _post(self, client, html):
        mail = Mail.objects.create(
            categorie="saisie_libre",
            objet="Objet",
            html=html,
            adresse_exp=self.adresse_exp,
            utilisateur=self.user,
        )
        mail.destinataires.add(
            Destinataire.objects.create(categorie="famille", adresse="famille@test.org")
        )
        client.force_login(self.user)
        return client.post(
            URL,
            data={
                "idmail": mail.pk,
                "objet": "Objet",
                "html": html,
                "adresse_exp": self.adresse_exp.pk,
                "dest": "Famille Test <famille@test.org>",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    def test_envoi_reussi(self, client):
        self.user.signature = SignatureEmail.objects.create(nom="Sig", html="<p>Signé</p>")
        self.user.save()

        response = self._post(client, HTML_AVEC_SIGNATURE)

        assert response.status_code == 200
        assert "envoyé avec succès à 1 destinataire" in response.json()["message"]

    def test_signature_manquante(self, client):
        """Le texte réclame {UTILISATEUR_SIGNATURE} mais l'utilisateur n'a pas de signature :
        Envoyer_model_mail renvoyait None et la vue plantait (TypeError)."""
        response = self._post(client, HTML_AVEC_SIGNATURE)

        assert response.status_code == 401
        assert "signature" in response.json()["message"]

    def test_connexion_impossible(self, client, monkeypatch):
        def open_en_echec(self):
            raise ConnectionRefusedError

        monkeypatch.setattr(EmailBackend, "open", open_en_echec)

        response = self._post(client, "<p>Bonjour</p>")

        assert response.status_code == 401
        assert "Connexion impossible" in response.json()["message"]

    def test_mode_demo(self, client, settings):
        settings.MODE_DEMO = True

        response = self._post(client, "<p>Bonjour</p>")

        assert response.status_code == 401
        assert "mode démo" in response.json()["message"]
