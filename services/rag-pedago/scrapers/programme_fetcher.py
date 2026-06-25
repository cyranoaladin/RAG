"""Governed fetcher for official programme PDFs.

Downloads programme PDFs from the registre, stores with checksum.
Respects data_staging_allowed verrou.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from scrapers.fetch import is_allowed_by_robots, is_whitelisted

ROOT = Path(__file__).resolve().parents[1]
REGISTRE_PATH = ROOT / "data" / "programmes" / "registre_programmes.yml"
STAGING_DIR = ROOT / "data" / "staging" / "programmes"
CONTRACT_PATH = ROOT / "configs" / "pedago_interface_contract.yml"


def _check_staging_allowed() -> bool:
    if not CONTRACT_PATH.is_file():
        return False
    config = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    return config.get("data_staging_allowed") is True


def load_registre() -> list[dict[str, str]]:
    data = yaml.safe_load(REGISTRE_PATH.read_text(encoding="utf-8"))
    return data.get("programmes", [])


def fetch_programmes(max_count: int | None = None) -> dict[str, Any]:
    """Download recoverable programmes from the registre."""
    if not _check_staging_allowed():
        return {"error": "data_staging_allowed is false", "results": []}

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    entries = load_registre()
    results: list[dict[str, Any]] = []
    fetched = 0

    for entry in entries:
        if entry.get("statut_recuperation") != "recuperable":
            results.append({
                "matiere": entry["matiere"],
                "niveau": entry["niveau"],
                "status": "skipped",
                "reason": entry.get("statut_recuperation", "unknown"),
            })
            continue

        url = entry.get("url_pdf", "")
        if not url:
            results.append({
                "matiere": entry["matiere"],
                "niveau": entry["niveau"],
                "status": "skipped",
                "reason": "no_url",
            })
            continue

        if max_count and fetched >= max_count:
            break

        matiere = entry["matiere"]
        niveau = entry["niveau"]
        print(f"Fetching {matiere}/{niveau}...")

        # Governance checks
        if not is_whitelisted(url):
            results.append({"matiere": matiere, "niveau": niveau,
                            "status": "refused", "reason": "not whitelisted", "url": url})
            continue
        if not is_allowed_by_robots(url):
            results.append({"matiere": matiere, "niveau": niveau,
                            "status": "refused", "reason": "robots.txt", "url": url})
            continue

        # Binary download (PDFs can't go through text-mode governed_fetch)
        import requests as _req

        from scrapers.fetch import REQUEST_TIMEOUT, USER_AGENT
        try:
            resp = _req.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        except Exception as e:
            results.append({"matiere": matiere, "niveau": niveau,
                            "status": "error", "error": str(e), "url": url})
            continue

        if resp.status_code != 200:
            results.append({"matiere": matiere, "niveau": niveau,
                            "status": "http_error", "status_code": resp.status_code, "url": url})
            continue

        content = resp.content  # raw bytes
        sha256 = hashlib.sha256(content).hexdigest()
        filename = f"{matiere}_{niveau}_{entry.get('statut', 'unknown')}.pdf"
        pdf_path = STAGING_DIR / filename
        pdf_path.write_bytes(content)

        # Save metadata
        meta = {
            "matiere": matiere,
            "niveau": niveau,
            "voie": entry.get("voie", ""),
            "statut": entry.get("statut", ""),
            "boen_reference": entry.get("boen_reference", ""),
            "url_pdf": url,
            "sha256": sha256,
            "size_bytes": len(content),
            "content_type": resp.headers.get("Content-Type", ""),
        }
        meta_path = STAGING_DIR / f"{filename}.meta.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        results.append({
            "matiere": matiere, "niveau": niveau,
            "status": "ok", "sha256": sha256,
            "size_bytes": len(content), "filename": filename,
        })
        fetched += 1
        print(f"  OK: {len(content)} bytes, sha256={sha256[:16]}...")

    return {
        "fetched": fetched,
        "total": len(entries),
        "results": results,
    }


if __name__ == "__main__":
    report = fetch_programmes()
    print(yaml.safe_dump(report, allow_unicode=True, sort_keys=False))
