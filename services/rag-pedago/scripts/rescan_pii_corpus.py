#!/usr/bin/env python3
"""Rescan PII d'un ensemble de contenus — une MESURE datée, jamais une correction.

Pourquoi ce script existe. Une politique nouvelle qui rend un verdict différent
d'une politique ancienne est une nouvelle mesure, pas une correction rétroactive
de l'ancienne (décision de gouvernance du 2026-09-02, §9). Cette mesure doit
donc être un artefact à part entière, qui NOMME ce qui l'a rendue : la politique,
le scanner, le foyer de pages (ADR-0046), le runtime pypdf, l'ensemble exact de
contenus mesurés. Elle ne transporte aucune correspondance brute : classes,
comptes et pages seulement (`result_to_dict_sanitized`).

    python scripts/rescan_pii_corpus.py \\
        --pdf-root ~/nexus-pdf-mirror-20260902 \\
        --content-set docs/reports/evidence-index/<set>.txt \\
        --policy configs/pii_gate_policy.yml \\
        --sortie docs/reports/evidence-index/pii_rescan_policy_v5_<date>.json

`--content-set` : un SHA-256 par ligne. Le miroir est adressé par contenu
(`<pdf-root>/<sha256>.pdf`) et chaque fichier est rehaché avant d'être mesuré.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

import nexus_pdf_page_policy as page_policy  # noqa: E402
import pypdf  # noqa: E402

from rag_pedago.imports import pii_scanner  # noqa: E402

PROTOCOL_VERSION = "NEXUS-PII-RESCAN-V1"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _content_set_sha256(values: Sequence[str]) -> str:
    return _sha256_bytes(("\n".join(sorted(set(values))) + "\n").encode("utf-8"))


def canonical_json_bytes(document: object) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def rescan(
    *,
    pdf_root: Path,
    content_sha256: Sequence[str],
    policy_path: Path,
    measured_at: str | None = None,
) -> dict[str, object]:
    """Mesure chaque contenu demandé et rend le document sanitisé complet.

    Refuse un fichier absent ou dont les octets ne portent pas l'empreinte de
    son nom : une mesure sur d'autres octets ne dirait rien de ce contenu.
    """
    demandes = sorted(set(content_sha256))
    if not demandes:
        raise ValueError("content set must not be empty")
    patterns = pii_scanner.load_patterns_from_config(policy_path)
    results: list[dict[str, object]] = []
    detected = clear = failed = 0
    for sha in demandes:
        path = pdf_root / f"{sha}.pdf"
        if not path.is_file():
            raise FileNotFoundError(f"mirror file missing for {sha}")
        content = path.read_bytes()
        if _sha256_bytes(content) != sha:
            raise ValueError(f"mirror file {path.name} does not match its content SHA-256")
        result = pii_scanner.scan_pdf_bytes(content, source_path=path.name, patterns=patterns)
        sanitized = pii_scanner.result_to_dict_sanitized(result)
        pages_per_class: dict[str, list[int]] = {}
        for match in result.matches:
            pages = pages_per_class.setdefault(match.pattern_id, [])
            if match.page_number is not None and match.page_number not in pages:
                pages.append(match.page_number)
        row: dict[str, object] = {
            "content_sha256": sha,
            "pii_detected": result.pii_detected,
            "extraction_error_code": sanitized["extraction_error_code"],
            "pages_scanned": result.pages_scanned,
            "characters_scanned": result.characters_scanned,
            "ignored_empty_pages": list(result.ignored_empty_pages),
            "signal_count": len(result.matches),
            "signal_classes": sorted({m.pattern_id for m in result.matches}),
            "pages_per_class": {k: sorted(v) for k, v in sorted(pages_per_class.items())},
        }
        if result.extraction_error:
            failed += 1
        elif result.pii_detected:
            detected += 1
        else:
            clear += 1
        results.append(row)
    return {
        "protocol_version": PROTOCOL_VERSION,
        "measured_at": measured_at or datetime.now(UTC).isoformat(),
        "policy_path": _repo_relative(policy_path),
        "policy_sha256": _sha256_bytes(policy_path.read_bytes()),
        "scanner_path": _repo_relative(Path(pii_scanner.__file__)),
        "scanner_sha256": _sha256_bytes(Path(pii_scanner.__file__).read_bytes()),
        "page_policy_id": page_policy.POLICY_ID,
        "page_policy_sha256": page_policy.policy_source_sha256(),
        "runtime": {"python": sys.version.split()[0], "pypdf": pypdf.__version__},
        "content_set_sha256": _content_set_sha256(demandes),
        "counts": {
            "scanned": len(demandes),
            "detected": detected,
            "clear": clear,
            "extraction_failed": failed,
        },
        "raw_pii_in_output": False,
        "results": results,
    }


def _repo_relative(path: Path) -> str:
    repository_root = SERVICE_ROOT.parents[1]
    try:
        return path.resolve().relative_to(repository_root).as_posix()
    except ValueError:
        return path.name


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pdf-root", type=Path, required=True)
    parser.add_argument("--content-set", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=SERVICE_ROOT / "configs/pii_gate_policy.yml")
    parser.add_argument("--sortie", type=Path, required=True)
    args = parser.parse_args(argv)
    shas = [line.strip() for line in args.content_set.read_text().splitlines() if line.strip()]
    document = rescan(pdf_root=args.pdf_root, content_sha256=shas, policy_path=args.policy)
    args.sortie.write_bytes(canonical_json_bytes(document))
    print(json.dumps({"sortie": str(args.sortie), "sha256": _sha256_bytes(args.sortie.read_bytes()), "counts": document["counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
