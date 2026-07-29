"""Extraction canonique du contenu PRINCIPAL d'une page HTML.

Module PARTAGE entre le source_validator (digest du verdict signe) et
l'EduscolAgent (controle de derive vs la preuve versionnee) : les deux
DOIVENT produire exactement le meme texte pour que les comparaisons de
content_sha256 soient significatives (revue PR #74, round 11).
"""
from __future__ import annotations

import re

_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(
    r"(?is)<(script|style|noscript)[^>]*>.*?</\1>")
_TAG_ANY_RE = re.compile(r"<[^>]+>")


def strip_html(html: str) -> str:
    """Extraction du contenu PRINCIPAL : le chrome de page (nav, header,
    footer, aside, formulaires) est exclu AVANT le comptage de substance,
    la relue pedagogique et tout digest de preuve."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:  # repli regex minimal si bs4 absent
        text = _TAG_RE.sub(" ", html)
        text = _TAG_ANY_RE.sub(" ", text)
        return _WS_RE.sub(" ", text).strip()
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside",
                     "form", "noscript"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    return _WS_RE.sub(" ", main.get_text(" ", strip=True))
