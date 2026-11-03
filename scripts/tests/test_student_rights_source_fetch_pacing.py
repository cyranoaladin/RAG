"""La campagne de source respecte un débit, et s'arrête au lieu de marteler.

ADR-0004 et le verrou `network_allowed` exigent « rate limiting et user-agent
identifiable ». L'user-agent l'était ; le débit, non. Une campagne réelle a
émis 392 GET en environ quarante-cinq secondes et a déclenché un blocage
Cloudflare sur la source officielle, arrêtant le rescellement d'actualité.

Trois propriétés sont éprouvées ici : l'intervalle minimum entre deux GET, le
respect de `Retry-After`, et le disjoncteur qui refuse de poursuivre après une
série de refus de débit. Le dernier compte le plus : sans lui, un outil
fail-closed produit quand même des centaines d'appels inutiles avant de
constater qu'il est bloqué.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))

import student_rights_source_check as checker  # noqa: E402
from student_rights_source_check import HTTPResponse, SourceCheckFailure  # noqa: E402

URL = "https://eduscol.education.gouv.fr/sites/default/files/document/a.pdf"


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    checker.reset_fetch_pacing()
    yield
    checker.reset_fetch_pacing()


def test_un_intervalle_minimum_separe_deux_get(monkeypatch):
    """Deux GET consécutifs ne partent pas dans la même milliseconde."""
    horloge = {"t": 0.0}
    dormi: list[float] = []
    monkeypatch.setattr(checker.time, "monotonic", lambda: horloge["t"])
    monkeypatch.setattr(checker.time, "sleep", lambda s: (dormi.append(s), horloge.__setitem__("t", horloge["t"] + s)))
    monkeypatch.setattr(checker, "FETCH_MIN_INTERVAL_SECONDS", 0.5)
    monkeypatch.setattr(checker, "_open_url", lambda url, max_bytes: HTTPResponse(200, {}, b"%PDF-1.4\n"))

    checker._fetch_urllib(URL, 1024)
    checker._fetch_urllib(URL, 1024)

    assert dormi, "aucune attente entre deux GET : le débit n'est pas respecté"
    assert dormi[0] == pytest.approx(0.5)


def test_retry_after_est_respecte(monkeypatch):
    """Un 429 avec Retry-After fait attendre la durée demandée."""
    horloge = {"t": 0.0}
    dormi: list[float] = []
    monkeypatch.setattr(checker.time, "monotonic", lambda: horloge["t"])
    monkeypatch.setattr(checker.time, "sleep", lambda s: (dormi.append(s), horloge.__setitem__("t", horloge["t"] + s)))
    monkeypatch.setattr(checker, "FETCH_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(checker, "_open_url", lambda url, max_bytes: HTTPResponse(429, {"Retry-After": "3"}, b""))

    with pytest.raises(SourceCheckFailure) as exc:
        for _ in range(checker.FETCH_RATE_LIMIT_STREAK_LIMIT):
            checker._fetch_urllib(URL, 1024)

    assert exc.value.reason_code == "SOURCE_RATE_LIMITED"
    assert 3.0 in dormi, "Retry-After n'a pas été respecté"


def test_le_disjoncteur_arrete_la_campagne(monkeypatch):
    """Après une série de 403, la campagne refuse de continuer."""
    monkeypatch.setattr(checker.time, "sleep", lambda s: None)
    monkeypatch.setattr(checker, "FETCH_MIN_INTERVAL_SECONDS", 0.0)
    appels = {"n": 0}

    def _bloque(url, max_bytes):
        appels["n"] += 1
        return HTTPResponse(403, {}, b"")

    monkeypatch.setattr(checker, "_open_url", _bloque)

    with pytest.raises(SourceCheckFailure) as exc:
        for _ in range(500):
            checker._fetch_urllib(URL, 1024)

    assert exc.value.reason_code == "SOURCE_RATE_LIMITED"
    assert appels["n"] == checker.FETCH_RATE_LIMIT_STREAK_LIMIT, (
        f"{appels['n']} GET émis avant l'arrêt : le disjoncteur doit couper à "
        f"{checker.FETCH_RATE_LIMIT_STREAK_LIMIT}, pas marteler la source"
    )


def test_un_succes_remet_le_disjoncteur_a_zero(monkeypatch):
    """Un refus isolé ne doit pas condamner une campagne par ailleurs saine."""
    monkeypatch.setattr(checker.time, "sleep", lambda s: None)
    monkeypatch.setattr(checker, "FETCH_MIN_INTERVAL_SECONDS", 0.0)
    suite = [403, 200, 403, 200, 403, 200, 403, 200, 403, 200]
    etat = {"i": 0}

    def _alterne(url, max_bytes):
        code = suite[etat["i"] % len(suite)]
        etat["i"] += 1
        return HTTPResponse(code, {}, b"" if code != 200 else b"%PDF-1.4\n")

    monkeypatch.setattr(checker, "_open_url", _alterne)

    for _ in range(len(suite)):
        checker._fetch_urllib(URL, 1024)  # ne doit pas lever


def test_user_agent_identifiable_conserve(monkeypatch):
    """L'user-agent identifiable d'ADR-0004 ne régresse pas."""
    vus: dict[str, str] = {}

    def _capture(url, max_bytes, headers=None):
        vus.update(headers or {})
        return HTTPResponse(200, {}, b"%PDF-1.4\n")

    monkeypatch.setattr(checker, "FETCH_MIN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(checker, "_open_url", lambda u, m: _capture(u, m, checker._FETCH_HEADERS))
    checker._fetch_urllib(URL, 1024)
    assert vus.get("User-Agent", "").startswith("NexusSourceIdentityVerifier/")
