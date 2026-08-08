"""LOT42 (ADR-0033) — attestation de publication liée aux preuves durables.

Remédiation GATE H1, items **E** et **F**.

**Les preuves sont produites par le vrai code.** Aucun ``workflow_event``
n'est fabriqué à la main ici : ce sont ``run_rights_agent`` et
``run_quality_agent`` — les fonctions que le worker appelle en production,
non modifiées — qui les écrivent. Un test qui insérerait lui-même les faits
qu'il prétend vérifier ne prouverait rien sur le système.

Une seule pièce est substituée pour les scénarios *positifs* : la sortie du
classifieur. ``classify_conformity_core`` est un placeholder documenté qui
laisse niveau/voie/programme « non vérifiés », de sorte qu'aucune ressource
ne peut aujourd'hui franchir le gate. Ce fait n'est pas contourné en
silence — il est vérifié explicitement par
``TestLivePipelineCannotYetPublish``, et c'est très exactement ce que
``LOT42_LIVE_PIPELINE_WIRED=false`` signifie.

**Item E.** L'opérateur ne fournit plus aucune donnée technique. La
sous-commande ``propose-review`` dérive l'artefact depuis la base ; la
sous-commande ``record-attestation`` relit le blob approuvé et refuse toute
divergence DB ↔ artefact.

**Item F.** Une chaîne négative est refusée à trois niveaux indépendants :
l'artefact ne peut pas se construire, la contrainte SQL rejette la ligne,
et la relecture refuse la transition.
"""
from __future__ import annotations

import hashlib
import json
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _authorization_stub import (  # noqa: E402
    STUB_AUTHORIZATION_ID,
    stub_verifier,
    verified_authorization,
)
from _local_github import (  # noqa: E402
    REPOSITORY,
    VALID_TOKEN,
    LocalGitHub,
    local_github_server,
)
from _pg_authority import (  # noqa: E402
    app_dsn,
    attestor_dsn,
    authority_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)
from nexus_contracts.authority_artifacts import (  # noqa: E402
    ScopeAuthorizationArtifact,
    canonical_authorization_path,
)
from nexus_contracts.document import Rights  # noqa: E402
from nexus_contracts.ingestion import (  # noqa: E402
    ArtifactRecord,
    CollectionProfile,
    ResourceCandidate,
    ResourceScope,
)
from nexus_contracts.resource_state import ResourceState  # noqa: E402

from ingestor.ingestion_agents.classifier import ConformityResult  # noqa: E402
from ingestor.ingestion_agents.quality_agent import run_quality_agent  # noqa: E402
from ingestor.ingestion_agents.rights_agent import run_rights_agent  # noqa: E402
from ingestor.ingestion_agents.transitions import (  # noqa: E402
    apply_resource_transition,
)
from ingestor.ingestion_control.jobs import create_job  # noqa: E402
from ingestor.ingestion_control.provisioning import (  # noqa: E402
    create_resource,
    get_resource_state,
    persist_artifact,
    persist_resource_candidate,
)
from ingestor.ingestion_control.publication_attestation import (  # noqa: E402
    PublicationAttestationInvalidError,
    attempt_retrieval_eligible_transition,
    verify_publication_attestation,
)
from ingestor.ingestion_control.publication_evidence import (  # noqa: E402
    PublicationEvidenceMissingError,
    collect_publication_facts,
)
from ingestor.ingestion_profiles.registry import profile_fingerprint  # noqa: E402
from ingestor.ingestion_worker.attest_publication_cli import (  # noqa: E402
    main as attest_main,
)
from ingestor.ingestion_worker.authorize_scope_cli import (  # noqa: E402
    main as authorize_scope_main,
)
from ingestor.ingestion_worker.runner import WorkerDeps, run_worker_iteration  # noqa: E402
from ingestor.ingestion_worker.storage import (  # noqa: E402
    make_filesystem_artifact_reader,
    make_filesystem_artifact_store,
)

pytestmark = [pytest.mark.integration, requires_docker]

MANIFEST_DIGEST = "a" * 64
AUTH_PR, AUTH_HEAD, AUTH_BASE, AUTH_REVIEW = 4242, "b" * 40, "a" * 40, 777
PUB_PR, PUB_HEAD, PUB_REVIEW = 4300, "c" * 40, 888
REVIEW_ID = "pub-nsi-001"

VALID_SCOPE: dict[str, Any] = {
    "tenant": "libre_terminale",
    "collection": "rag_nexus_nsi_terminale_specialite",
    "niveau": "terminale",
    "voie": "generale",
    "matiere": "nsi",
    "candidat": "libre",
    "audience": ["libre", "tous"],
    "visibility": "internal",
    "school_year": "2026-2027",
    "programme_version": "BOEN_special_8_2019-07-25",
}

PROFILE = CollectionProfile.model_validate({
    "profile_version": "v1",
    "enabled": True,
    "scope": VALID_SCOPE,
    "title": "NSI Terminale Spécialité",
    "owner": "equipe-nsi",
    "expected_topics": ["algorithmique"],
    "expected_resource_types": ["cours"],
    "allowed_domains": ["eduscol.education.fr"],
    "source_authority": "official",
    "search_cadence": "weekly",
    "max_queries_per_run": 10,
    "max_documents_per_run": 20,
    "max_chunk_size": 800,
    "chunk_overlap": 100,
    "min_source_confidence": 0.7,
    "min_scope_confidence": 0.7,
    "min_extraction_quality": 0.1,
})
REGISTRY = {(PROFILE.scope.collection, PROFILE.profile_version): PROFILE}
PROFILE_FINGERPRINT = profile_fingerprint(PROFILE)

RICH_CONTENT = (
    b"<p>Ce cours d'algorithmique aborde la recursivite, les structures de "
    b"donnees, les boucles, les fonctions et plusieurs algorithmes de tri "
    b"classiques du programme de terminale, avec exemples et exercices "
    b"corriges pour couvrir largement la notion.</p>"
)


def authorization_document() -> dict[str, Any]:
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    return {
        "protocol_version": "LOT41A-V1",
        "authorization_id": STUB_AUTHORIZATION_ID,
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "scope": dict(VALID_SCOPE),
        "manifest_digest": MANIFEST_DIGEST,
        "profile_id": PROFILE.scope.collection,
        "profile_version": PROFILE.profile_version,
        "profile_fingerprint": PROFILE_FINGERPRINT,
        "allowed_domains": ["eduscol.education.fr"],
        "rights_categories": ["officiel_public"],
        "exclusions": [],
        "pii_absence_attested": True,
        "pii_absence_evidence": "Corpus officiel, aucune donnee personnelle.",
        "valid_from": (now - timedelta(days=1)).isoformat(),
        "valid_until": (now + timedelta(days=365)).isoformat(),
    }


@pytest.fixture(scope="module")
def pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("lot42")


@pytest.fixture(autouse=True)
def _clean(pg: dict[str, str]) -> Iterator[None]:
    with psycopg.connect(superuser_dsn(pg)) as conn:
        with conn.cursor() as cur:
            for table in (
                "publication_attestations", "scope_authorizations", "workflow_events",
                "artifacts", "resource_candidates", "jobs", "resources", "ingestion_runs",
            ):
                cur.execute(f"DELETE FROM ingestion_control.{table}")  # noqa: S608
        conn.commit()
    yield


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[LocalGitHub]:
    state = LocalGitHub()
    state.add_approved_pr(
        number=AUTH_PR, head_sha=AUTH_HEAD, base_sha=AUTH_BASE, review_id=AUTH_REVIEW,
    )
    state.add_approved_pr(
        number=PUB_PR, head_sha=PUB_HEAD, base_sha=AUTH_BASE, review_id=PUB_REVIEW,
        submitted_at="2026-08-09T10:00:00Z",
    )
    state.put_blob(
        path=canonical_authorization_path(STUB_AUTHORIZATION_ID),
        ref=AUTH_HEAD,
        content=ScopeAuthorizationArtifact.model_validate(
            authorization_document()
        ).canonical_bytes(),
    )
    token_file = tmp_path / "gh-token"
    token_file.write_text(VALID_TOKEN, encoding="utf-8")
    with local_github_server(state) as base_url:
        monkeypatch.setenv("NEXUS_GITHUB_API_BASE", base_url)
        monkeypatch.setenv("NEXUS_GITHUB_TOKEN_FILE", str(token_file))
        monkeypatch.delenv("NEXUS_GITHUB_TOKEN", raising=False)
        yield state


@pytest.fixture
def operator_env(pg: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_INGESTION_CONTROL_AUTHORITY_DSN", authority_dsn(pg))
    monkeypatch.setenv("PG_INGESTION_CONTROL_ATTESTOR_DSN", attestor_dsn(pg))
    monkeypatch.delenv("PG_INGESTION_CONTROL_DSN", raising=False)


def _make_run(conn: psycopg.Connection) -> uuid.UUID:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.ingestion_runs
                (tenant, collection, niveau, voie, matiere, candidat, audience,
                 visibility, school_year, programme_version, profile_version,
                 trigger, status)
            VALUES (%(tenant)s, %(collection)s, %(niveau)s, %(voie)s, %(matiere)s,
                    %(candidat)s, %(audience)s, %(visibility)s, %(school_year)s,
                    %(programme_version)s, 'v1', 'manual', 'planned')
            RETURNING run_id
            """,
            {**VALID_SCOPE, "audience": sorted(VALID_SCOPE["audience"])},
        )
        row = cur.fetchone()
    assert row is not None
    conn.commit()
    return row[0]


def run_real_pipeline(
    pg: dict[str, str], tmp_path: Path, *, content: bytes = RICH_CONTENT
) -> tuple[uuid.UUID, uuid.UUID]:
    """Exécute le VRAI worker de bout en bout et rend ``(resource_id,
    artifact_id)``.

    Utilisé pour le cas **négatif** : dans l'état actuel du pipeline, le
    classifieur est un placeholder documenté qui laisse ``niveau``/``voie``/
    ``programme`` non vérifiés, donc toute ressource porte des motifs de
    rejet et le gate est nécessairement négatif. C'est précisément ce que
    ``LOT42_LIVE_PIPELINE_WIRED=false`` signifie, et c'est vérifié
    explicitement par ``TestLivePipelineCannotYetPublish``."""
    def fetch(url: str, *, max_bytes: int, **kwargs: Any) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/html"}, content=content,
            request=httpx.Request("GET", url),
        )

    auth = verified_authorization(
        scope=VALID_SCOPE,
        manifest_digest=MANIFEST_DIGEST,
        profile_id=PROFILE.scope.collection,
        profile_version=PROFILE.profile_version,
        profile_fingerprint=PROFILE_FINGERPRINT,
        rights_categories=("officiel_public",),
    )
    deps = WorkerDeps(
        owner="worker-lot42",
        profile_registry=REGISTRY,
        artifact_store=make_filesystem_artifact_store(tmp_path / "artifacts"),
        artifact_reader=make_filesystem_artifact_reader(tmp_path / "artifacts"),
        validate_destination=lambda url: url,
        safe_fetch=fetch,
        verify_scope_authorization=stub_verifier(auth),
        manifest_digest=MANIFEST_DIGEST,
    )
    with psycopg.connect(app_dsn(pg)) as conn:
        run_id = _make_run(conn)
        create_job(
            conn, run_id=run_id, job_type="resource_pipeline",
            payload={
                "scope": VALID_SCOPE,
                "dedup_key": "e" * 64,
                "source_url": "https://eduscol.education.fr/nsi/algo",
                "canonical_url": "https://eduscol.education.fr/nsi/algo",
                "domain": "eduscol.education.fr",
                "proposed_type_doc": "cours",
                "profile_version": "v1",
                "scope_authorization_id": STUB_AUTHORIZATION_ID,
                "license": "CC-BY-SA",
            },
        )
        conn.commit()
        outcome = run_worker_iteration(conn, deps=deps)
        assert outcome.status == "succeeded", outcome.error
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SELECT resource_id FROM ingestion_control.resources")
            (resource_id,) = cur.fetchone()
            cur.execute(
                "SELECT artifact_id FROM ingestion_control.artifacts WHERE resource_id = %s",
                (resource_id,),
            )
            (artifact_id,) = cur.fetchone()
    return resource_id, artifact_id


CONFORMING = ConformityResult(
    niveau_conformity=True,
    voie_conformity=True,
    matiere_conformity=True,
    programme_conformity=True,
    matiere_evidence=("algorithmique",),
)


def build_publishable_resource(pg: dict[str, str]) -> tuple[uuid.UUID, uuid.UUID]:
    """Produit une ressource dont la chaîne durable est POSITIVE, en
    exécutant les **vrais** émetteurs d'évidence.

    Pourquoi pas le worker complet : ``classify_conformity_core`` est un
    placeholder documenté qui renvoie ``False`` pour niveau/voie/programme
    (« non vérifié », jamais « vérifié non conforme »). Aucune ressource ne
    peut donc franchir le gate aujourd'hui — cf.
    ``TestLivePipelineCannotYetPublish``, qui vérifie explicitement ce fait
    plutôt que de le contourner en silence.

    La seule chose substituée ici est donc la sortie du classifieur, c'est-
    à-dire exactement la pièce que le lot documente comme non implémentée.
    ``run_rights_agent`` et ``run_quality_agent`` — les fonctions qui
    écrivent l'évidence durable dont dépend LOT42 — sont les vraies, non
    modifiées."""
    scope = ResourceScope.model_validate(VALID_SCOPE)
    with psycopg.connect(app_dsn(pg)) as conn:
        run_id = _make_run(conn)
        resource_id = create_resource(
            conn, run_id=run_id, dedup_key="f" * 64, scope=scope
        )
        now = datetime.now(UTC)
        candidate = ResourceCandidate(
            candidate_id=uuid.uuid4(),
            resource_id=resource_id,
            run_id=run_id,
            scope=scope,
            discovered_at=now,
            source_url="https://eduscol.education.fr/nsi/algo",
            canonical_url="https://eduscol.education.fr/nsi/algo",
            domain="eduscol.education.fr",
            proposed_type_doc="cours",
            dedup_key=hashlib.sha256(
                b"https://eduscol.education.fr/nsi/algo"
            ).hexdigest(),
        )
        persist_resource_candidate(conn, candidate=candidate)
        artifact = ArtifactRecord(
            artifact_id=uuid.uuid4(),
            resource_id=resource_id,
            run_id=run_id,
            scope=scope,
            sha256=hashlib.sha256(RICH_CONTENT).hexdigest(),
            size_bytes=len(RICH_CONTENT),
            mime_declared="text/html",
            mime_detected="text/html",
            original_url=candidate.source_url,
            final_url=candidate.canonical_url,
            collected_at=now,
            domain=candidate.domain,
            license="CC-BY-SA",
            rights_status=Rights.unknown,
        )
        persist_artifact(conn, artifact=artifact)

        # La version initiale est lue, jamais supposée : `create_resource`
        # ne garantit pas 1, et une hypothèse fausse ferait échouer le CAS
        # pour une raison sans rapport avec ce que ce fichier teste.
        current = get_resource_state(conn, resource_id=resource_id)
        assert current is not None
        _, version = current
        for from_state, to_state in (
            (ResourceState.DISCOVERED, ResourceState.CANDIDATE),
            (ResourceState.CANDIDATE, ResourceState.FETCHED),
            (ResourceState.FETCHED, ResourceState.STORED),
            (ResourceState.STORED, ResourceState.EXTRACTED),
            (ResourceState.EXTRACTED, ResourceState.CLASSIFIED),
        ):
            transition = apply_resource_transition(
                conn,
                resource_id=resource_id,
                expected_state=from_state,
                expected_version=version,
                new_state=to_state,
                actor="lot42-fixture",
                run_id=run_id,
            )
            version = transition.state_version

        rights, rights_transition = run_rights_agent(
            conn, artifact=artifact, profile=PROFILE,
            expected_version=version, actor="lot42-fixture",
        )
        assert rights is Rights.officiel_public
        run_quality_agent(
            conn,
            artifact=artifact,
            profile=PROFILE,
            conformity=CONFORMING,
            rights=rights,
            extracted_text=RICH_CONTENT.decode(),
            declared_language="fr",
            pii_detected=False,
            duplicate_detected=False,
            report_id=uuid.uuid4(),
            decision_id=uuid.uuid4(),
            evaluated_at=now,
            expected_version=rights_transition.state_version,
            actor="lot42-fixture",
        )
        conn.commit()
    return resource_id, artifact.artifact_id


def record_authorization(github: LocalGitHub) -> None:
    assert authorize_scope_main([
        "record-authorization",
        "--authorization-id", STUB_AUTHORIZATION_ID,
        "--repository", REPOSITORY,
        "--pull-request", str(AUTH_PR),
        "--expected-head", AUTH_HEAD,
    ]) == 0


def propose(
    resource_id: uuid.UUID, artifact_id: uuid.UUID, capsys: Any
) -> tuple[int, str, str]:
    capsys.readouterr()  # vide ce qu'ont écrit les étapes précédentes
    code = attest_main([
        "propose-review",
        "--resource-id", str(resource_id),
        "--artifact-id", str(artifact_id),
        "--scope-authorization-id", STUB_AUTHORIZATION_ID,
        "--review-id", REVIEW_ID,
    ])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def parse_proposal(output: str) -> tuple[str, bytes]:
    """Extrait le chemin canonique et les octets EXACTS de l'artefact.

    Le repérage se fait sur les marqueurs, jamais sur des index de ligne :
    une sortie précédente non drainée décalerait silencieusement le parse et
    ferait échouer le test pour une raison sans rapport."""
    lines = output.splitlines(keepends=True)
    path_index = next(
        i for i, line in enumerate(lines) if line.startswith("REVIEW_ARTIFACT_PATH ")
    )
    path = lines[path_index].split(" ", 1)[1].strip()
    assert lines[path_index + 1].startswith("REVIEW_ARTIFACT_DIGEST ")
    return path, "".join(lines[path_index + 2:]).encode("utf-8")


def attest(resource_id: uuid.UUID, artifact_id: uuid.UUID) -> int:
    return attest_main([
        "record-attestation",
        "--resource-id", str(resource_id),
        "--artifact-id", str(artifact_id),
        "--scope-authorization-id", STUB_AUTHORIZATION_ID,
        "--review-id", REVIEW_ID,
        "--repository", REPOSITORY,
        "--pull-request", str(PUB_PR),
        "--expected-head", PUB_HEAD,
    ])


@pytest.fixture
def attested(
    pg: dict[str, str], tmp_path: Path, github: LocalGitHub, operator_env: None,
    capsys: Any,
) -> dict[str, Any]:
    """Chaîne complète : pipeline réel -> autorisation -> proposition ->
    commit de l'artefact -> approbation -> attestation."""
    resource_id, artifact_id = build_publishable_resource(pg)
    record_authorization(github)
    code, output, _ = propose(resource_id, artifact_id, capsys)
    assert code == 0, output
    path, raw = parse_proposal(output)
    assert path.endswith(hashlib.sha256(raw).hexdigest() + ".json"), (
        "le chemin canonique doit porter le digest des octets proposés"
    )
    github.put_blob(path=path, ref=PUB_HEAD, content=raw)
    assert attest(resource_id, artifact_id) == 0
    return {
        "resource_id": resource_id, "artifact_id": artifact_id,
        "path": path, "raw": raw,
    }


def content_sha(pg: dict[str, str], artifact_id: uuid.UUID) -> str:
    with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT sha256 FROM ingestion_control.artifacts WHERE artifact_id = %s",
            (artifact_id,),
        )
        return str(cur.fetchone()[0])


def verify(pg: dict[str, str], attested: dict[str, Any], **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "current_content_sha256": content_sha(pg, attested["artifact_id"]),
        "current_profile_fingerprint": PROFILE_FINGERPRINT,
        "current_manifest_digest": MANIFEST_DIGEST,
    }
    kwargs.update(overrides)
    with psycopg.connect(superuser_dsn(pg)) as conn:
        return verify_publication_attestation(
            conn, resource_id=attested["resource_id"], **kwargs
        )


# ---------------------------------------------------------------------------
# Item E — les faits viennent du pipeline, jamais de l'opérateur
# ---------------------------------------------------------------------------


class TestDurableEvidenceIsTheOnlySource:
    def test_the_pipeline_writes_every_required_fact(
        self, pg: dict[str, str], tmp_path: Path
    ) -> None:
        resource_id, artifact_id = build_publishable_resource(pg)
        with psycopg.connect(superuser_dsn(pg)) as conn:
            facts = collect_publication_facts(
                conn, resource_id=resource_id, artifact_id=artifact_id
            )
        assert facts.quality_passed is True
        assert facts.gate_passed is True
        assert facts.gate_name == "routing_gate"
        assert facts.rights_status.value == "officiel_public"
        assert len(facts.quality_report_digest) == 64
        assert len(facts.evidence_event_ids) == 3

    def test_a_resource_without_pipeline_evidence_cannot_be_attested(
        self, pg: dict[str, str]
    ) -> None:
        with psycopg.connect(superuser_dsn(pg)) as conn:
            with pytest.raises(PublicationEvidenceMissingError, match="does not exist"):
                collect_publication_facts(
                    conn, resource_id=uuid.uuid4(), artifact_id=uuid.uuid4()
                )

    def test_the_cli_exposes_no_technical_argument(self) -> None:
        """Item E, garde-fou de surface : les options qui laissaient
        l'opérateur affirmer librement des faits techniques n'existent plus.
        Un futur lot qui les réintroduirait casse ce test."""
        source = (
            ENGINE_ROOT / "src" / "ingestor" / "ingestion_worker"
            / "attest_publication_cli.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            '"--content-sha256"', '"--canonical-url"', '"--collection"',
            '"--rights-status"', '"--quality-passed"', '"--quality-score"',
            '"--gate-passed"', '"--gate-name"', '"--profile-fingerprint"',
            '"--manifest-digest"',
        ):
            assert forbidden not in source, f"{forbidden} must never come back"

    def test_the_proposal_is_derived_entirely_from_the_database(
        self, pg: dict[str, str], tmp_path: Path, github: LocalGitHub,
        operator_env: None, capsys: Any,
    ) -> None:
        resource_id, artifact_id = build_publishable_resource(pg)
        record_authorization(github)
        code, output, _ = propose(resource_id, artifact_id, capsys)
        assert code == 0, output
        path, raw = parse_proposal(output)
        document = json.loads(raw.decode())
        assert document["content_sha256"] == content_sha(pg, artifact_id)
        assert document["resource_id"] == str(resource_id)
        assert document["profile_fingerprint"] == PROFILE_FINGERPRINT
        assert document["manifest_digest"] == MANIFEST_DIGEST
        assert document["gate_passed"] is True
        assert path.startswith("governance/publication-reviews/")


class TestAttestationBindsTheReviewedArtifact:
    def test_the_full_chain_records_and_verifies(
        self, pg: dict[str, str], attested: dict[str, Any]
    ) -> None:
        result = verify(pg, attested)
        assert result.review_id == REVIEW_ID
        assert result.scope_authorization_id == STUB_AUTHORIZATION_ID
        assert result.facts.gate_passed is True

    def test_an_artifact_diverging_from_the_database_is_refused_at_record_time(
        self, pg: dict[str, str], tmp_path: Path, github: LocalGitHub,
        operator_env: None, capsys: Any,
    ) -> None:
        """Le cœur de l'item E : l'opérateur commite un artefact qui
        prétend un contenu différent de celui enregistré. Le digest fait
        partie du chemin, donc l'artefact falsifié n'est même pas trouvé —
        et s'il l'était, la comparaison octet à octet le refuserait."""
        resource_id, artifact_id = build_publishable_resource(pg)
        record_authorization(github)
        code, output, _ = propose(resource_id, artifact_id, capsys)
        assert code == 0
        path, raw = parse_proposal(output)
        document = json.loads(raw.decode())
        document["content_sha256"] = "9" * 64
        github.put_blob(
            path=path, ref=PUB_HEAD,
            content=(json.dumps(document, sort_keys=True, indent=2) + "\n").encode(),
        )
        assert attest(resource_id, artifact_id) == 1

    def test_reviewed_bytes_modified_after_attestation_are_denied(
        self, pg: dict[str, str], attested: dict[str, Any], github: LocalGitHub
    ) -> None:
        document = json.loads(attested["raw"].decode())
        document["canonical_url"] = "https://attacker.test/leak"
        github.put_blob(
            path=attested["path"], ref=PUB_HEAD,
            content=(json.dumps(document, sort_keys=True, indent=2) + "\n").encode(),
        )
        with pytest.raises(PublicationAttestationInvalidError, match="review_artifact_blob_sha"):
            verify(pg, attested)


# ---------------------------------------------------------------------------
# Item F — une chaîne négative ne publie jamais
# ---------------------------------------------------------------------------


class TestNegativeChainsNeverPublish:
    def test_a_failing_quality_chain_is_refused_at_proposal(
        self, pg: dict[str, str], tmp_path: Path, github: LocalGitHub,
        operator_env: None, capsys: Any,
    ) -> None:
        """Contenu trop pauvre : le pipeline produit quality_passed=false et
        gate_passed=false. Aucune proposition n'est possible."""
        resource_id, artifact_id = run_real_pipeline(pg, tmp_path, content=b"<p>court</p>")
        record_authorization(github)
        code, _, error = propose(resource_id, artifact_id, capsys)
        assert code == 1
        assert "PUBLICATION_DENIED_QUALITY" in error or "PUBLICATION_DENIED_GATE" in error

    def test_a_failing_chain_can_never_be_recorded(
        self, pg: dict[str, str], tmp_path: Path, github: LocalGitHub, operator_env: None
    ) -> None:
        resource_id, artifact_id = run_real_pipeline(pg, tmp_path, content=b"<p>court</p>")
        record_authorization(github)
        assert attest(resource_id, artifact_id) == 1
        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM ingestion_control.publication_attestations")
            assert cur.fetchone() == (0,)

    @pytest.mark.parametrize("column", ["quality_passed", "gate_passed"])
    def test_the_database_refuses_a_negative_attestation_outright(
        self, pg: dict[str, str], attested: dict[str, Any], column: str
    ) -> None:
        """Barrière structurelle : même un accès SQL privilégié ne peut pas
        écrire une attestation négative — la contrainte CHECK l'interdit."""
        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    f"UPDATE ingestion_control.publication_attestations SET {column} = false"  # noqa: S608
                )

    def test_the_database_refuses_unknown_rights(
        self, pg: dict[str, str], attested: dict[str, Any]
    ) -> None:
        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    "UPDATE ingestion_control.publication_attestations "
                    "SET rights_status = 'unknown'"
                )


class TestVerificationRejectsEveryDrift:
    def test_content_drift_is_denied(
        self, pg: dict[str, str], attested: dict[str, Any]
    ) -> None:
        with pytest.raises(PublicationAttestationInvalidError, match="content_sha256"):
            verify(pg, attested, current_content_sha256="9" * 64)

    def test_profile_drift_is_denied(
        self, pg: dict[str, str], attested: dict[str, Any]
    ) -> None:
        with pytest.raises(PublicationAttestationInvalidError, match="profile_fingerprint"):
            verify(pg, attested, current_profile_fingerprint="9" * 64)

    def test_manifest_drift_is_denied(
        self, pg: dict[str, str], attested: dict[str, Any]
    ) -> None:
        with pytest.raises(PublicationAttestationInvalidError, match="manifest_digest"):
            verify(pg, attested, current_manifest_digest="9" * 64)

    def test_publication_review_dismissal_is_denied(
        self, pg: dict[str, str], attested: dict[str, Any], github: LocalGitHub
    ) -> None:
        github.dismiss_reviews(PUB_PR)
        with pytest.raises(PublicationAttestationInvalidError, match="no longer approved"):
            verify(pg, attested)

    def test_publication_pr_closure_is_denied(
        self, pg: dict[str, str], attested: dict[str, Any], github: LocalGitHub
    ) -> None:
        github.close_pr(PUB_PR)
        with pytest.raises(PublicationAttestationInvalidError, match="no longer approved"):
            verify(pg, attested)

    def test_scope_authorization_revocation_is_denied(
        self, pg: dict[str, str], attested: dict[str, Any], github: LocalGitHub
    ) -> None:
        """La révocation du scope LOT41A invalide la publication — sans
        aucune écriture sur la table d'attestation."""
        github.dismiss_reviews(AUTH_PR)
        with pytest.raises(PublicationAttestationInvalidError, match="no longer verifies live"):
            verify(pg, attested)

    def test_an_invalidated_attestation_stays_invalidated(
        self, pg: dict[str, str], attested: dict[str, Any]
    ) -> None:
        """L'invalidation détectée est persistée pour l'audit : la
        vérification suivante n'a même plus d'attestation active."""
        with pytest.raises(PublicationAttestationInvalidError):
            verify(pg, attested, current_content_sha256="9" * 64)
        with pytest.raises(PublicationAttestationInvalidError, match="no active"):
            verify(pg, attested)


class TestRetrievalEligibleAnchor:
    def test_the_transition_is_never_attempted_when_verification_fails(
        self, pg: dict[str, str], attested: dict[str, Any], github: LocalGitHub
    ) -> None:
        github.close_pr(PUB_PR)
        with psycopg.connect(superuser_dsn(pg)) as conn:
            with pytest.raises(PublicationAttestationInvalidError):
                attempt_retrieval_eligible_transition(
                    conn,
                    resource_id=attested["resource_id"],
                    run_id=uuid.uuid4(),
                    expected_version=1,
                    actor="test",
                    current_content_sha256=content_sha(pg, attested["artifact_id"]),
                    current_profile_fingerprint=PROFILE_FINGERPRINT,
                    current_manifest_digest=MANIFEST_DIGEST,
                )
        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT resource_state FROM ingestion_control.resources WHERE resource_id = %s",
                (attested["resource_id"],),
            )
            assert cur.fetchone()[0] != ResourceState.RETRIEVAL_ELIGIBLE.value


class TestLivePipelineCannotYetPublish:
    """État honnête du pipeline : `LOT42_LIVE_PIPELINE_WIRED=false`.

    Le classifieur de ce lot laisse niveau/voie/programme « non vérifiés »
    (placeholder documenté, remédiation PR#90). Toute ressource porte donc
    des motifs de rejet, le gate est négatif, et **aucune publication n'est
    possible via le pipeline vivant** — quelle que soit la richesse du
    contenu. Ce test fixe cet état pour qu'il ne puisse pas changer sans
    qu'on s'en aperçoive."""

    def test_even_rich_content_does_not_pass_the_live_gate(
        self, pg: dict[str, str], tmp_path: Path
    ) -> None:
        resource_id, artifact_id = run_real_pipeline(pg, tmp_path)
        with psycopg.connect(superuser_dsn(pg)) as conn:
            facts = collect_publication_facts(
                conn, resource_id=resource_id, artifact_id=artifact_id
            )
        assert facts.quality_passed is False
        assert facts.gate_passed is False

    def test_the_negative_verdict_is_nonetheless_durable(
        self, pg: dict[str, str], tmp_path: Path
    ) -> None:
        """Un gate négatif ne produit aucune transition d'état ; sans
        l'événement dédié, « pas de preuve de succès » serait
        indistinguable de « pas de preuve du tout »."""
        resource_id, _ = run_real_pipeline(pg, tmp_path)
        with psycopg.connect(superuser_dsn(pg)) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM ingestion_control.workflow_events "
                "WHERE resource_id = %s AND event_type = 'PUBLICATION_GATE_EVALUATED'",
                (resource_id,),
            )
            rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0][0]["gate_passed"] is False
        assert rows[0][0]["decision"] == "REJECT"
