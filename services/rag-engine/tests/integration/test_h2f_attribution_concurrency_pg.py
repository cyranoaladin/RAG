"""G3 — la sérialisation writer/attestor, mesurée sur PostgreSQL réel.

**Ce que ce test ferme.** L'identité du verrou advisory et l'ordre
« verrou → relecture → écriture » étaient prouvés *structurellement* :
une fonction unique ``lock_artifact_attribution``, une clé unique, un
verrou pris avant le ``SELECT``. Aucun test n'exécutait pourtant deux
acteurs concurrents. Une garantie non exécutée est une garantie qu'un
refactor peut retirer sans qu'aucun test ne rougisse.

**Trois connexions, deux rôles réels.** Le writer utilise le rôle
applicatif, l'attestor le rôle attestor — ceux de production, avec leurs
privilèges exacts. Une troisième connexion, purement observatrice,
interroge ``pg_locks`` sans jamais participer à la mutation.

**La preuve est un état, jamais une durée.** L'attente est établie en
lisant ``pg_locks`` (``granted = false``) sur la clé advisory *exacte*,
recalculée en SQL depuis la même chaîne canonique que la production.
Aucun ``sleep`` ne sert d'oracle : le polling est borné et ne fait
qu'attendre qu'un état observable apparaisse, l'assertion portant sur cet
état.

**Les deux ordres sont mesurés**, parce qu'ils ferment deux trous
différents :

* writer d'abord — l'attestor relit *après* le commit du writer et voit
  un digest divergent de celui que l'humain a approuvé : l'attestation
  est refusée ;
* attestor d'abord — le writer est bloqué jusqu'au commit de
  l'attestation, puis le trigger de scellement (migration 012) refuse sa
  mutation.

Aucun deadlock n'est attendu : il n'existe qu'un seul verrou et donc
qu'un seul ordre de prise possible.
"""
from __future__ import annotations

import sys
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pg_authority import (  # noqa: E402
    app_dsn,
    attestor_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)

from ingestor.ingestion_control.artifact_attribution import (  # noqa: E402
    ArtifactAttribution,
    load_artifact_attribution,
    lock_artifact_attribution,
    persist_artifact_attribution,
)

pytestmark = [pytest.mark.integration, requires_docker]

#: Chaîne canonique du verrou, identique à celle de
#: ``lock_artifact_attribution`` — répétée ici *délibérément* pour que le
#: test échoue si la production la change sans que personne ne s'en
#: aperçoive. C'est le seul endroit où la duplication est voulue.
LOCK_KEY_TEMPLATE = "nexus:artifact-attribution:{artifact_id}"

#: Bornes. Chaque attente a une limite ; aucune n'est un oracle.
WAIT_TIMEOUT_S = 15.0
THREAD_JOIN_TIMEOUT_S = 20.0
CHALLENGE = "NEXUS-TRUSTED-REVIEW-V1:" + "cd" * 32

REVIEWED = {
    "source_label": "Éduscol",
    "official": True,
    "source_kind": "eduscol.education.fr",
    "type_doc": "cours",
}
#: Ce que le writer concurrent tente d'imposer — divergent d'un seul fait,
#: ce qui suffit à changer le digest.
DIVERGENT = {**REVIEWED, "source_label": "Éditeur privé"}


@pytest.fixture(scope="module")
def pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("h2f-attribution-concurrency")


def _advisory_key(conn: psycopg.Connection, artifact_id: uuid.UUID) -> tuple[int, int]:
    """Recalcule en SQL la clé advisory et la décompose comme ``pg_locks``.

    ``pg_advisory_xact_lock(bigint)`` publie la clé en deux moitiés :
    ``classid`` = 32 bits de poids fort, ``objid`` = 32 bits de poids
    faible, ``objsubid = 1``. Recalculer ici — plutôt que de lire ce que
    le verrou a produit — est ce qui rend la preuve d'identité réelle :
    on affirme la valeur attendue, puis on la retrouve dans le catalogue.

    Les deux moitiés sont masquées en **non signé** : ``pg_locks.classid``
    et ``objid`` sont des ``oid``, donc sans signe. Un décalage signé
    donnerait la même ligne (PostgreSQL coerce à l'entrée) mais une
    valeur différente à la relecture, et l'assertion d'identité serait
    fausse pour une raison purement représentationnelle.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ((hashtextextended(%s, 0) >> 32) & 4294967295)::bigint, "
            "       (hashtextextended(%s, 0) & 4294967295)::bigint",
            (
                LOCK_KEY_TEMPLATE.format(artifact_id=artifact_id),
                LOCK_KEY_TEMPLATE.format(artifact_id=artifact_id),
            ),
        )
        classid, objid = cur.fetchone()
    return int(classid), int(objid)


def _await_waiting_lock(
    observer: psycopg.Connection, *, classid: int, objid: int
) -> dict[str, Any]:
    """Attend qu'un *waiter* apparaisse sur cette clé advisory exacte.

    Retourne la ligne ``pg_locks`` observée. Lève si la borne est
    atteinte : un blocage qui ne se matérialise pas est un échec, jamais
    un test qui passe silencieusement.
    """
    deadline = threading.Event()
    timer = threading.Timer(WAIT_TIMEOUT_S, deadline.set)
    timer.start()
    try:
        while not deadline.is_set():
            observer.rollback()  # vue fraîche du catalogue à chaque tour
            with observer.cursor() as cur:
                cur.execute(
                    """
                    SELECT pid, granted, classid, objid, objsubid
                    FROM pg_locks
                    WHERE locktype = 'advisory'
                      AND classid = %s AND objid = %s AND objsubid = 1
                      AND granted = false
                    """,
                    (classid, objid),
                )
                row = cur.fetchone()
            if row is not None:
                return {
                    "pid": row[0], "granted": row[1],
                    "classid": row[2], "objid": row[3], "objsubid": row[4],
                }
            deadline.wait(0.05)
    finally:
        timer.cancel()
    raise AssertionError(
        f"no waiter appeared on advisory key classid={classid} objid={objid} "
        f"within {WAIT_TIMEOUT_S}s — the two actors are not serialized on the "
        "same lock, or one of them never attempted to take it"
    )


def _bound_session(conn: psycopg.Connection) -> None:
    """Bornes de session : aucune attente ne peut être infinie."""
    with conn.cursor() as cur:
        cur.execute("SET lock_timeout = '10s'")
        cur.execute("SET statement_timeout = '20s'")
    conn.commit()


def _seed(conn: psycopg.Connection) -> dict[str, Any]:
    """Lignes parentes minimales exigées par les clés étrangères."""
    run_id, resource_id, artifact_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    authorization_id = f"conc-{uuid.uuid4().hex[:8]}"
    scope = (
        "'nexus', 'libre_terminale_philosophie', 'terminale', 'generale', "
        "'philosophie', 'libre', ARRAY['libre'], 'internal', '2026-2027', "
        "'BOEN_special_8_2019-07-25'"
    )
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO ingestion_control.ingestion_runs (
                run_id, tenant, collection, niveau, voie, matiere, candidat,
                audience, visibility, school_year, programme_version,
                profile_version, trigger
            ) VALUES (%s, {scope}, '1.0.0', 'manual')
            """,
            (run_id,),
        )
        cur.execute(
            f"""
            INSERT INTO ingestion_control.resources (
                resource_id, run_id, dedup_key,
                tenant, collection, niveau, voie, matiere, candidat,
                audience, visibility, school_year, programme_version,
                resource_state
            ) VALUES (%s, %s, %s, {scope}, 'REVIEWED')
            """,
            (resource_id, run_id, uuid.uuid4().hex),
        )
        cur.execute(
            """
            INSERT INTO ingestion_control.artifacts (
                artifact_id, resource_id, run_id, sha256, size_bytes,
                mime_declared, mime_detected, original_url, final_url
            ) VALUES (
                %s, %s, %s, repeat('1', 64), 1024,
                'application/pdf', 'application/pdf',
                'https://eduscol.education.gouv.fr/a',
                'https://eduscol.education.gouv.fr/a'
            )
            """,
            (artifact_id, resource_id, run_id),
        )
        cur.execute(
            """
            INSERT INTO ingestion_control.scope_authorizations (
                authorization_id, protocol_version, decision,
                tenant, collection, niveau, voie, matiere, candidat, audience,
                visibility, school_year, programme_version,
                manifest_digest, profile_id, profile_version, profile_fingerprint,
                allowed_domains, rights_categories, exclusions,
                pii_absence_attested, pii_absence_evidence,
                valid_from, valid_until,
                artifact_path, artifact_blob_sha, authorization_digest,
                evidence_repository, evidence_pull_request,
                evidence_base_sha, evidence_head_sha, evidence_review_id,
                evidence_reviewer, evidence_submitted_at, evidence_challenge,
                allowed_content_sha256
            ) VALUES (
                %s, 'LOT41A-V2', 'AUTHORIZE_INGESTION_SCOPE',
                'nexus', 'libre_terminale_philosophie', 'terminale', 'generale',
                'philosophie', 'libre', ARRAY['libre'], 'internal', '2026-2027',
                'BOEN_special_8_2019-07-25',
                repeat('a', 64), 'terminale-philosophie', '1.0.0', repeat('b', 64),
                ARRAY['eduscol.education.gouv.fr'], ARRAY['officiel_public'],
                ARRAY[]::text[],
                true, 'attested',
                now() - interval '1 day', now() + interval '365 days',
                %s, repeat('c', 40), repeat('d', 64),
                'cyranoaladin/RAG', 1, repeat('e', 40), repeat('f', 40), 2,
                'abenrhouma', now(), %s,
                ARRAY[repeat('1', 64)]
            )
            """,
            (
                authorization_id,
                f"governance/authorizations/{authorization_id}.json",
                CHALLENGE,
            ),
        )
    conn.commit()
    return {
        "run_id": run_id, "resource_id": resource_id,
        "artifact_id": artifact_id, "authorization_id": authorization_id,
    }


def _write_attribution(
    conn: psycopg.Connection, seeded: dict[str, Any], facts: dict[str, Any]
) -> str:
    return persist_artifact_attribution(
        conn,
        attribution=ArtifactAttribution(
            ingestion_artifact_id=seeded["artifact_id"], **facts
        ),
        run_id=seeded["run_id"],
        actor="concurrency-test",
    )


def _insert_attestation(
    conn: psycopg.Connection, seeded: dict[str, Any], digest: str
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.publication_attestations (
                resource_id, artifact_id, content_sha256, canonical_url, collection,
                scope_authorization_id, profile_id, profile_version,
                profile_fingerprint, manifest_digest,
                rights_status, rights_assessed_at,
                quality_passed, quality_report_digest, quality_assessed_at,
                gate_passed, gate_name, gate_evaluated_at,
                evidence_event_ids,
                review_id, review_artifact_path, review_artifact_blob_sha,
                attestation_digest,
                human_review_repository, human_review_pull_request,
                human_review_base_sha, human_review_head_sha, human_review_review_id,
                human_review_reviewer, human_review_submitted_at,
                human_review_challenge,
                protocol_version, attributed_facts_digest
            ) VALUES (
                %s, %s, repeat('1', 64), 'https://eduscol.education.gouv.fr/a',
                'libre_terminale_philosophie',
                %s, 'terminale-philosophie', '1.0.0', repeat('b', 64), repeat('a', 64),
                'officiel_public', now(),
                true, repeat('9', 64), now(),
                true, 'h2f-gate', now(),
                ARRAY[gen_random_uuid()],
                'review-conc',
                'governance/publication-reviews/review-conc-' || repeat('7', 64)
                    || '.json',
                repeat('c', 40), repeat('7', 64),
                'cyranoaladin/RAG', 1, repeat('e', 40), repeat('f', 40), 3,
                'abenrhouma', now(), %s,
                'LOT42-V2', %s
            )
            """,
            (
                seeded["resource_id"], seeded["artifact_id"],
                seeded["authorization_id"], CHALLENGE, digest,
            ),
        )


class TestWriterFirst:
    """Le writer détient le verrou ; l'attestor attend, puis refuse."""

    def test_the_attestor_waits_then_sees_the_committed_divergence(
        self, pg: dict[str, str]
    ) -> None:
        with psycopg.connect(superuser_dsn(pg)) as admin:
            seeded = _seed(admin)
        artifact_id = seeded["artifact_id"]

        reviewed_digest: str | None = None
        with psycopg.connect(app_dsn(pg)) as bootstrap:
            reviewed_digest = _write_attribution(bootstrap, seeded, REVIEWED)
            bootstrap.commit()

        observer = psycopg.connect(superuser_dsn(pg))
        writer = psycopg.connect(app_dsn(pg))
        attestor = psycopg.connect(attestor_dsn(pg))
        released = threading.Event()
        outcome: dict[str, Any] = {}

        try:
            _bound_session(writer)
            _bound_session(attestor)
            classid, objid = _advisory_key(observer, artifact_id)

            # 1/2 — le writer prend le verrou et diverge, sans committer.
            _write_attribution(writer, seeded, DIVERGENT)

            def attestor_side() -> None:
                try:
                    # Bloque ici : même clé advisory, détenue par le writer.
                    _attribution, digest = load_artifact_attribution(
                        attestor, ingestion_artifact_id=artifact_id, lock=True
                    )
                    outcome["digest_after_wait"] = digest
                except BaseException as exc:  # noqa: BLE001 - remonté tel quel
                    outcome["error"] = exc
                finally:
                    released.set()

            thread = threading.Thread(target=attestor_side, daemon=True)
            thread.start()

            # 2/2 — la preuve : un waiter sur CETTE clé exacte.
            waiting = _await_waiting_lock(observer, classid=classid, objid=objid)
            assert waiting["granted"] is False
            assert waiting["classid"] == classid
            assert waiting["objid"] == objid
            assert not released.is_set(), (
                "the attestor returned before the writer committed — it never "
                "took the lock, so nothing was serialized"
            )

            writer.commit()
            assert released.wait(THREAD_JOIN_TIMEOUT_S), "attestor never resumed"
            thread.join(THREAD_JOIN_TIMEOUT_S)
            assert not thread.is_alive()
            assert "error" not in outcome, outcome.get("error")

            # L'attestor lit la valeur committée, qui n'est plus celle revue :
            # c'est exactement le prédicat que ``record-attestation`` compare.
            assert outcome["digest_after_wait"] != reviewed_digest, (
                "the attestor read the reviewed digest even though the writer "
                "committed a divergence — the read was not serialized"
            )

            with psycopg.connect(superuser_dsn(pg)) as check, check.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM ingestion_control.publication_attestations "
                    "WHERE artifact_id = %s",
                    (artifact_id,),
                )
                assert cur.fetchone() == (0,), (
                    "an attestation was written despite a divergent attribution"
                )
        finally:
            for conn in (writer, attestor, observer):
                try:
                    conn.rollback()
                finally:
                    conn.close()


class TestAttestorFirst:
    """L'attestor scelle ; le writer attend, puis est refusé par le trigger."""

    def test_the_writer_waits_then_is_refused_by_the_seal(
        self, pg: dict[str, str]
    ) -> None:
        with psycopg.connect(superuser_dsn(pg)) as admin:
            seeded = _seed(admin)
        artifact_id = seeded["artifact_id"]

        with psycopg.connect(app_dsn(pg)) as bootstrap:
            reviewed_digest = _write_attribution(bootstrap, seeded, REVIEWED)
            bootstrap.commit()

        observer = psycopg.connect(superuser_dsn(pg))
        attestor = psycopg.connect(attestor_dsn(pg))
        writer = psycopg.connect(app_dsn(pg))
        released = threading.Event()
        outcome: dict[str, Any] = {}

        try:
            _bound_session(writer)
            _bound_session(attestor)
            classid, objid = _advisory_key(observer, artifact_id)

            # 1/3 — l'attestor prend le verrou, relit sous verrou, écrit.
            _attribution, digest = load_artifact_attribution(
                attestor, ingestion_artifact_id=artifact_id, lock=True
            )
            assert digest == reviewed_digest
            _insert_attestation(attestor, seeded, digest)

            def writer_side() -> None:
                try:
                    _write_attribution(writer, seeded, DIVERGENT)
                    writer.commit()
                    outcome["committed"] = True
                except BaseException as exc:  # noqa: BLE001
                    outcome["error"] = exc
                finally:
                    released.set()

            thread = threading.Thread(target=writer_side, daemon=True)
            thread.start()

            # 2/3 — le writer attend sur la même clé.
            waiting = _await_waiting_lock(observer, classid=classid, objid=objid)
            assert waiting["granted"] is False
            assert (waiting["classid"], waiting["objid"]) == (classid, objid)
            assert not released.is_set()

            # 3/3 — l'attestation devient durable ; le scellement s'applique.
            attestor.commit()
            assert released.wait(THREAD_JOIN_TIMEOUT_S), "writer never resumed"
            thread.join(THREAD_JOIN_TIMEOUT_S)
            assert not thread.is_alive()

            assert "committed" not in outcome, (
                "the writer mutated a sealed attribution after the attestation "
                "committed — the migration 012 trigger did not fire"
            )
            error = outcome.get("error")
            assert isinstance(error, psycopg.errors.RaiseException), error
            assert "ATTRIBUTION_SEALED_BY_ATTESTATION" in str(error)

            # État final cohérent : l'attribution scellée est intacte.
            with psycopg.connect(superuser_dsn(pg)) as check, check.cursor() as cur:
                cur.execute(
                    "SELECT attribution_digest FROM "
                    "ingestion_control.artifact_attributions "
                    "WHERE ingestion_artifact_id = %s",
                    (artifact_id,),
                )
                assert cur.fetchone() == (reviewed_digest,)
                cur.execute(
                    "SELECT attributed_facts_digest FROM "
                    "ingestion_control.publication_attestations "
                    "WHERE artifact_id = %s",
                    (artifact_id,),
                )
                assert cur.fetchone() == (reviewed_digest,)
        finally:
            for conn in (writer, attestor, observer):
                try:
                    conn.rollback()
                finally:
                    conn.close()


class TestNoDeadlockAndNoResidue:
    def test_the_two_roles_take_exactly_one_advisory_key(
        self, pg: dict[str, str]
    ) -> None:
        """Un seul verrou, donc un seul ordre de prise : aucun cycle
        d'attente n'est représentable entre writer et attestor."""
        with psycopg.connect(superuser_dsn(pg)) as admin:
            seeded = _seed(admin)
        artifact_id = seeded["artifact_id"]

        observer = psycopg.connect(superuser_dsn(pg))
        actor = psycopg.connect(app_dsn(pg))
        try:
            classid, objid = _advisory_key(observer, artifact_id)
            lock_artifact_attribution(actor, ingestion_artifact_id=artifact_id)
            observer.rollback()
            with observer.cursor() as cur:
                cur.execute(
                    "SELECT classid, objid, objsubid FROM pg_locks "
                    "WHERE locktype = 'advisory' AND granted = true "
                    "  AND pid = %s",
                    (actor.info.backend_pid,),
                )
                held = cur.fetchall()
            assert held == [(classid, objid, 1)], (
                f"expected exactly one advisory lock on the canonical key, got {held}"
            )
        finally:
            for conn in (actor, observer):
                try:
                    conn.rollback()
                finally:
                    conn.close()

    def test_no_deadlock_was_recorded_on_this_database(
        self, pg: dict[str, str]
    ) -> None:
        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute("SELECT deadlocks FROM pg_stat_database WHERE datname = current_database()")
            (deadlocks,) = cur.fetchone()
        assert deadlocks == 0, f"{deadlocks} deadlock(s) recorded during this run"

    def test_no_idle_in_transaction_session_remains(
        self, pg: dict[str, str]
    ) -> None:
        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() "
                "  AND state = 'idle in transaction' "
                "  AND pid <> pg_backend_pid()"
            )
            (stuck,) = cur.fetchone()
        assert stuck == 0, f"{stuck} session(s) left idle in transaction"
