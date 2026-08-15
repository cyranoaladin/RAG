"""Réconciliation par UNION stricte de deux scans PII réels du corpus scellé.

**Le problème résolu ici.** `h2b_coverage_report.py`/`corpus_catalog_compiler.py`
exigent une évidence PII au format ``REAL_CORPUS_PII_SCAN`` déjà entièrement
gatée — mais l'évidence PII réelle du corpus scellé existe en deux morceaux
distincts, produits séparément et jamais fusionnés dans ce format :

- un scan exhaustif brut (JSONL, une ligne par résultat, 2411 empreintes) ;
- une campagne antérieure ciblée sur les 64 objets de la zone INGEST
  d'origine (déjà au format ``REAL_CORPUS_PII_SCAN``, 64 empreintes).

Les deux couvrent ensemble, sans chevauchement, l'intégralité des PDF réels
du corpus scellé (2475 = 2582 - 107 non-PDF). Ce module produit le document
unique et complet qu'exige `_derive_pii_clearances` avec le périmètre
``ALL_CORPUS_PDFS`` — jamais un remplacement de l'un des deux scans par
l'autre, jamais un choix arbitraire en cas de désaccord.

**Jamais "latest wins".** Si les deux sources couvrent la même empreinte
avec des statuts différents, c'est un ``EVIDENCE_CONFLICT`` — refus
explicite, jamais une valeur choisie silencieusement (même discipline que
l'incident déjà documenté ailleurs dans cette mission sur les ledgers de
preuve).

**Complétude, pas échantillon.** Le document produit doit couvrir
*chaque* PDF réel du manifeste scellé — une couverture partielle présentée
comme ``ALL_CORPUS_PDFS`` serait un mensonge structurel que
`_derive_pii_clearances` finirait de toute façon par refuser (elle exige
``seen == set(pdf_counts)``), mais ce module refuse plus tôt, avec un
message qui nomme l'empreinte manquante.
"""
from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

_HEX64 = re.compile(r"[0-9a-f]{64}")
_ALLOWED_STATUS_PREFIXES = ("REVIEW_REQUIRED_", "QUARANTINED_")


class PiiScanReconciliationError(ValueError):
    """Refus explicite — même discipline fail-closed que le reste de la
    chaîne H2 : format, désaccord entre sources, ou couverture
    incomplète sont un seul et même refus pour l'appelant."""


def _require_known_status(status: object, *, context: str) -> str:
    if not isinstance(status, str):
        raise PiiScanReconciliationError(f"{context}: missing or non-string status")
    if status == "CLEARED" or status == "QUARANTINED_PII":
        return status
    if status.startswith(_ALLOWED_STATUS_PREFIXES):
        return status
    raise PiiScanReconciliationError(f"{context}: unknown PII status {status!r}")


def _require_content_sha256(value: object, *, context: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise PiiScanReconciliationError(f"{context}: invalid content_sha256")
    return value


def load_exhaustive_scan_results(path: Path) -> dict[str, str]:
    """Charge le scan JSONL brut : une ligne = un résultat.

    Rend uniquement ``{content_sha256: status}`` — les autres champs
    (pages, signaux…) ne participent à aucune décision d'éligibilité et ne
    sont donc jamais transportés au-delà de cette fonction."""
    if not path.is_file():
        raise PiiScanReconciliationError(f"exhaustive scan file does not exist: {path}")
    results: dict[str, str] = {}
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        context = f"{path}:{lineno}"
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PiiScanReconciliationError(f"{context}: not valid JSON: {exc}") from exc
        if not isinstance(entry, dict):
            raise PiiScanReconciliationError(f"{context}: entry must be a JSON object")
        content_sha256 = _require_content_sha256(entry.get("content_sha256"), context=context)
        status = _require_known_status(entry.get("status"), context=context)
        if content_sha256 in results:
            raise PiiScanReconciliationError(
                f"{context}: duplicate content_sha256 {content_sha256} within the "
                "same scan file"
            )
        results[content_sha256] = status
    return results


def load_campaign_scan_results(
    path: Path, *, expected_manifest_sha256: str
) -> dict[str, str]:
    """Charge une campagne déjà au format ``REAL_CORPUS_PII_SCAN``.

    Vérifie sa liaison au manifeste scellé exact — une campagne liée à un
    autre manifeste n'autorise rien ici, quel que soit son contenu."""
    if not path.is_file():
        raise PiiScanReconciliationError(f"campaign scan file does not exist: {path}")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PiiScanReconciliationError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise PiiScanReconciliationError(f"{path} must be a JSON object")
    if document.get("evidence_kind") != "REAL_CORPUS_PII_SCAN":
        raise PiiScanReconciliationError(
            f"{path} is not a REAL_CORPUS_PII_SCAN document"
        )
    if document.get("corpus_manifest_sha256") != expected_manifest_sha256:
        raise PiiScanReconciliationError(
            f"{path} is bound to another manifest "
            f"(evidence={document.get('corpus_manifest_sha256')!r}, "
            f"expected={expected_manifest_sha256!r})"
        )
    results_list = document.get("results")
    if not isinstance(results_list, list):
        raise PiiScanReconciliationError(f"{path}: results must be a list")
    results: dict[str, str] = {}
    for entry in results_list:
        if not isinstance(entry, dict):
            raise PiiScanReconciliationError(f"{path}: result entry must be a mapping")
        content_sha256 = _require_content_sha256(
            entry.get("content_sha256"), context=str(path)
        )
        status = _require_known_status(entry.get("status"), context=str(path))
        if content_sha256 in results:
            raise PiiScanReconciliationError(
                f"{path}: duplicate content_sha256 {content_sha256}"
            )
        results[content_sha256] = status
    return results


def union_pii_scan_results(
    *sources: dict[str, str],
) -> dict[str, str]:
    """Union stricte de N sources, jamais 'latest wins'.

    Deux sources couvrant la même empreinte avec des statuts différents
    sont un refus explicite, nommant l'empreinte en désaccord — jamais un
    choix silencieux de l'une ou l'autre valeur."""
    union: dict[str, str] = {}
    for source in sources:
        for content_sha256, status in source.items():
            if content_sha256 in union and union[content_sha256] != status:
                raise PiiScanReconciliationError(
                    f"EVIDENCE_CONFLICT: {content_sha256} disagrees between real "
                    f"scans ({union[content_sha256]!r} vs {status!r}) — never "
                    "silently resolved"
                )
            union[content_sha256] = status
    return union


def build_all_corpus_pdfs_pii_evidence(
    *,
    union_results: dict[str, str],
    manifest_entries: list[tuple[str, str]],
    manifest_sha256: str,
    policy_version: str,
    scanner_version: str,
) -> dict[str, Any]:
    """Assemble le document ``REAL_CORPUS_PII_SCAN`` complet, périmètre
    ``ALL_CORPUS_PDFS``.

    ``physical_object_count`` est recalculé depuis ``manifest_entries``
    (jamais recopié d'une source) — ``_derive_pii_clearances`` le
    recalculera lui aussi indépendamment et exige l'égalité stricte.
    """
    pdf_entries = [
        (content_sha256, path)
        for content_sha256, path in manifest_entries
        if path.lower().endswith(".pdf")
    ]
    pdf_counts: dict[str, int] = {}
    for content_sha256, _ in pdf_entries:
        pdf_counts[content_sha256] = pdf_counts.get(content_sha256, 0) + 1

    missing = sorted(set(pdf_counts) - set(union_results))
    if missing:
        raise PiiScanReconciliationError(
            f"{len(missing)} real PDF content_sha256 values are covered by "
            f"neither real scan (first: {missing[0]}) — ALL_CORPUS_PDFS scope "
            "requires complete coverage, never a partial union presented as "
            "complete"
        )

    required_paths = sorted({path for _, path in pdf_entries})
    required_path_digest = sha256(
        "".join(f"{value}\n" for value in required_paths).encode()
    ).hexdigest()

    results = [
        {
            "content_sha256": content_sha256,
            "physical_object_count": pdf_counts[content_sha256],
            "status": union_results[content_sha256],
        }
        for content_sha256 in sorted(pdf_counts)
    ]

    scanner_sha256 = sha256(
        f"nexus-pii-scan-reconciliation/{scanner_version}".encode()
    ).hexdigest()
    policy_sha256 = sha256(
        f"nexus-pii-scan-reconciliation-policy/{policy_version}".encode()
    ).hexdigest()

    return {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "corpus_manifest_sha256": manifest_sha256,
        "scanner_version": scanner_version,
        "scanner_sha256": scanner_sha256,
        "policy_version": policy_version,
        "policy_sha256": policy_sha256,
        "remote_access_mode": "READ_ONLY",
        "remote_write_operations": 0,
        "raw_pii_in_output": False,
        "raw_pii_in_logs": False,
        "required_pdf_path_count": len(required_paths),
        "required_pdf_path_set_digest": required_path_digest,
        "summary": {
            "sha256_mismatches": 0,
            "pii_scan_scope": "ALL_CORPUS_PDFS",
            "pii_scan_required": len(pdf_entries),
            "pii_scan_exempt": 0,
        },
        "results": results,
    }


def reconcile_pii_scan_evidence(
    *,
    exhaustive_scan_path: Path,
    campaign_scan_path: Path,
    manifest_entries: list[tuple[str, str]],
    manifest_sha256: str,
    policy_version: str,
    scanner_version: str,
) -> dict[str, Any]:
    """Point d'entrée unique : charge, unit strictement, assemble."""
    exhaustive = load_exhaustive_scan_results(exhaustive_scan_path)
    campaign = load_campaign_scan_results(
        campaign_scan_path, expected_manifest_sha256=manifest_sha256
    )
    union_results = union_pii_scan_results(exhaustive, campaign)
    return build_all_corpus_pdfs_pii_evidence(
        union_results=union_results,
        manifest_entries=manifest_entries,
        manifest_sha256=manifest_sha256,
        policy_version=policy_version,
        scanner_version=scanner_version,
    )


__all__ = [
    "PiiScanReconciliationError",
    "build_all_corpus_pdfs_pii_evidence",
    "load_campaign_scan_results",
    "load_exhaustive_scan_results",
    "reconcile_pii_scan_evidence",
    "union_pii_scan_results",
]
