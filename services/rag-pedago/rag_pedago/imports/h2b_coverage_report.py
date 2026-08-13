"""H2-B Coverage Report Generator.

Generates comprehensive coverage report proving:
- CORPUS_TOTAL = 2,584
- SUM(dispositions) = CORPUS_TOTAL
- Zero overlap (each object has exactly one disposition)
- Zero gap (no object without disposition)

Usage:
    python -m rag_pedago.imports.h2b_coverage_report \
        --catalog data/reports/corpus_disposition_catalog.json \
        --rights configs/rights_evidence_registry.yml \
        --pii /path/to/sealed_pii_evidence.json \
        --routing configs/corpus_zone_routing.yml \
        --golden configs/golden_corpus_h2b.yml \
        --manifest /path/to/SHA256SUMS.txt \
        --authority /path/to/scope_authorization.json \
        --authority-review-binding /path/to/review_binding.json \
        --authority-trust-anchor /path/to/trust_anchor.json \
        --authority-environment production \
        --output data/reports/h2b_coverage_report.md

Modes (ADR-0035) :

- ``--authority-environment production`` (défaut) exige une clé de
  production ; seul ce mode peut produire ``coverage_complete=true``.
- ``--authority-environment rehearsal`` exerce les clés de test et vérifie
  toute la chaîne, mais ne rend **jamais** un verdict final vert.

Le reçu de liaison de revue est émis par le plan de données :

    python -m ingestor.ingestion_worker.issue_review_binding_cli issue \
        --repository cyranoaladin/RAG --pull-request <n> \
        --expected-head <sha> --authorization-id <id> --key-id <key>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from nexus_contracts import ScopeAuthorizationArtifactV2
from nexus_contracts.authority_artifacts import (
    CanonicalArtifactError,
    canonical_authorization_path,
    git_blob_sha1,
    parse_scope_authorization_artifact,
)
from nexus_contracts.document import Rights
from nexus_contracts.review_binding import (
    ReviewBindingError,
    parse_trust_anchor,
    require_challenge_is_bound,
    require_matches_authorization,
    verify_review_binding,
)

from rag_pedago.imports.corpus_catalog_compiler import (
    verify_catalog_evidence_bindings,
)
from rag_pedago.imports.golden_corpus_validator import (
    load_spec,
    validate_golden_corpus,
)


@dataclass
class CoverageReport:
    """H2-B coverage report."""

    report_id: str
    generated_at: str
    git_commit: str
    git_branch: str

    # Evidence provenance
    real_corpus_catalog_source: bool
    synthetic_catalog_used_for_final_gate: bool
    manifest_sha256: str

    # Corpus totals
    corpus_total_expected: int
    corpus_total_actual: int
    corpus_match: bool

    # Disposition totals
    totals: dict[str, int] = field(default_factory=dict)
    totals_sum: int = 0

    # Verification
    sum_equals_total: bool = False
    zero_overlap: bool = False
    zero_gap: bool = False
    decision_coverage_complete: bool = False
    coverage_complete: bool = False
    unclassified: int = 0
    multiple_primary_disposition: int = 0
    safety_invariants: dict[str, int] = field(default_factory=dict)
    blocked_ingest_candidates: int = 0
    mandatory_gate_blockers: dict[str, int] = field(default_factory=dict)

    # Artifact / placement integration
    content_artifact_count: int = 0
    eduscol_unique_artifacts: int = 0
    eduscol_placement_count: int = 0
    eduscol_placements_classified: int = 0
    eduscol_placements_unclassified: int = 0
    multi_placement_artifacts: int = 0

    # Gate statuses
    rights_gate_status: str = "UNKNOWN"
    pii_gate_status: str = "UNKNOWN"
    rights_evidence_bound: bool = False
    pii_evidence_bound: bool = False
    currentness_gate_status: str = "UNKNOWN"
    format_gate_status: str = "UNKNOWN"

    # Golden corpus
    golden_controls_total: int = 0
    golden_controls_passed: int = 0
    golden_controls_failed: int = 0
    golden_validation_status: str = "UNKNOWN"
    golden_validation_pass: bool = False
    h2_coverage_gate_pass: bool = False

    # ADR-0035 — liaison de revue scellée
    authority_environment: str = "production"
    authority_review_binding_verified: bool = False
    #: F2 : la non-révocation a-t-elle été *prouvée* contre un registre
    #: gouverné, ou seulement supposée faute de registre ? Le rapport
    #: publie la différence au lieu de la lisser.
    authority_revocations_checked: bool = False

    # Files and hashes
    input_files: dict[str, str] = field(default_factory=dict)


def _get_git_commit() -> str:
    """Get current git commit hash."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    commit = result.stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("git HEAD is not a full commit SHA")
    return commit


def _get_git_branch() -> str:
    """Get current git branch."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _file_sha256(path: Path) -> str:
    """Compute SHA256 of a file."""
    if not path.exists():
        return "file_not_found"
    sha = hashlib.sha256()
    sha.update(path.read_bytes())
    return sha.hexdigest()


def load_catalog(path: Path) -> dict[str, Any]:
    """Load corpus disposition catalog."""
    content = path.read_text(encoding="utf-8")
    return json.loads(content)


def _load_yaml_mapping(path: Path, *, label: str) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


_GNU_SHA256_LINE = re.compile(r"([0-9a-f]{64})  (.*)\Z")


def _parse_manifest(path: Path) -> list[tuple[str, str]]:
    """Parse un manifeste GNU SHA256 en paires ``(sha256, path)``.

    F5 : les entrées sont conservées **avec leur cardinalité** — la liste
    n'est jamais réduite en ensemble ici. Deux refus explicites :

    * une ligne strictement dupliquée ;
    * un même chemin associé plusieurs fois, que le digest soit identique
      ou non.

    Le second est le cas dangereux : deux digests différents pour un même
    chemin décrivent deux contenus, et un ensemble en absorbe un
    silencieusement. Le même digest pour deux chemins **distincts** reste
    autorisé — c'est un doublon de contenu légitime, que le format GNU
    exprime normalement.

    Aucune normalisation de chemin n'est faite ici : décider que deux
    écritures différentes désignent le même fichier appartient aux règles
    de canonicité, pas à ce parseur, qui les rapporterait sinon comme un
    seul chemin sans que personne ne l'ait décidé.
    """
    entries: list[tuple[str, str]] = []
    seen_lines: set[tuple[str, str]] = set()
    path_first_line: dict[str, int] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\r\n")
            match = _GNU_SHA256_LINE.fullmatch(line)
            if match is None:
                raise ValueError(f"H2-F Défaut 1: invalid manifest line {line_number}")
            content_sha256, object_path = match.groups()
            entry = (content_sha256, object_path)
            if entry in seen_lines:
                raise ValueError(
                    f"H2-F Défaut 1: manifest line {line_number} duplicates an "
                    f"earlier identical entry for path {object_path!r}"
                )
            if object_path in path_first_line:
                raise ValueError(
                    f"H2-F Défaut 1: manifest line {line_number} re-declares path "
                    f"{object_path!r}, already declared at line "
                    f"{path_first_line[object_path]} — a path has exactly one "
                    "digest in a sealed manifest"
                )
            seen_lines.add(entry)
            path_first_line[object_path] = line_number
            entries.append(entry)
    return entries


# P1 PRRT_kwDOTEIbbs6X3cnF: Canonical path of the synthetic manifest self-object
# The compiler adds this object AFTER generating the manifest, so it's not
# in the manifest itself but must be present exactly once in the catalog.
_MANIFEST_SELF_PATH = "00_ADMIN/SHA256SUMS.txt"


def _verify_manifest_binding(
    manifest_path: Path,
    catalog: dict[str, Any],
) -> None:
    """H2-F Défaut 1: Verify exact binding between sealed manifest and catalog.

    P1 PRRT_kwDOTEIbbs6X3cnF: The catalog contains 2584 objects while the manifest
    contains 2583 entries because the compiler adds the synthetic manifest self-object
    (00_ADMIN/SHA256SUMS.txt) AFTER generating the manifest. This function:
    1. Verifies the self-object exists exactly once in the catalog
    2. Verifies the self-object's content_sha256 equals the manifest file's SHA256
    3. Excludes the self-object from the manifest/catalog comparison
    4. Requires exact equality of all other entries
    """
    # Compute actual manifest SHA256
    actual_manifest_sha256 = _file_sha256(manifest_path)
    if actual_manifest_sha256 is None:
        raise ValueError("H2-F Défaut 1: cannot compute manifest SHA256")

    # Compare with catalog-declared SHA256
    catalog_manifest_sha256 = catalog.get("manifest_sha256")
    if actual_manifest_sha256 != catalog_manifest_sha256:
        raise ValueError(
            f"H2-F Défaut 1: manifest SHA256 mismatch: "
            f"actual={actual_manifest_sha256}, catalog={catalog_manifest_sha256}"
        )

    # Parse manifest and compare with catalog.
    # F5 : multiensemble, pas ensemble. ``frozenset`` rendait deux
    # catalogues de tailles différentes égaux dès lors qu'ils portaient
    # les mêmes entrées distinctes — exactement l'écart qu'un doublon
    # injecté exploite.
    manifest_entries = _parse_manifest(manifest_path)
    manifest_counts = Counter(manifest_entries)

    physical_objects = catalog.get("physical_objects", [])
    if not isinstance(physical_objects, list):
        raise ValueError("H2-F Défaut 1: catalog physical_objects must be a list")

    # P1 PRRT_kwDOTEIbbs6X3cnF: Find and validate the synthetic self-object
    self_objects = [
        obj for obj in physical_objects
        if isinstance(obj, dict) and obj.get("path") == _MANIFEST_SELF_PATH
    ]
    if len(self_objects) == 0:
        raise ValueError(
            f"H2-F Défaut 1: synthetic manifest self-object '{_MANIFEST_SELF_PATH}' "
            "is missing from catalog"
        )
    if len(self_objects) > 1:
        raise ValueError(
            f"H2-F Défaut 1: synthetic manifest self-object '{_MANIFEST_SELF_PATH}' "
            f"appears {len(self_objects)} times in catalog (must be exactly once)"
        )
    self_object = self_objects[0]
    self_object_sha256 = self_object.get("content_sha256")
    if self_object_sha256 != actual_manifest_sha256:
        raise ValueError(
            f"H2-F Défaut 1: synthetic self-object content_sha256 mismatch: "
            f"self_object={self_object_sha256}, manifest_file={actual_manifest_sha256}"
        )

    # Build catalog multiset EXCLUDING the self-object. L'exclusion reste
    # unique et explicite, et n'intervient qu'APRÈS que la présence et
    # l'unicité du self-object ont été prouvées ci-dessus.
    catalog_entries = [
        (obj.get("content_sha256"), obj.get("path"))
        for obj in physical_objects
        if isinstance(obj, dict) and obj.get("path") != _MANIFEST_SELF_PATH
    ]
    catalog_counts: Counter[tuple[Any, Any]] = Counter(catalog_entries)

    # F5 : les doublons côté catalogue sont *rapportés*, pas absorbés.
    catalog_duplicates = sorted(
        (entry for entry, count in catalog_counts.items() if count > 1),
        key=lambda item: (str(item[1]), str(item[0])),
    )
    if catalog_duplicates:
        sample = catalog_duplicates[0]
        raise ValueError(
            f"H2-F Défaut 1: catalog declares {len(catalog_duplicates)} duplicated "
            f"(content_sha256, path) entries, e.g. path {sample[1]!r} appearing "
            f"{catalog_counts[sample]} times — a physical object is listed once"
        )

    # Comparaison de multiensembles : l'égalité porte sur les entrées ET
    # sur leurs cardinalités.
    if manifest_counts != catalog_counts:
        only_in_manifest = manifest_counts - catalog_counts
        only_in_catalog = catalog_counts - manifest_counts
        errors = []
        if only_in_manifest:
            errors.append(f"{sum(only_in_manifest.values())} entries only in manifest")
        if only_in_catalog:
            errors.append(f"{sum(only_in_catalog.values())} entries only in catalog")
        if not errors:  # pragma: no cover - cardinalités seules
            errors.append("entry cardinalities differ")
        total_manifest = sum(manifest_counts.values())
        total_catalog = sum(catalog_counts.values())
        raise ValueError(
            f"H2-F Défaut 1: manifest/catalog mismatch: {', '.join(errors)} "
            f"(manifest={total_manifest} entries, catalog={total_catalog} entries)"
        )


#: Catégorie de droits qui n'autorise jamais rien — la voir dans une
#: autorisation signifie qu'aucune décision de droits n'a été prise.
_UNKNOWN_RIGHTS = "unknown"

#: F4 : vocabulaire canonique des catégories de droits — celui du
#: contrat partagé, jamais une liste parallèle redéfinie ici. Une
#: valeur hors de cet ensemble n'est pas « inconnue », elle est
#: refusée.
_RIGHTS_VOCABULARY = frozenset(item.value for item in Rights)


def _authority_structural_validation(
    authority_path: Path,
) -> tuple[ScopeAuthorizationArtifactV2, bytes]:
    """STRUCTURAL_VALIDATION — les octets sont-ils une autorisation LOT41A ?

    ``parse_scope_authorization_artifact`` fait deux choses que
    ``model_validate(json.loads(...))`` ne faisait pas :

    1. il valide le schéma strict (aucune clé en trop, types stricts) ;
    2. il exige la **canonicité octet à octet** — les octets du fichier
       doivent être exactement leur propre re-sérialisation canonique.

    Le point 2 est la correction réelle : sans lui, un fichier aux clés
    réordonnées ou ré-indenté passait la validation Pydantic tout en ayant
    un digest qui ne correspondait à aucun octet relisible. Le digest
    calculé ensuite porte donc sur les octets réellement présents sur le
    disque, jamais sur une reconstruction.
    """
    if not authority_path.is_file():
        raise ValueError(
            f"H2-F Défaut 5: authority evidence file does not exist: {authority_path}"
        )
    raw = authority_path.read_bytes()
    try:
        artifact = parse_scope_authorization_artifact(raw)
    except CanonicalArtifactError as exc:
        raise ValueError(
            f"STRUCTURAL_VALIDATION failed: {authority_path} is not a canonical "
            f"LOT41A authorization artifact: {exc}"
        ) from exc
    if not isinstance(artifact, ScopeAuthorizationArtifactV2):
        raise ValueError(
            "STRUCTURAL_VALIDATION failed: the final gate requires a LOT41A-V2 "
            f"authorization (content allowlist), got {artifact.protocol_version!r} "
            "— a V1 authorization is domain-scoped only and can never prove that "
            "a given corpus object was authorized"
        )
    return artifact, raw


def _authority_semantic_validation(
    artifact: ScopeAuthorizationArtifactV2,
    *,
    manifest_sha256: str,
    ingest_content_sha256: frozenset[str],
    ingest_rights_candidates: tuple[tuple[str, str | None], ...],
    now: datetime,
    revoked_authorization_ids: frozenset[str],
) -> frozenset[str]:
    """SEMANTIC_VALIDATION — l'autorisation dit-elle réellement *ceci* ?

    Un JSON bien formé n'est pas une autorisation. Chaque contrôle
    ci-dessous refuse seul, et chacun a son test de rejet dédié :
    décision, périmètre du manifest, complétude de l'allowlist, catégories
    de droits, attestation PII, fenêtre de validité, non-révocation.
    """
    if artifact.decision != "AUTHORIZE_INGESTION_SCOPE":
        raise ValueError(
            "SEMANTIC_VALIDATION failed: authority decision must be "
            f"AUTHORIZE_INGESTION_SCOPE, got {artifact.decision!r}"
        )
    if artifact.manifest_digest != manifest_sha256:
        raise ValueError(
            "SEMANTIC_VALIDATION failed: authority is bound to another manifest "
            f"(authority={artifact.manifest_digest[:16]}..., "
            f"catalog={manifest_sha256[:16]}...)"
        )
    if artifact.authorization_id in revoked_authorization_ids:
        raise ValueError(
            "SEMANTIC_VALIDATION failed: authorization "
            f"{artifact.authorization_id!r} appears in the revocation registry — "
            "a revoked authorization never authorizes anything again"
        )
    if not artifact.pii_absence_attested:
        raise ValueError(
            "SEMANTIC_VALIDATION failed: pii_absence_attested is false"
        )
    rights = tuple(category.value for category in artifact.rights_categories)
    if _UNKNOWN_RIGHTS in rights:
        raise ValueError(
            "SEMANTIC_VALIDATION failed: rights_categories contains "
            f"{_UNKNOWN_RIGHTS!r} — an undetermined rights category authorizes "
            "nothing and can never appear in a granted authorization"
        )
    if now < artifact.valid_from:
        raise ValueError(
            "SEMANTIC_VALIDATION failed: authorization is not valid yet "
            f"(valid_from={artifact.valid_from.isoformat()}, now={now.isoformat()})"
        )
    if now >= artifact.valid_until:
        raise ValueError(
            "SEMANTIC_VALIDATION failed: authorization expired at "
            f"{artifact.valid_until.isoformat()} (now={now.isoformat()})"
        )

    allowlist = frozenset(artifact.allowed_content_sha256)
    # Complétude, pas échantillon : chaque objet destiné à l'ingestion doit
    # être nommé par l'autorisation. Un objet manquant est un objet que
    # personne n'a autorisé — le compter comme « invariant de sécurité »
    # a posteriori laisserait le gate produire un rapport où l'autorisation
    # est présentée comme vérifiée alors qu'elle ne couvre pas son périmètre.
    # F4 : la couverture des *catégories de droits*, sur le même périmètre
    # réel. Nommer les empreintes ne suffit pas : une autorisation peut
    # couvrir chaque octet et ne pas couvrir la catégorie de droits sous
    # laquelle cet octet serait publié. Le verdict est un refus, jamais un
    # compteur — un invariant de sécurité incrémenté laisserait le rapport
    # présenter l'autorisation comme vérifiée.
    granted = frozenset(rights)
    missing_category: dict[str, list[str]] = {}
    for content_sha, candidate in ingest_rights_candidates:
        if candidate is None:
            raise ValueError(
                "SEMANTIC_VALIDATION failed: object "
                f"{content_sha!r} is routed to ingestion without a "
                "rights_category_candidate — an object whose rights category is "
                "unknown is never covered by any authorization"
            )
        if candidate not in _RIGHTS_VOCABULARY:
            raise ValueError(
                "SEMANTIC_VALIDATION failed: object "
                f"{content_sha!r} declares rights_category_candidate "
                f"{candidate!r}, which is not in the canonical vocabulary "
                f"{sorted(_RIGHTS_VOCABULARY)!r}"
            )
        if candidate not in granted:
            missing_category.setdefault(candidate, []).append(content_sha)
    if missing_category:
        detail = ", ".join(
            f"{category} ({len(shas)} object(s), e.g. {sorted(shas)[0]})"
            for category, shas in sorted(missing_category.items())
        )
        raise ValueError(
            "SEMANTIC_VALIDATION failed: the authorization grants rights "
            f"categories {sorted(granted)!r} but objects routed to ingestion "
            f"require {detail} — an authorization that does not cover every "
            "rights category in its perimeter authorizes none of it"
        )

    uncovered = ingest_content_sha256 - allowlist
    if uncovered:
        sample = sorted(uncovered)[:3]
        raise ValueError(
            "SEMANTIC_VALIDATION failed: the authority allowlist does not cover "
            f"{len(uncovered)} of the {len(ingest_content_sha256)} objects routed "
            f"to ingestion (e.g. {sample}) — an authorization that names only "
            "part of its perimeter authorizes none of it"
        )
    return allowlist


#: Racine **gouvernée** : dérivée exclusivement de l'emplacement de CE
#: fichier. Aucun override, par aucun moyen. C'est la remédiation du
#: constat F1 : tant que la racine était redirigeable par
#: ``NEXUS_REPOSITORY_ROOT``, « ancre canonique » ne voulait rien dire —
#: l'appelant choisissait le dépôt, donc l'ancre, donc les clés réputées
#: de confiance.
_GOVERNED_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]

#: Racine *de commodité*, celle-ci redirigeable, utilisée uniquement pour
#: les lectures qui ne fondent aucune confiance (rehearsal, tests). Elle
#: ne doit jamais servir à résoudre une ancre ou un registre en
#: production : ``_governed_path`` ignore délibérément cette variable.
_REPOSITORY_ROOT = Path(
    os.environ.get("NEXUS_REPOSITORY_ROOT", "")
    or _GOVERNED_REPOSITORY_ROOT
)

#: Chemins canoniques gouvernés (ADR-0035 § 4). Versionnés dans Git, donc
#: eux-mêmes soumis à revue humaine : changer une clé de confiance ou
#: révoquer une autorisation est un diff, pas un argument de ligne de
#: commande.
_GOVERNED_TRUST_ANCHOR_PATH = "governance/trust-anchors/review-binding-v1.json"
_GOVERNED_REVOCATIONS_PATH = "governance/trust-anchors/authorization-revocations-v1.json"

#: Version de schéma du registre de révocation. Un registre sans version
#: est refusé : sa forme pourrait changer sans que rien ne le signale.
_REVOCATIONS_PROTOCOL_VERSION = "NEXUS-AUTHORIZATION-REVOCATIONS-V1"

#: Marqueurs qui identifient la racine du dépôt Nexus. Versionnés, donc
#: présents dans tout checkout, et absents de tout ``site-packages``.
_GOVERNED_ROOT_MARKERS = ("AGENTS.md", "services/rag-pedago", "docs/adr")


def _governed_path(relative: str, *, label: str) -> Path:
    """Résout un chemin gouverné sous la racine dérivée du code.

    Trois refus, dans cet ordre :

    1. **Symlink** — sur le fichier final comme sur chaque composant sous
       la racine. Un lien est une redirection : autoriser l'un des deux
       rendrait le confinement décoratif, puisqu'un attaquant disposant
       d'un accès en écriture au dépôt pourrait faire pointer l'ancre
       ailleurs sans que le chemin change.
    2. **Évasion** — le chemin résolu doit rester sous la racine gouvernée
       résolue.
    3. **Non-identité** — le chemin résolu doit être *exactement* le
       chemin canonique attendu. Ce contrôle est redondant avec les deux
       précédents et le reste volontairement.

    Ne vérifie pas l'existence : l'absence est un refus, mais c'est à
    l'appelant de le formuler dans son propre vocabulaire.
    """
    root = _GOVERNED_REPOSITORY_ROOT
    # Garde de packaging : la racine est dérivée par remontée de quatre
    # niveaux depuis ce fichier. Cette dérivation n'est vraie que dans un
    # checkout du dépôt. Installé en wheel dans ``site-packages``, le même
    # calcul désignerait un répertoire arbitraire — et une ancre déposée
    # là ferait autorité. Le refus est donc explicite plutôt que
    # silencieux : ce gate est un outil de checkout, pas un artefact
    # déployable, et il doit le dire quand il ne l'est pas.
    for marker in _GOVERNED_ROOT_MARKERS:
        if not (root / marker).exists():
            raise ValueError(
                f"{label} failed: {root} does not look like the Nexus repository "
                f"checkout (missing {marker}). The governed root is derived from "
                "the location of this module and is only meaningful inside a "
                "checkout — refusing rather than trusting an arbitrary directory."
            )
    candidate = root.joinpath(relative)

    # Chaque composant intermédiaire, de la racine jusqu'au fichier.
    parts = Path(relative).parts
    walked = root
    for part in parts:
        walked = walked / part
        if walked.is_symlink():
            raise ValueError(
                f"{label} failed: {walked} is a symlink — a governed path is "
                "never allowed to redirect, on any of its components"
            )

    resolved_root = root.resolve()
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise ValueError(f"{label} failed: cannot resolve {candidate}: {exc}") from exc

    if not resolved.is_relative_to(resolved_root):
        raise ValueError(
            f"{label} failed: {resolved} escapes the governed root {resolved_root}"
        )
    expected = resolved_root.joinpath(relative)
    if resolved != expected:
        raise ValueError(
            f"{label} failed: resolved path {resolved} is not the canonical "
            f"governed path {expected}"
        )
    return candidate

#: Reviewers habilités, lus depuis la configuration versionnée d'ADR-0025 —
#: jamais une liste parallèle réinventée ici.
_TRUSTED_REVIEWERS_CONFIG = "scripts/github/trusted-reviewers.json"


def _load_trusted_reviewers(
    repository_root: Path, *, environment: str
) -> tuple[str, tuple[str, ...]]:
    """Relit l'allowlist de reviewers d'ADR-0025 depuis le dépôt.

    Lecture de fichier, jamais un import de ``scripts/`` : le gate reste
    hors ligne et sans dépendance de code croisée.

    F1, second point d'application. Ce fichier décide **qui compte comme
    relecteur habilité** : le laisser dépendre d'une racine redirigeable
    par ``NEXUS_REPOSITORY_ROOT`` ou par un paramètre d'appelant serait
    exactement le défaut fermé pour l'ancre de confiance, à un autre
    endroit. En production, il est donc lu au chemin gouverné, et lui
    seul."""
    if environment == "production":
        path = _governed_path(_TRUSTED_REVIEWERS_CONFIG, label="TRUSTED_REVIEWERS")
    else:
        path = repository_root / _TRUSTED_REVIEWERS_CONFIG
    if not path.is_file():
        raise ValueError(
            f"REVIEW_BINDING_VALIDATION failed: trusted reviewer configuration "
            f"is missing at {path}"
        )
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(
            "REVIEW_BINDING_VALIDATION failed: trusted reviewer configuration "
            "must be a JSON object"
        )
    repository = document.get("repository")
    reviewers = document.get("reviewers")
    if not isinstance(repository, str) or not repository.strip():
        raise ValueError(
            "REVIEW_BINDING_VALIDATION failed: trusted reviewer configuration "
            "declares no repository"
        )
    if not isinstance(reviewers, list) or not reviewers or any(
        not isinstance(item, str) or not item.strip() for item in reviewers
    ):
        raise ValueError(
            "REVIEW_BINDING_VALIDATION failed: trusted reviewer configuration "
            "declares no reviewers"
        )
    return repository, tuple(reviewers)


def _authority_review_binding_validation(
    artifact: ScopeAuthorizationArtifactV2,
    raw: bytes,
    *,
    binding_path: Path,
    trust_anchor_path: Path,
    environment: str,
    now: datetime,
    revoked_authorization_ids: frozenset[str],
    repository_root: Path,
) -> dict[str, str]:
    """REVIEW_BINDING_VALIDATION — ces octets ont-ils réellement été revus ?

    C'est la couche qui manquait. Les deux précédentes sont entièrement
    satisfaisables par un fichier fabriqué localement : un JSON canonique,
    sémantiquement cohérent, que personne n'a jamais relu. Sans preuve de
    revue, le gate final devenait vert sur une autorisation inventée.

    Le reçu ``ScopeAuthorizationReviewBindingV1`` (ADR-0035) transporte ici,
    **hors ligne et signé**, le résultat de la vérification GitHub effectuée
    par le vérificateur canonique d'ADR-0025. Ce module ne parle jamais au
    réseau et n'importe jamais ``rag-engine`` : seul le contrat partagé
    ``nexus_contracts.review_binding`` traverse la frontière (ADR-0001).

    Ordre des contrôles, délibéré : signature d'abord — un reçu non vérifié
    n'a le droit de rien affirmer, pas même sur lui-même — puis liaison aux
    octets exacts de l'autorisation, puis au challenge, puis à la
    révocation.
    """
    if artifact.canonical_bytes() != raw:
        raise ValueError(  # pragma: no cover - déjà garanti par la couche structurelle
            "REVIEW_BINDING_VALIDATION failed: artifact bytes are not canonical"
        )
    if not binding_path.is_file():
        raise ValueError(
            f"REVIEW_BINDING_VALIDATION failed: the sealed review binding receipt "
            f"does not exist at {binding_path} — an authorization whose review "
            "cannot be verified never turns the final gate green"
        )
    if not trust_anchor_path.is_file():
        raise ValueError(
            f"REVIEW_BINDING_VALIDATION failed: the trust anchor does not exist at "
            f"{trust_anchor_path} — an unanchored signature proves nothing"
        )

    try:
        trust_anchor = parse_trust_anchor(trust_anchor_path.read_bytes())
        binding = verify_review_binding(
            binding_path.read_bytes(),
            trust_anchor=trust_anchor,
            environment=environment,
            now=now,
        )
    except ReviewBindingError as exc:
        raise ValueError(f"REVIEW_BINDING_VALIDATION failed: {exc}") from exc

    repository, reviewers = _load_trusted_reviewers(
        repository_root, environment=environment
    )
    try:
        require_matches_authorization(
            binding,
            authorization_id=artifact.authorization_id,
            authorization_bytes=raw,
            authorization_git_blob_sha1=git_blob_sha1(raw),
            expected_repository=repository,
            accepted_reviewers=reviewers,
        )
        require_challenge_is_bound(binding)
    except ReviewBindingError as exc:
        raise ValueError(f"REVIEW_BINDING_VALIDATION failed: {exc}") from exc

    if binding.authorization_decision != artifact.decision:
        raise ValueError(
            f"REVIEW_BINDING_VALIDATION failed: the receipt seals decision "
            f"{binding.authorization_decision!r} while the authorization declares "
            f"{artifact.decision!r}"
        )
    if binding.authorization_id in revoked_authorization_ids:
        raise ValueError(
            f"REVIEW_BINDING_VALIDATION failed: authorization "
            f"{binding.authorization_id!r} is revoked — a sealed review never "
            "outlives the revocation of what it reviewed"
        )

    return {
        "authorization_id": artifact.authorization_id,
        "canonical_path": canonical_authorization_path(artifact.authorization_id),
        "authorization_digest": artifact.digest(),
        "artifact_blob_sha": git_blob_sha1(raw),
        "review_repository": binding.repository,
        "review_pull_request": str(binding.pull_request),
        "review_base_sha": binding.base_sha,
        "review_head_sha": binding.head_sha,
        "review_id": str(binding.review_id),
        "review_reviewer": binding.reviewer_login,
        "review_reviewer_permission": binding.reviewer_permission,
        "review_author": binding.author_login,
        "review_challenge_digest": binding.challenge_digest,
        "review_binding_environment": environment,
        "review_binding_expires_at": binding.expires_at.isoformat(),
        "review_binding_verifier": binding.verifier_version,
    }


def _parse_revocation_registry(raw: bytes, *, origin: Path) -> frozenset[str]:
    """Schéma strict et versionné du registre de révocation (F2).

    Un registre **gouverné vide** est valide : « aucune autorisation
    révoquée » est une affirmation légitime, et le fichier prouve que
    quelqu'un l'a affirmée. C'est l'*absence* de registre qui ne l'est
    pas — elle ne distingue pas « rien n'est révoqué » de « personne n'a
    regardé ».

    Un doublon est refusé plutôt qu'absorbé par le ``frozenset`` : deux
    lignes identiques signalent une édition concurrente mal fusionnée, et
    un registre de révocation dont on ignore l'historique d'édition ne
    mérite pas la confiance qu'on lui accorde.
    """
    try:
        document = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"REVOCATION_REGISTRY_INVALID: {origin} is not valid UTF-8: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"REVOCATION_REGISTRY_INVALID: {origin} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise ValueError(
            f"REVOCATION_REGISTRY_INVALID: {origin} must be a JSON object"
        )

    unexpected = set(document) - {"protocol_version", "revoked_authorization_ids"}
    if unexpected:
        raise ValueError(
            f"REVOCATION_REGISTRY_INVALID: {origin} carries unknown keys "
            f"{sorted(unexpected)!r} — a governed registry never smuggles fields "
            "past the schema"
        )

    protocol_version = document.get("protocol_version")
    if protocol_version != _REVOCATIONS_PROTOCOL_VERSION:
        raise ValueError(
            f"REVOCATION_REGISTRY_INVALID: {origin} declares protocol_version "
            f"{protocol_version!r}, expected {_REVOCATIONS_PROTOCOL_VERSION!r}"
        )

    revoked = document.get("revoked_authorization_ids")
    if not isinstance(revoked, list) or any(
        not isinstance(item, str) or not item.strip() for item in revoked
    ):
        raise ValueError(
            f"REVOCATION_REGISTRY_INVALID: {origin} must declare "
            "revoked_authorization_ids as a list of non-empty strings"
        )
    duplicates = sorted({item for item in revoked if revoked.count(item) > 1})
    if duplicates:
        raise ValueError(
            f"REVOCATION_REGISTRY_INVALID: {origin} repeats authorization ids "
            f"{duplicates!r} — a revocation registry is a set, and a duplicate "
            "signals an unreviewed merge"
        )
    return frozenset(revoked)


def _load_revoked_authorization_ids(
    path: Path | None, *, environment: str
) -> tuple[frozenset[str], bool]:
    """Charge le registre de révocation et dit **si** il a été vérifié.

    En ``production`` le chemin est celui, canonique et gouverné, dérivé
    du code : ni argument CLI, ni variable d'environnement ne peuvent le
    déplacer, et son absence est un refus. En ``rehearsal`` une fixture
    peut être fournie ; son absence rend simplement le second membre du
    tuple faux, ce que le rapport publie.
    """
    if environment == "production":
        governed = _governed_path(
            _GOVERNED_REVOCATIONS_PATH, label="REVOCATION_REGISTRY"
        )
        if path is not None and path != governed:
            raise ValueError(
                "REVOCATION_REGISTRY_ARGUMENT_FORBIDDEN: --authority-revocations "
                f"is never honoured in production (got {path}). The registry is "
                f"read from the governed path {governed} only."
            )
        if not governed.is_file():
            raise ValueError(
                f"REVOCATION_REGISTRY_MISSING: {governed} does not exist. An "
                "absent registry is not an empty registry — it proves nobody "
                "checked, so the production gate refuses rather than assumes."
            )
        return _parse_revocation_registry(governed.read_bytes(), origin=governed), True

    if path is None:
        return frozenset(), False
    if not path.is_file():
        raise ValueError(
            f"REVOCATION_REGISTRY_MISSING: authority revocation registry does "
            f"not exist: {path}"
        )
    return _parse_revocation_registry(path.read_bytes(), origin=path), True


def _resolve_trust_anchor_path(
    supplied: Path | None, *, environment: str
) -> Path:
    """Chemin de l'ancre de confiance — gouverné en production (F1).

    En production, ``--authority-trust-anchor`` n'est pas ignoré : il est
    **refusé**. Ignorer silencieusement un argument laisserait un
    opérateur croire qu'il a désigné une ancre alors que le gate en lit
    une autre ; le refus explicite supprime cette ambiguïté.

    Il n'existe aucun chemin de code par lequel une ancre de production
    puisse venir d'ailleurs. En particulier, un fichier arbitraire qui
    déclarerait ``environment="production"`` dans ses clés ne confère
    aucune autorité : cette auto-déclaration n'est jamais lue, parce que
    le fichier n'est jamais ouvert.
    """
    if environment == "production":
        governed = _governed_path(
            _GOVERNED_TRUST_ANCHOR_PATH, label="TRUST_ANCHOR"
        )
        if supplied is not None and supplied != governed:
            raise ValueError(
                "TRUST_ANCHOR_ARGUMENT_FORBIDDEN: --authority-trust-anchor is "
                f"never honoured in production (got {supplied}). The anchor is "
                f"read from the governed path {governed} only — a key that "
                "declares itself trusted is not a trusted key."
            )
        if not governed.is_file():
            raise ValueError(
                f"TRUST_ANCHOR_MISSING: the governed production trust anchor "
                f"{governed} does not exist — an unanchored signature proves "
                "nothing, so the production gate refuses."
            )
        return governed

    if supplied is None:
        raise ValueError(
            "TRUST_ANCHOR_MISSING: --authority-trust-anchor is required in "
            "rehearsal mode"
        )
    return supplied


def _load_authority_evidence(
    authority_path: Path,
    manifest_sha256: str,
    *,
    ingest_content_sha256: frozenset[str],
    ingest_rights_candidates: tuple[tuple[str, str | None], ...],
    now: datetime,
    revocations_path: Path | None,
    binding_path: Path,
    trust_anchor_path: Path | None,
    environment: str,
    repository_root: Path,
) -> tuple[frozenset[str], dict[str, str], bool]:
    """H2-F Défaut 5 : les trois couches, dans cet ordre, toutes exécutées.

    Une validation Pydantic réussie n'est que la première. Aucune n'est
    optionnelle : le retour porte l'allowlist vérifiée, la liaison de
    revue scellée **et** le fait que la révocation ait été réellement
    vérifiée — pour que le rapport publie ce sur quoi il s'est appuyé
    plutôt qu'un simple booléen.
    """
    # Ordre délibéré : l'ancre d'abord. La confiance précède la
    # révocation — un registre lu sous une ancre non résolue ne dit rien.
    trust_anchor_path = _resolve_trust_anchor_path(
        trust_anchor_path, environment=environment
    )
    revoked, revocations_checked = _load_revoked_authorization_ids(
        revocations_path, environment=environment
    )
    artifact, raw = _authority_structural_validation(authority_path)
    allowlist = _authority_semantic_validation(
        artifact,
        manifest_sha256=manifest_sha256,
        ingest_content_sha256=ingest_content_sha256,
        ingest_rights_candidates=ingest_rights_candidates,
        now=now,
        revoked_authorization_ids=revoked,
    )
    binding = _authority_review_binding_validation(
        artifact,
        raw,
        binding_path=binding_path,
        trust_anchor_path=trust_anchor_path,
        environment=environment,
        now=now,
        revoked_authorization_ids=revoked,
        repository_root=repository_root,
    )
    return allowlist, binding, revocations_checked


def generate_coverage_report(
    catalog_path: Path,
    rights_path: Path | None = None,
    pii_path: Path | None = None,
    routing_path: Path | None = None,
    golden_path: Path | None = None,
    manifest_path: Path | None = None,
    authority_path: Path | None = None,
    authority_revocations_path: Path | None = None,
    authority_review_binding_path: Path | None = None,
    authority_trust_anchor_path: Path | None = None,
    authority_environment: str = "production",
    authority_now: datetime | None = None,
    repository_root: Path | None = None,
    expected_total: int = 2584,
    expected_manifest_sha256: str | None = None,
) -> CoverageReport:
    """Generate H2-B coverage report.

    H2-F Défaut 1: If manifest_path is provided, the report will verify
    exact binding between the sealed manifest file and the catalog entries.

    H2-F Défaut 5: If authority_path is provided, the report will verify
    that each INGEST item's content_sha256 is in the LOT41A authority
    evidence's allowed_content_sha256 list. Without authority_path, any
    authority=PASS in the catalog is flagged as self-declared.
    """
    catalog = load_catalog(catalog_path)
    if catalog.get("catalog_kind") != "REAL_SEALED_CORPUS":
        raise ValueError("final gate requires a real sealed corpus catalog")
    manifest_sha256 = catalog.get("manifest_sha256")
    if not isinstance(manifest_sha256, str) or re.fullmatch(
        r"[0-9a-f]{64}", manifest_sha256
    ) is None:
        raise ValueError("catalog manifest SHA256 is invalid")
    if (
        expected_manifest_sha256 is not None
        and manifest_sha256 != expected_manifest_sha256
    ):
        raise ValueError("catalog manifest SHA256 mismatch")
    # P1 PRRT_kwDOTEIbbs6X3cnO: manifest is REQUIRED for the final gate
    # H2-F Défaut 1: Verify exact binding between manifest file and catalog
    if manifest_path is None or not manifest_path.is_file():
        raise ValueError(
            "H2-F Défaut 1: sealed manifest file is required for the final gate "
            "(cannot produce coverage_complete=True without verifying manifest bytes)"
        )
    _verify_manifest_binding(manifest_path, catalog)
    if golden_path is None or not golden_path.is_file():
        raise ValueError("golden specification is required for the final gate")
    if rights_path is None or not rights_path.is_file():
        raise ValueError("rights evidence is required for the final gate")
    if pii_path is None or not pii_path.is_file():
        raise ValueError("PII evidence is required for the final gate")
    if routing_path is None or not routing_path.is_file():
        raise ValueError("routing policy is required for the final gate")

    # Git info
    git_commit = _get_git_commit()
    git_branch = _get_git_branch()

    # Corpus totals
    actual_total = catalog.get("physical_object_count")
    if (
        isinstance(actual_total, bool)
        or not isinstance(actual_total, int)
        or actual_total < 0
    ):
        raise ValueError("catalog physical_object_count is invalid")
    totals = catalog.get("disposition_counts", {})
    if not isinstance(totals, dict) or not all(
        isinstance(key, str)
        and key
        and not isinstance(value, bool)
        and isinstance(value, int)
        and value >= 0
        for key, value in totals.items()
    ):
        raise ValueError("catalog disposition counts are invalid")
    totals_sum = sum(totals.values())

    # Verification
    sum_equals_total = totals_sum == actual_total
    unclassified = catalog.get("unclassified")
    multiple_primary = catalog.get("multiple_primary_disposition")
    if (
        isinstance(unclassified, bool)
        or not isinstance(unclassified, int)
        or unclassified < 0
        or isinstance(multiple_primary, bool)
        or not isinstance(multiple_primary, int)
        or multiple_primary < 0
    ):
        raise ValueError("catalog classification counters are invalid")
    zero_overlap = (
        catalog.get("verification_passed") is True and multiple_primary == 0
    )
    zero_gap = sum_equals_total and unclassified == 0
    corpus_match = actual_total == expected_total

    safety_invariants = {
        "INGEST_WITHOUT_RIGHTS_CLEARANCE": 0,
        "INGEST_WITHOUT_PII_CLEARANCE": 0,
        "INGEST_WITHOUT_CURRENTNESS_CLEARANCE": 0,
        "INGEST_WITH_UNSUPPORTED_FORMAT": 0,
        "INGEST_WITHOUT_PROVENANCE": 0,
        "INGEST_WITHOUT_CONTENT_SHA": 0,
        "INGEST_WITHOUT_AUTHORITY": 0,
        "INGEST_WITH_SELF_DECLARED_AUTHORITY": 0,
        "INGEST_WITHOUT_ATTRIBUTION_METADATA": 0,
    }
    physical_objects = catalog.get("physical_objects")
    if not isinstance(physical_objects, list):
        raise ValueError("real catalog must include physical objects")
    if len(physical_objects) != actual_total:
        raise ValueError("physical object list does not match reported total")
    measured_dispositions: dict[str, int] = {}
    for item in physical_objects:
        if not isinstance(item, dict):
            raise ValueError("real catalog physical object must be a mapping")
        disposition = item.get("disposition")
        if not isinstance(disposition, str) or not disposition:
            raise ValueError("real catalog physical object disposition is invalid")
        measured_dispositions[disposition] = (
            measured_dispositions.get(disposition, 0) + 1
        )
    if {
        key: value for key, value in totals.items() if value != 0
    } != measured_dispositions:
        raise ValueError("disposition_counts do not match physical objects")

    rights_registry = _load_yaml_mapping(rights_path, label="rights registry")
    routing_config = _load_yaml_mapping(routing_path, label="routing policy")
    pii_evidence = load_catalog(pii_path)
    if not isinstance(pii_evidence, dict):
        raise ValueError("PII evidence must be a mapping")
    verify_catalog_evidence_bindings(
        catalog,
        routing_config,
        rights_registry,
        pii_evidence,
    )

    # H2-F Défaut 5 : les trois couches de validation d'autorité. La
    # complétude de l'allowlist est vérifiée sur le périmètre RÉEL (tous
    # les objets routés vers l'ingestion), jamais sur un échantillon —
    # d'où la collecte préalable de leurs empreintes.
    ingest_content_sha256 = frozenset(
        str(item.get("content_sha256"))
        for item in physical_objects
        if isinstance(item, dict)
        and item.get("disposition") == "INGEST"
        and isinstance(item.get("content_sha256"), str)
    )
    # F4 : les catégories de droits réellement portées par les objets
    # routés vers l'ingestion. Collectées sur **tous** ces objets, pas sur
    # un échantillon, et gardées avec l'identité de l'objet pour que le
    # refus puisse nommer le fautif. Deux objets de même contenu mais de
    # catégories différentes produisent donc deux entrées : les deux
    # catégories devront être couvertes.
    ingest_rights_candidates: tuple[tuple[str, str | None], ...] = tuple(
        (
            str(item.get("content_sha256")),
            item.get("rights_category_candidate")
            if isinstance(item.get("rights_category_candidate"), str)
            else None,
        )
        for item in physical_objects
        if isinstance(item, dict) and item.get("disposition") == "INGEST"
    )
    authority_allowlist: frozenset[str] | None = None
    authority_binding: dict[str, str] = {}
    # Fail-closed par défaut : sans artefact d'autorité, aucune révocation
    # n'a été vérifiée, et le rapport doit le dire.
    authority_revocations_checked: bool = False
    if authority_environment not in ("production", "rehearsal"):
        raise ValueError(
            f"authority_environment must be 'production' or 'rehearsal', got "
            f"{authority_environment!r}"
        )
    if authority_path is not None:
        # ADR-0035 : aucune de ces trois preuves n'est optionnelle. Rendre
        # le reçu ou l'ancre facultatifs reviendrait à laisser le gate
        # vert sur une autorisation que personne n'a relue — le défaut
        # exact que ce lot ferme.
        if authority_review_binding_path is None:
            raise ValueError(
                "REVIEW_BINDING_VALIDATION failed: an authority artifact requires "
                "a sealed review binding receipt — a locally authored "
                "authorization is not evidence of human review"
            )
        # L'ancre n'est plus un argument obligatoire : en production elle
        # est gouvernée (F1) et fournir l'argument est un refus ; en
        # rehearsal ``_resolve_trust_anchor_path`` exige la fixture.
        authority_allowlist, authority_binding, authority_revocations_checked = _load_authority_evidence(
            authority_path,
            manifest_sha256,
            ingest_content_sha256=ingest_content_sha256,
            ingest_rights_candidates=ingest_rights_candidates,
            now=authority_now or datetime.now(UTC),
            revocations_path=authority_revocations_path,
            binding_path=authority_review_binding_path,
            trust_anchor_path=authority_trust_anchor_path,
            # Le mode ``rehearsal`` exerce les clés de test et ne peut jamais
            # produire un verdict final vert (cf. ``coverage_complete``).
            environment="test" if authority_environment == "rehearsal" else "production",
            repository_root=repository_root or _REPOSITORY_ROOT,
        )

    blocked_ingest_candidates = 0
    mandatory_gate_blockers: dict[str, int] = {}
    for item in physical_objects:
        if not isinstance(item, dict):
            continue
        gates = item.get("gate_statuses")
        if (
            item.get("base_disposition") == "INGEST"
            and item.get("disposition") != "INGEST"
        ):
            blocked_ingest_candidates += 1
            if isinstance(gates, dict):
                for gate_name, status in gates.items():
                    if status != "PASS":
                        mandatory_gate_blockers[gate_name] = (
                            mandatory_gate_blockers.get(gate_name, 0) + 1
                        )
        if item.get("disposition") != "INGEST":
            continue
        if not isinstance(gates, dict) or gates.get("rights") != "PASS":
            safety_invariants["INGEST_WITHOUT_RIGHTS_CLEARANCE"] += 1
        if not isinstance(gates, dict) or gates.get("pii") != "PASS":
            safety_invariants["INGEST_WITHOUT_PII_CLEARANCE"] += 1
        if item.get("currentness") != "actuel":
            safety_invariants["INGEST_WITHOUT_CURRENTNESS_CLEARANCE"] += 1
        path_value = item.get("path")
        if not isinstance(path_value, str) or not path_value.lower().endswith(".pdf"):
            safety_invariants["INGEST_WITH_UNSUPPORTED_FORMAT"] += 1
        if item.get("provenance_status") != "VERIFIED":
            safety_invariants["INGEST_WITHOUT_PROVENANCE"] += 1
        content_sha256 = item.get("content_sha256")
        if not isinstance(content_sha256, str) or re.fullmatch(
            r"[0-9a-f]{64}", content_sha256
        ) is None:
            safety_invariants["INGEST_WITHOUT_CONTENT_SHA"] += 1
        # H2-F Défaut 5: authority gate verification
        # The catalog compiler cannot produce authority=PASS (always BLOCKED_NOT_CLEARED).
        # authority=PASS can only be accepted if:
        # 1. External LOT41A authority evidence is provided
        # 2. The content_sha256 is in the evidence's allowed_content_sha256 list
        if not isinstance(gates, dict) or gates.get("authority") != "PASS":
            safety_invariants["INGEST_WITHOUT_AUTHORITY"] += 1
        elif authority_allowlist is None:
            # No authority evidence provided - any authority=PASS is self-declared
            safety_invariants["INGEST_WITH_SELF_DECLARED_AUTHORITY"] += 1
        elif len(authority_allowlist) == 0:
            # V1 authority (no content allowlist) - cannot verify individual items
            safety_invariants["INGEST_WITH_SELF_DECLARED_AUTHORITY"] += 1
        elif content_sha256 not in authority_allowlist:
            # Content not in authority allowlist - authority claim is invalid
            safety_invariants["INGEST_WITHOUT_AUTHORITY"] += 1
        # else: authority=PASS is backed by external evidence - OK
        attribution = item.get("attribution_metadata")
        if not isinstance(attribution, dict) or not all(
            isinstance(attribution.get(field_name), str)
            and bool(attribution.get(field_name))
            for field_name in ("source", "source_url")
        ):
            safety_invariants["INGEST_WITHOUT_ATTRIBUTION_METADATA"] += 1

    # Input files
    input_files = {
        "catalog": _file_sha256(catalog_path),
        "pii": _file_sha256(pii_path),
        "rights": _file_sha256(rights_path),
        "routing": _file_sha256(routing_path),
    }
    if authority_path is not None:
        input_files["authority"] = _file_sha256(authority_path)
        # Publier la liaison recalculée plutôt qu'un booléen : le chemin
        # canonique, le digest et le SHA-1 de blob Git sont ce par quoi une
        # revue GitHub désigne ces octets exacts.
        input_files.update(
            {f"authority_{key}": value for key, value in authority_binding.items()}
        )
    if authority_revocations_path is not None:
        input_files["authority_revocations"] = _file_sha256(authority_revocations_path)

    # Rights gate
    rights_gate_status = (
        "PASS"
        if safety_invariants["INGEST_WITHOUT_RIGHTS_CLEARANCE"] == 0
        else "BLOCKED_INGEST_WITHOUT_CLEARANCE"
    )
    pii_gate_status = (
        "PASS"
        if safety_invariants["INGEST_WITHOUT_PII_CLEARANCE"] == 0
        else "BLOCKED_INGEST_WITHOUT_CLEARANCE"
    )

    # Currentness gate (derived from catalog)
    if safety_invariants["INGEST_WITHOUT_CURRENTNESS_CLEARANCE"] == 0:
        currentness_gate_status = "PASS"
    else:
        currentness_gate_status = "BLOCKED_INGEST_WITHOUT_CURRENTNESS"

    # Format gate (derived from catalog)
    unsupported = totals.get("UNSUPPORTED", 0)
    if safety_invariants["INGEST_WITH_UNSUPPORTED_FORMAT"] == 0:
        format_gate_status = f"PASS_WITH_{unsupported}_UNSUPPORTED"
    else:
        format_gate_status = f"CHECK_{unsupported}_UNSUPPORTED"

    # Golden corpus — the final gate executes the validator on this exact catalog.
    golden = load_spec(golden_path)
    golden_report = validate_golden_corpus(
        golden,
        catalog,
        golden_path,
        catalog_path,
    )
    golden_total = golden_report.total_controls
    golden_passed = golden_report.passed_controls
    golden_failed = golden_report.failed_controls
    golden_pass = golden_report.validation_passed
    golden_status = "PASS" if golden_pass else "FAIL"
    input_files["golden"] = _file_sha256(golden_path)

    decision_coverage_complete = (
        sum_equals_total
        and zero_overlap
        and zero_gap
        and corpus_match
    )
    # ADR-0035 : la liaison de revue scellée est une condition du verdict
    # final, au même titre que le manifest, les droits, la PII et le golden.
    # Le mode ``rehearsal`` exerce des clés de test : il vérifie donc toute
    # la chaîne mais ne peut, par construction, jamais rendre un verdict
    # final vert — une répétition ne publie rien.
    authority_review_binding_verified = bool(authority_binding)
    final_mode = authority_environment == "production"
    h2_coverage_gate_pass = (
        decision_coverage_complete
        and golden_pass
        and rights_gate_status == "PASS"
        and pii_gate_status == "PASS"
        and authority_review_binding_verified
        # F2 : sans preuve de non-révocation, le gate final reste faux.
        and authority_revocations_checked
        and final_mode
        and all(value == 0 for value in safety_invariants.values())
    )

    return CoverageReport(
        report_id=f"h2b_coverage_{git_commit}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        generated_at=datetime.now(UTC).isoformat(),
        git_commit=git_commit,
        git_branch=git_branch,
        real_corpus_catalog_source=True,
        synthetic_catalog_used_for_final_gate=False,
        manifest_sha256=manifest_sha256,
        corpus_total_expected=expected_total,
        corpus_total_actual=actual_total,
        corpus_match=corpus_match,
        totals=totals,
        totals_sum=totals_sum,
        sum_equals_total=sum_equals_total,
        zero_overlap=zero_overlap,
        zero_gap=zero_gap,
        decision_coverage_complete=decision_coverage_complete,
        coverage_complete=h2_coverage_gate_pass,
        authority_environment=authority_environment,
        authority_review_binding_verified=authority_review_binding_verified,
        authority_revocations_checked=authority_revocations_checked,
        unclassified=unclassified,
        multiple_primary_disposition=multiple_primary,
        safety_invariants=safety_invariants,
        blocked_ingest_candidates=blocked_ingest_candidates,
        mandatory_gate_blockers=dict(sorted(mandatory_gate_blockers.items())),
        content_artifact_count=catalog.get("content_artifact_count", 0),
        eduscol_unique_artifacts=catalog.get("eduscol_unique_artifacts", 0),
        eduscol_placement_count=catalog.get("eduscol_placement_count", 0),
        eduscol_placements_classified=catalog.get(
            "eduscol_placements_classified", 0
        ),
        eduscol_placements_unclassified=catalog.get(
            "eduscol_placements_unclassified", 0
        ),
        multi_placement_artifacts=catalog.get("multi_placement_artifacts", 0),
        rights_gate_status=rights_gate_status,
        pii_gate_status=pii_gate_status,
        rights_evidence_bound=True,
        pii_evidence_bound=True,
        currentness_gate_status=currentness_gate_status,
        format_gate_status=format_gate_status,
        golden_controls_total=golden_total,
        golden_controls_passed=golden_passed,
        golden_controls_failed=golden_failed,
        golden_validation_status=golden_status,
        golden_validation_pass=golden_pass,
        h2_coverage_gate_pass=h2_coverage_gate_pass,
        input_files=input_files,
    )


def render_markdown(report: CoverageReport) -> str:
    """Render coverage report as Markdown."""
    lines = [
        "# H2-B CORPUS COVERAGE REPORT",
        "",
        f"**Report ID**: `{report.report_id}`",
        f"**Generated**: {report.generated_at}",
        f"**Git Commit**: `{report.git_commit}`",
        f"**Git Branch**: `{report.git_branch}`",
        "",
        f"REAL_CORPUS_CATALOG_SOURCE={'true' if report.real_corpus_catalog_source else 'false'}",
        "SYNTHETIC_CATALOG_USED_FOR_FINAL_GATE="
        f"{'true' if report.synthetic_catalog_used_for_final_gate else 'false'}",
        f"CORPUS_MANIFEST_SHA256={report.manifest_sha256}",
        "",
        "---",
        "",
        "## 1. CORPUS TOTALS",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Expected total | {report.corpus_total_expected:,} |",
        f"| Actual total | {report.corpus_total_actual:,} |",
        f"| **Match** | **{'YES' if report.corpus_match else 'NO'}** |",
        "",
        "---",
        "",
        "## 2. DISPOSITION BREAKDOWN",
        "",
        "| Disposition | Count | Percentage |",
        "|-------------|-------|------------|",
    ]

    total = report.totals_sum or 1  # Avoid division by zero
    for disposition, count in sorted(report.totals.items()):
        pct = count / total * 100
        lines.append(f"| {disposition} | {count:,} | {pct:.1f}% |")

    lines.extend([
        f"| **SUM** | **{report.totals_sum:,}** | **100.0%** |",
        "",
        "---",
        "",
        "## 3. COVERAGE VERIFICATION",
        "",
        "| Check | Status |",
        "|-------|--------|",
        f"| SUM(dispositions) = corpus_total | **{'PASS' if report.sum_equals_total else 'FAIL'}** |",
        f"| Zero overlap (no duplicate SHA256) | **{'PASS' if report.zero_overlap else 'FAIL'}** |",
        f"| Zero gap (all objects assigned) | **{'PASS' if report.zero_gap else 'FAIL'}** |",
        f"| Corpus total matches expected | **{'PASS' if report.corpus_match else 'FAIL'}** |",
        f"| Unclassified objects | **{report.unclassified}** |",
        f"| Multiple primary dispositions | **{report.multiple_primary_disposition}** |",
        f"| Blocked ingest candidates | **{report.blocked_ingest_candidates}** |",
        f"| Decision coverage complete | **{'PASS' if report.decision_coverage_complete else 'FAIL'}** |",
        f"| Golden validation | **{'PASS' if report.golden_validation_pass else 'FAIL'}** |",
        "| Authority review binding (ADR-0035) | "
        f"**{'PASS' if report.authority_review_binding_verified else 'FAIL'}** |",
        "| Authority revocations checked (F2) | "
        f"**{'PASS' if report.authority_revocations_checked else 'FAIL'}** |",
        f"| Authority evidence mode | **{report.authority_environment}** |",
        f"| H2 coverage gate | **{'PASS' if report.h2_coverage_gate_pass else 'FAIL'}** |",
        "",
        f"BLOCKED_INGEST_CANDIDATES={report.blocked_ingest_candidates}",
        "DECISION_COVERAGE_COMPLETE="
        f"{'true' if report.decision_coverage_complete else 'false'}",
        "GOLDEN_VALIDATION_PASS="
        f"{'true' if report.golden_validation_pass else 'false'}",
        "AUTHORITY_REVIEW_BINDING_VERIFIED="
        f"{'true' if report.authority_review_binding_verified else 'false'}",
        "AUTHORITY_REVOCATIONS_CHECKED="
        f"{'true' if report.authority_revocations_checked else 'false'}",
        f"AUTHORITY_EVIDENCE_MODE={report.authority_environment}",
        "H2_COVERAGE_GATE_PASS="
        f"{'true' if report.h2_coverage_gate_pass else 'false'}",
        "",
        f"**COVERAGE_COMPLETE = {'TRUE' if report.coverage_complete else 'FALSE'}**",
        "",
        "---",
        "",
        "## 4. INGEST SAFETY INVARIANTS",
        "",
        "| Invariant | Count |",
        "|-----------|-------|",
    ])

    for invariant, count in report.safety_invariants.items():
        lines.append(f"| {invariant} | {count} |")

    lines.extend([
        "",
        "---",
        "",
        "## 5. GATE STATUSES",
        "",
        "| Gate | Status |",
        "|------|--------|",
        f"| Rights evidence | `{report.rights_gate_status}` |",
        f"| PII content scan | `{report.pii_gate_status}` |",
        f"| Rights evidence bound | `{'PASS' if report.rights_evidence_bound else 'FAIL'}` |",
        f"| PII evidence bound | `{'PASS' if report.pii_evidence_bound else 'FAIL'}` |",
        f"| Currentness classification | `{report.currentness_gate_status}` |",
        f"| Format support | `{report.format_gate_status}` |",
        "",
        "---",
        "",
        "## 6. GOLDEN CORPUS VALIDATION",
        "",
        f"- Total controls: {report.golden_controls_total}",
        f"- Passed controls: {report.golden_controls_passed}",
        f"- Failed controls: {report.golden_controls_failed}",
        f"- Status: `{report.golden_validation_status}`",
        "",
        "---",
        "",
        "## 7. INPUT FILE HASHES",
        "",
        "| File | SHA256 |",
        "|------|--------|",
    ])

    for name, sha in sorted(report.input_files.items()):
        lines.append(f"| {name} | `{sha}` |")

    lines.extend([
        "",
        "---",
        "",
        "## 8. BLOCKING ITEMS FOR GO-LIVE",
        "",
    ])

    blocking = []
    if report.rights_gate_status != "PASS":
        blocking.append(f"- Rights gate: `{report.rights_gate_status}`")
    if "BLOCKED" in report.pii_gate_status:
        blocking.append(f"- PII gate: `{report.pii_gate_status}`")
    if "INCOMPLETE" in report.currentness_gate_status:
        blocking.append(f"- Currentness gate: `{report.currentness_gate_status}`")
    if not report.corpus_match:
        blocking.append(f"- Corpus total mismatch: {report.corpus_total_actual} vs {report.corpus_total_expected}")
    if report.blocked_ingest_candidates:
        blocking.append(
            f"- Blocked ingest candidates: {report.blocked_ingest_candidates} "
            f"({report.mandatory_gate_blockers})"
        )
    for invariant, count in report.safety_invariants.items():
        if count:
            blocking.append(f"- {invariant}: {count}")
    if not report.golden_validation_pass:
        blocking.append(
            f"- Golden validation: {report.golden_controls_failed} failed controls"
        )

    if blocking:
        lines.extend(blocking)
    else:
        lines.append("None — all gates pass.")

    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate H2-B coverage report."
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        required=True,
        help="Path to corpus disposition catalog (JSON)",
    )
    parser.add_argument(
        "--rights",
        type=Path,
        required=True,
        help="Path to rights evidence registry (YAML)",
    )
    parser.add_argument(
        "--pii",
        type=Path,
        required=True,
        help="Path to sealed PII evidence (JSON)",
    )
    parser.add_argument(
        "--routing",
        type=Path,
        required=True,
        help="Path to independent corpus routing policy (YAML)",
    )
    parser.add_argument(
        "--golden",
        type=Path,
        help="Path to golden corpus specification (YAML)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="H2-F Défaut 1: Path to sealed SHA256SUMS.txt for exact binding verification",
    )
    parser.add_argument(
        "--authority",
        type=Path,
        help="H2-F Défaut 5: Path to LOT41A authority evidence (JSON)",
    )
    parser.add_argument(
        "--authority-review-binding",
        type=Path,
        help=(
            "ADR-0035 : reçu de liaison de revue scellé (JSON signé) qui prouve "
            "hors ligne que l'autorisation a été approuvée sur GitHub par un "
            "relecteur habilité, distinct de son auteur, au HEAD exact"
        ),
    )
    parser.add_argument(
        "--authority-trust-anchor",
        type=Path,
        help=(
            "ADR-0035 : ancre de confiance déclarant les clés publiques "
            "reconnues. **Rehearsal uniquement.** En production l'ancre est "
            "lue au chemin gouverné governance/trust-anchors/"
            "review-binding-v1.json et fournir cet argument est un refus."
        ),
    )
    parser.add_argument(
        "--authority-environment",
        choices=("production", "rehearsal"),
        default="production",
        help=(
            "'production' (défaut) exige une clé de production et peut rendre "
            "coverage_complete=True ; 'rehearsal' exerce les clés de test et ne "
            "peut jamais produire un verdict final vert"
        ),
    )
    parser.add_argument(
        "--authority-revocations",
        type=Path,
        help=(
            "Registre de révocation scellé (JSON versionné). **Rehearsal "
            "uniquement** : en production il est lu au chemin gouverné "
            "governance/trust-anchors/authorization-revocations-v1.json, son "
            "absence est un refus, et fournir cet argument est un refus. En "
            "rehearsal, son absence laisse AUTHORITY_REVOCATIONS_CHECKED=false."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output path for Markdown report",
    )
    parser.add_argument(
        "--expected-total",
        type=int,
        default=2584,
        help="Expected corpus total",
    )
    parser.add_argument(
        "--expected-manifest-sha256",
        help="Expected sealed SHA256SUMS digest",
    )
    args = parser.parse_args()

    report = generate_coverage_report(
        catalog_path=args.catalog,
        rights_path=args.rights,
        pii_path=args.pii,
        routing_path=args.routing,
        golden_path=args.golden,
        manifest_path=args.manifest,
        authority_path=args.authority,
        authority_revocations_path=args.authority_revocations,
        authority_review_binding_path=args.authority_review_binding,
        authority_trust_anchor_path=args.authority_trust_anchor,
        authority_environment=args.authority_environment,
        expected_total=args.expected_total,
        expected_manifest_sha256=args.expected_manifest_sha256,
    )

    markdown = render_markdown(report)
    print(markdown)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
        print(f"\nReport written to: {args.output}")

    return 0 if report.coverage_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
