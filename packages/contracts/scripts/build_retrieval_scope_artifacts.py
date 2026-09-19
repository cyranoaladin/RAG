#!/usr/bin/env python3
"""Émettre, DANS ce dépôt, les scopes de retrieval qu'une release-sujet exige.

**Pourquoi ce producteur existe.** Les trente `RetrievalScopeArtifactV2`
packagés dans `nexus_contracts` n'ont jamais eu d'émetteur reproductible
in-repo : ils ont été écrits à la main, puis épinglés au registre fermé par
leur digest. Tant que la release qu'ils désignaient ne bougeait pas, cela
suffisait. Dès qu'une release-sujet est régénérée, la garde de démarrage du
moteur — sélection exacte par `(collection, subject_sha256)`, zéro ou plusieurs
correspondances valant refus — n'a plus aucun scope à sélectionner, et
personne ne peut prouver comment les remplaçants ont été fabriqués.

**Ce que ce producteur dérive, et ce qu'il refuse de dériver.** Une release dit
CE QUI EXISTE ; un scope dit QUI PEUT VOIR QUOI. Les deux ne se déduisent pas
l'un de l'autre, et l'émetteur tient donc deux familles d'entrées séparées :

  * la RELEASE-SUJET (`--subject-release`), vérifiée contre le digest qu'on lui
    nomme, d'où l'émetteur ne tire QUE `source_sha256` — le digest du manifeste
    de subject de chaque collection ;
  * l'AUTORITÉ DE POLITIQUE (`--policy-authority`), vérifiée elle aussi contre
    son digest, qui NOMME pour chaque collection le scope déjà gouverné dont la
    politique est reconduite. `tenant`, `niveau`, `voie`, `matiere`,
    `statut_enseignement`, `candidat`, `audiences`, `visibility`, `rights`,
    `school_year`, `programme_version` et `collection` sont lus dans ce scope
    source, jamais déduits de la release, jamais inventés ici.

L'émetteur croise ensuite les deux : les dimensions que les placements du
subject déclarent doivent coïncider avec celles de la politique nommée. Une
divergence est un REFUS — jamais un élargissement silencieux de droits.

**Immuabilité.** Aucun artefact existant n'est réécrit : ADR-0045 exige qu'une
nouvelle version de subject reçoive un nouveau `scope_id` ET un nouveau digest.
L'émetteur refuse tout identifiant déjà détenu par le registre historique, et
tout identifiant qui ne suit pas la convention de succession `_v<N>`.

**Déterminisme.** Aucun horodatage, aucun chemin de poste de travail, aucun
CWD, aucun hostname dans les octets produits : deux dérivations des mêmes
entrées rendent les mêmes octets, faute de quoi rien n'est prouvable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, NamedTuple, Sequence

import yaml

from nexus_contracts.scope import (
    RetrievalScopeArtifactV2,
    load_retrieval_scope_artifact,
)
from nexus_contracts.scope import _RETRIEVAL_SCOPE_RESOURCES as HISTORICAL_REGISTRY

#: Identifiant de l'autorité de politique que cet émetteur sait lire.
POLICY_AUTHORITY_KIND = "MULTILEVEL_RETRIEVAL_SCOPE_POLICY_V1"

#: Les douze dimensions d'autorisation. Aucune n'est dérivée de la release.
AUTHORIZATION_DIMENSIONS: tuple[str, ...] = (
    "collection",
    "tenant",
    "niveau",
    "voie",
    "matiere",
    "statut_enseignement",
    "candidat",
    "audiences",
    "visibility",
    "rights",
    "school_year",
    "programme_version",
)

#: Les dimensions qu'un placement de subject déclare, et que l'émetteur peut
#: donc confronter à la politique. `audiences` et `rights` n'ont pas de
#: contrepartie dans la release : ils restent l'apanage de la politique.
SUBJECT_CROSS_CHECKED_DIMENSIONS: tuple[str, ...] = (
    "collection",
    "tenant",
    "niveau",
    "voie",
    "matiere",
    "statut_enseignement",
    "candidat",
    "visibility",
    "school_year",
    "programme_version",
)


class ScopeEmissionError(RuntimeError):
    """Refus d'émission : aucune sortie n'est écrite quand il est levé."""


class PolicyBinding(NamedTuple):
    """Liaison nommée : une collection, sa politique source, son successeur."""

    collection: str
    policy_source_scope_id: str
    scope_id: str


@dataclass(frozen=True)
class EmittedScope:
    """Un scope émis, avec la provenance qui permet de le contredire."""

    scope_id: str
    collection: str
    policy_source_scope_id: str
    resource_name: str
    artifact: RetrievalScopeArtifactV2
    canonical_bytes: bytes

    @property
    def sha256(self) -> str:
        return self.artifact.sha256_digest()


@dataclass(frozen=True)
class ReusedScope:
    """Un sujet qu'un scope existant lie déjà exactement : rien à émettre."""

    scope_id: str
    collection: str


@dataclass(frozen=True)
class EmissionResult:
    """Le compte rendu de l'émission, mesuré et non supposé."""

    emitted: tuple[EmittedScope, ...]
    reused: tuple[ReusedScope, ...]

    @property
    def subject_count(self) -> int:
        return len(self.emitted) + len(self.reused)

    @property
    def new_scope_count(self) -> int:
        return len(self.emitted)


# --- Lecture des entrées, chacune vérifiée contre le digest qu'on lui nomme ---


def _read_bytes_with_digest(path: Path, expected_sha256: str, label: str) -> bytes:
    try:
        raw = path.read_bytes()
    except OSError as exc:  # pragma: no cover - dépend du système de fichiers
        raise ScopeEmissionError(f"{label} illisible") from exc
    observed = hashlib.sha256(raw).hexdigest()
    if observed != expected_sha256:
        raise ScopeEmissionError(
            f"{label} : digest annoncé {expected_sha256}, observé {observed}"
        )
    return raw


def load_policy_authority(path: Path, expected_sha256: str) -> tuple[PolicyBinding, ...]:
    """Charger l'autorité de politique, sans jamais en déduire un droit."""
    raw = _read_bytes_with_digest(path, expected_sha256, "autorité de politique")
    payload = yaml.safe_load(raw.decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ScopeEmissionError("autorité de politique malformée")
    if payload.get("authority_id") != POLICY_AUTHORITY_KIND:
        raise ScopeEmissionError("autorité de politique d'un genre inconnu")
    bindings_raw = payload.get("bindings")
    if not isinstance(bindings_raw, list) or not bindings_raw:
        raise ScopeEmissionError("autorité de politique sans liaison")
    bindings: list[PolicyBinding] = []
    for index, entry in enumerate(bindings_raw):
        if not isinstance(entry, Mapping) or set(entry) != {
            "collection",
            "policy_source_scope_id",
            "scope_id",
        }:
            raise ScopeEmissionError(f"bindings[{index}] : champs inattendus")
        bindings.append(
            PolicyBinding(
                collection=str(entry["collection"]),
                policy_source_scope_id=str(entry["policy_source_scope_id"]),
                scope_id=str(entry["scope_id"]),
            )
        )
    return tuple(bindings)


def load_policy_source(scope_id: str) -> RetrievalScopeArtifactV2:
    """Lire la politique chez son autorité : le registre fermé, digest vérifié."""
    try:
        artifact = load_retrieval_scope_artifact(scope_id)
    except ValueError as exc:
        raise ScopeEmissionError(
            f"politique source inconnue du registre fermé : {scope_id}"
        ) from exc
    if not isinstance(artifact, RetrievalScopeArtifactV2):
        raise ScopeEmissionError(f"politique source non V2 : {scope_id}")
    return artifact


class SubjectFacts(NamedTuple):
    """Ce que la release-sujet déclare : son digest et ses dimensions observées."""

    collection: str
    sha256: str
    dimensions: Mapping[str, str]


def load_subject_release(path: Path, expected_sha256: str) -> tuple[SubjectFacts, ...]:
    """Lire la release-sujet : uniquement ce qui existe, jamais qui peut le voir."""
    raw = _read_bytes_with_digest(path, expected_sha256, "release-sujet")
    aggregate = json.loads(raw.decode("utf-8"))
    if not isinstance(aggregate, Mapping):
        raise ScopeEmissionError("release-sujet malformée")
    subjects = aggregate.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        raise ScopeEmissionError("release-sujet sans subject")
    root = path.parent
    facts: list[SubjectFacts] = []
    for index, entry in enumerate(subjects):
        if not isinstance(entry, Mapping):
            raise ScopeEmissionError(f"subjects[{index}] malformé")
        collection = str(entry["collection"])
        subject_sha256 = str(entry["sha256"])
        relative = Path(str(entry["path"]))
        if relative.is_absolute():
            raise ScopeEmissionError(f"subjects[{index}] : chemin absolu refusé")
        subject_path = (root / relative).resolve()
        if not subject_path.is_relative_to(root.resolve()):
            raise ScopeEmissionError(f"subjects[{index}] : chemin hors de la release")
        payload = json.loads(
            _read_bytes_with_digest(
                subject_path, subject_sha256, f"subjects[{index}]"
            ).decode("utf-8")
        )
        facts.append(
            SubjectFacts(
                collection=collection,
                sha256=subject_sha256,
                dimensions=_observed_subject_dimensions(payload, index),
            )
        )
    return tuple(facts)


def _observed_subject_dimensions(payload: Any, index: int) -> Mapping[str, str]:
    """Projeter les dimensions que les placements du subject déclarent."""
    if not isinstance(payload, Mapping):
        raise ScopeEmissionError(f"subjects[{index}] malformé")
    placements = [
        placement
        for artifact in payload.get("artifacts", [])
        for placement in artifact.get("placements", [])
    ]
    if not placements:
        raise ScopeEmissionError(f"subjects[{index}] : aucun placement à qualifier")
    observed: dict[str, str] = {}
    for dimension in SUBJECT_CROSS_CHECKED_DIMENSIONS:
        values = {str(placement[dimension]) for placement in placements}
        if len(values) != 1:
            raise ScopeEmissionError(
                f"subjects[{index}] : dimension {dimension} non univoque {sorted(values)}"
            )
        observed[dimension] = values.pop()
    return observed


# --- Croisement : la release ne peut jamais devenir la politique -------------


def _require_governed_successor(binding: PolicyBinding) -> None:
    """Exiger la convention de succession déjà gouvernée : `_v<N>` → `_v<N+1>`."""
    source = binding.policy_source_scope_id
    stem, _, version = source.rpartition("_v")
    if not stem or not version.isdigit():
        raise ScopeEmissionError(
            f"politique source hors convention de version : {source}"
        )
    expected = f"{stem}_v{int(version) + 1}"
    if binding.scope_id != expected:
        raise ScopeEmissionError(
            f"scope_id hors convention de succession : {binding.scope_id} "
            f"attendu {expected}"
        )


def _require_registry_reuse_is_a_strict_reproduction(
    scope_id: str,
    artifact: RetrievalScopeArtifactV2,
) -> None:
    """Refuser de rebrancher un identifiant déjà épinglé sur un autre contenu.

    Un identifiant absent du registre est libre. Un identifiant présent n'est
    admis que si les octets canoniques émis rendent EXACTEMENT le digest que le
    contrat épingle : c'est alors une reproduction du même artefact, la seule
    réutilisation que le contrat autorise. Toute autre valeur signifierait
    qu'un scope déjà adressable change de contenu sous le même nom.
    """
    pinned = HISTORICAL_REGISTRY.get(scope_id)
    if pinned is None:
        return
    _resource, expected_digest, _version = pinned
    observed = artifact.sha256_digest()
    if observed != expected_digest:
        raise ScopeEmissionError(
            f"collision de scope_id avec des octets différents : {scope_id} est "
            f"déjà épinglé au registre historique sous {expected_digest}, "
            f"émission {observed}"
        )


def _require_policy_matches_subject(
    binding: PolicyBinding,
    policy: RetrievalScopeArtifactV2,
    subject: SubjectFacts,
) -> None:
    """Refuser toute liaison dont le sujet contredit la politique nommée."""
    declared = policy.evidence_subject.model_dump(mode="json")
    if str(declared["collection"]) != binding.collection:
        raise ScopeEmissionError(
            f"{binding.scope_id} : collection de politique "
            f"{declared['collection']} ≠ collection liée {binding.collection}"
        )
    for dimension in SUBJECT_CROSS_CHECKED_DIMENSIONS:
        expected = str(declared[dimension])
        observed = subject.dimensions[dimension]
        if observed != expected:
            raise ScopeEmissionError(
                f"{binding.scope_id} : {dimension} du sujet {observed!r} "
                f"≠ {dimension} de la politique {expected!r}"
            )


def authorization_semantic_diff(
    artifact: RetrievalScopeArtifactV2,
    policy: RetrievalScopeArtifactV2,
) -> dict[str, tuple[Any, Any]]:
    """Comparer TOUT sauf ce qui doit nécessairement changer.

    Sont exclus `scope_id`, `source_sha256` et, par construction, le digest de
    l'artefact : ce sont les seuls porteurs de la nouvelle liaison. Tout le
    reste — `target_identity` en entier, et les douze dimensions de
    `evidence_subject` — doit être identique à la politique reconduite.
    """
    excluded = {"scope_id", "source_sha256"}
    left = artifact.model_dump(mode="json")
    right = policy.model_dump(mode="json")
    diff: dict[str, tuple[Any, Any]] = {}
    for field in sorted(set(left) | set(right)):
        if field in excluded:
            continue
        if field == "evidence_subject":
            for dimension in AUTHORIZATION_DIMENSIONS:
                if left[field].get(dimension) != right[field].get(dimension):
                    diff[f"evidence_subject.{dimension}"] = (
                        left[field].get(dimension),
                        right[field].get(dimension),
                    )
            continue
        if left.get(field) != right.get(field):
            diff[field] = (left.get(field), right.get(field))
    return diff


def _require_authorization_is_reconducted(
    artifact: RetrievalScopeArtifactV2,
    policy: RetrievalScopeArtifactV2,
) -> None:
    """Refuser tout élargissement de droits : AUTHORIZATION_SEMANTIC_DIFF == 0."""
    diff = authorization_semantic_diff(artifact, policy)
    if diff:
        raise ScopeEmissionError(
            f"{artifact.scope_id} : élargissement d'autorisation refusé, "
            f"la politique émise diverge de {policy.scope_id} sur {sorted(diff)}"
        )


def exact_existing_matches(
    collection: str,
    subject_sha256: str,
    *,
    excluded_scope_ids: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    """Chercher, parmi les scopes existants, ceux qui lient DÉJÀ ce sujet exact.

    C'est la question que le moteur pose au démarrage, posée ici avant toute
    émission : un sujet déjà couvert n'a pas besoin d'un scope de plus.
    `excluded_scope_ids` retire de la recherche des identifiants nommés — le
    seul usage prévu est la REPRODUCTION d'une émission déjà installée, pour
    prouver qu'elle est déterministe. Cela n'ouvre aucun droit : le résultat
    reproduit est comparé octet à octet à ce qui est déjà packagé.
    """
    matches: list[str] = []
    for scope_id in HISTORICAL_REGISTRY:
        if scope_id in excluded_scope_ids:
            continue
        artifact = load_retrieval_scope_artifact(scope_id)
        if not isinstance(artifact, RetrievalScopeArtifactV2):
            continue
        if (
            str(artifact.evidence_subject.collection) == collection
            and artifact.source_sha256 == subject_sha256
        ):
            matches.append(scope_id)
    return tuple(matches)


def resource_name_for(scope_id: str) -> str:
    """Nommer le fichier d'artefact selon la convention déjà en place."""
    return f"retrieval-scope-{scope_id.replace('_', '-')}.json"


def _artifact_bytes(artifact: RetrievalScopeArtifactV2) -> bytes:
    """Rendre l'artefact lisible par un relecteur, et strictement déterministe."""
    payload = artifact.model_dump(mode="json")
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _build_scope_artifact(
    binding: PolicyBinding,
    policy: RetrievalScopeArtifactV2,
    subject: SubjectFacts,
) -> RetrievalScopeArtifactV2:
    """Composer le successeur : la politique reconduite, la source renouvelée.

    `source_sha256` est LA seule valeur venue de la release. Tout le reste est
    repris de la politique, sans transformation ni valeur par défaut.
    """
    return RetrievalScopeArtifactV2(
        artifact_version="2",
        scope_id=binding.scope_id,
        status=policy.status,
        source_sha256=subject.sha256,
        target_identity=policy.target_identity,
        evidence_subject=policy.evidence_subject,
    )


# --- Émission ----------------------------------------------------------------


def emit_retrieval_scope_artifacts(
    *,
    subject_release: Path,
    subject_release_sha256: str,
    policy_authority: Path,
    policy_authority_sha256: str,
    artifacts_dir: Path,
    reproduce_scope_ids: frozenset[str] = frozenset(),
) -> EmissionResult:
    """Émettre un scope par subject NON ENCORE LIÉ, et rien de plus."""
    bindings = load_policy_authority(policy_authority, policy_authority_sha256)
    subjects = load_subject_release(subject_release, subject_release_sha256)

    binding_by_collection: dict[str, PolicyBinding] = {}
    binding_by_scope_id: dict[str, PolicyBinding] = {}
    for binding in bindings:
        if binding.collection in binding_by_collection:
            raise ScopeEmissionError(
                f"deux scopes liés à la même collection : {binding.collection}"
            )
        # Deux liaisons qui partagent un identifiant diffèrent forcément par
        # leur collection — le cas « même collection » vient d'être refusé —,
        # donc par leurs octets canoniques : c'est bien une collision.
        previous = binding_by_scope_id.get(binding.scope_id)
        if previous is not None:
            raise ScopeEmissionError(
                f"collision de scope_id avec des octets différents : "
                f"{binding.scope_id} lie déjà {previous.collection}"
            )
        binding_by_collection[binding.collection] = binding
        binding_by_scope_id[binding.scope_id] = binding

    emitted: list[EmittedScope] = []
    reused: list[ReusedScope] = []
    seen_subject_keys: set[tuple[str, str]] = set()

    for subject in subjects:
        key = (subject.collection, subject.sha256)
        if key in seen_subject_keys:
            raise ScopeEmissionError(
                f"deux scopes générés pour le même sujet : {subject.collection}"
            )
        seen_subject_keys.add(key)

        # RÉUTILISATION AVANT ÉMISSION : un sujet déjà lié exactement n'a pas
        # besoin d'un scope de plus, et deux liaisons exactes sont une ambiguïté
        # d'autorité que le moteur refuserait au démarrage.
        matches = exact_existing_matches(
            subject.collection,
            subject.sha256,
            excluded_scope_ids=reproduce_scope_ids,
        )
        if len(matches) > 1:
            raise ScopeEmissionError(
                f"correspondances exactes multiples pour {subject.collection} : "
                f"{sorted(matches)}"
            )
        if len(matches) == 1:
            reused.append(ReusedScope(scope_id=matches[0], collection=subject.collection))
            continue

        binding = binding_by_collection.get(subject.collection)
        if binding is None:
            raise ScopeEmissionError(
                f"autorité de politique absente pour {subject.collection}"
            )
        _require_governed_successor(binding)
        policy = load_policy_source(binding.policy_source_scope_id)
        _require_policy_matches_subject(binding, policy, subject)

        artifact = _build_scope_artifact(binding, policy, subject)
        _require_authorization_is_reconducted(artifact, policy)
        _require_registry_reuse_is_a_strict_reproduction(binding.scope_id, artifact)
        emitted.append(
            EmittedScope(
                scope_id=binding.scope_id,
                collection=subject.collection,
                policy_source_scope_id=binding.policy_source_scope_id,
                resource_name=resource_name_for(binding.scope_id),
                artifact=artifact,
                canonical_bytes=_artifact_bytes(artifact),
            )
        )

    covered = {item.collection for item in emitted} | {item.collection for item in reused}
    unbound = set(binding_by_collection) - covered
    if unbound:
        raise ScopeEmissionError(
            f"liaisons sans subject à émettre dans la release : {sorted(unbound)}"
        )

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    for item in emitted:
        (artifacts_dir / item.resource_name).write_bytes(item.canonical_bytes)
    return EmissionResult(emitted=tuple(emitted), reused=tuple(reused))


def registry_index_bytes(result: EmissionResult) -> bytes:
    """Rendre l'addendum de registre que `scope.py` doit porter, à la lettre."""
    emitted: Sequence[EmittedScope] = result.emitted
    payload = {
        "authority_id": POLICY_AUTHORITY_KIND,
        "subject_count": result.subject_count,
        "new_scope_count": result.new_scope_count,
        "reused": [
            {"scope_id": item.scope_id, "collection": item.collection}
            for item in result.reused
        ],
        "entries": [
            {
                "scope_id": item.scope_id,
                "resource": f"artifacts/{item.resource_name}",
                "sha256": item.sha256,
                "artifact_version": "2",
                "collection": item.collection,
                "policy_source_scope_id": item.policy_source_scope_id,
            }
            for item in emitted
        ],
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Toutes les entrées sont NOMMÉES : ce fichier ne lit jamais le CWD et ne
    # porte aucun chemin de poste de travail.
    parser.add_argument("--subject-release", type=Path, required=True)
    parser.add_argument("--subject-release-sha256", required=True)
    # Exigés sur le chemin historique ; l'exigence est reposée plus bas,
    # afin que le chemin « registre gouverné » puisse les omettre sans
    # qu'aucun des deux chemins ne perde sa garde.
    parser.add_argument("--policy-authority", type=Path)
    parser.add_argument("--policy-authority-sha256")
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--registry-index", type=Path, required=False)
    # Reproduire une émission déjà installée : le scope nommé est retiré de la
    # recherche de réutilisation, afin que le producteur refabrique ses propres
    # octets et qu'on puisse les comparer. Aucun droit n'est ouvert par là.
    parser.add_argument("--reproduce-scope-id", action="append", default=[])
    # ADR-0052 / ADR-0053 — chemin « registre de politique gouverné ». Quand il
    # est nommé, la politique se lit au registre et non dans un scope source,
    # et les deux règles d'ADR-0052 s'appliquent. Les entrées restent NOMMÉES
    # et vérifiées contre leur digest, comme sur l'autre chemin.
    parser.add_argument("--policy-registry", type=Path)
    parser.add_argument("--policy-registry-sha256")
    parser.add_argument("--successor-authority", type=Path)
    parser.add_argument("--successor-authority-sha256")
    parser.add_argument("--repo-root", type=Path)
    args = parser.parse_args(argv)

    if args.policy_registry is not None:
        missing = [
            name
            for name, value in (
                ("--policy-registry-sha256", args.policy_registry_sha256),
                ("--successor-authority", args.successor_authority),
                ("--successor-authority-sha256", args.successor_authority_sha256),
                ("--repo-root", args.repo_root),
            )
            if value is None
        ]
        if missing:
            parser.error(
                "le chemin registre de politique exige aussi : "
                + ", ".join(missing)
            )
        registry_result = emit_from_policy_registry(
            subject_release=args.subject_release,
            subject_release_sha256=args.subject_release_sha256,
            policy_registry=args.policy_registry,
            policy_registry_sha256=args.policy_registry_sha256,
            successor_authority=args.successor_authority,
            successor_authority_sha256=args.successor_authority_sha256,
            artifacts_dir=args.artifacts_dir,
            repo_root=args.repo_root,
            reproduce_scope_ids=frozenset(args.reproduce_scope_id),
        )
        if args.registry_index is not None:
            args.registry_index.write_bytes(registry_index_bytes(registry_result))
        for item in registry_result.emitted:
            print(f"{item.scope_id}\t{item.collection}\t{item.sha256}")
        for item in registry_result.reused:
            print(f"REUSED\t{item.collection}\t{item.scope_id}")
        return 0

    legacy_missing = [
        name
        for name, value in (
            ("--policy-authority", args.policy_authority),
            ("--policy-authority-sha256", args.policy_authority_sha256),
        )
        if value is None
    ]
    if legacy_missing:
        parser.error(
            "le chemin historique exige : " + ", ".join(legacy_missing)
        )

    result = emit_retrieval_scope_artifacts(
        subject_release=args.subject_release,
        subject_release_sha256=args.subject_release_sha256,
        policy_authority=args.policy_authority,
        policy_authority_sha256=args.policy_authority_sha256,
        artifacts_dir=args.artifacts_dir,
        reproduce_scope_ids=frozenset(args.reproduce_scope_id),
    )
    if args.registry_index is not None:
        index: Path = args.registry_index
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_bytes(registry_index_bytes(result))
    return 0



# --- Émission depuis le registre de politique gouverné (ADR-0052, ADR-0053) ---
#
# La famille « profils production » n'a jamais été émissible par le chemin
# ci-dessus : ses scopes ont été écrits à la main, et deux des dimensions que
# l'émetteur croise y divergent structurellement de la release.
#
#   * `programme_version` — les placements portent un identifiant de CORPUS
#     (`EDUSCOL_CORPUS_…`), pas une référence de programme. La référence
#     officielle se lit dans le registre de programme de la release
#     (`NEXUS_PROGRAMME_INDEX_REGISTRY_V3`). ADR-0052 §2 change donc
#     l'AUTORITÉ de ce croisement ; il ne le supprime pas.
#   * `visibility` — les placements déclarent l'OUVERTURE DU MATÉRIAU
#     (`public`), la politique déclare l'ACCÈS AU SERVICE (`internal`).
#     ADR-0052 §3 les nomme séparément et impose un ordre de restriction :
#     restreindre est admis, élargir est un REFUS.
#
# Rien ici n'assouplit le chemin multi-niveaux, qui reste intact au-dessus.

#: Genre du registre de politique que ce chemin sait lire.
POLICY_REGISTRY_KIND = "NEXUS_RETRIEVAL_SCOPE_POLICY_REGISTRY_V1"

#: Genre de l'autorité de nommage : elle ne porte aucune dimension.
SUCCESSOR_AUTHORITY_KIND = "PRODUCTION_PROFILE_SCOPE_SUCCESSORS_V1"

#: Genre de l'autorité de programme, nommée par le registre lui-même.
PROGRAMME_AUTHORITY_KIND = "NEXUS_PROGRAMME_INDEX_REGISTRY_V3"

#: ADR-0052 §1 — les dimensions curriculaires, croisées par ÉGALITÉ STRICTE
#: entre les placements du subject et la politique. Aucune n'est facultative.
CURRICULAR_CROSS_CHECKED_DIMENSIONS: tuple[str, ...] = (
    "collection",
    "tenant",
    "niveau",
    "voie",
    "matiere",
    "statut_enseignement",
    "candidat",
    "school_year",
)

#: Les deux statuts qu'une entrée de registre peut porter, et eux seuls.
_GOVERNED = "GOVERNED"
_BY_HUMAN_DECISION = "GOVERNED_BY_HUMAN_DECISION"


@dataclass(frozen=True)
class PolicyRegistryEntry:
    """Une politique gouvernée, lue telle quelle et jamais complétée."""

    collection: str
    decision_status: str
    authority_source: str
    policy_source_scope_id: str | None
    subject_manifest_sha256: str
    tenant: str
    niveau: str
    voie: str
    matiere: str
    statut_enseignement: str
    candidat: str
    audiences: tuple[str, ...]
    rights: tuple[str, ...]
    policy_visibility: str
    evidence_visibility: str
    programme_version: str
    target_audience: str
    target_candidates: tuple[str, ...]


@dataclass(frozen=True)
class PolicyRegistry:
    """Le registre gouverné, avec ce qu'il nomme comme autorités."""

    entries: Mapping[str, PolicyRegistryEntry]
    visibility_restriction_order: tuple[str, ...]
    school_year: str
    programme_authority_path: str
    programme_authority_sha256: str
    release_manifest_sha256: str


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ScopeEmissionError(message)


def load_policy_registry(path: Path, expected_sha256: str) -> PolicyRegistry:
    """Charger le registre de politique, sans jamais en déduire un droit."""
    raw = _read_bytes_with_digest(path, expected_sha256, "registre de politique")
    payload = yaml.safe_load(raw.decode("utf-8"))
    _require(isinstance(payload, Mapping), "registre de politique malformé")
    _require(
        payload.get("registry_kind") == POLICY_REGISTRY_KIND,
        "registre de politique d'un genre inconnu",
    )
    order = payload.get("visibility_restriction_order")
    _require(
        isinstance(order, list) and bool(order),
        "registre de politique sans ordre de restriction de visibilité",
    )
    authority = payload.get("programme_version_authority")
    _require(
        isinstance(authority, Mapping)
        and authority.get("authority_kind") == PROGRAMME_AUTHORITY_KIND,
        "registre de politique sans autorité de programme reconnue",
    )
    collections = payload.get("collections")
    _require(
        isinstance(collections, list) and bool(collections),
        "registre de politique sans collection",
    )

    entries: dict[str, PolicyRegistryEntry] = {}
    for index, item in enumerate(collections):
        _require(isinstance(item, Mapping), f"collections[{index}] malformé")
        collection = str(item["collection"])
        _require(
            collection not in entries,
            f"collection déclarée deux fois au registre : {collection}",
        )
        status = str(item["decision_status"])
        _require(
            status in {_GOVERNED, _BY_HUMAN_DECISION},
            f"{collection} : statut de décision inconnu {status!r}",
        )
        # Une politique incomplète est un REFUS, jamais une valeur par défaut.
        for field in (
            "audiences",
            "rights",
            "policy_visibility",
            "evidence_visibility",
            "programme_version",
            "authority_source",
            "target_audience",
            "target_candidates",
        ):
            _require(
                item.get(field) is not None,
                f"{collection} : {field} absent du registre — aucune émission",
            )
        source = item.get("policy_source_scope_id")
        entries[collection] = PolicyRegistryEntry(
            collection=collection,
            decision_status=status,
            authority_source=str(item["authority_source"]),
            policy_source_scope_id=None if source is None else str(source),
            subject_manifest_sha256=str(item["subject_manifest_sha256"]),
            tenant=str(item["tenant"]),
            niveau=str(item["niveau"]),
            voie=str(item["voie"]),
            matiere=str(item["matiere"]),
            statut_enseignement=str(item["statut_enseignement"]),
            candidat=str(item["candidat"]),
            audiences=tuple(str(a) for a in item["audiences"]),
            rights=tuple(str(r) for r in item["rights"]),
            policy_visibility=str(item["policy_visibility"]),
            evidence_visibility=str(item["evidence_visibility"]),
            programme_version=str(item["programme_version"]),
            target_audience=str(item["target_audience"]),
            target_candidates=tuple(str(c) for c in item["target_candidates"]),
        )

    return PolicyRegistry(
        entries=entries,
        visibility_restriction_order=tuple(str(v) for v in order),
        school_year=str(payload["school_year"]),
        programme_authority_path=str(authority["path"]),
        programme_authority_sha256=str(authority["sha256"]),
        release_manifest_sha256=str(payload["release_manifest_sha256"]),
    )


def load_successor_authority(path: Path, expected_sha256: str) -> Mapping[str, str]:
    """Lire les identifiants à émettre. Ce fichier ne porte aucune dimension."""
    raw = _read_bytes_with_digest(path, expected_sha256, "autorité de nommage")
    payload = yaml.safe_load(raw.decode("utf-8"))
    _require(isinstance(payload, Mapping), "autorité de nommage malformée")
    _require(
        payload.get("authority_id") == SUCCESSOR_AUTHORITY_KIND,
        "autorité de nommage d'un genre inconnu",
    )
    bindings = payload.get("bindings")
    _require(
        isinstance(bindings, list) and bool(bindings),
        "autorité de nommage sans liaison",
    )
    named: dict[str, str] = {}
    seen_scope_ids: set[str] = set()
    for index, item in enumerate(bindings):
        _require(isinstance(item, Mapping), f"bindings[{index}] malformé")
        collection = str(item["collection"])
        scope_id = str(item["scope_id"])
        _require(
            collection not in named,
            f"deux identifiants pour la même collection : {collection}",
        )
        _require(
            scope_id not in seen_scope_ids,
            f"collision de scope_id dans l'autorité de nommage : {scope_id}",
        )
        named[collection] = scope_id
        seen_scope_ids.add(scope_id)
    return named


#: Dimensions qu'un placement de la release profils production doit déclarer.
#: Aucune n'est facultative : une absence est un refus, jamais une dispense.
PROFILE_SUBJECT_DECLARED_DIMENSIONS: tuple[str, ...] = (
    "collection",
    "tenant",
    "niveau",
    "voie",
    "matiere",
    "statut_enseignement",
    "candidat",
    "school_year",
    "visibility",
)


def load_profile_subject_release(
    path: Path, expected_sha256: str
) -> tuple[SubjectFacts, ...]:
    """Lire une release de profils production : placements à la RACINE.

    La release multi-niveaux imbrique ses placements sous `artifacts` ; celle
    des profils production les porte à la racine du subject. Ce lecteur est
    donc distinct — le lecteur historique reste intact — et il est STRICT :
    chaque dimension de `PROFILE_SUBJECT_DECLARED_DIMENSIONS` doit être
    présente et univoque sur tous les placements. Une dimension absente ou
    divergente est un REFUS, jamais une dimension qu'on cesse de croiser.
    """
    raw = _read_bytes_with_digest(path, expected_sha256, "release-sujet")
    aggregate = json.loads(raw.decode("utf-8"))
    _require(isinstance(aggregate, Mapping), "release-sujet malformée")
    subjects = aggregate.get("subjects")
    _require(
        isinstance(subjects, list) and bool(subjects), "release-sujet sans subject"
    )
    root = path.parent
    facts: list[SubjectFacts] = []
    for index, entry in enumerate(subjects):
        _require(isinstance(entry, Mapping), f"subjects[{index}] malformé")
        collection = str(entry["collection"])
        subject_sha256 = str(entry["sha256"])
        relative = Path(str(entry["path"]))
        _require(
            not relative.is_absolute(), f"subjects[{index}] : chemin absolu refusé"
        )
        subject_path = (root / relative).resolve()
        _require(
            subject_path.is_relative_to(root.resolve()),
            f"subjects[{index}] : chemin hors de la release",
        )
        payload = json.loads(
            _read_bytes_with_digest(
                subject_path, subject_sha256, f"subjects[{index}]"
            ).decode("utf-8")
        )
        _require(isinstance(payload, Mapping), f"subjects[{index}] malformé")
        placements = payload.get("placements")
        _require(
            isinstance(placements, list) and bool(placements),
            f"subjects[{index}] : aucun placement à qualifier",
        )
        observed: dict[str, str] = {}
        for dimension in PROFILE_SUBJECT_DECLARED_DIMENSIONS:
            missing = [p for p in placements if dimension not in p]
            _require(
                not missing,
                f"subjects[{index}] : dimension {dimension} absente de "
                f"{len(missing)} placement(s) — aucune dispense de contrôle",
            )
            values = {str(p[dimension]) for p in placements}
            _require(
                len(values) == 1,
                f"subjects[{index}] : dimension {dimension} non univoque "
                f"{sorted(values)}",
            )
            observed[dimension] = values.pop()
        facts.append(
            SubjectFacts(
                collection=collection,
                sha256=subject_sha256,
                dimensions=observed,
            )
        )
    return tuple(facts)


def _require_evidence_visibility_matches_placements(
    entry: PolicyRegistryEntry, subject: SubjectFacts
) -> None:
    """Sans ce croisement, la garde de visibilité serait circulaire.

    `_require_visibility_is_not_widened` compare deux valeurs du REGISTRE. Si
    personne ne vérifiait que `evidence_visibility` est bien celle que la
    release déclare, il suffirait d'y écrire une valeur plus restrictive pour
    faire passer n'importe quelle politique.
    """
    observed = subject.dimensions.get("visibility")
    _require(
        observed is not None,
        f"{entry.collection} : les placements ne déclarent aucune visibility",
    )
    if observed != entry.evidence_visibility:
        raise ScopeEmissionError(
            f"{entry.collection} : evidence_visibility du registre "
            f"{entry.evidence_visibility!r} ≠ visibility déclarée par les "
            f"placements {observed!r}"
        )


def _require_visibility_is_not_widened(
    entry: PolicyRegistryEntry, order: Sequence[str]
) -> None:
    """ADR-0052 §3 — restreindre est admis, élargir est un REFUS.

    La garde est fermée des deux côtés : une valeur absente de l'ordre déclaré
    est refusée, faute de quoi une visibilité inconnue passerait sans être
    comparée à quoi que ce soit.
    """
    for label, value in (
        ("evidence_visibility", entry.evidence_visibility),
        ("policy_visibility", entry.policy_visibility),
    ):
        _require(
            value in order,
            f"{entry.collection} : {label} {value!r} hors de l'ordre de "
            f"restriction déclaré {list(order)}",
        )
    if order.index(entry.policy_visibility) < order.index(entry.evidence_visibility):
        raise ScopeEmissionError(
            f"{entry.collection} : élargissement d'accès refusé — "
            f"policy_visibility {entry.policy_visibility!r} est MOINS "
            f"restrictive que evidence_visibility {entry.evidence_visibility!r}"
        )


def _require_programme_version_matches_authority(
    entry: PolicyRegistryEntry, declared: Mapping[str, str]
) -> None:
    """ADR-0052 §2 — la référence de programme se lit chez son autorité."""
    _require(
        entry.collection in declared,
        f"{entry.collection} : absente du registre de programme — aucune "
        f"référence de programme ne peut être croisée",
    )
    expected = declared[entry.collection]
    if entry.programme_version != expected:
        raise ScopeEmissionError(
            f"{entry.collection} : programme_version du registre de politique "
            f"{entry.programme_version!r} ≠ {expected!r} déclaré par l'autorité "
            f"de programme"
        )


def _require_curricular_dimensions_match_subject(
    entry: PolicyRegistryEntry, subject: SubjectFacts, school_year: str
) -> None:
    """ADR-0052 §1 — les huit dimensions curriculaires, par égalité stricte."""
    expected = {
        "collection": entry.collection,
        "tenant": entry.tenant,
        "niveau": entry.niveau,
        "voie": entry.voie,
        "matiere": entry.matiere,
        "statut_enseignement": entry.statut_enseignement,
        "candidat": entry.candidat,
        "school_year": school_year,
    }
    for dimension in CURRICULAR_CROSS_CHECKED_DIMENSIONS:
        observed = subject.dimensions.get(dimension)
        _require(
            observed is not None,
            f"{entry.collection} : dimension {dimension} absente des placements "
            f"du subject — aucune dispense de contrôle",
        )
        if observed != expected[dimension]:
            raise ScopeEmissionError(
                f"{entry.collection} : {dimension} du sujet {observed!r} "
                f"≠ {dimension} de la politique {expected[dimension]!r}"
            )


def _require_governed_entry_restates_its_packaged_source(
    entry: PolicyRegistryEntry,
) -> None:
    """Une entrée GOVERNED doit rendre EXACTEMENT son scope source.

    C'est ce qui empêche le registre de devenir une seconde autorité : pour
    les collections reconduites, il ne fait que citer, et toute divergence
    avec l'artefact épinglé est un refus.
    """
    if entry.decision_status != _GOVERNED:
        return
    scope_id = entry.policy_source_scope_id
    _require(
        scope_id is not None,
        f"{entry.collection} : GOVERNED sans policy_source_scope_id",
    )
    policy = load_policy_source(str(scope_id))
    evidence = policy.evidence_subject
    target = policy.target_identity
    mismatches: list[str] = []
    if entry.audiences != tuple(evidence.audiences):
        mismatches.append("audiences")
    if entry.rights != tuple(r.value for r in evidence.rights):
        mismatches.append("rights")
    if entry.policy_visibility != evidence.visibility:
        mismatches.append("policy_visibility")
    if entry.programme_version != evidence.programme_version:
        mismatches.append("programme_version")
    if entry.target_audience != target.audience:
        mismatches.append("target_audience")
    if entry.target_candidates != tuple(c.value for c in target.candidates):
        mismatches.append("target_candidates")
    if mismatches:
        raise ScopeEmissionError(
            f"{entry.collection} : le registre diverge de son scope source "
            f"{scope_id} sur {sorted(mismatches)}"
        )


def _require_human_decision_is_declared_as_such(entry: PolicyRegistryEntry) -> None:
    """Une décision humaine ne se déguise pas en reconduction."""
    if entry.decision_status != _BY_HUMAN_DECISION:
        return
    _require(
        entry.policy_source_scope_id is None,
        f"{entry.collection} : une décision humaine ne peut pas invoquer un "
        f"policy_source_scope_id",
    )
    _require(
        entry.authority_source == "NEXUS_HUMAN_DECISION_ADR_0053",
        f"{entry.collection} : décision humaine sans autorité ADR-0053",
    )


def _build_artifact_from_registry(
    scope_id: str,
    entry: PolicyRegistryEntry,
    subject: SubjectFacts,
    school_year: str,
) -> RetrievalScopeArtifactV2:
    """Composer le scope : la politique du registre, la source de la release.

    `source_sha256` est LA seule valeur venue de la release. Toutes les autres
    sont lues au registre gouverné, sans transformation ni valeur par défaut.
    """
    return RetrievalScopeArtifactV2(
        artifact_version="2",
        scope_id=scope_id,
        status="eligible_for_promotion",
        source_sha256=subject.sha256,
        target_identity={
            "tenant": entry.tenant,
            "niveau": entry.niveau,
            "voie": entry.voie,
            "matiere": entry.matiere,
            "statut_enseignement": entry.statut_enseignement,
            "audience": entry.target_audience,
            "candidates": list(entry.target_candidates),
        },
        evidence_subject={
            "collection": entry.collection,
            "tenant": entry.tenant,
            "niveau": entry.niveau,
            "voie": entry.voie,
            "matiere": entry.matiere,
            "statut_enseignement": entry.statut_enseignement,
            "candidat": entry.candidat,
            "audiences": list(entry.audiences),
            "visibility": entry.policy_visibility,
            "rights": list(entry.rights),
            "school_year": school_year,
            "programme_version": entry.programme_version,
        },
    )


def emit_from_policy_registry(
    *,
    subject_release: Path,
    subject_release_sha256: str,
    policy_registry: Path,
    policy_registry_sha256: str,
    successor_authority: Path,
    successor_authority_sha256: str,
    artifacts_dir: Path,
    repo_root: Path,
    reproduce_scope_ids: frozenset[str] = frozenset(),
) -> EmissionResult:
    """Émettre un scope par collection de la release, et refuser tout le reste."""
    registry = load_policy_registry(policy_registry, policy_registry_sha256)
    named = load_successor_authority(successor_authority, successor_authority_sha256)
    subjects = load_profile_subject_release(
        subject_release, subject_release_sha256
    )

    programme_path = repo_root / registry.programme_authority_path
    programme_raw = _read_bytes_with_digest(
        programme_path, registry.programme_authority_sha256, "autorité de programme"
    )
    programme_payload = json.loads(programme_raw.decode("utf-8"))
    _require(
        programme_payload.get("registry_kind") == PROGRAMME_AUTHORITY_KIND,
        "autorité de programme d'un genre inconnu",
    )
    declared_programme = {
        str(t["collection"]): str(t["programme_version"])
        for t in programme_payload["taxonomies"]
    }

    emitted: list[EmittedScope] = []
    reused: list[ReusedScope] = []
    for subject in subjects:
        collection = subject.collection
        # Refus fail-closed : pas d'autorité, pas de scope.
        entry = registry.entries.get(collection)
        _require(
            entry is not None,
            f"{collection} : absente du registre de politique — aucune "
            f"autorité, aucune émission",
        )
        assert entry is not None  # noqa: S101 - resserre le type après _require
        scope_id = named.get(collection)
        _require(
            scope_id is not None,
            f"{collection} : aucun identifiant nommé par l'autorité de nommage",
        )
        assert scope_id is not None  # noqa: S101
        _require(
            entry.subject_manifest_sha256 == subject.sha256,
            f"{collection} : le registre lie le subject "
            f"{entry.subject_manifest_sha256} ≠ release {subject.sha256}",
        )

        _require_human_decision_is_declared_as_such(entry)
        _require_governed_entry_restates_its_packaged_source(entry)
        _require_curricular_dimensions_match_subject(
            entry, subject, registry.school_year
        )
        _require_programme_version_matches_authority(entry, declared_programme)
        _require_evidence_visibility_matches_placements(entry, subject)
        _require_visibility_is_not_widened(
            entry, registry.visibility_restriction_order
        )

        already = exact_existing_matches(
            collection, subject.sha256, excluded_scope_ids=reproduce_scope_ids
        )
        if already:
            _require(
                len(already) == 1,
                f"{collection} : {len(already)} scopes lient déjà ce sujet "
                f"{sorted(already)} — ambiguïté refusée",
            )
            reused.append(ReusedScope(scope_id=already[0], collection=collection))
            continue

        artifact = _build_artifact_from_registry(
            scope_id, entry, subject, registry.school_year
        )
        _require_registry_reuse_is_a_strict_reproduction(scope_id, artifact)
        emitted.append(
            EmittedScope(
                scope_id=scope_id,
                collection=collection,
                policy_source_scope_id=entry.policy_source_scope_id or entry.authority_source,
                resource_name=resource_name_for(scope_id),
                artifact=artifact,
                canonical_bytes=_artifact_bytes(artifact),
            )
        )

    artifacts_dir.mkdir(parents=True, exist_ok=True)
    for item in emitted:
        (artifacts_dir / item.resource_name).write_bytes(item.canonical_bytes)
    return EmissionResult(emitted=tuple(emitted), reused=tuple(reused))


if __name__ == "__main__":
    raise SystemExit(main())
