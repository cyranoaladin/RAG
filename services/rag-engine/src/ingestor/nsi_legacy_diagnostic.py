"""Diagnostic strictement read-only des lignes NSI historiques."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

NSI_COLLECTIONS = (
    "rag_nexus_nsi_premiere_specialite",
    "rag_nexus_nsi_terminale_specialite",
)


@dataclass(frozen=True)
class NsiLegacyDiagnostic:
    collection: str
    total_existing_rows: int
    governed_release_rows: int
    legacy_rows: int
    model_values: tuple[str, ...]
    review_status_values: tuple[str, ...]
    programme_values: tuple[str, ...]
    legacy_certified_as_governed: bool = False


def _values(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list | tuple):
        raise ValueError("NSI diagnostic aggregate is malformed")
    return tuple(sorted(str(value) for value in raw if value is not None))


def inspect_nsi_legacy_rows(conn: Any) -> tuple[NsiLegacyDiagnostic, ...]:
    """Mesurer le legacy sans écrire ni lui attribuer une gouvernance rétroactive."""
    column_row = conn.execute(
        """
        SELECT COALESCE(BOOL_OR(column_name = 'artifact_id'), false),
               COALESCE(BOOL_OR(column_name = 'model'), false),
               COALESCE(BOOL_OR(column_name = 'review_status'), false),
               COALESCE(BOOL_OR(column_name = 'programme_version'), false)
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'rag_chunks'
        """
    ).fetchone()
    if column_row is None or len(column_row) != 4:
        raise ValueError("NSI diagnostic could not inspect rag_chunks schema")
    has_artifact_id, has_model, has_review_status, has_programme_version = (
        value is True for value in column_row
    )

    def aggregate(column: str, *, available: bool) -> str:
        if not available:
            return "NULL::text[]"
        return (
            f"ARRAY_AGG(DISTINCT {column} ORDER BY {column}) "
            f"FILTER (WHERE {column} IS NOT NULL)"
        )

    model_aggregate = aggregate("model", available=has_model)
    review_aggregate = aggregate("review_status", available=has_review_status)
    programme_aggregate = aggregate("programme_version", available=has_programme_version)

    diagnostics: list[NsiLegacyDiagnostic] = []
    for collection in NSI_COLLECTIONS:
        if has_artifact_id:
            row = conn.execute(
                f"""
                SELECT COUNT(*)::bigint,
                       COUNT(*) FILTER (WHERE artifact_id IS NOT NULL)::bigint,
                       COUNT(*) FILTER (WHERE artifact_id IS NULL)::bigint,
                       {model_aggregate},
                       {review_aggregate},
                       {programme_aggregate}
                FROM public.rag_chunks
                WHERE collection = %s
                """,
                (collection,),
            ).fetchone()
            if row is None:
                raise ValueError("NSI diagnostic query returned no row")
            total, governed, legacy, models, reviews, programmes = row
        else:
            row = conn.execute(
                f"""
                SELECT COUNT(*)::bigint,
                       {model_aggregate},
                       {review_aggregate},
                       {programme_aggregate}
                FROM public.rag_chunks
                WHERE collection = %s
                """,
                (collection,),
            ).fetchone()
            if row is None:
                raise ValueError("NSI diagnostic query returned no row")
            total, models, reviews, programmes = row
            governed = 0
            legacy = total

        total_count = int(total)
        governed_count = int(governed)
        legacy_count = int(legacy)
        if total_count != governed_count + legacy_count:
            raise ValueError("NSI legacy partition is incomplete")
        diagnostics.append(
            NsiLegacyDiagnostic(
                collection=collection,
                total_existing_rows=total_count,
                governed_release_rows=governed_count,
                legacy_rows=legacy_count,
                model_values=_values(models),
                review_status_values=_values(reviews),
                programme_values=_values(programmes),
            )
        )
    return tuple(diagnostics)


__all__ = ["NSI_COLLECTIONS", "NsiLegacyDiagnostic", "inspect_nsi_legacy_rows"]
