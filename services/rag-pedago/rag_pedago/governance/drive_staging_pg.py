"""Magasin de staging du plan de contrôle, sur PostgreSQL.

**Ce n'est pas pgvector.** Le plan de données appartient à
``rag-engine`` et n'est atteignable qu'après ``quality → gate → review``
et une attestation humaine. Ici vit l'antichambre : ce que Drive a
livré, prouvé et classé, en attente de cette revue. Rien de ce qui est
écrit ici n'est servi en retrieval, et le schéma le dit — le statut de
revue a une valeur par défaut, et cette valeur est ``needs_review``.

**L'identité est portée par le schéma, pas par l'appelant.** Un artefact
est son empreinte de contenu : la contrainte l'exige, plutôt que de faire
confiance à un identifiant fourni. Deux exécutions sur les mêmes octets
tombent donc sur la même clé primaire, et l'``ON CONFLICT DO NOTHING``
rend l'idempotence mesurable au lieu de l'espérer : ``rowcount`` dit si
la ligne était nouvelle.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from rag_pedago.governance.drive_slice import (
    StagedArtifact,
    StagedChunk,
    StagedProvenance,
    StagingStore,
)
from rag_pedago.governance.drive_source import DriveSourceError

#: DSN du staging du plan de contrôle. Jamais de valeur par défaut : une
#: base devinée est une base dans laquelle on écrit sans savoir laquelle.
STAGING_DSN_ENV = "NEXUS_PEDAGO_STAGING_DSN"

SCHEMA = "drive_staging"

DDL = """
CREATE SCHEMA IF NOT EXISTS drive_staging;

CREATE TABLE IF NOT EXISTS drive_staging.artifacts (
    artifact_id     text PRIMARY KEY
                    CHECK (artifact_id ~ '^[0-9a-f]{64}$'),
    content_sha256  text NOT NULL UNIQUE
                    CHECK (artifact_id = content_sha256),
    source_kind     text NOT NULL,
    mime_type       text NOT NULL,
    size_bytes      bigint NOT NULL CHECK (size_bytes >= 0),
    modified_time   text NOT NULL,
    zone            text NOT NULL,
    cycle           text,
    niveau          text,
    matiere         text,
    nature          text,
    millesime       text,
    servable        boolean NOT NULL,
    review_status   text NOT NULL DEFAULT 'needs_review'
                    CHECK (review_status = 'needs_review'),
    first_seen_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS drive_staging.provenances (
    artifact_id     text NOT NULL
                    REFERENCES drive_staging.artifacts (artifact_id),
    relative_path   text NOT NULL,
    source_id       text NOT NULL,
    source_kind     text NOT NULL,
    drive_file_id   text NOT NULL,
    drive_path      text NOT NULL,
    shortcut_id     text,
    PRIMARY KEY (artifact_id, relative_path)
);

CREATE TABLE IF NOT EXISTS drive_staging.chunks (
    chunk_id        text PRIMARY KEY
                    CHECK (chunk_id ~ '^[0-9a-f]{64}$'),
    artifact_id     text NOT NULL
                    REFERENCES drive_staging.artifacts (artifact_id),
    chunk_index     integer NOT NULL CHECK (chunk_index >= 0),
    chunk_sha256    text NOT NULL,
    page_start      integer NOT NULL,
    page_end        integer NOT NULL,
    text            text NOT NULL CHECK (length(btrim(text)) > 0),
    UNIQUE (artifact_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_drive_staging_chunks_artifact
    ON drive_staging.chunks (artifact_id);
"""


def staging_dsn() -> str:
    raw = os.environ.get(STAGING_DSN_ENV)
    if not raw:
        raise DriveSourceError(
            f"{STAGING_DSN_ENV} n'est pas défini — refus d'écrire dans une base "
            "qu'on ne saurait pas nommer dans une preuve"
        )
    return raw


@dataclass
class PostgresStagingStore(StagingStore):
    """``StagingStore`` adossé à une connexion psycopg ouverte."""

    connection: Any

    def create_schema(self) -> None:
        with self.connection.cursor() as cursor:
            cursor.execute(DDL)
        self.connection.commit()

    def upsert_artifact(self, artifact: StagedArtifact) -> bool:
        placement = artifact.placement
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO drive_staging.artifacts (
                    artifact_id, content_sha256, source_kind, mime_type,
                    size_bytes, modified_time, zone, cycle, niveau, matiere,
                    nature, millesime, servable, review_status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (artifact_id) DO NOTHING
                """,
                (
                    artifact.artifact_id,
                    artifact.content_sha256,
                    artifact.source_kind,
                    artifact.mime_type,
                    artifact.size_bytes,
                    artifact.modified_time,
                    placement.zone,
                    placement.cycle,
                    placement.niveau,
                    placement.matiere,
                    placement.nature,
                    placement.millesime,
                    placement.servable,
                    artifact.review_status,
                ),
            )
            return bool(cursor.rowcount)

    def upsert_provenance(self, provenance: StagedProvenance) -> bool:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO drive_staging.provenances (
                    artifact_id, relative_path, source_id, source_kind,
                    drive_file_id, drive_path, shortcut_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (artifact_id, relative_path) DO NOTHING
                """,
                (
                    provenance.artifact_id,
                    provenance.relative_path,
                    provenance.source_id,
                    "GOOGLE_DRIVE",
                    provenance.drive_file_id,
                    provenance.drive_path,
                    provenance.shortcut_id,
                ),
            )
            return bool(cursor.rowcount)

    def upsert_chunk(self, chunk: StagedChunk) -> bool:
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO drive_staging.chunks (
                    chunk_id, artifact_id, chunk_index, chunk_sha256,
                    page_start, page_end, text
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (chunk_id) DO NOTHING
                """,
                (
                    chunk.chunk_id,
                    chunk.artifact_id,
                    chunk.chunk_index,
                    chunk.chunk_sha256,
                    chunk.page_start,
                    chunk.page_end,
                    chunk.text,
                ),
            )
            return bool(cursor.rowcount)

    def query(
        self,
        *,
        matiere: str | None = None,
        niveau: str | None = None,
        motif: str | None = None,
        limit: int = 20,
    ) -> list[tuple[Any, ...]]:
        """Interroge le staging par placement et par motif textuel."""
        with self.connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.chunk_id, c.chunk_index, c.page_start, a.matiere,
                       a.niveau, a.nature, a.review_status,
                       substring(c.text from 1 for 160)
                  FROM drive_staging.chunks c
                  JOIN drive_staging.artifacts a USING (artifact_id)
                 WHERE (%s::text IS NULL OR a.matiere = %s::text)
                   AND (%s::text IS NULL OR a.niveau = %s::text)
                   AND (%s::text IS NULL OR c.text ILIKE '%%' || %s::text || '%%')
                 ORDER BY c.chunk_index
                 LIMIT %s
                """,
                (matiere, matiere, niveau, niveau, motif, motif, limit),
            )
            return list(cursor.fetchall())


__all__ = ["DDL", "SCHEMA", "STAGING_DSN_ENV", "PostgresStagingStore", "staging_dsn"]
