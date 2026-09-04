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

import pytest

from rag_pedago.imports.pii_review_projection import (
    CONTEXT_CHARS,
    finding_context,
    finding_identity,
)

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

    def test_the_page_policy_too_is_sealed(self) -> None:
        """Le foyer de pages décide quelles pages sont scannées et citées.

        Le changer déplacerait les pages sous les décisions déjà rendues."""
        import json
        from pathlib import Path

        import nexus_pdf_page_policy as page_policy

        root = Path(__file__).resolve().parents[3]
        sealed = json.loads(
            (
                root / "governance/pii-review-decisions/pii-review-2026-09-03-final.json"
            ).read_text(encoding="utf-8")
        )
        assert page_policy.policy_source_sha256() == sealed["page_policy_sha256"]
        assert page_policy.POLICY_ID == sealed["page_policy_id"]

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



class TestFindingContext:
    """Le contexte d'un finding est celui que le REVIEWER a vu (ADR-0047).

    Le paquet de revue fige `context_sha256` sur une fenêtre de 240 caractères
    de texte de page BRUT. Le scanner, lui, expose un contexte de confort de
    50 caractères, sauts de ligne remplacés. Les deux sont légitimes ; les
    confondre fait diverger l'empreinte, et le producteur refuse alors une
    décision parfaitement valide — ce qui s'est produit.
    """

    PAGE = "".join(f"ligne {i}\n" for i in range(200))

    def test_window_is_the_reviewed_one(self) -> None:
        assert CONTEXT_CHARS == 240
        offset, length = 500, 10
        context = finding_context(self.PAGE, char_offset=offset, match_length=length)
        assert context == self.PAGE[offset - 240 : offset + length + 240]

    def test_newlines_are_preserved(self) -> None:
        """Le paquet fige le texte tel quel : normaliser changerait l'empreinte."""
        assert "\n" in finding_context(self.PAGE, char_offset=500, match_length=10)

    def test_window_is_clamped_at_both_ends(self) -> None:
        assert finding_context(self.PAGE, char_offset=0, match_length=5) == self.PAGE[:245]
        tail = finding_context(self.PAGE, char_offset=len(self.PAGE) - 5, match_length=5)
        assert tail == self.PAGE[len(self.PAGE) - 245 :]

    def test_it_reproduces_a_real_sealed_context_digest(self) -> None:
        """La preuve qui compte : un contexte réellement scellé, reproduit.

        On relit le paquet de revue local du contenu que le producteur a
        refusé, et l'on vérifie que la fenêtre partagée redonne exactement
        l'empreinte que la décision humaine porte."""
        import json
        from hashlib import sha256
        from pathlib import Path

        bundles = Path("/home/alaeddine/nexus-pii-review-final-candidate")
        if not bundles.is_dir():
            pytest.skip("paquets de revue absents de cette machine")
        checked = 0
        for bundle in sorted(bundles.iterdir()):
            manifest = bundle / "manifest.json"
            if not manifest.is_file():
                continue
            document = json.loads(manifest.read_text(encoding="utf-8"))
            for signal in document["signals"]:
                page = bundle / "pages" / f"page-{signal['page_number']:04d}.txt"
                if not page.is_file():
                    continue
                context = finding_context(
                    page.read_text(encoding="utf-8"),
                    char_offset=signal["char_offset"],
                    match_length=signal["match_length"],
                )
                assert sha256(context.encode("utf-8")).hexdigest() == signal["context_sha256"]
                checked += 1
        assert checked > 0


class TestContextWindowEdges:
    """Fige précisément la fenêtre, pour qu'aucune divergence ne revienne (§6).

    Le test réel sur les 23 paquets prouve la conformité d'aujourd'hui ; ces
    cas synthétiques disent ce que la fenêtre DOIT faire, y compris là où les
    paquets réels ne l'exercent pas."""

    def test_match_at_the_very_start_of_a_page(self) -> None:
        page = "A" * 1000
        assert finding_context(page, char_offset=0, match_length=3) == page[:243]

    def test_match_at_the_very_end_of_a_page(self) -> None:
        page = "A" * 1000
        got = finding_context(page, char_offset=997, match_length=3)
        assert got == page[757:1000]

    def test_page_shorter_than_the_window(self) -> None:
        page = "court"
        assert finding_context(page, char_offset=1, match_length=2) == page

    def test_two_matches_on_one_page_have_distinct_windows(self) -> None:
        page = "".join(f"{i:04d}-" for i in range(400))
        first = finding_context(page, char_offset=100, match_length=4)
        second = finding_context(page, char_offset=1200, match_length=4)
        assert first != second

    def test_newlines_and_whitespace_are_not_normalised(self) -> None:
        page = "debut\n\n   espaces\ttabulation\r\nfin " + "x" * 500
        got = finding_context(page, char_offset=10, match_length=3)
        assert got == page[: 10 + 3 + 240]
        assert "\n\n" in got and "\t" in got and "\r" in got

    def test_the_window_counts_characters_not_bytes(self) -> None:
        """Unicode : une fenêtre en octets couperait un caractère en deux."""
        page = "é" * 1000
        got = finding_context(page, char_offset=500, match_length=2)
        assert len(got) == 482
        assert got == page[260:742]
        assert "\ufffd" not in got

    def test_identical_repeated_text_still_yields_position_specific_windows(self) -> None:
        """Même matière, deux endroits : l'empreinte de contexte doit différer
        dès que le voisinage diffère, et coïncider quand il est identique."""
        page = ("bloc" * 100) + "UNIQUE" + ("bloc" * 100)
        near_unique = finding_context(page, char_offset=398, match_length=4)
        far_from_it = finding_context(page, char_offset=10, match_length=4)
        assert "UNIQUE" in near_unique
        assert "UNIQUE" not in far_from_it
