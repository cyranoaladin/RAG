"""Validation locale et fail-closed d'un manifeste de cutover moteur."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .legacy_convergence import (
    ChromaInventory,
    ImageArtifact,
    LegacyCaptureError,
    PgvectorInventory,
    ReconstructibleAssets,
    SQLiteSnapshot,
    _assets,
    _chroma,
    _pgvector,
    _sqlite_snapshot,
)

_PROTOCOL_VERSION = "NEXUS-ENGINE-CUTOVER-V1"
_GIT_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_SENSITIVE_HINT = re.compile(
    r"(?:api[_-]?key|bearer|password|secret|token)", re.IGNORECASE
)
_CAPTURE_ORDER = (
    "chroma",
    "catalog.sqlite",
    "drive_sync_state.db",
    "uploads",
)
_CAPTURE_VALIDITY = timedelta(hours=24)
_CAPTURE_CONTEXTS = frozenset({"SYNTHETIC_TEST", "OPERATOR_READ_ONLY_CAPTURE"})
_FACT_EVIDENCE_TYPES = {
    "snapshot_restored_verified": "SNAPSHOT_RESTORE_VERIFICATION",
    "real_parity_executed": "REAL_PARITY_EXECUTION",
    "restore_rehearsal_verified": "RESTORE_REHEARSAL_VERIFICATION",
    "traffic_rollback_tested": "TRAFFIC_ROLLBACK_TEST",
    "cutover_authorized": "CUTOVER_AUTHORIZATION",
}


class EngineCutoverError(ValueError):
    """Le manifeste ne fournit pas une preuve de cutover valide."""


@dataclass(frozen=True)
class ReleaseIdentity:
    """Release et images immuables engagées dans le manifeste."""

    git_commit: str
    images: tuple[ImageArtifact, ...]


@dataclass(frozen=True)
class EngineAInventory:
    """Inventaire reconstructible du moteur A."""

    chroma: ChromaInventory
    catalog_sqlite: SQLiteSnapshot
    drive_sync_sqlite: SQLiteSnapshot
    assets: ReconstructibleAssets


@dataclass(frozen=True)
class PgvectorBackup:
    """Backup pgvector scellé, sans primitive de restauration."""

    method: str
    integrity_check: str
    digest_sha256: str


@dataclass(frozen=True)
class EngineBInventory:
    """Inventaire et backup reconstructibles du moteur B."""

    pgvector: PgvectorInventory
    backup: PgvectorBackup


@dataclass(frozen=True)
class SnapshotState:
    """Comptes et digests d'un état A observé."""

    chroma_count: int
    catalog_count: int
    drive_sync_count: int
    uploads_count: int
    chroma_digest_sha256: str
    catalog_digest_sha256: str
    drive_sync_digest_sha256: str
    uploads_digest_sha256: str


@dataclass(frozen=True)
class QuiescenceProof:
    """Preuve que les producteurs A sont arrêtés pendant la capture."""

    captured_at: str
    valid_until: str
    capture_mode: str
    writers_disabled: bool
    scheduled_tasks_disabled: bool
    capture_order: tuple[str, ...]
    mutation_free_until_decision: bool
    before: SnapshotState
    after: SnapshotState


@dataclass(frozen=True)
class CutoverTopology:
    """Cibles explicites de continuité, canary et rollback."""

    active_target: str
    canary_target: str
    rollback_target: str


@dataclass(frozen=True)
class SmokeProbe:
    """Description bornée d'un smoke externe, jamais exécuté ici."""

    check_id: str
    target: str
    timeout_seconds: int
    max_attempts: int
    evidence_sha256: str


@dataclass(frozen=True)
class EvidenceReference:
    """Référence scellée d'un fait d'exécution réelle."""

    evidence_type: str
    reference_id: str
    digest_sha256: str


@dataclass(frozen=True)
class CutoverGate:
    """État d'un gate de cutover sans synonyme de readiness."""

    name: str
    satisfied: bool
    evidence: EvidenceReference | None


@dataclass(frozen=True)
class EngineCutoverDecision:
    """Résultat local d'une validation de cutover."""

    capture_context: str
    release: ReleaseIdentity
    engine_a: EngineAInventory
    engine_b: EngineBInventory
    quiescence: QuiescenceProof
    topology: CutoverTopology
    smokes: tuple[SmokeProbe, ...]
    snapshot_declared: bool
    gates: tuple[CutoverGate, ...]
    verdict: str


def _mapping(
    value: Any,
    *,
    field: str,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or not required <= frozenset(value)
        or frozenset(value) - required - optional
    ):
        raise EngineCutoverError(f"{field} schema is invalid")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise EngineCutoverError("cutover manifest contains a duplicate key")
        document[key] = value
    return document


def _release(document: dict[str, Any]) -> ReleaseIdentity:
    release = _mapping(
        document.get("release"),
        field="release",
        required=frozenset({"git_commit", "images"}),
    )
    git_commit = release.get("git_commit")
    if not isinstance(git_commit, str) or _GIT_COMMIT.fullmatch(git_commit) is None:
        raise EngineCutoverError("release commit is invalid")
    raw_images = release.get("images")
    if not isinstance(raw_images, list) or not raw_images:
        raise EngineCutoverError("release images are invalid")
    images: list[ImageArtifact] = []
    names: set[str] = set()
    for raw_image in raw_images:
        image = _mapping(
            raw_image,
            field="release image",
            required=frozenset({"name", "digest"}),
        )
        name = image.get("name")
        digest = image.get("digest")
        if (
            not isinstance(name, str)
            or not name
            or name in names
            or not isinstance(digest, str)
            or not digest.startswith("sha256:")
            or _SHA256.fullmatch(digest.removeprefix("sha256:")) is None
        ):
            raise EngineCutoverError("release image is invalid")
        names.add(name)
        images.append(ImageArtifact(name=name, digest=digest))
    return ReleaseIdentity(git_commit=git_commit, images=tuple(images))


def _engine_a(document: dict[str, Any]) -> EngineAInventory:
    engine_a = _mapping(
        document.get("engine_a"),
        field="engine A",
        required=frozenset(
            {"chroma", "catalog_sqlite", "drive_sync_sqlite", "assets"}
        ),
    )
    try:
        chroma = _chroma(engine_a)
        catalog_sqlite = _sqlite_snapshot(
            engine_a.get("catalog_sqlite"), expected_identity="catalog.sqlite"
        )
        drive_sync_sqlite = _sqlite_snapshot(
            engine_a.get("drive_sync_sqlite"),
            expected_identity="drive_sync_state.db",
        )
        assets = _assets(engine_a["assets"])
    except LegacyCaptureError as exc:
        raise EngineCutoverError(str(exc)) from None
    return EngineAInventory(
        chroma=chroma,
        catalog_sqlite=catalog_sqlite,
        drive_sync_sqlite=drive_sync_sqlite,
        assets=assets,
    )


def _engine_b(document: dict[str, Any]) -> EngineBInventory:
    engine_b = _mapping(
        document.get("engine_b"),
        field="engine B",
        required=frozenset({"pgvector", "backup"}),
    )
    try:
        pgvector = _pgvector(engine_b)
    except LegacyCaptureError as exc:
        raise EngineCutoverError(str(exc)) from None
    backup = _mapping(
        engine_b.get("backup"),
        field="pgvector backup",
        required=frozenset({"method", "integrity_check", "digest_sha256"}),
    )
    if backup.get("method") != "pg_dump_custom":
        raise EngineCutoverError("pgvector backup method is invalid")
    if backup.get("integrity_check") != "verified":
        raise EngineCutoverError("pgvector backup integrity is invalid")
    digest = backup.get("digest_sha256")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise EngineCutoverError("pgvector backup digest is invalid")
    return EngineBInventory(
        pgvector=pgvector,
        backup=PgvectorBackup(
            method="pg_dump_custom",
            integrity_check="verified",
            digest_sha256=digest,
        ),
    )


def _snapshot_state(value: Any, *, field: str) -> SnapshotState:
    document = _mapping(
        value,
        field=field,
        required=frozenset(
            {
                "chroma_count",
                "catalog_count",
                "drive_sync_count",
                "uploads_count",
                "chroma_digest_sha256",
                "catalog_digest_sha256",
                "drive_sync_digest_sha256",
                "uploads_digest_sha256",
            }
        ),
    )

    def count(name: str) -> int:
        raw = document.get(name)
        if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
            raise EngineCutoverError(f"{field} count is invalid")
        return raw

    def digest(name: str) -> str:
        raw = document.get(name)
        if not isinstance(raw, str) or _SHA256.fullmatch(raw) is None:
            raise EngineCutoverError(f"{field} digest is invalid")
        return raw

    return SnapshotState(
        chroma_count=count("chroma_count"),
        catalog_count=count("catalog_count"),
        drive_sync_count=count("drive_sync_count"),
        uploads_count=count("uploads_count"),
        chroma_digest_sha256=digest("chroma_digest_sha256"),
        catalog_digest_sha256=digest("catalog_digest_sha256"),
        drive_sync_digest_sha256=digest("drive_sync_digest_sha256"),
        uploads_digest_sha256=digest("uploads_digest_sha256"),
    )


def _utc_instant(value: Any, *, field: str) -> tuple[str, datetime]:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise EngineCutoverError(f"{field} is invalid")
    try:
        instant = datetime.fromisoformat(f"{value.removesuffix('Z')}+00:00")
    except ValueError:
        raise EngineCutoverError(f"{field} is invalid") from None
    if instant.tzinfo != UTC:
        raise EngineCutoverError(f"{field} is invalid")
    return value, instant


def _quiescence(
    document: dict[str, Any],
    *,
    capture_context: str,
    now: datetime,
) -> QuiescenceProof:
    proof = _mapping(
        document.get("quiescence"),
        field="quiescence",
        required=frozenset(
            {
                "captured_at",
                "valid_until",
                "capture_mode",
                "writers_disabled",
                "scheduled_tasks_disabled",
                "capture_order",
                "mutation_free_until_decision",
                "before",
                "after",
            }
        ),
    )
    captured_at, captured = _utc_instant(
        proof.get("captured_at"), field="quiescence capture instant"
    )
    valid_until, expiry = _utc_instant(
        proof.get("valid_until"), field="quiescence expiry"
    )
    if expiry <= captured or expiry - captured > _CAPTURE_VALIDITY:
        raise EngineCutoverError("quiescence validity window is invalid")
    capture_mode = proof.get("capture_mode")
    expected_modes = {
        "SYNTHETIC_TEST": frozenset({"SYNTHETIC_TEST"}),
        "OPERATOR_READ_ONLY_CAPTURE": frozenset({"QUIESCED_SNAPSHOT", "LIVE"}),
    }
    if capture_mode not in expected_modes[capture_context]:
        raise EngineCutoverError("quiescence capture mode is invalid")
    if capture_context == "OPERATOR_READ_ONLY_CAPTURE" and not captured <= now <= expiry:
        raise EngineCutoverError("quiescence proof is not fresh")
    if proof.get("writers_disabled") is not True:
        raise EngineCutoverError("writers are not quiescent")
    if proof.get("scheduled_tasks_disabled") is not True:
        raise EngineCutoverError("scheduled tasks are not quiescent")
    raw_order = proof.get("capture_order")
    if not isinstance(raw_order, list) or tuple(raw_order) != _CAPTURE_ORDER:
        raise EngineCutoverError("capture order is invalid")
    if proof.get("mutation_free_until_decision") is not True:
        raise EngineCutoverError("capture mutation barrier is invalid")
    before = _snapshot_state(proof.get("before"), field="state before capture")
    after = _snapshot_state(proof.get("after"), field="state after capture")
    if before != after:
        raise EngineCutoverError("capture state is not stable")
    return QuiescenceProof(
        captured_at=captured_at,
        valid_until=valid_until,
        capture_mode=capture_mode,
        writers_disabled=True,
        scheduled_tasks_disabled=True,
        capture_order=_CAPTURE_ORDER,
        mutation_free_until_decision=True,
        before=before,
        after=after,
    )


def _topology(document: dict[str, Any]) -> CutoverTopology:
    topology = _mapping(
        document.get("topology"),
        field="cutover topology",
        required=frozenset({"active_target", "canary_target", "rollback_target"}),
    )
    active = topology.get("active_target")
    canary = topology.get("canary_target")
    rollback = topology.get("rollback_target")
    if (
        not isinstance(active, str)
        or active not in {"engine_a", "engine_b"}
        or not isinstance(canary, str)
        or canary not in {"engine_a", "engine_b"}
        or not isinstance(rollback, str)
        or rollback not in {"engine_a", "engine_b"}
    ):
        raise EngineCutoverError("cutover topology target is invalid")
    if canary == rollback:
        raise EngineCutoverError("canary and rollback targets must be distinct")
    return CutoverTopology(
        active_target=active,
        canary_target=canary,
        rollback_target=rollback,
    )


def _smokes(document: dict[str, Any]) -> tuple[SmokeProbe, ...]:
    raw_smokes = document.get("smokes")
    if not isinstance(raw_smokes, list) or not raw_smokes:
        raise EngineCutoverError("smoke probes are invalid")
    probes: list[SmokeProbe] = []
    identifiers: set[str] = set()
    for raw_probe in raw_smokes:
        probe = _mapping(
            raw_probe,
            field="smoke probe",
            required=frozenset(
                {
                    "check_id",
                    "target",
                    "timeout_seconds",
                    "max_attempts",
                    "evidence_sha256",
                }
            ),
        )
        check_id = probe.get("check_id")
        target = probe.get("target")
        timeout = probe.get("timeout_seconds")
        attempts = probe.get("max_attempts")
        evidence = probe.get("evidence_sha256")
        if (
            not isinstance(check_id, str)
            or _IDENTIFIER.fullmatch(check_id) is None
            or check_id in identifiers
            or target not in {"engine_a", "engine_b"}
            or not isinstance(timeout, int)
            or isinstance(timeout, bool)
            or not 1 <= timeout <= 60
            or not isinstance(attempts, int)
            or isinstance(attempts, bool)
            or not 1 <= attempts <= 10
            or not isinstance(evidence, str)
            or _SHA256.fullmatch(evidence) is None
        ):
            raise EngineCutoverError("smoke probe is invalid")
        identifiers.add(check_id)
        probes.append(
            SmokeProbe(
                check_id=check_id,
                target=target,
                timeout_seconds=timeout,
                max_attempts=attempts,
                evidence_sha256=evidence,
            )
        )
    return tuple(probes)


def _facts(document: dict[str, Any]) -> tuple[CutoverGate, ...]:
    facts = _mapping(
        document.get("facts"),
        field="cutover facts",
        required=frozenset(_FACT_EVIDENCE_TYPES),
    )
    gates: list[CutoverGate] = []
    for name, expected_evidence_type in _FACT_EVIDENCE_TYPES.items():
        fact = _mapping(
            facts.get(name),
            field=f"cutover fact {name}",
            required=frozenset({"value", "evidence"}),
        )
        value = fact.get("value")
        if not isinstance(value, bool):
            raise EngineCutoverError(f"cutover fact {name} is invalid")
        raw_evidence = fact.get("evidence")
        if not value:
            if raw_evidence is not None:
                raise EngineCutoverError(f"cutover fact {name} has unexpected evidence")
            gates.append(CutoverGate(name=name, satisfied=False, evidence=None))
            continue
        evidence = _mapping(
            raw_evidence,
            field=f"cutover fact {name} evidence",
            required=frozenset({"evidence_type", "reference_id", "digest_sha256"}),
        )
        evidence_type = evidence.get("evidence_type")
        reference_id = evidence.get("reference_id")
        digest = evidence.get("digest_sha256")
        if (
            evidence_type != expected_evidence_type
            or not isinstance(reference_id, str)
            or _IDENTIFIER.fullmatch(reference_id) is None
            or _SENSITIVE_HINT.search(reference_id) is not None
            or not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
        ):
            raise EngineCutoverError(f"cutover fact {name} lacks exact evidence")
        raise EngineCutoverError("positive execution facts are forbidden in Lot 2")
    return tuple(gates)


def _verdict(document: dict[str, Any]) -> str:
    verdict = document.get("verdict")
    if verdict in {"READY", "GO_LIVE_READY", "CUTOVER_READY"}:
        raise EngineCutoverError("readiness vocabulary is forbidden")
    if verdict != "NO_GO":
        raise EngineCutoverError("cutover verdict must be NO_GO")
    return "NO_GO"


def validate_engine_cutover(
    path: Path,
    *,
    now: datetime | None = None,
) -> EngineCutoverDecision:
    """Valider un manifeste local sans exécuter de primitive de bascule."""

    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise EngineCutoverError("cutover manifest is unavailable") from None
    if not isinstance(document, dict):
        raise EngineCutoverError("cutover manifest is invalid")
    _mapping(
        document,
        field="cutover manifest",
        required=frozenset(
            {
                "protocol_version",
                "capture_context",
                "release",
                "engine_a",
                "engine_b",
                "quiescence",
                "topology",
                "smokes",
                "snapshot_declared",
                "facts",
                "verdict",
            }
        ),
    )
    if document.get("protocol_version") != _PROTOCOL_VERSION:
        raise EngineCutoverError("cutover protocol is invalid")
    capture_context = document.get("capture_context")
    if capture_context not in _CAPTURE_CONTEXTS:
        raise EngineCutoverError("cutover context is invalid")
    reference_instant = now or datetime.now(UTC)
    if reference_instant.tzinfo != UTC:
        raise EngineCutoverError("reference instant is invalid")
    snapshot_declared = document.get("snapshot_declared")
    if not isinstance(snapshot_declared, bool):
        raise EngineCutoverError("snapshot declaration is invalid")
    quiescence = _quiescence(
        document,
        capture_context=capture_context,
        now=reference_instant,
    )
    if quiescence.capture_mode == "LIVE" and snapshot_declared:
        raise EngineCutoverError("live archive cannot declare a snapshot")
    return EngineCutoverDecision(
        capture_context=capture_context,
        release=_release(document),
        engine_a=_engine_a(document),
        engine_b=_engine_b(document),
        quiescence=quiescence,
        topology=_topology(document),
        smokes=_smokes(document),
        snapshot_declared=snapshot_declared,
        gates=_facts(document),
        verdict=_verdict(document),
    )
