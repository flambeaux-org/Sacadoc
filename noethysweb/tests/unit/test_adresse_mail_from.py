# -*- coding: utf-8 -*-
"""Tests de AdresseMail.Get_from_email : format du header From des mails envoyés."""
from email.header import decode_header, make_header
from email.utils import parseaddr

import pytest
from django.core.mail import EmailMultiAlternatives

from core.models import AdresseMail


def _adresse(adresse="contact@asso.org", nom_adresse=None):
    # Instance non sauvegardée : aucun accès base de données nécessaire
    return AdresseMail(adresse=adresse, nom_adresse=nom_adresse, moteur="console")


class TestGetFromEmail:
    def test_sans_nom_retourne_adresse_seule(self):
        assert _adresse(nom_adresse=None).Get_from_email() == "contact@asso.org"

    @pytest.mark.parametrize("nom", ["", "   "])
    def test_nom_vide_ou_espaces_retourne_adresse_seule(self, nom):
        assert _adresse(nom_adresse=nom).Get_from_email() == "contact@asso.org"

    def test_avec_nom_format_nom_chevrons_adresse(self):
        assert _adresse(nom_adresse="Les Flambeaux").Get_from_email() == "Les Flambeaux <contact@asso.org>"

    def test_nom_est_strippe(self):
        assert _adresse(nom_adresse="  Les Flambeaux  ").Get_from_email() == "Les Flambeaux <contact@asso.org>"

    def test_nom_avec_virgule_est_entre_guillemets(self):
        # Une virgule non protégée serait lue comme un séparateur de deux adresses
        resultat = _adresse(nom_adresse="Asso, Section Jeunes").Get_from_email()
        assert resultat == '"Asso, Section Jeunes" <contact@asso.org>'
        assert parseaddr(resultat) == ("Asso, Section Jeunes", "contact@asso.org")

    def test_nom_avec_guillemets_est_echappe(self):
        resultat = _adresse(nom_adresse='Asso "Les Flambeaux"').Get_from_email()
        assert parseaddr(resultat) == ('Asso "Les Flambeaux"', "contact@asso.org")

    def test_nom_avec_accents(self):
        resultat = _adresse(nom_adresse="Association Éducative").Get_from_email()
        assert resultat == "Association Éducative <contact@asso.org>"

    def test_saut_de_ligne_interdit_dans_le_nom(self):
        # Protection contre l'injection de header
        with pytest.raises(ValueError):
            _adresse(nom_adresse="Asso\nBcc: pirate@evil.org").Get_from_email()


class TestHeaderFromDuMessage:
    """Vérifie le header From réellement produit par EmailMultiAlternatives."""

    def _header_from(self, adresse_mail):
        message = EmailMultiAlternatives(
            subject="Sujet", body="Corps", from_email=adresse_mail.Get_from_email(), to=["dest@example.org"],
        )
        return message.message()["From"]

    def test_header_avec_nom(self):
        header = self._header_from(_adresse(nom_adresse="Les Flambeaux"))
        assert header == "Les Flambeaux <contact@asso.org>"
        assert parseaddr(header) == ("Les Flambeaux", "contact@asso.org")

    def test_header_sans_nom(self):
        header = self._header_from(_adresse(nom_adresse=None))
        assert header == "contact@asso.org"
        assert parseaddr(header) == ("", "contact@asso.org")

    def test_header_avec_accents_est_encode_mais_decodable(self):
        header = self._header_from(_adresse(nom_adresse="Association Éducative"))
        nom, adresse = parseaddr(header)
        assert adresse == "contact@asso.org"
        assert str(make_header(decode_header(nom))) == "Association Éducative"
