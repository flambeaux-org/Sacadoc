"""Tests for portail/utils/utils_impression.add_watermark (real, tiny PDFs; no network)."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from portail.utils.utils_impression import add_watermark
from pypdf import PdfReader, PdfWriter


def _pdf(path, pages=1, size=(300, 400)):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=size[0], height=size[1])
    with open(path, "wb") as f:
        writer.write(f)


def _text_of(page):
    return page.extract_text() or ""


def test_watermark_added_to_single_page(tmp_path):
    path = tmp_path / "doc.pdf"
    _pdf(path)
    add_watermark(SimpleNamespace(path=str(path)), "BROUILLON")
    reader = PdfReader(str(path))
    assert len(reader.pages) == 1
    assert "BROUILLON" in _text_of(reader.pages[0])


def test_watermark_added_to_every_page(tmp_path):
    path = tmp_path / "doc.pdf"
    _pdf(path, pages=3)
    add_watermark(SimpleNamespace(path=str(path)), "COPIE")
    reader = PdfReader(str(path))
    assert len(reader.pages) == 3
    assert all("COPIE" in _text_of(p) for p in reader.pages)


def test_page_size_is_preserved(tmp_path):
    path = tmp_path / "doc.pdf"
    _pdf(path, size=(595, 842))
    add_watermark(SimpleNamespace(path=str(path)), "X")
    page = PdfReader(str(path)).pages[0]
    assert (float(page.mediabox.width), float(page.mediabox.height)) == (595.0, 842.0)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        add_watermark(SimpleNamespace(path=str(tmp_path / "nope.pdf")), "X")


def test_pdf_without_pages_raises(tmp_path):
    path = tmp_path / "empty.pdf"
    buf = BytesIO()
    PdfWriter().write(buf)
    path.write_bytes(buf.getvalue())
    with pytest.raises((IndexError, KeyError, ValueError)):
        add_watermark(SimpleNamespace(path=str(path)), "X")
