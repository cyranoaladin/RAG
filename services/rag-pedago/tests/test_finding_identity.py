"""Identité d'un finding de scan PII — partagée, donc comparable (ADR-0047).

Le préparateur de paquets et le producteur de release doivent nommer un
finding **de la même façon**, sinon comparer « l'univers des findings scannés »
à « l'univers des findings décidés » ne prouve rien : deux dérivations
différentes donneraient deux ensembles disjoints, et la comparaison échouerait
pour une raison qui n'a rien à voir avec la revue.

L'identité ne porte jamais la matière : contenu, motif, page, position, et
l'EMPREINTE de la correspondance.
"""
from __future__ import annotations

from hashlib import sha256

from rag_pedago.imports.pii_review_projection import finding_identity

CONTENT = "a" * 64
MATCH_SHA = sha256(b"0612345678").hexdigest()


def _identity(**overrides: object) -> str:
    payload: dict[str, object] = {
        "content_sha256": CONTENT,
        "pattern_id": "phone_french",
        "page_number": 3,
        "char_offset": 128,
        "match_sha256": MATCH_SHA,
    }
    payload.update(overrides)
    return finding_identity(**payload)  # type: ignore[arg-type]


class TestFindingIdentity:
    def test_is_a_sha256_hex_digest(self) -> None:
        value = _identity()
        assert len(value) == 64
        assert set(value) <= set("0123456789abcdef")

    def test_is_deterministic(self) -> None:
        assert _identity() == _identity()

    def test_never_carries_the_material(self) -> None:
        assert "0612345678" not in _identity()

    def test_every_component_changes_the_identity(self) -> None:
        """Aucune des cinq composantes n'est décorative."""
        base = _identity()
        assert _identity(content_sha256="b" * 64) != base
        assert _identity(pattern_id="email_address") != base
        assert _identity(page_number=4) != base
        assert _identity(char_offset=129) != base
        assert _identity(match_sha256=sha256(b"other").hexdigest()) != base

    def test_same_material_at_two_places_has_two_identities(self) -> None:
        assert _identity(char_offset=10) != _identity(char_offset=20)

    def test_matches_the_sealed_derivation(self) -> None:
        """La formule est celle sous laquelle les 23 paquets ont été scellés.

        Elle est reproduite ici littéralement : si quelqu'un la « simplifie »
        un jour, ce test dit que les décisions humaines déjà rendues cessent
        d'être rattachables à leur scan."""
        expected = sha256(
            f"{CONTENT}:phone_french:3:128:{MATCH_SHA}".encode()
        ).hexdigest()
        assert _identity() == expected


class TestTheScannerDigestIsSealed:
    """Le scanner est une AUTORITÉ, pas seulement du code.

    `pii_scanner.py` est scellé par son empreinte dans l'ensemble de décisions
    humaines (`scanner_sha256`). Y ajouter la moindre ligne — même une fonction
    utile, même sans changer un seul comportement — change ce digest et rend,
    par la règle d'ADR-0047 elle-même, les décisions déjà rendues caduques pour
    tous les contenus concernés.

    Ce test existe parce que le piège s'est refermé une fois : `finding_identity`
    avait été placée dans `pii_scanner.py`, où sa place semblait naturelle."""

    def test_the_scanner_still_hashes_to_what_the_decisions_were_sealed_against(
        self,
    ) -> None:
        import json
        from hashlib import sha256
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        scanner = root / "services/rag-pedago/rag_pedago/imports/pii_scanner.py"
        sealed = json.loads(
            (
                root / "governance/pii-review-decisions/pii-review-2026-09-03-final.json"
            ).read_text(encoding="utf-8")
        )["scanner_sha256"]
        assert sha256(scanner.read_bytes()).hexdigest() == sealed, (
            "pii_scanner.py a changé : les décisions humaines scellées ne "
            "décrivent plus ce scanner, et ne peuvent plus admettre aucun contenu"
        )

    def test_the_policy_too_is_sealed(self) -> None:
        import json
        from hashlib import sha256
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        policy = root / "services/rag-pedago/configs/pii_gate_policy.yml"
        sealed = json.loads(
            (
                root / "governance/pii-review-decisions/pii-review-2026-09-03-final.json"
            ).read_text(encoding="utf-8")
        )["policy_sha256"]
        assert sha256(policy.read_bytes()).hexdigest() == sealed
