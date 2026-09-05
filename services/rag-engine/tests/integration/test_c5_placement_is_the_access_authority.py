"""C5 — l'autorité d'accès est le placement, jamais une colonne dénormalisée.

`rag_chunks` porte encore `visibility` et `audience` : des colonnes héritées,
peuplées à la publication et donc susceptibles d'être PÉRIMÉES. Si l'une
d'elles pouvait décider de ce qui est servi, l'autorité gouvernée cesserait
d'être une autorité — il suffirait d'une ligne non rafraîchie pour élargir la
portée d'un contenu.

L'autorité déclarée est `rag_artifact_placements`. Ces épreuves l'établissent
sur une base RÉELLE, en exerçant le prédicat que le moteur livre — jamais une
copie réécrite pour le test.
"""
from __future__ import annotations

import os
import uuid

import psycopg
import pytest

from ingestor.retrieval_pg_v2 import (
    _EFFECTIVE_SCOPE_FILTER_SQL,
    _GOVERNED_SCOPE_JOINS_SQL,
)

DSN = os.environ.get("NEXUS_C5_PG_DSN", "").strip()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DSN,
        reason=(
            "intégration gouvernée : exige NEXUS_C5_PG_DSN vers un PostgreSQL "
            "de qualification jetable — jamais la base servie"
        ),
    ),
]

SCOPE = {
    "collection": "rag_nexus_nsi_terminale_specialite",
    "tenant": "libre_terminale",
    "niveau": "terminale",
    "voie": None,
    "matiere": "nsi",
    "statut_enseignement": "specialite",
    "candidat": ["libre"],
    "audience": ["eleve"],
    "rights": ["officiel_public"],
    "visibility": ["public"],
    "school_year": "2026-2027",
    "programme_version": "BOEN-NSI-2026",
}

SCHEMA = """
CREATE TABLE rag_artifacts (
    artifact_id TEXT PRIMARY KEY,
    rights TEXT NOT NULL,
    source_label TEXT NOT NULL,
    source_uri TEXT NOT NULL
);
CREATE TABLE rag_chunks (
    chunk_id TEXT PRIMARY KEY,
    artifact_id TEXT,
    collection TEXT, tenant TEXT, niveau TEXT, voie TEXT, matiere TEXT,
    statut_enseignement TEXT, candidat TEXT,
    audience TEXT[] NOT NULL DEFAULT '{"tous"}',
    rights TEXT, visibility TEXT, school_year TEXT, programme_version TEXT,
    review_status TEXT NOT NULL DEFAULT 'reviewed'
);
CREATE TABLE rag_artifact_placements (
    placement_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    collection TEXT NOT NULL, tenant TEXT NOT NULL, niveau TEXT NOT NULL,
    voie TEXT, matiere TEXT NOT NULL, statut_enseignement TEXT NOT NULL,
    candidat TEXT NOT NULL,
    audience TEXT[] NOT NULL, visibility TEXT NOT NULL,
    school_year TEXT NOT NULL, programme_version TEXT NOT NULL,
    placement_status TEXT NOT NULL, currentness TEXT NOT NULL,
    review_status TEXT NOT NULL, source_scope TEXT, source_placement_id TEXT,
    source_path TEXT, source_uri TEXT
);
"""


def _scope_params() -> tuple[object, ...]:
    """Les paramètres du prédicat livré, dans son ordre exact."""
    placement = (
        SCOPE["collection"], SCOPE["tenant"], SCOPE["niveau"], SCOPE["voie"],
        SCOPE["matiere"], SCOPE["statut_enseignement"], SCOPE["candidat"],
        SCOPE["audience"], SCOPE["visibility"], SCOPE["school_year"],
        SCOPE["programme_version"],
    )
    legacy = (
        SCOPE["collection"], SCOPE["tenant"], SCOPE["niveau"], SCOPE["voie"],
        SCOPE["matiere"], SCOPE["statut_enseignement"], SCOPE["candidat"],
        SCOPE["audience"], SCOPE["rights"], SCOPE["visibility"],
        SCOPE["school_year"], SCOPE["programme_version"],
    )
    return placement + legacy + (SCOPE["rights"],)


GOVERNED_SQL = f"""
    SELECT chunk.chunk_id
    FROM public.rag_chunks AS chunk
    {_GOVERNED_SCOPE_JOINS_SQL}
    WHERE {_EFFECTIVE_SCOPE_FILTER_SQL}
"""


@pytest.fixture
def governed(request):
    """Base jetable, schéma minimal, un chunk lié à un artefact et son placement."""
    name = f"c5_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    dsn = psycopg.conninfo.make_conninfo(DSN, dbname=name)
    conn = psycopg.connect(dsn, autocommit=True)

    def drop() -> None:
        conn.close()
        with psycopg.connect(DSN, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')

    request.addfinalizer(drop)
    conn.execute(SCHEMA)
    conn.execute(
        "INSERT INTO rag_artifacts VALUES ('art-1','officiel_public','Eduscol','https://x/1')"
    )
    conn.execute(
        "INSERT INTO rag_chunks (chunk_id, artifact_id, collection, tenant, niveau,"
        " voie, matiere, statut_enseignement, candidat, audience, rights, visibility,"
        " school_year, programme_version)"
        " VALUES ('chunk-1','art-1',%s,%s,%s,%s,%s,%s,'libre',%s,'officiel_public',"
        " 'public',%s,%s)",
        (SCOPE["collection"], SCOPE["tenant"], SCOPE["niveau"], SCOPE["voie"],
         SCOPE["matiere"], SCOPE["statut_enseignement"], SCOPE["audience"],
         SCOPE["school_year"], SCOPE["programme_version"]),
    )
    conn.execute(
        "INSERT INTO rag_artifact_placements VALUES ('pl-1','art-1',%s,%s,%s,%s,%s,%s,"
        " 'libre',%s,'public',%s,%s,'active','current','reviewed','s','sp','p','https://x/1')",
        (SCOPE["collection"], SCOPE["tenant"], SCOPE["niveau"], SCOPE["voie"],
         SCOPE["matiere"], SCOPE["statut_enseignement"], SCOPE["audience"],
         SCOPE["school_year"], SCOPE["programme_version"]),
    )
    return conn


def _served(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(GOVERNED_SQL, _scope_params())
        return [row[0] for row in cur.fetchall()]


def test_the_nominal_placement_serves_the_chunk(governed) -> None:
    """Contrôle positif : sans lui, un refus ne prouverait rien."""
    assert _served(governed) == ["chunk-1"]


def test_altering_the_placement_authority_changes_what_is_served(governed) -> None:
    """L'autorité DÉCIDE : la restreindre retire le contenu."""
    governed.execute("UPDATE rag_artifact_placements SET visibility = 'restricted'")
    assert _served(governed) == []


def test_a_stale_chunk_visibility_cannot_widen_the_authority(governed) -> None:
    """Le sabotage qui compte.

    La colonne dénormalisée annonce `public` — élargissante — tandis que
    l'autorité dit `restricted`. Si la colonne pouvait décider, une ligne
    simplement non rafraîchie suffirait à servir un contenu que personne n'a
    autorisé."""
    governed.execute("UPDATE rag_artifact_placements SET visibility = 'restricted'")
    governed.execute("UPDATE rag_chunks SET visibility = 'public', audience = %s",
                     (SCOPE["audience"],))
    assert _served(governed) == [], (
        "une colonne dénormalisée a outrepassé l'autorité de placement"
    )


def test_a_stale_chunk_audience_cannot_widen_the_authority(governed) -> None:
    governed.execute("UPDATE rag_artifact_placements SET audience = ARRAY['enseignant']")
    governed.execute("UPDATE rag_chunks SET audience = ARRAY['eleve','enseignant']")
    assert _served(governed) == []


def test_a_restrictive_chunk_column_does_not_hide_an_authorised_placement(governed) -> None:
    """Le sens inverse : la colonne ne RESTREINT pas davantage non plus.

    Une autorité que l'on peut contredire dans un sens comme dans l'autre n'est
    pas une autorité. Le placement autorise, donc le contenu est servi."""
    governed.execute("UPDATE rag_chunks SET visibility = 'restricted', audience = ARRAY['aucun']")
    assert _served(governed) == ["chunk-1"]


def test_an_inactive_placement_stops_serving(governed) -> None:
    governed.execute("UPDATE rag_artifact_placements SET placement_status = 'retired'")
    assert _served(governed) == []


def test_a_stale_placement_stops_serving(governed) -> None:
    governed.execute("UPDATE rag_artifact_placements SET currentness = 'stale'")
    assert _served(governed) == []


def test_deleting_the_placement_stops_serving(governed) -> None:
    """Sans autorité, rien n'est servi — jamais un repli sur la colonne."""
    governed.execute("DELETE FROM rag_artifact_placements")
    governed.execute("UPDATE rag_chunks SET visibility = 'public'")
    assert _served(governed) == []
