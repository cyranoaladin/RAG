"""Deterministic discovery module for pilot acquisition planning (Lot 4.1).

Input sources are limited to local files:

- terminale maths / NSI taxonomies
- official reference catalog

No network call and no LLM usage are performed.
"""

from __future__ import annotations

import argparse
import re
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from rag_pedago.reference.loader import load_official_reference_index
from schema.document import Niveau, Rights, SourceType, TypeDoc
from schema.official_reference import OfficialSource
from schema.source import SourceManifestItem
from schema.taxonomy import TaxonomySpec

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_REFERENCE_DIR = Path("data/reference")
DEFAULT_TAXONOMY_PATHS = [
    Path("taxonomy/maths/terminale_specialite.yml"),
    Path("taxonomy/nsi/terminale.yml"),
]

DISCOVERY_RULE = """
Règle de matching stricte (lot 4.1 corrigé):
1) Une source doit matcher la matière de la notion (maths/nsi).
2) Une source doit matcher le niveau terminale ou ne pas imposer de niveau explicite.
3) Elle est retenue UNIQUEMENT si un token significatif de notion_id/notion_label
   apparaît dans source_id, title, ou applies_to de la source.
   Aucun fallback curriculaire : une source de programme générique ne couvre pas
   automatiquement toutes les notions de la matière.
4) Les champs de sortie (rights/type_doc/audience) sont inférés via des règles
   locales sur l'autorité et la structure des métadonnées source.
""".strip()


MATIERE_KEYWORDS = {
    "mathematiques": {"math", "mathematiques", "maths", "mathematique"},
    "nsi": {"nsi", "informatique", "numerique", "numeriques", "sciences", "snt"},
}

LEVEL_MARKERS = {
    "terminale": {"terminale", "terminale_generale", "terminale_technologique"},
    "premiere": {"premiere", "premiere_generale", "premiere_technologique"},
}


def _ensure_path(path: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        return ROOT / candidate
    return candidate


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return normalized


def _tokenize(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", _normalize_text(value)))


def _source_terms(source: OfficialSource) -> set[str]:
    terms = set()
    terms.update(_tokenize(source.source_id))
    terms.update(_tokenize(source.title))
    for item in source.applies_to:
        terms.update(_tokenize(item))
    return terms


def _detect_subject(source: OfficialSource) -> str | None:
    terms = _source_terms(source)
    for subject, markers in MATIERE_KEYWORDS.items():
        if terms.intersection(markers):
            return subject
    return None


def _matches_level(source: OfficialSource, niveau: str) -> bool:
    terms = _source_terms(source)
    markers = LEVEL_MARKERS.get(niveau, set())
    if terms.intersection(markers):
        return True
    # Fallback : if no explicit level marker, accept as generic curriculum source.
    level_markers = set().union(*LEVEL_MARKERS.values())
    return not bool(terms.intersection(level_markers))


def _notion_tokens(notion_id: str, notion_label: str) -> set[str]:
    return _tokenize(notion_id) | _tokenize(notion_label)


def _matches_notion(
    notion_id: str,
    notion_label: str,
    subject: str,
    niveau: str,
    source: OfficialSource,
) -> bool:
    if not _matches_level(source, niveau):
        return False
    source_subject = _detect_subject(source)
    if source_subject != subject:
        return False
    source_tokens = _source_terms(source)
    notion_toks = _notion_tokens(notion_id, notion_label)
    # Strict matching: at least one significant notion token must appear in source
    # Exclude trivially short tokens (< 3 chars) to avoid false positives
    significant = {t for t in notion_toks if len(t) >= 3}
    return bool(significant.intersection(source_tokens))


def _infer_rights(source: OfficialSource) -> Rights:
    if source.authority_level.startswith("official"):
        return Rights.officiel_public
    if source.authority_level.startswith("institutional"):
        return Rights.usage_interne
    return Rights.unknown


def _infer_audience(source: OfficialSource) -> str:
    """Infer audience per ADR-0003: libre, aefe, or tous."""
    tokens = _source_terms(source)
    libre_markers = {"candidat_individuel", "candidat_libre", "libre", "individuel",
                     "ponctuelle", "evaluation_ponctuelle", "descriptif_eaf"}
    aefe_markers = {"aefe", "etablissement_francais", "homologue"}
    if tokens.intersection(libre_markers):
        return "libre"
    if tokens.intersection(aefe_markers):
        return "aefe"
    return "tous"


def _infer_type_doc(source: OfficialSource) -> TypeDoc:
    tokens = _source_terms(source)
    if "programme" in tokens:
        return TypeDoc.programme_officiel
    if "exam" in tokens or "bac" in tokens or "dnb" in tokens:
        return TypeDoc.ressource_officielle
    return TypeDoc.ressource_officielle


def _infer_source_type(source: OfficialSource) -> SourceType:
    parsed = urlparse(source.url)
    domain = _normalize_text(parsed.netloc)
    source_id = source.source_id
    if "eduscol" in source_id or "eduscol" in domain:
        return SourceType.eduscol
    if source_id.startswith("bo_") or "bo" in parsed.path.split("/"):
        return SourceType.bo
    if "candidat.examens-concours.gouv.fr" in source.url:
        return SourceType.examens
    return SourceType.officiel


def _build_source_manifest(
    source: OfficialSource,
    notion_id: str,
    matiere: str,
    niveau: str,
    discovered_at: datetime,
) -> SourceManifestItem:
    return SourceManifestItem(
        source_name=source.source_id,
        source_uri=source.url,
        title=source.title,
        detected_matiere=matiere,
        detected_niveau=Niveau(niveau),
        detected_type_doc=_infer_type_doc(source),
        source_type=_infer_source_type(source),
        rights=_infer_rights(source),
        fetched=False,
        discovered_at=discovered_at,
    )


def _load_taxonomy(path: Path) -> TaxonomySpec:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return TaxonomySpec.model_validate(payload)


def _iter_notions(taxonomy: TaxonomySpec) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for theme in taxonomy.themes:
        for notion in theme.notions:
            entries = [(notion.id, notion.label or notion.id)]
            entries.extend((subnotion, subnotion) for subnotion in notion.subnotions)
            for notion_id, notion_label in entries:
                key = (taxonomy.matiere, notion_id)
                if key in seen:
                    continue
                seen.add(key)
                items.append(
                    {
                        "matiere": taxonomy.matiere,
                        "niveau": taxonomy.niveau.value,
                        "notion_id": notion_id,
                        "notion_label": notion_label,
                    }
                )
    return sorted(items, key=lambda item: (item["matiere"], item["notion_id"]))


def build_discovery_plan(
    taxonomy_paths: list[Path] | None = None,
    reference_dir: Path = DEFAULT_REFERENCE_DIR,
    discovered_at: datetime | None = None,
    sources_override: dict[str, OfficialSource] | None = None,
) -> dict[str, Any]:
    if taxonomy_paths is None:
        taxonomy_paths = DEFAULT_TAXONOMY_PATHS

    resolved_taxonomies = [_load_taxonomy(_ensure_path(path)) for path in taxonomy_paths]
    resolved_reference_dir = _ensure_path(reference_dir)

    if sources_override is None:
        index = load_official_reference_index(resolved_reference_dir)
        sources = list(index.sources.values())
    else:
        sources = list(sources_override.values())

    discovered_at = discovered_at or datetime.now(UTC)

    notion_blocks: list[dict[str, Any]] = []
    for taxonomy in resolved_taxonomies:
        for notion in _iter_notions(taxonomy):
            notion_id = notion["notion_id"]
            notion_label = notion["notion_label"]
            matiere = notion["matiere"]
            niveau = notion["niveau"]
            matched_candidates = []

            for source in sorted(sources, key=lambda item: item.source_id):
                if not _matches_notion(notion_id, notion_label, matiere, niveau, source):
                    continue
                manifest = _build_source_manifest(source, notion_id, matiere, niveau, discovered_at)
                matched_candidates.append(
                    {
                        "notion": notion_id,
                        "source_label": source.source_id,
                        "source_uri": source.url,
                        "rights": manifest.rights.value,
                        "type_doc": manifest.detected_type_doc.value,  # type: ignore[union-attr]
                        "audience": _infer_audience(source),
                        "source_manifest": manifest.model_dump(mode="json"),
                    }
                )

            notion_blocks.append(
                {
                    "matiere": matiere,
                    "niveau": niveau,
                    "notion_id": notion_id,
                    "notion_label": notion_label,
                    "candidates": matched_candidates,
                }
            )

    return {
        "discovery_mode": "local_only",
        "matching_rule": DISCOVERY_RULE,
        "generated_at": discovered_at.isoformat(),
        "scope": {
            "pilot": "terminale",
            "matieres": sorted({entry["matiere"] for entry in notion_blocks}),
            "niveau": Niveau.terminale.value,
        },
        "notions": notion_blocks,
    }


def compute_coverage(plan: dict[str, Any]) -> dict[str, Any]:
    by_matiere: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "total": 0,
            "covered": 0,
            "uncovered": [],
        }
    )

    for notion in plan.get("notions", []):
        matiere = notion["matiere"]
        notion_id = notion["notion_id"]
        by_matiere[matiere]["total"] += 1
        if notion.get("candidates"):
            by_matiere[matiere]["covered"] += 1
        else:
            by_matiere[matiere]["uncovered"].append(notion_id)

    covered_total = sum(item["covered"] for item in by_matiere.values())
    total = sum(item["total"] for item in by_matiere.values())

    return {
        "total_notions": total,
        "covered_notions": covered_total,
        "uncovered_notions": total - covered_total,
        "by_matiere": {
            key: {
                "total": value["total"],
                "covered": value["covered"],
                "uncovered": sorted(value["uncovered"]),
            }
            for key, value in sorted(by_matiere.items())
        },
    }


def write_plan(path: Path, plan: dict[str, Any]) -> Path:
    resolved = _ensure_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(yaml.safe_dump(plan, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build deterministic acquisition plan for pilot Terminale."
    )
    parser.add_argument("--taxonomy", action="append", type=Path, default=[])
    parser.add_argument("--reference-dir", type=Path, default=DEFAULT_REFERENCE_DIR)
    parser.add_argument("--discovered-at", type=str, default="")
    parser.add_argument(
        "--output", type=Path, default=Path("data/acquisition/pilot_terminale_plan.yml")
    )
    args = parser.parse_args()

    taxonomy_paths = args.taxonomy if args.taxonomy else DEFAULT_TAXONOMY_PATHS
    discovered_at: datetime | None = None
    if args.discovered_at:
        discovered_at = datetime.fromisoformat(args.discovered_at)
        if discovered_at.tzinfo is None:
            discovered_at = discovered_at.replace(tzinfo=UTC)

    plan = build_discovery_plan(
        taxonomy_paths=taxonomy_paths,
        reference_dir=args.reference_dir,
        discovered_at=discovered_at,
    )
    write_plan(args.output, plan)
    coverage = compute_coverage(plan)
    print(f"plan écrit: {args.output}")
    print(f"notions totales: {coverage['total_notions']}")
    print(f"notions couvertes: {coverage['covered_notions']}")
    print(f"notions non couvertes: {coverage['uncovered_notions']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
