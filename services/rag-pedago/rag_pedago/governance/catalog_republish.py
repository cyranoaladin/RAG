"""Republication gouvernée du catalogue candidat vers INGEST.

**Le problème résolu ici.** Deux constats identiques, documentés
indépendamment dans deux rapports de lot antérieurs
(``docs/reports/lot_fix_h2_evidence_workflow.md`` §6,
``docs/reports/lot_h2_authority_promotion.md`` §« Portée ») : le gate
H2-B/H2-F sait *reconnaître* qu'une autorité LOT41A-V2 réelle couvre un
candidat bloqué (``_promote_authority_cleared_candidates``, introduit par
la remédiation du « Finding C ») — mais cette reconnaissance n'existe
qu'en mémoire, pour la durée d'un rapport de couverture. Aucune étape ne
matérialisait un catalogue où ces candidats portent réellement
``disposition="INGEST"``. Un pipeline d'ingestion aval n'avait donc aucun
fichier réel à lire.

**Ce module ne recalcule aucun verdict.** Il réutilise, sans les
dupliquer, les mêmes fonctions que ``h2b_coverage_report.py`` — le
producteur du rapport de couverture H2 — pour charger et vérifier
l'évidence d'autorité (les trois couches d'ADR-0035 : structurelle,
sémantique, liaison de revue scellée) puis appliquer la même promotion.
Seule la destination change : au lieu d'alimenter un rapport agrégé, le
résultat déjà validé est sérialisé et écrit sous un chemin gouverné,
versionné, vérifiable.

**Ce que la campagne approuve réellement.** ``CorpusCampaignV1`` nomme
``expected_catalog_digest`` depuis son introduction (ADR-0036) — jamais
produit ni vérifié par personne jusqu'ici. Ce module lui donne son
premier producteur et son premier vérificateur : le digest calculé ici
doit égaler exactement celui que la campagne, relue par un humain, a
déjà déclaré. Une divergence est un refus, jamais une réécriture
silencieuse de ce que la campagne annonce.

**Idempotence, jamais écrasement.** Si ``catalog.digest.json`` existe
déjà sous le répertoire de la campagne, ce module exige l'égalité octet
pour octet avant d'accepter de ne rien réécrire — jamais un
écrasement silencieux d'un artefact gouverné déjà publié (même
philosophie que ``corpus_publication.py`` pour le registre OCI adressé
par contenu).

**production uniquement.** Comme ``report_to_h2_coverage_evidence``, ce
module refuse tout environnement autre que ``production`` : une clé de
répétition (``rehearsal``) ne peut jamais matérialiser ce qui sera
réellement consommé par un pipeline d'ingestion.
"""
from __future__ import annotations

import copy
import json
import os
import re
import secrets
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from nexus_contracts.authority_artifacts import (
    ScopeAuthorizationArtifactV2,
    canonical_authorization_path,
    parse_scope_authorization_artifact,
)
from nexus_contracts.authorization_set import (
    AuthorizationSetV1,
    ReleaseScopePlacementEntryV1,
    ReleaseScopePlacementV1,
    VerifiedAuthorizationSetV1,
    parse_authorization_set,
    resolve_authorization_set_material,
    scope_digest,
    verify_authorization_set,
)
from nexus_contracts.review_binding import parse_trust_anchor

from rag_pedago.governance import release_scope_placement as release_scope_module
from rag_pedago.governance.corpus_campaign import (
    CorpusCampaignV1,
    CorpusCampaignV2,
    parse_corpus_campaign_v2,
    verify_corpus_campaign_v2,
)
from rag_pedago.governance.release_scope_placement import (
    ReleaseScopePlacementGitInputs,
    produce_release_scope_placement_from_git,
)
from rag_pedago.imports import h2b_coverage_report as h2b_module
from rag_pedago.imports.corpus_catalog_compiler import (
    _derive_pii_clearances,  # noqa: SLF001 - réutilisation intentionnelle
    _derive_rights_clearances,  # noqa: SLF001
)
from rag_pedago.imports.h2b_coverage_report import (
    _load_authority_evidence,  # noqa: SLF001 - réutilisation intentionnelle, cf. docstring
    _load_currentness_verification_evidence,  # noqa: SLF001
    _load_yaml_mapping,  # noqa: SLF001
    _promote_authority_cleared_candidates,  # noqa: SLF001
    _promote_currentness_verified_candidates,  # noqa: SLF001
    authority_required_candidate_facts,
    authority_required_set_digest,
    load_catalog,
)

#: Version du fichier de digest — jamais implicite, jamais absente.
CATALOG_DIGEST_PROTOCOL_VERSION = "NEXUS-CATALOG-REPUBLISH-DIGEST-V1"
CATALOG_DIGEST_V2_PROTOCOL_VERSION = "NEXUS-CATALOG-REPUBLISH-DIGEST-V2"

_CANONICAL_INDENT = 2
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_VERIFIED_SET_MAX_AGE = timedelta(minutes=1)


class CatalogRepublishError(ValueError):
    """Refus explicite — mêmes principes fail-closed que le reste de la
    chaîne H2 : structure, complétude, ou divergence avec la campagne
    approuvée sont une seule et même catégorie de refus pour l'appelant."""


@dataclass(frozen=True)
class CatalogRepublishResult:
    """Ce qui a été (ou aurait déjà été) publié, jamais un booléen seul."""

    campaign_id: str
    catalog_sha256: str
    promoted_count: int
    catalog_path: Path
    digest_path: Path
    already_published: bool
    #: Empreinte du périmètre requis par l'autorité — doit égaler
    #: ``CoverageReport.authority_required_set_sha256`` produit par
    #: ``generate_coverage_report`` sur le même catalogue promu (§8 de
    #: l'audit du 2026-08-15). Un test dédié le prouve.
    authority_required_set_sha256: str


@dataclass(frozen=True)
class CatalogRepublishResultV2:
    """Catalogue V2 lié au set global et à chaque attribution de contenu."""

    campaign_id: str
    catalog_sha256: str
    promoted_count: int
    mapped_content_count: int
    authorization_set_digest: str
    authority_required_set_sha256: str
    catalog_path: Path
    digest_path: Path
    already_published: bool


@dataclass(frozen=True)
class _CatalogEvidenceSnapshotV2:
    """Octets immuables lus une seule fois au boundary de production."""

    catalog: bytes
    currentness: bytes | None
    rights: bytes | None
    pii: bytes | None
    routing: bytes | None


@dataclass(frozen=True)
class _PreparedCatalogV2:
    """Catalogue post-currentness figé, source unique de toute la publication."""

    catalog_bytes: bytes
    manifest_sha256: str
    required_contents: frozenset[str]
    required_rights_candidates: tuple[tuple[str, str | None], ...]


def _canonical_catalog_bytes(catalog: dict[str, Any]) -> bytes:
    """Mêmes réglages que ``corpus_catalog_compiler.py --output`` : clés
    triées, indentation fixe, UTF-8, saut de ligne final. Un consommateur
    du catalogue promu ne doit jamais avoir à deviner quel formatteur l'a
    produit."""
    return (
        json.dumps(catalog, indent=_CANONICAL_INDENT, ensure_ascii=False, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _digest_document(
    *, campaign_id: str, catalog_sha256: str, promoted_count: int, generated_at: str
) -> bytes:
    document = {
        "protocol_version": CATALOG_DIGEST_PROTOCOL_VERSION,
        "campaign_id": campaign_id,
        "catalog_sha256": catalog_sha256,
        "promoted_count": promoted_count,
        "generated_at": generated_at,
    }
    return (
        json.dumps(document, indent=_CANONICAL_INDENT, ensure_ascii=False, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _digest_document_v2(
    *,
    campaign_id: str,
    catalog_sha256: str,
    promoted_count: int,
    mapped_content_count: int,
    authorization_set_digest: str,
    release_scope_placement_digest: str,
    profile_manifest_digest: str,
    authority_required_count: int,
    authority_required_set_sha256: str,
    content_mappings: list[dict[str, Any]],
    generated_at: str,
) -> bytes:
    content_mapping_digest = sha256(
        (
            json.dumps(
                content_mappings,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
    ).hexdigest()
    document = {
        "protocol_version": CATALOG_DIGEST_V2_PROTOCOL_VERSION,
        "campaign_id": campaign_id,
        "catalog_sha256": catalog_sha256,
        "promoted_count": promoted_count,
        "mapped_content_count": mapped_content_count,
        "authorization_set_digest": authorization_set_digest,
        "release_scope_placement_digest": release_scope_placement_digest,
        "profile_manifest_digest": profile_manifest_digest,
        "authority_required_count": authority_required_count,
        "authority_required_set_sha256": authority_required_set_sha256,
        "content_mapping_digest": content_mapping_digest,
        "content_mappings": content_mappings,
        "generated_at": generated_at,
    }
    return (
        json.dumps(document, indent=_CANONICAL_INDENT, ensure_ascii=False, sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _canonical_scope_document(entry: ReleaseScopePlacementEntryV1) -> dict[str, Any]:
    scope_document = entry.scope.model_dump(mode="json")
    scope_document["audience"] = sorted(scope_document["audience"])
    return scope_document


def _trusted_utc_now() -> datetime:
    """Horloge interne de production ; aucun appelant ne fournit ce fait."""
    return datetime.now(UTC)


def _open_or_create_directory(path: Path) -> int:
    """Ouvre/crée un chemin absolu composant par composant sans symlink."""
    absolute = Path(os.path.abspath(path))
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(absolute.anchor, flags)
    try:
        for component in absolute.parts[1:]:
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
                os.fsync(descriptor)
                child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_optional_regular_file(directory_fd: int, name: str) -> bytes | None:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except FileNotFoundError:
        return None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise CatalogRepublishError(
                f"unsafe governed publication member {name!r}: not a regular file"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(descriptor)


def _atomic_create_file(directory_fd: int, name: str, raw: bytes) -> None:
    """Crée une fois, sans remplacement ; fsync fichier puis répertoire."""
    temporary_name: str | None = None
    descriptor: int | None = None
    try:
        for _attempt in range(16):
            candidate = f".{name}.{secrets.token_hex(8)}.tmp"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            try:
                descriptor = os.open(
                    candidate, flags, 0o600, dir_fd=directory_fd
                )
            except FileExistsError:
                continue
            temporary_name = candidate
            break
        if descriptor is None or temporary_name is None:
            raise CatalogRepublishError(
                "cannot allocate a temporary governed publication file"
            )
        try:
            remaining = memoryview(raw)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("short write")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
            descriptor = None
        os.link(
            temporary_name,
            name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
            follow_symlinks=False,
        )
        os.unlink(temporary_name, dir_fd=directory_fd)
        temporary_name = None
        os.fsync(directory_fd)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass


def republish_catalog(
    *,
    campaign: CorpusCampaignV1,
    catalog_path: Path,
    authority_path: Path,
    authority_review_binding_path: Path,
    out_root: Path,
    now: datetime | None = None,
    repository_root: Path | None = None,
    currentness_verification_path: Path | None = None,
    rights_path: Path | None = None,
    pii_path: Path | None = None,
    routing_path: Path | None = None,
) -> CatalogRepublishResult:
    """Charge, promeut et matérialise le catalogue gouverné d'une campagne.

    ``authority_revocations_path`` et ``authority_trust_anchor_path`` ne
    sont jamais des paramètres : en production ils sont **toujours** lus
    aux chemins gouvernés par ``_load_authority_evidence`` lui-même — les
    exposer ici referait exister le défaut qu'ADR-0035 a fermé.

    ``currentness_verification_path`` (gap Tier A, audit du 2026-08-15)
    est optionnel — mais quand il est fourni, ``rights_path``/
    ``pii_path``/``routing_path`` le deviennent aussi : la promotion par
    currentness réévalue réellement droits et PII (voir
    ``h2b_coverage_report._promote_currentness_verified_candidates``),
    elle ne peut jamais s'appliquer sans cette évidence.
    """
    if campaign.environment != "production":
        raise CatalogRepublishError(
            f"republish_catalog refuses environment={campaign.environment!r} — "
            "only a 'production' campaign may materialize the catalog a real "
            "ingestion pipeline will read; a rehearsal key can never gate what "
            "actually ships"
        )

    if not authority_path.is_file():
        raise CatalogRepublishError(
            f"authority evidence file does not exist: {authority_path}"
        )
    if not authority_review_binding_path.is_file():
        raise CatalogRepublishError(
            "an authority artifact requires a sealed review binding receipt — "
            f"{authority_review_binding_path} does not exist"
        )

    raw_authority = authority_path.read_bytes()
    try:
        authority_document = json.loads(raw_authority.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogRepublishError(
            f"authority evidence is not valid UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(authority_document, dict):
        raise CatalogRepublishError("authority evidence must be a JSON object")
    authorization_id = authority_document.get("authorization_id")
    if authorization_id != campaign.authorization_id:
        raise CatalogRepublishError(
            f"authority evidence names authorization_id {authorization_id!r}, but "
            f"the campaign was approved for {campaign.authorization_id!r} — a "
            "different authorization authorizes nothing here"
        )

    catalog = load_catalog(catalog_path)
    if not isinstance(catalog, dict):
        raise CatalogRepublishError("catalog must be a JSON object")
    manifest_sha256 = catalog.get("manifest_sha256")
    if manifest_sha256 != campaign.expected_manifest_sha256:
        raise CatalogRepublishError(
            f"catalog is bound to manifest {manifest_sha256!r}, but the campaign "
            f"expects {campaign.expected_manifest_sha256!r}"
        )
    physical_objects = catalog.get("physical_objects")
    if not isinstance(physical_objects, list):
        raise CatalogRepublishError("catalog must include physical_objects")

    moment = now or datetime.now(UTC)

    # Finding du 2026-08-15 : la promotion currentness doit s'appliquer
    # AVANT que le périmètre requis par l'autorité ne soit mesuré — même
    # défaut, même correctif, que ``generate_coverage_report`` (voir la
    # docstring d'``authority_required_candidate_facts``).
    promoted_physical_objects = copy.deepcopy(physical_objects)
    if currentness_verification_path is not None:
        if rights_path is None or pii_path is None or routing_path is None:
            raise CatalogRepublishError(
                "currentness_verification_path requires rights_path, "
                "pii_path and routing_path — currentness promotion "
                "re-evaluates rights and PII for real, it can never "
                "apply without this evidence"
            )
        currentness_verified_sha256 = _load_currentness_verification_evidence(
            currentness_verification_path, manifest_sha256=str(manifest_sha256)
        )
        entries_for_clearances = [
            (str(item.get("content_sha256")), str(item.get("path")))
            for item in physical_objects
            if isinstance(item, dict)
        ]
        rights_registry = _load_yaml_mapping(rights_path, label="rights registry")
        routing_config = _load_yaml_mapping(routing_path, label="routing policy")
        pii_evidence = load_catalog(pii_path)
        if not isinstance(pii_evidence, dict):
            raise CatalogRepublishError("PII evidence must be a mapping")
        rights_cleared_sha256 = frozenset(
            _derive_rights_clearances(
                entries_for_clearances,
                str(manifest_sha256),
                rights_registry,
                routing_config,
            )
        )
        pii_cleared_sha256_set, pii_quarantined_sha256_set = _derive_pii_clearances(
            entries_for_clearances,
            str(manifest_sha256),
            pii_evidence,
            routing_config,
        )
        _promote_currentness_verified_candidates(
            promoted_physical_objects,
            currentness_verified_sha256=currentness_verified_sha256,
            rights_cleared_sha256=rights_cleared_sha256,
            pii_cleared_sha256=frozenset(pii_cleared_sha256_set),
            pii_quarantined_sha256=frozenset(pii_quarantined_sha256_set),
        )
    # Mesuré ICI, après toute promotion non liée à l'autorité — jamais
    # avant. ``catalog_republish`` doit produire exactement le même
    # périmètre requis que ``generate_coverage_report`` pour le même
    # catalogue promu (§8 de l'audit du 2026-08-15) : réutilise la même
    # primitive, ne recalcule jamais un périmètre parallèle.
    authority_required_sha256, authority_required_rights_candidates = (
        authority_required_candidate_facts(promoted_physical_objects)
    )
    authority_required_set_sha256 = authority_required_set_digest(
        authority_required_sha256
    )
    authority_allowlist, _binding, _revocations_checked = _load_authority_evidence(
        authority_path,
        str(manifest_sha256),
        ingest_content_sha256=authority_required_sha256,
        ingest_rights_candidates=authority_required_rights_candidates,
        now=moment,
        revocations_path=None,
        binding_path=authority_review_binding_path,
        trust_anchor_path=None,
        environment="production",
        repository_root=repository_root or Path(__file__).resolve().parents[4],
    )
    promoted_count = _promote_authority_cleared_candidates(
        promoted_physical_objects,
        authority_allowlist=authority_allowlist,
    )

    promoted_catalog = dict(catalog)
    promoted_catalog["physical_objects"] = promoted_physical_objects
    catalog_bytes = _canonical_catalog_bytes(promoted_catalog)
    catalog_sha256 = sha256(catalog_bytes).hexdigest()

    if catalog_sha256 != campaign.expected_catalog_digest:
        raise CatalogRepublishError(
            "computed catalog digest does not match the campaign's approved "
            f"expected_catalog_digest (computed={catalog_sha256}, "
            f"approved={campaign.expected_catalog_digest}) — the promoted "
            "catalog is not the one a human reviewed"
        )

    campaign_dir = out_root / campaign.canonical_dir()
    catalog_out_path = out_root / f"{campaign.canonical_dir()}/catalog.json"
    digest_out_path = out_root / campaign.catalog_digest_path()

    generated_at = moment.astimezone(UTC).isoformat().replace("+00:00", "Z")
    digest_bytes = _digest_document(
        campaign_id=campaign.campaign_id,
        catalog_sha256=catalog_sha256,
        promoted_count=promoted_count,
        generated_at=generated_at,
    )

    if digest_out_path.is_file():
        existing = json.loads(digest_out_path.read_text(encoding="utf-8"))
        existing_sha256 = existing.get("catalog_sha256") if isinstance(existing, dict) else None
        if existing_sha256 != catalog_sha256:
            raise CatalogRepublishError(
                f"{digest_out_path} already exists with catalog_sha256="
                f"{existing_sha256!r}, which differs from the freshly computed "
                f"{catalog_sha256!r} — a previously published governed catalog "
                "is never silently overwritten with different content"
            )
        return CatalogRepublishResult(
            campaign_id=campaign.campaign_id,
            catalog_sha256=catalog_sha256,
            promoted_count=promoted_count,
            catalog_path=catalog_out_path,
            digest_path=digest_out_path,
            already_published=True,
            authority_required_set_sha256=authority_required_set_sha256,
        )

    campaign_dir.mkdir(parents=True, exist_ok=True)
    catalog_out_path.write_bytes(catalog_bytes)
    digest_out_path.write_bytes(digest_bytes)

    return CatalogRepublishResult(
        campaign_id=campaign.campaign_id,
        catalog_sha256=catalog_sha256,
        promoted_count=promoted_count,
        catalog_path=catalog_out_path,
        digest_path=digest_out_path,
        already_published=False,
        authority_required_set_sha256=authority_required_set_sha256,
    )


def _snapshot_v2_catalog_evidence(
    *,
    catalog_path: Path,
    currentness_verification_path: Path | None,
    rights_path: Path | None,
    pii_path: Path | None,
    routing_path: Path | None,
) -> _CatalogEvidenceSnapshotV2:
    """Fige chaque input une fois ; aucun path ne franchit le boundary interne."""
    if currentness_verification_path is not None and (
        rights_path is None or pii_path is None or routing_path is None
    ):
        raise CatalogRepublishError(
            "currentness_verification_path requires rights_path, pii_path "
            "and routing_path"
        )
    return _CatalogEvidenceSnapshotV2(
        catalog=bytes(catalog_path.read_bytes()),
        currentness=(
            bytes(currentness_verification_path.read_bytes())
            if currentness_verification_path is not None
            else None
        ),
        rights=bytes(rights_path.read_bytes()) if rights_path is not None else None,
        pii=bytes(pii_path.read_bytes()) if pii_path is not None else None,
        routing=bytes(routing_path.read_bytes()) if routing_path is not None else None,
    )


def _prepare_v2_catalog(snapshot: _CatalogEvidenceSnapshotV2) -> _PreparedCatalogV2:
    """Applique currentness une fois puis scelle les faits qui seront publiés."""
    catalog = h2b_module._load_catalog_bytes(snapshot.catalog)  # noqa: SLF001
    if not isinstance(catalog, dict):
        raise CatalogRepublishError("catalog must be a JSON object")
    manifest_sha256 = catalog.get("manifest_sha256")
    if not isinstance(manifest_sha256, str):
        raise CatalogRepublishError("catalog must name manifest_sha256")
    physical_objects = catalog.get("physical_objects")
    if not isinstance(physical_objects, list):
        raise CatalogRepublishError("catalog must include physical_objects")

    promoted_physical_objects = copy.deepcopy(physical_objects)
    if snapshot.currentness is not None:
        if snapshot.rights is None or snapshot.pii is None or snapshot.routing is None:
            raise CatalogRepublishError("currentness snapshot is structurally incomplete")
        currentness_verified_sha256 = _load_currentness_verification_evidence(
            snapshot.currentness, manifest_sha256=manifest_sha256
        )
        entries_for_clearances = [
            (str(item.get("content_sha256")), str(item.get("path")))
            for item in physical_objects
            if isinstance(item, dict)
        ]
        rights_registry = h2b_module._load_yaml_mapping_bytes(  # noqa: SLF001
            snapshot.rights, label="rights registry"
        )
        routing_config = h2b_module._load_yaml_mapping_bytes(  # noqa: SLF001
            snapshot.routing, label="routing policy"
        )
        pii_evidence = h2b_module._load_catalog_bytes(snapshot.pii)  # noqa: SLF001
        if not isinstance(pii_evidence, dict):
            raise CatalogRepublishError("PII evidence must be a mapping")
        rights_cleared_sha256 = frozenset(
            _derive_rights_clearances(
                entries_for_clearances,
                manifest_sha256,
                rights_registry,
                routing_config,
            )
        )
        pii_cleared_sha256_set, pii_quarantined_sha256_set = _derive_pii_clearances(
            entries_for_clearances,
            manifest_sha256,
            pii_evidence,
            routing_config,
        )
        _promote_currentness_verified_candidates(
            promoted_physical_objects,
            currentness_verified_sha256=currentness_verified_sha256,
            rights_cleared_sha256=rights_cleared_sha256,
            pii_cleared_sha256=frozenset(pii_cleared_sha256_set),
            pii_quarantined_sha256=frozenset(pii_quarantined_sha256_set),
        )
    prepared_catalog = copy.deepcopy(catalog)
    prepared_catalog["physical_objects"] = promoted_physical_objects
    required_contents, required_rights_candidates = authority_required_candidate_facts(
        promoted_physical_objects
    )
    return _PreparedCatalogV2(
        catalog_bytes=_canonical_catalog_bytes(prepared_catalog),
        manifest_sha256=manifest_sha256,
        required_contents=frozenset(required_contents),
        required_rights_candidates=tuple(required_rights_candidates),
    )


def _validated_v2_mapping(
    *,
    authorization_set: AuthorizationSetV1,
    verified_authorization_set: VerifiedAuthorizationSetV1,
    release_scope_placement: ReleaseScopePlacementV1,
    authorization_member_bytes: Mapping[str, bytes | bytearray],
    now: datetime,
) -> tuple[
    dict[str, str],
    dict[str, ReleaseScopePlacementEntryV1],
    dict[str, ScopeAuthorizationArtifactV2],
]:
    """Rejoue les identités du snapshot vérifié, sans refaire l'autorité."""
    try:
        canonical_set = parse_authorization_set(authorization_set.canonical_bytes())
    except ValueError as exc:
        raise CatalogRepublishError(f"authorization set is invalid: {exc}") from exc
    canonical_bytes = canonical_set.canonical_bytes()
    set_digest = sha256(canonical_bytes).hexdigest()
    if verified_authorization_set.authorization_set_bytes != canonical_bytes:
        raise CatalogRepublishError(
            "verified authorization set bytes differ from AuthorizationSetV1"
        )
    if verified_authorization_set.authorization_set_digest != set_digest:
        raise CatalogRepublishError("verified authorization set digest mismatch")
    if not (
        verified_authorization_set.authorizations_effective_valid_from
        <= now
        < verified_authorization_set.authorizations_effective_valid_until
    ):
        raise CatalogRepublishError(
            "authorization set is outside its effective validity window"
        )
    if verified_authorization_set.verified_at > now:
        raise CatalogRepublishError(
            "authorization set verification time is in the future"
        )
    if now - verified_authorization_set.verified_at > _VERIFIED_SET_MAX_AGE:
        raise CatalogRepublishError(
            "authorization set must be freshly globally verified at the "
            "republish moment"
        )
    if now >= verified_authorization_set.earliest_review_binding_expires_at:
        raise CatalogRepublishError(
            "authorization set review binding has expired at the republish moment"
        )

    expected_ids = tuple(member.authorization_id for member in canonical_set.members)
    if verified_authorization_set.authorization_ids != expected_ids:
        raise CatalogRepublishError("verified authorization identities mismatch")

    owners: dict[str, str] = {}
    members_by_id = {member.authorization_id: member for member in canonical_set.members}
    for member in canonical_set.members:
        for content_sha256 in member.allowed_content_sha256:
            if content_sha256 in owners:
                raise CatalogRepublishError(
                    f"authorization overlap for content {content_sha256!r}"
                )
            owners[content_sha256] = member.authorization_id
    expected_content_mapping = tuple(sorted(owners.items()))
    if verified_authorization_set.content_authorization_ids != expected_content_mapping:
        raise CatalogRepublishError("verified content authorization mapping mismatch")
    expected_scope_mapping = tuple(
        sorted(
            (member.scope_digest, member.authorization_id)
            for member in canonical_set.members
        )
    )
    if verified_authorization_set.scope_authorization_ids != expected_scope_mapping:
        raise CatalogRepublishError("verified scope authorization mapping mismatch")

    expected_paths = {
        canonical_authorization_path(member.authorization_id)
        for member in canonical_set.members
    }
    supplied_paths = set(authorization_member_bytes)
    missing_paths = sorted(expected_paths - supplied_paths)
    extra_paths = sorted(supplied_paths - expected_paths)
    if missing_paths:
        raise CatalogRepublishError(
            f"authorization member bytes are missing: {missing_paths!r}"
        )
    if extra_paths:
        raise CatalogRepublishError(
            f"authorization member bytes contain extras: {extra_paths!r}"
        )
    artifacts: dict[str, ScopeAuthorizationArtifactV2] = {}
    for member in canonical_set.members:
        path = canonical_authorization_path(member.authorization_id)
        raw = bytes(authorization_member_bytes[path])
        if sha256(raw).hexdigest() != member.authorization_digest:
            raise CatalogRepublishError(
                f"authorization member digest mismatch for {member.authorization_id!r}"
            )
        try:
            artifact = parse_scope_authorization_artifact(raw)
        except ValueError as exc:
            raise CatalogRepublishError(
                f"authorization member is invalid for {member.authorization_id!r}: {exc}"
            ) from exc
        if not isinstance(artifact, ScopeAuthorizationArtifactV2):
            raise CatalogRepublishError(
                f"authorization member {member.authorization_id!r} is not LOT41A-V2"
            )
        if artifact.authorization_id != member.authorization_id:
            raise CatalogRepublishError(
                f"authorization member identity mismatch for {member.authorization_id!r}"
            )
        artifacts[member.authorization_id] = artifact

    if release_scope_placement.digest() != canonical_set.release_scope_placement_digest:
        raise CatalogRepublishError("release scope placement digest mismatch")
    if release_scope_placement.profile_manifest_digest != canonical_set.profile_manifest_digest:
        raise CatalogRepublishError("profile manifest digest mismatch")
    placements = {
        placement.content_sha256: placement
        for placement in release_scope_placement.placements
    }
    gap = sorted(set(owners) - set(placements))
    extra = sorted(set(placements) - set(owners))
    if gap:
        raise CatalogRepublishError(f"release scope placement has a gap: {gap!r}")
    if extra:
        raise CatalogRepublishError(f"release scope placement has extra content: {extra!r}")
    for content_sha256, authorization_id in owners.items():
        member = members_by_id[authorization_id]
        if scope_digest(placements[content_sha256].scope) != member.scope_digest:
            raise CatalogRepublishError(
                f"release scope placement scope mismatch for content {content_sha256!r}"
            )
    return owners, placements, artifacts


def _verified_required_rights_by_occurrence(
    *,
    authorization_set: AuthorizationSetV1,
    authorization_member_bytes: Mapping[str, bytes | bytearray],
    required_rights_candidates: tuple[tuple[str, str | None], ...],
) -> dict[str, str]:
    """Délègue les droits à l'unique vérificateur H2 puis projette le fait."""
    try:
        h2b_module._verify_v2_catalog_rights_semantics(  # noqa: SLF001
            authorization_set,
            release_files={
                path: bytes(raw) for path, raw in authorization_member_bytes.items()
            },
            required_rights_candidates=required_rights_candidates,
        )
    except ValueError as exc:
        raise CatalogRepublishError(str(exc)) from exc
    required_by_content: dict[str, str] = {}
    for content_sha256, raw_category in required_rights_candidates:
        # Le vérificateur partagé a déjà refusé None, vocabulaire inconnu,
        # divergence et catégorie non accordée ; ce cast est une projection.
        assert isinstance(raw_category, str)  # noqa: S101
        required_by_content[content_sha256] = raw_category
    return required_by_content


def _content_mapping_documents(
    *,
    authorization_set: AuthorizationSetV1,
    owners: Mapping[str, str],
    placements: Mapping[str, ReleaseScopePlacementEntryV1],
    artifacts: Mapping[str, ScopeAuthorizationArtifactV2],
    required_rights: Mapping[str, str],
) -> list[dict[str, Any]]:
    members = {member.authorization_id: member for member in authorization_set.members}
    mappings: list[dict[str, Any]] = []
    for content_sha256 in sorted(owners):
        authorization_id = owners[content_sha256]
        member = members[authorization_id]
        placement = placements[content_sha256]
        mappings.append(
            {
                "authorization_digest": member.authorization_digest,
                "authorized_rights_categories": [
                    value.value for value in artifacts[authorization_id].rights_categories
                ],
                "content_sha256": content_sha256,
                "profile_fingerprint": placement.profile_fingerprint,
                "profile_id": placement.profile_id,
                "profile_version": placement.profile_version,
                "required_rights_category": required_rights[content_sha256],
                "review_binding_digest": member.review_binding_digest,
                "scope": _canonical_scope_document(placement),
                "scope_authorization_id": authorization_id,
                "scope_digest": member.scope_digest,
            }
        )
    return mappings


def _parse_generated_at(value: Any, *, now: datetime) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CatalogRepublishError("V2 digest generated_at must be canonical UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CatalogRepublishError("V2 digest generated_at is invalid") from exc
    if parsed.astimezone(UTC).isoformat().replace("+00:00", "Z") != value:
        raise CatalogRepublishError("V2 digest generated_at is not canonical")
    if parsed > now:
        raise CatalogRepublishError("V2 digest generated_at is in the future")
    return parsed


def _json_exact(actual: Any, expected: Any) -> bool:
    """Égalité JSON avec types stricts (``true`` n'est jamais l'entier 1)."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(actual) == set(expected) and all(
            _json_exact(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _json_exact(left, right) for left, right in zip(actual, expected, strict=True)
        )
    return bool(actual == expected)


def _validate_existing_v2_digest(
    raw: bytes,
    *,
    expected_document: dict[str, Any],
    now: datetime,
    effective_valid_from: datetime,
    effective_valid_until: datetime,
) -> None:
    """Parse strict et comparaison exhaustive de l'évidence déjà publiée."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogRepublishError(
            f"existing V2 digest document is invalid: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise CatalogRepublishError("existing V2 digest document must be an object")
    expected_fields = set(expected_document)
    actual_fields = set(document)
    missing = sorted(expected_fields - actual_fields)
    extra = sorted(actual_fields - expected_fields)
    if missing:
        raise CatalogRepublishError(
            f"existing V2 digest document is missing fields: {missing!r}"
        )
    if extra:
        raise CatalogRepublishError(
            f"existing V2 digest document has extra fields: {extra!r}"
        )
    generated_at = _parse_generated_at(document["generated_at"], now=now)
    if not (effective_valid_from <= generated_at < effective_valid_until):
        raise CatalogRepublishError(
            "existing V2 digest generated_at is outside authorization validity"
        )
    expected_with_original_time = dict(expected_document)
    expected_with_original_time["generated_at"] = document["generated_at"]
    if not _json_exact(document, expected_with_original_time):
        divergent = sorted(
            field
            for field in expected_fields
            if not _json_exact(
                document.get(field), expected_with_original_time.get(field)
            )
        )
        raise CatalogRepublishError(
            f"existing V2 digest facts differ from this release: {divergent!r}"
        )
    canonical = (
        json.dumps(document, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    if raw != canonical:
        raise CatalogRepublishError(
            "existing V2 digest document bytes are not canonical"
        )


def _republish_catalog_v2_verified(
    *,
    campaign: CorpusCampaignV2,
    prepared_catalog: _PreparedCatalogV2,
    authorization_set: AuthorizationSetV1,
    verified_authorization_set: VerifiedAuthorizationSetV1,
    release_scope_placement: ReleaseScopePlacementV1,
    authorization_member_bytes: Mapping[str, bytes | bytearray],
    out_root: Path,
    moment: datetime,
) -> CatalogRepublishResultV2:
    """Publie l'union V2 exacte et sa fonction contenu → autorisation.

    Le snapshot ``VerifiedAuthorizationSetV1`` doit provenir du boundary
    global de ``nexus-contracts``. Ici, aucune autorisation individuelle
    n'est relue ou sélectionnée : les octets et toutes les projections du
    snapshot sont confrontés au set et au placement déjà vérifiés.
    """
    if campaign.environment != "production":
        raise CatalogRepublishError(
            "republish_catalog_v2 only accepts a production campaign"
        )
    if moment.tzinfo is None:  # pragma: no cover - garde interne défensive
        raise CatalogRepublishError("verification moment is not timezone-aware")
    moment = moment.astimezone(UTC)
    catalog = h2b_module._load_catalog_bytes(  # noqa: SLF001
        prepared_catalog.catalog_bytes
    )
    physical_objects = copy.deepcopy(catalog["physical_objects"])
    manifest_sha256 = prepared_catalog.manifest_sha256
    if authorization_set.corpus_manifest_sha256 != manifest_sha256:
        raise CatalogRepublishError(
            "authorization set corpus manifest differs from the frozen catalog manifest"
        )
    owners, placements, artifacts = _validated_v2_mapping(
        authorization_set=authorization_set,
        verified_authorization_set=verified_authorization_set,
        release_scope_placement=release_scope_placement,
        authorization_member_bytes=authorization_member_bytes,
        now=moment,
    )
    try:
        verify_corpus_campaign_v2(
            campaign,
            corpus_manifest_sha256=manifest_sha256,
            authorization_set_digest=verified_authorization_set.authorization_set_digest,
            authority_required_count=authorization_set.authority_required_count,
            authority_required_set_sha256=authorization_set.authority_required_set_sha256,
            profile_manifest_digest=authorization_set.profile_manifest_digest,
            release_scope_placement_digest=release_scope_placement.digest(),
        )
    except ValueError as exc:
        raise CatalogRepublishError(str(exc)) from exc

    required_contents, required_rights_candidates = authority_required_candidate_facts(
        physical_objects
    )
    if (
        required_contents != prepared_catalog.required_contents
        or required_rights_candidates
        != prepared_catalog.required_rights_candidates
    ):
        raise CatalogRepublishError("frozen catalog facts changed after preparation")
    owner_contents = frozenset(owners)
    gap = sorted(required_contents - owner_contents)
    extra = sorted(owner_contents - required_contents)
    if gap:
        raise CatalogRepublishError(f"authorization union has a gap: {gap!r}")
    if extra:
        raise CatalogRepublishError(f"authorization union has extra content: {extra!r}")
    required_rights = _verified_required_rights_by_occurrence(
        authorization_set=authorization_set,
        authorization_member_bytes=authorization_member_bytes,
        required_rights_candidates=required_rights_candidates,
    )

    promoted_count = _promote_authority_cleared_candidates(
        physical_objects,
        authority_allowlist=owner_contents,
    )
    mapped_contents: set[str] = set()
    for item in physical_objects:
        if not isinstance(item, dict):
            continue
        content_sha256 = item.get("content_sha256")
        if content_sha256 not in owners or item.get("disposition") != "INGEST":
            continue
        placement = placements[str(content_sha256)]
        item["scope_authorization_id"] = owners[str(content_sha256)]
        item["profile_id"] = placement.profile_id
        item["profile_version"] = placement.profile_version
        item["profile_fingerprint"] = placement.profile_fingerprint
        item["scope"] = _canonical_scope_document(placement)
        mapped_contents.add(str(content_sha256))
    if mapped_contents != owner_contents:
        missing = sorted(owner_contents - mapped_contents)
        raise CatalogRepublishError(
            f"not every authorized content was promoted and mapped: {missing!r}"
        )
    ingest_contents = {
        str(item.get("content_sha256"))
        for item in physical_objects
        if isinstance(item, dict) and item.get("disposition") == "INGEST"
    }
    if ingest_contents != owner_contents:
        raise CatalogRepublishError(
            "republished INGEST contents differ from the exact authorization union"
        )

    promoted_catalog = dict(catalog)
    promoted_catalog["physical_objects"] = physical_objects
    catalog_bytes = _canonical_catalog_bytes(promoted_catalog)
    catalog_sha256 = sha256(catalog_bytes).hexdigest()
    if catalog_sha256 != campaign.expected_catalog_digest:
        raise CatalogRepublishError(
            "computed catalog digest does not match the V2 campaign's approved "
            f"expected_catalog_digest (computed={catalog_sha256}, "
            f"approved={campaign.expected_catalog_digest})"
        )

    generated_at = moment.astimezone(UTC).isoformat().replace("+00:00", "Z")
    content_mappings = _content_mapping_documents(
        authorization_set=authorization_set,
        owners=owners,
        placements=placements,
        artifacts=artifacts,
        required_rights=required_rights,
    )
    digest_bytes = _digest_document_v2(
        campaign_id=campaign.campaign_id,
        catalog_sha256=catalog_sha256,
        promoted_count=promoted_count,
        mapped_content_count=len(mapped_contents),
        authorization_set_digest=verified_authorization_set.authorization_set_digest,
        release_scope_placement_digest=release_scope_placement.digest(),
        profile_manifest_digest=authorization_set.profile_manifest_digest,
        authority_required_count=authorization_set.authority_required_count,
        authority_required_set_sha256=authorization_set.authority_required_set_sha256,
        content_mappings=content_mappings,
        generated_at=generated_at,
    )
    expected_digest_document = json.loads(digest_bytes.decode("utf-8"))
    campaign_dir = out_root / campaign.canonical_dir()
    catalog_out_path = campaign_dir / "catalog.json"
    digest_out_path = out_root / campaign.catalog_digest_path()
    try:
        campaign_directory_fd = _open_or_create_directory(campaign_dir)
    except OSError as exc:
        raise CatalogRepublishError(
            f"unsafe governed publication directory: {exc}"
        ) from exc
    try:
        existing_catalog = _read_optional_regular_file(
            campaign_directory_fd, "catalog.json"
        )
        existing_digest = _read_optional_regular_file(
            campaign_directory_fd, "catalog.digest.json"
        )
        if existing_digest is not None and existing_catalog is None:
            raise CatalogRepublishError(
                "orphan V2 digest exists without its governed catalog"
            )
        if existing_catalog is not None and existing_catalog != catalog_bytes:
            raise CatalogRepublishError(
                "existing V2 catalog bytes differ; governed material is never overwritten"
            )
        if existing_catalog is None:
            _atomic_create_file(campaign_directory_fd, "catalog.json", catalog_bytes)
        if existing_digest is None:
            # Commit marker en dernier. Un crash avant ce point laisse un
            # catalogue exact récupérable ; il n'est jamais écrasé au retry.
            _atomic_create_file(
                campaign_directory_fd,
                "catalog.digest.json",
                digest_bytes,
            )
            already_published = False
        else:
            _validate_existing_v2_digest(
                existing_digest,
                expected_document=expected_digest_document,
                now=moment,
                effective_valid_from=(
                    verified_authorization_set.authorizations_effective_valid_from
                ),
                effective_valid_until=(
                    verified_authorization_set.authorizations_effective_valid_until
                ),
            )
            already_published = True
    except OSError as exc:
        raise CatalogRepublishError(
            f"atomic governed publication failed: {exc}"
        ) from exc
    finally:
        os.close(campaign_directory_fd)

    return CatalogRepublishResultV2(
        campaign_id=campaign.campaign_id,
        catalog_sha256=catalog_sha256,
        promoted_count=promoted_count,
        mapped_content_count=len(mapped_contents),
        authorization_set_digest=verified_authorization_set.authorization_set_digest,
        authority_required_set_sha256=authorization_set.authority_required_set_sha256,
        catalog_path=catalog_out_path,
        digest_path=digest_out_path,
        already_published=already_published,
    )


def republish_catalog_v2(
    *,
    campaign_relative_path: str,
    catalog_path: Path,
    authorization_set_relative_path: str,
    release_scope_git_inputs: ReleaseScopePlacementGitInputs,
    out_root: Path,
    currentness_verification_path: Path | None = None,
    rights_path: Path | None = None,
    pii_path: Path | None = None,
    routing_path: Path | None = None,
) -> CatalogRepublishResultV2:
    """Boundary production : vérifie lui-même toutes les preuves globales.

    Aucune campagne parsée, aucun ``VerifiedAuthorizationSetV1``, aucune ancre,
    aucun registre et aucune horloge ne sont fournis par l'appelant. Les
    fichiers de confiance viennent exclusivement du tree Git exact de la
    release puis le boundary public partagé ``verify_authorization_set`` est
    invoqué sur ces snapshots exacts.
    """
    moment = _trusted_utc_now().astimezone(UTC)
    governed_root = h2b_module._GOVERNED_REPOSITORY_ROOT  # noqa: SLF001
    try:
        evidence_snapshot = _snapshot_v2_catalog_evidence(
            catalog_path=catalog_path,
            currentness_verification_path=currentness_verification_path,
            rights_path=rights_path,
            pii_path=pii_path,
            routing_path=routing_path,
        )
        prepared_catalog = _prepare_v2_catalog(evidence_snapshot)
        manifest_sha256 = prepared_catalog.manifest_sha256
        required_contents = prepared_catalog.required_contents
        required_rights = prepared_catalog.required_rights_candidates
        head_sha = h2b_module._get_git_commit(governed_root)  # noqa: SLF001
        h2b_module._validate_v2_release_scope_provenance(  # noqa: SLF001
            release_scope_git_inputs,
            environment="production",
            governed_repository_root=governed_root,
            release_tree_sha=h2b_module._git_tree_sha(  # noqa: SLF001
                governed_root, head_sha
            ),
        )
        tree_reader = release_scope_module._GitTreeReader(  # noqa: SLF001
            repository_root=governed_root,
            source_tree_sha=release_scope_git_inputs.source_tree_sha,
        )
        campaign = parse_corpus_campaign_v2(
            tree_reader.read_blob(campaign_relative_path)
        )
        if campaign_relative_path != campaign.canonical_path():
            raise CatalogRepublishError(
                "campaign path does not match its canonical campaign identity"
            )
        if campaign.environment != "production":
            raise CatalogRepublishError(
                "republish_catalog_v2 only accepts a production campaign"
            )
        set_files = {
            authorization_set_relative_path: tree_reader.read_blob(
                authorization_set_relative_path
            )
        }
        authorization_set = parse_authorization_set(
            set_files[authorization_set_relative_path]
        )
        if authorization_set.corpus_manifest_sha256 != manifest_sha256:
            raise CatalogRepublishError(
                "authorization set corpus manifest differs from the catalog manifest"
            )
        if (
            authorization_set.authority_required_count != len(required_contents)
            or authorization_set.authority_required_set_sha256
            != authority_required_set_digest(required_contents)
        ):
            raise CatalogRepublishError(
                "authorization set identity differs from the exact Tier-A required set"
            )

        produced_scope = produce_release_scope_placement_from_git(
            repository_root=release_scope_git_inputs.repository_root,
            source_tree_sha=release_scope_git_inputs.source_tree_sha,
            profile_proposal_matrix_path=(
                release_scope_git_inputs.profile_proposal_matrix_path
            ),
            accepted_placements_path=(
                release_scope_git_inputs.accepted_placements_path
            ),
            release_registry_path=release_scope_git_inputs.release_registry_path,
            expected_contents_path=release_scope_git_inputs.expected_contents_path,
            verified_profiles_path=release_scope_git_inputs.verified_profiles_path,
            profile_manifest_path=release_scope_git_inputs.profile_manifest_path,
        )

        material_paths = tuple(
            sorted(
                path
                for member in authorization_set.members
                for path in (member.authorization_path, member.review_binding_path)
            )
        )
        governed_files = {path: tree_reader.read_blob(path) for path in material_paths}
        release_files = resolve_authorization_set_material(
            authorization_set,
            governed_files=governed_files,
        )
        control_paths = (
            h2b_module._GOVERNED_TRUST_ANCHOR_PATH,  # noqa: SLF001
            h2b_module._GOVERNED_REVOCATIONS_PATH,  # noqa: SLF001
            h2b_module._TRUSTED_REVIEWERS_CONFIG,  # noqa: SLF001
        )
        control_files = {path: tree_reader.read_blob(path) for path in control_paths}
        expected_repository, accepted_reviewers = h2b_module._parse_trusted_reviewers(  # noqa: SLF001
            control_files[h2b_module._TRUSTED_REVIEWERS_CONFIG]  # noqa: SLF001
        )
        verified = verify_authorization_set(
            authorization_set,
            release_files=release_files,
            trust_anchor=parse_trust_anchor(
                control_files[h2b_module._GOVERNED_TRUST_ANCHOR_PATH]  # noqa: SLF001
            ),
            environment="production",
            now=moment,
            expected_repository=expected_repository,
            accepted_reviewers=accepted_reviewers,
            release_scope_placement=produced_scope.placement,
            verified_profiles=produced_scope.verified_profile_facts,
            revocation_registry_raw=control_files[
                h2b_module._GOVERNED_REVOCATIONS_PATH  # noqa: SLF001
            ],
            authority_required_content_sha256=tuple(sorted(required_contents)),
        )
        h2b_module._verify_v2_catalog_rights_semantics(  # noqa: SLF001
            authorization_set,
            release_files=release_files,
            required_rights_candidates=required_rights,
        )
    except CatalogRepublishError:
        raise
    except (OSError, ValueError) as exc:
        raise CatalogRepublishError(str(exc)) from exc

    authorization_member_bytes = {
        member.authorization_path: release_files[member.authorization_path]
        for member in authorization_set.members
    }
    return _republish_catalog_v2_verified(
        campaign=campaign,
        prepared_catalog=prepared_catalog,
        authorization_set=authorization_set,
        verified_authorization_set=verified,
        release_scope_placement=produced_scope.placement,
        authorization_member_bytes=authorization_member_bytes,
        out_root=out_root,
        moment=moment,
    )


__all__ = [
    "CATALOG_DIGEST_PROTOCOL_VERSION",
    "CATALOG_DIGEST_V2_PROTOCOL_VERSION",
    "CatalogRepublishError",
    "CatalogRepublishResult",
    "CatalogRepublishResultV2",
    "republish_catalog",
    "republish_catalog_v2",
]
