"""La sonde DI juge les candidats par l'autorité de placement, sur PG jetable."""

from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from nexus_contracts import Rights

from ingestor.retrieval_pg_v2 import PgCandidateStore
from ingestor.retrieval_scope_v2 import ServerRetrievalScope
from tests.integration._pg_authority import requires_docker, start_rag_retrieval_postgres

pytestmark = [pytest.mark.integration, requires_docker]

ROOT = Path(__file__).resolve().parents[4]
SPEC = importlib.util.spec_from_file_location(
    "staging_retrieval_probe", ROOT / "scripts/go_live/staging_retrieval_probe.py"
)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)

A = "rag_nexus_hlp_premiere_specialite"
B = "rag_nexus_hlp_terminale_specialite"
ARTIFACT = hashlib.sha256(b"di-shared-artifact").hexdigest()
CHUNK = hashlib.sha256(b"di-shared-chunk").hexdigest()
PLACEMENT_A = hashlib.sha256(b"di-placement-a").hexdigest()
PLACEMENT_B = hashlib.sha256(b"di-placement-b").hexdigest()
VECTOR = "[" + ",".join(["0.01"] * 1024) + "]"
TEXT = "La littérature et la philosophie interprètent ensemble cette question importante."

SCOPE_A = ServerRetrievalScope(
    tenant="libre_premiere", niveau="premiere", voie="generale", matiere="hlp",
    statut_enseignement="specialite", candidat="libre", audiences=("libre", "tous"),
    rights=(Rights.officiel_public,), visibilities=("internal",),
    school_year="2026-2027", collection=A,
    programme_version="BOEN_special_1_2019-01-22",
    scope_id="di-hlp-premiere", scope_digest="di-digest",
    source_sha256=hashlib.sha256(b"di-source").hexdigest(),
)


@pytest.fixture(scope="module")
def postgres() -> Iterator[dict[str, str]]:
    yield from start_rag_retrieval_postgres("di-probe")


@pytest.fixture
def base(postgres: dict[str, str]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(postgres["dsn"], autocommit=True) as conn:
        conn.execute("TRUNCATE public.rag_chunks, public.rag_artifact_placements, public.rag_artifacts")
        conn.execute(
            "INSERT INTO public.rag_artifacts (artifact_id, content_sha256, source_label,"
            " source_uri, rights, official, source_kind, type_doc, ingestion_artifact_id)"
            " VALUES (%s, %s, 'Eduscol', 'https://eduscol.education.fr/di',"
            " 'officiel_public', true, 'officiel', 'cours', gen_random_uuid())",
            (ARTIFACT, ARTIFACT),
        )
        yield conn


def _placement(conn: psycopg.Connection, *, collection: str, placement_id: str) -> None:
    niveau = "premiere" if collection == A else "terminale"
    tenant = f"libre_{niveau}"
    programme = "BOEN_special_1_2019-01-22" if collection == A else "BOEN_special_8_2019-07-25"
    conn.execute(
        "INSERT INTO public.rag_artifact_placements (placement_id, artifact_id,"
        " collection, tenant, niveau, voie, audience, matiere, statut_enseignement,"
        " candidat, visibility, school_year, programme_version, currentness,"
        " placement_status, review_status, source_scope, source_placement_id,"
        " source_path, source_uri, authorization_id, publication_attestation_id)"
        " VALUES (%s, %s, %s, %s, %s, 'generale', ARRAY['libre','tous'], 'hlp',"
        " 'specialite', 'libre', 'internal', '2026-2027', %s,"
        " 'official_snapshot', 'active', 'reviewed', 'corpus', %s, 'corpus/hlp/di.pdf',"
        " 'https://eduscol.education.fr/di', 'auth-di', gen_random_uuid())",
        (placement_id, ARTIFACT, collection, tenant, niveau, programme, placement_id),
    )


def _chunk(conn: psycopg.Connection, *, collection: str, artifact_id: str | None = ARTIFACT) -> None:
    niveau = "premiere" if collection == A else "terminale"
    programme = "BOEN_special_1_2019-01-22" if collection == A else "BOEN_special_8_2019-07-25"
    conn.execute(
        "INSERT INTO public.rag_chunks (chunk_id, doc_id, chunk_sha256, vector,"
        " collection, niveau, voie, audience, matiere, statut_enseignement, notions,"
        " source_label, source_uri, rights, type_doc, official, text, chunk_index,"
        " review_status, tenant, candidat, visibility, school_year,"
        " programme_version, artifact_id)"
        " VALUES (%s, %s, %s, %s::vector, %s, %s, 'generale', ARRAY['libre','tous'],"
        " 'hlp', 'specialite', ARRAY['litterature'], 'Eduscol',"
        " 'https://eduscol.education.fr/di', 'officiel_public', 'cours', true,"
        " %s, 0, 'reviewed', %s, 'libre', 'internal', '2026-2027',"
        " %s, %s)",
        (CHUNK, ARTIFACT, hashlib.sha256(b"di-chunk-content").hexdigest(), VECTOR,
         collection, niveau, TEXT, f"libre_{niveau}", programme, artifact_id),
    )


def _jeu(conn: psycopg.Connection):
    return probe.jeu_publie(conn, SCOPE_A)


def _candidat(*, placement_id: str | None = PLACEMENT_A, artifact_id: str | None = ARTIFACT):
    return SimpleNamespace(chunk_id=CHUNK, artifact_id=artifact_id, placement_id=placement_id)


def test_chunk_physique_a_et_placement_a_est_accepte(base: psycopg.Connection) -> None:
    _chunk(base, collection=A)
    _placement(base, collection=A, placement_id=PLACEMENT_A)
    chunks, autorises = _jeu(base)
    assert set(chunks) == {CHUNK}
    probe.verifier_candidats_publies([_candidat()], autorises, collection=A, canal="dense")


def test_derivative_marker_and_attribution_survive_real_retrieval(
    base: psycopg.Connection, postgres: dict[str, str],
) -> None:
    base.execute(
        "UPDATE public.rag_artifacts SET is_text_derivative = true, "
        "licensor = 'MEN', licence_id = 'ETALAB-2.0', "
        "source_updated_at = '2026-10-10', derivative_notice = 'Extrait dérivé'"
    )
    _chunk(base, collection=A)
    base.execute("UPDATE public.rag_chunks SET page_start = 1, page_end = 1")
    _placement(base, collection=A, placement_id=PLACEMENT_A)
    store = PgCandidateStore(lambda: psycopg.connect(postgres["dsn"]), SCOPE_A)
    candidates = store.lexical(raw_query="littérature philosophie", collection=A, limit=5)
    assert len(candidates) == 1
    assert candidates[0].is_text_derivative is True
    assert candidates[0].licence_id == "ETALAB-2.0"
    assert candidates[0].page_start == 1
    with pytest.raises(psycopg.errors.CheckViolation):
        base.execute(
            "UPDATE public.rag_artifacts SET licensor = NULL, licence_id = NULL, "
            "source_updated_at = NULL, derivative_notice = NULL"
        )


def test_chunk_physique_b_avec_placements_a_et_b_est_accepte_depuis_a(base: psycopg.Connection) -> None:
    _chunk(base, collection=B)
    _placement(base, collection=A, placement_id=PLACEMENT_A)
    _placement(base, collection=B, placement_id=PLACEMENT_B)
    chunks, autorises = _jeu(base)
    assert set(chunks) == {CHUNK}
    assert (CHUNK, ARTIFACT, PLACEMENT_A) in autorises
    probe.verifier_candidats_publies([_candidat()], autorises, collection=A, canal="dense")


def test_chunk_physique_b_sans_placement_a_est_refuse(base: psycopg.Connection) -> None:
    _chunk(base, collection=B)
    _placement(base, collection=B, placement_id=PLACEMENT_B)
    chunks, autorises = _jeu(base)
    assert chunks == {}
    with pytest.raises(probe.SondeEchec, match="hors du jeu publié"):
        probe.verifier_candidats_publies([_candidat()], autorises, collection=A, canal="dense")


@pytest.mark.parametrize("colonne,valeur", [
    ("placement_status", "disabled"),
    ("review_status", "needs_review"),
    ("currentness", "archive"),
    ("visibility", "restricted"),
    ("tenant", "autre_premiere"),
    ("niveau", "terminale"),
    ("voie", "technologique"),
    ("matiere", "nsi"),
    ("statut_enseignement", "commun"),
    ("candidat", "scolarise"),
    ("audience", ["enseignant"]),
    ("school_year", "2025-2026"),
    ("programme_version", "ANCIEN"),
])
def test_placement_hors_scope_est_refuse(base: psycopg.Connection, colonne: str, valeur: object) -> None:
    _chunk(base, collection=B)
    _placement(base, collection=A, placement_id=PLACEMENT_A)
    base.execute(f"UPDATE public.rag_artifact_placements SET {colonne} = %s", (valeur,))
    chunks, autorises = _jeu(base)
    assert chunks == {}
    with pytest.raises(probe.SondeEchec, match="hors du jeu publié"):
        probe.verifier_candidats_publies([_candidat()], autorises, collection=A, canal="dense")


def test_droits_de_l_artefact_refuses(base: psycopg.Connection) -> None:
    _chunk(base, collection=B)
    _placement(base, collection=A, placement_id=PLACEMENT_A)
    base.execute("UPDATE public.rag_artifacts SET rights = 'restreint'")
    assert _jeu(base) == ({}, set())


@pytest.mark.parametrize("colonne,valeur", [("vector", None), ("text", "")])
def test_chunk_place_sans_donnees_necessaires_est_refuse(
    base: psycopg.Connection, colonne: str, valeur: object,
) -> None:
    _chunk(base, collection=B)
    _placement(base, collection=A, placement_id=PLACEMENT_A)
    base.execute(f"UPDATE public.rag_chunks SET {colonne} = %s", (valeur,))
    with pytest.raises(probe.SondeEchec, match="chunk publié sans vecteur ou texte"):
        _jeu(base)


def test_vrai_candidat_cross_scope_est_refuse_meme_si_le_chunk_est_atteignable(
    base: psycopg.Connection,
) -> None:
    _chunk(base, collection=B)
    _placement(base, collection=A, placement_id=PLACEMENT_A)
    _placement(base, collection=B, placement_id=PLACEMENT_B)
    _chunks, autorises = _jeu(base)
    with pytest.raises(probe.SondeEchec, match="hors du jeu publié"):
        probe.verifier_candidats_publies(
            [_candidat(placement_id=PLACEMENT_B)], autorises, collection=A, canal="dense"
        )


def test_lexical_multiplacement_est_accepte_et_fuite_refusee(base: psycopg.Connection) -> None:
    _chunk(base, collection=B)
    _placement(base, collection=A, placement_id=PLACEMENT_A)
    _placement(base, collection=B, placement_id=PLACEMENT_B)
    chunks, autorises = _jeu(base)
    assert set(chunks) == {CHUNK}
    probe.verifier_candidats_publies([_candidat()], autorises, collection=A, canal="lexical")
    with pytest.raises(probe.SondeEchec, match="hors du jeu publié"):
        probe.verifier_candidats_publies(
            [_candidat(placement_id=PLACEMENT_B)], autorises, collection=A, canal="lexical"
        )


def test_sonde_complete_accepte_dense_et_lexical_multiplacement(
    base: psycopg.Connection, postgres: dict[str, str],
) -> None:
    _chunk(base, collection=B)
    _placement(base, collection=A, placement_id=PLACEMENT_A)
    _placement(base, collection=B, placement_id=PLACEMENT_B)
    rapport = probe.sonder(
        ROOT, connexion=lambda: psycopg.connect(postgres["dsn"]),
        modules=probe._modules(), collections=[A],
    )
    assert rapport["collections"][A]["chunks"] == 1
    assert rapport["collections"][A]["rappel_a_5"] == 1
    assert rapport["collections"][A]["lexicaux"] >= 1
    assert rapport["collections"][A]["student"] == "refuse"


@pytest.mark.parametrize("canal", ["dense", "lexical"])
def test_sonde_complete_refuse_un_placement_cross_scope_rendu_par_un_canal(
    base: psycopg.Connection, postgres: dict[str, str], canal: str,
) -> None:
    _chunk(base, collection=B)
    _placement(base, collection=A, placement_id=PLACEMENT_A)
    _placement(base, collection=B, placement_id=PLACEMENT_B)
    modules = probe._modules()
    pg = modules["pg"]

    class StoreSabote:
        def __init__(self, _connexion, _scope):
            pass

        def dense(self, *, query_vector, collection, limit):
            placement = PLACEMENT_B if canal == "dense" else PLACEMENT_A
            return [SimpleNamespace(
                chunk_id=CHUNK, artifact_id=ARTIFACT, placement_id=placement,
                vector=tuple(query_vector),
            )]

        def lexical(self, *, raw_query, collection, limit):
            placement = PLACEMENT_B if canal == "lexical" else PLACEMENT_A
            return [_candidat(placement_id=placement)]

    modules["pg"] = SimpleNamespace(_dense_payload=pg._dense_payload, PgCandidateStore=StoreSabote)
    with pytest.raises(probe.SondeEchec, match=f"candidat {canal} hors du jeu publié"):
        probe.sonder(
            ROOT, connexion=lambda: psycopg.connect(postgres["dsn"]),
            modules=modules, collections=[A],
        )


def test_legacy_reste_borne_par_son_scope_physique_complet(base: psycopg.Connection) -> None:
    _chunk(base, collection=A, artifact_id=None)
    chunks, autorises = _jeu(base)
    assert set(chunks) == {CHUNK}
    assert autorises == {(CHUNK, None, None)}
    base.execute("UPDATE public.rag_chunks SET tenant = 'autre_premiere'")
    assert _jeu(base) == ({}, set())


def test_role_student_reste_refuse() -> None:
    modules = probe._modules()
    emis = probe.scopes_emis(ROOT)
    configuration = modules["load_collection_config"](ROOT / probe.CONFIG_COLLECTIONS)
    identite = probe.identite_verifiee(modules, emis[A], role="student", secret="di-test-secret-" + "x" * 32)
    with pytest.raises(modules["scope"].RetrievalScopeError):
        modules["scope"].build_server_retrieval_scope(
            identite, collection=A, collection_config=configuration
        )
