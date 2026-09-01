#!/usr/bin/env python3
"""Prépare les paquets de revue PII, hors dépôt, figés par empreinte (ADR-0047 § 2).

Un reviewer humain statue sur ce que le scanner a trouvé, pas sur un résumé. Le
paquet d'un contenu est donc généré depuis les octets exacts du PDF (rehachés),
sous la politique, le scanner, le foyer de pages et le runtime nommés dans son
manifeste. Il porte chaque correspondance avec sa page, sa longueur, son
contexte et le texte brut, le texte complet des pages concernées, et le PDF
entier — matière brute, donc HORS Git. Son empreinte est celle de son
`manifest.json`, qui épingle chaque fichier : toute modification après décision
l'invalide (`--verifier`).

Le dépôt ne garde que l'INDEX (`NEXUS-PII-REVIEW-INDEX-V1`) : empreintes,
classes, comptes, pages, titres, placements — jamais la matière.

    python scripts/preparer_paquets_revue_pii.py \\
        --pdf-root ~/nexus-pdf-mirror-20260902 \\
        --content-set docs/reports/evidence-index/production_content_set_320_20260902.txt \\
        --placements docs/reports/evidence-index/pii_review_placements_20260902.json \\
        --output-root ~/nexus-pii-review-20260902 \\
        --index docs/reports/evidence-index/pii_review_index_20260902.json \\
        --campaign-id pii-review-2026-09-02-lot-1-2

    python scripts/preparer_paquets_revue_pii.py --verifier \\
        --output-root ~/nexus-pii-review-20260902 \\
        --index docs/reports/evidence-index/pii_review_index_20260902.json
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

BUNDLE_PROTOCOL = "NEXUS-PII-REVIEW-BUNDLE-V1"
INDEX_PROTOCOL = "NEXUS-PII-REVIEW-INDEX-V1"
CONTEXT_CHARS = 240


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def canonical_json_bytes(document: object) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(SERVICE_ROOT.parents[1]).as_posix()
    except ValueError:
        return path.name


def _instruments(policy_path: Path) -> dict[str, object]:
    return {
        "policy_path": _repo_relative(policy_path),
        "policy_sha256": _sha256_file(policy_path),
        "scanner_path": _repo_relative(Path(pii_scanner.__file__)),
        "scanner_sha256": _sha256_file(Path(pii_scanner.__file__)),
        "page_policy_id": page_policy.POLICY_ID,
        "page_policy_sha256": page_policy.policy_source_sha256(),
        "runtime": {"python": sys.version.split()[0], "pypdf": pypdf.__version__},
    }


def _bundle_for(
    *,
    sha: str,
    content: bytes,
    result: pii_scanner.PIIScanResult,
    pages_text: list[str],
    facts: dict[str, object],
    instruments: dict[str, object],
    bundle_dir: Path,
    campaign_id: str,
) -> dict[str, object]:
    bundle_dir.mkdir(parents=True, exist_ok=False)
    (bundle_dir / "pages").mkdir()
    files: dict[str, str] = {}
    (bundle_dir / "document.pdf").write_bytes(content)
    files["document.pdf"] = sha
    concerned = sorted({m.page_number for m in result.matches if m.page_number is not None})
    for page in concerned:
        name = f"pages/page-{page:04d}.txt"
        text = pages_text[page - 1]
        (bundle_dir / name).write_text(text, encoding="utf-8")
        files[name] = _sha256_bytes(text.encode("utf-8"))
    signals = []
    for match in sorted(result.matches, key=lambda m: (m.page_number or 0, m.char_offset, m.pattern_id)):
        page_text = pages_text[(match.page_number or 1) - 1]
        start = max(0, match.char_offset - CONTEXT_CHARS)
        end = min(len(page_text), match.char_offset + len(match.match_text) + CONTEXT_CHARS)
        signals.append(
            {
                "pattern_id": match.pattern_id,
                "description": match.description,
                "page_number": match.page_number,
                "char_offset": match.char_offset,
                "match_length": len(match.match_text),
                "match_text": match.match_text,
                "context": page_text[start:end],
            }
        )
    manifest: dict[str, object] = {
        "protocol_version": BUNDLE_PROTOCOL,
        "campaign_id": campaign_id,
        "content_sha256": sha,
        "title": facts.get("title"),
        "source_path": facts.get("source_path"),
        "placements": sorted(facts.get("placements", [])),  # type: ignore[arg-type]
        **instruments,
        "page_count": len(pages_text),
        "pages_scanned": result.pages_scanned,
        "ignored_empty_pages": list(result.ignored_empty_pages),
        "characters_scanned": result.characters_scanned,
        "signal_count": len(result.matches),
        "signal_classes": sorted({m.pattern_id for m in result.matches}),
        "pages": concerned,
        "signals": signals,
        "files": dict(sorted(files.items())),
        "raw_pii_in_bundle": True,
        "instructions": (
            "Ce paquet porte de la matière brute : il ne doit jamais entrer dans le dépôt. "
            "Statuez sur chaque correspondance en lisant la page entière, et le PDF si le "
            "contexte ne suffit pas. Toute modification de ce paquet après décision "
            "invalide la décision (empreinte du manifeste)."
        ),
    }
    (bundle_dir / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    return manifest


def preparer(
    *,
    pdf_root: Path,
    content_sha256: Sequence[str],
    placements_path: Path,
    policy_path: Path,
    output_root: Path,
    index_path: Path,
    campaign_id: str,
) -> dict[str, object]:
    """Génère un paquet par contenu DÉTECTÉ et l'index versionnable."""
    facts_by_sha: dict[str, dict[str, object]] = json.loads(placements_path.read_text(encoding="utf-8"))
    instruments = _instruments(policy_path)
    patterns = pii_scanner.load_patterns_from_config(policy_path)
    output_root.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    scanned = 0
    for sha in sorted(set(content_sha256)):
        path = pdf_root / f"{sha}.pdf"
        if not path.is_file():
            raise FileNotFoundError(f"mirror file missing for {sha}")
        content = path.read_bytes()
        if _sha256_bytes(content) != sha:
            raise ValueError(f"mirror file {path.name} does not match its content SHA-256")
        result = pii_scanner.scan_pdf_bytes(content, source_path=path.name, patterns=patterns)
        scanned += 1
        if result.extraction_error:
            raise ValueError(f"content {sha} could not be scanned: {result.extraction_error}")
        if not result.pii_detected:
            continue
        pages_text, _ignored, error = pii_scanner.extract_pdf_pages_with_structural_empty_pages(content)
        if error:
            raise ValueError(f"content {sha} could not be paginated: {error}")
        facts = facts_by_sha.get(sha)
        if facts is None:
            raise ValueError(f"no placement facts declared for detected content {sha}")
        bundle_dir = output_root / sha
        if bundle_dir.exists():
            raise FileExistsError(f"bundle already exists: {bundle_dir}")
        manifest = _bundle_for(
            sha=sha, content=content, result=result, pages_text=pages_text, facts=facts,
            instruments=instruments, bundle_dir=bundle_dir, campaign_id=campaign_id,
        )
        entries.append(
            {
                "content_sha256": sha,
                "bundle_dir": sha,
                "bundle_sha256": _sha256_file(bundle_dir / "manifest.json"),
                "title": manifest["title"],
                "source_path": manifest["source_path"],
                "placements": manifest["placements"],
                "signal_count": manifest["signal_count"],
                "signal_classes": manifest["signal_classes"],
                "pages": manifest["pages"],
                "page_count": manifest["page_count"],
                "files": manifest["files"],
            }
        )
    index: dict[str, object] = {
        "protocol_version": INDEX_PROTOCOL,
        "campaign_id": campaign_id,
        "generated_at": datetime.now(UTC).isoformat(),
        **instruments,
        "content_set_sha256": _sha256_bytes(("\n".join(sorted(set(content_sha256))) + "\n").encode()),
        "counts": {"scanned": scanned, "bundles": len(entries)},
        "raw_pii_in_output": False,
        # L'index ne peut pas porter sa propre empreinte ; c'est l'ensemble de
        # décisions qui l'épingle (`review_index_sha256`).
        "index_sha256_excluded": True,
        "bundles": entries,
    }
    index_path.write_bytes(canonical_json_bytes(index))
    return index


def verifier(*, output_root: Path, index_path: Path) -> list[str]:
    """Rehache chaque paquet contre l'index ; rend la liste des écarts (vide = intact)."""
    index = json.loads(index_path.read_text(encoding="utf-8"))
    problemes: list[str] = []
    for entry in index["bundles"]:
        bundle_dir = output_root / entry["bundle_dir"]
        manifest_path = bundle_dir / "manifest.json"
        if not manifest_path.is_file():
            problemes.append(f"{entry['content_sha256']}: manifest.json missing")
            continue
        if _sha256_file(manifest_path) != entry["bundle_sha256"]:
            problemes.append(f"{entry['content_sha256']}: manifest.json digest differs from the index")
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for name, digest in manifest["files"].items():
            file_path = bundle_dir / name
            if not file_path.is_file():
                problemes.append(f"{entry['content_sha256']}: {name} missing")
            elif _sha256_file(file_path) != digest:
                problemes.append(f"{entry['content_sha256']}: {name} digest differs from the manifest")
    return problemes


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--verifier", action="store_true")
    parser.add_argument("--pdf-root", type=Path)
    parser.add_argument("--content-set", type=Path)
    parser.add_argument("--placements", type=Path)
    parser.add_argument("--policy", type=Path, default=SERVICE_ROOT / "configs/pii_gate_policy.yml")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--campaign-id")
    args = parser.parse_args(argv)
    if args.verifier:
        problemes = verifier(output_root=args.output_root, index_path=args.index)
        print(json.dumps({"intact": not problemes, "ecarts": problemes}, ensure_ascii=False, indent=2))
        return 0 if not problemes else 1
    if not (args.pdf_root and args.content_set and args.placements and args.campaign_id):
        parser.error("--pdf-root, --content-set, --placements et --campaign-id sont requis")
    shas = [line.strip() for line in args.content_set.read_text().splitlines() if line.strip()]
    index = preparer(
        pdf_root=args.pdf_root, content_sha256=shas, placements_path=args.placements,
        policy_path=args.policy, output_root=args.output_root, index_path=args.index,
        campaign_id=args.campaign_id,
    )
    print(json.dumps({"index": str(args.index), "index_sha256": _sha256_file(args.index), "counts": index["counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
