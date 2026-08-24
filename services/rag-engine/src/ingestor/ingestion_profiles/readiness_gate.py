"""Gate de readiness au runtime — défense en profondeur (ADR-0036).

**Ce que ce gate n'est pas.** Ce n'est pas une protection cryptographique
contre l'administrateur de l'hôte. Un root hostile ou compromis peut
remplacer ce fichier, patcher ce module, changer l'environnement ou
parler directement à PostgreSQL. Le modèle de menace d'ADR-0036 place
explicitement le root de l'hôte dans la base de confiance.

**Ce qu'il ferme réellement**, et c'est utile :

* le déploiement normal privé de preuve — un worker démarré sans qu'aucune
  chaîne de promotion n'ait abouti ;
* l'erreur de configuration — un manifeste d'un autre environnement, d'une
  autre release, ou dont le gate H2 n'était pas passant ;
* la substitution par un processus non privilégié — le fichier est refusé
  s'il est inscriptible par autre chose que son propriétaire ;
* le démarrage incomplet — un worker qui tournerait avec une partie
  seulement de sa chaîne d'autorité.

**Où il s'applique.** Avant le démarrage du worker, et **de nouveau** avant
chaque création de job de mutation. Le second point n'est pas redondant :
un manifeste retiré ou remplacé après le démarrage ne serait jamais vu par
un contrôle qui ne s'exécuterait qu'une fois, et la création de job est la
mutation qui compte.

**Il ne duplique aucun parseur.** Toute la validation vient du contrat
partagé ``nexus_contracts.production_readiness`` — le même que celui
qu'utilisera le wrapper de déploiement. Deux implémentations finiraient
par diverger, et un manifeste interprété différemment par le vérificateur
et par l'exécutant n'est plus une preuve.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeAlias

from nexus_contracts.authorization_set import (
    AuthorizationSetError,
    VerifiedAuthorizationSetV1,
    VerifiedProfileFactV1,
    parse_authorization_set,
)
from nexus_contracts.h2_coverage_evidence import parse_h2_coverage_evidence_v2
from nexus_contracts.production_readiness import (
    PRODUCTION_ENVIRONMENT,
    ProductionReadinessError,
    ProductionReadinessManifestV1,
    ProductionReadinessManifestV2,
    parse_production_readiness_trust_anchor,
    require_manifest_matches_release,
    verify_production_readiness_manifest,
    verify_production_readiness_manifest_v2,
)

from ingestor.ingestion_profiles import release_verification_v2 as rv2
from ingestor.ingestion_worker.authorization_mapping import (
    AuthorizationMapping,
    build_authorization_mapping,
)

#: Chemin du manifeste déposé par le wrapper de déploiement, monté en
#: lecture seule dans le conteneur.
MANIFEST_PATH_ENV = "NEXUS_READINESS_MANIFEST_PATH"
AUTHORIZATION_SET_PATH_ENV = "NEXUS_AUTHORIZATION_SET_PATH"
V2_MATERIAL_ROOT_ENV = "NEXUS_V2_RELEASE_MATERIAL_ROOT"
EXPECTED_PROTOCOL_ENV = "NEXUS_EXPECTED_READINESS_PROTOCOL"

#: Commit de merge que ce déploiement croit exécuter. Injecté par le
#: wrapper ; comparé au manifeste signé.
RELEASE_SHA_ENV = "NEXUS_RELEASE_SHA"

#: ``production`` (défaut, fail-closed) ou ``rehearsal``.
ENVIRONMENT_ENV = "NEXUS_ENVIRONMENT"

#: Ancre publique de readiness. En production, **jamais** substituable par
#: un argument : le chemin est gouverné et versionné dans le dépôt.
GOVERNED_TRUST_ANCHOR_PATH = "governance/trust-anchors/production-readiness-v1.json"

#: Ancre de rehearsal, explicitement distincte.
#:
#: L'isolation entre répétition et production se fait par **identité du
#: fichier d'ancre**, pas par une étiquette dans le manifeste. Le contrat
#: ``NEXUS-PRODUCTION-READINESS-V1`` fixe ``environment="production"`` par
#: littéral, et ADR-0036 interdit de l'affaiblir pour accueillir une
#: répétition : un manifeste et une répétition de manifeste doivent rester
#: discernables. La conséquence est nette — le mode production ne lit
#: **que** le chemin gouverné, donc une clé de répétition déclarée dans un
#: autre fichier n'a aucun moyen d'être consultée en production, quel que
#: soit ce qu'elle affirme sur elle-même.
REHEARSAL_TRUST_ANCHOR_ENV = "NEXUS_READINESS_REHEARSAL_TRUST_ANCHOR"

#: Racine gouvernée, dérivée de l'emplacement de CE fichier — aucun
#: override, par aucun moyen. Même discipline que le gate H2-B côté
#: rag-pedago : une racine redirigeable rendrait « ancre gouvernée »
#: dépourvu de sens.
#:
#: Ce fichier vit à ``services/rag-engine/src/ingestor/ingestion_profiles/``,
#: soit 5 niveaux sous la racine du dépôt (ingestion_profiles, ingestor,
#: src, rag-engine, services) — jamais 3, qui désignerait ``services/
#: rag-engine`` lui-même et ferait échouer la résolution des marqueurs sur
#: tout checkout réel (cf. le même calcul pour le gate H2-B, ``rag_pedago/
#: imports/h2b_coverage_report.py``, 4 niveaux sous sa racine avec un seul
#: répertoire de paquet entre le fichier et le service).
_GOVERNED_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]

#: Marqueurs du dépôt. La dérivation par remontée n'est vraie que dans un
#: checkout ; installée ailleurs, elle désignerait un répertoire
#: arbitraire où une ancre déposée ferait autorité.
_GOVERNED_ROOT_MARKERS = ("services/rag-engine", "docs/adr")

_FAILURE_PREFIX = "WORKER_READINESS_GATE_FAILED"


class ReadinessGateError(RuntimeError):
    """Le manifeste ne prouve pas cette release — refus, jamais un défaut
    permissif."""


@dataclass(frozen=True)
class ReadinessGateResult:
    manifest: ProductionReadinessManifestV1 | ProductionReadinessManifestV2
    manifest_path: Path
    environment: str
    release_sha: str
    authorization_mapping: AuthorizationMapping | None = None
    verified_authorization_set: VerifiedAuthorizationSetV1 | None = None
    authorization_context: RuntimeAuthorizationContext | None = None


@dataclass(frozen=True)
class RuntimeAuthorizationContext:
    """Identité V2 immutable accompagnée de sa revérification fraîche.

    Le callable regèle les chemins gouvernés et rejoue la frontière globale à
    l'heure UTC effective. Le mapping initial n'est jamais accepté si cette
    nouvelle preuve diverge, même si son set reste syntaxiquement valide.
    """

    mapping: AuthorizationMapping
    _refresh: Callable[[], AuthorizationMapping]

    def reverify(self) -> AuthorizationMapping:
        refreshed = self._refresh()
        if refreshed != self.mapping:
            raise _fail(
                "runtime authorization identity changed after startup"
            )
        return refreshed


RuntimeV2ReleaseMaterial: TypeAlias = rv2.V2ReleaseMaterial


def _fail(reason: str) -> ReadinessGateError:
    return ReadinessGateError(f"{_FAILURE_PREFIX}: {reason}")


def _governed_anchor_path() -> Path:
    root = _GOVERNED_REPOSITORY_ROOT
    for marker in _GOVERNED_ROOT_MARKERS:
        if not (root / marker).exists():
            raise _fail(
                f"{root} does not look like the Nexus repository checkout "
                f"(missing {marker}); the governed readiness anchor cannot be "
                "resolved from an arbitrary directory"
            )
    candidate = root / GOVERNED_TRUST_ANCHOR_PATH
    walked = root
    for part in Path(GOVERNED_TRUST_ANCHOR_PATH).parts:
        walked = walked / part
        if walked.is_symlink():
            raise _fail(
                f"{walked} is a symlink — a governed path never redirects, on "
                "any of its components"
            )
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    if resolved != resolved_root / GOVERNED_TRUST_ANCHOR_PATH:
        raise _fail(
            f"resolved anchor {resolved} is not the canonical governed path"
        )
    return candidate


def _read_manifest_file(path: Path) -> bytes:
    """Lit le manifeste avec les refus de substitution.

    Les permissions sont vérifiées parce que le risque couvert est la
    substitution par un processus **non privilégié** : un fichier
    inscriptible par le groupe ou par tous n'est pas une preuve."""
    if path.is_symlink():
        raise _fail(
            f"{path} is a symlink — the readiness manifest is never followed "
            "through a redirection"
        )
    if not path.exists():
        raise _fail(
            f"{path} does not exist — this deployment carries no proof that a "
            "governed promotion produced it"
        )
    if not path.is_file():
        raise _fail(f"{path} is not a regular file")
    mode = path.stat().st_mode
    if mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise _fail(
            f"{path} is group- or world-writable — a manifest any process can "
            "rewrite proves nothing"
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise _fail(f"cannot read {path}: {exc}") from exc


def _resolve_anchor_bytes(environment: str) -> bytes:
    if environment == PRODUCTION_ENVIRONMENT:
        anchor = _governed_anchor_path()
        if not anchor.is_file():
            raise _fail(
                f"the governed production readiness anchor {anchor} does not "
                "exist — an unanchored signature proves nothing"
            )
        return anchor.read_bytes()

    raw_path = os.environ.get(REHEARSAL_TRUST_ANCHOR_ENV, "").strip()
    if not raw_path:
        raise _fail(
            f"{REHEARSAL_TRUST_ANCHOR_ENV} is required in rehearsal mode — a "
            "rehearsal never borrows the production anchor"
        )
    candidate = Path(raw_path)
    if not candidate.is_file():
        raise _fail(f"rehearsal readiness anchor {candidate} does not exist")
    return candidate.read_bytes()


def _signed_protocol(raw: bytes) -> str:
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail(f"readiness manifest is not valid UTF-8 JSON: {exc}") from exc
    manifest = document.get("manifest") if isinstance(document, dict) else None
    protocol = manifest.get("protocol_version") if isinstance(manifest, dict) else None
    if protocol not in {
        "NEXUS-PRODUCTION-READINESS-V1",
        "NEXUS-PRODUCTION-READINESS-V2",
    }:
        raise _fail(
            "readiness manifest protocol_version is not an explicitly supported "
            f"readiness protocol: {protocol!r}"
        )
    return str(protocol)


def _runtime_bytes(path: Path, *, label: str) -> bytes:
    absolute = path.absolute()
    walked = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        walked /= part
        if walked.is_symlink():
            raise _fail(f"{label} path component {walked} is a symlink")
    if not absolute.is_file():
        raise _fail(f"{label} must be a regular non-symlink file at {path}")
    try:
        descriptor = os.open(absolute, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise _fail(f"cannot read {label} at {path}: {exc}") from exc


def _runtime_verified_profiles(raw: bytes) -> tuple[VerifiedProfileFactV1, ...]:
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail(f"verified profiles is invalid: {exc}") from exc
    records = document.get("profiles") if isinstance(document, dict) else None
    if (
        not isinstance(document, dict)
        or set(document) != {"profile_manifest_digest", "profiles"}
        or not isinstance(records, list)
        or not records
    ):
        raise _fail("verified profiles has an unexpected structure")
    facts: list[VerifiedProfileFactV1] = []
    fields = set(VerifiedProfileFactV1.model_fields)
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) not in (
            fields,
            fields | {"source_path"},
        ):
            raise _fail(f"verified profile #{index} has unexpected fields")
        facts.append(
            VerifiedProfileFactV1.model_validate(
                {name: record[name] for name in fields}
            )
        )
    return tuple(facts)


def _runtime_required_set(raw: bytes) -> tuple[str, ...]:
    if not raw or not raw.endswith(b"\n") or b"\r" in raw:
        raise _fail("authority-required set must use canonical LF-final lines")
    try:
        values = tuple(raw[:-1].decode("ascii").split("\n"))
    except UnicodeDecodeError as exc:
        raise _fail("authority-required set must be ASCII") from exc
    if (
        any(len(value) != 64 or any(c not in "0123456789abcdef" for c in value) for value in values)
        or tuple(sorted(values)) != values
        or len(values) != len(set(values))
    ):
        raise _fail("authority-required set is not canonical")
    return values


def _load_runtime_v2_material_from_environment(
    manifest: ProductionReadinessManifestV2,
) -> RuntimeV2ReleaseMaterial:
    set_path_raw = os.environ.get(AUTHORIZATION_SET_PATH_ENV, "").strip()
    root_raw = os.environ.get(V2_MATERIAL_ROOT_ENV, "").strip()
    if not set_path_raw or not root_raw:
        raise _fail(
            f"V2 readiness requires {AUTHORIZATION_SET_PATH_ENV} and "
            f"{V2_MATERIAL_ROOT_ENV}"
        )
    root = Path(root_raw)
    if root.is_symlink() or not root.is_dir():
        raise _fail("V2 release material root must be a regular non-symlink directory")
    authorization_set_raw = _runtime_bytes(
        Path(set_path_raw), label="authorization set"
    )
    try:
        authorization_set = parse_authorization_set(authorization_set_raw)
    except AuthorizationSetError as exc:
        raise _fail(str(exc)) from exc
    release_files = {
        relative: _runtime_bytes(root / "release-material" / relative, label=relative)
        for member in authorization_set.members
        for relative in (member.authorization_path, member.review_binding_path)
    }
    read = lambda name: _runtime_bytes(root / name, label=name)  # noqa: E731
    h2_coverage_raw = read("h2-coverage.json")
    try:
        coverage = parse_h2_coverage_evidence_v2(h2_coverage_raw)
    except Exception as exc:  # noqa: BLE001 - frontière de chargement
        raise _fail(f"H2 coverage cannot derive runtime material: {exc}") from exc
    try:
        bundle_document = json.loads(read("bundle_manifest.json").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail(f"deployment bundle manifest is invalid: {exc}") from exc
    release_scope_git_paths = (
        bundle_document.get("v2_release_scope_git_paths")
        if isinstance(bundle_document, dict)
        else None
    )
    expected_roles = {
        "profile_proposal_matrix_path",
        "accepted_placements_path",
        "release_registry_path",
        "expected_contents_path",
        "verified_profiles_path",
        "profile_manifest_path",
    }
    if (
        not isinstance(release_scope_git_paths, dict)
        or set(release_scope_git_paths) != expected_roles
        or any(not isinstance(value, str) for value in release_scope_git_paths.values())
    ):
        raise _fail("deployment bundle has no exact release-scope path roles")
    return RuntimeV2ReleaseMaterial(
        authorization_set_raw=authorization_set_raw,
        release_files=release_files,
        review_binding_trust_anchor_raw=read(
            "evidence/review_binding_trust_anchor.bin"
        ),
        trusted_reviewers_raw=read("evidence/trusted_reviewers.bin"),
        revocation_registry_raw=read("authorization-revocations.json"),
        release_scope_placement_raw=read("release-scope-placement.jsonl"),
        verified_profiles=_runtime_verified_profiles(read("verified-profiles.json")),
        profile_manifest_raw=read("profile-manifest.yml"),
        authority_required_content_sha256=_runtime_required_set(
            read("authority-required.txt")
        ),
        h2_coverage_raw=h2_coverage_raw,
        h2_evidence_bundle_raw=read("h2-evidence.json"),
        promotion_evidence_raw=read("promotion-evidence.json"),
        evidence_files={
            name: read(f"evidence/{name}.bin")
            for name in coverage.input_file_digests
        },
        release_scope_source_blobs={
            path: read(f"release-scope-sources/{path}")
            for path in coverage.release_scope_source_blob_digests
        },
        release_scope_git_paths={
            str(key): str(value) for key, value in release_scope_git_paths.items()
        },
        sealed_manifest_raw=read("sealed-manifest.txt"),
        now=datetime.now(UTC),
        merge_sha=manifest.merge_sha,
        merge_tree_sha=manifest.merge_tree_sha,
    )


def _verify_v2_material(
    material: RuntimeV2ReleaseMaterial,
) -> tuple[VerifiedAuthorizationSetV1, AuthorizationMapping]:
    try:
        verified = rv2.verify_v2_release_material(
            rv2.V2ReleaseMaterial.from_signing_material(material)
        )
        mapping = build_authorization_mapping(
            authorization_set_bytes=verified.verified_authorization_set.authorization_set_bytes,
            expected_authorization_set_digest=(
                verified.verified_authorization_set.authorization_set_digest
            ),
            authority_required_content_sha256=(
                material.authority_required_content_sha256
            ),
        )
    except rv2.V2ReleaseVerificationError as exc:
        raise _fail(f"V2 authorization material refused: {exc}") from exc
    return verified.verified_authorization_set, mapping


def enforce_readiness_gate(
    *,
    manifest_path: Path | None = None,
    release_sha: str | None = None,
    environment: str | None = None,
    v2_material: RuntimeV2ReleaseMaterial | None = None,
    expected_protocol: str | None = None,
) -> ReadinessGateResult:
    """Refuse tout ce qui ne prouve pas *cette* release.

    Les paramètres existent pour les tests et pour un appelant qui a déjà
    lu son environnement ; ils ne peuvent pas désigner une **ancre**, qui
    reste gouvernée en production. Aucune valeur de repli : chaque absence
    est un refus."""
    resolved_environment = (
        environment
        if environment is not None
        else os.environ.get(ENVIRONMENT_ENV, PRODUCTION_ENVIRONMENT).strip()
        or PRODUCTION_ENVIRONMENT
    )
    resolved_expected_protocol = (
        expected_protocol
        if expected_protocol is not None
        else os.environ.get(EXPECTED_PROTOCOL_ENV, "").strip()
    )
    if resolved_expected_protocol not in {
        "NEXUS-PRODUCTION-READINESS-V1",
        "NEXUS-PRODUCTION-READINESS-V2",
    }:
        raise _fail(
            f"{EXPECTED_PROTOCOL_ENV} must explicitly pin V1 or V2; got "
            f"{resolved_expected_protocol!r}"
        )
    if resolved_environment not in (PRODUCTION_ENVIRONMENT, "rehearsal"):
        raise _fail(
            f"{ENVIRONMENT_ENV} must be 'production' or 'rehearsal', got "
            f"{resolved_environment!r}"
        )

    raw_manifest_path = (
        str(manifest_path)
        if manifest_path is not None
        else os.environ.get(MANIFEST_PATH_ENV, "").strip()
    )
    if not raw_manifest_path:
        raise _fail(
            f"{MANIFEST_PATH_ENV} is not configured — a worker never starts "
            "without naming the readiness manifest it runs under"
        )

    resolved_release_sha = (
        release_sha
        if release_sha is not None
        else os.environ.get(RELEASE_SHA_ENV, "").strip()
    )
    if not resolved_release_sha:
        raise _fail(
            f"{RELEASE_SHA_ENV} is not configured — without it the manifest "
            "cannot be tied to the revision actually running"
        )

    raw = _read_manifest_file(Path(raw_manifest_path))
    anchor_bytes = _resolve_anchor_bytes(resolved_environment)

    material_loaded_from_environment = False
    try:
        anchor = parse_production_readiness_trust_anchor(anchor_bytes)
        # ``environment`` reste ``production`` dans les deux modes : c'est
        # la valeur que le contrat impose au manifeste, et l'isolation
        # d'une répétition tient au fichier d'ancre consulté, jamais à un
        # assouplissement du contrat.
        protocol = _signed_protocol(raw)
        if protocol != resolved_expected_protocol:
            raise _fail(
                f"signed readiness protocol {protocol!r} differs from expected "
                f"{resolved_expected_protocol!r}"
            )
        if protocol == "NEXUS-PRODUCTION-READINESS-V1":
            if v2_material is not None:
                raise _fail("legacy V1 readiness never accepts V2 release material")
            manifest = verify_production_readiness_manifest(
                raw, trust_anchor=anchor, environment=PRODUCTION_ENVIRONMENT
            )
            verified_set = None
            authorization_mapping = None
        else:
            manifest = verify_production_readiness_manifest_v2(
                raw, trust_anchor=anchor, environment=PRODUCTION_ENVIRONMENT
            )
            if v2_material is None:
                v2_material = _load_runtime_v2_material_from_environment(manifest)
                material_loaded_from_environment = True
            verified_set, authorization_mapping = _verify_v2_material(v2_material)
            if manifest.authorization_set_digest != verified_set.authorization_set_digest:
                raise _fail("signed readiness authorization set digest mismatch")
            if manifest.revocation_registry_digest != hashlib.sha256(
                v2_material.revocation_registry_raw
            ).hexdigest():
                raise _fail("signed readiness revocation registry digest mismatch")
            if manifest.h2b_report_digest != hashlib.sha256(
                v2_material.promotion_evidence_raw
            ).hexdigest():
                raise _fail("signed readiness promotion digest mismatch")
            verified_v2 = rv2.verify_v2_release_material(
                rv2.V2ReleaseMaterial.from_signing_material(v2_material)
            )
            coverage = verified_v2.h2_coverage
            bundle = verified_v2.h2_bundle
            promotion = verified_v2.promotion
            release_links = {
                "repository": (
                    manifest.repository,
                    bundle.repository,
                    promotion.repository,
                ),
                "merge_sha": (
                    manifest.merge_sha,
                    coverage.git_commit,
                    bundle.merge_sha,
                    promotion.merge_sha,
                ),
                "merge_tree_sha": (
                    manifest.merge_tree_sha,
                    bundle.merge_tree_sha,
                    promotion.merge_tree_sha,
                ),
                "pr_number": (
                    manifest.pr_number,
                    bundle.pull_request_number,
                    promotion.pull_request_number,
                ),
                "pr_head_sha": (
                    manifest.pr_head_sha,
                    bundle.pr_head_sha,
                    promotion.pr_head_sha,
                ),
                "pr_head_tree_sha": (
                    manifest.pr_head_tree_sha,
                    bundle.pr_head_tree_sha,
                    promotion.pr_head_tree_sha,
                ),
                "catalog_digest": (
                    manifest.catalog_digest,
                    hashlib.sha256(v2_material.evidence_files["catalog"]).hexdigest(),
                ),
                "trust_anchor_digest": (
                    manifest.trust_anchor_digest,
                    hashlib.sha256(
                        v2_material.review_binding_trust_anchor_raw
                    ).hexdigest(),
                ),
                "sealed_manifest_digest": (
                    manifest.sealed_manifest_digest,
                    hashlib.sha256(v2_material.sealed_manifest_raw).hexdigest(),
                ),
                "workflow_path": (
                    manifest.workflow_path,
                    promotion.promotion_workflow_path,
                ),
                "workflow_ref": (
                    manifest.workflow_ref,
                    promotion.promotion_workflow_ref,
                ),
                "run_id": (manifest.run_id, promotion.promotion_run_id),
                "run_attempt": (
                    manifest.run_attempt,
                    promotion.promotion_run_attempt,
                ),
            }
            mismatches = [
                label
                for label, values in release_links.items()
                if any(value != values[0] for value in values[1:])
            ]
            if mismatches:
                raise _fail(
                    f"signed readiness release identity mismatch: {sorted(mismatches)!r}"
                )
        require_manifest_matches_release(
            manifest, release_sha=resolved_release_sha
        )
    except (ProductionReadinessError, AuthorizationSetError) as exc:
        raise _fail(str(exc)) from exc

    authorization_context: RuntimeAuthorizationContext | None = None
    if authorization_mapping is not None and v2_material is not None:
        initial_mapping = authorization_mapping
        initial_readiness_digest = hashlib.sha256(raw).hexdigest()

        def refresh() -> AuthorizationMapping:
            current_readiness = _read_manifest_file(Path(raw_manifest_path))
            if hashlib.sha256(current_readiness).hexdigest() != initial_readiness_digest:
                raise _fail("signed readiness bytes changed after startup")
            refreshed_material = (
                None
                if material_loaded_from_environment
                else replace(v2_material, now=datetime.now(UTC))
            )
            result = enforce_readiness_gate(
                manifest_path=Path(raw_manifest_path),
                release_sha=resolved_release_sha,
                environment=resolved_environment,
                v2_material=refreshed_material,
                expected_protocol=resolved_expected_protocol,
            )
            if result.authorization_mapping is None:
                raise _fail("V2 refresh produced no authorization mapping")
            return result.authorization_mapping

        authorization_context = RuntimeAuthorizationContext(
            mapping=initial_mapping,
            _refresh=refresh,
        )

    return ReadinessGateResult(
        manifest=manifest,
        manifest_path=Path(raw_manifest_path),
        environment=resolved_environment,
        release_sha=resolved_release_sha,
        authorization_mapping=authorization_mapping,
        verified_authorization_set=verified_set,
        authorization_context=authorization_context,
    )


__all__ = [
    "ENVIRONMENT_ENV",
    "EXPECTED_PROTOCOL_ENV",
    "AUTHORIZATION_SET_PATH_ENV",
    "GOVERNED_TRUST_ANCHOR_PATH",
    "MANIFEST_PATH_ENV",
    "REHEARSAL_TRUST_ANCHOR_ENV",
    "RELEASE_SHA_ENV",
    "ReadinessGateError",
    "ReadinessGateResult",
    "RuntimeAuthorizationContext",
    "RuntimeV2ReleaseMaterial",
    "V2_MATERIAL_ROOT_ENV",
    "enforce_readiness_gate",
]
