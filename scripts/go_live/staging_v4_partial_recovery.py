#!/usr/bin/env python3
"""Reprise PARTIELLE gouvernée de la publication V4 sous la revue #262 (lot DI).

Worker B a publié 76 des 479 placements attestés sous #262, puis s'est heurté à
deux causes distinctes :

* 74 placements HGGSP ne peuvent PAS être publiés sous V4 : le mapping de
  sujets que V4 scelle (``authorities.subject_mapping_sha256``) ne gouverne pas
  ``hggsp``. Ils attendent une release successeur ; leurs jobs ne doivent pas
  être réclamés d'ici là (chaque réclamation consommerait une tentative) ;
* les autres ont échoué sur une limitation GitHub pendant la revérification
  live : leur autorité V4 est valide, ils peuvent être repris.

Ce script ne crée AUCUNE autorité, n'écrit RIEN et n'utilise que le rôle
``ingestion_control_app`` en lecture. Il fait deux constats :

``partial-precondition``
    avant Worker B : la base, la release, la revue #262 derrière les 479
    attestations actives ; les collections exclues exactement celles que
    l'identité versionnée nomme ; leurs ressources en ``NEEDS_REVIEW``, sans
    pin, chacune avec UN job en file, jamais épuisé ni en cours ; le périmètre
    repris sans ``dead_letter`` ni bail actif. Il rend la liste d'autorisation
    à passer à Worker B (``--collection``) et l'empreinte des jobs exclus.
``partial-closure-check``
    après Worker B : tout le périmètre repris est ``RETRIEVAL_ELIGIBLE``, pinné
    au head de la revue, avec un job réussi ; plus aucun job du périmètre en
    file ; les jobs exclus portent EXACTEMENT l'empreinte relevée avant (aucun
    n'a été réclamé, retenté ni consommé). Il n'annonce JAMAIS que la revue
    peut être fermée : tant que les exclus attendent, ``closure-check`` (DH)
    refuse, et la PR de revue reste ouverte.

La sélection elle-même n'est PAS faite ici : elle est faite par Worker B
(``claim_job(collections=…)``), jamais par une réécriture de ``status``,
``next_attempt_at`` ou ``attempt_count``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

RACINE_DEPOT = Path(__file__).resolve().parents[2]
IDENTITE_PAR_DEFAUT = "docs/reports/go_live/recovery/di_partial_v4_262.json"
KIND = "NEXUS-STAGING-V4-PARTIAL-RECOVERY-V1"
JOB_TYPE = "publication_resume"
ETAT_EN_REVUE = "NEEDS_REVIEW"
ETAT_PUBLIE = "RETRIEVAL_ELIGIBLE"
ROLE_APP = "ingestion_control_app"
CLES = frozenset({
    "kind", "release", "database", "review", "excluded_collections", "exclusion_authority", "expected",
})
CLES_ATTENDUES = frozenset({
    "active_attestations", "scope_collections", "scope_placements", "excluded_placements",
    "product_after_partial",
})


class RepriseRefusee(RuntimeError):
    def __init__(self, ecarts: list[str]) -> None:
        super().__init__("; ".join(ecarts))
        self.ecarts = ecarts


@dataclass(frozen=True)
class Perimetre:
    database: str
    release_id: str
    release_manifest_sha256: str
    repository: str
    pull_request: int
    head_sha: str
    exclues: Mapping[str, str]
    attendu: Mapping[str, Any]


def charger_perimetre(chemin: Path) -> Perimetre:
    document = json.loads(chemin.read_text(encoding="utf-8"))
    if set(document) != CLES or document.get("kind") != KIND:
        raise RepriseRefusee([f"{chemin} : identité de reprise partielle non conforme"])
    if set(document["expected"]) != CLES_ATTENDUES:
        raise RepriseRefusee([f"{chemin} : comptes attendus non conformes"])
    exclues = document["excluded_collections"]
    if not isinstance(exclues, dict) or not exclues:
        raise RepriseRefusee([f"{chemin} : aucune collection exclue nommée"])
    revue = document["review"]
    return Perimetre(
        database=str(document["database"]),
        release_id=str(document["release"]["release_id"]),
        release_manifest_sha256=str(document["release"]["release_manifest_sha256"]),
        repository=str(revue["repository"]),
        pull_request=int(revue["pull_request"]),
        head_sha=str(revue["head_sha"]),
        exclues={str(k): str(v) for k, v in exclues.items()},
        attendu=document["expected"],
    )


# ── lecture ────────────────────────────────────────────────────────────────

REQUETE_ACTIVES = """
SELECT pa.attestation_id::text AS attestation_id, pa.resource_id::text AS resource_id,
       pa.collection, pa.release_id, pa.release_manifest_sha256,
       pa.human_review_repository, pa.human_review_pull_request, pa.human_review_head_sha,
       r.resource_state
  FROM ingestion_control.publication_attestations pa
  JOIN ingestion_control.resources r ON r.resource_id = pa.resource_id
 WHERE pa.invalidated_at IS NULL AND pa.release_id = %s
 ORDER BY pa.attestation_id
"""
REQUETE_JOBS = """
SELECT job_id::text AS job_id, status, attempt_count, max_attempts, next_attempt_at,
       last_error, lease_token IS NOT NULL AS leased,
       COALESCE(lease_expires_at > clock_timestamp(), false) AS lease_active,
       payload->>'publication_attestation_id' AS attestation_id
  FROM ingestion_control.jobs
 WHERE job_type = %s
 ORDER BY job_id
"""
REQUETE_PINS = """
SELECT publication_attestation_id::text AS attestation_id, publication_review_pull_request,
       publication_review_head_sha
  FROM ingestion_control.publication_commit_pins
"""


def _lignes(conn: Any, requete: str, parametres: Any = None) -> list[dict[str, Any]]:
    curseur = conn.execute(requete, parametres)
    colonnes = [colonne.name for colonne in curseur.description]
    return [dict(zip(colonnes, ligne, strict=True)) for ligne in curseur.fetchall()]


@dataclass
class Etat:
    base: str
    role: str
    actives: list[dict[str, Any]]
    jobs: list[dict[str, Any]]
    pins: dict[str, dict[str, Any]]


def lire_etat(conn: Any, perimetre: Perimetre) -> Etat:
    """Une seule transaction en LECTURE SEULE, toujours annulée."""
    conn.execute("SET TRANSACTION READ ONLY")
    try:
        base, role = conn.execute("SELECT current_database(), current_user").fetchone()
        return Etat(
            base=str(base),
            role=str(role),
            actives=_lignes(conn, REQUETE_ACTIVES, (perimetre.release_id,)),
            jobs=_lignes(conn, REQUETE_JOBS, (JOB_TYPE,)),
            pins={str(p["attestation_id"]): p for p in _lignes(conn, REQUETE_PINS)},
        )
    finally:
        conn.rollback()


def _instant(valeur: Any) -> str:
    return valeur.isoformat() if isinstance(valeur, datetime) else str(valeur)


def empreinte_des_jobs_exclus(jobs: Iterable[Mapping[str, Any]]) -> str:
    """Tout ce qu'une réclamation, une tentative ou un report changerait."""
    lignes = sorted(
        [
            str(j["job_id"]), str(j["attestation_id"]), str(j["status"]), int(j["attempt_count"]),
            int(j["max_attempts"]), _instant(j["next_attempt_at"]), str(j["last_error"] or ""),
            bool(j["leased"]),
        ]
        for j in jobs
    )
    return hashlib.sha256(
        json.dumps(lignes, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass
class Partition:
    portee: list[dict[str, Any]]
    exclues: list[dict[str, Any]]
    jobs_par_attestation: dict[str, list[dict[str, Any]]]


def _partition(etat: Etat, perimetre: Perimetre) -> tuple[Partition, list[str]]:
    ecarts: list[str] = []
    if etat.base != perimetre.database:
        ecarts.append(f"base {etat.base!r}, attendu {perimetre.database!r}")
    if etat.role != ROLE_APP:
        ecarts.append(f"rôle {etat.role!r}, attendu {ROLE_APP}")
    attendu = perimetre.attendu
    if len(etat.actives) != attendu["active_attestations"]:
        ecarts.append(f"{len(etat.actives)} attestation(s) active(s), attendu {attendu['active_attestations']}")
    revues = {
        (a["human_review_repository"], a["human_review_pull_request"], a["human_review_head_sha"])
        for a in etat.actives
    }
    if revues != {(perimetre.repository, perimetre.pull_request, perimetre.head_sha)}:
        ecarts.append(
            f"les attestations actives portent {len(revues)} revue(s), attendu "
            f"#{perimetre.pull_request}@{perimetre.head_sha}"
        )
    if {a["release_manifest_sha256"] for a in etat.actives} - {perimetre.release_manifest_sha256}:
        ecarts.append("une attestation active nomme un autre manifeste de release")
    collections = {a["collection"] for a in etat.actives}
    absentes = sorted(set(perimetre.exclues) - collections)
    if absentes:
        ecarts.append(f"collections exclues absentes de la release attestée : {absentes}")
    portee = [a for a in etat.actives if a["collection"] not in perimetre.exclues]
    exclues = [a for a in etat.actives if a["collection"] in perimetre.exclues]
    if len(collections - set(perimetre.exclues)) != attendu["scope_collections"]:
        ecarts.append(
            f"{len(collections - set(perimetre.exclues))} collection(s) reprise(s), "
            f"attendu {attendu['scope_collections']}"
        )
    if len(portee) != attendu["scope_placements"]:
        ecarts.append(f"{len(portee)} placement(s) repris, attendu {attendu['scope_placements']}")
    if len(exclues) != attendu["excluded_placements"]:
        ecarts.append(f"{len(exclues)} placement(s) exclu(s), attendu {attendu['excluded_placements']}")
    jobs: dict[str, list[dict[str, Any]]] = {}
    for job in etat.jobs:
        jobs.setdefault(str(job["attestation_id"]), []).append(job)
    return Partition(portee=portee, exclues=exclues, jobs_par_attestation=jobs), ecarts


def _jobs_exclus(partition: Partition) -> list[dict[str, Any]]:
    return [j for a in partition.exclues for j in partition.jobs_par_attestation.get(a["attestation_id"], [])]


def _ecarts_des_exclus(partition: Partition, etat: Etat) -> list[str]:
    ecarts: list[str] = []
    for attestation in partition.exclues:
        ident = attestation["attestation_id"]
        if attestation["resource_state"] != ETAT_EN_REVUE:
            ecarts.append(f"exclue {ident} : ressource {attestation['resource_state']}, attendu {ETAT_EN_REVUE}")
        if ident in etat.pins:
            ecarts.append(f"exclue {ident} : un pin de commit existe déjà")
        jobs = partition.jobs_par_attestation.get(ident, [])
        vivants = [j for j in jobs if j["status"] in ("queued", "running")]
        if len(vivants) != 1:
            ecarts.append(f"exclue {ident} : {len(vivants)} job(s) vivant(s), attendu 1")
            continue
        job = vivants[0]
        if job["status"] != "queued" or job["leased"]:
            ecarts.append(f"exclue {ident} : job {job['job_id']} {job['status']} (bail={job['leased']})")
        if int(job["attempt_count"]) >= int(job["max_attempts"]):
            ecarts.append(f"exclue {ident} : job {job['job_id']} sans tentative restante")
        if any(j["status"] == "dead_letter" for j in jobs):
            ecarts.append(f"exclue {ident} : un job est déjà en dead_letter")
    return ecarts


def precondition_partielle(conn: Any, perimetre: Perimetre) -> dict[str, Any]:
    etat = lire_etat(conn, perimetre)
    partition, ecarts = _partition(etat, perimetre)
    ecarts += _ecarts_des_exclus(partition, etat)
    a_publier = epingles_en_attente = promues_sans_pin = deja = 0
    for attestation in partition.portee:
        ident = attestation["attestation_id"]
        jobs = partition.jobs_par_attestation.get(ident, [])
        if any(j["status"] == "dead_letter" for j in jobs):
            ecarts.append(f"reprise {ident} : job en dead_letter — hors de ce lot, jamais réanimé à la main")
        if any(j["lease_active"] for j in jobs):
            ecarts.append(f"reprise {ident} : bail ACTIF — un Worker B tourne encore")
        reussi = any(j["status"] == "succeeded" for j in jobs)
        vivant = [j for j in jobs if j["status"] in ("queued", "running")]
        if reussi and attestation["resource_state"] == ETAT_PUBLIE:
            deja += 1
            continue
        if len(vivant) != 1:
            ecarts.append(f"reprise {ident} : {len(vivant)} job(s) vivant(s), attendu 1")
            continue
        a_publier += 1
        # Promue (avec ou sans pin), le même job reprend sans nouvelle
        # promotion ; un pin exige toujours une ressource promue.
        if ident in etat.pins:
            epingles_en_attente += 1
            if attestation["resource_state"] != ETAT_PUBLIE:
                ecarts.append(f"reprise {ident} : pin présent mais ressource {attestation['resource_state']}")
        elif attestation["resource_state"] == ETAT_PUBLIE:
            promues_sans_pin += 1
        elif attestation["resource_state"] != ETAT_EN_REVUE:
            ecarts.append(f"reprise {ident} : ressource {attestation['resource_state']}")
    if ecarts:
        raise RepriseRefusee(ecarts)
    return {
        "claim_scope": sorted({a["collection"] for a in partition.portee}),
        "excluded_jobs_sha256": empreinte_des_jobs_exclus(_jobs_exclus(partition)),
        "already_published": deja,
        "to_publish": a_publier,
        "pinned_awaiting_product": epingles_en_attente,
        "promoted_awaiting_pin": promues_sans_pin,
        "excluded_pending": len(partition.exclues),
    }


def controle_partiel(conn: Any, perimetre: Perimetre, *, empreinte_exclus: str) -> dict[str, Any]:
    etat = lire_etat(conn, perimetre)
    partition, ecarts = _partition(etat, perimetre)
    ecarts += _ecarts_des_exclus(partition, etat)
    for attestation in partition.portee:
        ident = attestation["attestation_id"]
        jobs = partition.jobs_par_attestation.get(ident, [])
        pin = etat.pins.get(ident)
        if attestation["resource_state"] != ETAT_PUBLIE:
            ecarts.append(f"reprise {ident} : ressource {attestation['resource_state']}")
        if pin is None or pin["publication_review_head_sha"] != perimetre.head_sha:
            ecarts.append(f"reprise {ident} : pas de pin au head de #{perimetre.pull_request}")
        if not any(j["status"] == "succeeded" for j in jobs):
            ecarts.append(f"reprise {ident} : aucun job réussi")
        if any(j["status"] in ("queued", "running") for j in jobs):
            ecarts.append(f"reprise {ident} : job encore en file ou en cours")
    observee = empreinte_des_jobs_exclus(_jobs_exclus(partition))
    if observee != empreinte_exclus:
        ecarts.append(
            f"jobs exclus modifiés depuis la précondition : {observee}, attendu {empreinte_exclus} "
            "(réclamés, retentés ou reportés — interdit)"
        )
    if ecarts:
        raise RepriseRefusee(ecarts)
    return {
        "published": len(partition.portee),
        "excluded_pending": len(partition.exclues),
        "excluded_jobs_sha256": observee,
        "review_closure": "NOT_SAFE",
    }


# ── les exclusions sont dérivées de l'autorité scellée, jamais déclarées ───


def exclusions_derivees(racine: Path, identite: Mapping[str, Any]) -> dict[str, str]:
    """Les collections que les mappings SCELLÉS de la release ne gouvernent pas.

    Même règle que le contrôle de démarrage de Worker B
    (``ungoverned_release_collections``), sur les mêmes fichiers liés par les
    empreintes du manifeste. L'identité versionnée doit nommer exactement ce
    résultat : une exclusion n'est jamais choisie à la main."""
    import yaml  # noqa: PLC0415

    from ingestor.multilevel_evidence import load_multilevel_candidate_inventory  # noqa: PLC0415
    from ingestor.multilevel_mapping import load_multilevel_mapping  # noqa: PLC0415
    from ingestor.multilevel_verified_placement import ungoverned_release_collections  # noqa: PLC0415

    autorite = identite["exclusion_authority"]
    manifeste_chemin = racine / autorite["release_manifest"]
    octets = manifeste_chemin.read_bytes()
    if hashlib.sha256(octets).hexdigest() != identite["release"]["release_manifest_sha256"]:
        raise RepriseRefusee([f"{autorite['release_manifest']} ne porte pas l'empreinte de la release"])
    autorites = json.loads(octets)["authorities"]
    mappings = autorite["mappings"]
    mapping = load_multilevel_mapping(
        levels_path=racine / mappings["levels"],
        expected_levels_sha256=autorites["level_mapping_sha256"],
        subjects_path=racine / mappings["subjects"],
        expected_subjects_sha256=autorites["subject_mapping_sha256"],
        document_types_path=racine / mappings["document_types"],
        expected_document_types_sha256=autorites["document_type_mapping_sha256"],
    )
    inventaire = load_multilevel_candidate_inventory(
        manifeste_chemin.parent / "candidate_inventory.json",
        expected_sha256=autorites["candidate_inventory_sha256"],
    )
    configuration = yaml.safe_load((racine / autorite["collection_config"]).read_text(encoding="utf-8"))
    return ungoverned_release_collections(
        placements=inventaire.placements, mapping=mapping, collection_config=configuration
    )


def verifier_exclusions(racine: Path, chemin_identite: Path) -> None:
    identite = json.loads(chemin_identite.read_text(encoding="utf-8"))
    derivees = exclusions_derivees(racine, identite)
    if derivees != identite["excluded_collections"]:
        raise RepriseRefusee([
            f"exclusions déclarées {sorted(identite['excluded_collections'])} ≠ dérivées de l'autorité "
            f"scellée {sorted(derivees)}"
        ])


# ── CLI ────────────────────────────────────────────────────────────────────


def _imprimer_refus(exc: RepriseRefusee) -> int:
    print(f"REPRISE_PARTIELLE_REFUSEE: {len(exc.ecarts)} écart(s)", file=sys.stderr)
    for ecart in exc.ecarts[:50]:
        print(f"  - {ecart}", file=sys.stderr)
    return 1


def main(argv: Iterable[str] | None = None) -> int:  # pragma: no cover - exécuté dans l'image
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repository-root", type=Path, default=RACINE_DEPOT)
    parser.add_argument("--identity", type=Path, default=None)
    sous = parser.add_subparsers(dest="commande", required=True)
    sous.add_parser("partial-precondition")
    p = sous.add_parser("partial-closure-check")
    p.add_argument("--excluded-jobs-sha256", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)

    import psycopg

    chemin = args.identity or args.repository_root / IDENTITE_PAR_DEFAUT
    try:
        perimetre = charger_perimetre(chemin)
        verifier_exclusions(args.repository_root, chemin)
        dsn = os.environ.get("PG_INGESTION_CONTROL_DSN", "").strip()
        if not dsn:
            raise RepriseRefusee(["PG_INGESTION_CONTROL_DSN absent"])
        with psycopg.connect(dsn) as conn:
            if args.commande == "partial-precondition":
                bilan = precondition_partielle(conn, perimetre)
                print("PARTIAL_PRECONDITION_OK " + " ".join(
                    f"{k}={','.join(v) if isinstance(v, list) else v}" for k, v in bilan.items()
                ))
            else:
                bilan = controle_partiel(conn, perimetre, empreinte_exclus=args.excluded_jobs_sha256)
                print("DI_PARTIAL_PUBLICATION_COMPLETE " + " ".join(f"{k}={v}" for k, v in bilan.items()))
    except RepriseRefusee as exc:
        return _imprimer_refus(exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
