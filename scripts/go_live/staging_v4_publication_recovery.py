#!/usr/bin/env python3
"""Récupérer la publication V4 après la fermeture de la revue batch #257 (lot DH).

La PR de revue #257 a été fusionnée avant que Worker B n'utilise les 479
attestations batch qu'elle fondait. ADR-0033 § 5 le prescrit : une PR fermée
invalide la revue, et Worker B refuse (``pull_request_not_open``). Le rôle
applicatif de Worker B ne peut pas persister cette invalidation ; les
attestations restent donc « actives » en base mais inutilisables, et les 479
jobs qui les nomment ne publieront jamais.

Ce script ne crée AUCUNE seconde chaîne d'autorité. Il fait quatre choses, et
elles seules, avec les rôles et les droits qui existent déjà :

``preview``
    lecture seule (``default_transaction_read_only``) : l'ensemble EXACT
    concerné, identités vérifiées une à une — release et ses cinq empreintes,
    revue #257 (dépôt, PR, tête, artefact, digest), références croisées
    attestation ↔ ressource ↔ artefact ↔ job ↔ run, baux, pins, états. Deux
    empreintes d'ensemble en sortent ; les écritures les exigent.
``cancel-stale-jobs``
    rôle ``ingestion_control_app`` (``UPDATE`` sur ``jobs`` depuis LOT44e) :
    passe à ``cancelled`` les seuls jobs périmés en file, ou dont le bail a
    EXPIRÉ sans complétion. Un bail actif est un refus. Rien n'est supprimé ni
    réaffecté ; ``last_error`` (le refus de Worker B) est conservé ; le motif
    d'annulation est ajouté au ``payload`` sous ``recovery_cancellation``.
``invalidate-stale-attestations``
    rôle ``ingestion_control_attestor`` (``UPDATE (invalidated_at,
    invalidated_reason)`` depuis LOT42) : invalide les seules attestations de
    #257, après avoir constaté EN DIRECT que #257 n'autorise plus rien.
``review-precondition`` / ``closure-check``
    lecture seule : la nouvelle revue est ouverte, approuvée au head exact et
    nomme les attestations actives (avant mise en file et avant le lancement
    de Worker B) ; puis, après publication, rien ne dépend plus d'elle.

Chaque écriture est UNE transaction : l'ensemble est re-dérivé sous verrou,
doit porter l'empreinte de l'aperçu, et le compte exact est exigé ; sinon
rien n'est validé. Un rejeu identique ne réécrit rien : motifs et horodatages
déjà posés sont conservés.

Exécuté depuis ``/repo`` dans l'image worker épinglée, comme la mise en file
DG : n'importe que des primitives déjà présentes dans l'image
(``nexus_contracts``, ``ingestor.ingestion_control.github_authority``).
Aucune valeur de connexion n'est affichée.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RACINE_DEPOT = Path(__file__).resolve().parents[2]
IDENTITE_PAR_DEFAUT = "docs/reports/go_live/recovery/dh_stale_review_257.json"
KIND_IDENTITE = "NEXUS-STAGING-V4-STALE-PUBLICATION-REVIEW-V1"
PROTOCOLE_BATCH = "LOT42-RELEASE-BATCH-V1"
PIPELINE_SCELLE = "sealed_release_pipeline"
JOB_TYPE = "publication_resume"
ETAT_EN_REVUE = "NEEDS_REVIEW"
ETAT_PUBLIE = "RETRIEVAL_ELIGIBLE"
ROLE_APP = "ingestion_control_app"
ROLE_ATTESTOR = "ingestion_control_attestor"
#: Préfixe du motif d'annulation et d'invalidation : il permet de reconnaître
#: un rejeu du MÊME ensemble, jamais de deviner une intention.
MARQUE_DH = "DH-RECOVERY"
CLE_ANNULATION = "recovery_cancellation"
STATUTS_TERMINAUX = frozenset({"succeeded", "failed", "dead_letter", "cancelled"})
IDENTITE_RELEASE = (
    "release_id",
    "release_manifest_sha256",
    "artifacts_release_sha256",
    "candidate_inventory_sha256",
    "artifact_transfer_manifest_sha256",
)


class RecuperationRefusee(RuntimeError):
    """Un écart a été constaté ; rien n'est écrit."""

    def __init__(self, ecarts: Sequence[str]) -> None:
        self.ecarts = list(ecarts)
        super().__init__("; ".join(self.ecarts[:10]) + (" …" if len(self.ecarts) > 10 else ""))


# ── identité attendue de la revue périmée ──────────────────────────────────


@dataclass(frozen=True)
class RevuePerimee:
    """Ce que les anciennes attestations DOIVENT nommer, tiré du dépôt.

    Les champs de release viennent de l'artefact de revue versionné (relu,
    empreinte recalculée), jamais d'un argument libre."""

    repository: str
    pull_request: int
    head_sha: str
    review_artifact_path: str
    review_digest: str
    review_id: str
    release: Mapping[str, str]
    collections: tuple[str, ...]
    scope_authorization_ids: tuple[str, ...]
    database: str
    legacy_database: str
    attendu: Mapping[str, int]

    def cle(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "pull_request": self.pull_request,
            "head_sha": self.head_sha,
            "review_artifact_path": self.review_artifact_path,
            "review_digest": self.review_digest,
        }

    def etiquette(self) -> str:
        return f"{self.repository}#{self.pull_request}@{self.head_sha[:12]}"


def charger_revue_perimee(chemin: Path, *, racine: Path = RACINE_DEPOT) -> RevuePerimee:
    """Charge l'identité de la revue périmée et l'artefact qu'elle nomme."""
    from nexus_contracts.authority_artifacts import (  # noqa: PLC0415
        canonical_publication_review_path,
        parse_release_batch_publication_review_artifact,
    )

    document = json.loads(chemin.read_text(encoding="utf-8"))
    if document.get("kind") != KIND_IDENTITE:
        raise RecuperationRefusee([f"identité de revue périmée : kind {document.get('kind')!r} inconnu"])
    octets = (racine / document["review_artifact_path"]).read_bytes()
    empreinte = hashlib.sha256(octets).hexdigest()
    ecarts = []
    if empreinte != document["review_artifact_sha256"]:
        ecarts.append(f"artefact de revue : sha256 {empreinte}, l'identité nomme {document['review_artifact_sha256']}")
    artefact = parse_release_batch_publication_review_artifact(octets)
    if artefact.digest() != document["review_artifact_sha256"]:
        ecarts.append("artefact de revue : digest canonique différent de l'identité")
    canonique = canonical_publication_review_path(review_id=artefact.review_id, digest=artefact.digest())
    if canonique != document["review_artifact_path"]:
        ecarts.append(f"artefact de revue : chemin canonique {canonique}, l'identité nomme un autre chemin")
    if ecarts:
        raise RecuperationRefusee(ecarts)
    attendu = dict(document["expected"])
    comptes = artefact.expected_counts
    for cle, valeur in (("attestations", comptes.placements), ("resources", comptes.placements),
                        ("unique_contents", comptes.unique_artifacts), ("collections", comptes.subjects)):
        if attendu.get(cle) != valeur:
            raise RecuperationRefusee([f"identité : {cle}={attendu.get(cle)!r}, l'artefact revu déclare {valeur}"])
    return RevuePerimee(
        repository=str(document["repository"]),
        pull_request=int(document["pull_request"]),
        head_sha=str(document["head_sha"]),
        review_artifact_path=str(document["review_artifact_path"]),
        review_digest=artefact.digest(),
        review_id=artefact.review_id,
        release={cle: str(getattr(artefact, cle)) for cle in IDENTITE_RELEASE},
        collections=tuple(artefact.collections),
        scope_authorization_ids=tuple(artefact.scope_authorization_ids),
        database=str(document["database"]),
        legacy_database=str(document.get("legacy_database") or "ragdb"),
        attendu=attendu,
    )


# ── instantané ─────────────────────────────────────────────────────────────

REQUETE_ATTESTATIONS = """
SELECT pa.attestation_id, pa.resource_id, pa.artifact_id, pa.content_sha256,
       pa.collection, pa.scope_authorization_id, pa.protocol_version,
       pa.release_id, pa.release_manifest_sha256, pa.artifacts_release_sha256,
       pa.candidate_inventory_sha256, pa.artifact_transfer_manifest_sha256,
       pa.review_id, pa.review_artifact_path, pa.review_artifact_blob_sha,
       pa.attestation_digest, pa.release_batch_review_digest,
       pa.human_review_repository, pa.human_review_pull_request,
       pa.human_review_head_sha, pa.human_review_base_sha,
       pa.human_review_review_id, pa.human_review_reviewer,
       pa.human_review_submitted_at, pa.human_review_challenge,
       pa.invalidated_at, pa.invalidated_reason,
       r.collection AS resource_collection, r.pipeline_kind, r.resource_state,
       r.state_version, r.run_id AS resource_run_id,
       r.lease_token IS NOT NULL AS resource_leased,
       COALESCE(r.lease_expires_at > clock_timestamp(), false) AS resource_lease_active,
       a.resource_id AS artifact_resource_id, a.sha256 AS artifact_sha256,
       a.payload->>'release_id' AS artifact_release_id
  FROM ingestion_control.publication_attestations pa
  LEFT JOIN ingestion_control.resources r ON r.resource_id = pa.resource_id
  LEFT JOIN ingestion_control.artifacts a ON a.artifact_id = pa.artifact_id
 ORDER BY pa.attestation_id
"""
REQUETE_RESSOURCES_RELEASE = """
SELECT DISTINCT r.resource_id
  FROM ingestion_control.resources r
  JOIN ingestion_control.artifacts a ON a.resource_id = r.resource_id
 WHERE r.pipeline_kind = %s AND a.payload->>'release_id' = %s
"""
REQUETE_JOBS = """
SELECT job_id, run_id, resource_id, job_type, status, claimed_by,
       lease_token IS NOT NULL AS leased,
       COALESCE(lease_expires_at > clock_timestamp(), false) AS lease_active,
       lease_expires_at, attempt_count, max_attempts, last_error, payload
  FROM ingestion_control.jobs
 ORDER BY job_id
"""
REQUETE_PINS = """
SELECT publication_attestation_id, resource_id, publication_review_pull_request,
       publication_review_head_sha
  FROM ingestion_control.publication_commit_pins
"""


def _lignes(conn: Any, requete: str, parametres: Any = None) -> list[dict[str, Any]]:
    curseur = conn.execute(requete, parametres)
    colonnes = [colonne.name for colonne in curseur.description]
    return [dict(zip(colonnes, ligne, strict=True)) for ligne in curseur.fetchall()]


@dataclass
class Instantane:
    base: str
    role: str
    attestations: list[dict[str, Any]]
    ressources_release: set[str]
    ressources_total: int
    #: ``None`` : le rôle ne lit pas cette table (attestor) — jamais « vide ».
    jobs: list[dict[str, Any]] | None
    pins: list[dict[str, Any]] | None


def prendre_instantane(conn: Any, revue: RevuePerimee, *, avec_jobs: bool) -> Instantane:
    base, role = conn.execute("SELECT current_database(), current_user").fetchone()
    return Instantane(
        base=str(base),
        role=str(role),
        attestations=_lignes(conn, REQUETE_ATTESTATIONS),
        ressources_release={
            str(ligne["resource_id"])
            for ligne in _lignes(conn, REQUETE_RESSOURCES_RELEASE, (PIPELINE_SCELLE, revue.release["release_id"]))
        },
        ressources_total=int(conn.execute("SELECT count(*) FROM ingestion_control.resources").fetchone()[0]),
        jobs=_lignes(conn, REQUETE_JOBS) if avec_jobs else None,
        pins=_lignes(conn, REQUETE_PINS) if avec_jobs else None,
    )


# ── analyse ────────────────────────────────────────────────────────────────


def _canonique(valeur: Any) -> str:
    return hashlib.sha256(
        json.dumps(valeur, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _de_la_revue(ligne: Mapping[str, Any], revue: RevuePerimee) -> bool:
    """Une ligne appartient à #257 par sa clé de revue COMPLÈTE, jamais par un compte."""
    return (
        ligne["human_review_repository"] == revue.repository
        and ligne["human_review_pull_request"] == revue.pull_request
        and ligne["human_review_head_sha"] == revue.head_sha
        and ligne["review_artifact_path"] == revue.review_artifact_path
        and ligne["attestation_digest"] == revue.review_digest
    )


def motif_invalidation(revue: RevuePerimee, *, empreinte: str, raison_live: str) -> str:
    return (
        f"{MARQUE_DH} attestation_set_sha256={empreinte} : revue {revue.etiquette()} "
        f"(artefact {revue.review_digest[:16]}…) n'autorise plus rien en direct "
        f"(reason={raison_live}) ; invalidée par le rôle attestor, historique conservé"
    )


def _invalidee_par_dh(ligne: Mapping[str, Any], empreinte: str) -> bool:
    motif = ligne.get("invalidated_reason") or ""
    return motif.startswith(f"{MARQUE_DH} attestation_set_sha256={empreinte} ")


def _annule_par_dh(job: Mapping[str, Any], empreinte: str) -> bool:
    marque = (job.get("payload") or {}).get(CLE_ANNULATION) or {}
    return job["status"] == "cancelled" and marque.get("attestation_set_sha256") == empreinte


@dataclass
class Apercu:
    base: str
    role: str
    attestation_set_sha256: str
    job_set_sha256: str | None
    anciennes: list[dict[str, Any]]
    anciens_jobs: list[dict[str, Any]]
    successeurs: list[dict[str, Any]]
    jobs_successeurs: list[dict[str, Any]]
    comptes: dict[str, Any] = field(default_factory=dict)
    ecarts: list[str] = field(default_factory=list)
    homogene: dict[str, Any] = field(default_factory=dict)

    def rendu(self) -> dict[str, Any]:
        return {
            "database": self.base,
            "role": self.role,
            "attestation_set_sha256": self.attestation_set_sha256,
            "job_set_sha256": self.job_set_sha256,
            "stale_review_rows": self.homogene,
            "counts": self.comptes,
            "ecarts": self.ecarts,
        }


def analyser(instantane: Instantane, revue: RevuePerimee) -> Apercu:
    """Constate l'ensemble exact et TOUS ses écarts. N'écrit rien."""
    ecarts: list[str] = []
    if instantane.base == revue.legacy_database:
        ecarts.append(f"base {instantane.base!r} : la base historique n'est jamais une cible de DH")
    if instantane.base != revue.database:
        ecarts.append(f"base {instantane.base!r}, attendu {revue.database!r}")

    anciennes = [ligne for ligne in instantane.attestations if _de_la_revue(ligne, revue)]
    autres = [ligne for ligne in instantane.attestations if not _de_la_revue(ligne, revue)]
    ids_anciennes = {str(ligne["attestation_id"]) for ligne in anciennes}

    ensemble = sorted(
        [str(x["attestation_id"]), str(x["resource_id"]), str(x["artifact_id"]),
         x["content_sha256"], x["collection"], x["scope_authorization_id"]]
        for x in anciennes
    )
    empreinte = _canonique({"review": revue.cle(), "release": dict(revue.release), "attestations": ensemble})

    # 1. Chaque ancienne ligne porte EXACTEMENT l'identité revue et approuvée.
    attendu_ligne = {
        "protocol_version": PROTOCOLE_BATCH,
        "review_id": revue.review_id,
        "release_batch_review_digest": revue.review_digest,
        **revue.release,
    }
    baux_expires = 0
    for ligne in anciennes:
        aid = ligne["attestation_id"]
        for colonne, attendu in attendu_ligne.items():
            if ligne[colonne] != attendu:
                ecarts.append(f"attestation {aid} : {colonne}={ligne[colonne]!r}, attendu {attendu!r}")
        if ligne["resource_collection"] is None:
            ecarts.append(f"attestation {aid} : ressource {ligne['resource_id']} absente")
            continue
        if ligne["artifact_resource_id"] is None:
            ecarts.append(f"attestation {aid} : artefact {ligne['artifact_id']} absent")
            continue
        for libelle, observe, attendu in (
            ("artefact.resource_id", str(ligne["artifact_resource_id"]), str(ligne["resource_id"])),
            ("artefact.sha256", ligne["artifact_sha256"], ligne["content_sha256"]),
            ("artefact.release_id", ligne["artifact_release_id"], revue.release["release_id"]),
            ("ressource.collection", ligne["resource_collection"], ligne["collection"]),
            ("ressource.pipeline_kind", ligne["pipeline_kind"], PIPELINE_SCELLE),
        ):
            if observe != attendu:
                ecarts.append(f"attestation {aid} : {libelle}={observe!r}, attendu {attendu!r}")
        if ligne["collection"] not in revue.collections:
            ecarts.append(f"attestation {aid} : collection {ligne['collection']!r} hors de la revue")
        if ligne["scope_authorization_id"] not in revue.scope_authorization_ids:
            ecarts.append(f"attestation {aid} : autorisation {ligne['scope_authorization_id']!r} hors de la revue")
        if ligne["resource_state"] != ETAT_EN_REVUE:
            ecarts.append(
                f"attestation {aid} : ressource en {ligne['resource_state']}, attendu {ETAT_EN_REVUE} — "
                "une promotion a eu lieu : hors périmètre DH, escalade"
            )
        if ligne["resource_lease_active"]:
            ecarts.append(f"attestation {aid} : bail ACTIF sur la ressource {ligne['resource_id']}")
        elif ligne["resource_leased"]:
            baux_expires += 1

    # 2. Homogénéité : UNE revue, un seul relecteur, une seule base, un seul blob.
    homogene: dict[str, Any] = {}
    for colonne in ("human_review_base_sha", "human_review_review_id", "human_review_reviewer",
                    "review_artifact_blob_sha"):
        valeurs = {ligne[colonne] for ligne in anciennes}
        if len(valeurs) > 1:
            ecarts.append(f"les attestations de {revue.etiquette()} portent {len(valeurs)} {colonne} distincts")
        homogene[colonne] = sorted(str(v) for v in valeurs)
    paires: dict[str, set[str]] = {}
    for ligne in anciennes:
        paires.setdefault(ligne["collection"], set()).add(ligne["scope_authorization_id"])
    for collection, autorisations in sorted(paires.items()):
        if len(autorisations) != 1:
            ecarts.append(f"collection {collection} : {len(autorisations)} autorisations distinctes")

    # 3. Comptes ET couverture : l'ensemble est celui de la release, ni plus ni moins.
    ressources = {str(ligne["resource_id"]) for ligne in anciennes}
    comptes = {
        "attestations": len(anciennes),
        "resources": len(ressources),
        "unique_contents": len({ligne["content_sha256"] for ligne in anciennes}),
        "collections": len({ligne["collection"] for ligne in anciennes}),
    }
    for cle, valeur in comptes.items():
        if valeur != revue.attendu[cle]:
            ecarts.append(f"{cle} = {valeur}, attendu {revue.attendu[cle]}")
    if ressources != instantane.ressources_release:
        ecarts.append(
            f"couverture : {len(ressources - instantane.ressources_release)} ressource(s) attestée(s) hors "
            f"release, {len(instantane.ressources_release - ressources)} ressource(s) de release sans attestation"
        )
    if instantane.ressources_total != len(instantane.ressources_release):
        ecarts.append(
            f"la base porte {instantane.ressources_total} ressources, dont "
            f"{len(instantane.ressources_release)} de la release : ligne étrangère"
        )

    etat_attestations = Counter(
        "active" if ligne["invalidated_at"] is None
        else "invalidated_dh" if _invalidee_par_dh(ligne, empreinte)
        else "invalidated_other"
        for ligne in anciennes
    )
    comptes["attestation_states"] = dict(sorted(etat_attestations.items()))
    # Un bail de ressource EXPIRÉ n'est ni une annulation ni un blocage : il
    # est constaté, jamais modifié — DH ne touche pas aux ressources.
    comptes["resource_leases_expired"] = baux_expires

    # 4. Lignes hors #257 : admises seulement comme successeurs, après invalidation.
    successeurs: list[dict[str, Any]] = []
    for ligne in autres:
        aid = ligne["attestation_id"]
        conforme = (
            ligne["protocol_version"] == PROTOCOLE_BATCH
            and all(ligne[cle] == valeur for cle, valeur in revue.release.items())
            and ligne["attestation_digest"] != revue.review_digest
        )
        if not conforme:
            ecarts.append(f"attestation étrangère {aid} (release {ligne['release_id']!r}, protocole {ligne['protocol_version']!r})")
        elif etat_attestations.get("active"):
            ecarts.append(f"attestation {aid} d'une autre revue coexiste avec des attestations #257 encore actives")
        else:
            successeurs.append(ligne)
    comptes["successor_attestations"] = len(successeurs)

    # 5. Jobs et pins, quand le rôle les lit.
    anciens_jobs: list[dict[str, Any]] = []
    jobs_successeurs: list[dict[str, Any]] = []
    empreinte_jobs: str | None = None
    if instantane.jobs is not None:
        par_attestation = {str(ligne["attestation_id"]): ligne for ligne in anciennes}
        ids_successeurs = {str(ligne["attestation_id"]) for ligne in successeurs}
        non_terminaux: Counter[str] = Counter()
        for job in instantane.jobs:
            jid, charge = job["job_id"], job["payload"] or {}
            nomme = str(charge.get("publication_attestation_id") or "")
            if job["job_type"] != JOB_TYPE:
                ecarts.append(f"job étranger {jid} : type {job['job_type']!r}")
                continue
            if nomme in ids_successeurs:
                jobs_successeurs.append(job)
                continue
            ligne = par_attestation.get(nomme)
            if ligne is None:
                ecarts.append(f"job {jid} nomme l'attestation {nomme or '∅'} : ni #257, ni successeur")
                continue
            anciens_jobs.append(job)
            for libelle, observe, attendu in (
                ("job.resource_id", str(job["resource_id"]), str(ligne["resource_id"])),
                ("payload.resource_id", str(charge.get("resource_id")), str(ligne["resource_id"])),
                ("payload.artifact_id", str(charge.get("artifact_id")), str(ligne["artifact_id"])),
                ("payload.run_id", str(charge.get("run_id")), str(job["run_id"])),
                ("job.run_id", str(job["run_id"]), str(ligne["resource_run_id"])),
                ("payload.dedup_key", str(charge.get("dedup_key")), f"publication:{nomme}"),
                ("payload.expected_state_version", str(charge.get("expected_state_version")),
                 str(ligne["state_version"])),
            ):
                if observe != attendu:
                    ecarts.append(f"job {jid} : {libelle}={observe!r}, attendu {attendu!r}")
            if job["status"] == "succeeded":
                ecarts.append(f"job {jid} : SUCCEEDED sous une attestation #257 — publication à expertiser, escalade")
            if job["status"] == "running" and job["lease_active"]:
                ecarts.append(f"job {jid} : bail ACTIF (détenu par {job['claimed_by']!r}) — arrêter Worker B, attendre l'expiration")
            if job["status"] == "queued" and job["leased"]:
                ecarts.append(f"job {jid} : en file mais porteur d'un bail — état incohérent")
            if job["status"] not in STATUTS_TERMINAUX:
                non_terminaux[nomme] += 1
        doublons = [nomme for nomme, n in non_terminaux.items() if n > 1]
        if doublons:
            ecarts.append(f"{len(doublons)} attestation(s) portent plusieurs jobs non terminaux")
        if len(anciens_jobs) != revue.attendu["publication_jobs"]:
            ecarts.append(f"jobs de #257 = {len(anciens_jobs)}, attendu {revue.attendu['publication_jobs']}")
        sans_job = ids_anciennes - {str((j["payload"] or {}).get("publication_attestation_id")) for j in anciens_jobs}
        if sans_job:
            ecarts.append(f"{len(sans_job)} attestation(s) de #257 sans job")
        comptes["job_states"] = dict(sorted(Counter(_classe_job(j, empreinte) for j in anciens_jobs).items()))
        comptes["successor_jobs"] = len(jobs_successeurs)
        empreinte_jobs = _canonique({
            "attestation_set_sha256": empreinte,
            "jobs": sorted(
                [str(j["job_id"]), str((j["payload"] or {}).get("publication_attestation_id")),
                 str(j["resource_id"]), str(j["run_id"])]
                for j in anciens_jobs
            ),
        })
    if instantane.pins is not None:
        for pin in instantane.pins:
            nomme = str(pin["publication_attestation_id"])
            if nomme in ids_anciennes:
                ecarts.append(f"pin de commit produit sous l'attestation #257 {nomme} — publication à expertiser, escalade")
            elif nomme not in {str(x["attestation_id"]) for x in successeurs}:
                ecarts.append(f"pin étranger {nomme}")
        comptes["commit_pins"] = len(instantane.pins)

    return Apercu(
        base=instantane.base,
        role=instantane.role,
        attestation_set_sha256=empreinte,
        job_set_sha256=empreinte_jobs,
        anciennes=anciennes,
        anciens_jobs=anciens_jobs,
        successeurs=successeurs,
        jobs_successeurs=jobs_successeurs,
        comptes=comptes,
        ecarts=ecarts,
        homogene=homogene,
    )


def _classe_job(job: Mapping[str, Any], empreinte: str) -> str:
    """Expiration et annulation sont deux faits distincts, jamais confondus."""
    statut = job["status"]
    if statut == "running":
        return "running_lease_active" if job["lease_active"] else "running_lease_expired"
    if statut == "cancelled":
        return "cancelled_dh" if _annule_par_dh(job, empreinte) else "cancelled_other"
    return str(statut)


def _exiger(apercu: Apercu, *, attestation_set: str, job_set: str | None) -> None:
    ecarts = list(apercu.ecarts)
    if apercu.attestation_set_sha256 != attestation_set:
        ecarts.append(
            f"attestation_set_sha256 {apercu.attestation_set_sha256}, l'aperçu approuvé nomme {attestation_set}"
        )
    if job_set is not None and apercu.job_set_sha256 != job_set:
        ecarts.append(f"job_set_sha256 {apercu.job_set_sha256}, l'aperçu approuvé nomme {job_set}")
    if ecarts:
        raise RecuperationRefusee(ecarts)


def _exiger_role(conn: Any, role: str) -> None:
    courant = conn.execute("SELECT current_user").fetchone()[0]
    if courant != role:
        raise RecuperationRefusee([f"rôle {courant!r}, attendu {role!r}"])


# ── opérations ─────────────────────────────────────────────────────────────


def apercu(conn: Any, revue: RevuePerimee) -> Apercu:
    """Lecture seule imposée au serveur, puis rollback : rien ne peut être écrit."""
    conn.execute("SET TRANSACTION READ ONLY")
    try:
        _exiger_role(conn, ROLE_APP)
        return analyser(prendre_instantane(conn, revue, avec_jobs=True), revue)
    finally:
        conn.rollback()


def annuler_jobs_perimes(
    conn: Any, revue: RevuePerimee, *, attestation_set: str, job_set: str, lock_timeout_ms: int = 5000
) -> dict[str, int]:
    """Annule les jobs périmés dans la transaction de ``conn`` ; l'appelant valide."""
    _exiger_role(conn, ROLE_APP)
    conn.execute(f"SET LOCAL lock_timeout = {int(lock_timeout_ms)}")
    # Verrou d'abord, constat ensuite : un Worker B qui réclamerait pendant
    # l'opération saute ces lignes (SKIP LOCKED) ou a déjà un bail, refusé.
    conn.execute(
        "SELECT job_id FROM ingestion_control.jobs WHERE job_type = %s ORDER BY job_id FOR UPDATE",
        (JOB_TYPE,),
    ).fetchall()
    constat = analyser(prendre_instantane(conn, revue, avec_jobs=True), revue)
    _exiger(constat, attestation_set=attestation_set, job_set=job_set)

    bilan = Counter[str]()
    for job in constat.anciens_jobs:
        classe = _classe_job(job, attestation_set)
        if classe not in ("queued", "running_lease_expired"):
            bilan["deja_annules" if classe == "cancelled_dh" else f"preserves_{classe}"] += 1
            continue
        marque = {
            "lot": "DH",
            "motif": f"{MARQUE_DH} : job nommant une attestation de {revue.etiquette()}, périmée",
            "attestation_set_sha256": attestation_set,
            "job_set_sha256": job_set,
            "stale_review": revue.etiquette(),
            "previous_status": job["status"],
            "previous_claimed_by": job["claimed_by"],
            "previous_lease_expires_at": (
                job["lease_expires_at"].isoformat() if job["lease_expires_at"] else None
            ),
            "previous_lease": "expired_not_released" if classe == "running_lease_expired" else "none",
            "previous_attempt_count": job["attempt_count"],
            "cancelled_by_role": ROLE_APP,
        }
        ligne = conn.execute(
            """
            UPDATE ingestion_control.jobs
               SET status = 'cancelled', claimed_by = NULL, lease_token = NULL,
                   lease_expires_at = NULL, updated_at = now(),
                   payload = payload || jsonb_build_object(
                       %s::text,
                       %s::jsonb || jsonb_build_object('cancelled_at', clock_timestamp()))
             WHERE job_id = %s AND status = %s
               AND ((status = 'queued' AND lease_token IS NULL)
                 OR (status = 'running' AND lease_expires_at <= clock_timestamp()))
            RETURNING job_id
            """,
            (CLE_ANNULATION, json.dumps(marque), job["job_id"], job["status"]),
        ).fetchone()
        if ligne is None:
            raise RecuperationRefusee([f"job {job['job_id']} a changé sous verrou — rien n'est validé"])
        bilan["annules_en_file" if classe == "queued" else "annules_bail_expire"] += 1
    if sum(bilan.values()) != len(constat.anciens_jobs):
        raise RecuperationRefusee(["bilan d'annulation incomplet — rien n'est validé"])
    return dict(sorted(bilan.items()))


def constater_revue_fermee(revue: RevuePerimee) -> str:
    """#257 ne doit plus rien autoriser EN DIRECT ; rend la raison constatée.

    Une revue qui vérifierait encore n'est pas périmée : rien ne s'invalide."""
    from ingestor.ingestion_control.github_authority import (  # noqa: PLC0415
        GitHubAuthorityError,
        verify_review,
    )

    try:
        live = verify_review(
            repository=revue.repository, pull_request=revue.pull_request, expected_head=revue.head_sha
        )
    except GitHubAuthorityError as exc:
        raise RecuperationRefusee([f"revue {revue.etiquette()} : vérification live impossible ({exc})"]) from exc
    if live.approved:
        raise RecuperationRefusee([
            f"revue {revue.etiquette()} est encore approuvée en direct : elle n'est pas périmée, rien n'est invalidé"
        ])
    return str(live.reason)


def invalider_attestations_perimees(
    conn: Any,
    revue: RevuePerimee,
    *,
    attestation_set: str,
    raison_live: str,
    lock_timeout_ms: int = 5000,
) -> dict[str, int]:
    """Invalide les attestations #257 dans la transaction de ``conn`` ; l'appelant valide."""
    _exiger_role(conn, ROLE_ATTESTOR)
    conn.execute(f"SET LOCAL lock_timeout = {int(lock_timeout_ms)}")
    conn.execute(
        "SELECT attestation_id FROM ingestion_control.publication_attestations"
        " WHERE human_review_pull_request = %s ORDER BY attestation_id FOR UPDATE",
        (revue.pull_request,),
    ).fetchall()
    constat = analyser(prendre_instantane(conn, revue, avec_jobs=False), revue)
    _exiger(constat, attestation_set=attestation_set, job_set=None)

    motif = motif_invalidation(revue, empreinte=attestation_set, raison_live=raison_live)
    bilan = Counter[str]()
    for ligne in constat.anciennes:
        if ligne["invalidated_at"] is not None:
            bilan["deja_invalidees" if _invalidee_par_dh(ligne, attestation_set) else "preservees_autre_motif"] += 1
            continue
        ecrite = conn.execute(
            """
            UPDATE ingestion_control.publication_attestations
               SET invalidated_at = clock_timestamp(), invalidated_reason = %s
             WHERE attestation_id = %s AND invalidated_at IS NULL
            RETURNING attestation_id
            """,
            (motif, ligne["attestation_id"]),
        ).fetchone()
        if ecrite is None:
            raise RecuperationRefusee([f"attestation {ligne['attestation_id']} a changé sous verrou"])
        bilan["invalidees"] += 1
    if sum(bilan.values()) != len(constat.anciennes):
        raise RecuperationRefusee(["bilan d'invalidation incomplet — rien n'est validé"])
    return dict(sorted(bilan.items()))


# ── la nouvelle revue : avant usage, puis avant fermeture ──────────────────

REQUETE_ACTIVES = REQUETE_ATTESTATIONS.replace(
    " ORDER BY pa.attestation_id", " WHERE pa.invalidated_at IS NULL AND pa.release_id = %s ORDER BY pa.attestation_id"
)


def _normaliser_instant(valeur: Any) -> str:
    if valeur is None:
        return ""
    instant = valeur if isinstance(valeur, datetime) else datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(UTC).isoformat()


def precondition_revue(
    conn: Any,
    revue_perimee: RevuePerimee,
    *,
    pull_request: int,
    head_sha: str,
    etape: str,
    verifier_revue: Any = None,
    lire_blob: Any = None,
) -> dict[str, Any]:
    """La revue qui fonde les attestations ACTIVES est-elle utilisable maintenant ?

    Condition préalable (mise en file, lancement de Worker B), jamais un
    substitut aux vérifications que Worker B refait à chaque publication."""
    from nexus_contracts.authority_artifacts import (  # noqa: PLC0415
        parse_release_batch_publication_review_artifact,
    )

    if verifier_revue is None or lire_blob is None:
        from ingestor.ingestion_control.github_authority import (  # noqa: PLC0415
            fetch_blob_at_ref,
            verify_review,
        )

        verifier_revue = verifier_revue or verify_review
        lire_blob = lire_blob or fetch_blob_at_ref
    conn.execute("SET TRANSACTION READ ONLY")
    try:
        base = conn.execute("SELECT current_database()").fetchone()[0]
        actives = _lignes(conn, REQUETE_ACTIVES, (revue_perimee.release["release_id"],))
        jobs = _lignes(conn, REQUETE_JOBS) if etape == "worker-b" else []
    finally:
        conn.rollback()

    ecarts: list[str] = []
    if base != revue_perimee.database:
        ecarts.append(f"base {base!r}, attendu {revue_perimee.database!r}")
    if len(actives) != revue_perimee.attendu["attestations"]:
        ecarts.append(f"{len(actives)} attestation(s) active(s), attendu {revue_perimee.attendu['attestations']}")
    cles = ("human_review_repository", "human_review_pull_request", "human_review_head_sha",
            "human_review_base_sha", "human_review_review_id", "human_review_reviewer",
            "human_review_submitted_at", "human_review_challenge", "review_artifact_path",
            "review_artifact_blob_sha", "attestation_digest", "release_batch_review_digest", "review_id")
    distinctes = {tuple(str(ligne[c]) for c in cles) for ligne in actives}
    if len(distinctes) != 1:
        raise RecuperationRefusee([*ecarts, f"les attestations actives portent {len(distinctes)} revues distinctes"])
    ligne = actives[0]
    if any(_de_la_revue(x, revue_perimee) for x in actives) or ligne["human_review_pull_request"] == revue_perimee.pull_request:
        ecarts.append(f"la revue {revue_perimee.etiquette()} est fermée : elle ne fonde jamais une reprise")
    if ligne["attestation_digest"] == revue_perimee.review_digest:
        ecarts.append("l'artefact de revue périmé ne peut pas être réapprouvé tel quel : nouvel artefact exigé")
    if (ligne["human_review_pull_request"], ligne["human_review_head_sha"]) != (pull_request, head_sha):
        ecarts.append(
            f"les attestations nomment #{ligne['human_review_pull_request']}@{ligne['human_review_head_sha'][:12]}, "
            f"l'opérateur #{pull_request}@{head_sha[:12]}"
        )
    for x in actives:
        if x["protocol_version"] != PROTOCOLE_BATCH or any(x[c] != v for c, v in revue_perimee.release.items()):
            ecarts.append(f"attestation {x['attestation_id']} hors de la release V4 attendue")
            break
    if ecarts:
        raise RecuperationRefusee(ecarts)

    live = verifier_revue(repository=ligne["human_review_repository"], pull_request=pull_request, expected_head=head_sha)
    if not live.approved:
        raise RecuperationRefusee([f"revue #{pull_request} non approuvée en direct (reason={live.reason})"])
    for colonne, observe in (
        ("human_review_head_sha", live.head_sha), ("human_review_base_sha", live.base_sha),
        ("human_review_review_id", live.review_id), ("human_review_reviewer", live.reviewer),
        ("human_review_challenge", live.challenge),
    ):
        if ligne[colonne] != observe:
            ecarts.append(f"{colonne} : attesté {ligne[colonne]!r}, en direct {observe!r}")
    if _normaliser_instant(ligne["human_review_submitted_at"]) != _normaliser_instant(live.submitted_at):
        ecarts.append("human_review_submitted_at diffère de la revue en direct")
    blob = lire_blob(repository=ligne["human_review_repository"], path=ligne["review_artifact_path"], ref=head_sha)
    if blob.blob_sha != ligne["review_artifact_blob_sha"]:
        ecarts.append("l'artefact relu au head approuvé n'est pas le blob attesté")
    artefact = parse_release_batch_publication_review_artifact(blob.content)
    if artefact.digest() != ligne["attestation_digest"]:
        ecarts.append("l'artefact relu ne porte pas le digest attesté")
    if any(str(getattr(artefact, c)) != v for c, v in revue_perimee.release.items()):
        ecarts.append("l'artefact relu décrit une autre release")

    bilan: dict[str, Any] = {"review": f"#{pull_request}@{head_sha}", "active_attestations": len(actives)}
    if etape == "worker-b":
        ids = {str(x["attestation_id"]) for x in actives}
        vivants = [j for j in jobs if j["job_type"] == JOB_TYPE and j["status"] in ("queued", "running")]
        etrangers = [j for j in vivants if str((j["payload"] or {}).get("publication_attestation_id")) not in ids]
        if etrangers:
            ecarts.append(f"{len(etrangers)} job(s) vivant(s) ne nomment pas une attestation de la revue approuvée")
        couverts = {str((j["payload"] or {}).get("publication_attestation_id")) for j in vivants} & ids
        deja = {str(x["attestation_id"]) for x in actives if x["resource_state"] == ETAT_PUBLIE}
        if couverts | deja != ids:
            ecarts.append(f"{len(ids - couverts - deja)} attestation(s) active(s) sans job en file ni publication")
        bilan["live_jobs"] = len(vivants)
        bilan["already_published"] = len(deja)
    if ecarts:
        raise RecuperationRefusee(ecarts)
    return bilan


def controle_de_fermeture(conn: Any, revue_perimee: RevuePerimee) -> dict[str, Any]:
    """Rien ne dépend plus de la revue active : sa PR peut être close par un humain.

    Tant qu'un job peut encore être repris, qu'une ressource n'a pas atteint
    ``RETRIEVAL_ELIGIBLE`` ou qu'un pin manque, une reprise refera la
    vérification live (``publication_resume`` ou publisher) : la PR doit
    rester ouverte, approuvée, inchangée."""
    conn.execute("SET TRANSACTION READ ONLY")
    try:
        actives = _lignes(conn, REQUETE_ACTIVES, (revue_perimee.release["release_id"],))
        jobs = _lignes(conn, REQUETE_JOBS)
        pins = {str(p["publication_attestation_id"]): p for p in _lignes(conn, REQUETE_PINS)}
    finally:
        conn.rollback()
    ecarts: list[str] = []
    if len(actives) != revue_perimee.attendu["attestations"]:
        ecarts.append(f"{len(actives)} attestation(s) active(s), attendu {revue_perimee.attendu['attestations']}")
    ids = {str(x["attestation_id"]) for x in actives}
    non_publiees = [x for x in actives if x["resource_state"] != ETAT_PUBLIE]
    if non_publiees:
        ecarts.append(f"{len(non_publiees)} ressource(s) pas encore {ETAT_PUBLIE}")
    sans_pin = [
        x for x in actives
        if str(x["attestation_id"]) not in pins
        or pins[str(x["attestation_id"])]["publication_review_head_sha"] != x["human_review_head_sha"]
    ]
    if sans_pin:
        ecarts.append(f"{len(sans_pin)} attestation(s) sans pin de commit à leur head")
    vivants = [j for j in jobs if j["job_type"] == JOB_TYPE and j["status"] in ("queued", "running")]
    if vivants:
        ecarts.append(f"{len(vivants)} job(s) de publication encore en file ou en cours")
    reussis = {
        str((j["payload"] or {}).get("publication_attestation_id"))
        for j in jobs if j["job_type"] == JOB_TYPE and j["status"] == "succeeded"
    }
    if ids - reussis:
        ecarts.append(f"{len(ids - reussis)} attestation(s) sans job réussi")
    if ecarts:
        raise RecuperationRefusee(ecarts)
    return {"active_attestations": len(actives), "published": len(actives), "pins": len(actives)}


# ── CLI ────────────────────────────────────────────────────────────────────


def _dsn(variable: str) -> str:
    dsn = os.environ.get(variable, "").strip()
    if not dsn:
        raise RecuperationRefusee([f"{variable} absent"])
    return dsn


def _imprimer_refus(exc: RecuperationRefusee, etiquette: str) -> int:
    print(f"{etiquette}: {len(exc.ecarts)} écart(s)", file=sys.stderr)
    for ecart in exc.ecarts[:50]:
        print(f"  - {ecart}", file=sys.stderr)
    return 1


def main(argv: Iterable[str] | None = None) -> int:  # pragma: no cover - exécuté dans l'image
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repository-root", type=Path, default=RACINE_DEPOT)
    parser.add_argument("--stale-review", type=Path, default=None,
                        help=f"identité de la revue périmée (défaut : {IDENTITE_PAR_DEFAUT})")
    sous = parser.add_subparsers(dest="commande", required=True)
    p = sous.add_parser("preview")
    p.add_argument("--output", type=Path)
    p = sous.add_parser("cancel-stale-jobs")
    p.add_argument("--attestation-set-sha256", required=True)
    p.add_argument("--job-set-sha256", required=True)
    p = sous.add_parser("invalidate-stale-attestations")
    p.add_argument("--attestation-set-sha256", required=True)
    p = sous.add_parser("review-precondition")
    p.add_argument("--pull-request", required=True, type=int)
    p.add_argument("--expected-head", required=True)
    p.add_argument("--stage", required=True, choices=("enqueue", "worker-b"))
    sous.add_parser("closure-check")
    args = parser.parse_args(list(argv) if argv is not None else None)

    import psycopg

    try:
        revue = charger_revue_perimee(
            args.stale_review or args.repository_root / IDENTITE_PAR_DEFAUT, racine=args.repository_root
        )
        if args.commande == "invalidate-stale-attestations":
            raison = constater_revue_fermee(revue)
            with psycopg.connect(_dsn("PG_INGESTION_CONTROL_ATTESTOR_DSN")) as conn:
                bilan = invalider_attestations_perimees(
                    conn, revue, attestation_set=args.attestation_set_sha256, raison_live=raison
                )
                conn.commit()
            print(f"STALE_ATTESTATIONS_INVALIDATED review={revue.etiquette()} live_reason={raison} "
                  + " ".join(f"{k}={v}" for k, v in bilan.items()))
            return 0
        with psycopg.connect(_dsn("PG_INGESTION_CONTROL_DSN")) as conn:
            if args.commande == "preview":
                vue = apercu(conn, revue)
                rendu = json.dumps(vue.rendu(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                if args.output is not None:
                    args.output.write_text(rendu, encoding="utf-8")
                print(rendu, end="")
                if vue.ecarts:
                    raise RecuperationRefusee(vue.ecarts)
                print(f"RECOVERY_PREVIEW attestation_set_sha256={vue.attestation_set_sha256} "
                      f"job_set_sha256={vue.job_set_sha256}")
            elif args.commande == "cancel-stale-jobs":
                bilan = annuler_jobs_perimes(
                    conn, revue, attestation_set=args.attestation_set_sha256, job_set=args.job_set_sha256
                )
                conn.commit()
                print(f"STALE_JOBS_CANCELLED review={revue.etiquette()} "
                      + " ".join(f"{k}={v}" for k, v in bilan.items()))
            elif args.commande == "review-precondition":
                bilan = precondition_revue(
                    conn, revue, pull_request=args.pull_request, head_sha=args.expected_head, etape=args.stage
                )
                print(f"REVIEW_PRECONDITION_OK stage={args.stage} "
                      + " ".join(f"{k}={v}" for k, v in bilan.items()))
            else:
                bilan = controle_de_fermeture(conn, revue)
                print("REVIEW_CLOSURE_SAFE " + " ".join(f"{k}={v}" for k, v in bilan.items()))
    except RecuperationRefusee as exc:
        return _imprimer_refus(exc, "RECUPERATION_REFUSEE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
