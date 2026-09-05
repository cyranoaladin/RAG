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
    parser.add_argument("--policy-authority", type=Path, required=True)
    parser.add_argument("--policy-authority-sha256", required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    parser.add_argument("--registry-index", type=Path, required=False)
    # Reproduire une émission déjà installée : le scope nommé est retiré de la
    # recherche de réutilisation, afin que le producteur refabrique ses propres
    # octets et qu'on puisse les comparer. Aucun droit n'est ouvert par là.
    parser.add_argument("--reproduce-scope-id", action="append", default=[])
    args = parser.parse_args(argv)

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


if __name__ == "__main__":
    raise SystemExit(main())
