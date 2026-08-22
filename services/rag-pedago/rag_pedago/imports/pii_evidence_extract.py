"""PII Review Evidence Extraction — LOT41A-V2 remediation (Codex P1, PR #98).

**Le problème résolu ici.** Une autorisation LOT41A-V2 porte
``pii_absence_attested=true`` pour un ensemble de contenus exacts
(``allowed_content_sha256``). Avant ce module, la seule preuve committée
était une citation en texte libre d'un digest — un reviewer GitHub ne
pouvait ni recalculer ce digest (le fichier source vit hors dépôt, sur la
machine de l'opérateur), ni vérifier que les résultats couvrent
effectivement les contenus autorisés, ni s'assurer qu'aucun des cinq
n'est en réalité ``QUARANTINED_PII``/``REVIEW_REQUIRED``.

**Ce que ce module produit.** Un extrait canonique, déterministe et
committable : uniquement les entrées des contenus explicitement demandés,
uniquement les champs déjà garantis PII-safe par
``pii_scanner.result_to_dict_sanitized`` (jamais ``match_text`` ni
``context`` — ce module ne les lit même pas, il les ignore par
construction du sous-ensemble de clés qu'il projette). Le fichier source
externe est relu octet à octet et son SHA-256 recalculé et comparé à la
valeur attendue **avant** tout parsing JSON — un fichier substitué est
donc détecté avant même d'être interprété.

**Ce que ce module refuse, fermé, jamais silencieusement** :

- digest de la source externe qui ne correspond pas à l'attendu ;
- ``corpus_manifest_sha256`` de la source qui ne correspond pas à
  l'attendu (l'evidence PII et l'autorisation doivent porter sur le même
  manifeste de corpus) ;
- un des SHA-256 autorisés absent des résultats de la source ;
- un résultat dont ``status`` n'est pas exactement ``CLEARED`` ;
- un résultat dont ``pii_detected`` n'est pas ``False`` ;
- un résultat dont ``error_code`` n'est pas ``None`` (extraction/scan
  incomplet) ;
- toute clé de PII brute (``match_text``, ``context``, ...) détectée dans
  le document produit — défense en profondeur même si la source amont est
  déjà sanitized par construction.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Version du format d'evidence reviewable produit par ce module. Distincte
#: de ``evidence_kind`` (``REAL_CORPUS_PII_SCAN``, hérité de la source) —
#: celle-ci nomme *ce* format d'extrait, pas le scan d'origine.
REVIEWABLE_EVIDENCE_PROTOCOL_VERSION = "NEXUS-PII-REVIEW-EVIDENCE-V1"

#: Seul statut jamais accepté pour une entrée : un résultat ``QUARANTINED_PII``,
#: ``REVIEW_REQUIRED`` ou toute autre valeur est refusé fermé.
_REQUIRED_STATUS = "CLEARED"

#: Clés jamais autorisées à apparaître nulle part dans le document produit —
#: défense en profondeur au-delà du sous-ensemble de champs projeté.
_FORBIDDEN_KEYS = frozenset(
    {
        "match_text",
        "context",
        "raw_text",
        "name",
        "email",
        "phone",
        "iban",
        "signals",
    }
)

#: Champs par résultat repris de la source — exactement ceux déjà garantis
#: PII-safe par ``pii_scanner.result_to_dict_sanitized``. Aucun champ hors
#: de cette liste n'est jamais copié depuis la source, quel que soit son nom.
_RESULT_FIELDS = (
    "content_sha256",
    "status",
    "pii_detected",
    "pages_scanned",
    "characters_scanned",
    "signal_count",
    "signal_classes",
    "error_code",
)

_CANONICAL_INDENT = 2


class PiiEvidenceExtractionError(ValueError):
    """La source ne prouve pas ce que l'autorisation prétend — refus
    explicite, jamais un extrait partiel ou une valeur de repli."""


@dataclass(frozen=True)
class ExtractedPiiEvidence:
    document: dict[str, Any]
    canonical_bytes: bytes
    digest: str


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(document, sort_keys=True, indent=_CANONICAL_INDENT, ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def _scan_for_forbidden_keys(document: Any, *, path: str = "$") -> None:
    if isinstance(document, dict):
        for key, value in document.items():
            if key in _FORBIDDEN_KEYS:
                raise PiiEvidenceExtractionError(
                    f"forbidden key {key!r} present at {path}.{key} in the produced "
                    "evidence document — raw PII must never reach a committed artifact"
                )
            _scan_for_forbidden_keys(value, path=f"{path}.{key}")
    elif isinstance(document, list):
        for index, value in enumerate(document):
            _scan_for_forbidden_keys(value, path=f"{path}[{index}]")


def extract_reviewable_pii_evidence(
    source_path: Path,
    *,
    expected_source_sha256: str,
    expected_corpus_manifest_sha256: str,
    required_content_sha256: tuple[str, ...],
) -> ExtractedPiiEvidence:
    """Dérive un extrait d'evidence PII reviewable et déterministe.

    Pure et sans effet de bord réseau : lit uniquement ``source_path``.
    Lève ``PiiEvidenceExtractionError`` sur toute divergence — jamais un
    document partiel, jamais un statut autre que ``CLEARED`` accepté en
    silence."""
    if len(required_content_sha256) == 0:
        raise PiiEvidenceExtractionError("required_content_sha256 must not be empty")
    if len(set(required_content_sha256)) != len(required_content_sha256):
        raise PiiEvidenceExtractionError("required_content_sha256 must not contain duplicates")

    raw = source_path.read_bytes()
    observed_source_sha256 = hashlib.sha256(raw).hexdigest()
    if observed_source_sha256 != expected_source_sha256:
        raise PiiEvidenceExtractionError(
            f"source evidence at {source_path} hashes to {observed_source_sha256}, "
            f"expected {expected_source_sha256} — refusing to read a substituted file"
        )

    try:
        source = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PiiEvidenceExtractionError(f"source evidence is not valid JSON: {exc}") from exc
    if not isinstance(source, dict):
        raise PiiEvidenceExtractionError("source evidence must be a JSON object")

    source_manifest = source.get("corpus_manifest_sha256")
    if source_manifest != expected_corpus_manifest_sha256:
        raise PiiEvidenceExtractionError(
            f"source evidence corpus_manifest_sha256={source_manifest!r} does not match "
            f"the expected {expected_corpus_manifest_sha256!r} — the PII scan and the "
            "authorization would be describing two different corpora"
        )

    results = source.get("results")
    if not isinstance(results, list):
        raise PiiEvidenceExtractionError("source evidence 'results' must be a list")

    by_sha: dict[str, dict[str, Any]] = {}
    for entry in results:
        if not isinstance(entry, dict):
            continue
        sha = entry.get("content_sha256")
        if isinstance(sha, str):
            by_sha[sha] = entry

    extracted: list[dict[str, Any]] = []
    for sha in sorted(required_content_sha256):
        entry = by_sha.get(sha)
        if entry is None:
            raise PiiEvidenceExtractionError(
                f"content_sha256={sha!r} is not present in the source PII scan results — "
                "an authorization can never attest PII absence for a content the scan "
                "never covered"
            )
        status = entry.get("status")
        if status != _REQUIRED_STATUS:
            raise PiiEvidenceExtractionError(
                f"content_sha256={sha!r} has status={status!r}, not {_REQUIRED_STATUS!r} — "
                "an authorization can never attest PII absence for content that is not "
                "cleared"
            )
        if entry.get("pii_detected") is not False:
            raise PiiEvidenceExtractionError(
                f"content_sha256={sha!r} has pii_detected={entry.get('pii_detected')!r}, "
                "expected False"
            )
        if entry.get("error_code") is not None:
            raise PiiEvidenceExtractionError(
                f"content_sha256={sha!r} has error_code={entry.get('error_code')!r} — "
                "an incomplete scan can never clear a content for PII absence"
            )
        extracted.append({field: entry.get(field) for field in _RESULT_FIELDS})

    document: dict[str, Any] = {
        "evidence_protocol_version": REVIEWABLE_EVIDENCE_PROTOCOL_VERSION,
        "source_evidence_sha256": observed_source_sha256,
        "source_evidence_kind": source.get("evidence_kind"),
        "source_generated_at": source.get("generated_at"),
        "scanner_version": source.get("scanner_version"),
        "scanner_sha256": source.get("scanner_sha256"),
        "policy_version": source.get("policy_version"),
        "policy_sha256": source.get("policy_sha256"),
        "corpus_manifest_sha256": source_manifest,
        "authorized_content_sha256": sorted(required_content_sha256),
        "results": extracted,
    }
    _scan_for_forbidden_keys(document)

    # Pas de champ auto-référentiel : le digest de cet extrait est
    # simplement le SHA-256 du fichier tel qu'il est committé — calculable
    # par n'importe qui avec `sha256sum`, sans dépendre d'une convention de
    # sérialisation interne au document lui-même.
    canonical = _canonical_bytes(document)
    digest = hashlib.sha256(canonical).hexdigest()

    return ExtractedPiiEvidence(document=document, canonical_bytes=canonical, digest=digest)


def _build_arg_parser() -> Any:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Derive a committable, reviewable PII evidence extract from an "
            "external sanitized PII scan report. Deterministic: identical "
            "inputs always produce byte-identical output."
        )
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--expected-corpus-manifest-sha256", required=True)
    parser.add_argument(
        "--content-sha256",
        required=True,
        action="append",
        help="One of the authorized content SHA-256 values; repeat for each.",
    )
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> int:
    args = _build_arg_parser().parse_args()
    try:
        extracted = extract_reviewable_pii_evidence(
            args.source,
            expected_source_sha256=args.expected_source_sha256,
            expected_corpus_manifest_sha256=args.expected_corpus_manifest_sha256,
            required_content_sha256=tuple(args.content_sha256),
        )
    except PiiEvidenceExtractionError as exc:
        print(f"REFUSED: {exc}", file=__import__("sys").stderr)
        return 1

    args.output.write_bytes(extracted.canonical_bytes)
    print(f"EVIDENCE_DIGEST={extracted.digest}")
    print(f"OUTPUT={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "REVIEWABLE_EVIDENCE_PROTOCOL_VERSION",
    "ExtractedPiiEvidence",
    "PiiEvidenceExtractionError",
    "extract_reviewable_pii_evidence",
]
