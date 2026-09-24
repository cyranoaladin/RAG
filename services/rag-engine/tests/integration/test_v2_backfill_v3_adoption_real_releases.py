"""La chaîne staging de V3 par adoption de V2, sur les VRAIES releases (lots CY, CZ).

Ce module rejoue, par les vrais CLI et sur les octets réels, le chemin
d'ADOPTION (ADR-0059, ADR-0060) :

1. état historique : les 479 placements de V2 écrits par le vrai Worker A
   sous les autorisations RÉELLES ``lot41a-staging-v2-*-r2`` (LOT41A-V1),
   puis privés de leurs attributions, comme sur le staging ;
2. ``--only-attributions`` sur V2, sous une readiness de staging nommant V2 ;
3. ``adopt-predecessor-release`` pour V3 (manifeste de transfert au nom de V3) ;
4. enregistrement des onze r3, puis ``bind-publication-authorities`` ;
5. ``propose-release-batch-review`` (chaîne PII réelle), approbation sur la
   forge du banc, ``record-release-batch-attestation`` ;
6. Worker B qualifié par une readiness de STAGING nommant V3.

V3 n'est PAS publiable : ses placements et ses profils portent le programme
``EDUSCOL_CORPUS_20260808``, son registre de programmes les versions BOEN.
Worker B le refuse placement par placement — ``test_4`` le constate. Son
successeur V4 (programmes officiels) est prouvé par
``test_v4_staging_direct_real_chain``.

Chaque contre-épreuve est un test : readiness d'une autre release, manifeste
de profils altéré ou autre, chaîne PII non autorisée, autorité V1 sans
liaison, r3 étrangère ou incomplète, readiness de staging sous production.

Prérequis : ``NEXUS_REAL_RELEASE_ADOPTION=1``, ``NEXUS_REAL_RELEASE_ARTIFACT_MIRRORS``,
``RAG_EMBEDDING_MODEL_CACHE_DIR`` (E5, inventaire 58ad18db…), Docker.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _banc_releases_reelles import (  # noqa: E402
    CHAINE_PII,
    MODELE_E5_ENV,
    PROFILE_MANIFEST_V2,
    PROFILES_V2,
    REPOSITORY_ROOT,
    TRANSFER_V2,
    V2_DIR,
    V2_ID,
    V2_MANIFEST_SHA256,
    V3_DIR,
    V3_ID,
    V3_MANIFEST_SHA256,
    acces_github,
    arguments_de_proposition,
    arguments_worker_a,
    arguments_worker_b,
    champs,
    compte_par_table,
    creer_les_jobs,
    ecarts,
    empreinte,
    enregistrer,
    erreurs_d_iteration,
    lancer_worker_b,
    magasin_reel,
    produit,
    r2_reelles,
    readiness,
    refus_au_demarrage,
    remplacer,
    run,
    sha,
    transfert_nomme,
)
from _local_github import REPOSITORY, VALID_TOKEN, LocalGitHub, local_github_server  # noqa: E402
from _pg_authority import (  # noqa: E402
    app_dsn,
    attestor_dsn,
    authority_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    start_rag_product_postgres,
    superuser_dsn,
)

pytestmark = [pytest.mark.integration, requires_docker]

if os.environ.get("NEXUS_REAL_RELEASE_ADOPTION") != "1":
    pytest.skip(
        "real V2 backfill / V3 adoption not requested (NEXUS_REAL_RELEASE_ADOPTION=1)",
        allow_module_level=True,
    )

def _r3_derivees() -> dict[str, tuple[str, bytes]]:
    """Les onze r3 de V3, dérivées comme le faisait
    ``scripts/go_live/build_lot41a_r3_authorizations.py`` (5543436d), retiré
    depuis au profit des r4 de V4 : chaque r2 réelle portée au protocole
    LOT41A-V2, avec la liste POSITIVE des contenus que V3 place dans sa
    collection et l'empreinte canonique du manifeste de profils de V3."""
    from nexus_contracts.authority_artifacts import ScopeAuthorizationArtifactV2  # noqa: PLC0415

    autorites = json.loads((V3_DIR / "production-profile-gate.release.json").read_bytes())["authorities"]
    contenus: dict[str, list[str]] = {}
    for sujet in sorted((V3_DIR / "subjects").glob("*.release.json")):
        document = json.loads(sujet.read_bytes())
        contenus[document["collection"]] = sorted({str(p["artifact_id"]) for p in document["placements"]})
    derivees: dict[str, tuple[str, bytes]] = {}
    for collection, (identifiant_r2, octets) in r2_reelles().items():
        r2 = json.loads(octets)
        identifiant = identifiant_r2.replace("lot41a-staging-v2-", "lot41a-staging-v3-").removesuffix("-r2") + "-r3"
        artefact = ScopeAuthorizationArtifactV2.model_validate({
            **{k: r2[k] for k in (
                "allowed_domains", "decision", "exclusions", "profile_fingerprint",
                "profile_id", "profile_version", "rights_categories", "scope", "valid_until",
            )},
            "allowed_content_sha256": contenus[collection],
            "authorization_id": identifiant,
            "manifest_digest": autorites["profile_manifest_sha256"],
            "pii_absence_attested": True,
            "pii_absence_evidence": f"v3 pii_evidence.json@sha256:{autorites['pii_evidence_sha256']}",
            "protocol_version": "LOT41A-V2",
            "valid_from": "2026-09-24T00:00:00.000000Z",
        })
        derivees[collection] = (identifiant, artefact.canonical_bytes())
    assert len(derivees) == 11
    return derivees

#: Le sous-ensemble soumis à Worker B : quatre placements, quatre collections,
#: dont un contenu DETECTED_REVIEWED_ACCEPTED (ebe2d96d…) et un contenu placé
#: dans deux collections (8eb23c91…).
PLACEMENTS_PUBLIES = (
    ("rag_nexus_dgemc_terminale_option", "ebe2d96d2460"),
    ("rag_nexus_svt_premiere_specialite", "8eb23c91b035"),
    ("rag_nexus_svt_terminale_specialite", "8eb23c91b035"),
    ("rag_nexus_hlp_premiere_specialite", "8d8d833b4051"),
)
CONTENU_DRA = "ebe2d96d2460"

_RUN_ID = uuid.uuid4().hex[:10]
REVUE_V3 = f"lot42-release-batch-v3-reelle-{_RUN_ID}"


def _enregistrer(
    *, github: LocalGitHub, env: Mapping[str, str], documents: Sequence[tuple[str, bytes]], numero: int
) -> None:
    enregistrer(github=github, env=env, documents=documents, numero=numero, graine=_RUN_ID)


def _arguments_worker_a(
    *, magasin: Path, autorisations: Mapping[str, str], extra: Sequence[str] = ()
) -> list[str]:
    return list[str](arguments_worker_a(
        release_dir=V2_DIR, profiles_dir=PROFILES_V2, transfert=TRANSFER_V2,
        magasin=magasin, autorisations=autorisations, extra=extra,
    ))


def _arguments_d_adoption(transfert: Path) -> list[str]:
    return [
        "adopt-predecessor-release",
        "--release-id", V3_ID,
        "--release-dir", str(V3_DIR),
        "--release-manifest-sha256", sha(V3_DIR / "production-profile-gate.release.json"),
        "--artifacts-release-sha256", sha(V3_DIR / "artifacts.release.json"),
        "--candidate-inventory-sha256", sha(V3_DIR / "candidate_inventory.json"),
        "--transfer-manifest-path", str(transfert),
        "--transfer-manifest-sha256", sha(transfert),
        "--predecessor-release-id", V2_ID,
        "--predecessor-release-manifest-sha256", V2_MANIFEST_SHA256,
        "--adopted-by", "real-release-adoption-bench",
    ]


def _arguments_de_liaison(par_collection: Mapping[str, str]) -> list[str]:
    args = ["bind-publication-authorities", "--release-id", V3_ID, "--bound-by", "real-release-bench"]
    for collection, identifiant in sorted(par_collection.items()):
        args += ["--scope-authorization", f"{collection}={identifiant}"]
    return args


def _arguments_de_proposition_v3(transfert: Path, *, revue: str) -> list[str]:
    return list[str](arguments_de_proposition(
        release_dir=V3_DIR, release_id=V3_ID, transfert=transfert, revue=revue
    ))


def _etat_historique(pg: dict[str, str]) -> dict[str, Any]:
    """Les identités acquises de V2 — ce qu'aucune étape n'a le droit de modifier."""
    with psycopg.connect(superuser_dsn(pg)) as conn:
        ressources = conn.execute(
            "SELECT resource_id, collection, dedup_key, pipeline_kind, run_id"
            "  FROM ingestion_control.resources ORDER BY resource_id"
        ).fetchall()
        artefacts = conn.execute(
            "SELECT artifact_id, resource_id, sha256, run_id, payload"
            "  FROM ingestion_control.artifacts ORDER BY artifact_id"
        ).fetchall()
        candidats = conn.execute("SELECT * FROM ingestion_control.resource_candidates ORDER BY 1").fetchall()
        conn.rollback()
    return {
        "resources": empreinte(ressources),
        "artifacts": empreinte(artefacts),
        "resource_candidates": empreinte(candidats),
        "counts": (len(ressources), len(artefacts), len(candidats)),
        "release_ids": sorted({ligne[4]["release_id"] for ligne in artefacts}),
        "acquisition_authorities": sorted({ligne[4]["scope_authorization_id"] for ligne in artefacts}),
    }


# --- Fixtures -----------------------------------------------------------------


@pytest.fixture(scope="module")
def control_pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("v3-real-chain")


@pytest.fixture(scope="module")
def produit_pg() -> Iterator[dict[str, str]]:
    yield from start_rag_product_postgres("v3-real-product")


@pytest.fixture(scope="module")
def banc(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Le matériel partagé : magasin réel, manifeste de transfert V3 (TEST),
    readiness de staging, modèle E5."""
    tmp_path = tmp_path_factory.mktemp("banc")
    modele = os.environ.get(MODELE_E5_ENV, "").strip()
    if not modele:
        pytest.fail(f"{MODELE_E5_ENV} is required: Worker B really embeds")
    transfert_v3 = transfert_nomme(tmp_path, V3_ID)
    jeton = tmp_path / "github-token"
    jeton.write_text(VALID_TOKEN, encoding="utf-8")
    return {
        "tmp_path": tmp_path,
        "magasin": magasin_reel(tmp_path),
        "transfert_v3": transfert_v3,
        "jeton": jeton,
        "modele": Path(modele),
        "readiness_v2": readiness(tmp_path, release_id=V2_ID, manifest_sha256=V2_MANIFEST_SHA256),
        "readiness_v3": readiness(tmp_path, release_id=V3_ID, manifest_sha256=V3_MANIFEST_SHA256),
    }


def _jusqu_a_l_adoption(
    pg: dict[str, str], banc: Mapping[str, Any], github: LocalGitHub
) -> dict[str, Any]:
    """État historique (r2 réelles, V1) → rattrapage V2 → adoption V3.

    Chaque étape est ASSERTÉE : un échec arrête à l'étape qui a échoué."""
    r2 = r2_reelles()
    base = {"PG_INGESTION_CONTROL_DSN": app_dsn(pg)}
    with local_github_server(github) as github_url:
        acces = acces_github(github_url, banc["jeton"])
        _enregistrer(
            github=github,
            env={"PG_INGESTION_CONTROL_AUTHORITY_DSN": authority_dsn(pg), **acces},
            documents=[r2[c] for c in sorted(r2)],
            numero=8100,
        )
        autorisations_r2 = {collection: identifiant for collection, (identifiant, _o) in r2.items()}
        ingere = run(
            "ingestor.ingestion_worker.sealed_release_ingestion_cli",
            _arguments_worker_a(magasin=banc["magasin"], autorisations=autorisations_r2),
            {**base, **banc["readiness_v2"], **acces},
        )
    assert ingere.returncode == 0, ingere.stderr
    fin = champs(ingere.stdout, "SEALED_RELEASE_INGESTION_DONE")
    assert (fin["resources"], fin["artifacts"], fin["terminal_state"]) == ("479", "479", "NEEDS_REVIEW")

    # L'état de staging : lignes écrites avant que Worker A n'établisse les
    # attributions.
    with psycopg.connect(superuser_dsn(pg)) as conn:
        retirees = conn.execute("DELETE FROM ingestion_control.artifact_attributions RETURNING 1").fetchall()
        conn.commit()
    assert len(retirees) == 479
    historique = _etat_historique(pg)
    assert historique["counts"] == (479, 479, 479)
    assert historique["acquisition_authorities"] == sorted(autorisations_r2.values())

    rattrape = run(
        "ingestor.ingestion_worker.sealed_release_ingestion_cli",
        _arguments_worker_a(
            magasin=banc["magasin"], autorisations=autorisations_r2, extra=["--only-attributions"]
        ),
        {**base, **banc["readiness_v2"]},
    )
    assert rattrape.returncode == 0, rattrape.stderr
    bilan = champs(rattrape.stdout, "SEALED_RELEASE_ATTRIBUTION_BACKFILL_DONE")
    assert (bilan["examined"], bilan["written"], bilan["missing_rows"]) == ("479", "479", "0")

    adopte = run(
        "ingestor.ingestion_worker.attest_publication_cli",
        _arguments_d_adoption(banc["transfert_v3"]),
        {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(pg)},
    )
    assert adopte.returncode == 0, adopte.stderr
    adoption = champs(adopte.stdout, "ADOPTION_RECORDED")
    assert (adoption["placements"], adoption["written"], adoption["currentness"]) == (
        "479", "479", "official_snapshot",
    )
    assert _etat_historique(pg) == historique
    return {
        "historique": historique,
        "r2": autorisations_r2,
        "rattrapage": rattrape.stdout.strip().splitlines()[-1],
        "adoption": adopte.stdout.strip(),
    }


@pytest.fixture(scope="module")
def github() -> LocalGitHub:
    return LocalGitHub()


@pytest.fixture(scope="module")
def adopte(control_pg: dict[str, str], banc: dict[str, Any], github: LocalGitHub) -> dict[str, Any]:
    etat = _jusqu_a_l_adoption(control_pg, banc, github)
    print("REAL_CHAIN_BACKFILL", etat["rattrapage"])
    print("REAL_CHAIN_ADOPTION", etat["adoption"])
    return etat


@pytest.fixture(scope="module")
def r3_enregistrees(
    adopte: dict[str, Any], control_pg: dict[str, str], banc: dict[str, Any], github: LocalGitHub
) -> dict[str, str]:
    """Les onze r3, enregistrées par le vrai CLI d'autorité — pas encore liées."""
    r3 = _r3_derivees()
    with local_github_server(github) as github_url:
        _enregistrer(
            github=github,
            env={
                "PG_INGESTION_CONTROL_AUTHORITY_DSN": authority_dsn(control_pg),
                **acces_github(github_url, banc["jeton"]),
            },
            documents=[r3[c] for c in sorted(r3)],
            numero=8200,
        )
    return {collection: identifiant for collection, (identifiant, _o) in r3.items()}


@pytest.fixture(scope="module")
def lie(
    r3_enregistrees: dict[str, str],
    control_pg: dict[str, str],
    banc: dict[str, Any],
    github: LocalGitHub,
) -> dict[str, Any]:
    """Les onze r3 liées aux 479 placements adoptés."""
    par_collection = r3_enregistrees
    with local_github_server(github) as github_url:
        acces = acces_github(github_url, banc["jeton"])
        avant = compte_par_table(control_pg)
        lier = run(
            "ingestor.ingestion_worker.attest_publication_cli",
            _arguments_de_liaison(par_collection),
            {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg), **acces},
        )
        print("REAL_CHAIN_BIND", lier.stdout.strip(), lier.stderr.strip())
        assert lier.returncode == 0, lier.stderr
        rejoue = run(
            "ingestor.ingestion_worker.attest_publication_cli",
            _arguments_de_liaison(par_collection),
            {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg), **acces},
        )
    assert rejoue.returncode == 0, rejoue.stderr
    return {
        "r3": par_collection,
        "sortie": lier.stdout.strip(),
        "rejeu": rejoue.stdout.strip(),
        "ecarts": ecarts(avant, compte_par_table(control_pg)),
    }


@pytest.fixture(scope="module")
def atteste(
    lie: dict[str, Any], control_pg: dict[str, str], banc: dict[str, Any], github: LocalGitHub
) -> dict[str, Any]:
    """Proposition (sans GitHub), approbation sur la forge du banc, enregistrement."""
    attestor = {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg)}
    propose = run(
        "ingestor.ingestion_worker.attest_publication_cli",
        _arguments_de_proposition_v3(banc["transfert_v3"], revue=REVUE_V3),
        attestor,
    )
    print("REAL_CHAIN_PROPOSE", propose.stdout.splitlines()[:3], propose.stderr[-1500:])
    assert propose.returncode == 0, propose.stderr
    chemin = next(
        ligne.split(" ", 1)[1].strip()
        for ligne in propose.stdout.splitlines()
        if ligne.startswith("REVIEW_ARTIFACT_PATH ")
    )
    octets = propose.stdout[propose.stdout.index("{") :].encode("utf-8")
    tete = hashlib.sha1(f"revue-v3:{_RUN_ID}".encode()).hexdigest()
    github.add_approved_pr(number=8401, head_sha=tete, base_sha="9" * 40, review_id=8411)
    github.put_blob(path=chemin, ref=tete, content=octets)
    with local_github_server(github) as github_url:
        enregistre = run(
            "ingestor.ingestion_worker.attest_publication_cli",
            [
                "record-release-batch-attestation",
                "--release-id", V3_ID,
                "--review-id", REVUE_V3,
                "--repository", REPOSITORY,
                "--pull-request", "8401",
                "--expected-head", tete,
                "--review-artifact-path", chemin,
            ],
            {**attestor, **acces_github(github_url, banc["jeton"])},
        )
    print("REAL_CHAIN_RECORD", enregistre.stdout.strip()[-600:], enregistre.stderr[-1500:])
    assert enregistre.returncode == 0, enregistre.stderr
    return {
        "propose": propose.stdout.splitlines()[0],
        "revue": json.loads(octets),
        "record": enregistre.stdout.strip().splitlines()[-1],
    }


def _lancer_worker_b(
    control_pg: dict[str, str],
    produit_pg: dict[str, str],
    banc: Mapping[str, Any],
    github: LocalGitHub,
    *,
    arguments: Sequence[str],
    readiness_env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    sortie: subprocess.CompletedProcess[str] = lancer_worker_b(
        control_pg, produit_pg, github=github, jeton=banc["jeton"],
        readiness_env=readiness_env or banc["readiness_v3"], arguments=arguments,
    )
    return sortie


def _arguments_b(banc: Mapping[str, Any]) -> list[str]:
    return list[str](arguments_worker_b(
        release_dir=V3_DIR,
        profiles_dir=PROFILES_V2,
        profile_manifest=PROFILE_MANIFEST_V2,
        magasin=banc["magasin"],
        transfert=banc["transfert_v3"],
        modele=banc["modele"],
    ))


@pytest.fixture(scope="module")
def publie(
    atteste: dict[str, Any],
    control_pg: dict[str, str],
    produit_pg: dict[str, str],
    banc: dict[str, Any],
    github: LocalGitHub,
) -> dict[str, Any]:
    """Worker B, readiness de staging nommant V3, sur le sous-ensemble borné."""
    jobs = creer_les_jobs(control_pg, release_id=V3_ID, cibles=PLACEMENTS_PUBLIES)
    debut = time.monotonic()
    worker = _lancer_worker_b(
        control_pg, produit_pg, banc, github,
        arguments=[*_arguments_b(banc), "--poll-interval-s", "1", "--max-iterations", str(len(jobs))],
    )
    duree = time.monotonic() - debut
    print("REAL_CHAIN_WORKER_B_SECONDS", round(duree, 1))
    print("REAL_CHAIN_WORKER_B_STDOUT", worker.stdout[-4000:])
    print("REAL_CHAIN_WORKER_B_STDERR", worker.stderr[-4000:])
    assert worker.returncode == 0, worker.stderr
    return {
        "jobs": jobs,
        "sortie": worker.stdout,
        "erreurs": erreurs_d_iteration(worker.stderr),
        "succes": worker.stdout.count("status=succeeded") == len(jobs),
        "secondes": duree,
        "produit": produit(produit_pg),
    }


# --- La chaîne ----------------------------------------------------------------


def test_les_releases_reelles_sont_celles_attendues() -> None:
    """Un skip n'est pas une exécution : les octets réels sont vérifiés ici."""
    assert sha(V2_DIR / "production-profile-gate.release.json") == V2_MANIFEST_SHA256
    assert sha(V3_DIR / "production-profile-gate.release.json") == V3_MANIFEST_SHA256
    assert TRANSFER_V2.is_file()
    assert len(list(PROFILES_V2.glob("*.yml"))) == 11
    pii = json.loads((V3_DIR / "pii_evidence.json").read_bytes())
    statuts = {r["content_sha256"][:12]: r["status"] for r in pii["results"]}
    assert statuts[CONTENU_DRA] == "DETECTED_REVIEWED_ACCEPTED"


def test_1_rattrapage_v2_puis_adoption_v3_sous_autorites_r2_reelles(adopte: dict[str, Any]) -> None:
    assert "examined=479 written=479" in adopte["rattrapage"]
    assert "placements=479 written=479" in adopte["adoption"]


def test_e_une_r3_etrangere_ou_incomplete_n_est_pas_liee(
    r3_enregistrees: dict[str, str],
    control_pg: dict[str, str],
    banc: dict[str, Any],
    github: LocalGitHub,
) -> None:
    """AVANT toute liaison : une r3 d'une autre collection, ou une r3 qui ne
    nomme pas un contenu, ne lie rien — pas même les placements qu'elle couvre."""
    from nexus_contracts.authority_artifacts import ScopeAuthorizationArtifactV2  # noqa: PLC0415

    r3 = _r3_derivees()
    document = json.loads(r3["rag_nexus_dgemc_terminale_option"][1])
    retire = document["allowed_content_sha256"][0]
    document["authorization_id"] = f"lot41a-bench-dgemc-partielle-{_RUN_ID}"
    document["allowed_content_sha256"] = document["allowed_content_sha256"][1:]
    partielle = ScopeAuthorizationArtifactV2.model_validate(document)
    # Une autorité qui nomme TOUS les contenus de SVT terminale, mais dont le
    # scope est SVT première : seule la collection la disqualifie.
    document = json.loads(r3["rag_nexus_svt_premiere_specialite"][1])
    document["authorization_id"] = f"lot41a-bench-svt-autre-collection-{_RUN_ID}"
    document["allowed_content_sha256"] = json.loads(r3["rag_nexus_svt_terminale_specialite"][1])[
        "allowed_content_sha256"
    ]
    autre_collection = ScopeAuthorizationArtifactV2.model_validate(document)
    with local_github_server(github) as github_url:
        acces = acces_github(github_url, banc["jeton"])
        _enregistrer(
            github=github,
            env={"PG_INGESTION_CONTROL_AUTHORITY_DSN": authority_dsn(control_pg), **acces},
            documents=[
                (partielle.authorization_id, partielle.canonical_bytes()),
                (autre_collection.authorization_id, autre_collection.canonical_bytes()),
            ],
            numero=8300,
        )
        avant = compte_par_table(control_pg)
        assert avant["sealed_release_publication_authorizations"] == 0
        attestor = {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg), **acces}
        etrangere = dict(r3_enregistrees)
        etrangere["rag_nexus_svt_terminale_specialite"] = r3_enregistrees["rag_nexus_svt_premiere_specialite"]
        incomplete = dict(r3_enregistrees)
        incomplete["rag_nexus_dgemc_terminale_option"] = partielle.authorization_id
        mauvaise_collection = dict(r3_enregistrees)
        mauvaise_collection["rag_nexus_svt_terminale_specialite"] = autre_collection.authorization_id
        # Une r3 d'une autre collection échoue sur le premier placement examiné :
        # contenu absent de sa liste, ou contenu partagé mais autre collection
        # (l'ordre des ressources est celui de leurs identifiants aléatoires).
        for nom, mapping, motifs in (
            ("r3 d'une autre collection", etrangere, ("does not name content", "covers collection")),
            ("contenus complets, autre collection", mauvaise_collection, ("covers collection",)),
            ("r3 incomplète", incomplete, (f"does not name content {retire}",)),
        ):
            refus = run(
                "ingestor.ingestion_worker.attest_publication_cli", _arguments_de_liaison(mapping), attestor
            )
            print("REAL_CHAIN_E", nom, refus.stderr.strip())
            assert refus.returncode == 1 and "BINDING_REFUSED" in refus.stderr, refus.stderr
            assert any(motif in refus.stderr for motif in motifs), refus.stderr
    assert compte_par_table(control_pg) == avant


def test_2_les_r3_sont_liees_sans_reecrire_l_acquis(
    lie: dict[str, Any], adopte: dict[str, Any], control_pg: dict[str, str]
) -> None:
    assert "collections=11 written=479 already_present=0" in lie["sortie"], lie["sortie"]
    assert "written=0 already_present=479" in lie["rejeu"], lie["rejeu"]
    assert lie["ecarts"] == {"sealed_release_publication_authorizations": (0, 479)}, lie["ecarts"]
    # L'autorité d'ACQUISITION reste celle des r2 : rien n'est réécrit.
    assert _etat_historique(control_pg) == adopte["historique"]


def test_3_la_revue_batch_nomme_les_r3_et_l_attestation_est_enregistree(
    atteste: dict[str, Any], lie: dict[str, Any], adopte: dict[str, Any]
) -> None:
    assert "written=479" in atteste["propose"] and "blocked=0" in atteste["propose"], atteste
    assert "written=479" in atteste["record"], atteste["record"]
    texte = json.dumps(atteste["revue"])
    assert all(identifiant in texte for identifiant in lie["r3"].values())
    assert not any(identifiant in texte for identifiant in adopte["r2"].values())
    assert atteste["revue"]["placement_evidence"]["currentness"] == "official_snapshot"


def test_4a_worker_b_demarre_qualifie_et_l_attestation_liee_aux_r3_tient(
    publie: dict[str, Any], control_pg: dict[str, str]
) -> None:
    """Démarrage sous qualification, puis vérification vivante de l'attestation
    batch (LOT41A-V2, contenu nommé, même collection) : aucune n'est invalidée,
    et aucun refus ne porte sur l'autorité."""
    sortie = publie["sortie"]
    assert "authority_mode=RELEASE_BOUND_STAGING_QUALIFICATION" in sortie, sortie
    assert f"release_id={V3_ID}" in sortie
    print("REAL_CHAIN_WORKER_B_ERRORS", publie["erreurs"])
    for erreur in publie["erreurs"]:
        assert "authorization" not in erreur and "LOT41A" not in erreur, erreur
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        invalidees = conn.execute(
            "SELECT count(*) FROM ingestion_control.publication_attestations"
            " WHERE release_id = %s AND invalidated_at IS NOT NULL",
            (V3_ID,),
        ).fetchone()
        conn.rollback()
    assert invalidees == (0,), invalidees


def test_4_v3_n_est_pas_publiable_son_programme_contredit_son_registre(
    publie: dict[str, Any], produit_pg: dict[str, str]
) -> None:
    """Les placements et profils de V3 portent ``EDUSCOL_CORPUS_20260808`` ;
    son registre de programmes, les versions BOEN. Worker B refuse chaque
    placement, n'écrit rien, et V4 lui succède (ADR-0061)."""
    placements = json.loads(
        (V3_DIR / "subjects/rag_nexus_dgemc_terminale_option.release.json").read_bytes()
    )["placements"]
    registre = json.loads((V3_DIR / "programme_registry.json").read_bytes())
    programmes = {t["collection"]: t["programme_version"] for t in registre["taxonomies"]}
    assert {p["programme_version"] for p in placements} == {"EDUSCOL_CORPUS_20260808"}
    assert programmes["rag_nexus_dgemc_terminale_option"].startswith("BOEN_")
    assert not publie["succes"]
    assert len(publie["erreurs"]) == len(publie["jobs"]) == 4, publie["erreurs"]
    assert all(
        "release programme version differs from canonical programme" in erreur
        for erreur in publie["erreurs"]
    ), publie["erreurs"]
    assert produit(produit_pg) == publie["produit"]
    assert publie["produit"]["artifacts"] == 0


# --- Contre-épreuves ----------------------------------------------------------


def test_a_une_readiness_d_une_autre_release_est_refusee(
    publie: dict[str, Any], control_pg: dict[str, str], produit_pg: dict[str, str],
    banc: dict[str, Any], github: LocalGitHub,
) -> None:
    refus = _lancer_worker_b(
        control_pg, produit_pg, banc, github,
        arguments=[*_arguments_b(banc), "--once"], readiness_env=banc["readiness_v2"],
    )
    print("REAL_CHAIN_A", refus_au_demarrage(refus))
    assert "staging readiness authorises release manifest" in refus.stderr
    assert produit(produit_pg) == publie["produit"]


def test_b_un_manifeste_de_profils_altere_ou_de_staging_est_refuse(
    publie: dict[str, Any], control_pg: dict[str, str], produit_pg: dict[str, str],
    banc: dict[str, Any], github: LocalGitHub,
) -> None:
    from ingestor.ingestion_profiles.registry import (  # noqa: PLC0415
        load_profile_registry,
        profile_fingerprint,
    )

    tmp_path: Path = banc["tmp_path"]
    brut = PROFILE_MANIFEST_V2.read_text(encoding="utf-8")
    empreinte = brut.split("fingerprint: ", 1)[1].split("\n", 1)[0].strip()
    altere = tmp_path / "altered_profile_manifest.yml"
    altere.write_text(brut.replace(empreinte, "0" * 64, 1), encoding="utf-8")
    staging = tmp_path / "bench_staging_profile_manifest.json"
    registre = load_profile_registry(PROFILES_V2)
    staging.write_text(
        json.dumps({
            "manifest_kind": "NEXUS_STAGING_PROFILE_MANIFEST_V1",
            "provenance": "real-release bench; test document",
            "generated_at": "2026-09-24T00:00:00Z",
            "authority_mode": "STAGING_LOCAL_GITHUB_ONLY",
            "production_approval": False,
            "profiles": [
                {"collection": c, "profile_version": v, "fingerprint": profile_fingerprint(p)}
                for (c, v), p in sorted(registre.items())
            ],
        }),
        encoding="utf-8",
    )
    for fichier in (altere, staging):
        arguments = remplacer(_arguments_b(banc), "--profile-manifest-path", str(fichier))
        arguments = remplacer(arguments, "--profile-manifest-sha256", sha(fichier))
        refus = _lancer_worker_b(
            control_pg, produit_pg, banc, github, arguments=[*arguments, "--once"]
        )
        print("REAL_CHAIN_B", fichier.name, refus_au_demarrage(refus))
    assert produit(produit_pg) == publie["produit"]


def test_c_une_chaine_pii_d_une_autre_ancre_est_refusee(
    publie: dict[str, Any], control_pg: dict[str, str], produit_pg: dict[str, str],
    banc: dict[str, Any], github: LocalGitHub,
) -> None:
    """Une ancre de revue qui n'est pas l'ancre réelle : clé de TEST déclarée
    ``test``, puis clé étrangère déclarée ``production``. Le reçu réel ne se
    vérifie sous aucune des deux."""
    from nexus_contracts.review_binding import public_key_hex  # noqa: PLC0415

    reelle = json.loads((REPOSITORY_ROOT / CHAINE_PII["--review-trust-anchor-path"]).read_bytes())
    for environnement in ("test", "production"):
        ancre = banc["tmp_path"] / f"bench_review_binding_anchor_{environnement}.json"
        ancre.write_text(
            json.dumps({
                "protocol_version": reelle["protocol_version"],
                "keys": [{
                    **reelle["keys"][0],
                    "public_key": public_key_hex(secrets.token_hex(32)),
                    "environment": environnement,
                    "comment": "bench key — never an authority",
                }],
            }),
            encoding="utf-8",
        )
        arguments = remplacer(_arguments_b(banc), "--review-trust-anchor-path", str(ancre))
        arguments = remplacer(arguments, "--review-trust-anchor-sha256", sha(ancre))
        refus = _lancer_worker_b(control_pg, produit_pg, banc, github, arguments=[*arguments, "--once"])
        print("REAL_CHAIN_C", environnement, refus_au_demarrage(refus))
    assert produit(produit_pg) == publie["produit"]


def test_f_une_readiness_de_staging_sous_production_est_refusee(
    publie: dict[str, Any], control_pg: dict[str, str], produit_pg: dict[str, str],
    banc: dict[str, Any], github: LocalGitHub,
) -> None:
    sous_production = {**banc["readiness_v3"], "NEXUS_ENVIRONMENT": "production"}
    protocole_de_production = {
        **banc["readiness_v3"],
        "NEXUS_EXPECTED_READINESS_PROTOCOL": "NEXUS-PRODUCTION-READINESS-V1",
        "NEXUS_READINESS_REHEARSAL_TRUST_ANCHOR": banc["readiness_v3"]["NEXUS_STAGING_READINESS_TRUST_ANCHOR"],
        "NEXUS_RELEASE_SHA": "c" * 40,
    }
    for nom, env_readiness in (("environment=production", sous_production), ("production protocol", protocole_de_production)):
        refus = _lancer_worker_b(
            control_pg, produit_pg, banc, github,
            arguments=[*_arguments_b(banc), "--once"], readiness_env=env_readiness,
        )
        print("REAL_CHAIN_F", nom, refus_au_demarrage(refus))
    assert produit(produit_pg) == publie["produit"]


# --- (d) sur une seconde base : l'autorité r2 (V1), sans liaison ---------------


@pytest.fixture(scope="module")
def control_pg_sans_liaison() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("v3-real-unbound")


def test_d_une_autorite_r2_sans_liaison_ne_publie_rien(
    control_pg_sans_liaison: dict[str, str],
    produit_pg: dict[str, str],
    banc: dict[str, Any],
) -> None:
    """Sans ``bind-publication-authorities``, les faits batch portent l'autorité
    d'ACQUISITION (r2, LOT41A-V1). Elle ne fonde aucune publication."""
    pg = control_pg_sans_liaison
    github = LocalGitHub()
    etat = _jusqu_a_l_adoption(pg, banc, github)
    attestor = {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(pg)}
    # La liaison des r2 elles-mêmes est refusée : V1 ne borne aucun contenu.
    with local_github_server(github) as github_url:
        lier_r2 = run(
            "ingestor.ingestion_worker.attest_publication_cli",
            _arguments_de_liaison(etat["r2"]),
            {**attestor, **acces_github(github_url, banc["jeton"])},
        )
    print("REAL_CHAIN_D_BIND_R2", lier_r2.stderr.strip())
    assert lier_r2.returncode == 1 and "LOT41A-V2" in lier_r2.stderr, lier_r2.stderr

    revue = f"{REVUE_V3}-sans-liaison"
    propose = run(
        "ingestor.ingestion_worker.attest_publication_cli",
        _arguments_de_proposition_v3(banc["transfert_v3"], revue=revue),
        attestor,
    )
    print("REAL_CHAIN_D_PROPOSE", propose.returncode, propose.stdout.splitlines()[:1], propose.stderr[-800:])
    produit_avant = produit(produit_pg)
    if propose.returncode != 0:
        return
    chemin = next(
        ligne.split(" ", 1)[1].strip()
        for ligne in propose.stdout.splitlines()
        if ligne.startswith("REVIEW_ARTIFACT_PATH ")
    )
    octets = propose.stdout[propose.stdout.index("{") :].encode("utf-8")
    assert all(identifiant in octets.decode() for identifiant in etat["r2"].values())
    tete = hashlib.sha1(f"revue-v3-sans-liaison:{_RUN_ID}".encode()).hexdigest()
    github.add_approved_pr(number=8501, head_sha=tete, base_sha="9" * 40, review_id=8511)
    github.put_blob(path=chemin, ref=tete, content=octets)
    with local_github_server(github) as github_url:
        enregistre = run(
            "ingestor.ingestion_worker.attest_publication_cli",
            [
                "record-release-batch-attestation",
                "--release-id", V3_ID, "--review-id", revue, "--repository", REPOSITORY,
                "--pull-request", "8501", "--expected-head", tete, "--review-artifact-path", chemin,
            ],
            {**attestor, **acces_github(github_url, banc["jeton"])},
        )
    print("REAL_CHAIN_D_RECORD", enregistre.returncode, enregistre.stdout[-400:], enregistre.stderr[-800:])
    if enregistre.returncode != 0:
        return
    jobs = creer_les_jobs(pg, release_id=V3_ID, cibles=[("rag_nexus_svt_terminale_specialite", "8eb23c91b035")])
    worker = _lancer_worker_b(
        pg, produit_pg, banc, github,
        arguments=[*_arguments_b(banc), "--poll-interval-s", "1", "--max-iterations", "1"],
    )
    print("REAL_CHAIN_D_WORKER_B", worker.stdout[-1200:], worker.stderr[-1500:])
    assert "status=succeeded" not in worker.stdout, worker.stdout
    assert "LOT41A-V2" in worker.stderr or "does not bind content" in worker.stderr, worker.stderr
    assert produit(produit_pg) == produit_avant
    with psycopg.connect(superuser_dsn(pg)) as conn:
        etat_ressource = conn.execute(
            "SELECT resource_state FROM ingestion_control.resources WHERE resource_id = %s",
            (next(iter(jobs.values()))["resource_id"],),
        ).fetchone()
        conn.rollback()
    assert etat_ressource == ("NEEDS_REVIEW",), etat_ressource
