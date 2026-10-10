"""Capture navigateur datée des pages-listes Éduscol de l'inventaire #300.

Les HTML, textes et captures d'écran restent des preuves internes. Ce script ne
publie aucun PDF et ne tire aucune conclusion juridique d'un HTTP 403.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import secrets
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

from student_rights_source_provenance import _official_url, build_listing_capture_receipt


def _atomic_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f"{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def listing_urls(artifacts: list[dict], extra_listing_urls: list[str]) -> list[str]:
    """Ajoute des pages officielles découvertes sans réécrire l'inventaire."""
    base = {row["source_listing_url"] for row in artifacts
            if not urllib.parse.urlsplit(row["source_listing_url"]).path.lower().endswith(".pdf")}
    if not all(_official_url(url) for url in base):
        raise ValueError("SOURCE_LISTING_URL_SET_INVALID")
    if len(extra_listing_urls) != len(set(extra_listing_urls)):
        raise ValueError("SOURCE_EXTRA_LISTING_DUPLICATE")
    for url in extra_listing_urls:
        if (not _official_url(url)
                or urllib.parse.urlsplit(url).path.lower().endswith(".pdf")
                or url in base):
            raise ValueError("SOURCE_EXTRA_LISTING_INVALID")
    return sorted(base | set(extra_listing_urls))


def capture_listings(
    packet_path: Path, output_dir: Path, *, extra_listing_urls: list[str] | None = None,
) -> dict:
    packet = json.loads(packet_path.read_bytes())
    artifacts = packet.get("artifacts")
    if not isinstance(artifacts, list) or len(artifacts) != 315:
        raise ValueError("SOURCE_PACKET_COUNT_INVALID")
    urls = listing_urls(artifacts, extra_listing_urls or [])
    if len(urls) != 14 + len(extra_listing_urls or []):
        raise ValueError("SOURCE_LISTING_URL_SET_INVALID")
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    code_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    summary: list[dict] = []
    with sync_playwright() as playwright:
        for url in urls:
            # Éduscol limite parfois plusieurs requêtes dans un seul contexte.
            # Un navigateur neuf par URL préserve le résultat de chaque capture.
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    locale="fr-FR", timezone_id="Europe/Paris",
                    viewport={"width": 1440, "height": 1000},
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                    ),
                )
                page = context.new_page()
                response = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                page.locator("body").wait_for(state="visible", timeout=15_000)
                final_url = page.url
                if not _official_url(final_url):
                    raise ValueError("LISTING_FINAL_URL_NOT_OFFICIAL")
                status = response.status if response is not None else 0
                html = (page.content().replace("\r\n", "\n").replace("\r", "\n").strip() + "\n").encode("utf-8")
                text = (page.locator("body").inner_text().replace("\r\n", "\n").replace("\r", "\n").strip() + "\n").encode("utf-8")
                shot = page.screenshot(full_page=True, animations="disabled")
                observed = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                stem = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
                html_name, text_name, shot_name = f"{stem}.normalized.html", f"{stem}.extracted.txt", f"{stem}.png"
                receipt = build_listing_capture_receipt(
                    requested_url=url, final_url=final_url, http_status=status,
                    observed_at_utc=observed, normalized_html=html, extracted_text=text,
                    screenshot=shot, browser_version=browser.version,
                    playwright_version=importlib.metadata.version("playwright"),
                    capture_script_sha256=code_sha, normalized_html_file=html_name,
                    extracted_text_file=text_name, screenshot_file=shot_name,
                )
                for name, body in ((html_name, html), (text_name, text), (shot_name, shot)):
                    _atomic_write(output_dir / name, body)
                receipt_name = f"{stem}.receipt.json"
                receipt_body = (json.dumps(receipt, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                _atomic_write(output_dir / receipt_name, receipt_body)
                summary.append({"url": url, "http_status": status, "pdf_link_count": receipt["pdf_link_count"],
                                "receipt": receipt_name, "receipt_sha256": hashlib.sha256(receipt_body).hexdigest()})
                context.close()
            except Exception:
                summary.append({"url": url, "http_status": None, "error_code": "LISTING_CAPTURE_FAILED"})
            finally:
                browser.close()
    return {"kind": "NEXUS_EDUSCOL_LISTING_CAPTURE_SUMMARY_V1", "listing_count": len(urls),
            "http_200_count": sum(row["http_status"] == 200 for row in summary), "rows": summary,
            "capture_script_sha256": code_sha}


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture navigateur des listings Éduscol")
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--extra-listing-url", action="append", default=[])
    args = parser.parse_args()
    try:
        result = capture_listings(
            args.packet, args.output_dir, extra_listing_urls=args.extra_listing_url,
        )
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({"status": "FAIL_CLOSED"}))
        return 1
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
