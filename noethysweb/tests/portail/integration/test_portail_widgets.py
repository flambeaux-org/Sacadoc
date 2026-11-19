"""Tests for portail/widgets.py (ValidationApprobation and Selection_image_article widgets)."""

import datetime

import pytest
from core.models import TypeConsentement, UniteConsentement
from django.utils.safestring import SafeString
from portail.widgets import Selection_image_article, ValidationApprobation
from tests.unit.factories import FamilleFactory, IndividuFactory, RattachementFactory


class FakeDocument:
    url = "/media/doc.pdf"


class TestValidationApprobationContext:
    def test_context_basic(self):
        ctx = ValidationApprobation().get_context("approb", None)
        assert ctx == {"name": "approb"}

    def test_context_includes_widget_attrs(self):
        ctx = ValidationApprobation(attrs={"id": "x1"}).get_context("n", None)
        assert ctx["id"] == "x1"

    def test_context_extra_attrs_override_widget_attrs(self):
        ctx = ValidationApprobation(attrs={"id": "x1", "a": 1}).get_context(
            "n", None, attrs={"id": "x2", "b": 2}
        )
        assert (ctx["id"], ctx["a"], ctx["b"]) == ("x2", 1, 2)

    def test_context_value_set_when_not_none(self):
        assert ValidationApprobation().get_context("n", "v")["value"] == "v"

    def test_context_falsy_value_kept(self):
        assert ValidationApprobation().get_context("n", "")["value"] == ""

    def test_context_value_absent_when_none(self):
        assert "value" not in ValidationApprobation().get_context("n", None)


@pytest.mark.django_db
class TestValidationApprobationRender:
    def test_render_returns_safe_string_checkbox(self):
        html = ValidationApprobation(attrs={"id": "chk1"}).render("approb_1", None)
        assert isinstance(html, SafeString)
        assert 'name="approb_1"' in html
        assert 'id="chk1"' in html
        assert 'type="checkbox"' in html
        assert "<a href" not in html

    def test_render_unite_consentement(self):
        tc = TypeConsentement.objects.create(nom="Reglement interieur")
        unite = UniteConsentement(
            type_consentement=tc, date_debut=datetime.date(2025, 9, 1)
        )
        unite.document = FakeDocument()
        html = ValidationApprobation(
            attrs={"id": "c", "unite_consentement": unite}
        ).render("n", None)
        assert "Reglement interieur" in html
        assert "01/09/2025" in html
        assert 'href="/media/doc.pdf"' in html

    def test_render_rattachement(self):
        indiv = IndividuFactory(nom="DUPONT", prenom="Lea")
        ratt = RattachementFactory(individu=indiv, famille=FamilleFactory())
        html = ValidationApprobation(attrs={"id": "c", "rattachement": ratt}).render(
            "n", None
        )
        assert "fiche de" in html
        assert indiv.Get_nom() in html
        assert "fiche famille" not in html

    def test_render_famille(self):
        html = ValidationApprobation(
            attrs={"id": "c", "famille": FamilleFactory()}
        ).render("n", None)
        assert "fiche famille" in html


class TestSelectionImageArticleContext:
    def widget(self, **kwargs):
        w = Selection_image_article(**kwargs)
        w.choices = [(1, "Un", "a.png"), (2, "Deux", None)]
        return w

    def test_context_has_choices_and_name(self):
        w = self.widget()
        ctx = w.get_context("img", None)
        assert ctx["choices"] == w.choices
        assert ctx["name"] == "img"
        assert "value" not in ctx

    def test_context_attrs_merge(self):
        ctx = self.widget(attrs={"id": "a", "x": 1}).get_context(
            "n", 2, attrs={"id": "b"}
        )
        assert (ctx["id"], ctx["x"], ctx["value"]) == ("b", 1, 2)

    def test_context_value_zero_kept(self):
        assert self.widget().get_context("n", 0)["value"] == 0

    def test_media_declares_select2_assets(self):
        media = str(Selection_image_article().media)
        assert "select2.min.css" in media
        assert "select2.min.js" in media
        assert "django_select2.js" in media


@pytest.mark.django_db
class TestSelectionImageArticleRender:
    def widget(self):
        w = Selection_image_article(attrs={"id": "id_image"})
        w.choices = [(1, "Un", "a.png"), (2, "Deux", None)]
        return w

    def test_render_options_and_selected(self):
        html = self.widget().render("image", 2)
        assert isinstance(html, SafeString)
        assert 'name="image"' in html
        assert 'id="id_image"' in html
        assert '<option value="1" data-image="a.png" >Un</option>' in html
        assert '<option value="2" data-image="None" selected>Deux</option>' in html
        assert "select2" in html

    def test_render_no_value_nothing_selected(self):
        html = self.widget().render("image", None)
        assert "selected" not in html

    def test_render_with_extra_attrs(self):
        html = self.widget().render("image", 1, attrs={"id": "other"})
        assert 'id="other"' in html
