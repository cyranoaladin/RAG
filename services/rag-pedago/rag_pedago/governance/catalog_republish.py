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
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from rag_pedago.governance.corpus_campaign import CorpusCampaignV1
from rag_pedago.imports.h2b_coverage_report import (
    _load_authority_evidence,  # noqa: SLF001 - réutilisation intentionnelle, cf. docstring
    _promote_authority_cleared_candidates,  # noqa: SLF001
    ingest_candidate_facts,
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
) -> CatalogRepublishResult:
    """Charge, promeut et matérialise le catalogue gouverné d'une campagne.

    ``authority_revocations_path`` et ``authority_trust_anchor_path`` ne
    sont jamais des paramètres : en production ils sont **toujours** lus
    aux chemins gouvernés par ``_load_authority_evidence`` lui-même — les
    exposer ici referait exister le défaut qu'ADR-0035 a fermé.
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

    ingest_content_sha256, ingest_rights_candidates = ingest_candidate_facts(
        physical_objects
    )
    moment = now or datetime.now(UTC)
    authority_allowlist, _binding, _revocations_checked = _load_authority_evidence(
        authority_path,
        str(manifest_sha256),
        ingest_content_sha256=ingest_content_sha256,
        ingest_rights_candidates=ingest_rights_candidates,
        now=moment,
        revocations_path=None,
        binding_path=authority_review_binding_path,
        trust_anchor_path=None,
        environment="production",
        repository_root=repository_root or Path(__file__).resolve().parents[4],
    )

    promoted_physical_objects = copy.deepcopy(physical_objects)
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
    )


__all__ = [
    "CATALOG_DIGEST_PROTOCOL_VERSION",
    "CatalogRepublishError",
    "CatalogRepublishResult",
    "republish_catalog",
]
