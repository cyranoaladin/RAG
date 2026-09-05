import io
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src/ingestor"))
import mm_adapter


def test_oversize_dimensions_rejected_before_ocr(monkeypatch):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (20, 20)).save(buf, format="PNG")
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "pytesseract",
        types.SimpleNamespace(image_to_string=lambda *a, **k: calls.append(1) or "text"),
    )
    monkeypatch.setenv("MM_MAX_IMAGE_PIXELS", "100")
    with pytest.raises(ValueError, match="Image"):
        mm_adapter._decode_to_text(buf.getvalue(), "image/png")
    assert not calls


def test_malformed_image_does_not_become_text(monkeypatch):
    monkeypatch.setitem(
        sys.modules, "pytesseract", types.SimpleNamespace(image_to_string=lambda *a, **k: "text")
    )
    with pytest.raises(ValueError, match="Image"):
        mm_adapter._decode_to_text(b"not an image", "image/png")
