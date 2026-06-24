from __future__ import annotations

import json
from collections import Counter
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from schema.document import DocumentMeta
from schema.taxonomy import TaxonomySpec


class CoverageStatus(str, Enum):
    ok = "coverage_ok"
    partial = "coverage_partial"
    insufficient = "coverage_insufficient"


class CoverageReport(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    batch_id: str
    status: CoverageStatus
    manifest_count: int
    documents_valid: int
    by_matiere: dict[str, int]
    by_niveau: dict[str, int]
    by_type_doc: dict[str, int]
    by_candidat: dict[str, int]
    notions_declared: list[str]
    notions_unknown: list[str]
    notions_known: list[str]
    missing_priority_notions: list[str]
    taxonomy_ids_used: list[str]
    recommended_actions: list[str] = Field(default_factory=list)
    markdown_path: Path
    json_path: Path


def _manifest_paths(directory_path: Path) -> list[Path]:
    paths = sorted(path for path in directory_path.iterdir() if path.suffix == ".jsonl")
    if not paths:
        raise ValueError(f"no JSONL manifests found: {directory_path}")
    return paths


def _load_taxonomies(taxonomy_paths: list[Path]) -> list[TaxonomySpec]:
    taxonomies: list[TaxonomySpec] = []
    for path in taxonomy_paths:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        taxonomies.append(TaxonomySpec.model_validate(payload))
    return taxonomies


def _read_valid_metas(manifest_paths: list[Path]) -> list[DocumentMeta]:
    metas: list[DocumentMeta] = []
    for manifest_path in manifest_paths:
        with manifest_path.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    metas.append(DocumentMeta.model_validate(json.loads(raw_line)))
                except Exception:
                    continue
    return metas


def _counter_dict(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _recommended_actions(
    *,
    status: CoverageStatus,
    notions_unknown: list[str],
    missing_priority_notions: list[str],
    documents_valid: int,
    notions_declared: list[str],
) -> list[str]:
    actions: list[str] = []
    if documents_valid == 0:
        actions.append("Ajouter au moins un document valide dans les manifests.")
    if documents_valid > 0 and not notions_declared:
        actions.append("Renseigner les notions dans les métadonnées des documents.")
    if notions_unknown:
        actions.append("Aligner les notions inconnues avec les taxonomies contrôlées.")
    if missing_priority_notions:
        actions.append("Ajouter des documents couvrant les notions prioritaires manquantes.")
    if status is CoverageStatus.ok:
        actions.append("Couverture déclarative suffisante pour une revue humaine pré-ingestion.")
    return actions


def _status(
    *,
    documents_valid: int,
    notions_declared: list[str],
    notions_unknown: list[str],
    missing_priority_notions: list[str],
) -> CoverageStatus:
    if documents_valid == 0 or not notions_declared:
        return CoverageStatus.insufficient
    if notions_unknown or missing_priority_notions:
        return CoverageStatus.partial
    return CoverageStatus.ok


def _write_markdown_report(report: CoverageReport, known_notion_count: int) -> None:
    report.markdown_path.parent.mkdir(parents=True, exist_ok=True)

    def bullet(values: list[str]) -> str:
        return "\n".join(f"- {value}" for value in values) or "- none"

    def count_lines(values: dict[str, int]) -> str:
        return "\n".join(f"- {key}: {value}" for key, value in values.items()) or "- none"

    actions = bullet(report.recommended_actions)
    content = f"""# Coverage Report — {report.batch_id}

## Decision

Status: {report.status.value}

## Executive summary

The batch contains {report.documents_valid} valid manifest document(s), {len(report.notions_declared)} declared notion(s), and {known_notion_count} known notion(s) loaded from controlled taxonomies.

## Counts by matière

{count_lines(report.by_matiere)}

## Counts by niveau

{count_lines(report.by_niveau)}

## Counts by type_doc

{count_lines(report.by_type_doc)}

## Counts by candidat

{count_lines(report.by_candidat)}

## Taxonomies used

{bullet(report.taxonomy_ids_used)}

## Known notions found

{bullet(report.notions_known)}

## Unknown notions

{bullet(report.notions_unknown)}

## Missing priority notions

{bullet(report.missing_priority_notions)}

## Recommended actions

{actions}

## Guarantees

- No source_uri was opened.
- No network call was made.
- No document ingestion was performed.
"""
    report.markdown_path.write_text(content, encoding="utf-8")


def _write_json_report(report: CoverageReport, known_notion_count: int) -> None:
    report.json_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "batch_id": report.batch_id,
        "status": report.status.value,
        "manifest_count": report.manifest_count,
        "documents_valid": report.documents_valid,
        "by_matiere": report.by_matiere,
        "by_niveau": report.by_niveau,
        "by_type_doc": report.by_type_doc,
        "by_candidat": report.by_candidat,
        "notions_declared": report.notions_declared,
        "notions_unknown": report.notions_unknown,
        "notions_known": report.notions_known,
        "missing_priority_notions": report.missing_priority_notions,
        "taxonomy_ids_used": report.taxonomy_ids_used,
        "known_notion_count": known_notion_count,
        "recommended_actions": report.recommended_actions,
        "guarantees": {
            "no_source_uri_opened": True,
            "no_network_call": True,
            "no_document_ingestion": True,
        },
    }
    report.json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_coverage_report(
    directory_path: Path,
    batch_id: str,
    taxonomy_paths: list[Path],
    priority_notions: list[str] | None = None,
    output_dir: Path = Path("data/reports"),
) -> CoverageReport:
    manifest_paths = _manifest_paths(directory_path)
    taxonomies = _load_taxonomies(taxonomy_paths)
    metas = _read_valid_metas(manifest_paths)

    known_notion_ids = set().union(*(taxonomy.known_notion_ids for taxonomy in taxonomies))
    notions_declared = sorted({notion for meta in metas for notion in meta.notions})
    notions_known = sorted(notion for notion in notions_declared if notion in known_notion_ids)
    notions_unknown = sorted(notion for notion in notions_declared if notion not in known_notion_ids)
    priorities = priority_notions or []
    missing_priority_notions = sorted(notion for notion in priorities if notion not in notions_declared)
    status = _status(
        documents_valid=len(metas),
        notions_declared=notions_declared,
        notions_unknown=notions_unknown,
        missing_priority_notions=missing_priority_notions,
    )

    report = CoverageReport(
        batch_id=batch_id,
        status=status,
        manifest_count=len(manifest_paths),
        documents_valid=len(metas),
        by_matiere=_counter_dict([meta.matiere for meta in metas]),
        by_niveau=_counter_dict([meta.niveau.value for meta in metas if meta.niveau is not None]),
        by_type_doc=_counter_dict([meta.type_doc.value for meta in metas]),
        by_candidat=_counter_dict([meta.candidat.value for meta in metas]),
        notions_declared=notions_declared,
        notions_unknown=notions_unknown,
        notions_known=notions_known,
        missing_priority_notions=missing_priority_notions,
        taxonomy_ids_used=[taxonomy.id for taxonomy in taxonomies],
        recommended_actions=_recommended_actions(
            status=status,
            notions_unknown=notions_unknown,
            missing_priority_notions=missing_priority_notions,
            documents_valid=len(metas),
            notions_declared=notions_declared,
        ),
        markdown_path=output_dir / f"coverage_{batch_id}.md",
        json_path=output_dir / f"coverage_{batch_id}.json",
    )
    _write_markdown_report(report, len(known_notion_ids))
    _write_json_report(report, len(known_notion_ids))
    return report
