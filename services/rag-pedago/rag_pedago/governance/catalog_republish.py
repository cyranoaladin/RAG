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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from rag_pedago.governance.corpus_campaign import CorpusCampaignV1, CorpusCampaignV2
from rag_pedago.imports.corpus_catalog_compiler import (
    _derive_pii_clearances,  # noqa: SLF001 - réutilisation intentionnelle
    _derive_rights_clearances,  # noqa: SLF001
)
from rag_pedago.imports.h2b_coverage_report import (
    _load_authority_evidence,  # noqa: SLF001 - réutilisation intentionnelle, cf. docstring
    _load_authority_set_evidence,  # noqa: SLF001 - ADR-0044, même réutilisation
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

_CANONICAL_INDENT = 2


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


def republish_catalog_v2(
    *,
    campaign: CorpusCampaignV2,
    catalog_path: Path,
    authority_paths: Sequence[Path],
    authority_review_binding_paths: Sequence[Path],
    out_root: Path,
    now: datetime | None = None,
    repository_root: Path | None = None,
    currentness_verification_path: Path | None = None,
    rights_path: Path | None = None,
    pii_path: Path | None = None,
    routing_path: Path | None = None,
) -> CatalogRepublishResult:
    """ADR-0044 : équivalent ``CorpusCampaignV2`` de ``republish_catalog``.

    Même déroulé exact (promotion currentness optionnelle, calcul du
    périmètre requis, matérialisation du catalogue, idempotence par
    digest) — seule la liaison d'autorité change : au lieu d'une égalité
    stricte 1:1 sur ``authorization_id``, l'ensemble gouverné construit
    depuis les N autorisations fournies doit référencer exactement le
    même ``authorization_set_digest`` que celui déjà approuvé par la
    campagne. ``authority_revocations_path``/``authority_trust_anchor_path``
    restent absents des paramètres pour la même raison qu'en V1 : toujours
    lus aux chemins gouvernés en production, jamais exposés ici.
    """
    if campaign.environment != "production":
        raise CatalogRepublishError(
            f"republish_catalog_v2 refuses environment={campaign.environment!r} — "
            "only a 'production' campaign may materialize the catalog a real "
            "ingestion pipeline will read; a rehearsal key can never gate what "
            "actually ships"
        )
    if not authority_paths:
        raise CatalogRepublishError(
            "republish_catalog_v2 requires at least one authority evidence file"
        )
    for path in authority_paths:
        if not path.is_file():
            raise CatalogRepublishError(f"authority evidence file does not exist: {path}")
    for path in authority_review_binding_paths:
        if not path.is_file():
            raise CatalogRepublishError(
                "an authority artifact requires a sealed review binding receipt — "
                f"{path} does not exist"
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

    authority_required_sha256, authority_required_rights_candidates = (
        authority_required_candidate_facts(promoted_physical_objects)
    )
    authority_required_set_sha256 = authority_required_set_digest(
        authority_required_sha256
    )
    authorization_set, _revocations_checked = _load_authority_set_evidence(
        authority_paths,
        authority_review_binding_paths,
        str(manifest_sha256),
        ingest_content_sha256=authority_required_sha256,
        ingest_rights_candidates=authority_required_rights_candidates,
        now=moment,
        revocations_path=None,
        trust_anchor_path=None,
        environment="production",
        repository_root=repository_root or Path(__file__).resolve().parents[4],
    )
    if authorization_set.authorization_set_digest != campaign.authorization_set_digest:
        raise CatalogRepublishError(
            "the authorization set built from the provided --authority files "
            f"(digest={authorization_set.authorization_set_digest}) does not "
            "match the campaign's approved "
            f"authorization_set_digest ({campaign.authorization_set_digest}) — a "
            "different set of authorizations authorizes nothing here"
        )
    authority_allowlist = frozenset(
        content_sha256
        for member in authorization_set.members
        for content_sha256 in member.allowed_content_sha256
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


__all__ = [
    "CATALOG_DIGEST_PROTOCOL_VERSION",
    "CatalogRepublishError",
    "CatalogRepublishResult",
    "republish_catalog",
]
