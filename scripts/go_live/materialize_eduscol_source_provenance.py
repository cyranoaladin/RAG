"""Matérialise 315 constats de provenance à partir des captures Éduscol V1.

La sortie est une base candidate à la revue déléguée, jamais une permission de
servir les PDF ou un verdict final de droits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from student_rights_source_check import _write_atomic_json
from student_rights_source_provenance import (
    _official_url,
    canonical_json_bytes,
    fetch_pdf_observation,
    load_listing_capture,
    materialize_provenance_records,
    verify_sitewide_authority,
)


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _old_http_diagnostics(folder: Path | None, artifacts: list[dict]) -> dict[str, int | None]:
    if folder is None:
        return {}
    result = {}
    for artifact in artifacts:
        sha = artifact["content_sha256"]
        try:
            old = json.loads((folder / f"{sha}.json").read_bytes())
            if (old.get("content_sha256") == sha
                    and old.get("source_listing_url") == artifact["source_listing_url"]):
                result[sha] = old.get("source_identity", {}).get("source_http_status")
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    return result


def run(
    *, root: Path, packet_path: Path, listings_dir: Path, authority_path: Path,
    output_dir: Path, old_checkpoints_dir: Path | None = None,
    extra_listing_urls: list[str] | None = None,
) -> dict:
    packet_path = packet_path if packet_path.is_absolute() else root / packet_path
    listings_dir = listings_dir if listings_dir.is_absolute() else root / listings_dir
    authority_path = authority_path if authority_path.is_absolute() else root / authority_path
    output_dir = output_dir if output_dir.is_absolute() else root / output_dir
    packet_bytes = packet_path.read_bytes()
    packet = json.loads(packet_bytes)
    artifacts = packet.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 315:
        raise ValueError("SOURCE_PACKET_COUNT_INVALID")
    inventory_sha = hashlib.sha256(packet_bytes).hexdigest()
    authority = verify_sitewide_authority(root, authority_path)
    if authority["status"] != "CAPTURE_VERIFIED_PENDING_FINAL_APPROVAL":
        raise ValueError("SITEWIDE_AUTHORITY_CAPTURE_INVALID")
    capture_script = root / "scripts/go_live/capture_eduscol_source_listings.py"
    captures = {}
    for receipt_path in sorted(listings_dir.glob("*.receipt.json")):
        capture = load_listing_capture(root, receipt_path, capture_script)
        url = capture["receipt"]["requested_url"]
        if url in captures:
            raise ValueError("SOURCE_LISTING_DUPLICATE_CAPTURE")
        captures[url] = capture
    expected_listings = {
        row["source_listing_url"] for row in artifacts
        if not urllib.parse.urlsplit(row["source_listing_url"]).path.lower().endswith(".pdf")
    }
    extra_listings = extra_listing_urls or []
    if (
        len(expected_listings) != 14
        or len(extra_listings) != len(set(extra_listings))
        or any(
            not _official_url(url)
            or urllib.parse.urlsplit(url).path.lower().endswith(".pdf")
            or url in expected_listings
            for url in extra_listings
        )
        or set(captures) != expected_listings | set(extra_listings)
    ):
        raise ValueError("SOURCE_LISTING_CAPTURE_SET_INVALID")
    urls = {
        row["source_listing_url"] for row in artifacts
        if urllib.parse.urlsplit(row["source_listing_url"]).path.lower().endswith(".pdf")
    }
    for capture in captures.values():
        receipt = capture["receipt"]
        if receipt["http_status"] != 200:
            continue
        urls.update(anchor["href"] for anchor in receipt["pdf_links"])
    def fetch(url: str) -> tuple[str, dict]:
        return url, fetch_pdf_observation(url, observed_at_utc=_now_utc())
    with ThreadPoolExecutor(max_workers=6) as pool:
        pdf_fetches = dict(pool.map(fetch, sorted(urls)))
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    fetch_dir = output_dir / "pdf_fetches"
    for url, observation in sorted(pdf_fetches.items()):
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        envelope = {
            "kind": "NEXUS-STUDENT-SOURCE-PDF-FETCH-RECEIPT-V1",
            "url": url,
            "source_checker_code_sha256": hashlib.sha256(
                (root / "scripts/go_live/student_rights_source_provenance.py").read_bytes()
            ).hexdigest(),
            "fetch": observation,
        }
        envelope["receipt_sha256"] = hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()
        _write_atomic_json(fetch_dir / f"{key}.json", envelope)
    checked = _now_utc()
    records = materialize_provenance_records(
        artifacts, captures=captures, pdf_fetches=pdf_fetches,
        inventory_sha256=inventory_sha,
        authority_yaml_sha256=authority["authority_yaml_sha256"],
        authority_status=authority["status"], checked_at_utc=checked,
        raw_http_status_by_sha=_old_http_diagnostics(old_checkpoints_dir, artifacts),
    )
    if len(records) != 315:
        raise ValueError("SOURCE_PROVENANCE_RECORD_COUNT_INVALID")
    checkpoint_dir = output_dir / "checkpoints"
    rows = []
    for sha, record in sorted(records.items()):
        body = canonical_json_bytes(record)
        _write_atomic_json(checkpoint_dir / f"{sha}.json", record)
        rows.append({
            "content_sha256": sha,
            "checkpoint_relpath": (checkpoint_dir / f"{sha}.json").relative_to(root).as_posix(),
            "checkpoint_file_sha256": hashlib.sha256(body).hexdigest(),
            "source_status": record["source_provenance"]["status"],
            "rights_basis_kind": record["rights_basis_kind"],
            "currentness_status": record["source_provenance"]["currentness_status"],
            "revocation_status": record["source_provenance"]["revocation_status"],
        })
    index = {
        "kind": "NEXUS-STUDENT-SOURCE-PROVENANCE-INDEX-V1",
        "checked_at_utc": checked,
        "inventory_sha256": inventory_sha,
        "authority_yaml_sha256": authority["authority_yaml_sha256"],
        "source_checker_code_sha256": hashlib.sha256(
            (root / "scripts/go_live/student_rights_source_provenance.py").read_bytes()
        ).hexdigest(),
        "capture_script_sha256": hashlib.sha256(capture_script.read_bytes()).hexdigest(),
        "listing_count": len(captures),
        "extra_listing_urls": sorted(extra_listings),
        "record_count": len(rows),
        "status_counts": dict(Counter(row["source_status"] for row in rows)),
        "rights_basis_counts": dict(Counter(row["rights_basis_kind"] for row in rows)),
        "currentness_counts": dict(Counter(row["currentness_status"] for row in rows)),
        "revocation_counts": dict(Counter(row["revocation_status"] for row in rows)),
        "pdf_fetch_count": len(pdf_fetches),
        "rows": rows,
    }
    index["index_sha256"] = hashlib.sha256(canonical_json_bytes(index)).hexdigest()
    _write_atomic_json(output_dir / "index.json", index)
    return {key: value for key, value in index.items() if key != "rows"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provenance Éduscol exacte pour les 315 PDF")
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--listings-dir", type=Path, required=True)
    parser.add_argument("--authority", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--old-checkpoints-dir", type=Path)
    parser.add_argument("--extra-listing-url", action="append", default=[])
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    try:
        result = run(
            root=root, packet_path=args.packet, listings_dir=args.listings_dir,
            authority_path=args.authority, output_dir=args.output_dir,
            old_checkpoints_dir=args.old_checkpoints_dir,
            extra_listing_urls=args.extra_listing_url,
        )
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({"status": "FAIL_CLOSED"}))
        return 1
    print(json.dumps({"status": "COMPLETE", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
