"""C6 — un filtre de métadonnée RESTREINT, il n'AUTORISE jamais.

C5 a établi que l'autorité d'accès est `rag_artifact_placements` : les dix
dimensions de placement décident seules de ce qui est servi. Les dimensions
pédagogiques `notion`, `chapitre`, `type_document` vivent, elles, sur les
métadonnées de chunk (`ChunkMetadata`) — elles ne sont pas une autorité.

D'où l'invariant que ces épreuves scellent :

    servi  ⟺  AUTORISÉ_PAR_PLACEMENT **ET** CORRESPOND_AUX_MÉTADONNÉES

Jamais un OU. Une notion qui « correspond » ne peut pas rendre visible un
contenu que son placement interdit ; un placement qui autorise ne dispense
pas de correspondre au filtre demandé.

Les trois sabotages tournent sur un PostgreSQL RÉEL et jetable, portant le
schéma issu des vraies migrations livrées, et exercent le VRAI magasin de
candidats (`PgCandidateStore`) — pas une requête réécrite pour le test, qui
pourrait diverger de celle que le moteur envoie.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from nexus_contracts import Rights

from ingestor.retrieval_metadata_v2 import ChunkMetadataFilters
from ingestor.retrieval_pg_v2 import PgCandidateStore
from ingestor.retrieval_scope_v2 import ServerRetrievalScope
from tests.integration._pg_authority import (
    requires_docker,
    start_rag_retrieval_postgres,
)

pytestmark = [pytest.mark.integration, requires_docker]

COLLECTION = "rag_nexus_nsi_terminale_specialite"
TENANT = "libre_terminale"
SCHOOL_YEAR = "2026-2027"
PROGRAMME_VERSION = "BOEN-NSI-2026"

#: Identités gouvernées : `artifact_id = content_sha256 = doc_id`, et les
#: deux identifiants sont des sha256 — la contrainte est celle de la
#: migration 004, pas une convention de test.
ARTIFACT_ID = hashlib.sha256(b"c6-artifact").hexdigest()
PLACEMENT_ID = hashlib.sha256(b"c6-placement").hexdigest()
CHUNK_ID = "c6-chunk-1"

#: La requête lexicale doit réellement matcher `text_tsv`.
QUERY = "recursivite"
CHUNK_TEXT = "La recursivite permet de definir une fonction par elle-meme."

NOTION_DU_CHUNK = "recursivite"
NOTION_ABSENTE = "graphes"

VECTOR = "[" + ",".join(["0.01"] * 1024) + "]"


SCOPE = ServerRetrievalScope(
    tenant=TENANT,
    niveau="terminale",
    voie="generale",
    matiere="nsi",
    statut_enseignement="specialite",
    candidat="libre",
    audiences=("eleve",),
    rights=(Rights.officiel_public,),
    visibilities=("public",),
    school_year=SCHOOL_YEAR,
    collection=COLLECTION,
    programme_version=PROGRAMME_VERSION,
    scope_id="c6-scope",
    scope_digest="c6-digest",
    source_sha256=hashlib.sha256(b"c6-source").hexdigest(),
)


@pytest.fixture(scope="module")
def retrieval_pg() -> Iterator[dict[str, str]]:
    yield from start_rag_retrieval_postgres("c6-metadata")


@pytest.fixture
def seeded(retrieval_pg: dict[str, str]) -> Iterator[psycopg.Connection]:
    """Un artefact, son placement nominal, un chunk portant une notion."""
    with psycopg.connect(retrieval_pg["dsn"], autocommit=True) as connection:
        connection.execute("TRUNCATE public.rag_chunks, public.rag_artifact_placements, public.rag_artifacts")
        connection.execute(
            "INSERT INTO public.rag_artifacts (artifact_id, content_sha256, source_label,"
            " source_uri, rights, official, source_kind, type_doc, ingestion_artifact_id)"
            " VALUES (%s, %s, 'Eduscol', 'https://eduscol.education.fr/c6',"
            " 'officiel_public', true, 'officiel', 'cours', gen_random_uuid())",
            (ARTIFACT_ID, ARTIFACT_ID),
        )
        connection.execute(
            "INSERT INTO public.rag_artifact_placements (placement_id, artifact_id,"
            " collection, tenant, niveau, voie, audience, matiere, statut_enseignement,"
            " candidat, visibility, school_year, programme_version, currentness,"
            " placement_status, review_status, source_scope, source_placement_id,"
            " source_path, source_uri, authorization_id, publication_attestation_id)"
            " VALUES (%s, %s, %s, %s, 'terminale', 'generale', ARRAY['eleve'], 'nsi',"
            " 'specialite', 'libre', 'public', %s, %s, 'current', 'active', 'reviewed',"
            " 'corpus', 'sp-1', 'corpus/nsi/c6.pdf', 'https://eduscol.education.fr/c6',"
            " 'auth-c6', gen_random_uuid())",
            (PLACEMENT_ID, ARTIFACT_ID, COLLECTION, TENANT, SCHOOL_YEAR, PROGRAMME_VERSION),
        )
        connection.execute(
            "INSERT INTO public.rag_chunks (chunk_id, doc_id, chunk_sha256, vector,"
            " collection, niveau, voie, audience, matiere, statut_enseignement, notions,"
            " source_label, source_uri, rights, type_doc, official, text, chunk_index,"
            " review_status, tenant, candidat, visibility, school_year,"
            " programme_version, artifact_id)"
            " VALUES (%s, %s, %s, %s::vector, %s, 'terminale', 'generale', ARRAY['eleve'],"
            " 'nsi', 'specialite', %s, 'Eduscol', 'https://eduscol.education.fr/c6',"
            " 'officiel_public', 'cours', true, %s, 0, 'reviewed', %s, 'libre', 'public',"
            " %s, %s, %s)",
            (
                CHUNK_ID, ARTIFACT_ID, hashlib.sha256(b"c6-chunk").hexdigest(), VECTOR,
                COLLECTION, [NOTION_DU_CHUNK], CHUNK_TEXT, TENANT, SCHOOL_YEAR,
                PROGRAMME_VERSION, ARTIFACT_ID,
            ),
        )
        yield connection


def _served(
    connection: psycopg.Connection,
    *,
    metadata: ChunkMetadataFilters | None = None,
) -> list[str]:
    """Ce que le VRAI magasin de candidats livré rend, canal lexical."""

    @contextmanager
    def provider() -> Iterator[psycopg.Connection]:
        yield connection

    store = PgCandidateStore(provider, SCOPE, metadata_filters=metadata)
    candidates = store.lexical(raw_query=QUERY, collection=COLLECTION, limit=10)
    return [candidate.chunk_id for candidate in candidates]


def test_le_placement_nominal_sert_le_chunk_sans_filtre(seeded: psycopg.Connection) -> None:
    """Contrôle positif : sans lui, les trois refus ne prouveraient rien."""
    assert _served(seeded) == [CHUNK_ID]


def test_placement_refuse_et_notion_correspond_ne_sert_rien(
    seeded: psycopg.Connection,
) -> None:
    """Sabotage 1 — le filtre de métadonnée n'AUTORISE pas.

    La notion demandée est exactement celle du chunk : si la sélection était
    un OU, cette correspondance suffirait à servir un contenu dont le
    placement vient d'être restreint. Elle ne doit rien servir."""
    seeded.execute("UPDATE public.rag_artifact_placements SET visibility = 'restricted'")
    assert _served(seeded, metadata=ChunkMetadataFilters(notions=(NOTION_DU_CHUNK,))) == [], (
        "une notion correspondante a outrepassé un placement qui refuse"
    )


def test_placement_autorise_et_notion_ne_correspond_pas_ne_sert_rien(
    seeded: psycopg.Connection,
) -> None:
    """Sabotage 2 — le filtre de métadonnée RESTREINT réellement.

    Le placement autorise ; la notion demandée est absente du chunk. Un
    filtre décoratif, non poussé jusqu'au SQL, servirait quand même."""
    assert _served(seeded, metadata=ChunkMetadataFilters(notions=(NOTION_ABSENTE,))) == [], (
        "le filtre de notion n'a pas restreint un placement autorisé"
    )


def test_placement_autorise_et_notion_correspond_sert_le_chunk(
    seeded: psycopg.Connection,
) -> None:
    """Sabotage 3 — la conjonction ne ferme pas tout par excès de zèle.

    Les deux conditions sont réunies : le contenu doit être servi. Sans ce
    cas, un filtre qui refuserait systématiquement passerait les deux
    précédents."""
    assert _served(seeded, metadata=ChunkMetadataFilters(notions=(NOTION_DU_CHUNK,))) == [
        CHUNK_ID
    ]


def test_une_notion_correspondante_ne_ressuscite_pas_un_placement_retire(
    seeded: psycopg.Connection,
) -> None:
    """Toutes les façons de refuser un placement résistent au filtre."""
    seeded.execute("UPDATE public.rag_artifact_placements SET placement_status = 'disabled'")
    assert _served(seeded, metadata=ChunkMetadataFilters(notions=(NOTION_DU_CHUNK,))) == []
    seeded.execute(
        "UPDATE public.rag_artifact_placements"
        " SET placement_status = 'active', currentness = 'archive'"
    )
    assert _served(seeded, metadata=ChunkMetadataFilters(notions=(NOTION_DU_CHUNK,))) == []
    seeded.execute("DELETE FROM public.rag_artifact_placements")
    assert _served(seeded, metadata=ChunkMetadataFilters(notions=(NOTION_DU_CHUNK,))) == []
