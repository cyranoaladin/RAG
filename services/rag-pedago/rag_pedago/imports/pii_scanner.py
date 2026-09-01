"""PII Scanner — Full-content PII detection for corpus objects (H2-B).

Scans PDF content for personal identifiable information patterns.
Required for PII gate clearance before INGEST disposition.

Usage:
    python -m rag_pedago.imports.pii_scanner \
        --pdf /path/to/document.pdf \
        --output /path/to/pii_report.json

    # Batch mode for corpus
    python -m rag_pedago.imports.pii_scanner \
        --corpus-manifest /path/to/manifest.tsv \
        --corpus-root /tmp/corpus_download \
        --output /path/to/corpus_pii_report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import yaml

try:
    from pypdf import PdfReader
    from pypdf.generic import ContentStream
except ImportError:
    PdfReader = None  # type: ignore[misc,assignment]
    ContentStream = None  # type: ignore[misc,assignment]


@dataclass
class PIIPattern:
    """A PII detection pattern."""

    pattern_id: str
    description: str
    regex: re.Pattern[str]
    severity: str = "high"


@dataclass
class PIIMatch:
    """A single PII match found in content."""

    pattern_id: str
    description: str
    match_text: str
    page_number: int | None
    char_offset: int
    context: str  # Surrounding text for review


@dataclass
class PIIScanResult:
    """Result of PII scan for a single document."""

    file_path: str
    sha256: str
    pages_scanned: int
    characters_scanned: int
    pii_detected: bool
    ignored_empty_pages: tuple[int, ...] = ()
    matches: list[PIIMatch] = field(default_factory=list)
    extraction_error: str | None = None
    scan_duration_ms: int = 0


@dataclass
class PIIScanReport:
    """Complete PII scan report for corpus."""

    report_id: str
    generated_at: str
    policy_version: str
    total_files: int
    files_scanned: int
    files_with_errors: int
    files_with_pii: int
    files_clean: int
    pii_absent_attested: bool
    total_matches: int
    matches_by_pattern: dict[str, int] = field(default_factory=dict)
    results: list[PIIScanResult] = field(default_factory=list)


# Default PII patterns (from pii_gate_policy.yml)
DEFAULT_PII_PATTERNS = [
    PIIPattern(
        pattern_id="french_ssn",
        description="Numero de securite sociale",
        regex=re.compile(
            r"\b[12]\s?\d{2}\s?\d{2}\s?\d{2}\s?\d{3}\s?\d{3}\s?\d{2}\b"
        ),
        severity="critical",
    ),
    PIIPattern(
        pattern_id="email_address",
        description="Email addresses",
        regex=re.compile(
            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        ),
        severity="high",
    ),
    PIIPattern(
        pattern_id="phone_french",
        description="French phone numbers",
        regex=re.compile(
            r"(?:(?:\+|00)33[\s.-]?|0)[1-9](?:[\s.-]?\d{2}){4}"
        ),
        severity="high",
    ),
    PIIPattern(
        pattern_id="iban_french",
        description="French IBAN",
        regex=re.compile(
            r"FR\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{3}"
        ),
        severity="critical",
    ),
    PIIPattern(
        pattern_id="student_name_pattern",
        description="Student name indicators (Nom: Prenom:)",
        regex=re.compile(
            r"(?:Nom|Prénom|Élève|Candidat)\s*:?\s*[A-Z][a-zéèêëàâäùûüïîôöç]+"
        ),
        severity="medium",
    ),
    PIIPattern(
        pattern_id="date_of_birth",
        description="Date de naissance with context",
        regex=re.compile(
            r"(?:né\(e\)|date de naissance|naissance)\s*:?\s*\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}",
            re.IGNORECASE,
        ),
        severity="high",
    ),
]

# Allowlist patterns for pedagogical content (not actual PII)
ALLOWLIST_PATTERNS = [
    re.compile(r"jean\.dupont@example\.com", re.IGNORECASE),
    re.compile(r"jean\.exemple@education\.fr", re.IGNORECASE),
    re.compile(r"exemple@.*\.fr", re.IGNORECASE),
    re.compile(r"prenom\.nom@.*\.fr", re.IGNORECASE),
    re.compile(r"contact@eduscol\.education\.fr", re.IGNORECASE),
    re.compile(r"^\s*Nom\s*:\s*\.{3,}\s*$", re.MULTILINE),  # "Nom: ..." fill-in blanks
    re.compile(r"^\s*Prénom\s*:\s*\.{3,}\s*$", re.MULTILINE),
]


def load_patterns_from_config(config_path: Path) -> list[PIIPattern]:
    """Load PII patterns from YAML configuration.

    Fail-closed: If a config file exists, it MUST contain valid patterns.
    Silent fallback to defaults is forbidden (H2-F Défaut 2).
    """
    if not config_path.exists():
        return DEFAULT_PII_PATTERNS

    content = config_path.read_text(encoding="utf-8")
    config = yaml.safe_load(content)

    if not isinstance(config, dict):
        raise ValueError("PII policy must be a YAML mapping")

    full_content_scan = config.get("full_content_scan")
    if not isinstance(full_content_scan, dict):
        raise ValueError("full_content_scan section is required in PII policy")

    patterns_raw = full_content_scan.get("patterns_to_search")
    if not isinstance(patterns_raw, list) or len(patterns_raw) == 0:
        raise ValueError(
            "patterns_to_search must be a non-empty list in PII policy"
        )

    patterns = []
    for p in patterns_raw:
        if not isinstance(p, dict):
            raise ValueError("Each pattern in patterns_to_search must be a mapping")
        pattern_id = p.get("pattern_id")
        if not isinstance(pattern_id, str) or not pattern_id:
            raise ValueError("pattern_id must be a non-empty string")
        description = p.get("description")
        if not isinstance(description, str) or not description:
            raise ValueError(f"description must be a non-empty string for pattern {pattern_id!r}")
        regex_str = p.get("regex")
        if not isinstance(regex_str, str) or not regex_str:
            raise ValueError(f"regex must be a non-empty string for pattern {pattern_id!r}")
        try:
            regex = re.compile(regex_str, re.IGNORECASE if "IGNORECASE" in p.get("flags", "") else 0)
            patterns.append(
                PIIPattern(
                    pattern_id=pattern_id,
                    description=description,
                    regex=regex,
                    severity=p.get("severity", "high"),
                )
            )
        except re.error as exc:
            raise ValueError(
                f"Invalid PII regex for pattern {pattern_id!r}"
            ) from exc

    return patterns


def is_allowlisted(match_text: str) -> bool:
    """Check if a match is in the allowlist (pedagogical examples, not real PII)."""
    for pattern in ALLOWLIST_PATTERNS:
        if pattern.search(match_text):
            return True
    return False


def extract_context(text: str, start: int, end: int, context_chars: int = 50) -> str:
    """Extract surrounding context for a match."""
    ctx_start = max(0, start - context_chars)
    ctx_end = min(len(text), end + context_chars)
    context = text[ctx_start:ctx_end]
    # Replace newlines for readability
    return context.replace("\n", " ").strip()


def extract_pdf_text(pdf_path: Path) -> tuple[list[str], str | None]:
    """Extract text from PDF, returns (pages_text, error_or_none)."""
    if PdfReader is None:
        return [], "pypdf not installed"

    try:
        reader = PdfReader(str(pdf_path))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)
        return pages, None
    except Exception as e:
        return [], f"PDF extraction failed: {type(e).__name__}: {e}"


def extract_pdf_text_bytes(pdf_content: bytes) -> tuple[list[str], str | None]:
    """Extract text from one immutable PDF byte snapshot."""
    if PdfReader is None:
        return [], "pypdf not installed"

    try:
        reader = PdfReader(BytesIO(pdf_content))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)
        return pages, None
    except Exception as exc:
        return [], f"PDF extraction failed: {type(exc).__name__}: {exc}"


def scan_text_for_pii(
    text: str,
    patterns: list[PIIPattern],
    page_number: int | None = None,
) -> list[PIIMatch]:
    """Scan text for PII patterns, return matches."""
    matches = []

    for pattern in patterns:
        for m in pattern.regex.finditer(text):
            match_text = m.group(0)

            # Skip allowlisted matches
            if is_allowlisted(match_text):
                continue

            context = extract_context(text, m.start(), m.end())
            matches.append(
                PIIMatch(
                    pattern_id=pattern.pattern_id,
                    description=pattern.description,
                    match_text=match_text,
                    page_number=page_number,
                    char_offset=m.start(),
                    context=context,
                )
            )

    return matches


def compute_file_sha256(path: Path) -> str:
    """Compute SHA256 hash of a file."""
    sha = hashlib.sha256()
    sha.update(path.read_bytes())
    return sha.hexdigest()


class PageInspectionError(RuntimeError):
    """L'inspection structurelle d'une page n'a pas pu s'effectuer.

    Ce n'est pas un verdict. Une panne d'instrument ne conclut jamais « aucune
    image » : elle refuse. Voir docs/reports/lot_1_2_critere_page_sans_texte.md.
    """


PAGE_REFUS_IMAGE = "PAGE_IMAGE_NON_LISIBLE"
PAGE_REFUS_TEXTE = "PAGE_TEXTE_NON_DECODABLE"
PAGE_REFUS_TRACE = "PAGE_TRACE_VECTORIEL"
PAGE_INSPECTION_ECHOUEE = "PAGE_INSPECTION_FAILED"

_OPS_TEXTE = {b"Tj", b"TJ", b"'", b'"'}
_OPS_COURBE = {b"c", b"v", b"y"}
_OPS_TRACE_LIBRE = {b"m", b"l"}


def _inspecter_structure(
    obj: Any,
    reader: Any,
    *,
    vus: set[int],
) -> tuple[int, bool, bool]:
    """Rend (nb_images, opérateur_de_texte, tracé_pouvant_porter_un_glyphe).

    Suit le FLUX DE CONTENU, pas l'inventaire des ressources : beaucoup de
    producteurs attachent le même dictionnaire /Resources à toutes les pages,
    et une image déclarée mais jamais peinte ne porte aucun glyphe. Descend
    récursivement dans les /Form XObjects effectivement invoqués par `Do`.
    Compte les images sans les décoder : aucune dépendance à pillow.
    """
    images = 0
    texte = False
    trace = False

    xobjects: Any = {}
    ressources = obj.get("/Resources")
    if ressources is not None:
        declares = ressources.get_object().get("/XObject")
        if declares is not None:
            xobjects = declares.get_object()

    # Une page porte son flux dans /Contents ; un /Form XObject EST son flux.
    source = obj.get_contents() if hasattr(obj, "get_contents") else obj
    if source is None:
        return images, texte, trace

    for operandes, operateur in ContentStream(source, reader).operations:
        if operateur in _OPS_TEXTE:
            texte = True
        elif operateur in _OPS_COURBE or operateur in _OPS_TRACE_LIBRE:
            trace = True
        elif operateur == b"INLINE IMAGE":
            images += 1
        elif operateur == b"Do" and operandes:
            reference = xobjects.get(operandes[0]) if xobjects else None
            if reference is None:
                # L'instrument ne peut pas dire ce qui est peint : il refuse.
                raise KeyError(f"XObject {operandes[0]!r} introuvable")
            identifiant = getattr(reference, "idnum", None)
            if identifiant is not None:
                if identifiant in vus:
                    continue
                vus.add(identifiant)
            enfant = reference.get_object()
            sous_type = enfant.get("/Subtype")
            if sous_type == "/Image":
                images += 1
            elif sous_type == "/Form":
                n, t, v = _inspecter_structure(enfant, reader, vus=vus)
                images += n
                texte = texte or t
                trace = trace or v
    return images, texte, trace


def classer_pages_sans_texte(
    pdf_content: bytes,
    numeros: Sequence[int],
) -> dict[int, str]:
    """Rend {numéro de page: motif de refus} pour les pages NON ignorables.

    Une page absente du résultat est ignorable : structurellement incapable de
    porter un glyphe. Le critère est fixé dans
    docs/reports/lot_1_2_critere_page_sans_texte.md et n'emploie aucun seuil.

    Lève PageInspectionError si l'instrument ne peut pas s'exercer — jamais de
    valeur de repli (R32).
    """
    if PdfReader is None or ContentStream is None:
        raise PageInspectionError("pypdf indisponible")
    try:
        reader = PdfReader(BytesIO(pdf_content))
    except Exception as exc:  # noqa: BLE001 - relevée, jamais convertie en verdict
        raise PageInspectionError(
            f"lecture impossible: {type(exc).__name__}: {exc}"
        ) from exc
    refus: dict[int, str] = {}
    for numero in numeros:
        try:
            page = reader.pages[numero - 1]
            images, texte, trace = _inspecter_structure(page, reader, vus=set())
        except Exception as exc:  # noqa: BLE001 - relevée, jamais convertie en verdict
            raise PageInspectionError(
                f"page {numero}: {type(exc).__name__}: {exc}"
            ) from exc
        if images:
            refus[numero] = PAGE_REFUS_IMAGE
        elif texte:
            refus[numero] = PAGE_REFUS_TEXTE
        elif trace:
            refus[numero] = PAGE_REFUS_TRACE
    return refus


def extract_pdf_pages_with_structural_empty_pages(
    pdf_content: bytes,
) -> tuple[list[str], tuple[int, ...], str | None]:
    """Extrait les pages et dérive les seules pages structurellement vides.

    Cette fonction est l'autorité commune du scan PII et du préflight. Une
    chaîne vide issue de ``extract_text()`` n'est jamais, à elle seule, un
    verdict de vide : le prédicat structurel existant doit également conclure
    que la page ne peut porter aucun glyphe.
    """
    pages_text, error = extract_pdf_text_bytes(pdf_content)
    if error:
        return pages_text, (), error
    if not pages_text or not any(page_text.strip() for page_text in pages_text):
        return pages_text, (), "PDF_TEXT_EXTRACTION_EMPTY"

    sans_texte = tuple(
        numero
        for numero, page_text in enumerate(pages_text, start=1)
        if not page_text.strip()
    )
    if not sans_texte:
        return pages_text, (), None

    try:
        refus = classer_pages_sans_texte(pdf_content, sans_texte)
    except PageInspectionError as exc:
        return pages_text, (), f"{PAGE_INSPECTION_ECHOUEE}:{exc}"
    if refus:
        motif = sorted({m for m in refus.values()})
        pages = ",".join(str(n) for n in sorted(refus))
        return pages_text, (), f"{'+'.join(motif)}:pages {pages}"
    return pages_text, sans_texte, None


def scan_pdf_bytes(
    pdf_content: bytes,
    *,
    source_path: str,
    patterns: list[PIIPattern] | None = None,
) -> PIIScanResult:
    """Scan one immutable PDF byte snapshot for PII."""
    import time

    start = time.monotonic()
    patterns = patterns or DEFAULT_PII_PATTERNS
    sha256 = hashlib.sha256(pdf_content).hexdigest()
    pages_text, ignored_empty_pages, error = (
        extract_pdf_pages_with_structural_empty_pages(pdf_content)
    )
    if error:
        return PIIScanResult(
            file_path=source_path,
            sha256=sha256,
            pages_scanned=0,
            characters_scanned=0,
            pii_detected=False,
            ignored_empty_pages=(),
            matches=[],
            extraction_error=error,
            scan_duration_ms=int((time.monotonic() - start) * 1000),
        )

    all_matches: list[PIIMatch] = []
    total_chars = 0

    ignorables = set(ignored_empty_pages)
    for page_idx, page_text in enumerate(pages_text, start=1):
        if page_idx in ignorables:
            continue
        total_chars += len(page_text)
        page_matches = scan_text_for_pii(page_text, patterns, page_number=page_idx)
        all_matches.extend(page_matches)

    duration_ms = int((time.monotonic() - start) * 1000)

    return PIIScanResult(
        file_path=source_path,
        sha256=sha256,
        pages_scanned=len(pages_text) - len(ignorables),
        characters_scanned=total_chars,
        pii_detected=len(all_matches) > 0,
        ignored_empty_pages=ignored_empty_pages,
        matches=all_matches,
        extraction_error=None,
        scan_duration_ms=duration_ms,
    )


def scan_pdf(
    pdf_path: Path,
    patterns: list[PIIPattern] | None = None,
) -> PIIScanResult:
    """Read a PDF once, then scan exactly the bytes that were hashed."""
    import time

    start = time.monotonic()
    try:
        pdf_content = pdf_path.read_bytes()
    except OSError as exc:
        return PIIScanResult(
            file_path=str(pdf_path),
            sha256="",
            pages_scanned=0,
            characters_scanned=0,
            pii_detected=False,
            matches=[],
            extraction_error=f"PDF read failed: {type(exc).__name__}: {exc}",
            scan_duration_ms=int((time.monotonic() - start) * 1000),
        )
    return scan_pdf_bytes(
        pdf_content,
        source_path=str(pdf_path),
        patterns=patterns,
    )


def scan_corpus(
    manifest_path: Path,
    corpus_root: Path,
    patterns: list[PIIPattern] | None = None,
    file_column: str = "path",
    sha_column: str = "sha256",
) -> PIIScanReport:
    """Scan the exact non-empty PDF perimeter declared by a local manifest."""
    patterns = patterns or DEFAULT_PII_PATTERNS

    # Read manifest (TSV format)
    manifest_content = manifest_path.read_text(encoding="utf-8")
    lines = manifest_content.splitlines()

    if not lines or not manifest_content.strip():
        raise ValueError(f"Empty manifest: {manifest_path}")

    # Parse header
    header = lines[0].split("\t")
    try:
        path_idx = header.index(file_column)
    except ValueError as e:
        raise ValueError(f"Column '{file_column}' not found in manifest header: {header}") from e

    try:
        sha_idx = header.index(sha_column)
    except ValueError as e:
        raise ValueError(
            f"Column '{sha_column}' not found in manifest header: {header}"
        ) from e

    results: list[PIIScanResult] = []
    total_matches = 0
    matches_by_pattern: dict[str, int] = {}
    files_with_pii = 0
    files_with_errors = 0

    expected_pdf_count = 0
    root = corpus_root.resolve()
    for line_number, line in enumerate(lines[1:], start=2):
        if not line.strip():
            continue

        cols = line.split("\t")
        if len(cols) <= max(path_idx, sha_idx):
            raise ValueError(f"Malformed manifest row {line_number}")

        rel_path = cols[path_idx].strip()
        if not rel_path:
            raise ValueError(f"Manifest row {line_number} has an empty path")

        # Only scan PDFs
        if not rel_path.lower().endswith(".pdf"):
            continue
        expected_pdf_count += 1

        expected_sha256 = cols[sha_idx].strip()
        if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
            raise ValueError(
                f"Manifest row {line_number} requires a canonical SHA256"
            )

        relative = Path(rel_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Manifest row {line_number} has an unsafe PDF path")
        pdf_path = (root / relative).resolve()
        if root not in pdf_path.parents:
            raise ValueError(f"Manifest row {line_number} escapes corpus root")

        if not pdf_path.is_file():
            result = PIIScanResult(
                file_path=str(pdf_path),
                sha256="",
                pages_scanned=0,
                characters_scanned=0,
                pii_detected=False,
                extraction_error="LOCAL_FILE_MISSING",
            )
        else:
            observed_sha256 = compute_file_sha256(pdf_path)
            if observed_sha256 != expected_sha256:
                result = PIIScanResult(
                    file_path=str(pdf_path),
                    sha256=observed_sha256,
                    pages_scanned=0,
                    characters_scanned=0,
                    pii_detected=False,
                    extraction_error="CONTENT_SHA256_MISMATCH",
                )
            else:
                result = scan_pdf(pdf_path, patterns)
                if result.sha256 != observed_sha256:
                    result = PIIScanResult(
                        file_path=str(pdf_path),
                        sha256=observed_sha256,
                        pages_scanned=0,
                        characters_scanned=0,
                        pii_detected=False,
                        extraction_error="SCANNER_SHA256_DRIFT",
                    )

        results.append(result)

        if result.extraction_error:
            files_with_errors += 1
        elif result.pii_detected:
            files_with_pii += 1

        total_matches += len(result.matches)
        for m in result.matches:
            matches_by_pattern[m.pattern_id] = matches_by_pattern.get(m.pattern_id, 0) + 1

    if expected_pdf_count == 0:
        raise ValueError("Manifest must declare a non-empty PDF perimeter")
    if len(results) != expected_pdf_count:
        raise RuntimeError("PDF scan perimeter was not evaluated completely")

    files_clean = expected_pdf_count - files_with_pii - files_with_errors
    pii_absent = (
        expected_pdf_count > 0
        and len(results) == expected_pdf_count
        and files_with_pii == 0
        and files_with_errors == 0
    )

    return PIIScanReport(
        report_id=f"pii_scan_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        generated_at=datetime.now(UTC).isoformat(),
        policy_version="pii_gate_policy_h2b_v1",
        total_files=expected_pdf_count,
        files_scanned=expected_pdf_count - files_with_errors,
        files_with_errors=files_with_errors,
        files_with_pii=files_with_pii,
        files_clean=files_clean,
        pii_absent_attested=pii_absent,
        total_matches=total_matches,
        matches_by_pattern=matches_by_pattern,
        results=results,
    )


def result_to_dict_sanitized(result: PIIScanResult) -> dict[str, Any]:
    """Convert PIIScanResult to sanitized dict for external evidence.

    CRITICAL: This function NEVER includes raw PII values.
    Only safe metadata is exposed for audit trail.
    """
    extraction_error_code = None
    if result.extraction_error == "pypdf not installed":
        extraction_error_code = "PYPDF_UNAVAILABLE"
    elif result.extraction_error and result.extraction_error.split(":", 1)[0] in {
        PAGE_INSPECTION_ECHOUEE,
    } | {
        "+".join(sorted(combinaison))
        for combinaison in (
            {PAGE_REFUS_IMAGE},
            {PAGE_REFUS_TEXTE},
            {PAGE_REFUS_TRACE},
            {PAGE_REFUS_IMAGE, PAGE_REFUS_TEXTE},
            {PAGE_REFUS_IMAGE, PAGE_REFUS_TRACE},
            {PAGE_REFUS_TEXTE, PAGE_REFUS_TRACE},
            {PAGE_REFUS_IMAGE, PAGE_REFUS_TEXTE, PAGE_REFUS_TRACE},
        )
    }:
        extraction_error_code = result.extraction_error.split(":", 1)[0]
    elif result.extraction_error in {
        "CONTENT_SHA256_MISMATCH",
        "LOCAL_FILE_MISSING",
        "PDF_PAGE_TEXT_EXTRACTION_EMPTY",
        "PDF_TEXT_EXTRACTION_EMPTY",
        "SCANNER_SHA256_DRIFT",
    }:
        extraction_error_code = result.extraction_error
    elif result.extraction_error:
        extraction_error_code = "PDF_EXTRACTION_FAILED"

    return {
        "sha256": result.sha256,
        "pages_scanned": result.pages_scanned,
        "characters_scanned": result.characters_scanned,
        "pii_detected": result.pii_detected,
        "ignored_empty_pages": list(result.ignored_empty_pages),
        "signal_count": len(result.matches),
        "signal_classes": sorted({m.pattern_id for m in result.matches}),
        "signals": [
            {
                "pattern_id": m.pattern_id,
                "page_number": m.page_number,
                "match_length": len(m.match_text),
                # NO match_text - contains raw PII
                # NO context - contains raw PII
            }
            for m in result.matches
        ],
        "extraction_error_code": extraction_error_code,
        "scan_duration_ms": result.scan_duration_ms,
    }


def result_to_dict(result: PIIScanResult) -> dict[str, Any]:
    """Convert a result to the only supported, PII-safe external form."""
    return result_to_dict_sanitized(result)


def report_to_dict(report: PIIScanReport) -> dict[str, Any]:
    """Convert a report to the only supported, PII-safe external form."""
    return {
        "report_id": report.report_id,
        "generated_at": report.generated_at,
        "policy_version": report.policy_version,
        "summary": {
            "total_files": report.total_files,
            "files_scanned": report.files_scanned,
            "files_with_errors": report.files_with_errors,
            "files_with_pii": report.files_with_pii,
            "files_clean": report.files_clean,
            "pii_absent_attested": report.pii_absent_attested,
            "total_matches": report.total_matches,
            "matches_by_pattern": report.matches_by_pattern,
        },
        "results": [result_to_dict(result) for result in report.results],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan PDFs for PII content.")
    parser.add_argument(
        "--pdf",
        type=Path,
        help="Single PDF file to scan",
    )
    parser.add_argument(
        "--corpus-manifest",
        type=Path,
        help="TSV manifest of corpus files to scan",
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        help="Root directory of corpus files",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/pii_gate_policy.yml"),
        help="Path to PII policy configuration",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output path for JSON report",
    )
    args = parser.parse_args()

    patterns = load_patterns_from_config(args.config)

    if args.pdf:
        # Single file mode
        result = scan_pdf(args.pdf, patterns)
        output = result_to_dict(result)

        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(output, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        print(json.dumps(output, indent=2, ensure_ascii=False))

        return 1 if result.pii_detected or result.extraction_error else 0

    elif args.corpus_manifest and args.corpus_root:
        # Corpus mode
        try:
            report = scan_corpus(args.corpus_manifest, args.corpus_root, patterns)
        except Exception:
            print("PII_SCAN_FAILED=true")
            return 2
        output = report_to_dict(report)

        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(output, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        # Print summary
        print(f"PII SCAN REPORT: {report.report_id}")
        print("=" * 60)
        print(f"Total files:       {report.total_files}")
        print(f"Files scanned:     {report.files_scanned}")
        print(f"Files with errors: {report.files_with_errors}")
        print(f"Files with PII:    {report.files_with_pii}")
        print(f"Files clean:       {report.files_clean}")
        print(f"Total matches:     {report.total_matches}")
        print()
        print(f"PII_ABSENT_ATTESTED = {report.pii_absent_attested}")

        return 0 if report.pii_absent_attested else 1

    else:
        parser.error("Provide either --pdf or both --corpus-manifest and --corpus-root")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
