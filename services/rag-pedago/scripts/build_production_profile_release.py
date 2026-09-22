#!/usr/bin/env python3
"""Construire la release production exacte issue du gate de profils 2026-2027."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple, Protocol

import nexus_pdf_page_policy as page_policy
import yaml
from nexus_contracts.embedding_utils import format_passage
from nexus_contracts.review_binding import (
    ReviewBindingError,
    TrustAnchor,
    verify_pii_review_decision_authority,
)
from nexus_release_chain.collection_config import load_collection_config
from nexus_release_chain.ingestion_profiles.manifest import verify_profile_manifest
from nexus_release_chain.ingestion_profiles.registry import (
    load_profile_registry,
    profile_fingerprint,
)
from nexus_release_chain.publication_chunking import chunk_publication
from nexus_release_chain.release_readiness import (
    load_release_expectation,
    load_release_registry_file,
)

from rag_pedago.governance.currentness_disposition import (
    CHEMIN_POLITIQUE as CURRENTNESS_POLICY_PATH,
)
from rag_pedago.governance.currentness_disposition import (
    DISPOSITIONS,
    NOT_CURRENT_DECLARED_BY_SOURCE,
    OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE,
    POLICY_ID,
    STATUT_ARCHIVE,
    VERIFIED_CURRENT,
    cas_depuis_ligne_de_matrice,
    charger_politique,
    conditions_de_repli,
    disposition_actualite,
)
from rag_pedago.imports.pii_review_projection import (
    PiiProjectionError,
    ScannedContent,
    ScannedFinding,
    finding_context,
    finding_identity,
    project_pii_review,
)
from rag_pedago.imports.pii_scanner import (
    extract_pdf_pages_with_structural_empty_pages,
    load_patterns_from_config,
    scan_pdf_bytes,
)
from rag_pedago.imports.raw_pii_guard import require_no_raw_pii

REPOSITORY_ROOT = Path(os.environ.get("NEXUS_REPO_ROOT") or Path(__file__).resolve().parents[3])

SCHOOL_YEAR = "2026-2027"
#: Identité de la release HISTORIQUE. ADR-0050 §1 en fait un enregistrement
#: immuable, jamais rescellé en place, et §3-§4 interdisent qu'une nouvelle
#: release la réutilise. Cette constante n'est donc PLUS un défaut : elle ne
#: sert qu'à nommer l'historique et à refuser une collision. Un producteur qui
#: retombait dessus en silence émettait une chaîne scellée différente sous une
#: identité déjà publiée — exactement la confusion qu'ADR-0050 ferme.
HISTORICAL_RELEASE_ID = "production-profile-gate-2026-2027-v1"

#: Identités déjà publiées dans ce dépôt, qu'aucune nouvelle release ne peut
#: reprendre (ADR-0050 §4). La liste est un plancher : le garde interroge en
#: plus le registre réellement présent sur disque.
PUBLISHED_RELEASE_IDS = frozenset(
    {
        HISTORICAL_RELEASE_ID,
        "production-profile-gate-2026-2027-v2-rehearsal",
        "production-profile-gate-2026-2027-v2-candidate-candidate-v2-20260904T084521Z",
    }
)

#: Forme admise : minuscules, chiffres, tiret et point, bornée. Une identité
#: libre laisserait passer un chemin, un espace ou un caractère qui casserait
#: la comparaison d'un registre à l'autre.
RELEASE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.\-]{7,127}$")


class ReleaseIdentityError(ValueError):
    """L'identité proposée pour une release est absente, malformée ou déjà prise."""


def require_governed_release_id(
    release_id: str | None,
    *,
    registry_path: Path | None = None,
    allow_historical: bool = False,
) -> str:
    """Exiger une identité de release explicitement gouvernée.

    ADR-0050 : aucune release ne se rescelle en place et aucune nouvelle
    release ne reprend une identité publiée. Le producteur ne peut donc plus
    retomber sur une constante quand l'appelant ne dit rien — ce silence
    produisait une chaîne scellée nouvelle sous une identité ancienne.

    ``allow_historical`` n'existe que pour rejouer la release historique
    elle-même : une épreuve qui reconstruit V1 doit pouvoir la nommer.
    """
    if not release_id or not release_id.strip():
        raise ReleaseIdentityError(
            "aucune identité de release n'a été fournie : ADR-0050 exige une "
            "identité explicitement gouvernée, jamais un repli sur l'identité "
            "historique. Passez --release-id."
        )
    release_id = release_id.strip()
    if not allow_historical:
        deja = set(PUBLISHED_RELEASE_IDS)
        registry = (
            registry_path
            if registry_path is not None
            else RELEASE_ROOT.parent / "release-registry.json"
        )
        try:
            payload = json.loads(Path(registry).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = None
        if isinstance(payload, dict):
            for entree in payload.get("releases", []) or []:
                identifiant = entree.get("release_id")
                if identifiant:
                    deja.add(str(identifiant))
        if release_id in deja:
            raise ReleaseIdentityError(
                f"identité déjà publiée : {release_id!r}. ADR-0050 §4 interdit "
                "qu'une nouvelle chaîne scellée reprenne une identité existante."
            )
    if not RELEASE_ID_PATTERN.fullmatch(release_id) and not allow_historical:
        raise ReleaseIdentityError(
            f"identité de release malformée : {release_id!r}. Attendu : "
            "minuscules, chiffres, tiret ou point, de 8 à 128 caractères."
        )
    return release_id
#: Empreinte de l'ensemble de contenus que la lignée canonique produit. Ce
#: n'est pas une affirmation : un test recalcule l'ensemble depuis la matrice
#: et les profils déclarés, et exige ce digest. Il coïncide par ailleurs avec
#: le `content_set_sha256` de l'index de la campagne de revue PII — le corpus
#: scellé et le corpus revu sont le même.
CANONICAL_CONTENT_SET_SHA256 = (
    "77f01c824c6be14ba6fd66eda99c2179fd87d9a2aaaf3c58e56a917d1ad5c31d"
)
#: Valeur que le fichier d'autorité de manifeste DÉCLARE (`authority_sha256`).
#: C'est elle que la release embarque sous `corpus_manifest_sha256`.
CORPUS_MANIFEST_AUTHORITY = (
    "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
)


def corpus_manifest_authority_file_sha256() -> str:
    """Empreinte des OCTETS du fichier d'autorité de manifeste.

    **Pourquoi ce n'est pas `CORPUS_MANIFEST_AUTHORITY`.** L'ensemble de
    décisions scellé enregistre l'empreinte du FICHIER ; la release embarque la
    valeur que ce fichier DÉCLARE. Deux mesures de la même autorité, jamais
    égales. Les confondre faisait refuser à la projection le corpus même sur
    lequel la revue humaine avait été rendue — « the decisions describe another
    corpus », sur les décisions qui le décrivent exactement — et rendait la
    candidate de production irreproductible.

    La liaison déclarée est vérifiée au passage : le fichier doit annoncer
    l'autorité que la release embarque, faute de quoi les deux grandeurs ne
    décrivent plus le même objet et l'égalité d'empreinte ne prouverait rien."""
    # Résolu à l'usage : `RELEASE_ROOT` est défini plus bas dans ce module, et
    # une constante de niveau module créerait une dépendance d'ordre inutile.
    path = RELEASE_ROOT / "corpus_manifest_authority.json"
    if not path.is_file():
        raise ValueError(
            f"corpus manifest authority is missing at {path.name} — the human "
            "review cannot be bound to a corpus nobody can read"
        )
    raw = path.read_bytes()
    declared = json.loads(raw.decode("utf-8")).get("authority_sha256")
    if declared != CORPUS_MANIFEST_AUTHORITY:
        raise ValueError(
            f"corpus manifest authority declares {str(declared)[:16]}… while this "
            f"release ships {CORPUS_MANIFEST_AUTHORITY[:16]}… — the file and the "
            "release do not describe the same corpus authority"
        )
    return hashlib.sha256(raw).hexdigest()
CANONICAL_EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
CANONICAL_EMBEDDING_REVISION = "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"
CANONICAL_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
CANONICAL_RERANKER_REVISION = "c5ee24cb16019beea0893ab7796b1df96625c6b8"
TARGET_TOKENS = 384
#: D-41 — le runtime fait partie des entrées de la release.
#:
#: `chunk_id` dérive du TEXTE des chunks, et le texte dépend de la version de
#: pypdf : 6.14.2 et 6.16.1 produisent deux découpages différents du même PDF.
#: Chacune est déterministe ; la release ne l'est qu'à interpréteur fixé. Le
#: 29/08/2026, une release a été produite hors du venv déclaré et a divergé de
#: la base sur 5 chunks — alors que `check_runtime_conformance.py` avait signalé
#: la divergence le matin même, classée « préexistante » et ignorée.
#:
#: 6.16.1 est en outre MOINS bonne : elle fragmente les mots sur la capitale
#: initiale (`Yoko` -> `Y` + `oko`, `République` -> `R` + `épublique`).
#:
#: La garde ne demande PAS que tous les runtimes concordent — l'image de
#: l'ingestor ne porte aucun pypdf et n'en portera jamais, elle n'extrait pas.
#: Elle demande : mon interpréteur est-il celui qui est déclaré ?
CANONICAL_PYPDF_VERSION = page_policy.CANONICAL_PYPDF_VERSION


def require_canonical_runtime() -> str:
    """D-41 : refuser de sceller hors du runtime déclaré. À la porte."""
    import pypdf as _pypdf

    version = str(_pypdf.__version__)
    if version != CANONICAL_PYPDF_VERSION:
        raise ValueError(
            f"D-41 : pypdf {version} n'est pas le runtime déclaré "
            f"({CANONICAL_PYPDF_VERSION}). Le découpage des chunks en dépend : "
            "produire ici donnerait une release irreproductible ailleurs. "
            "Exécuter le producteur dans le venv du service."
        )
    return version

RELEASE_ROOT = (
    REPOSITORY_ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate"
)
CURRENTNESS_NETWORK_AUDIT_PATH = RELEASE_ROOT / "currentness_network_audit.json"
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class ReleaseLineage:
    """Ce qui définit le corpus d'une release : matrice, profils, empreinte.

    Les trois voyagent ENSEMBLE. Les résoudre séparément, en trois endroits,
    est ce qui a permis à `build_release` de travailler sur une lignée que les
    constantes du module ne décrivaient pas."""

    matrix_path: Path
    profile_root: Path
    profile_manifest_path: Path
    expected_content_set_sha256: str
    is_overridden: bool


@dataclass(frozen=True)
class GovernedExclusionRegistry:
    """Registre gouverné scellé des contenus exclus pour cause d'actualité (ADR-0055)."""

    path: Path
    sha256: str
    excluded_contents: frozenset[str]
    kind: str
    governance_reference: str


def load_and_validate_exclusion_registry(
    registry_path: Path | None,
    expected_sha256: str | None = None,
    *,
    expected_count: int = 4,
) -> GovernedExclusionRegistry | None:
    """Charge et valide rigoureusement le registre d'exclusion d'actualité.

    Refuse fail-closed si le fichier est absent, le hash non conforme,
    les contenus non conformes ou ne correspondant pas aux 4 archives ADR-0055.
    """
    if registry_path is None:
        return None
    reg_path = Path(registry_path).resolve()
    if not reg_path.is_file():
        raise FileNotFoundError(f"exclusion registry absent: {reg_path}")
    raw_bytes = reg_path.read_bytes()
    actual_sha = hashlib.sha256(raw_bytes).hexdigest()

    sha_file = reg_path.with_suffix(".sha256")
    if expected_sha256:
        if actual_sha.lower() != expected_sha256.lower():
            raise ValueError(
                f"exclusion registry sha256 mismatch: expected {expected_sha256}, got {actual_sha}"
            )
    elif sha_file.is_file():
        expected = sha_file.read_text(encoding="utf-8").split()[0].lower()
        if actual_sha.lower() != expected:
            raise ValueError(
                f"exclusion registry sealed sha256 mismatch: expected {expected}, got {actual_sha}"
            )

    try:
        data = json.loads(raw_bytes.decode("utf-8"))
    except ValueError as e:
        raise ValueError(f"exclusion registry is not valid JSON: {e}") from e

    if data.get("kind") != "NEXUS-CURRENTNESS-EXCLUSION-REGISTRY-V1":
        raise ValueError(f"unexpected exclusion registry kind: {data.get('kind')}")
    if data.get("governance_reference") != "ADR-0055":
        raise ValueError(f"unexpected governance reference: {data.get('governance_reference')}")

    entries = data.get("excluded_contents", [])
    if len(entries) != expected_count:
        raise ValueError(f"exclusion registry count mismatch: expected {expected_count}, got {len(entries)}")

    excluded_shas = set()
    for entry in entries:
        sha = entry.get("content_sha256")
        if not sha or not isinstance(sha, str) or len(sha) != 64 or not _HEX64.fullmatch(sha):
            raise ValueError(f"invalid content_sha256 in exclusion registry: {sha}")
        if entry.get("currentness_status") != "ARCHIVE_DECLARED":
            raise ValueError(f"content {sha} must have currentness_status ARCHIVE_DECLARED")
        if entry.get("servability_verdict") != "BLOCKED_NOT_CURRENT_BY_SOURCE":
            raise ValueError(f"content {sha} must have servability_verdict BLOCKED_NOT_CURRENT_BY_SOURCE")
        excluded_shas.add(sha)

    return GovernedExclusionRegistry(
        path=reg_path,
        sha256=actual_sha,
        excluded_contents=frozenset(excluded_shas),
        kind=data["kind"],
        governance_reference=data["governance_reference"],
    )


@dataclass(frozen=True)
class GovernedCurrentnessAuthority:
    """La matrice de servabilité gouvernée et la politique appliquée (ADR-0055).

    Toutes deux sont INJECTÉES : le producteur ne décide aucune disposition
    d'actualité, il cite celle de la matrice et la vérifie contre la politique.
    La preuve V3 nomme l'empreinte des octets de l'une et de l'autre."""

    matrix_path: Path
    matrix_sha256: str
    rows_by_sha: Mapping[str, Mapping[str, Any]]
    policy: Mapping[str, Any]
    policy_path: Path
    policy_sha256: str
    policy_id: str


def load_governed_currentness_authority(
    matrix_path: Path | None,
    expected_matrix_sha256: str | None,
    *,
    policy_path: Path | None = None,
) -> GovernedCurrentnessAuthority:
    """Charge la matrice de servabilité et la politique, fail-closed.

    Refuse : matrice ou empreinte absente, empreinte différente des octets,
    matrice d'un autre type ou portant deux lignes pour un contenu, politique
    non appliquée (`charger_politique`) ou d'une autre identité."""
    if matrix_path is None:
        raise ValueError(
            "the governed servability matrix is required: currentness "
            "dispositions derive from it, never from the producer"
        )
    if not expected_matrix_sha256:
        raise ValueError("the expected sha256 of the servability matrix is required")
    path = Path(matrix_path).resolve()
    if not path.is_file():
        raise ValueError(f"servability matrix absent: {path}")
    raw = path.read_bytes()
    actual = _sha256_bytes(raw)
    if actual != expected_matrix_sha256.lower():
        raise ValueError(
            f"servability matrix sha256 mismatch: expected {expected_matrix_sha256}, "
            f"got {actual}"
        )
    document = json.loads(raw.decode("utf-8"))
    if not isinstance(document, dict) or document.get("kind") != "NEXUS-SERVABILITY-MATRIX-V1":
        raise ValueError("servability matrix kind is not NEXUS-SERVABILITY-MATRIX-V1")
    rows_by_sha: dict[str, Mapping[str, Any]] = {}
    for row in document.get("rows") or []:
        sha = row.get("content_sha256")
        if not isinstance(sha, str) or not _HEX64.fullmatch(sha):
            raise ValueError(f"servability matrix row has no content identity: {sha!r}")
        if sha in rows_by_sha:
            raise ValueError(f"servability matrix row is duplicated for {sha}")
        rows_by_sha[sha] = row
    if not rows_by_sha:
        raise ValueError("servability matrix has no row")

    resolved_policy_path = Path(policy_path or CURRENTNESS_POLICY_PATH).resolve()
    policy = charger_politique(resolved_policy_path)
    if policy.get("policy_id") != POLICY_ID:
        raise ValueError(
            f"currentness policy {policy.get('policy_id')!r} is not {POLICY_ID}"
        )
    return GovernedCurrentnessAuthority(
        matrix_path=path,
        matrix_sha256=actual,
        rows_by_sha=rows_by_sha,
        policy=policy,
        policy_path=resolved_policy_path,
        policy_sha256=_sha256_bytes(resolved_policy_path.read_bytes()),
        policy_id=POLICY_ID,
    )


#: La lignée SERVIE, déclarée ici et nulle part ailleurs : la matrice de
#: production du 31 août et les onze profils de la livraison 319. Une exécution
#: par défaut, depuis le commit candidat, reproduit ce corpus sans qu'aucune
#: variable d'environnement n'ait à être connue.
CANONICAL_LINEAGE = ReleaseLineage(
    matrix_path=REPOSITORY_ROOT / "docs/reports/evidence-index/matrice_production_20260831.json",
    profile_root=REPOSITORY_ROOT
    / "services/rag-engine/configs/ingestion_profiles/v2_livraison_319",
    profile_manifest_path=REPOSITORY_ROOT
    / "services/rag-engine/configs/ingestion_profiles/ingestion_manifest_v2_livraison_319.yml",
    expected_content_set_sha256=CANONICAL_CONTENT_SET_SHA256,
    is_overridden=False,
)


def resolve_release_lineage() -> ReleaseLineage:
    """Résout la lignée, une seule fois, pour tout le producteur.

    **Une surcharge n'éteint jamais l'invariant d'ensemble.** L'expression
    précédente — `FINAL_SET_SHA256 if not NEXUS_FINAL_MATRIX else ""` — faisait
    exactement cela : changer la matrice retirait la vérification d'empreinte,
    si bien qu'une émission surchargée pouvait produire n'importe quel corpus
    sans qu'aucun ensemble déclaré ne s'y oppose. C'était un défaut fail-open
    dans un producteur dont tout le reste est fail-closed.

    Une émission qui vise une autre lignée DOIT donc déclarer l'ensemble
    qu'elle attend, via `NEXUS_FINAL_SET_SHA256`. Épingler reste toujours
    permis ; éteindre ne l'est plus."""
    matrix = os.environ.get("NEXUS_FINAL_MATRIX")
    root = os.environ.get("NEXUS_PROFILE_ROOT")
    manifest = os.environ.get("NEXUS_PROFILE_MANIFEST")
    declared = os.environ.get("NEXUS_FINAL_SET_SHA256")
    overridden = any(value is not None for value in (matrix, root, manifest))

    if overridden and not declared:
        raise ValueError(
            "a lineage override (NEXUS_FINAL_MATRIX / NEXUS_PROFILE_ROOT / "
            "NEXUS_PROFILE_MANIFEST) requires NEXUS_FINAL_SET_SHA256: targeting "
            "another corpus never removes the obligation to declare which one"
        )
    expected = declared or CANONICAL_LINEAGE.expected_content_set_sha256
    if not _HEX64.match(expected):
        raise ValueError(
            f"NEXUS_FINAL_SET_SHA256 must be a lowercase 64-hex SHA-256, got {expected!r}"
        )
    return ReleaseLineage(
        matrix_path=Path(matrix) if matrix else CANONICAL_LINEAGE.matrix_path,
        profile_root=Path(root) if root else CANONICAL_LINEAGE.profile_root,
        profile_manifest_path=(
            Path(manifest) if manifest else CANONICAL_LINEAGE.profile_manifest_path
        ),
        expected_content_set_sha256=expected,
        is_overridden=overridden or bool(declared),
    )


#: Entrées par défaut = celles de la release scellée des onze (lignée B, LOT 1c) :
#: la matrice de production dérivée du 31/08, les onze profils `v2_livraison_319`
#: et leur manifeste au chemin que `authority_bindings.json` lie. Les surcharges
#: d'environnement restent possibles pour une émission différente, mais une
#: production « par défaut » reproduit la lignée servie — plus la lignée A.
#: Vues de la lignée CANONIQUE, pour les appelants qui n'ont pas de contexte
#: d'exécution. Elles ne lisent pas l'environnement : un import ne doit pas
#: échouer, ni changer de sens, selon les variables du shell qui l'entoure.
#: Les usages qui décident quelque chose passent par `resolve_release_lineage()`.
FINAL_MATRIX_PATH = CANONICAL_LINEAGE.matrix_path
FINAL_PRODUCTION_SET_PATH = (
    REPOSITORY_ROOT / "docs/reports/final_production_eligible_set_20260825.txt"
)
ACCEPTED_PLACEMENTS_PATH = (
    REPOSITORY_ROOT
    / "docs/reports/production_profile_accepted_placements_20260825.json"
)
VERIFIED_PROFILES_PATH = (
    REPOSITORY_ROOT / "docs/reports/verified_production_profiles_20260825.json"
)
PRIMARY_EVIDENCE_PATH = REPOSITORY_ROOT / "docs/reports/production_profile_primary_evidence_20260825.json"
DRIVE_MAPPING_PATH = (
    REPOSITORY_ROOT
    / "docs/reports/evidence-index/drive-snapshot/drive_snapshot_mapping_20260815.json"
)
#: Registre de contenus successeur, dérivé par exécution du registre du 14/08
#: (`deriver_content_ledger.py`, provenance à côté). Le registre du 14/08 reste
#: à son état attesté et n'est plus lu ici.
CONTENT_LEDGER_PATH = (
    REPOSITORY_ROOT / "docs/reports/evidence-index/content_ledger_20260902.jsonl"
)
PLACEMENT_LEDGER_PATH = (
    REPOSITORY_ROOT / "docs/reports/evidence-index/placement_ledger_20260814.jsonl"
)
OLD_RELEASE_ROOT = (
    REPOSITORY_ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027/multilevel"
)
P24_POLICY_PATH = REPOSITORY_ROOT / "services/rag-engine/configs/h2_initial_placement_policy.yml"
#: Quatrième autorité de fait de source, autorisée par ADR-0053 et scellée par
#: son empreinte externe. Elle vit DANS le corpus, sous 00_INDEX_PROVENANCE/ —
#: la zone que le README du corpus désigne comme celle de la traçabilité.
#:
#: Ce qu'elle atteste : `url_source`, l'URL de listing officielle dont le
#: document provient ; `type_document`, sa nature ; les faits bibliographiques.
#: Ce qu'elle N'ATTESTE PAS : aucune affirmation pédagogique, aucune décision de
#: niveau — son champ `niveau` est celui du catalogue amont, faux sur 72,3 % des
#: documents où l'éditeur s'est prononcé.
CATALOGUE_PROVENANCE_PATH = (
    REPOSITORY_ROOT / "docs/reports/evidence-index/eduscol_catalogue_par_scope_20260829.tsv"
)
CATALOGUE_PROVENANCE_SHA256 = (
    "ec5ccbf7a30fec012734061c5fd14761d2079a0bca527320847468a23523c79b"
)
#: Les trois entrées de périmètre sont surchargeables par l'environnement : une
#: seconde émission vise d'autres profils, un autre manifeste et une autre
#: matrice, sans que le producteur ait à être dupliqué. Les défauts restent ceux
#: de la release historique — aucune émission existante ne change de cible.
PROFILE_ROOT = CANONICAL_LINEAGE.profile_root
PROFILE_MANIFEST_PATH = CANONICAL_LINEAGE.profile_manifest_path
COLLECTION_CONFIG_PATH = REPOSITORY_ROOT / "services/rag-engine/configs/rag_collections.yml"


#: Dépôt dont un reçu de revue peut faire autorité ici. Constante du module,
#: comme dans l'outillage de provenance : une revue faite ailleurs ne décide
#: rien pour cette release. Ce n'est pas l'identité d'une campagne, qui,
#: elle, n'apparaît jamais dans ce fichier.
CANONICAL_REPOSITORY = "cyranoaladin/RAG"

PII_POLICY_PATH = REPOSITORY_ROOT / "services/rag-pedago/configs/pii_gate_policy.yml"
PII_SCANNER_PATH = REPOSITORY_ROOT / "services/rag-pedago/rag_pedago/imports/pii_scanner.py"
RIGHTS_REGISTRY_PATH = (
    REPOSITORY_ROOT / "services/rag-pedago/configs/rights_evidence_registry.yml"
)
LEVEL_MAPPING_PATH = (
    REPOSITORY_ROOT / "services/rag-engine/configs/mappings/eduscol_multilevel_levels.yml"
)
SUBJECT_MAPPING_PATH = (
    REPOSITORY_ROOT / "services/rag-engine/configs/mappings/eduscol_profile_gate_subjects.yml"
)
DOCUMENT_TYPE_MAPPING_PATH = (
    REPOSITORY_ROOT
    / "services/rag-engine/configs/mappings/eduscol_multilevel_document_types.yml"
)
DGEMC_INDEX_PATH = (
    RELEASE_ROOT / "programmes/dgemc_terminale_option.index.yml"
)

PROGRAMME_INDEX_PATHS = (
    "corpus/College/Quatrieme/_index.yml",
    "corpus/Lycee/Seconde/_index.yml",
    "corpus/Lycee/Premiere/Specialites/_index.yml",
    "corpus/Lycee/Premiere/Tronc_commun/_index.yml",
    "corpus/Lycee/Terminale/Specialites/_index.yml",
    "corpus/Lycee/Terminale/Tronc_commun/_index.yml",
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/programmes/dgemc_terminale_option.index.yml",
)

OFFICIAL_DOWNLOAD_URLS = {
    "03f268dc1f2628dbc76c58921ed868624437f06a15432ea055fff844f12aaf91": "https://eduscol.education.gouv.fr/sites/default/files/document/ra20lyceegtterphiloevaluations1318475pdf-83655.pdf",
    "06e491d369c5164d9f746176edeef45363cef53d3de2d5fb55153e6e96f98f2e": "https://eduscol.education.gouv.fr/sites/default/files/document/spe639annexe1063544pdf-82752.pdf",
    "2f1035c74db485d12e80d7c887cb9090807be32e5f79a6074d2decb1073ec154": "https://eduscol.education.gouv.fr/sites/default/files/document/spe253annexe1158821pdf-82755.pdf",
    "4433fee96b6e803c71edf2764d99bd269e649dcff646aee97327fdfeed143f13": "https://eduscol.education.gouv.fr/sites/default/files/document/ra19lyceeg1-thlpexemple-sujet-commentesujet-zero21205357pdf-83931.pdf",
    "60eeb7dd1ee55d1ed2bb2c7671ecf3c971aeef6996db2bc7cd9c7919ae4b19ac": "https://eduscol.education.gouv.fr/sites/default/files/document/ra19lyceeg1-t-hlplitterature-apprentissage-oral-etude-textes1219746pdf-83940.pdf",
    "64f5b3427dee3b23d421fe03cb2f3aac75e0e47cee31be91b197d4e09c012987": "https://eduscol.education.gouv.fr/sites/default/files/document/ra19lyceeg1-t-hlpphilosophie-apprentissage-oral-etude-textes1219750pdf-83943.pdf",
    "846962c15217af5cfe7ba40b173e94cb225d2153ffd3131d23b2c60a2b5e9a17": "https://eduscol.education.gouv.fr/sites/default/files/document/ra20lyceegtterphiloexercices21307357pdf-83652.pdf",
    "8eb0e41f95bf4aca37e6231c06109579faf6bf410d6bd2bc210574e66e2762fa": "https://eduscol.education.gouv.fr/sites/default/files/document/spe648annexe1063542pdf-82878.pdf",
    "9357dfdebca347264787dfebacb674666d87660b82f789657ddd230c7ff224aa": "https://eduscol.education.gouv.fr/sites/default/files/document/ra19lyceeg1-thlpexemple-sujet-commentesujet-zero31205359pdf-83934.pdf",
    "b5ed52b1a4754298f7ecdbc56cb886a438c580ebd04284be0ca878b82e7c62db": "https://eduscol.education.gouv.fr/sites/default/files/document/ra21lyceegtterphilorecommandations2-73131.pdf",
    "d2cbd06f2e8099d9080f17f3abb5b0fc90460b86b3c11f808b99daa01f77f897": "https://eduscol.education.gouv.fr/sites/default/files/document/spe252annexe1159114pdf-82881.pdf",
    "db43d342edf55e162d0153028b43287e4ece0ce81b4dc75f0730bf368b98c0f0": "https://eduscol.education.gouv.fr/sites/default/files/document/spe635annexe1063432pdf-82266.pdf",
    "e591a87aee633ca3b2593e2d4fd5b183e518ebe0f9d4861e4cdfe0f494f39439": "https://eduscol.education.gouv.fr/sites/default/files/document/annexeprogrammedgemcmodifiepdf-84138.pdf",
    "e7cf3bdb7a1c3831ccc465d842d8ab0dacb688d565cb35510aee4eac4f2bf5f9": "https://eduscol.education.gouv.fr/sites/default/files/document/ra20lyceegtterphiloetudestextes1294343pdf-83649.pdf",
    "f0dec90cafd512cb754fb71ed33dbf0a48f0e67a166be35b5b16a1daa6dd006d": "https://eduscol.education.gouv.fr/sites/default/files/document/ra20lyceegtterphilonotionsauteursreperes1304038pdf-83646.pdf",
}

MATHEMATICS_LISTING_URL = (
    "https://eduscol.education.gouv.fr/5817/"
    "programmes-et-ressources-en-mathematiques-voie-gt"
)


class CanonicalTokenCounter(Protocol):
    model_id: str
    model_revision: str
    max_sequence_length: int

    def passage_token_count(self, text: str) -> int: ...


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _compact_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _set_digest(values: Sequence[object]) -> str:
    if len(values) != len({json.dumps(value, sort_keys=True) for value in values}):
        raise ValueError("set digest input contains duplicate values")
    encoded = json.dumps(
        sorted(values, key=lambda item: json.dumps(item, sort_keys=True)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _final_set_digest(values: Sequence[str]) -> str:
    return _sha256_bytes(("\n".join(sorted(values)) + "\n").encode())


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _repo_relative(path: Path) -> str:
    return path.resolve().relative_to(REPOSITORY_ROOT.resolve()).as_posix()


class VerifiedPdf(NamedTuple):
    """Path identity and immutable bytes verified in one read."""

    path: Path
    content: bytes


def validate_pdf_mirror(
    *,
    pdf_root: Path,
    content_sha256: list[str],
    physical_paths: Mapping[str, str] | None = None,
) -> dict[str, VerifiedPdf]:
    """Lit chaque contenu du miroir UNE fois et le re-hache.

    Deux organisations sont admises : adressée par contenu (`<sha>.pdf`) ou
    par chemin (`physical_paths[sha]`, le chemin canonique du Drive). Dans les
    deux cas, les octets lus doivent porter l'empreinte demandée ; un chemin qui
    sortirait de la racine est refusé comme absent."""
    # Un contenu correspond à UN fichier du miroir : le miroir est 1:1 par
    # nature. Un même document demandé plusieurs fois est la conséquence normale
    # du multi-placement — il est placé dans plusieurs collections — et non une
    # anomalie. La demande se déduplique ; ce qui doit rester unique, c'est le
    # couple (collection, contenu), et c'est `stable_release_order` qui le tient.
    demandes = sorted(set(content_sha256))
    resolved: dict[str, VerifiedPdf] = {}
    root = pdf_root.resolve()
    for content_sha in demandes:
        path = (root / f"{content_sha}.pdf").resolve()
        if not path.is_file() and physical_paths and content_sha in physical_paths:
            path = (root / physical_paths[content_sha]).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"PDF mirror is missing content {content_sha}")
        content = path.read_bytes()
        if _sha256_bytes(content) != content_sha:
            raise ValueError(f"PDF mirror digest differs for {content_sha}")
        resolved[content_sha] = VerifiedPdf(path=path, content=content)
    return resolved


def stable_release_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ordonner les lignes de release, en refusant le seul doublon qui en est un.

    L'INVARIANT CONSERVÉ — un même contenu ne peut pas être placé deux fois dans
    la MÊME collection. C'est le doublon réel, et il reste refusé.

    LE CONTRÔLE RETIRÉ — un contrôle d'unicité globale du `content_sha256`
    interdisait qu'un contenu apparaisse dans deux collections différentes,
    c'est-à-dire interdisait le MULTI-PLACEMENT. Il contredisait trois sources
    indépendantes du dépôt :

      1. le modèle de données — la migration `004_artifact_placements` déclare
         « identité produit liée au contenu et placements 1:N » ;
      2. le mandat, qui consacre un chapitre au multi-placement ;
      3. la conception du corpus — son README énonce une seule copie canonique
         pour plusieurs affectations : 2 956 affectations pour 2 451 documents,
         dont 505 pour cette raison exacte.

    Il n'avait jamais été éprouvé : la release historique porte 26 placements
    pour 26 artefacts. Ce n'est donc pas un garde-fou que l'on lève, c'est une
    contradiction que l'on retire. Décision opérateur du 29/08/2026.
    """
    keys = [(row.get("collection"), row.get("content_sha256")) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("release contains duplicate collection/content")
    return sorted(rows, key=lambda row: (row["collection"], row["content_sha256"]))


def require_canonical_token_counter(token_counter: object) -> None:
    if getattr(token_counter, "model_id", None) != CANONICAL_EMBEDDING_MODEL:
        raise ValueError("token counter model identity differs")
    if getattr(token_counter, "model_revision", None) != CANONICAL_EMBEDDING_REVISION:
        raise ValueError("token counter model revision differs")
    if getattr(token_counter, "max_sequence_length", 0) < TARGET_TOKENS:
        raise ValueError("token counter sequence length is too small")
    if not callable(getattr(token_counter, "passage_token_count", None)):
        raise ValueError("token counter is unavailable")


class E5TokenCounter:
    model_id = CANONICAL_EMBEDDING_MODEL
    model_revision = CANONICAL_EMBEDDING_REVISION

    def __init__(self, snapshot: Path) -> None:
        from transformers import AutoTokenizer

        if snapshot.name != self.model_revision or not snapshot.is_dir():
            raise ValueError("E5 tokenizer snapshot revision differs")
        self._tokenizer = AutoTokenizer.from_pretrained(
            str(snapshot), local_files_only=True
        )
        self.max_sequence_length = int(self._tokenizer.model_max_length)
        require_canonical_token_counter(self)

    def passage_token_count(self, text: str) -> int:
        encoded = self._tokenizer(
            format_passage(text), add_special_tokens=True, truncation=False
        )
        count = len(encoded["input_ids"])
        if count <= 0:
            raise ValueError("E5 tokenizer returned no token")
        return count


def _model_inventory(
    *, snapshot: Path, manifest: Mapping[str, object]
) -> tuple[bytes, bytes]:
    """Sceller la totalité du snapshot, sous-répertoires compris.

    Le parcours était `snapshot.iterdir()` — non récursif — filtré par
    `is_file()`, qui écarte les répertoires **sans erreur ni avertissement**.
    Tout sous-répertoire disparaissait donc du sceau, et l'artefact construit
    sur cet inventaire en était amputé.

    Le 27/08/2026, cela a produit un artefact embedding sans `1_Pooling/` :
    conforme à son empreinte, et incapable de se charger — `sentence_transformers`
    lit `modules.json`, ne trouve pas le module de pooling en local, et retombe
    sur un téléchargement distant qui échoue. Le seul garde-fou existant
    (« model inventory has no weights ») protégeait les poids, pas la structure.

    `rglob` aligne ce producteur sur `scripts/e2e/prepare-embedding-model-artifact.sh`,
    qui scelle par `find . -type f`. Les chemins restent relatifs à la racine du
    snapshot, avec un tri déterministe sur le chemin POSIX complet.
    """
    if not snapshot.is_dir():
        raise ValueError(f"model snapshot is missing: {snapshot}")
    manifest_bytes = canonical_json_bytes(manifest)
    rows = [f"{_sha256_bytes(manifest_bytes)}  manifest.json"]
    # `is_file()` suit les liens symboliques, et c'est requis : le cache hub
    # HuggingFace — passé tel quel en `--embedding-snapshot`, son nom devant être
    # la révision — ne contient que des liens vers `../../blobs`. Les exclure
    # viderait l'inventaire. `_file_sha256` scelle le contenu pointé, ce qui est
    # la propriété voulue.
    entries = sorted(
        (path for path in snapshot.rglob("*") if path.is_file()),
        key=lambda item: item.relative_to(snapshot).as_posix(),
    )
    for path in entries:
        relative = path.relative_to(snapshot).as_posix()
        if relative in {"manifest.json", "SHA256SUMS"}:
            continue
        rows.append(f"{_file_sha256(path)}  {relative}")
    if not any(row.endswith("model.safetensors") for row in rows):
        raise ValueError("model inventory has no weights")
    _require_declared_modules_are_present(snapshot)
    return manifest_bytes, ("\n".join(rows) + "\n").encode()


#: Types de modules `sentence_transformers` qui ne portent AUCUN fichier. Un
#: module de ce type n'a pas de répertoire, même dans un artefact complet :
#: exiger le sien refuserait l'instantané qui sert aujourd'hui.
_PARAMETERLESS_MODULE_TYPES = frozenset({"sentence_transformers.models.Normalize"})


def _require_declared_modules_are_present(snapshot: Path) -> None:
    """Un instantané doit contenir les modules que `modules.json` déclare.

    Le 27/08/2026, un artefact embedding a été scellé sans `1_Pooling/` :
    conforme à son empreinte, et incapable de se charger — `sentence_transformers`
    lit `modules.json`, ne trouve pas le module de pooling en local, et retombe
    sur un téléchargement distant qui échoue hors ligne. « Pas de poids, pas
    d'inventaire » protégeait les poids ; rien ne protégeait la structure.

    La règle appliquée est celle que le fichier énonce lui-même, et non une
    liste de fichiers devinée : chaque module déclaré avec un chemin doit
    exister. Un type inconnu et absent fait échouer — un garde-fou qui ne
    reconnaît pas quelque chose se ferme, il ne suppose pas."""
    modules_path = snapshot / "modules.json"
    if not modules_path.is_file():
        # Tout instantané n'est pas un sentence-transformer : le reranker, par
        # exemple, n'a pas de `modules.json` et n'a donc rien à déclarer.
        return
    try:
        declared = json.loads(modules_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"modules.json is not readable in {snapshot}: {exc}") from exc
    if not isinstance(declared, list):
        raise ValueError(f"modules.json must declare a list in {snapshot}")
    for module in declared:
        if not isinstance(module, dict):
            raise ValueError(f"modules.json carries a non-object module in {snapshot}")
        relative = str(module.get("path") or "")
        if not relative:
            continue  # le transformeur racine, déjà couvert par les poids
        if str(module.get("type")) in _PARAMETERLESS_MODULE_TYPES:
            continue
        if not (snapshot / relative).is_dir():
            raise ValueError(
                f"model snapshot {snapshot.name} declares module {relative!r} "
                f"({module.get('type')}) in modules.json but does not carry it — "
                "the artifact would seal cleanly and fail to load"
            )


def _old_artifacts() -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for path in sorted(OLD_RELEASE_ROOT.rglob("*.release.json")):
        if path.name == "multilevel.release.json":
            continue
        document = _load_json(path)
        for artifact in document.get("artifacts", []):
            artifact = dict(artifact)
            artifact["evidence_path"] = _repo_relative(path)
            artifacts[artifact["content_sha256"]] = artifact
    return artifacts


def _title_from_path(path: str) -> str:
    stem = Path(path).stem.rsplit("--", 1)[0]
    return re.sub(r"\s+", " ", stem.replace("-", " ")).strip().capitalize()


def _load_catalogue_provenance() -> dict[str, dict[str, str]]:
    """Charger le catalogue de provenance après vérification de son empreinte.

    Une autorité non scellée dérive en silence : l'empreinte est vérifiée à
    chaque chargement, et un écart refuse la production plutôt que de sceller
    une release sur une source qui a changé sans qu'on le sache.
    """
    import csv as _csv

    octets = CATALOGUE_PROVENANCE_PATH.read_bytes()
    empreinte = hashlib.sha256(octets).hexdigest()
    if empreinte != CATALOGUE_PROVENANCE_SHA256:
        raise ValueError(
            f"catalogue de provenance non conforme : attendu "
            f"{CATALOGUE_PROVENANCE_SHA256}, obtenu {empreinte}"
        )
    lignes = _csv.DictReader(
        octets.decode("utf-8").splitlines(), delimiter="\t")
    return {ligne["sha256"]: ligne for ligne in lignes}


def _source_records(
    *, matrix: list[dict[str, Any]], profiles: Mapping[str, Any]
) -> list[dict[str, Any]]:
    drive = {row["content_sha256"]: row for row in _load_json(DRIVE_MAPPING_PATH)}
    primary = {
        row["content_sha256"]: row
        for row in _load_json(PRIMARY_EVIDENCE_PATH)["records"]
    }
    old = _old_artifacts()
    p24 = _load_yaml(P24_POLICY_PATH)["approved_artifacts"]
    provenance = _load_catalogue_provenance()
    placement_rows: list[dict[str, Any]] = []
    subject_names = {
        "maths": "mathematiques",
        "physique_chimie": "physique-chimie",
    }
    for matrix_row in matrix:
        collection = matrix_row["dimensions"]["collection"]["value"]
        if collection not in profiles:
            continue
        profile = profiles[collection]
        for content_sha in matrix_row["content_sha256"]:
            mirror = drive.get(content_sha)
            if mirror is None or mirror.get("mime_type") != "application/pdf":
                raise ValueError(f"Drive snapshot PDF is absent for {content_sha}")
            old_artifact = old.get(content_sha)
            primary_row = primary.get(content_sha)
            p24_row = p24.get(content_sha)
            if old_artifact:
                download_url = old_artifact["source_url"]
                listing_url = (
                    MATHEMATICS_LISTING_URL
                    if "education.gouv.fr" in download_url
                    and "eduscol.education.gouv.fr" not in download_url
                    else download_url
                )
                title = old_artifact["title"]
                type_doc = (
                    "programme-officiel"
                    if old_artifact["type_doc"] == "programme_officiel"
                    else "reperes-attendus"
                )
                evidence = old_artifact["evidence_path"]
            # `OFFICIAL_DOWNLOAD_URLS` est la table figée des documents de la
            # release historique. Un document présent dans `primary_evidence`
            # mais absent de cette table n'a pas d'URL de téléchargement
            # connue : il descend à l'autorité suivante plutôt que de lever.
            elif primary_row and content_sha in OFFICIAL_DOWNLOAD_URLS:
                listing_url = primary_row["official_source_url"]
                download_url = OFFICIAL_DOWNLOAD_URLS[content_sha]
                title = _title_from_path(mirror["canonical_path"])
                type_doc = (
                    "programme-officiel"
                    if "/01_PROGRAMMES_OFFICIELS/" in mirror["canonical_path"]
                    else "ressource-accompagnement"
                )
                evidence = _repo_relative(PRIMARY_EVIDENCE_PATH)
            elif p24_row:
                listing_url = p24_row["source_url"]
                download_url = OFFICIAL_DOWNLOAD_URLS[content_sha]
                title = _title_from_path(mirror["canonical_path"])
                type_doc = p24_row["source_document_type"]
                evidence = _repo_relative(P24_POLICY_PATH)
            else:
                prov = provenance.get(content_sha)
                if prov and prov.get("url_source"):
                    # Quatrième autorité : le catalogue de provenance du corpus.
                    # Il porte l'URL de listing et le type documentaire ; il ne
                    # porte AUCUNE décision de niveau, qui vient des placements.
                    listing_url = prov["url_source"]
                    title = prov.get("titre") or ""
                    type_doc = prov.get("type_document") or "ressource_officielle"
                    # Le catalogue de provenance porte l'URL de LISTING, jamais
                    # l'URL de téléchargement direct. Les deux ne sont pas la
                    # même chose, et présenter l'une pour l'autre serait
                    # affirmer une provenance qu'on n'a pas. Le champ reste vide.
                    download_url = None
                    evidence = _repo_relative(CATALOGUE_PROVENANCE_PATH)
                else:
                    raise ValueError(
                        f"content {content_sha} has no release source fact")
            level = profile.scope.niveau.value
            external_level = "4e" if level == "quatrieme" else level
            matiere = str(profile.scope.matiere)
            external_subject = subject_names.get(matiere, matiere)
            external_scope = (
                f"college/{external_level}/{external_subject}"
                if profile.scope.voie.value == "college"
                else f"lycee/general/{external_subject}"
            )
            source_placement_id = _sha256_bytes(
                _compact_json_bytes(
                    {
                        "collection": collection,
                        "content_sha256": content_sha,
                        "source_url": listing_url,
                    }
                )
            )
            year_match = re.search(r"/(20[0-9]{2})/", mirror["canonical_path"])
            placement_rows.append(
                {
                    "collection": collection,
                    "content_sha256": content_sha,
                    "physical_path": mirror["canonical_path"],
                    "drive_file_id": mirror["drive_file_id"],
                    "drive_modified_time": mirror["modified_time"],
                    "drive_size": mirror["size"],
                    "source_placement_id": source_placement_id,
                    "source_url": listing_url,
                    "current_download_url": download_url,
                    "title": title,
                    "external_level": external_level,
                    "external_subject": external_subject,
                    "external_scope": external_scope,
                    "external_document_type": type_doc,
                    "year": year_match.group(1) if year_match else "2026",
                    "partition_id": matrix_row["partition_id"],
                    "source_evidence": evidence,
                }
            )
    ordered = stable_release_order(placement_rows)
    # L'INVARIANT : l'ensemble produit doit être EXACTEMENT l'ensemble déclaré.
    # Il vaut, et il reste. C'est la CONSTANTE qui figeait le périmètre d'un
    # jour — `!= 26` et une empreinte gravée — comme le faisait `!= 18` pour les
    # profils. Un producteur qui ne peut produire qu'une seule release n'est pas
    # un producteur.
    #
    # L'ensemble déclaré se lit désormais dans son fichier, surchargeable. Le
    # défaut reste celui de la release historique : aucune émission existante ne
    # change de référence.
    attendu = sorted({
        contenu
        for ligne in matrix
        if ligne["dimensions"]["collection"]["value"] in profiles
        for contenu in ligne["content_sha256"]
    })
    produit = sorted({row["content_sha256"] for row in ordered})
    if produit != attendu:
        manquants = len(set(attendu) - set(produit))
        surnumeraires = len(set(produit) - set(attendu))
        raise ValueError(
            f"release source placement_rows differ from the final set: "
            f"{manquants} manquants, {surnumeraires} surnuméraires"
        )
    attendue = resolve_release_lineage().expected_content_set_sha256
    if _final_set_digest(produit) != attendue:
        raise ValueError("release source placement_rows differ from the sealed final set")
    return ordered


def _catalog_documents(placement_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    unique_artifacts = _group_artifact_rows(placement_rows)
    additions = [
        {
            "collection": row["collection"],
            "content_sha256": row["content_sha256"],
            "physical_path": row["physical_path"],
            "source_placement_id": row["source_placement_id"],
        }
        for row in placement_rows
    ]
    payload_sha = _sha256_bytes(_compact_json_bytes(additions))
    delta = {
        "catalog_delta_kind": "PRODUCTION_PROFILE_GATE_CATALOG_PROJECTION_V1",
        "school_year": SCHOOL_YEAR,
        "parent_catalog_path": _repo_relative(DRIVE_MAPPING_PATH),
        "parent_catalog_sha256": _file_sha256(DRIVE_MAPPING_PATH),
        "catalog_delta_payload_sha256": payload_sha,
        "counts": {
            "unique_artifacts": len(unique_artifacts),
            "placements": len(placement_rows),
        },
        "placements": additions,
    }
    delta_sha = _sha256_bytes(canonical_json_bytes(delta))
    effective_sha = _sha256_bytes(
        _compact_json_bytes(
            {
                "parent_sealed_catalog_sha256": _file_sha256(DRIVE_MAPPING_PATH),
                "catalog_delta_sha256": delta_sha,
                "catalog_delta_payload_sha256": payload_sha,
            }
        )
    )
    effective = {
        "authority_kind": "EFFECTIVE_PROFILE_GATE_CATALOG_V1",
        "authority_sha256": effective_sha,
        "parent_sealed_catalog_sha256": _file_sha256(DRIVE_MAPPING_PATH),
        "catalog_delta_sha256": delta_sha,
        "catalog_delta_payload_sha256": payload_sha,
    }
    return delta, effective


def _candidate_inventory(
    placement_rows: list[dict[str, Any]], *, delta: Mapping[str, Any], effective: Mapping[str, Any]
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in placement_rows:
        grouped[row["collection"]].append(row)
    collections = []
    # D-44 appliquée aux variables. Ces trois noms ont produit deux fois la même
    # faute dans ce fichier, à mille lignes d'écart : `records` ne disait pas
    # qu'il s'agit de PLACEMENTS, et `all_shas` ne disait pas que la liste en
    # porte un par placement — donc 486 pour 319 documents. Une fois les
    # variables nommées, `len(placement_shas)` sous un champ `unique_artifacts`
    # devient inécrivable.
    placement_shas = sorted(row["content_sha256"] for row in placement_rows)
    unique_shas = sorted(set(placement_shas))
    for collection in sorted(grouped):
        rows = sorted(grouped[collection], key=lambda row: row["content_sha256"])
        candidates = []
        for row in rows:
            candidates.append(
                {
                    "content_sha256": row["content_sha256"],
                    "physical_path": row["physical_path"],
                    "physical_currentness_candidate": "actuel",
                    "physical_disposition_candidate": "INGEST",
                    "placements": [
                        {
                            "source_placement_id": row["source_placement_id"],
                            "source_url": row["source_url"],
                            "title": row["title"],
                            "external_level": row["external_level"],
                            "external_subject": row["external_subject"],
                            "external_scope": row["external_scope"],
                            "external_document_type": row["external_document_type"],
                            "pedagogical_status": "production_eligible",
                            "year": row["year"],
                            "placement_origin": "PRODUCTION_PROFILE_GATE_20260825",
                            "placement_reason_code": row["partition_id"],
                        }
                    ],
                }
            )
        first = rows[0]
        collections.append(
            {
                "phase": "production_profile_gate",
                "collection": collection,
                "external_level": first["external_level"],
                "external_subject": first["external_subject"],
                "external_scope": first["external_scope"],
                "counts": {
                    "unique_artifacts": len({row["content_sha256"] for row in rows}),
                    "placements": len(rows),
                },
                "observed_values": {
                    "document_types": sorted(
                        {row["external_document_type"] for row in rows}
                    )
                },
                "discovery_routes": [first["source_url"]],
                "inventory_disposition": "RELEASE_ELIGIBLE",
                "candidate_partition": {
                    "release_eligible": sorted(row["content_sha256"] for row in rows),
                    "review_required": [],
                },
                "candidates": candidates,
            }
        )
    return {
        "inventory_kind": "MULTILEVEL_CANDIDATE_INVENTORY_V1",
        "school_year": SCHOOL_YEAR,
        "corpus_manifest_sha256": CORPUS_MANIFEST_AUTHORITY,
        "sealed_catalog_sha256": _file_sha256(DRIVE_MAPPING_PATH),
        "placement_catalog_sha256": _file_sha256(PLACEMENT_LEDGER_PATH),
        "catalog_delta_sha256": _sha256_bytes(canonical_json_bytes(delta)),
        "catalog_delta_payload_sha256": delta["catalog_delta_payload_sha256"],
        "effective_catalog_authority_sha256": effective["authority_sha256"],
        # D-44 : les comptes sont RECOMPTÉS depuis la structure émise, avec la
        # sémantique exacte du chargeur (`_inventory_counts`), jamais tirés de
        # variables qui pourraient désigner autre chose.
        "counts": _inventory_counts(collections),
        "collection_partition": {
            "production_profile_exact": sorted(grouped),
            "review_required": [],
            "unevaluated": [],
        },
        "candidate_partition": {
            # Une PARTITION de candidats, donc des documents distincts. Elle
            # portait `all_shas` — un sha par placement — et listait donc 167
            # documents deux fois. Le défaut est le même que celui des comptes,
            # dans la charge utile plutôt que dans son cardinal.
            "exact_grade_gate_pending": unique_shas,
            "named_noneligible": [],
            "unevaluated": [],
        },
        "collections": collections,
    }


def _inventory_counts(collections: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Comptes d'inventaire, avec la sémantique que le chargeur recompte.

    - `unique_artifacts` : contenus distincts ;
    - `placements` : un par placement de candidat ;
    - `physical_objects` : objets physiques distincts, UN par contenu — le
      chargeur les indexe par empreinte et refuse deux chemins pour un même
      contenu ; il vaut donc `unique_artifacts`, et le refus ci-dessous le
      garantit plutôt que de le supposer ;
    - `multi_placement_artifacts` : contenus portés par plus d'un placement.

    Le 486 pour 319 de la release historique venait de comptes écrits à
    côté de la structure qu'ils décrivaient. Ici, ils en sont dérivés."""
    physical_by_sha: dict[str, str] = {}
    multiplicity: Counter[str] = Counter()
    for collection in collections:
        for candidate in collection["candidates"]:
            sha = candidate["content_sha256"]
            if physical_by_sha.setdefault(sha, candidate["physical_path"]) != candidate[
                "physical_path"
            ]:
                raise ValueError(f"inventory content {sha} has conflicting physical paths")
            multiplicity[sha] += len(candidate["placements"])
    return {
        "target_collections": len(collections),
        "unique_artifacts": len(physical_by_sha),
        "placements": sum(multiplicity.values()),
        "physical_objects": len(physical_by_sha),
        "multi_placement_artifacts": sum(1 for n in multiplicity.values() if n > 1),
    }


def _dedupe(values: Sequence[str], *, excluded: frozenset[str]) -> list[str]:
    return sorted({value for value in values if value not in excluded})


def _recount_candidate_inventory(
    source: Mapping[str, Any], *, excluded: frozenset[str]
) -> dict[str, Any]:
    """Reprend l'inventaire d'une release source, sans ses exclus, recompté.

    La voie de répétition RECOPIAIT l'inventaire source octet pour octet :
    les contenus exclus (ADR-0055) y restaient, et ses comptes — 486
    `unique_artifacts` pour 319 contenus, `multi_placement_artifacts: 0` —
    étaient refusés par le chargeur. Les autorités qu'il cite (catalogue,
    delta, autorité effective) sont conservées telles quelles : seule la
    population et ses comptes changent."""
    collections = []
    for collection in source["collections"]:
        candidates = [
            candidate
            for candidate in collection["candidates"]
            if candidate["content_sha256"] not in excluded
        ]
        if not candidates:
            continue
        shas = {candidate["content_sha256"] for candidate in candidates}
        partition = dict(collection.get("candidate_partition") or {})
        collections.append(
            {
                **collection,
                "counts": {
                    "unique_artifacts": len(shas),
                    "placements": sum(len(c["placements"]) for c in candidates),
                },
                "candidate_partition": {
                    key: _dedupe(values, excluded=excluded)
                    for key, values in partition.items()
                },
                "candidates": candidates,
            }
        )
    kept = {collection["collection"] for collection in collections}
    unique_shas = {
        candidate["content_sha256"]
        for collection in collections
        for candidate in collection["candidates"]
    }
    source_partition = source["candidate_partition"]
    named = _dedupe(source_partition.get("named_noneligible", []), excluded=excluded)
    unevaluated = _dedupe(source_partition.get("unevaluated", []), excluded=excluded)
    pending = sorted(unique_shas - set(named) - set(unevaluated))
    if set(pending) | set(named) | set(unevaluated) != unique_shas or set(named) & set(
        unevaluated
    ):
        raise ValueError("source inventory partition does not cover its artifact set")
    return {
        **source,
        "counts": _inventory_counts(collections),
        "collection_partition": {
            key: [name for name in values if name in kept]
            for key, values in source["collection_partition"].items()
        },
        "candidate_partition": {
            **source_partition,
            "exact_grade_gate_pending": pending,
            "named_noneligible": named,
            "unevaluated": unevaluated,
        },
        "collections": collections,
    }


def _release_scope_inputs(
    *,
    matrix: list[dict[str, Any]],
    profiles: Mapping[str, Any],
    profile_manifest_digest: str,
    release_id: str,
) -> tuple[bytes, bytes, bytes]:
    placements: list[dict[str, str]] = []
    profile_sources: dict[str, str] = {}
    for row in matrix:
        dimensions = row["dimensions"]
        collection = dimensions["collection"]["value"]
        if collection not in profiles:
            continue
        profile = profiles[collection]
        sources = {
            dimension["source_of_truth"] for dimension in dimensions.values()
        }
        if len(sources) != 1:
            raise ValueError(f"profile source is ambiguous for {collection}")
        source_path = next(iter(sources))
        expected_prefix = "services/rag-engine/configs/ingestion_profiles/"
        if not source_path.startswith(expected_prefix) or not source_path.endswith(
            ".yml"
        ):
            raise ValueError(f"profile source is not canonical for {collection}")
        if collection in profile_sources and profile_sources[collection] != source_path:
            raise ValueError(f"profile source differs for {collection}")
        profile_sources[collection] = source_path
        for content_sha256 in row["content_sha256"]:
            placements.append(
                {
                    "content_sha256": content_sha256,
                    "release_id": release_id,
                    "collection": collection,
                    "profile_version": profile.profile_version,
                }
            )
    placements = sorted(
        placements,
        key=lambda row: (row["content_sha256"], row["collection"]),
    )
    contents = sorted({row["content_sha256"] for row in placements})
    # Même famille que `!= 18` et `!= 26` plus haut : l'invariant — l'ensemble
    # des placements couvre exactement l'ensemble déclaré — vaut et reste. La
    # constante figeait le périmètre d'un jour.
    attendu_scope = sorted(
        {
            c
            for ligne in matrix
            if ligne["dimensions"]["collection"]["value"] in profiles
            for c in ligne["content_sha256"]
        }
    )
    if sorted(set(contents)) != attendu_scope:
        raise ValueError(
            f"release scope inputs differ from the final set: "
            f"{len(set(attendu_scope) - set(contents))} manquants, "
            f"{len(set(contents) - set(attendu_scope))} surnuméraires")
    attendue = resolve_release_lineage().expected_content_set_sha256
    if _final_set_digest(contents) != attendue:
        raise ValueError("release scope inputs differ from the sealed final set")
    # La provenance enregistre la source RÉELLEMENT LUE. Ce chemin était figé sur
    # `v2_corpus_complet` alors que le répertoire est paramétré par
    # NEXUS_PROFILE_ROOT : une release produite depuis `v2_livraison_319`
    # affirmait que ses profils venaient des 121. La provenance est précisément ce
    # que cette chaîne existe pour garantir ; un chemin en dur la rendait fausse
    # dès que le paramètre servait.
    profile_root = resolve_release_lineage().profile_root.resolve()
    profile_root_relative = (
        profile_root.relative_to(REPOSITORY_ROOT).as_posix()
        if profile_root.is_relative_to(REPOSITORY_ROOT)
        else profile_root.as_posix()
    )
    for collection in profiles:
        if collection not in profile_sources:
            profile_sources[collection] = f"{profile_root_relative}/{collection}.yml"

    verified_profiles = {
        "profile_manifest_digest": profile_manifest_digest,
        "profiles": [
            {
                "profile_id": collection,
                "profile_version": profiles[collection].profile_version,
                "profile_fingerprint": profile_fingerprint(profiles[collection]),
                "scope": profiles[collection].scope.model_dump(mode="json"),
                "source_path": profile_sources[collection],
            }
            for collection in sorted(profile_sources)
        ],
    }
    # L'invariant est que TOUS les profils du registre sont vérifiés — pas qu'ils
    # soient dix-huit. Le manifeste est la référence, comme pour le verrou du
    # registre corrigé plus haut.
    if len(verified_profiles["profiles"]) != len(profiles):
        raise ValueError(
            f"verified production profile count differs: "
            f"{len(verified_profiles['profiles'])} vérifiés pour "
            f"{len(profiles)} profils")
    return (
        ("\n".join(contents) + "\n").encode("utf-8"),
        canonical_json_bytes(placements),
        canonical_json_bytes(verified_profiles),
    )


def _verify_official_downloads(placement_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    audit = []
    for group in _group_artifact_rows(placement_rows).values():
        row = group["artifact_row"]
        completed = subprocess.run(
            [
                "curl",
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                row["current_download_url"],
            ],
            check=True,
            capture_output=True,
        )
        observed = _sha256_bytes(completed.stdout)
        if observed != row["content_sha256"]:
            raise ValueError(
                f"official download digest differs for {row['content_sha256']}"
            )
        audit.append(
            {
                "content_sha256": row["content_sha256"],
                "current_source_listing_url": row["source_url"],
                "current_download_url": row["current_download_url"],
                "downloaded_sha256": observed,
                "byte_identity": True,
            }
        )
    return audit


def _corpus_binding(placement_rows: list[dict[str, Any]]) -> dict[str, str]:
    """Ce que tout audit de fraîcheur NOMME : le corpus qu'il a mesuré.

    Un audit rescellé à côté d'une autre preuve doit rester refusable par le
    lecteur : il porte donc le manifeste corpus et l'ensemble exact de contenus
    (même canonicalisation que `_final_set_digest`)."""
    return {
        "corpus_manifest_sha256": CORPUS_MANIFEST_AUTHORITY,
        "content_set_sha256": _final_set_digest(sorted(_group_artifact_rows(placement_rows))),
    }


def _currentness_network_audit_document(
    network_rows: list[dict[str, Any]],
    *,
    placement_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "audit_kind": "PRODUCTION_PROFILE_GATE_CURRENTNESS_AUDIT_V1",
        **_corpus_binding(placement_rows),
        "verified_at": "2026-08-25T00:00:00Z",
        "network_mode": "READ_ONLY",
        "write_operations": 0,
        "counts": {"verified": len(network_rows), "digest_mismatch": 0},
        "artifacts": network_rows,
    }


def _expected_currentness_network_rows(
    placement_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "content_sha256": row["content_sha256"],
            "current_source_listing_url": row["source_url"],
            "current_download_url": row["current_download_url"],
            "downloaded_sha256": row["content_sha256"],
            "byte_identity": True,
        }
        for group in _group_artifact_rows(placement_rows).values()
        for row in (group["artifact_row"],)
    ]


def _out_of_band_currentness_evidence() -> list[dict[str, str]]:
    """Les rapports qui relatent l'enquête de fraîcheur, avec CE QU'ILS ÉTABLISSENT.

    Le producteur ne fait aucune tentative réseau dans la branche hors ligne ; il
    ne peut donc consigner aucun essai. Ce qu'il peut faire — et ce qui est
    vérifiable — c'est NOMMER les documents qui relatent l'enquête, en sceller
    l'empreinte, et dire ce que chacun établit. Un lecteur peut les ouvrir et
    juger ; il ne peut pas juger un nombre.

    `establishes` décrit ce que le rapport DIT, jamais un décompte d'hypothèses :
    aucune trace structurée n'existe des essais eux-mêmes — ni horodatage par
    requête, ni code de retour par URL. Cette lacune est déclarée ici plutôt que
    comblée : l'inventer serait fabriquer la preuve que cet artefact résume.

    DETTE, ET SON DÉCLENCHEUR — la branche `--verify-official-downloads` de
    `resolve_currentness_network_audit` PRODUIT des lignes de vérification par
    document. Elle n'a pas été empruntée, la source étant injoignable. La première
    émission qui l'empruntera portera des tentatives structurées, et ce champ
    n'aura plus lieu d'être.
    """
    rapports = (
        (
            "docs/reports/gate_currentness_audit_20260829.md",
            "Éduscol répond 403 à toute requête programmée — vérifié sur une URL du "
            "corpus, et constaté aussi avec un User-Agent de navigateur. Le "
            "catalogue de provenance porte l'URL de LISTING, jamais celle de "
            "téléchargement direct.",
        ),
        (
            "docs/reports/lecture_par_agents_20260829.md",
            "Les 24 pages de listing du corpus répondent HTTP 403 Forbidden à une "
            "requête programmée. Aucun document acquis, aucun scellé.",
        ),
        (
            "docs/reports/justification_trois_extensions_20260829.md",
            "education.gouv.fr ET eduscol.education.gouv.fr rendent 403 depuis la "
            "machine de production des releases — le blocage porte sur deux "
            "domaines, non sur un chemin isolé.",
        ),
    )
    sortie: list[dict[str, str]] = []
    for relatif, etablit in rapports:
        chemin = REPOSITORY_ROOT / relatif
        if not chemin.is_file():
            raise FileNotFoundError(
                f"preuve de fraîcheur hors bande introuvable : {relatif}"
            )
        sortie.append(
            {"path": relatif, "sha256": _file_sha256(chemin), "establishes": etablit}
        )
    return sortie


def resolve_currentness_network_audit(
    placement_rows: list[dict[str, Any]],
    *,
    verify_official_downloads: bool,
    audit_path: Path = CURRENTNESS_NETWORK_AUDIT_PATH,
    release_id: str | None = None,
    source_unreachable: bool | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Separate optional live acquisition from deterministic offline replay.

    ``source_unreachable`` déclare explicitement la lacune nommée ; à défaut,
    elle se lit dans ``NEXUS_CURRENTNESS_UNVERIFIED``. La répétition la déduit
    de l'audit de sa release source, sans variable d'environnement."""
    if verify_official_downloads:
        network_rows = _verify_official_downloads(placement_rows)
        return (
            _currentness_network_audit_document(network_rows, placement_rows=placement_rows),
            network_rows,
        )

    # LACUNE NOMMÉE ET BORNÉE — décision opérateur du 29/08/2026.
    #
    # Une release ne peut attester que ce qu'elle a vérifié : l'empreinte du
    # contenu et sa date d'acquisition. Pas sa fraîcheur à la source, si la
    # source est injoignable.
    #
    # Le blocage est de CHEMIN, non de source : un fichier direct
    # (`/sites/default/files/document/…pdf`) répond 200, une page de listing
    # (`/5718/ressources-…`) répond 403 — protection anti-robot du CMS. Or les
    # URL de fichier direct n'existent dans aucune preuve en notre possession :
    # ni le catalogue de provenance, ni les registres de contenu et de
    # placement, ni le snapshot Drive. Les découvrir exigerait les pages de
    # listing, qui sont précisément ce qui refuse.
    #
    # On NOMME le trou, on ne le comble pas d'une affirmation. C'est le
    # précédent COVERAGE_GAP, appliqué à la fraîcheur. Cette lacune est bornée :
    # elle ne relâche AUCUN autre contrôle — empreintes, scellement, unicité,
    # gate de revue restent exercés à l'identique.
    # La déclaration prime sur la lecture : l'audit scellé du dépôt couvre un
    # AUTRE périmètre — les 26 documents de la release historique. Le confronter
    # à une émission de 2 389 documents ne mesurerait rien.
    if source_unreachable is None:
        source_unreachable = (
            os.environ.get("NEXUS_CURRENTNESS_UNVERIFIED") == "SOURCE_UNREACHABLE"
        )
    if source_unreachable:
        return {
            "audit_kind": "PRODUCTION_PROFILE_GATE_CURRENTNESS_AUDIT_V1",
            **_corpus_binding(placement_rows),
            "network_mode": "UNVERIFIED",
            "currentness_status": "CURRENTNESS_UNVERIFIED_SOURCE_UNREACHABLE",
            "reason": (
                "eduscol.education.gouv.fr répond 403 aux pages de listing "
                "(protection anti-robot) ; les URL de fichier direct, seules "
                "joignables, ne figurent dans aucune preuve du corpus"
            ),
            "corpus_harvested_at": "2026-08-04/2026-08-05",
            "corpus_sealed_at": "2026-08-08",
            "verified_at": None,
            "artifacts": [],
            # CE QUI A RÉELLEMENT EU LIEU — et rien de plus.
            #
            # Cette branche ne fait AUCUNE requête réseau : c'est le rejeu hors
            # ligne. Elle ne peut donc consigner aucune tentative, et le déclare.
            # Le verdict repose sur une enquête menée HORS de ce producteur, dont
            # les rapports sont nommés et scellés par leur empreinte : ils sont
            # vérifiables, eux.
            "attempts": [],
            "attempts_made_by_this_producer": False,
            "out_of_band_evidence": _out_of_band_currentness_evidence(),
            # La portée du verdict est DÉRIVÉE de la release, jamais recomptée
            # ici : « s'applique aux documents de cette release ».
            "verdict_scope": {
                "kind": "RELEASE_WIDE",
                # La portée nomme LA release qui embarque ce verdict, pas la
                # constante historique du module. Une candidate qui hériterait
                # de l'identifiant d'une autre release ferait lire à l'auditeur
                # — seul consommateur déclaré de ce champ — une portée qui
                # n'est pas la sienne.
                "release_id": require_governed_release_id(
                    release_id, allow_historical=True
                ),
                "school_year": SCHOOL_YEAR,
                # Un champ scellé que rien ne lit à l'exécution a exactement un
                # consommateur : l'humain qui vérifie une release et ne peut pas
                # la recompter à la main. Sans ce champ, il ignore si le verdict
                # d'invérifiabilité porte sur quelques documents ou sur toute la
                # livraison — et c'est la première question qu'il se posera.
                # Le consommateur est donc DÉCLARÉ, plutôt que laissé implicite.
                "consumer": "auditeur humain ; aucun consommateur machine",
            },
            # `verified` et `digest_mismatch` valent 0 et s'accordent à une charge
            # utile vide : zéro tentative, zéro vérification, zéro divergence.
            #
            # `unverified_source_unreachable: len(placement_rows)` est RETIRÉ. Il
            # valait 486 pour une charge utile de 0 entrée — un compte sans sujet.
            # Son nom promettait N déterminations individuelles que personne n'a
            # faites ; le peupler de 319 entrées fabriquerait la preuve qu'il
            # prétendait résumer, ce qui est la seule façon de rendre un artefact
            # de preuve pire qu'un artefact vide. Aucun lecteur ne s'en servait.
            "counts": {"verified": 0, "digest_mismatch": 0},
            "write_operations": 0,
        }, []
    if not audit_path.is_file():
        raise ValueError("sealed currentness audit is missing")
    network_audit = _load_json(audit_path)
    expected_rows = _expected_currentness_network_rows(placement_rows)
    expected_audit = _currentness_network_audit_document(
        expected_rows, placement_rows=placement_rows
    )
    if network_audit != expected_audit:
        raise ValueError("sealed currentness audit differs from release inputs")
    return network_audit, expected_rows


CURRENTNESS_EVIDENCE_KIND_V3 = "MULTILEVEL_ARTIFACT_CURRENTNESS_V3"
UNVERIFIED_CURRENTNESS_STATUS = "CURRENTNESS_UNVERIFIED_SOURCE_UNREACHABLE"
#: Verdict de la matrice qui, seul, admet un contenu dans une release.
SERVABLE_MATRIX_VERDICT = "CANDIDATE_NO_BLOCKING_DIMENSION"
#: Hôtes institutionnels admis pour une URL de provenance d'instantané
#: (annexe ADR-0059) et pour les URL d'une vérification (règles V2).
SNAPSHOT_PROVENANCE_HOSTS = frozenset({"eduscol.education.gouv.fr", "www.education.gouv.fr"})
VERIFIED_LISTING_HOSTS = frozenset({"eduscol.education.gouv.fr"})
VERIFIED_DOWNLOAD_HOSTS = SNAPSHOT_PROVENANCE_HOSTS
_VERIFICATION_FACTS = (
    "effective_currentness",
    "current_source_listing_url",
    "current_download_url",
    "current_download_sha256",
    "byte_identity",
)


def _host(url: object) -> str | None:
    from urllib.parse import urlparse

    return urlparse(url).hostname if isinstance(url, str) else None


def _require_v3_entry_admissible(entry: Mapping[str, Any], *, audit_unverified: bool) -> None:
    """Applique à l'entrée émise les règles du chargeur V3 (annexe ADR-0059).

    Le producteur refuse ce que le chargeur refuserait : une release qui ne se
    charge pas n'est découverte qu'au moment de la servir."""
    sha = entry["content_sha256"]
    disposition = entry["currentness_disposition"]
    status = entry["source_status"]
    facts = [entry[name] for name in _VERIFICATION_FACTS]
    if disposition == VERIFIED_CURRENT:
        if audit_unverified:
            raise ValueError(
                f"{sha}: VERIFIED_CURRENT under an unverified currentness audit"
            )
        if (
            entry["effective_currentness"] != "actuel"
            or entry["byte_identity"] is not True
            or entry["current_download_sha256"] != sha
            or _host(entry["current_source_listing_url"]) not in VERIFIED_LISTING_HOSTS
            or _host(entry["current_download_url"]) not in VERIFIED_DOWNLOAD_HOSTS
            or entry["current_source_listing_url"] != entry["provenance_url"]
        ):
            raise ValueError(f"{sha}: VERIFIED_CURRENT byte identity is not exact")
        if entry["fallback_conditions"] is not None:
            raise ValueError(f"{sha}: VERIFIED_CURRENT carries fallback conditions")
        return
    if any(fact is not None for fact in facts):
        raise ValueError(f"{sha}: {disposition} carries a network verification fact")
    if disposition == OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE:
        conditions = entry["fallback_conditions"]
        if (
            not isinstance(conditions, Mapping)
            or set(conditions) != set(conditions_de_repli({}))
            or any(value is not True for value in conditions.values())
        ):
            raise ValueError(f"{sha}: snapshot fallback conditions are not all true")
        if not isinstance(status, str) or not status or STATUT_ARCHIVE in status:
            raise ValueError(f"{sha}: an archived source status is never a snapshot")
        if _host(entry["provenance_url"]) not in SNAPSHOT_PROVENANCE_HOSTS:
            raise ValueError(
                f"{sha}: snapshot provenance URL is not institutional: "
                f"{entry['provenance_url']!r}"
            )
        return
    if entry["fallback_conditions"] is not None:
        raise ValueError(f"{sha}: {disposition} carries fallback conditions")
    if disposition == NOT_CURRENT_DECLARED_BY_SOURCE and STATUT_ARCHIVE not in str(status):
        raise ValueError(f"{sha}: NOT_CURRENT_DECLARED_BY_SOURCE without an archive status")


def _inventory_content_facts(inventory: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Regroupe les placements de l'inventaire PAR CONTENU.

    L'inventaire est la vérité que le chargeur confronte à la preuve : chemin,
    collections, faits de placement et URL de provenance en sont tirés, jamais
    d'une autre source qui pourrait diverger."""
    by_sha: dict[str, dict[str, Any]] = {}
    for collection in inventory["collections"]:
        for candidate in collection["candidates"]:
            sha = candidate["content_sha256"]
            facts = by_sha.setdefault(
                sha,
                {
                    "exact_path": candidate["physical_path"],
                    "collections": set(),
                    "placement_facts": [],
                    "source_urls": set(),
                },
            )
            if facts["exact_path"] != candidate["physical_path"]:
                raise ValueError(f"inventory physical path differs for {sha}")
            for placement in candidate["placements"]:
                facts["collections"].add(collection["collection"])
                facts["source_urls"].add(placement["source_url"])
                facts["placement_facts"].append(
                    {
                        "collection": collection["collection"],
                        "source_placement_id": placement["source_placement_id"],
                        "external_level": placement["external_level"],
                        "external_subject": placement["external_subject"],
                        "external_scope": placement["external_scope"],
                        "external_document_type": placement["external_document_type"],
                    }
                )
    return by_sha


def _currentness_documents(
    placement_rows: list[dict[str, Any]],
    *,
    inventory: Mapping[str, Any],
    inventory_sha256: str,
    network_audit: dict[str, Any],
    authority: GovernedCurrentnessAuthority,
    exclusion_registry: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Émet MULTILEVEL_ARTIFACT_CURRENTNESS_V3 (ADR-0059), une entrée par contenu.

    La disposition n'est PAS décidée ici. Elle vient de la matrice de
    servabilité gouvernée ; le producteur la recalcule depuis les faits que la
    matrice a utilisés (`cas_depuis_ligne_de_matrice`, la même dérivation) et
    refuse tout désaccord. Le seul fait qu'il ajoute est celui de l'audit
    réseau scellé : une identité d'octets, que la politique elle-même convertit
    en VERIFIED_CURRENT. Un audit qui se déclare non vérifié n'en fournit
    aucune — et s'il en porte, il se contredit : refus.
    """
    network_rows = network_audit["artifacts"]
    audit_sha = _sha256_bytes(canonical_json_bytes(network_audit))
    audit_unverified = (
        network_audit.get("currentness_status") == UNVERIFIED_CURRENTNESS_STATUS
    )
    if audit_unverified and network_rows:
        raise ValueError(
            "an unverified currentness audit carries verification rows — it "
            "contradicts itself, and no content can be declared verified from it"
        )
    by_sha_network = {row["content_sha256"]: row for row in network_rows}
    grouped = _group_artifact_rows(placement_rows)
    inventory_facts = _inventory_content_facts(inventory)
    if set(inventory_facts) != set(grouped):
        raise ValueError("currentness population differs from the candidate inventory")
    excluded = (
        frozenset(exclusion_registry.excluded_contents)
        if exclusion_registry is not None
        else frozenset()
    )

    artifacts = []
    partition: dict[str, list[str]] = {name: [] for name in sorted(DISPOSITIONS)}
    for sha in sorted(grouped):
        if sha in excluded:
            raise ValueError(
                f"{sha} is listed in the ADR-0055 exclusion registry and must not "
                "be in the release at all"
            )
        row = grouped[sha]["artifact_row"]
        facts = inventory_facts[sha]
        matrix_row = authority.rows_by_sha.get(sha)
        if matrix_row is None:
            raise ValueError(f"{sha} is absent from the servability matrix")
        if matrix_row.get("verdict") != SERVABLE_MATRIX_VERDICT:
            raise ValueError(
                f"{sha} is not servable per the servability matrix "
                f"(verdict {matrix_row.get('verdict')!r}); a content the governed "
                "matrix blocks enters a release only by being excluded from it "
                "(ADR-0055 exclusion registry)"
            )
        cas = cas_depuis_ligne_de_matrice(matrix_row)
        recomputed = disposition_actualite(cas, authority.policy)
        if recomputed != matrix_row.get("currentness_disposition"):
            raise ValueError(
                f"{sha}: the servability matrix disposition "
                f"{matrix_row.get('currentness_disposition')!r} disagrees with the "
                f"applied policy on the matrix's own facts ({recomputed!r})"
            )
        if len(facts["source_urls"]) != 1:
            raise ValueError(
                f"{sha}: placements carry divergent provenance URLs "
                f"{sorted(facts['source_urls'])}"
            )
        (provenance_url,) = facts["source_urls"]

        network = by_sha_network.get(sha)
        if network is not None:
            if network.get("byte_identity") is not True or network.get(
                "downloaded_sha256"
            ) != sha:
                raise ValueError(f"{sha}: sealed audit row does not prove byte identity")
            cas = {**cas, "content_identity_match": True}
        disposition = disposition_actualite(cas, authority.policy)

        verified = disposition == VERIFIED_CURRENT
        snapshot = disposition == OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE
        if verified:
            assert network is not None
            reason_codes = ["OFFICIAL_CURRENT_BYTE_IDENTITY_EXACT"]
        elif snapshot:
            reason_codes = ["OFFICIAL_SNAPSHOT_FALLBACK_CONDITIONS_MET"]
            if audit_unverified:
                reason_codes.insert(0, "CURRENT_SOURCE_UNREACHABLE_NOT_AUDITED")
        else:
            reason_codes = [f"{disposition}_BY_POLICY"]
        entry = {
            "content_sha256": sha,
            "exact_path": facts["exact_path"],
            "collections": sorted(facts["collections"]),
            "placement_facts": sorted(
                facts["placement_facts"],
                key=lambda fact: (fact["collection"], fact["source_placement_id"]),
            ),
            "current_for_school_year": SCHOOL_YEAR,
            "currentness_disposition": disposition,
            # Verbatim : la matrice est l'autorité de ce statut, la preuve le cite.
            "source_status": matrix_row["currentness"],
            "provenance_url": provenance_url,
            "fallback_conditions": conditions_de_repli(cas) if snapshot else None,
            # Faits de vérification réseau : exigés pour VERIFIED_CURRENT, null
            # pour toute autre disposition. Un instantané n'a été téléchargé par
            # personne ; lui prêter une URL de téléchargement serait le
            # contrefaire.
            "effective_currentness": "actuel" if verified else None,
            "current_source_listing_url": (
                network["current_source_listing_url"] if verified and network else None
            ),
            "current_download_url": (
                network["current_download_url"] if verified and network else None
            ),
            "current_download_sha256": sha if verified else None,
            "byte_identity": True if verified else None,
            "reason_codes": reason_codes,
            # `drive_file_id` reste hors de la preuve (poignée d'écriture Drive).
            "drive_modified_time": row["drive_modified_time"],
        }
        _require_v3_entry_admissible(entry, audit_unverified=audit_unverified)
        artifacts.append(entry)
        partition[disposition].append(sha)

    decision_basis = (
        "Official source unreachable; no network currentness fact measured. "
        f"Dispositions derived from the governed servability matrix under {POLICY_ID}"
        if audit_unverified
        else "Byte identity from the sealed read-only audit where proven; other "
        f"dispositions derived from the governed servability matrix under {POLICY_ID}"
    )
    evidence = {
        "evidence_kind": CURRENTNESS_EVIDENCE_KIND_V3,
        "school_year": SCHOOL_YEAR,
        "candidate_inventory_sha256": inventory_sha256,
        "corpus_manifest_sha256": inventory["corpus_manifest_sha256"],
        "sealed_catalog_sha256": inventory["sealed_catalog_sha256"],
        "placement_catalog_sha256": inventory["placement_catalog_sha256"],
        "catalog_delta_sha256": inventory["catalog_delta_sha256"],
        "effective_catalog_authority_sha256": inventory[
            "effective_catalog_authority_sha256"
        ],
        "currentness_audit_sha256": audit_sha,
        "decision_basis": decision_basis,
        "currentness_policy_id": authority.policy_id,
        "currentness_policy_sha256": authority.policy_sha256,
        "servability_matrix_sha256": authority.matrix_sha256,
        "counts": {
            "unique_artifacts": len(artifacts),
            "evaluated": len(artifacts),
            **{name: len(partition[name]) for name in sorted(DISPOSITIONS)},
        },
        "partition": partition,
        "artifacts": artifacts,
    }
    return network_audit, evidence


class ServedCurrentness(NamedTuple):
    """Ce que le catalogue scellé dit d'un contenu : sa valeur produit, et
    l'URL qu'il cite. Dérivé de la preuve V3, jamais écrit en dur."""

    currentness: str
    source_url: str


#: ADR-0059 §2 : correspondance disposition → valeur produit. Les deux autres
#: dispositions ne sont jamais publiées.
PRODUCT_CURRENTNESS_BY_DISPOSITION = {
    VERIFIED_CURRENT: "current",
    OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE: "official_snapshot",
}
PRODUCT_CURRENTNESS_VALUES = frozenset(PRODUCT_CURRENTNESS_BY_DISPOSITION.values())


def served_currentness_from_evidence(
    evidence: Mapping[str, Any],
) -> dict[str, ServedCurrentness]:
    """Dérive, par contenu, l'actualité produit et l'URL citée.

    On cite le téléchargement pour une identité d'octets prouvée, la
    provenance pour un instantané : on ne cite pas un téléchargement qui n'a
    pas eu lieu."""
    if evidence.get("evidence_kind") != CURRENTNESS_EVIDENCE_KIND_V3:
        raise ValueError(
            "served currentness derives only from MULTILEVEL_ARTIFACT_CURRENTNESS_V3"
        )
    served: dict[str, ServedCurrentness] = {}
    for entry in evidence["artifacts"]:
        sha = entry["content_sha256"]
        disposition = entry["currentness_disposition"]
        product = PRODUCT_CURRENTNESS_BY_DISPOSITION.get(disposition)
        if product is None:
            raise ValueError(
                f"{sha}: disposition {disposition!r} never reaches the catalogue"
            )
        url = (
            entry["current_download_url"]
            if disposition == VERIFIED_CURRENT
            else entry["provenance_url"]
        )
        served[sha] = ServedCurrentness(product, url)
    return served


_INTRINSIC_ARTIFACT_ROW_FIELDS = (
    "physical_path",
    "drive_file_id",
    "drive_modified_time",
    "drive_size",
    "source_url",
    "current_download_url",
    "title",
    "external_document_type",
    "year",
    "source_evidence",
)


def _group_artifact_rows(
    placement_rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Regrouper les placements sans choisir arbitrairement des faits documentaires."""
    rows_by_sha: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in placement_rows:
        rows_by_sha[str(row["content_sha256"])].append(row)

    grouped: dict[str, dict[str, Any]] = {}
    for sha in sorted(rows_by_sha):
        rows = sorted(
            rows_by_sha[sha],
            key=lambda row: (
                str(row.get("collection", "")),
                str(row.get("source_placement_id", "")),
                str(row.get("external_scope", "")),
            ),
        )
        reference = rows[0]
        for field in _INTRINSIC_ARTIFACT_ROW_FIELDS:
            expected = (field in reference, reference.get(field))
            if any((field in row, row.get(field)) != expected for row in rows[1:]):
                raise ValueError(
                    f"intrinsic artifact field {field} differs for {sha}"
                )
        grouped[sha] = {
            "artifact_row": reference,
            "placement_rows": rows,
        }
    return grouped


def _corpus_descriptor(placement_rows: list[dict[str, Any]]) -> dict[str, Any]:
    unique_shas = sorted(_group_artifact_rows(placement_rows))
    return {
        "authority_kind": "SEALED_CORPUS_MANIFEST_REFERENCE_V1",
        "authority_sha256": CORPUS_MANIFEST_AUTHORITY,
        "content_ledger_path": _repo_relative(CONTENT_LEDGER_PATH),
        "content_ledger_sha256": _file_sha256(CONTENT_LEDGER_PATH),
        "final_content_count": len(unique_shas),
        "final_content_set_sha256": _final_set_digest(unique_shas),
    }


class ReviewAuthorityInputs(NamedTuple):
    """Les quatre entrées qui portent la décision humaine, toutes injectées.

    Aucune n'est dérivée d'un chemin en dur : faire tourner une autre campagne
    de revue ne doit toucher aucune ligne de ce producteur."""

    decision_set_path: Path | None
    receipt_path: Path | None
    trust_anchor_path: Path | None
    review_index_path: Path | None
    reviewers: tuple[str, ...]
    environment: str = "production"

    @property
    def declared(self) -> bool:
        return self.decision_set_path is not None


#: « Aucune autorité de revue fournie ». Ce n'est pas une permission : toute
#: détection rencontrée sans décision scellée est alors refusée. Le défaut
#: existe pour qu'un appelant qui n'a rien à projeter n'ait pas à fabriquer
#: une autorité vide, jamais pour rendre la revue facultative.
NO_REVIEW_AUTHORITY = ReviewAuthorityInputs(None, None, None, None, ())


def _load_review_authority(
    inputs: ReviewAuthorityInputs,
) -> tuple[dict[str, Any] | None, dict[str, str], dict[str, str]]:
    """Vérifie la chaîne d'autorité et rend (décisions, paquets, empreintes).

    Les paquets viennent de l'INDEX, jamais de la décision elle-même :
    confronter une décision à sa propre revendication de paquet ne prouverait
    rien. Les empreintes rendues rejoignent la chaîne d'autorité de la release
    (§7) — celle du NOUVEAU candidat, jamais d'une release historique."""
    if not inputs.declared:
        return None, {}, {}

    assert inputs.decision_set_path is not None
    for label, path in (
        ("decision set", inputs.decision_set_path),
        ("review receipt", inputs.receipt_path),
        ("trust anchor", inputs.trust_anchor_path),
        ("review index", inputs.review_index_path),
    ):
        if path is None or not path.is_file():
            raise ValueError(
                f"the PII {label} is required to project a human review and is absent"
            )
    assert inputs.receipt_path and inputs.trust_anchor_path and inputs.review_index_path

    raw_decision_set = inputs.decision_set_path.read_bytes()
    raw_receipt = inputs.receipt_path.read_bytes()
    anchor_bytes = inputs.trust_anchor_path.read_bytes()
    try:
        anchor = TrustAnchor.model_validate(json.loads(anchor_bytes.decode("utf-8")))
    except Exception as exc:  # noqa: BLE001 - frontière de parsing
        raise ValueError(f"the review trust anchor is not usable: {exc}") from exc

    try:
        decision_set, _binding = verify_pii_review_decision_authority(
            decision_set_bytes=raw_decision_set,
            receipt_bytes=raw_receipt,
            trust_anchor=anchor,
            environment=inputs.environment,  # type: ignore[arg-type]
            expected_repository=CANONICAL_REPOSITORY,
            accepted_reviewers=inputs.reviewers or None,
            now=datetime.now(UTC),
        )
    except ReviewBindingError as exc:
        raise ValueError(f"the PII review authority is refused: {exc}") from exc

    index = json.loads(inputs.review_index_path.read_text(encoding="utf-8"))
    bundles = {
        str(entry["content_sha256"]): str(entry["bundle_sha256"])
        for entry in index.get("bundles", [])
    }
    # Inconditionnel. La comparaison était sautée si l'index déclarait
    # `review_index_sha256_declared` — une clé qui vit DANS le fichier vérifié.
    # Quiconque fournissait l'index pouvait donc la poser et éteindre le seul
    # contrôle qui le lie à la campagne scellée. Un champ ne décide jamais s'il
    # est lui-même vérifié.
    indexed_digest = _sha256_bytes(inputs.review_index_path.read_bytes())
    if indexed_digest != decision_set.review_index_sha256:
        raise ValueError(
            "the decision set was sealed against review index "
            f"{decision_set.review_index_sha256[:16]}… while the supplied review index "
            f"hashes to {indexed_digest[:16]}… — they are not the same campaign"
        )

    # L'ensemble de contenus que la revue a RÉELLEMENT couvert. C'est le seul
    # champ de toute la chaîne qui désigne la matière revue plutôt qu'un
    # document ; sans lui, on prouve que les autorités sont intactes sans
    # jamais prouver qu'elles parlent de la candidate.
    reviewed_content_set = index.get("content_set_sha256")
    if not isinstance(reviewed_content_set, str) or not _HEX64.match(reviewed_content_set):
        raise ValueError(
            "the review index declares no usable content_set_sha256 — the review "
            "cannot be bound to any corpus"
        )

    digests = {
        "pii_decision_set_sha256": _sha256_bytes(raw_decision_set),
        "pii_review_receipt_sha256": _sha256_bytes(raw_receipt),
        "pii_review_trust_anchor_sha256": _sha256_bytes(anchor_bytes),
        "pii_review_index_sha256": _sha256_bytes(inputs.review_index_path.read_bytes()),
        "reviewed_content_set_sha256": reviewed_content_set,
    }
    return json.loads(raw_decision_set.decode("utf-8")), bundles, digests


#: Statuts qui rendraient une release promouvable ou activable. Une candidate
#: n'a jamais le droit de les porter : le gate PII n'est qu'un des gates de
#: go-live, et C1-C6 restent ouverts tant qu'ils ne sont pas prouvés.
_ACTIVATING_PROMOTION = "PROMOTABLE"
_ACTIVATING_ACTIVATION = "PRODUCTION_ACTIVATION_ALLOWED"


#: Les seuls modes de release que le producteur sait traiter. Un mode absent de
#: cet ensemble est refusé, jamais rattaché par défaut au cas permissif.
_SUPPORTED_RELEASE_MODES = frozenset({"production", "rehearsal"})


def resolve_release_lifecycle_statuses(
    *,
    release_mode: str,
    release_id: str | None = None,
    promotion_status: str | None,
    activation_status: str | None,
    review_status: str | None,
) -> dict[str, str | None]:
    """Résout les statuts d'une release, et refuse une production activable.

    **Le cycle de vie ne se déduit pas du NOM.** La version précédente écrivait
    `is_candidate = release_id is not None` : une production utilisant le
    `release_id` par défaut — cas légitime, le paramètre valant `None` — était
    donc traitée comme non-candidate et transmettait des statuts activables au
    manifeste. Le nom d'une release ne dit rien de son cycle de vie.

    Le signal juste est le MODE. Une release de production n'est jamais émise
    activable : la promotion se gagne aux gates de go-live, pas par un argument
    de producteur. `release_id` n'entre pas dans la décision, et n'est présent
    ici que pour rendre cette indifférence explicite et testable.

    Une demande activante n'est pas silencieusement corrigée mais REFUSÉE : un
    appel qui la formule est un appel qui se trompe, et écraser sa demande sans
    rien dire lui laisserait croire qu'il l'a obtenue."""
    del release_id  # jamais un signal de cycle de vie — voir la docstring
    # Un mode inconnu n'est pas « pas la production » : c'est une demande qui
    # ne veut rien dire. La traiter comme un simple non-production faisait
    # passer `staging` — ou une faute de frappe — à travers la garde, en
    # conservant des statuts activables. Le refus est explicite.
    if release_mode not in _SUPPORTED_RELEASE_MODES:
        raise ValueError(
            f"release_mode={release_mode!r} is not supported — expected one of "
            f"{sorted(_SUPPORTED_RELEASE_MODES)}; an unknown mode must not inherit "
            "the lenient branch and keep activatable statuses"
        )
    if release_mode != "production":
        return {
            "promotion_status": promotion_status,
            "activation_status": activation_status,
            "review_status": review_status,
        }
    refused = []
    if promotion_status == _ACTIVATING_PROMOTION:
        refused.append(f"promotion_status={_ACTIVATING_PROMOTION}")
    if activation_status == _ACTIVATING_ACTIVATION:
        refused.append(f"activation_status={_ACTIVATING_ACTIVATION}")
    if refused:
        raise ValueError(
            f"a production release cannot be asked to be activable ({', '.join(refused)}): "
            "promotion is earned at the go-live gates, not requested from the producer"
        )
    return {
        "promotion_status": promotion_status or "NOT_PROMOTABLE",
        "activation_status": activation_status or "NO_PRODUCTION_ACTIVATION",
        "review_status": review_status,
    }


def require_review_covers_produced_content_set(
    *,
    reviewed_content_set_sha256: str | None,
    produced_content_set_sha256: str,
) -> None:
    """Le pont entre la revue humaine et la candidate.

    Toute la chaîne d'autorités prouve que des DOCUMENTS sont intacts : le
    decision set nomme un fichier d'autorité qui n'a pas bougé, un reçu signé,
    une ancre épinglée, un index dont l'empreinte est celle scellée. Aucune de
    ces vérifications ne dit sur QUELLE MATIÈRE la revue a porté.

    Le seul champ qui le dise est `content_set_sha256` de l'index de revue. Il
    était lu — pour ses paquets — sans jamais être confronté à l'ensemble que
    la candidate produit. La coïncidence était AFFIRMÉE dans un commentaire et
    vérifiée nulle part.

    Mesuré sur la campagne réelle : le fichier d'autorité que le decision set
    scelle décrit 26 contenus, la candidate en émet 320. Prouver que ce fichier
    est intact ne prouve donc rien de la candidate ; cette confrontation-ci le
    fait, et elle porte sur la matière plutôt que sur un document.

    `None` signifie qu'aucune autorité de revue n'a été fournie — cas où rien
    n'est projeté et où le registre refuse déjà toute admission non fondée."""
    if reviewed_content_set_sha256 is None:
        return
    if reviewed_content_set_sha256 != produced_content_set_sha256:
        raise ValueError(
            f"the human review covered content set "
            f"{reviewed_content_set_sha256[:16]}… while this candidate ships "
            f"{produced_content_set_sha256[:16]}… — the review does not bind the "
            "corpus this release would publish"
        )


def _pii_evidence(
    placement_rows: list[dict[str, Any]],
    *,
    pdfs: Mapping[str, VerifiedPdf],
    inventory_sha256: str,
    review_authority: ReviewAuthorityInputs = NO_REVIEW_AUTHORITY,
) -> dict[str, Any]:
    patterns = load_patterns_from_config(PII_POLICY_PATH)
    grouped = _group_artifact_rows(placement_rows)
    policy_sha = _file_sha256(PII_POLICY_PATH)
    scanner_sha = _file_sha256(PII_SCANNER_PATH)
    page_policy_sha = page_policy.policy_source_sha256()

    decision_document, review_bundles, authority_digests = _load_review_authority(
        review_authority
    )

    # ── LE SCAN MESURE, LA REVUE DÉCIDE ─────────────────────────────────
    #
    # Le scan enregistre ce qu'il trouve, sans rien exclure ni rien admettre :
    # sa précision mesurée (2 vrais positifs sur 20 correspondances tirées au
    # hasard) ne lui donne pas qualité à trancher. La raison est structurelle,
    # pas un défaut de réglage — le corpus ENSEIGNE le courriel, les en-têtes,
    # l'encodage et les formats de contact, si bien qu'un détecteur de données
    # personnelles passé sur du matériel pédagogique qui porte sur les formats
    # de données personnelles se déclenche sur la pédagogie.
    #
    # C'est donc une revue humaine, décision par décision, contenu par contenu,
    # scellée et signée, qui décide (ADR-0047). Ce producteur ne fait que
    # projeter son résultat : il n'ajoute aucun jugement, et il refuse dès que
    # son scan et cette revue ne décrivent pas le même monde.
    scanned: list[ScannedContent] = []
    for sha, group in grouped.items():
        row = group["artifact_row"]
        pdf = pdfs[sha]
        result = scan_pdf_bytes(
            pdf.content,
            source_path=str(pdf.path),
            patterns=patterns,
        )
        if result.sha256 != row["content_sha256"]:
            raise ValueError(f"PII scan digest differs for {row['content_sha256']}")
        if result.extraction_error:
            raise ValueError(
                f"PII scan could not read {row['content_sha256']} — "
                f"{result.extraction_error}"
            )
        findings: list[ScannedFinding] = []
        if result.matches:
            # Les textes de page ne sont ré-extraits que pour les contenus qui
            # portent une correspondance — 23 sur 320 — parce que le contexte
            # scellé se calcule sur le texte de page brut, et sur lui seul.
            pages_text, _ignored, page_error = (
                extract_pdf_pages_with_structural_empty_pages(pdf.content)
            )
            if page_error:
                raise ValueError(
                    f"page text extraction failed for {row['content_sha256']} — {page_error}"
                )
        for match in result.matches:
            match_sha = _sha256_bytes(match.match_text.encode("utf-8"))
            page_text = pages_text[(match.page_number or 1) - 1]
            findings.append(
                ScannedFinding(
                    # Identité et contexte viennent de l'autorité unique : ce
                    # sont eux qui rendent les findings du scan comparables à
                    # ceux que la revue humaine a dispositionnés. Le contexte
                    # de confort du scanner (50 caractères, sauts de ligne
                    # remplacés) n'est PAS celui que le paquet a figé.
                    finding_id=finding_identity(
                        content_sha256=row["content_sha256"],
                        pattern_id=match.pattern_id,
                        page_number=match.page_number,
                        char_offset=match.char_offset,
                        match_sha256=match_sha,
                    ),
                    pattern_id=match.pattern_id,
                    page=match.page_number or 1,
                    match_sha256=match_sha,
                    context_sha256=_sha256_bytes(
                        finding_context(
                            page_text,
                            char_offset=match.char_offset,
                            match_length=len(match.match_text),
                        ).encode("utf-8")
                    ),
                )
            )
        scanned.append(
            ScannedContent(
                content_sha256=row["content_sha256"],
                pages_scanned=result.pages_scanned,
                characters_scanned=result.characters_scanned,
                ignored_empty_pages=tuple(result.ignored_empty_pages),
                findings=tuple(findings),
            )
        )

    try:
        projection = project_pii_review(
            scanned,
            decision_set_document=decision_document,
            review_bundles=review_bundles,
            policy_sha256=policy_sha,
            scanner_sha256=scanner_sha,
            page_policy_sha256=page_policy_sha,
            # L'empreinte du FICHIER, jamais la valeur qu'il déclare : c'est
            # celle que l'ensemble de décisions humaines a enregistrée.
            corpus_manifest_sha256=corpus_manifest_authority_file_sha256(),
        )
    except PiiProjectionError as exc:
        raise ValueError(f"the PII review cannot be projected on this scan: {exc}") from exc

    # ── LE PONT ENTRE LA REVUE HUMAINE ET LA CANDIDATE ────────────────────
    #
    # Tout ce qui précède prouve que les AUTORITÉS sont intactes : le decision
    # set nomme un fichier d'autorité qui n'a pas bougé, un reçu signé, une
    # ancre épinglée, un index dont l'empreinte est celle scellée. Aucune de
    # ces vérifications ne dit sur QUELLE MATIÈRE la revue a porté.
    #
    # Le seul champ qui le dise est `content_set_sha256` de l'index. Il était
    # lu — pour ses paquets — sans jamais être confronté à l'ensemble que la
    # candidate produit. La coïncidence était AFFIRMÉE dans un commentaire de
    # `CANONICAL_CONTENT_SET_SHA256` et vérifiée nulle part.
    #
    # Mesuré : le fichier d'autorité que le decision set scelle décrit 26
    # contenus, la candidate en émet 320. Prouver que ce fichier est intact ne
    # prouve donc RIEN de la candidate. C'est cette confrontation-ci qui le
    # fait, et elle porte sur la matière, pas sur un document.
    require_review_covers_produced_content_set(
        reviewed_content_set_sha256=authority_digests.get("reviewed_content_set_sha256"),
        produced_content_set_sha256=_final_set_digest(sorted(grouped)),
    )

    source_by_sha = {
        group["artifact_row"]["content_sha256"]: group["artifact_row"]["physical_path"]
        for group in grouped.values()
    }
    results = [
        {
            **entry,
            "evidence_sha256": _sha256_bytes(_compact_json_bytes(entry)),
            "source_path": source_by_sha[entry["content_sha256"]],
        }
        for entry in projection.entries
    ]

    # `raw_pii_in_output: false`, plus bas, était une CONSTANTE : le producteur
    # certifiait que sa preuve ne porte aucune matière brute sans l'avoir
    # regardée. La mesure a lieu ici, sur les résultats réellement produits, et
    # avant l'attestation qui en dépend. Un finding est un refus.
    require_no_raw_pii({"results": results}, label="pii_evidence.results", patterns=patterns)

    return {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "school_year": SCHOOL_YEAR,
        "candidate_inventory_sha256": inventory_sha256,
        "corpus_manifest_sha256": CORPUS_MANIFEST_AUTHORITY,
        "policy_version": "pii_gate_policy_h2b_v5",
        "policy_sha256": _file_sha256(PII_POLICY_PATH),
        "scanner_version": "production-profile-gate-v1",
        "scanner_sha256": _file_sha256(PII_SCANNER_PATH),
        "page_policy_id": page_policy.POLICY_ID,
        "page_policy_sha256": page_policy.policy_source_sha256(),
        "required_pdf_path_count": len(grouped),
        "remote_access_mode": "READ_ONLY",
        "remote_write_operations": 0,
        "raw_pii_in_output": False,
        "raw_pii_in_logs": False,
        "decision_set_id": projection.decision_set_id,
        **authority_digests,
        "summary": {
            "unique_contents_required": len(grouped),
            "unique_contents_scanned": len(grouped),
            "pii_scan_coverage": 1.0,
            "unique_contents_not_scanned": 0,
            "sha256_mismatches": 0,
            # Sept dimensions distinctes, toutes DÉRIVÉES des ensembles. Les
            # fondre en « combien sont propres » rendrait invisible la
            # différence entre « rien trouvé » et « trouvé, examiné, admis ».
            **projection.counts,
        },
        "results": results,
    }


def _preflight(
    placement_rows: list[dict[str, Any]],
    *,
    pdfs: Mapping[str, VerifiedPdf],
    token_counter: CanonicalTokenCounter,
    pii_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    require_canonical_token_counter(token_counter)
    artifacts = []
    chunks_total = 0
    grouped = _group_artifact_rows(placement_rows)
    if set(pdfs) != set(grouped):
        raise ValueError("verified PDF SHA population differs from preflight")
    raw_pii_results = pii_evidence.get("results")
    if not isinstance(raw_pii_results, list):
        raise ValueError("PII evidence results must be a list")
    pii_by_sha: dict[str, tuple[int, ...]] = {}
    for evidence_row in raw_pii_results:
        if not isinstance(evidence_row, dict):
            raise ValueError("PII evidence result must be an object")
        evidence_sha = evidence_row.get("content_sha256")
        if not isinstance(evidence_sha, str) or evidence_sha in pii_by_sha:
            raise ValueError("PII evidence SHA population is not unique")
        raw_ignored = evidence_row.get("ignored_empty_pages")
        if not isinstance(raw_ignored, list) or any(
            type(page) is not int for page in raw_ignored
        ):
            raise ValueError("PII ignored_empty_pages must contain strict integers")
        ignored = tuple(raw_ignored)
        if ignored != tuple(sorted(set(ignored))):
            raise ValueError("PII ignored_empty_pages must be strictly increasing")
        pii_by_sha[evidence_sha] = ignored
    if set(pii_by_sha) != set(grouped):
        raise ValueError("PII evidence SHA population differs from preflight")

    for sha, group in grouped.items():
        row = group["artifact_row"]
        content = pdfs[sha].content
        if _sha256_bytes(content) != sha:
            raise ValueError(f"verified PDF digest differs for {sha}")
        pages_text, authoritative_ignored, extraction_error = (
            extract_pdf_pages_with_structural_empty_pages(content)
        )
        if extraction_error:
            raise ValueError(
                f"preflight extraction failed for {sha} — {extraction_error}"
            )
        page_count = len(pages_text)
        declared_ignored = pii_by_sha[sha]
        if any(page < 1 or page > page_count for page in declared_ignored):
            raise ValueError(f"PII ignored_empty_pages is out of bounds for {sha}")
        if declared_ignored != authoritative_ignored:
            raise ValueError(
                f"PII ignored_empty_pages differs from authoritative extraction "
                f"for {sha}"
            )
        chunks = chunk_publication(
            content=content,
            mime_detected="application/pdf",
            extracted_text="",
            token_counter=token_counter,
            target_tokens=TARGET_TOKENS,
        )
        chunk_rows = []
        for index, chunk in enumerate(chunks):
            token_count = token_counter.passage_token_count(chunk.text)
            if token_count > TARGET_TOKENS:
                raise ValueError("publication chunk exceeds E5 target budget")
            chunk_sha = _sha256_bytes(chunk.text.encode("utf-8"))
            chunk_id = _sha256_bytes(
                f"{row['content_sha256']}:{index}:{chunk_sha}".encode()
            )
            chunk_rows.append(
                {
                    "chunk_index": index,
                    "chunk_id": chunk_id,
                    "chunk_sha256": chunk_sha,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "token_count": token_count,
                    "character_count": len(chunk.text),
                }
            )
        covered_pages = {
            page
            for chunk in chunk_rows
            for page in range(chunk["page_start"], chunk["page_end"] + 1)
        }
        ignored_pages = set(authoritative_ignored)
        expected_pages = set(range(1, page_count + 1))
        overlap = covered_pages & ignored_pages
        if overlap:
            raise ValueError(
                f"covered/ignored page overlap for {sha}: {sorted(overlap)}"
            )
        out_of_bounds = (covered_pages | ignored_pages) - expected_pages
        if out_of_bounds:
            raise ValueError(
                f"page partition is out of bounds for {sha}: {sorted(out_of_bounds)}"
            )
        unexplained = expected_pages - covered_pages - ignored_pages
        if unexplained:
            raise ValueError(
                f"page partition has uncovered pages for {sha}: "
                f"{sorted(unexplained)}"
            )
        chunks_total += len(chunk_rows)
        artifacts.append(
            {
                "content_sha256": row["content_sha256"],
                "source_path": row["physical_path"],
                "page_count": page_count,
                "ignored_empty_pages": list(authoritative_ignored),
                "chunks": chunk_rows,
            }
        )
    return {
        "evidence_kind": "PRODUCTION_PROFILE_GATE_PREFLIGHT_V1",
        "school_year": SCHOOL_YEAR,
        "model_id": token_counter.model_id,
        "model_revision": token_counter.model_revision,
        "target_tokens": TARGET_TOKENS,
        "counts": {
            "unique_artifacts": len(artifacts),
            "pages": sum(row["page_count"] for row in artifacts),
            "chunks": chunks_total,
            "empty_pages": sum(
                len(row["ignored_empty_pages"]) for row in artifacts
            ),
            "empty_chunks": 0,
            "oversized_chunks": 0,
        },
        "artifacts": artifacts,
    }


def _review_chain_authority_paths(
    review_authority: ReviewAuthorityInputs | None,
) -> dict[str, Path]:
    """ADR-0047 §7 : les quatre fichiers de la décision humaine rejoignent la
    chaîne d'autorité du candidat qui la projette — ensemble ou pas du tout."""
    if review_authority is None or not review_authority.declared:
        return {}
    paths = {
        "pii_decision_set_sha256": review_authority.decision_set_path,
        "pii_review_receipt_sha256": review_authority.receipt_path,
        "pii_review_trust_anchor_sha256": review_authority.trust_anchor_path,
        "pii_review_index_sha256": review_authority.review_index_path,
    }
    return {name: path for name, path in paths.items() if path is not None}


def _rehearsal_pii_evidence(
    placement_rows: list[dict[str, Any]],
    *,
    pdf_root: Path,
    inventory_sha256: str,
    review_authority: ReviewAuthorityInputs,
    preflight_by_sha: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Réémet la preuve PII d'une répétition avec la fonction de production.

    Le scan porte sur la population CONSERVÉE, un contenu une fois, avec le
    scanner courant et l'autorité de revue injectée. Les chunks, eux, ne sont
    pas recalculés : la découpe de la release source est conservée, et la seule
    dépendance de la découpe envers la PII — les pages vides écartées — est
    confrontée ici, contenu par contenu. Une divergence refuse plutôt que de
    choisir laquelle des deux mesures croire."""
    grouped = _group_artifact_rows(placement_rows)
    pdfs = validate_pdf_mirror(
        pdf_root=pdf_root,
        content_sha256=sorted(grouped),
        physical_paths={
            sha: str(group["artifact_row"]["physical_path"])
            for sha, group in grouped.items()
        },
    )
    evidence = _pii_evidence(
        placement_rows,
        pdfs=pdfs,
        inventory_sha256=inventory_sha256,
        review_authority=review_authority,
    )
    for row in evidence["results"]:
        sha = row["content_sha256"]
        preflight = preflight_by_sha.get(sha)
        if preflight is None:
            raise ValueError(f"source preflight is absent for {sha}")
        if list(preflight.get("ignored_empty_pages") or []) != list(
            row["ignored_empty_pages"]
        ):
            raise ValueError(
                f"source chunks ignored_empty_pages differ from the current PII "
                f"extraction for {sha} — the kept chunking no longer describes "
                "these bytes"
            )
    return evidence


def require_pii_evidence_names_the_declared_scanner(
    pii_evidence: Mapping[str, Any] | None,
    aggregate: Mapping[str, Any],
) -> None:
    """Refuse une release dont la preuve PII nomme un autre scanner que son
    manifeste.

    Le candidat `profile_gate_v2` déclarait `pii_scanner_sha256 = 388e3ed4…`
    (le scanner courant) et embarquait une preuve produite par `8ec8af55…`.
    Les deux valeurs étaient scellées, chacune dans son fichier, et rien ne les
    confrontait : la preuve attestait 486 × CLEARED avec un instrument que la
    release ne déclarait pas."""
    declared = (aggregate.get("authorities") or {}).get("pii_scanner_sha256")
    measured = pii_evidence.get("scanner_sha256") if pii_evidence else None
    if not declared or not measured or declared != measured:
        raise ValueError(
            "PII evidence scanner differs from the manifest's pii_scanner_sha256 "
            f"(evidence {str(measured)[:16]}…, manifest {str(declared)[:16]}…) — "
            "the attestation was not produced by the instrument the release declares"
        )


def _programme_registry(profiles: Mapping[str, Any]) -> dict[str, Any]:
    collection_config = load_collection_config(COLLECTION_CONFIG_PATH)["collections"]
    indexes = [
        {"path": path, "sha256": _file_sha256(REPOSITORY_ROOT / path)}
        for path in PROGRAMME_INDEX_PATHS
    ]
    taxonomies = []
    for collection in sorted(profiles):
        definition = collection_config[collection]
        path = REPOSITORY_ROOT / "services/rag-pedago/taxonomy" / definition[
            "taxonomy_file"
        ]
        taxonomy = _load_yaml(path)
        taxonomies.append(
            {
                "collection": collection,
                "path": _repo_relative(path),
                "sha256": _file_sha256(path),
                "niveau": taxonomy["niveau"],
                "voie": taxonomy["voie"],
                "matiere": taxonomy["matiere"],
                "statut_enseignement": taxonomy["statut_enseignement"],
                "programme_version": taxonomy["programme_version"],
            }
        )
    return {
        "registry_kind": "NEXUS_PROGRAMME_INDEX_REGISTRY_V3",
        "school_year": SCHOOL_YEAR,
        "indexes": indexes,
        "taxonomies": taxonomies,
    }


def _placement(
    row: Mapping[str, Any],
    *,
    profile: Any,
    status: str,
    include_artifact_id: bool,
    currentness: str,
) -> dict[str, Any]:
    sha = row["content_sha256"]
    # ADR-0059 §2 : la valeur produit est DÉRIVÉE de la disposition V3 du
    # contenu (`served_currentness_from_evidence`). `current` n'est plus écrit
    # en dur : il affirmait une identité d'octets pour des instantanés.
    if currentness not in PRODUCT_CURRENTNESS_VALUES:
        raise ValueError(
            f"placement currentness {currentness!r} is not a product value "
            f"({sorted(PRODUCT_CURRENTNESS_VALUES)})"
        )
    placement_document = {
        "artifact_id": sha,
        "audience": sorted(value.value for value in profile.scope.audience),
        "candidat": profile.scope.candidat.value,
        "collection": str(profile.scope.collection),
        "matiere": str(profile.scope.matiere),
        "niveau": profile.scope.niveau.value,
        "programme_version": str(profile.scope.programme_version),
        "school_year": str(profile.scope.school_year),
        "statut_enseignement": status,
        "tenant": str(profile.scope.tenant),
        "visibility": str(profile.scope.visibility),
        "voie": profile.scope.voie.value,
    }
    placement_id = _sha256_bytes(_compact_json_bytes(placement_document))
    placement = {
        "placement_id": placement_id,
        "source_placement_id": row["source_placement_id"],
        "source_scope": row["external_scope"],
        "collection": row["collection"],
        "tenant": str(profile.scope.tenant),
        "niveau": profile.scope.niveau.value,
        "voie": profile.scope.voie.value,
        "matiere": str(profile.scope.matiere),
        "statut_enseignement": status,
        "candidat": profile.scope.candidat.value,
        "visibility": str(profile.scope.visibility),
        "school_year": str(profile.scope.school_year),
        "programme_version": str(profile.scope.programme_version),
        "currentness": currentness,
        "placement_status": "active",
        "review_status": "reviewed",
    }
    if include_artifact_id:
        placement["artifact_id"] = sha
    return placement


def _artifact(
    row: Mapping[str, Any],
    *,
    profile: Any,
    status: str,
    preflight: Mapping[str, Any],
    type_doc_mapping: Mapping[str, str],
    currentness: str,
) -> dict[str, Any]:
    sha = row["content_sha256"]
    placement = _placement(
        row,
        profile=profile,
        status=status,
        include_artifact_id=False,
        currentness=currentness,
    )
    placement_id = placement["placement_id"]
    chunks = [
        {
            key: chunk[key]
            for key in (
                "chunk_index",
                "chunk_id",
                "chunk_sha256",
                "page_start",
                "page_end",
            )
        }
        for chunk in preflight["chunks"]
    ]
    pages = sorted(
        {
            page
            for chunk in chunks
            for page in range(chunk["page_start"], chunk["page_end"] + 1)
        }
    )
    return {
        "content_sha256": sha,
        "source_path": row["physical_path"],
        "source_url": row["current_download_url"] or row["source_url"],
        "current_download_url": row["current_download_url"],
        "title": row["title"],
        "type_doc": type_doc_mapping[row["external_document_type"]],
        "page_count": preflight["page_count"],
        "placements": [placement],
        "chunks": chunks,
        "placement_id_set_digest": _set_digest([placement_id]),
        "chunk_id_set_digest": _set_digest([chunk["chunk_id"] for chunk in chunks]),
        "chunk_sha256_set_digest": _set_digest(
            [chunk["chunk_sha256"] for chunk in chunks]
        ),
        "page_coverage_digest": _set_digest(pages),
    }


def _global_artifact(
    row: Mapping[str, Any],
    *,
    preflight: Mapping[str, Any],
    type_doc_mapping: Mapping[str, str],
    source_url: str,
) -> dict[str, Any]:
    sha = str(row["content_sha256"])
    chunks = [
        {
            key: chunk[key]
            for key in (
                "chunk_index",
                "chunk_id",
                "chunk_sha256",
                "page_start",
                "page_end",
            )
        }
        for chunk in preflight["chunks"]
    ]
    pages = sorted(
        {
            page
            for chunk in chunks
            for page in range(chunk["page_start"], chunk["page_end"] + 1)
        }
    )
    return {
        "artifact_id": sha,
        "content_sha256": sha,
        "source_path": row["physical_path"],
        # ADR-0059 : téléchargement pour VERIFIED_CURRENT, provenance pour un
        # instantané — dérivé de la preuve, jamais `download or listing`.
        "source_url": source_url,
        "title": row["title"],
        "type_doc": type_doc_mapping[row["external_document_type"]],
        "page_count": preflight["page_count"],
        "ignored_empty_pages": list(preflight["ignored_empty_pages"]),
        "chunks": chunks,
        "chunk_id_set_digest": _set_digest(
            [chunk["chunk_id"] for chunk in chunks]
        ),
        "chunk_sha256_set_digest": _set_digest(
            [chunk["chunk_sha256"] for chunk in chunks]
        ),
        "page_coverage_digest": _set_digest(pages),
    }


def _release_topology_documents(
    placement_rows: list[dict[str, Any]],
    *,
    profiles: Mapping[str, Any],
    profile_manifest_digest: str,
    collection_config: Mapping[str, Any],
    preflight_by_sha: Mapping[str, Mapping[str, Any]],
    type_doc_mapping: Mapping[str, str],
    authorities: Mapping[str, str],
    models: Mapping[str, Any],
    release_root: Path,
    release_id: str,
    school_year: str,
    served_currentness: Mapping[str, ServedCurrentness],
    release_mode: str = "production",
    promotion_status: str | None = None,
    activation_status: str | None = None,
    review_status: str | None = None,
) -> dict[Path, bytes]:

    grouped_artifacts = _group_artifact_rows(placement_rows)
    artifact_shas = set(grouped_artifacts)
    if set(served_currentness) != artifact_shas:
        raise ValueError(
            "served currentness population differs from artifacts: "
            f"missing={sorted(artifact_shas - set(served_currentness))}, "
            f"extra={sorted(set(served_currentness) - artifact_shas)}"
        )
    preflight_shas = set(preflight_by_sha)
    if preflight_shas != artifact_shas:
        missing = sorted(artifact_shas - preflight_shas)
        extra = sorted(preflight_shas - artifact_shas)
        raise ValueError(
            "preflight population differs from artifacts: "
            f"missing={missing}, extra={extra}"
        )
    for sha, group in grouped_artifacts.items():
        preflight = preflight_by_sha[sha]
        if preflight.get("content_sha256") != sha:
            raise ValueError(
                f"preflight content identity differs for {sha}: "
                f"{preflight.get('content_sha256')!r}"
            )
        physical_path = group["artifact_row"]["physical_path"]
        if preflight.get("source_path") != physical_path:
            raise ValueError(
                f"preflight source path differs for {sha}: "
                f"{preflight.get('source_path')!r} != {physical_path!r}"
            )

    placement_collections = {
        str(row["collection"])
        for group in grouped_artifacts.values()
        for row in group["placement_rows"]
    }
    profile_collections = set(profiles)
    if profile_collections != placement_collections:
        profiles_without_placement = sorted(
            profile_collections - placement_collections
        )
        placements_without_profile = sorted(
            placement_collections - profile_collections
        )
        raise ValueError(
            "profile collections differ from placement collections: "
            f"profiles_without_placement={profiles_without_placement}, "
            f"placements_without_profile={placements_without_profile}"
        )

    artifacts = [
        _global_artifact(
            group["artifact_row"],
            preflight=preflight_by_sha[sha],
            type_doc_mapping=type_doc_mapping,
            source_url=served_currentness[sha].source_url,
        )
        for sha, group in grouped_artifacts.items()
    ]
    unique_chunk_count = sum(len(artifact["chunks"]) for artifact in artifacts)
    artifact_registry = {
        "release_kind": "MULTILEVEL_ARTIFACT_REGISTRY_V2",
        "release_id": release_id,
        "school_year": school_year,
        "expected_counts": {
            "unique_artifacts": len(artifacts),
            "unique_chunks": unique_chunk_count,
        },
        "artifacts": artifacts,
    }
    artifact_registry_path = release_root / "artifacts.release.json"
    artifact_registry_raw = canonical_json_bytes(artifact_registry)
    artifact_registry_sha = _sha256_bytes(artifact_registry_raw)

    placements_by_collection: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sha, group in grouped_artifacts.items():
        for row in group["placement_rows"]:
            collection = str(row["collection"])
            placement = _placement(
                row,
                profile=profiles[collection],
                status=collection_config[collection]["statut"],
                include_artifact_id=True,
                currentness=served_currentness[sha].currentness,
            )
            if placement["artifact_id"] != sha:
                raise ValueError("placement artifact identity differs from its group")
            placements_by_collection[collection].append(placement)

    documents: dict[Path, bytes] = {
        artifact_registry_path: artifact_registry_raw,
    }
    subjects: list[dict[str, str]] = []
    for collection in sorted(placements_by_collection):
        profile = profiles[collection]
        placements = sorted(
            placements_by_collection[collection],
            key=lambda placement: (placement["artifact_id"], placement["placement_id"]),
        )
        subject = {
            "release_kind": "MULTILEVEL_SUBJECT_RELEASE_V2",
            "release_id": f"{release_id}-{collection}",
            "school_year": school_year,
            "collection": collection,
            "programme_version": str(profile.scope.programme_version),
            "authorities": dict(authorities),
            "profile": {
                "version": profile.profile_version,
                "fingerprint": profile_fingerprint(profile),
                "manifest_digest": profile_manifest_digest,
            },
            "models": dict(models),
            "artifact_registry": {
                "path": "../artifacts.release.json",
                "sha256": artifact_registry_sha,
            },
            "expected_counts": {
                "unique_artifact_references": len(
                    {placement["artifact_id"] for placement in placements}
                ),
                "placements": len(placements),
            },
            "placements": placements,
        }
        path = release_root / "subjects" / f"{collection}.release.json"
        raw = canonical_json_bytes(subject)
        documents[path] = raw
        subjects.append(
            {
                "path": path.relative_to(release_root).as_posix(),
                "sha256": _sha256_bytes(raw),
                "collection": collection,
            }
        )

    aggregate = {
        "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V2",
        "release_id": release_id,
        "school_year": school_year,
        "authorities": dict(authorities),
        "models": dict(models),
        "artifact_registry": {
            "path": artifact_registry_path.relative_to(release_root).as_posix(),
            "sha256": artifact_registry_sha,
        },
        "expected_counts": {
            "unique_artifacts": len(artifacts),
            "placements": sum(len(rows) for rows in placements_by_collection.values()),
            "unique_chunks": unique_chunk_count,
            "subjects": len(subjects),
        },
        "subjects": subjects,
    }
    if release_mode != "production":
        aggregate["release_mode"] = release_mode
    if promotion_status is not None:
        aggregate["promotion_status"] = promotion_status
    if activation_status is not None:
        aggregate["activation_status"] = activation_status
    if review_status is not None:
        aggregate["review_status"] = review_status
    aggregate_path = release_root / "production-profile-gate.release.json"

    aggregate_raw = canonical_json_bytes(aggregate)
    documents[aggregate_path] = aggregate_raw
    release_registry = {
        "registry_version": "1",
        "school_year": school_year,
        "releases": [
            {
                "release_id": release_id,
                "collections": sorted(placements_by_collection),
                "manifest_path": (
                    Path(release_root.name) / aggregate_path.name
                ).as_posix(),
                "expected_manifest_sha256": _sha256_bytes(aggregate_raw),
                "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V2",
            }
        ],
    }
    documents[release_root.parent / "release-registry.json"] = canonical_json_bytes(
        release_registry
    )
    return documents


def validate_authority_bindings(
    *,
    repository_root: Path,
    bindings: dict[str, Any],
    aggregate: dict[str, Any],
    release_root: Path | None = None,
) -> None:
    if set(bindings) != {
        "binding_kind",
        "school_year",
        "profile_manifest_file_sha256",
        "profile_manifest_fingerprint",
        "runtime",
        "bindings",
    }:
        raise ValueError("authority bindings fields are not exact")
    runtime = bindings["runtime"]
    if not isinstance(runtime, dict) or runtime.get("pypdf") != CANONICAL_PYPDF_VERSION:
        raise ValueError("authority bindings runtime differs from the declared one")
    raw_bindings = bindings["bindings"]
    authorities = aggregate["authorities"]
    if not isinstance(raw_bindings, dict) or set(raw_bindings) != set(authorities):
        raise ValueError("authority binding set differs")
    root = repository_root.resolve()
    rel_root = release_root.resolve() if release_root else None
    seen_paths: set[Path] = set()
    for name, binding in raw_bindings.items():
        if set(binding) != {
            "path",
            "file_sha256",
            "authority_sha256",
            "authority_kind",
        }:
            raise ValueError(f"authority binding {name} fields differ")
        relative = Path(binding["path"])
        # Si release_root est fourni et que le fichier existe dans release_root (relatif à RELEASE_ROOT.parent)
        if rel_root is not None:
            # Les chemins des liaisons sont relatifs au dépôt. Les fichiers
            # que CETTE release produit n'y existent pas encore — ils sont
            # dans le répertoire de préparation — d'où la réécriture vers
            # `rel_root.parent`.
            #
            # Mais toutes les liaisons sous le répertoire des releases
            # n'appartiennent pas à la release produite : le registre
            # d'exclusions (ADR-0055) désigne le fichier scellé d'une
            # release ANTÉRIEURE. Le réécrire vers la sortie faisait
            # chercher un fichier qui n'y sera jamais, et `--output-dir`
            # devenait inutilisable dès qu'un registre d'exclusions était
            # fourni — c'est-à-dire pour toute régénération gouvernée.
            #
            # La réécriture n'est donc appliquée que si elle DÉSIGNE
            # quelque chose ; sinon le chemin du dépôt vaut, et s'il
            # n'existe pas davantage le refus vient de la lecture, nommé.
            racine_rel = RELEASE_ROOT.parent.relative_to(REPOSITORY_ROOT)
            try:
                sous_rel = relative.relative_to(racine_rel)
            except ValueError:
                path = (root / relative).resolve()
            else:
                candidate = (rel_root.parent / sous_rel).resolve()
                path = candidate if candidate.exists() else (root / relative).resolve()
        else:
            path = (root / relative).resolve()
        if relative.is_absolute() or path in seen_paths:
            raise ValueError("authority binding path is invalid")
        seen_paths.add(path)
        actual = _file_sha256(path)
        if actual != binding["file_sha256"]:
            raise ValueError(f"authority binding digest differs for {name}")
        if authorities[name] != binding["authority_sha256"]:
            raise ValueError(f"aggregate authority digest differs for {name}")
        kind = binding["authority_kind"]
        if kind == "FILE_SHA256" and actual != binding["authority_sha256"]:
            raise ValueError(f"file authority digest differs for {name}")
        if kind == "SEMANTIC_PROFILE_FINGERPRINT":
            if name != "profile_manifest_sha256" or binding[
                "authority_sha256"
            ] != bindings["profile_manifest_fingerprint"]:
                raise ValueError("profile manifest semantic digest differs")
        elif kind == "LOGICAL_SHA256":
            descriptor = _load_json(path)
            if descriptor.get("authority_sha256") != binding["authority_sha256"]:
                raise ValueError(f"logical authority digest differs for {name}")
        elif kind != "FILE_SHA256":
            raise ValueError(f"authority binding kind is unsupported for {name}")


def _comparer_autorites_a_la_reference(
    racine_ecrite: Path,
    *,
    reference: Path | None,
    motif: str | None,
    ecrites: set[Path],
) -> None:
    """Exiger un motif écrit pour tout écart d'empreinte d'autorité.

    L'auto-cohérence dit qu'une release ne se contredit pas ; elle ne dit rien
    de ce qui a changé depuis la précédente. Les deux sont nécessaires.
    """
    if reference is not None and str(reference).lower() == "none":
        print("AUTHORITY_REFERENCE=none — première émission, comparaison désactivée")
        return
    chemin_ref = (reference or RELEASE_ROOT) / "authority_bindings.json"
    if not chemin_ref.is_file():
        raise ValueError(
            f"référence d'autorité introuvable : {chemin_ref}. Passer "
            f"`--reference-release none` si cette émission n'a pas de précédent.")

    # `bindings` est un dictionnaire nom -> {authority_kind, file_sha256, …},
    # non une liste. Vérifié sur le fichier plutôt que supposé.
    avant = _load_json(chemin_ref)["bindings"]
    apres = _load_json(racine_ecrite / "authority_bindings.json")["bindings"]

    # ── DÉRIVÉE ou EXTERNE, sans liste à maintenir ──────────────────────
    #
    # Une autorité est DÉRIVÉE si ce même passage l'a écrite ; sinon elle est
    # EXTERNE. Le producteur connaît ses propres sorties : `ecrites` porte les
    # chemins relatifs qu'il vient de produire.
    #
    # Une autorité dérivée ne se compare pas à la release précédente : deux
    # releases différentes produisent des artefacts différents, et le constater
    # n'apprend rien. Elle se vérifie contre le passage qui vient de l'écrire —
    # c'est l'auto-cohérence, déjà assurée par `validate_authority_bindings`.
    #
    # Une autorité externe préexiste au passage. C'est elle, et elle seule, qui
    # appelle une comparaison à la référence et un motif si elle diffère.
    #
    # Sans cette distinction, une production exigeait NEUF justifications dont
    # huit sans objet — et un contrôle qu'on remplit sans lire cesse de protéger.
    externes = {
        nom for nom, liaison in apres.items()
        if Path(liaison["path"]) not in ecrites
    }
    derivees = sorted(set(apres) - externes)

    ecarts = [
        (nom, avant[nom]["file_sha256"], apres[nom]["file_sha256"])
        for nom in sorted(set(avant) & set(apres) & externes)
        if avant[nom]["file_sha256"] != apres[nom]["file_sha256"]
    ]
    if derivees:
        print(f"AUTHORITY_DERIVED={len(derivees)} — écrites par ce passage, "
              f"non comparées : {', '.join(derivees)}")
    nouvelles = sorted((set(apres) - set(avant)) & externes)
    disparues = sorted(set(avant) - set(apres))

    if not ecarts and not nouvelles and not disparues:
        print("AUTHORITY_DIGESTS=identiques à la référence")
        return
    if not motif:
        detail = "; ".join(f"{nom} {a[:12]}… -> {b[:12]}…" for nom, a, b in ecarts)
        raise ValueError(
            "des empreintes d'autorité diffèrent de la référence et aucun motif "
            f"n'est donné :\n  écarts : {detail or 'aucun'}\n"
            f"  autorités nouvelles : {nouvelles or 'aucune'}\n"
            f"  autorités disparues : {disparues or 'aucune'}\n"
            "  Passer `--authority-change-motive` avec la raison écrite.")
    print(f"AUTHORITY_DIGESTS_CHANGED={len(ecarts) + len(nouvelles) + len(disparues)}")
    for nom, a, b in ecarts:
        print(f"  {nom}: {a[:12]}… -> {b[:12]}…")
    require_motive_cites_the_commit_that_changed_each_authority(
        motif,
        changements=[
            *(
                ChangementAutorite(
                    nom=nom,
                    genre=AUTORITE_MODIFIEE,
                    chemin=apres[nom]["path"],
                    digest_reference=reference_digest,
                    digest_candidat=candidat_digest,
                )
                for nom, reference_digest, candidat_digest in ecarts
            ),
            *(
                ChangementAutorite(
                    nom=nom,
                    genre=AUTORITE_AJOUTEE,
                    chemin=apres[nom]["path"],
                    digest_reference=None,
                    digest_candidat=apres[nom]["file_sha256"],
                )
                for nom in nouvelles
            ),
            *(
                ChangementAutorite(
                    nom=nom,
                    genre=AUTORITE_SUPPRIMEE,
                    chemin=avant[nom]["path"],
                    digest_reference=avant[nom]["file_sha256"],
                    digest_candidat=None,
                )
                for nom in disparues
            ),
        ],
        repository_root=REPOSITORY_ROOT,
    )
    print(f"AUTHORITY_CHANGE_MOTIVE={motif}")


_COMMIT_TOKEN = re.compile(r"\b[0-9a-f]{7,40}\b")

#: Les trois familles d'écart entre la référence et la candidate. Elles se
#: prouvent différemment, mais aucune n'échappe à la preuve.
AUTORITE_MODIFIEE = "MODIFIED_AUTHORITIES"
AUTORITE_AJOUTEE = "ADDED_AUTHORITIES"
AUTORITE_SUPPRIMEE = "REMOVED_AUTHORITIES"


class AuthorityMotiveError(ValueError):
    """Un motif de changement d'autorité n'est pas vérifiable."""


@dataclass(frozen=True)
class ChangementAutorite:
    """Un écart d'autorité à justifier, avec les deux digests qui l'encadrent.

    `digest_reference` est ce que la release de référence liait ; `digest_candidat`
    ce que la candidate lie. L'un des deux est absent pour un ajout ou une
    suppression — c'est précisément ce qui distingue les trois familles.
    """

    nom: str
    genre: str
    chemin: str
    digest_reference: str | None
    digest_candidat: str | None


def _commit_is_reachable(repository_root: Path, commit: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(repository_root), "merge-base", "--is-ancestor", commit, "HEAD"],
        capture_output=True,
    ).returncode == 0


def _blob_sha256(repository_root: Path, commit: str, relative_path: str) -> str | None:
    """L'empreinte du *contenu* du fichier tel que ce commit le porte.

    Ce n'est pas l'identifiant du blob git — celui-ci hache un en-tête en plus
    du contenu. Les autorités portent le sha256 du contenu ; c'est donc lui, et
    lui seul, qui peut se confronter à `file_sha256`.
    """
    completed = subprocess.run(
        ["git", "-C", str(repository_root), "cat-file", "blob", f"{commit}:{relative_path}"],
        capture_output=True,
    )
    if completed.returncode != 0:
        return None
    return hashlib.sha256(completed.stdout).hexdigest()


def _parents(repository_root: Path, commit: str) -> list[str]:
    completed = subprocess.run(
        ["git", "-C", str(repository_root), "rev-list", "--parents", "-n", "1", commit],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return []
    return completed.stdout.split()[1:]


def _path_is_tracked(repository_root: Path, relative_path: str) -> bool:
    return subprocess.run(
        ["git", "-C", str(repository_root), "ls-files", "--error-unmatch", relative_path],
        capture_output=True,
    ).returncode == 0


def _git_connait_le_chemin(repository_root: Path, relative_path: str) -> bool:
    """git a-t-il la moindre trace de ce chemin ?

    Le suivi de l'index ne suffit pas : une autorité *supprimée* pointe un
    fichier qui n'est plus dans l'arbre de travail, et se déclarer hors portée
    dans ce cas rendrait la preuve de suppression facultative — c'est-à-dire
    inexistante. L'historique de HEAD tranche.
    """
    if _path_is_tracked(repository_root, relative_path):
        return True
    completed = subprocess.run(
        ["git", "-C", str(repository_root), "rev-list", "--max-count=1", "HEAD",
         "--", relative_path],
        capture_output=True,
        text=True,
    )
    return bool(completed.stdout.strip())


def _preuve_du_commit(
    repository_root: Path, changement: ChangementAutorite, commit: str
) -> str | None:
    """Ce que ce commit prouve de cet écart, ou None s'il ne prouve rien.

    Le cœur du contrôle : « ce commit a touché ce fichier » ne prouve rien du
    tout. Deux commits touchent le même fichier ; un seul porte le contenu que
    la candidate lie. C'est ce contenu qui est confronté.
    """
    porte = _blob_sha256(repository_root, commit, changement.chemin)
    etats_parents = [
        _blob_sha256(repository_root, parent, changement.chemin)
        for parent in _parents(repository_root, commit)
    ]

    if changement.genre == AUTORITE_SUPPRIMEE:
        # La preuve porte sur la dernière liaison connue côté référence : le
        # commit cité doit avoir quitté ce digest, et son parent le portait.
        if porte == changement.digest_reference:
            return None
        if changement.digest_reference not in etats_parents:
            return None
        return "suppression" if porte is None else "remplacement"

    if porte is None or porte != changement.digest_candidat:
        return None

    if changement.genre == AUTORITE_AJOUTEE:
        return "ajout" if all(etat is None for etat in etats_parents) else "reprise"

    if changement.digest_reference is not None and changement.digest_reference in etats_parents:
        # Chaîne complète : ANCIEN DIGEST → commit cité → NOUVEAU DIGEST.
        return "transition directe"
    # Le digest candidat est prouvé, mais la référence n'est pas au parent :
    # le passage a transité par des états intermédiaires. Le dire plutôt que
    # laisser croire à une chaîne qui n'a pas été établie.
    return "transition indirecte"


def require_motive_cites_the_commit_that_changed_each_authority(
    motif: str,
    *,
    changements: Sequence[ChangementAutorite],
    repository_root: Path,
) -> None:
    """Exiger que le motif cite, pour chaque écart d'autorité, le commit qui le porte.

    Un motif était de la prose libre : n'importe quelle phrase ouvrait la porte.
    Une release a ainsi été produite en attribuant le rescellement de
    `document_type_mapping_sha256` à un commit qui n'était même pas un ancêtre
    de HEAD — l'écart de digest était réel et légitime, mais la justification
    écrite, celle sur laquelle un relecteur s'appuie, était fausse et rien ne
    pouvait le dire.

    « Ce commit a touché ce fichier » ne suffit pas non plus : `2182339` a bien
    touché le mappage des types documentaires, mais c'est `a4b1f96` qui porte le
    digest que la candidate lie. Le motif doit donc citer, pour chaque écart, un
    commit qui (1) est atteignable depuis HEAD et (2) porte le contenu en cause :
    le digest candidat pour une modification ou un ajout, la sortie du digest de
    référence pour une suppression. Les trois familles sont contrôlées ; aucune
    n'est laissée à la prose. Seuls les chemins dont git n'a aucune trace —
    ni index, ni historique — sont déclarés hors portée, et le disent.
    """
    cites = {
        jeton for jeton in _COMMIT_TOKEN.findall(motif or "")
        if _commit_is_reachable(repository_root, jeton)
    }
    manquants: list[str] = []
    hors_portee: list[str] = []
    for changement in changements:
        if not _git_connait_le_chemin(repository_root, changement.chemin):
            hors_portee.append(f"{changement.nom} ({changement.chemin})")
            continue
        preuve = next(
            (
                (commit, qualification)
                for commit in sorted(cites)
                if (qualification := _preuve_du_commit(repository_root, changement, commit))
            ),
            None,
        )
        if preuve is None:
            attendu = (
                f"sortie de {changement.digest_reference[:12]}…"
                if changement.genre == AUTORITE_SUPPRIMEE and changement.digest_reference
                else f"digest {(changement.digest_candidat or '')[:12]}…"
            )
            manquants.append(
                f"{changement.nom} [{changement.genre}] ({changement.chemin}, {attendu})"
            )
            continue
        commit, qualification = preuve
        print(
            f"AUTHORITY_MOTIVE_PROVEN nom={changement.nom} genre={changement.genre} "
            f"commit={commit[:12]} preuve={qualification}"
        )
    if hors_portee:
        print(
            "AUTHORITY_MOTIVE_OUT_OF_SCOPE="
            f"{len(hors_portee)} — chemin inconnu de git : "
            f"{', '.join(sorted(hors_portee))}"
        )
    if manquants:
        raise AuthorityMotiveError(
            "le motif ne cite aucun commit atteignable portant le contenu de ces "
            f"autorités : {'; '.join(manquants)}.\n"
            f"  commits cités et atteignables : "
            f"{sorted(c[:12] for c in cites) or 'aucun'}\n"
            "  Citer dans `--authority-change-motive` le commit qui porte "
            "réellement chaque contenu. Avoir touché le fichier ne suffit pas."
        )
    print(f"AUTHORITY_MOTIVE_COMMITS_VERIFIED={len(cites)}")


def _verifier_preconditions(
    profiles: Mapping[str, Any],
    collection_config: Mapping[str, Any],
) -> None:
    """Refuser tout de suite ce qui échouera de toute façon, et le nommer.

    Chaque manque est rapporté avec son compte et un échantillon : un message
    qui nomme une seule collection sur cinquante-trois fait recommencer
    cinquante-trois fois.
    """
    manques: list[str] = []

    declarees = collection_config.get("collections") or {}
    absentes = sorted(set(profiles) - set(declarees))
    if absentes:
        manques.append(
            f"{len(absentes)} collection(s) absente(s) de rag_collections.yml : "
            f"{', '.join(absentes[:5])}"
            + (f" … et {len(absentes) - 5} autres" if len(absentes) > 5 else "")
        )

    racine_taxo = REPOSITORY_ROOT / "services/rag-pedago/taxonomy"
    sans_taxo: list[str] = []
    illisibles: list[str] = []
    for collection in sorted(set(profiles) & set(declarees)):
        fichier = declarees[collection].get("taxonomy_file")
        if not fichier:
            sans_taxo.append(collection)
            continue
        chemin = racine_taxo / fichier
        if not chemin.is_file():
            sans_taxo.append(f"{collection} -> {fichier}")
            continue
        try:
            donnees = _load_yaml(chemin)
            if not isinstance(donnees, dict) or "niveau" not in donnees:
                illisibles.append(f"{collection} -> {fichier} (niveau absent)")
        except Exception as exc:                             # noqa: BLE001
            illisibles.append(f"{collection} -> {fichier} ({type(exc).__name__})")
    if sans_taxo:
        manques.append(
            f"{len(sans_taxo)} taxonomie(s) absente(s) : "
            f"{', '.join(sans_taxo[:5])}"
            + (f" … et {len(sans_taxo) - 5} autres" if len(sans_taxo) > 5 else "")
        )
    if illisibles:
        manques.append(
            f"{len(illisibles)} taxonomie(s) illisible(s) : "
            f"{', '.join(illisibles[:5])}"
        )

    if manques:
        raise ValueError(
            "préconditions non réunies, aucun calcul n'a été engagé :\n  - "
            + "\n  - ".join(manques)
        )


def _build_rehearsal_release(
    *,
    currentness_authority: GovernedCurrentnessAuthority,
    pdf_root: Path | None = None,
    review_authority: ReviewAuthorityInputs = NO_REVIEW_AUTHORITY,
    source_release_root: Path,
    release_id: str,
    release_mode: str,
    promotion_status: str,
    activation_status: str,
    review_status: str,
    exclusion_registry: GovernedExclusionRegistry | None = None,
) -> dict[Path, bytes]:
    src_root = source_release_root.resolve()
    profile_root = REPOSITORY_ROOT / "services/rag-engine/configs/ingestion_profiles"
    profile_dir = profile_root / "v2_livraison_319"
    profile_manifest_path = profile_root / "ingestion_manifest_v2_livraison_319.yml"
    registry = load_profile_registry(profile_dir)
    manifest = verify_profile_manifest(registry, profile_manifest_path)
    profiles = {p.scope.collection: p for p in registry.values()}

    subjects_dir = src_root / "subjects"
    drive = {row["content_sha256"]: row for row in _load_json(DRIVE_MAPPING_PATH)}
    preflight_by_sha: dict[str, dict[str, Any]] = {}
    placement_rows: list[dict[str, Any]] = []
    for subj_file in sorted(subjects_dir.glob("*.release.json")):
        subj = _load_json(subj_file)
        col = subj["collection"]
        for art in subj["artifacts"]:
            sha = art["content_sha256"]
            if exclusion_registry is not None and sha in exclusion_registry.excluded_contents:
                continue
            if sha not in preflight_by_sha:
                preflight_by_sha[sha] = {
                    "content_sha256": sha,
                    "source_path": art["source_path"],
                    "page_count": art["page_count"],
                    "ignored_empty_pages": art.get("ignored_empty_pages", []),
                    "chunks": art["chunks"],
                }
            if sha not in drive:
                raise ValueError(f"Drive snapshot fact is absent for {sha}")
            for pl in art["placements"]:
                placement_rows.append({
                    "content_sha256": sha,
                    "physical_path": art["source_path"],
                    "drive_modified_time": drive[sha]["modified_time"],
                    "source_url": art.get("source_url", ""),
                    "current_download_url": art.get("current_download_url", ""),
                    "title": art["title"],
                    "external_document_type": art["type_doc"],
                    "collection": col,
                    "source_placement_id": pl["source_placement_id"],
                    "external_scope": pl["source_scope"],
                })

    collection_config = load_collection_config(COLLECTION_CONFIG_PATH)["collections"]
    type_doc_mapping = _load_yaml(DOCUMENT_TYPE_MAPPING_PATH)["document_types"]
    effective_type_doc_mapping = {**type_doc_mapping, **{v: v for v in type_doc_mapping.values()}}

    auth_doc = _load_json(src_root / "authority_bindings.json")
    raw_bindings = dict(auth_doc["bindings"])
    authorities = {k: v["authority_sha256"] for k, v in raw_bindings.items()}

    authorities["document_type_mapping_sha256"] = _file_sha256(DOCUMENT_TYPE_MAPPING_PATH)
    raw_bindings["document_type_mapping_sha256"] = {
        "path": _repo_relative(DOCUMENT_TYPE_MAPPING_PATH),
        "file_sha256": authorities["document_type_mapping_sha256"],
        "authority_sha256": authorities["document_type_mapping_sha256"],
        "authority_kind": "FILE_SHA256",
    }

    authorities["pii_scanner_sha256"] = _file_sha256(PII_SCANNER_PATH)
    raw_bindings["pii_scanner_sha256"] = {
        "path": _repo_relative(PII_SCANNER_PATH),
        "file_sha256": authorities["pii_scanner_sha256"],
        "authority_sha256": authorities["pii_scanner_sha256"],
        "authority_kind": "FILE_SHA256",
    }

    authorities["profile_manifest_sha256"] = manifest.manifest_fingerprint
    raw_bindings["profile_manifest_sha256"] = {
        "path": _repo_relative(profile_manifest_path),
        "file_sha256": _file_sha256(profile_manifest_path),
        "authority_sha256": manifest.manifest_fingerprint,
        "authority_kind": "SEMANTIC_PROFILE_FINGERPRINT",
    }

    if exclusion_registry is not None:
        authorities["currentness_exclusion_registry_sha256"] = exclusion_registry.sha256
        raw_bindings["currentness_exclusion_registry_sha256"] = {
            "path": _repo_relative(exclusion_registry.path),
            "file_sha256": exclusion_registry.sha256,
            "authority_sha256": exclusion_registry.sha256,
            "authority_kind": "FILE_SHA256",
        }

    # ── L'ACTUALITÉ ET L'INVENTAIRE SONT RÉÉMIS, PAS RECOPIÉS ──────────
    #
    # Cette voie recopiait `candidate_inventory.json`, `currentness_evidence.json`
    # et `currentness_network_audit.json` de la release source. Le candidat
    # `profile_gate_v2` en a hérité une preuve V1 déclarant 486 × CURRENT par
    # identité d'octets à côté d'un audit disant 0 vérifié, un inventaire à 486
    # contenus pour 319 et les quatre exclus ADR-0055. Les trois sont désormais
    # recalculés pour la population de CETTE release ; les autorités qu'ils
    # citent (catalogue, delta, autorité effective) restent celles de la source.
    excluded = (
        exclusion_registry.excluded_contents if exclusion_registry is not None else frozenset()
    )
    inventory = _recount_candidate_inventory(
        _load_json(src_root / "candidate_inventory.json"), excluded=frozenset(excluded)
    )
    inventory_keys = {
        (collection["collection"], candidate["content_sha256"], placement["source_placement_id"])
        for collection in inventory["collections"]
        for candidate in collection["candidates"]
        for placement in candidate["placements"]
    }
    release_keys = {
        (row["collection"], row["content_sha256"], row["source_placement_id"])
        for row in placement_rows
    }
    if inventory_keys != release_keys or len(release_keys) != len(placement_rows):
        raise ValueError(
            "source candidate inventory placements differ from the release placements: "
            f"{len(inventory_keys - release_keys)} absent from the release, "
            f"{len(release_keys - inventory_keys)} absent from the inventory"
        )
    inventory_raw = canonical_json_bytes(inventory)
    source_audit_path = src_root / "currentness_network_audit.json"
    source_audit = _load_json(source_audit_path) if source_audit_path.is_file() else {}
    network_audit, _network_rows = resolve_currentness_network_audit(
        placement_rows,
        verify_official_downloads=False,
        audit_path=source_audit_path,
        release_id=release_id,
        source_unreachable=(
            source_audit.get("currentness_status") == UNVERIFIED_CURRENTNESS_STATUS
        ),
    )
    network_audit, currentness = _currentness_documents(
        placement_rows,
        inventory=inventory,
        inventory_sha256=_sha256_bytes(inventory_raw),
        network_audit=network_audit,
        authority=currentness_authority,
        exclusion_registry=exclusion_registry,
    )
    reemitted = {
        "candidate_inventory.json": inventory_raw,
        "currentness_network_audit.json": canonical_json_bytes(network_audit),
        "currentness_evidence.json": canonical_json_bytes(currentness),
    }
    # ── LA PREUVE PII, RÉÉMISE QUAND LE MIROIR EST FOURNI ──────────────
    #
    # Sans miroir, la preuve source est recopiée — et la garde d'écriture la
    # refuse si elle nomme un autre scanner que le manifeste, ce qui était le
    # cas du candidat V2. Avec le miroir, elle est reproduite par la fonction
    # de production, pour la population conservée seulement.
    renamed_bindings = [
        ("candidate_inventory_sha256", "candidate_inventory.json"),
        ("currentness_evidence_sha256", "currentness_evidence.json"),
    ]
    if pdf_root is not None:
        reemitted["pii_evidence.json"] = canonical_json_bytes(
            _rehearsal_pii_evidence(
                placement_rows,
                pdf_root=pdf_root,
                inventory_sha256=_sha256_bytes(inventory_raw),
                review_authority=review_authority,
                preflight_by_sha=preflight_by_sha,
            )
        )
        renamed_bindings.append(("pii_evidence_sha256", "pii_evidence.json"))
        for name, path in {
            "pii_policy_sha256": PII_POLICY_PATH,
            **_review_chain_authority_paths(review_authority),
        }.items():
            digest = _file_sha256(path)
            authorities[name] = digest
            raw_bindings[name] = {
                "path": _repo_relative(path),
                "file_sha256": digest,
                "authority_sha256": digest,
                "authority_kind": "FILE_SHA256",
            }
    for name, file_name in renamed_bindings:
        digest = _sha256_bytes(reemitted[file_name])
        authorities[name] = digest
        raw_bindings[name] = {
            "path": _repo_relative(RELEASE_ROOT / file_name),
            "file_sha256": digest,
            "authority_sha256": digest,
            "authority_kind": "FILE_SHA256",
        }

    models = {
        "embedding": {
            "model_id": CANONICAL_EMBEDDING_MODEL,
            "inventory_sha256": authorities["embedding_inventory_sha256"],
            "dimension": 1024,
        },
        "reranker": {
            "model_id": CANONICAL_RERANKER_MODEL,
            "inventory_sha256": authorities["reranker_inventory_sha256"],
        },
    }


    documents = _release_topology_documents(
        placement_rows,
        profiles=profiles,
        profile_manifest_digest=manifest.manifest_fingerprint,
        collection_config=collection_config,
        preflight_by_sha=preflight_by_sha,
        type_doc_mapping=effective_type_doc_mapping,
        authorities=authorities,
        models=models,
        release_root=RELEASE_ROOT,
        release_id=release_id,
        school_year=SCHOOL_YEAR,
        served_currentness=served_currentness_from_evidence(currentness),
        release_mode=release_mode,
        promotion_status=promotion_status,
        activation_status=activation_status,
        review_status=review_status,
    )

    if exclusion_registry is not None:
        documents[RELEASE_ROOT / "release_currentness_exclusion_registry.json"] = (
            exclusion_registry.path.read_bytes()
        )

    for file_name, raw in reemitted.items():
        documents[RELEASE_ROOT / file_name] = raw
    for evidence_file in (
        "catalog_delta.json",
        "effective_catalog_authority.json",
        "corpus_manifest_authority.json",
        *(() if "pii_evidence.json" in reemitted else ("pii_evidence.json",)),
        "preflight_evidence.json",
        "programme_registry.json",
        "models/embedding/manifest.json",
        "models/embedding/SHA256SUMS",
        "models/reranker/manifest.json",
        "models/reranker/SHA256SUMS",
    ):

        p = src_root / evidence_file
        if p.exists():
            documents[RELEASE_ROOT / evidence_file] = p.read_bytes()

    bindings = {

        "binding_kind": "PRODUCTION_PROFILE_RELEASE_AUTHORITY_BINDINGS_V1",
        "school_year": SCHOOL_YEAR,
        "profile_manifest_file_sha256": _file_sha256(profile_manifest_path),
        "profile_manifest_fingerprint": manifest.manifest_fingerprint,
        "runtime": {"pypdf": require_canonical_runtime()},
        "bindings": raw_bindings,
    }
    documents[RELEASE_ROOT / "authority_bindings.json"] = canonical_json_bytes(bindings)
    return documents


def build_release(
    *,
    pdf_root: Path | None = None,
    embedding_snapshot: Path | None = None,
    reranker_snapshot: Path | None = None,
    verify_official_downloads: bool = False,
    release_mode: str = "production",
    promotion_status: str | None = None,
    activation_status: str | None = None,
    review_status: str | None = None,
    release_id: str | None = None,
    source_release_root: Path | None = None,
    review_authority: ReviewAuthorityInputs | None = None,
    exclusion_registry: GovernedExclusionRegistry | None = None,
    currentness_authority: GovernedCurrentnessAuthority | None = None,
) -> dict[Path, bytes]:
    # ADR-0059 : l'actualité d'une release dérive de la matrice de servabilité
    # gouvernée. Sans elle, aucune disposition ne peut être écrite — ni par la
    # production, ni par la répétition qui recopiait une preuve V1 fausse.
    if currentness_authority is None:
        raise ValueError(
            "the governed servability matrix is required to build a release "
            "(--servability-matrix / --servability-matrix-sha256)"
        )
    if release_mode == "rehearsal":
        return _build_rehearsal_release(
            currentness_authority=currentness_authority,
            pdf_root=pdf_root,
            review_authority=review_authority or NO_REVIEW_AUTHORITY,
            source_release_root=source_release_root or RELEASE_ROOT,
            release_id=release_id or "production-profile-gate-2026-2027-v2-rehearsal",
            release_mode=release_mode,
            promotion_status=promotion_status or "NOT_PROMOTABLE",
            activation_status=activation_status or "NO_PRODUCTION_ACTIVATION",
            review_status=review_status or "PRE_REVIEW",
            exclusion_registry=exclusion_registry,
        )
    if pdf_root is None or embedding_snapshot is None or reranker_snapshot is None:
        raise ValueError("pdf_root, embedding_snapshot, and reranker_snapshot are required in production mode")

    # Une seule lignée, résolue une fois. `build_release` redéfinissait ici ses
    # propres défauts — la matrice du 25 août et les dix-huit profils — alors
    # que les constantes du module en documentaient d'autres. Un lecteur qui
    # lisait les constantes se trompait, et une exécution « par défaut »
    # rendait 26 documents au lieu de 320.
    lineage = resolve_release_lineage()
    matrix_path = lineage.matrix_path
    matrix = _load_json(matrix_path)
    profile_root = lineage.profile_root
    profile_manifest_path = lineage.profile_manifest_path
    registry = load_profile_registry(profile_root)
    manifest = verify_profile_manifest(registry, profile_manifest_path)
    profiles = {profile.scope.collection: profile for profile in registry.values()}
    # L'invariant est juste et il survit : le registre de profils et le manifeste
    # doivent déclarer le MÊME compte. Un manifeste qui annonce un nombre que le
    # répertoire ne contient pas est un manifeste qui affirme plus qu'il n'a
    # vérifié — la famille de défauts de ce dépôt.
    #
    # Ce qui était fautif, c'est la CONSTANTE. `!= 18` figeait l'invariant sur le
    # périmètre d'un jour, et interdisait toute release additionnelle sans rien
    # garantir de plus. Le manifeste est la référence, pas un nombre en dur.
    if len(profiles) != manifest.declared_count:
        raise ValueError(
            f"production profile registry declares {len(profiles)} profiles, "
            f"manifest declares {manifest.declared_count}"
        )
    if not profiles:
        raise ValueError("production profile registry declares no profile")
    # ── PRÉCONDITIONS, VALIDÉES AVANT DE DÉPENSER ──────────────────────
    #
    # Le 29/08/2026, un build a rendu la main après 57 MINUTES — scan PII de
    # 2 348 documents, puis chunking — sur un `KeyError` de collection non
    # déclarée. Le producteur avait tout calculé avant de vérifier qu'il pouvait
    # écrire quoi que ce soit.
    #
    # Valider les préconditions coûte une seconde ; les valider après coûte une
    # heure par tentative. C'est la différence entre itérer et attendre.
    _verifier_preconditions(profiles, _load_yaml(COLLECTION_CONFIG_PATH))

    placement_rows = _source_records(matrix=matrix, profiles=profiles)
    if exclusion_registry is not None:
        placement_rows = [
            r for r in placement_rows if r["content_sha256"] not in exclusion_registry.excluded_contents
        ]
    final_set_raw, accepted_placements_raw, verified_profiles_raw = (
        _release_scope_inputs(
            matrix=matrix,
            profiles=profiles,
            profile_manifest_digest=manifest.manifest_fingerprint,
            # La portée nomme LA release produite, jamais la constante
            # historique : sans quoi une candidate scellerait ses placements
            # sous l'identité d'une autre chaîne.
            release_id=require_governed_release_id(release_id),
        )
    )
    pdfs = validate_pdf_mirror(
        pdf_root=pdf_root,
        content_sha256=[row["content_sha256"] for row in placement_rows],
    )
    token_counter = E5TokenCounter(embedding_snapshot)

    embedding_manifest, embedding_inventory = _model_inventory(
        snapshot=embedding_snapshot,
        manifest={
            "model_id": CANONICAL_EMBEDDING_MODEL,
            "revision": CANONICAL_EMBEDDING_REVISION,
            "canonical_dim": 1024,
        },
    )
    reranker_manifest, reranker_inventory = _model_inventory(
        snapshot=reranker_snapshot,
        manifest={
            "model_id": CANONICAL_RERANKER_MODEL,
            "revision": CANONICAL_RERANKER_REVISION,
        },
    )
    delta, effective = _catalog_documents(placement_rows)
    inventory = _candidate_inventory(placement_rows, delta=delta, effective=effective)
    inventory_sha = _sha256_bytes(canonical_json_bytes(inventory))
    network_audit, _network_rows = resolve_currentness_network_audit(
        placement_rows,
        verify_official_downloads=verify_official_downloads,
        release_id=release_id,
    )
    network_audit, currentness = _currentness_documents(
        placement_rows,
        inventory=inventory,
        inventory_sha256=inventory_sha,
        network_audit=network_audit,
        authority=currentness_authority,
        exclusion_registry=exclusion_registry,
    )
    served_currentness = served_currentness_from_evidence(currentness)
    pii = _pii_evidence(
        placement_rows,
        pdfs=pdfs,
        inventory_sha256=inventory_sha,
        review_authority=review_authority or NO_REVIEW_AUTHORITY,
    )
    preflight = _preflight(
        placement_rows,
        pdfs=pdfs,
        token_counter=token_counter,
        pii_evidence=pii,
    )
    programme = _programme_registry(profiles)

    corpus_descriptor = _corpus_descriptor(placement_rows)
    documents: dict[Path, bytes] = {
        RELEASE_ROOT / "catalog_delta.json": canonical_json_bytes(delta),
        RELEASE_ROOT / "effective_catalog_authority.json": canonical_json_bytes(effective),
        RELEASE_ROOT / "candidate_inventory.json": canonical_json_bytes(inventory),
        RELEASE_ROOT / "currentness_network_audit.json": canonical_json_bytes(network_audit),
        RELEASE_ROOT / "currentness_evidence.json": canonical_json_bytes(currentness),
        RELEASE_ROOT / "pii_evidence.json": canonical_json_bytes(pii),
        RELEASE_ROOT / "preflight_evidence.json": canonical_json_bytes(preflight),
        RELEASE_ROOT / "programme_registry.json": canonical_json_bytes(programme),
        RELEASE_ROOT / "corpus_manifest_authority.json": canonical_json_bytes(
            corpus_descriptor
        ),
        RELEASE_ROOT / "models/embedding/manifest.json": embedding_manifest,
        RELEASE_ROOT / "models/embedding/SHA256SUMS": embedding_inventory,
        RELEASE_ROOT / "models/reranker/manifest.json": reranker_manifest,
        RELEASE_ROOT / "models/reranker/SHA256SUMS": reranker_inventory,
        **(
            {RELEASE_ROOT / "release_currentness_exclusion_registry.json": exclusion_registry.path.read_bytes()}
            if exclusion_registry is not None
            else {}
        ),
    }
    authority_paths = {
        "corpus_manifest_sha256": RELEASE_ROOT / "corpus_manifest_authority.json",
        "parent_sealed_catalog_sha256": DRIVE_MAPPING_PATH,
        "placement_catalog_sha256": PLACEMENT_LEDGER_PATH,
        "catalog_delta_sha256": RELEASE_ROOT / "catalog_delta.json",
        "effective_catalog_authority_sha256": RELEASE_ROOT
        / "effective_catalog_authority.json",
        "candidate_inventory_sha256": RELEASE_ROOT / "candidate_inventory.json",
        "currentness_evidence_sha256": RELEASE_ROOT / "currentness_evidence.json",
        "pii_evidence_sha256": RELEASE_ROOT / "pii_evidence.json",
        "pii_policy_sha256": PII_POLICY_PATH,
        "pii_scanner_sha256": PII_SCANNER_PATH,
        # ADR-0047 §7 : la décision humaine et son reçu appartiennent à la
        # chaîne d'autorité de CE candidat. On ne réécrit jamais les liens
        # d'une release historique pour les y faire entrer après coup.
        **_review_chain_authority_paths(review_authority),
        **(
            {"currentness_exclusion_registry_sha256": exclusion_registry.path}
            if exclusion_registry is not None
            else {}
        ),
        "rights_registry_sha256": RIGHTS_REGISTRY_PATH,
        "preflight_evidence_sha256": RELEASE_ROOT / "preflight_evidence.json",
        "programme_registry_sha256": RELEASE_ROOT / "programme_registry.json",
        "profile_manifest_sha256": lineage.profile_manifest_path,
        "level_mapping_sha256": LEVEL_MAPPING_PATH,
        "subject_mapping_sha256": SUBJECT_MAPPING_PATH,
        "document_type_mapping_sha256": DOCUMENT_TYPE_MAPPING_PATH,
        "embedding_inventory_sha256": RELEASE_ROOT / "models/embedding/SHA256SUMS",
        "reranker_inventory_sha256": RELEASE_ROOT / "models/reranker/SHA256SUMS",
    }
    logical_authorities = {
        "corpus_manifest_sha256": CORPUS_MANIFEST_AUTHORITY,
        "effective_catalog_authority_sha256": effective["authority_sha256"],
        "profile_manifest_sha256": manifest.manifest_fingerprint,
    }
    authorities: dict[str, str] = {}
    raw_bindings: dict[str, dict[str, str]] = {}
    for name, path in authority_paths.items():
        file_bytes = documents.get(path, path.read_bytes() if path.is_file() else b"")
        if not file_bytes:
            raise ValueError(f"authority file is absent: {path}")
        file_sha = _sha256_bytes(file_bytes)
        authority_sha = logical_authorities.get(name, file_sha)
        kind = (
            "SEMANTIC_PROFILE_FINGERPRINT"
            if name == "profile_manifest_sha256"
            else "LOGICAL_SHA256"
            if name in logical_authorities
            else "FILE_SHA256"
        )
        authorities[name] = authority_sha
        raw_bindings[name] = {
            "path": _repo_relative(path),
            "file_sha256": file_sha,
            "authority_sha256": authority_sha,
            "authority_kind": kind,
        }

    models = {
        "embedding": {
            "model_id": CANONICAL_EMBEDDING_MODEL,
            "inventory_sha256": authorities["embedding_inventory_sha256"],
            "dimension": 1024,
        },
        "reranker": {
            "model_id": CANONICAL_RERANKER_MODEL,
            "inventory_sha256": authorities["reranker_inventory_sha256"],
        },
    }
    collection_config = load_collection_config(COLLECTION_CONFIG_PATH)["collections"]
    preflight_by_sha = {
        row["content_sha256"]: row for row in preflight["artifacts"]
    }
    type_doc_mapping = _load_yaml(DOCUMENT_TYPE_MAPPING_PATH)["document_types"]
    documents.update(
        _release_topology_documents(
            placement_rows,
            profiles=profiles,
            profile_manifest_digest=manifest.manifest_fingerprint,
            collection_config=collection_config,
            preflight_by_sha=preflight_by_sha,
            type_doc_mapping=type_doc_mapping,
            authorities=authorities,
            models=models,
            release_root=RELEASE_ROOT,
            served_currentness=served_currentness,
            # §8 : une candidate porte SA propre identité. Réemployer
            # l'identifiant historique ferait passer une nouvelle release pour
            # celle dont la sémantique a déjà dérivé — et rendrait indécidable
            # laquelle des deux un registre désigne.
            release_id=require_governed_release_id(release_id),
            school_year=SCHOOL_YEAR,
            # §9-§10 : le corpus peut être final et la release rester non
            # activable. Le gate PII n'est qu'un des gates de go-live, et le
            # runtime refuse déjà mécaniquement NOT_PROMOTABLE /
            # NO_PRODUCTION_ACTIVATION. Ces statuts traversent donc aussi la
            # voie production, sans quoi une candidate serait silencieusement
            # activable au seul motif que sa PII est en règle.
            **resolve_release_lifecycle_statuses(
                release_mode=release_mode,
                release_id=release_id,
                promotion_status=promotion_status,
                activation_status=activation_status,
                review_status=review_status,
            ),
        )
    )
    bindings = {
        "binding_kind": "PRODUCTION_PROFILE_RELEASE_AUTHORITY_BINDINGS_V1",
        "school_year": SCHOOL_YEAR,
        "profile_manifest_file_sha256": _file_sha256(lineage.profile_manifest_path),
        "profile_manifest_fingerprint": manifest.manifest_fingerprint,
        # D-41 : une release nomme l'interpréteur qui l'a produite. Sans cela,
        # « cette release est reproductible » est une phrase sans domaine.
        "runtime": {"pypdf": require_canonical_runtime()},
        "bindings": raw_bindings,
    }
    documents[RELEASE_ROOT / "authority_bindings.json"] = canonical_json_bytes(bindings)
    documents[FINAL_PRODUCTION_SET_PATH] = final_set_raw
    documents[ACCEPTED_PLACEMENTS_PATH] = accepted_placements_raw
    documents[VERIFIED_PROFILES_PATH] = verified_profiles_raw
    return documents


def _identite_de_release(documents: Mapping[Path, bytes]) -> str:
    """Dériver l'identité de la release DE SON CONTENU.

    Un même `release_id` pour deux contenus différents rend toute référence
    ambiguë : aucune vérification a posteriori ne peut plus dire laquelle des
    deux elle a validée. Tout l'appareil de scellement — inventaires
    `SHA256SUMS`, empreintes canoniques, `ReviewBindings`, registres de
    placement — suppose qu'un identifiant désigne UN contenu, et rien
    n'imposait cette unicité.

    Dériver l'identité du contenu la rend structurelle : deux contenus
    différents ne peuvent pas produire le même identifiant.
    """
    racine = RELEASE_ROOT.parent
    normalises: dict[str, bytes] = {}
    for chemin, contenu in documents.items():
        try:
            relatif = chemin.relative_to(racine)
        except ValueError:
            relatif = Path(chemin.name)
        normalises[relatif.as_posix()] = contenu

    empreinte = hashlib.sha256()
    for rel_posix, contenu in sorted(normalises.items(), key=lambda x: x[0]):
        empreinte.update(rel_posix.encode("utf-8"))
        empreinte.update(hashlib.sha256(contenu).digest())
    return empreinte.hexdigest()[:16]


def verify_release_directory_identity(release_dir: Path) -> str:
    """D-15 : Vérifier que le nom du répertoire correspond EXACTEMENT à l'empreinte de son contenu."""
    fichiers = {
        p.relative_to(release_dir).as_posix(): p.read_bytes()
        for p in sorted(release_dir.rglob("*"))
        if p.is_file()
    }
    if not fichiers:
        raise ValueError(f"release directory is empty: {release_dir}")
    empreinte = hashlib.sha256()
    for rel_posix, contenu in sorted(fichiers.items(), key=lambda x: x[0]):
        empreinte.update(rel_posix.encode("utf-8"))
        empreinte.update(hashlib.sha256(contenu).digest())
    fingerprint = empreinte.hexdigest()[:16]
    expected_name = f"release-{fingerprint}"
    if release_dir.name != expected_name:
        raise ValueError(
            f"D-15 VIOLATION: release directory name {release_dir.name} does not match content fingerprint {expected_name} (computed {fingerprint})"
        )
    return fingerprint


def _write_documents(
    documents: Mapping[Path, bytes],
    *,
    output_dir: Path | None = None,
    validate_reference: bool = False,
    reference_release: Path | None = None,
    authority_change_motive: str | None = None,
) -> Path:
    """Écrire la release dans un répertoire NEUF, jamais dans celui qui sert.

    Retourne le répertoire écrit. Le basculement se fait ensuite, à part, par
    un lien symbolique — geste atomique et réversible d'un `ln -sfn`.
    """
    if output_dir is None:
        raise ValueError(
            "output_dir explicite est obligatoire : aucune release ne peut "
            "être écrite dans les chemins historiques"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    identite = _identite_de_release(documents)
    cible = output_dir / f"release-{identite}"
    if cible.exists():
        # Même identité = même contenu : la réémission est un no-op vérifiable.
        # Une identité différente ne peut pas atterrir ici, par construction.
        raise ValueError(
            f"le répertoire {cible} existe déjà. Une identité de release dérive "
            f"de son contenu : si le contenu est identique, il n'y a rien à "
            f"réécrire ; s'il diffère, il aurait une autre identité.")

    staging_parent = Path(
        tempfile.mkdtemp(prefix=f".{cible.name}.staging-", dir=output_dir)
    )
    staging = staging_parent / cible.name
    try:
        racine = RELEASE_ROOT.parent
        for chemin, contenu in sorted(
            documents.items(), key=lambda x: x[0].as_posix()
        ):
            try:
                relatif = chemin.relative_to(racine)
            except ValueError:
                relatif = Path(chemin.name)
            destination = staging / relatif
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contenu)

        # D-31 : valider le contrat du consommateur dans le staging. Une
        # release invalide ne reçoit jamais son nom dans le répertoire final.
        racine_ecrite = staging / RELEASE_ROOT.relative_to(RELEASE_ROOT.parent)
        aggregate_manifest = racine_ecrite / "production-profile-gate.release.json"
        if aggregate_manifest.exists():
            manifest_sha = hashlib.sha256(aggregate_manifest.read_bytes()).hexdigest()
            load_release_expectation(aggregate_manifest, manifest_sha)
        release_registry = racine_ecrite.parent / "release-registry.json"
        if release_registry.exists():
            registry_sha = hashlib.sha256(release_registry.read_bytes()).hexdigest()
            load_release_registry_file(release_registry, registry_sha)

        # Toute liaison interne et toute divergence contre la référence sont
        # contrôlées dans le staging. Après le rename, il ne reste aucun garde
        # susceptible de transformer une release déjà publiée en échec.
        bindings_path = racine_ecrite / "authority_bindings.json"
        if aggregate_manifest.exists() and bindings_path.exists():
            # Une release complète : sa preuve PII doit nommer le scanner que
            # son manifeste déclare. Le défaut du candidat V2, fermé ici.
            pii_path = racine_ecrite / "pii_evidence.json"
            require_pii_evidence_names_the_declared_scanner(
                _load_json(pii_path) if pii_path.is_file() else None,
                _load_json(aggregate_manifest),
            )
            validate_authority_bindings(
                repository_root=REPOSITORY_ROOT,
                bindings=_load_json(bindings_path),
                aggregate=_load_json(aggregate_manifest),
                release_root=racine_ecrite,
            )
        if validate_reference:
            _comparer_autorites_a_la_reference(
                racine_ecrite,
                reference=reference_release,
                motif=authority_change_motive,
                ecrites={
                    chemin.resolve().relative_to(REPOSITORY_ROOT)
                    for chemin in documents
                    if chemin.resolve().is_relative_to(REPOSITORY_ROOT)
                },
            )

        # Le répertoire est immuable : on le rend non inscriptible après
        # validation et avant publication.
        for chemin in sorted(staging.rglob("*")):
            if chemin.is_file():
                chemin.chmod(0o444)
        verify_release_directory_identity(staging)

        if cible.exists():
            raise ValueError(f"la cible finale existe déjà: {cible}")
        staging.rename(cible)
        staging_parent.rmdir()
    except Exception:
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise
    return cible


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-root", required=False, type=Path, default=None)
    parser.add_argument("--embedding-snapshot", required=False, type=Path, default=None)
    parser.add_argument("--reranker-snapshot", required=False, type=Path, default=None)
    parser.add_argument(
        "--release-mode",
        choices=["production", "rehearsal"],
        default="production",
        help="Mode de release: 'production' ou 'rehearsal'",
    )
    parser.add_argument(
        "--promotion-status",
        choices=["PROMOTABLE", "NOT_PROMOTABLE"],
        default=None,
        help="Statut de promotion (défaut: NOT_PROMOTABLE si rehearsal)",
    )
    parser.add_argument(
        "--activation-status",
        choices=["PRODUCTION_ACTIVATION_ALLOWED", "NO_PRODUCTION_ACTIVATION"],
        default=None,
        help="Statut d'activation (défaut: NO_PRODUCTION_ACTIVATION si rehearsal)",
    )
    parser.add_argument(
        "--review-status",
        choices=["REVIEWED", "PRE_REVIEW"],
        default=None,
        help="Statut de revue PII (défaut: PRE_REVIEW si rehearsal)",
    )
    parser.add_argument(
        "--release-id",
        default=None,
        help="Identifiant de la release",
    )
    parser.add_argument(
        "--source-release-root",
        type=Path,
        default=None,
        help="Répertoire source pour la génération rehearsal",
    )
    # ── PRODUIRE NE DOIT PAS POUVOIR TOUCHER CE QUI SERT ────────────────
    #
    # Le 29/08/2026, ce producteur a écrasé la release EN SERVICE et rendu le
    # moteur indisponible pendant quatre minutes. Ce n'était que le service
    # local ; la même commande après bascule aurait retiré le service aux
    # familles. Seule la cible différait.
    #
    # Un drapeau `--output-dir` corrige l'occurrence ; il ne rend pas l'accident
    # impossible — il suffit de l'oublier une fois. La propriété visée est plus
    # forte, et la PRODUCTION l'applique déjà :
    #
    #     /opt/rag-v2/current -> /opt/rag-v2/releases/rag-v2-main-27a4558-…
    #
    # Un répertoire de release IMMUABLE nommé par son identité, et un lien
    # `current` basculé d'un geste atomique. Le producteur écrit toujours dans
    # un répertoire neuf ; il ne peut pas écrire dans celui qui sert, parce que
    # celui qui sert n'est jamais sa cible. Le retour arrière est un `ln -sfn`.
    #
    # Même architecture des deux côtés : cela supprime l'écart entre
    # l'environnement où l'on essaie et celui où l'on livre.
    # ── AUTO-COHÉRENCE **ET** ÉCART JUSTIFIÉ ────────────────────────────
    #
    # La vérification des liens d'autorité lisait le répertoire SERVANT, par
    # accident de chemin. Corrigé, elle ne lisait plus que la release écrite —
    # et devenait TAUTOLOGIQUE : une release qui redéfinit une autorité et met à
    # jour son propre lien en conséquence est auto-cohérente, donc passe.
    #
    # C'est pourtant ce contrôle qui a détecté le changement du mappage de types
    # et produit la preuve d'additivité. En le rendant auto-référent, j'avais
    # supprimé le vrai positif avec le faux.
    #
    # La comparaison n'est donc pas supprimée : elle est REDIRIGÉE vers une base
    # de référence CHOISIE — la release précédente — et tout écart d'empreinte
    # d'autorité exige son motif, écrit. On ne remplace pas un contrôle qui gêne
    # par un contrôle qui ne gêne jamais.
    parser.add_argument(
        "--reference-release", type=Path, default=None,
        help="Release servant de référence pour les empreintes d'autorité. "
             "Défaut : la release du dépôt. `none` désactive la comparaison — "
             "réservé à une première émission, qui n'a pas de précédent.")
    parser.add_argument(
        "--authority-change-motive", default=None,
        help="Motif écrit de tout écart d'empreinte d'autorité contre la "
             "référence. Exigé dès qu'un écart existe ; conservé dans la trace.")
    parser.add_argument(
        "--output-dir", type=Path, required=False, default=None,
        help="Répertoire de sortie. NEUF et vide — le producteur refuse "
             "d'écrire dans un répertoire existant qui n'est pas le sien. "
             "Facultatif en mode --dry-run.")
    parser.add_argument(
        "--exclusion-registry",
        type=Path,
        default=None,
        help="Chemin vers le registre gouverné scellé des contenus exclus pour cause d'actualité (ADR-0055).",
    )
    parser.add_argument(
        "--exclusion-registry-sha256",
        default=None,
        help="Empreinte SHA-256 attendue du registre d'exclusion pour vérification fail-closed.",
    )
    # ── L'ACTUALITÉ S'INJECTE, ELLE NE SE DÉCIDE PAS ICI (ADR-0059) ─────
    #
    # La disposition d'actualité de chaque contenu vient de la matrice de
    # servabilité gouvernée, produite sous la politique appliquée (ADR-0055).
    # Matrice et empreinte sont exigées ensemble ; l'une sans l'autre, ou une
    # empreinte qui ne correspond pas aux octets, refuse la construction.
    parser.add_argument(
        "--servability-matrix",
        type=Path,
        default=None,
        help="Matrice de servabilité gouvernée (NEXUS-SERVABILITY-MATRIX-V1). Exigée.",
    )
    parser.add_argument(
        "--servability-matrix-sha256",
        default=None,
        help="Empreinte SHA-256 attendue des octets de la matrice. Exigée.",
    )
    parser.add_argument(
        "--currentness-policy",
        type=Path,
        default=None,
        help="Politique d'actualité appliquée. Défaut : la politique gouvernée "
             "du dépôt ; refusée si elle ne se déclare pas appliquée.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simule la génération en mémoire sans écrire aucun fichier sur disque.",
    )
    parser.add_argument("--verify-official-downloads", action="store_true")
    # ── L'AUTORITÉ DE REVUE PII S'INJECTE ───────────────────────────────
    #
    # Ni identifiant de campagne, ni chemin de gouvernance en dur : faire
    # tourner une autre campagne demain ne doit toucher aucune ligne de ce
    # fichier. Les quatre entrées sont fournies ensemble ou pas du tout ; une
    # release sans contenu détecté n'a pas de décisions à joindre, et le
    # producteur refuse toute détection non dispositionnée.
    for option, description in (
        ("pii-decision-set", "ensemble scellé des décisions humaines de revue PII"),
        ("pii-review-receipt", "reçu ADR-0035 scellant cet ensemble"),
        ("review-trust-anchor", "ancre de confiance vérifiant le reçu"),
        ("pii-review-index", "index des paquets de revue ayant fondé les décisions"),
    ):
        parser.add_argument(f"--{option}", type=Path, default=None, help=description)
    parser.add_argument(
        "--pii-review-reviewer",
        action="append",
        default=None,
        dest="pii_review_reviewers",
        help=(
            "Login GitHub autorisé à approuver l'ensemble de décisions. Répétable. "
            "Absent signifie qu'aucune revue n'est acceptée — jamais que tout "
            "reviewer convient."
        ),
    )
    args = parser.parse_args(argv)
    if not args.dry_run and args.output_dir is None:
        parser.error("--output-dir est requis lorsque --dry-run n'est pas activé")

    if args.servability_matrix is None or not args.servability_matrix_sha256:
        parser.error(
            "--servability-matrix et --servability-matrix-sha256 sont requis : "
            "l'actualité d'une release dérive de la matrice gouvernée (ADR-0059)"
        )

    exclusion_registry = load_and_validate_exclusion_registry(
        args.exclusion_registry,
        expected_sha256=args.exclusion_registry_sha256,
    )
    currentness_authority = load_governed_currentness_authority(
        args.servability_matrix,
        args.servability_matrix_sha256,
        policy_path=args.currentness_policy,
    )

    review_authority = ReviewAuthorityInputs(
        decision_set_path=args.pii_decision_set,
        receipt_path=args.pii_review_receipt,
        trust_anchor_path=args.review_trust_anchor,
        review_index_path=args.pii_review_index,
        reviewers=tuple(args.pii_review_reviewers or ()),
    )
    if args.release_mode == "production" and (
        args.pdf_root is None
        or args.embedding_snapshot is None
        or args.reranker_snapshot is None
    ):
        parser.error("--pdf-root, --embedding-snapshot, and --reranker-snapshot are required in production mode")

    require_canonical_runtime()  # D-41 : à la porte, avant les huit minutes.
    documents = build_release(
        pdf_root=args.pdf_root,
        embedding_snapshot=args.embedding_snapshot,
        reranker_snapshot=args.reranker_snapshot,
        verify_official_downloads=args.verify_official_downloads,
        release_mode=args.release_mode,
        promotion_status=args.promotion_status,
        activation_status=args.activation_status,
        review_status=args.review_status,
        release_id=args.release_id,
        source_release_root=args.source_release_root,
        review_authority=review_authority,
        exclusion_registry=exclusion_registry,
        currentness_authority=currentness_authority,
    )

    if args.dry_run:
        manifest_bytes = documents.get(RELEASE_ROOT / "production-profile-gate.release.json")
        if not manifest_bytes:
            raise RuntimeError("dry-run: production-profile-gate.release.json non généré en mémoire")
        aggregate = json.loads(manifest_bytes.decode("utf-8"))
        pii_bytes = documents.get(RELEASE_ROOT / "pii_evidence.json")
        require_pii_evidence_names_the_declared_scanner(
            json.loads(pii_bytes) if pii_bytes else None, aggregate
        )
        counts = aggregate.get("expected_counts", {})
        unique_artifacts = counts.get("unique_artifacts", 0)
        placements = counts.get("placements", 0)
        unique_chunks = counts.get("unique_chunks", 0)
        collections_count = counts.get("subjects", len(aggregate.get("subjects", [])))
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        print("DRY_RUN=true")
        print(f"EXCLUDED_CONTENTS_COUNT={len(exclusion_registry.excluded_contents) if exclusion_registry else 0}")
        print(f"PRODUCTION_PROFILE_RELEASE_UNIQUE_ARTIFACTS={unique_artifacts}")
        print(f"PRODUCTION_PROFILE_RELEASE_PLACEMENTS={placements}")
        print(f"PRODUCTION_PROFILE_RELEASE_COLLECTIONS={collections_count}")
        print(f"PRODUCTION_PROFILE_RELEASE_CHUNKS={unique_chunks}")
        print(f"PRODUCTION_PROFILE_RELEASE_SHA256={manifest_sha}")
        return 0

    ecrit = _write_documents(
        documents,
        output_dir=args.output_dir,
        validate_reference=True,
        reference_release=args.reference_release,
        authority_change_motive=args.authority_change_motive,
    )
    if args.output_dir is not None:
        print(f"PRODUCTION_PROFILE_RELEASE_DIR={ecrit}")
        if args.release_mode == "production":
            print("PRODUCTION_PROFILE_RELEASE_ACTIVATION="
                  f"ln -sfn {ecrit} {args.output_dir / 'current'}")
        else:
            print(f"REHEARSAL_STATUS={args.review_status or 'PRE_REVIEW'}")
            print(f"PROMOTABLE={'true' if args.promotion_status == 'PROMOTABLE' else 'false'}")
            print(f"ACTIVATABLE={'true' if args.activation_status == 'PRODUCTION_ACTIVATION_ALLOWED' else 'false'}")

    # La vérification porte sur la release QUI VIENT D'ÊTRE ÉCRITE, jamais sur
    # celle qui sert. Lire `RELEASE_ROOT` ici confrontait les liens d'autorité
    # de l'ANCIENNE release aux fichiers courants du dépôt : tout changement
    # d'une autorité — même purement additif — faisait échouer une production
    # qui, elle, était parfaitement cohérente avec elle-même.
    #
    # L'invariant qui vaut est l'auto-cohérence : la release enregistre les
    # empreintes des fichiers qu'elle a effectivement utilisés.
    racine_verif = (
        ecrit / RELEASE_ROOT.relative_to(RELEASE_ROOT.parent)
        if args.output_dir is not None else RELEASE_ROOT
    )
    aggregate = _load_json(racine_verif / "production-profile-gate.release.json")
    print(
        "PRODUCTION_PROFILE_RELEASE_UNIQUE_ARTIFACTS="
        f"{aggregate['expected_counts']['unique_artifacts']}"
    )
    print(
        "PRODUCTION_PROFILE_RELEASE_PLACEMENTS="
        f"{aggregate['expected_counts']['placements']}"
    )
    print(f"PRODUCTION_PROFILE_RELEASE_COLLECTIONS={len(aggregate['subjects'])}")
    print(
        "PRODUCTION_PROFILE_RELEASE_SHA256="
        f"{_file_sha256(racine_verif / 'production-profile-gate.release.json')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
