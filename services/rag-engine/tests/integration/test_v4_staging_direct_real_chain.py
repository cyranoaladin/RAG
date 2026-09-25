"""Ingestion directe de V4 puis publication, sur les VRAIES octets (lot CZ).

V4 (``profile_gate_v4/release-024f8625ebfeb7ce``, manifeste ``bab9c398…``)
porte les mêmes 315 contenus que V3, avec des placements au programme
officiel de chaque collection et à la visibilité servie (ADR-0061). Ce
module rejoue, par les vrais CLI, le chemin DIRECT que le staging suivra :

1. les onze r4 (``build_lot41a_r4_authorizations.construire``) servies par
   la forge du banc et enregistrées par ``authorize_scope_cli`` ;
2. ``sealed_release_ingestion_cli`` sur V4 (readiness de staging nommant V4,
   manifeste de transfert au nom de V4) avec les r4 → 479 placements ;
3. ``propose-release-batch-review`` (chaîne PII réelle), approbation sur la
   forge du banc, ``record-release-batch-attestation`` ;
4. Worker B qualifié (``RELEASE_BOUND_STAGING_QUALIFICATION``) sur le modèle
   E5 réel et une base produit jetable, puis relecture indépendante.

Contre-épreuves : qualification d'une autre release (V3), profils de V3 avec
la release V4, autorité r2 (LOT41A-V1) à la place d'une r4, reprise après
écriture produit.

Par défaut, Worker B publie TOUS les placements de trois collections, dont
des contenus DETECTED_REVIEWED_ACCEPTED ; ``NEXUS_REAL_V4_PUBLISH_ALL=1``
publie les 479 (≈ 2 h sur CPU), ``NEXUS_REAL_V4_COLLECTIONS=a,b`` choisit.

Prérequis : ``NEXUS_REAL_RELEASE_ADOPTION=1``, ``NEXUS_REAL_RELEASE_ARTIFACT_MIRRORS``,
``RAG_EMBEDDING_MODEL_CACHE_DIR`` (E5, inventaire 58ad18db…), Docker.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _banc_releases_reelles import (  # noqa: E402
    MODELE_E5_ENV,
    PROFILE_MANIFEST_V2,
    PROFILE_MANIFEST_V4,
    PROFILES_V2,
    PROFILES_V4,
    REPOSITORY_ROOT,
    V3_ID,
    V3_MANIFEST_SHA256,
    V4_DIR,
    V4_ID,
    V4_MANIFEST_SHA256,
    acces_github,
    arguments_d_enregistrement,
    arguments_de_proposition,
    arguments_worker_a,
    arguments_worker_b,
    artefact_propose,
    autorisations_derivees,
    champs,
    compte_par_table,
    enregistrer,
    erreurs_d_iteration,
    lancer_worker_b,
    magasin_reel,
    manifeste,
    produit,
    r2_reelles,
    readiness,
    refus_au_demarrage,
    remplacer,
    run,
    sha,
    transfert_nomme,
)
from _local_github import VALID_TOKEN, LocalGitHub, local_github_server  # noqa: E402
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
        "real V4 staging chain not requested (NEXUS_REAL_RELEASE_ADOPTION=1)",
        allow_module_level=True,
    )

GENERATEUR_R4 = REPOSITORY_ROOT / "scripts/go_live/build_lot41a_r4_authorizations.py"
COLLECTIONS_PUBLIEES_PAR_DEFAUT = (
    "rag_nexus_dgemc_terminale_option",
    "rag_nexus_nsi_premiere_specialite",
    "rag_nexus_svt_premiere_specialite",
)
_RUN_ID = uuid.uuid4().hex[:10]
REVUE_V4 = f"lot42-release-batch-v4-reelle-{_RUN_ID}"


def _placements_v4() -> dict[tuple[str, str], dict[str, Any]]:
    """(collection, contenu) → placement prescrit par V4."""
    document = manifeste(V4_DIR)
    prescrits: dict[tuple[str, str], dict[str, Any]] = {}
    for sujet in document["subjects"]:
        contenu = json.loads((V4_DIR / sujet["path"]).read_bytes())
        for placement in contenu["placements"]:
            prescrits[(contenu["collection"], placement["artifact_id"])] = placement
    assert len(prescrits) == 479
    return prescrits


def _programmes_v4() -> dict[str, str]:
    registre = json.loads((V4_DIR / "programme_registry.json").read_bytes())
    return {t["collection"]: t["programme_version"] for t in registre["taxonomies"]}


def _collections_publiees() -> tuple[str, ...]:
    if os.environ.get("NEXUS_REAL_V4_PUBLISH_ALL") == "1":
        return tuple(sorted(_programmes_v4()))
    choisies = os.environ.get("NEXUS_REAL_V4_COLLECTIONS", "").strip()
    if choisies:
        return tuple(sorted(c.strip() for c in choisies.split(",") if c.strip()))
    return COLLECTIONS_PUBLIEES_PAR_DEFAUT


# --- Fixtures -----------------------------------------------------------------


@pytest.fixture(scope="module")
def control_pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("v4-real-chain")


@pytest.fixture(scope="module")
def produit_pg() -> Iterator[dict[str, str]]:
    yield from start_rag_product_postgres("v4-real-product")


@pytest.fixture(scope="module")
def github() -> LocalGitHub:
    return LocalGitHub()


@pytest.fixture(scope="module")
def banc(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp_path = tmp_path_factory.mktemp("banc-v4")
    modele = os.environ.get(MODELE_E5_ENV, "").strip()
    if not modele:
        pytest.fail(f"{MODELE_E5_ENV} is required: Worker B really embeds")
    jeton = tmp_path / "github-token"
    jeton.write_text(VALID_TOKEN, encoding="utf-8")
    return {
        "tmp_path": tmp_path,
        "magasin": magasin_reel(tmp_path),
        "transfert_v4": transfert_nomme(tmp_path, V4_ID),
        "jeton": jeton,
        "modele": Path(modele),
        "readiness_v4": readiness(tmp_path, release_id=V4_ID, manifest_sha256=V4_MANIFEST_SHA256),
        "readiness_v3": readiness(tmp_path, release_id=V3_ID, manifest_sha256=V3_MANIFEST_SHA256),
    }


@pytest.fixture(scope="module")
def autorites(
    control_pg: dict[str, str], banc: dict[str, Any], github: LocalGitHub
) -> dict[str, dict[str, str]]:
    """Les onze r4 dérivées ET les onze r2 réelles, enregistrées par le vrai
    CLI d'autorité (les r2 ne servent qu'à la contre-épreuve)."""
    r4 = autorisations_derivees(GENERATEUR_R4)
    r2 = r2_reelles()
    with local_github_server(github) as github_url:
        env = {
            "PG_INGESTION_CONTROL_AUTHORITY_DSN": authority_dsn(control_pg),
            **acces_github(github_url, banc["jeton"]),
        }
        enregistrer(github=github, env=env, documents=[r4[c] for c in sorted(r4)], numero=9100, graine=_RUN_ID)
        enregistrer(github=github, env=env, documents=[r2[c] for c in sorted(r2)], numero=9200, graine=_RUN_ID)
    return {
        "r4": {c: identifiant for c, (identifiant, _o) in r4.items()},
        "r2": {c: identifiant for c, (identifiant, _o) in r2.items()},
    }


def _ingerer(
    control_pg: dict[str, str], banc: dict[str, Any], github: LocalGitHub, autorisations: dict[str, str]
) -> Any:
    with local_github_server(github) as github_url:
        return run(
            "ingestor.ingestion_worker.sealed_release_ingestion_cli",
            arguments_worker_a(
                release_dir=V4_DIR,
                profiles_dir=PROFILES_V4,
                transfert=banc["transfert_v4"],
                magasin=banc["magasin"],
                autorisations=autorisations,
            ),
            {
                "PG_INGESTION_CONTROL_DSN": app_dsn(control_pg),
                **banc["readiness_v4"],
                **acces_github(github_url, banc["jeton"]),
            },
        )


@pytest.fixture(scope="module")
def acquis(
    autorites: dict[str, dict[str, str]],
    control_pg: dict[str, str],
    banc: dict[str, Any],
    github: LocalGitHub,
) -> dict[str, Any]:
    """Le vrai Worker A ingère V4 sous les r4."""
    avant = compte_par_table(control_pg)
    ingere = _ingerer(control_pg, banc, github, autorites["r4"])
    print("REAL_V4_INGEST", ingere.stdout.strip().splitlines()[-1:], ingere.stderr[-1500:])
    assert ingere.returncode == 0, ingere.stderr
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        payloads = conn.execute(
            "SELECT a.payload->>'release_id', a.payload->>'scope_authorization_id', r.resource_state,"
            "       count(*)"
            "  FROM ingestion_control.artifacts a JOIN ingestion_control.resources r USING (resource_id)"
            " GROUP BY 1, 2, 3 ORDER BY 2"
        ).fetchall()
        conn.rollback()
    return {
        "sortie": champs(ingere.stdout, "SEALED_RELEASE_INGESTION_DONE"),
        "payloads": payloads,
        "ecarts": {t: (avant.get(t, 0), n) for t, n in compte_par_table(control_pg).items() if n != avant.get(t, 0)},
    }


@pytest.fixture(scope="module")
def atteste(
    acquis: dict[str, Any], control_pg: dict[str, str], banc: dict[str, Any], github: LocalGitHub
) -> dict[str, Any]:
    attestor = {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg)}
    propose = run(
        "ingestor.ingestion_worker.attest_publication_cli",
        arguments_de_proposition(
            release_dir=V4_DIR, release_id=V4_ID, transfert=banc["transfert_v4"], revue=REVUE_V4
        ),
        attestor,
    )
    print("REAL_V4_PROPOSE", propose.stdout.splitlines()[:1], propose.stderr[-1500:])
    assert propose.returncode == 0, propose.stderr
    chemin, octets = artefact_propose(propose.stdout)
    tete = hashlib.sha1(f"revue-v4:{_RUN_ID}".encode()).hexdigest()
    github.add_approved_pr(number=9401, head_sha=tete, base_sha="9" * 40, review_id=9411)
    github.put_blob(path=chemin, ref=tete, content=octets)
    with local_github_server(github) as github_url:
        enregistre = run(
            "ingestor.ingestion_worker.attest_publication_cli",
            arguments_d_enregistrement(
                release_id=V4_ID, revue=REVUE_V4, pull_request=9401, tete=tete, chemin=chemin
            ),
            {**attestor, **acces_github(github_url, banc["jeton"])},
        )
    print("REAL_V4_RECORD", enregistre.stdout.strip()[-400:], enregistre.stderr[-1500:])
    assert enregistre.returncode == 0, enregistre.stderr
    return {
        "propose": propose.stdout.splitlines()[0],
        "revue": json.loads(octets),
        "record": enregistre.stdout.strip().splitlines()[-1],
    }


def _arguments_b(banc: dict[str, Any]) -> list[str]:
    return list[str](arguments_worker_b(
        release_dir=V4_DIR,
        profiles_dir=PROFILES_V4,
        profile_manifest=PROFILE_MANIFEST_V4,
        magasin=banc["magasin"],
        transfert=banc["transfert_v4"],
        modele=banc["modele"],
    ))


MISE_EN_FILE = REPOSITORY_ROOT / "scripts/go_live/staging_v4_enqueue_publication.py"


def _mettre_en_file_par_le_script(
    control_pg: dict[str, str], *, collections: tuple[str, ...], attendu: int
) -> dict[str, dict[str, Any]]:
    """Les jobs de publication, créés par l'outil que le staging exécutera
    (``staging_v4_enqueue_publication``), sous le rôle applicatif — pas par un
    utilitaire de banc en superutilisateur. Rejeu sans effet ; compte faux refusé."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("staging_v4_enqueue_publication", MISE_EN_FILE)
    assert spec and spec.loader
    outil = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(outil)
    with psycopg.connect(app_dsn(control_pg)) as conn:
        assert conn.execute("select current_user").fetchone()[0] == "ingestion_control_app"
        with pytest.raises(outil.MiseEnFileRefusee):
            outil.mettre_en_file(conn, release_id=V4_ID, attendu=attendu + 1, collections=collections)
        conn.rollback()
        bilan = outil.mettre_en_file(conn, release_id=V4_ID, attendu=attendu, collections=collections)
        conn.commit()
    assert bilan == {"crees": attendu, "deja_en_file": 0, "deja_publies": 0}, bilan
    with psycopg.connect(app_dsn(control_pg)) as conn:
        rejeu = outil.mettre_en_file(conn, release_id=V4_ID, attendu=attendu, collections=collections)
        conn.commit()
    assert rejeu == {"crees": 0, "deja_en_file": attendu, "deja_publies": 0}, rejeu
    print("REAL_V4_ENQUEUE", bilan, "rejeu", rejeu)
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        lignes = conn.execute(
            "SELECT j.job_id, j.payload, r.collection FROM ingestion_control.jobs j"
            "  JOIN ingestion_control.resources r ON r.resource_id = j.resource_id"
            " WHERE j.job_type = 'publication_resume'"
        ).fetchall()
        conn.rollback()
    assert len(lignes) == attendu
    return {
        str(job_id): {
            "collection": collection,
            "resource_id": uuid.UUID(payload["resource_id"]),
            "attestation_id": payload["publication_attestation_id"],
        }
        for job_id, payload, collection in lignes
    }


@pytest.fixture(scope="module")
def publie(
    atteste: dict[str, Any],
    control_pg: dict[str, str],
    produit_pg: dict[str, str],
    banc: dict[str, Any],
    github: LocalGitHub,
) -> dict[str, Any]:
    """Worker B qualifié par une readiness de staging nommant V4."""
    collections = _collections_publiees()
    cibles = sorted((c, contenu) for (c, contenu) in _placements_v4() if c in collections)
    jobs = _mettre_en_file_par_le_script(control_pg, collections=collections, attendu=len(cibles))
    debut = time.monotonic()
    worker = lancer_worker_b(
        control_pg, produit_pg, github=github, jeton=banc["jeton"], readiness_env=banc["readiness_v4"],
        arguments=[*_arguments_b(banc), "--poll-interval-s", "1", "--max-iterations", str(len(jobs) + 3)],
        timeout=4 * 3600,
    )
    duree = time.monotonic() - debut
    erreurs = erreurs_d_iteration(worker.stderr)
    print("REAL_V4_WORKER_B_SECONDS", round(duree, 1), "jobs", len(jobs))
    print("REAL_V4_WORKER_B_STARTUP", worker.stdout.splitlines()[:1])
    print("REAL_V4_WORKER_B_ERRORS", erreurs[:5])
    assert worker.returncode == 0, worker.stderr[-3000:]
    return {
        "collections": collections,
        "cibles": cibles,
        "jobs": jobs,
        "sortie": worker.stdout,
        "erreurs": erreurs,
        "succes": worker.stdout.count("status=succeeded") == len(jobs),
        "secondes": duree,
        "produit": produit(produit_pg),
    }


# --- La chaîne ----------------------------------------------------------------


def test_les_octets_de_v4_sont_ceux_attendus() -> None:
    assert sha(V4_DIR / "production-profile-gate.release.json") == V4_MANIFEST_SHA256
    assert manifeste(V4_DIR)["release_id"] == V4_ID
    pii = json.loads((V4_DIR / "pii_evidence.json").read_bytes())
    statuts = {r["content_sha256"]: r["status"] for r in pii["results"]}
    publies = {contenu for (c, contenu) in _placements_v4() if c in _collections_publiees()}
    # Le sous-ensemble publié contient des contenus dont la PII a été revue.
    assert any(statuts[c] == "DETECTED_REVIEWED_ACCEPTED" for c in publies)


def test_d_une_autorite_r2_a_la_place_d_une_r4_n_ingere_rien(
    autorites: dict[str, dict[str, str]],
    control_pg: dict[str, str],
    banc: dict[str, Any],
    github: LocalGitHub,
) -> None:
    """Avant toute ingestion : les r2 (LOT41A-V1, portée V2) ne fondent pas
    l'ingestion de V4 — et rien n'est écrit."""
    avant = compte_par_table(control_pg)
    refus = _ingerer(control_pg, banc, github, autorites["r2"])
    print("REAL_V4_D_R2", refus.stderr.strip()[-800:])
    assert refus.returncode == 1, refus.stdout
    assert compte_par_table(control_pg) == avant


def test_1_worker_a_ingere_v4_sous_les_r4(acquis: dict[str, Any], autorites: dict[str, dict[str, str]]) -> None:
    sortie = acquis["sortie"]
    assert (sortie["resources"], sortie["artifacts"], sortie["terminal_state"]) == ("479", "479", "NEEDS_REVIEW")
    print("REAL_V4_PAYLOADS", acquis["payloads"])
    assert {(r, s) for r, _a, s, _n in acquis["payloads"]} == {(V4_ID, "NEEDS_REVIEW")}
    assert {a for _r, a, _s, _n in acquis["payloads"]} == set(autorites["r4"].values())
    assert sum(n for *_x, n in acquis["payloads"]) == 479
    print("REAL_V4_INGEST_TABLES", acquis["ecarts"])
    assert acquis["ecarts"]["artifact_attributions"] == (0, 479)


def test_2_la_revue_batch_nomme_les_r4_et_l_attestation_est_enregistree(
    atteste: dict[str, Any], autorites: dict[str, dict[str, str]]
) -> None:
    assert "written=479" in atteste["propose"] and "blocked=0" in atteste["propose"], atteste["propose"]
    assert "written=479" in atteste["record"], atteste["record"]
    texte = json.dumps(atteste["revue"])
    assert all(identifiant in texte for identifiant in autorites["r4"].values())
    assert not any(identifiant in texte for identifiant in autorites["r2"].values())


def test_3_worker_b_publie_sous_qualification_et_la_base_produit_dit_v4(
    publie: dict[str, Any],
    autorites: dict[str, dict[str, str]],
    control_pg: dict[str, str],
) -> None:
    sortie = publie["sortie"]
    assert "authority_mode=RELEASE_BOUND_STAGING_QUALIFICATION" in sortie
    assert f"release_id={V4_ID}" in sortie
    assert publie["succes"], publie["erreurs"][:5]

    # Plan de contrôle, relu indépendamment.
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        etats = conn.execute(
            "SELECT resource_state, count(*) FROM ingestion_control.resources"
            " WHERE resource_id = ANY(%s) GROUP BY 1",
            ([job["resource_id"] for job in publie["jobs"].values()],),
        ).fetchall()
        conn.rollback()
    assert etats == [("RETRIEVAL_ELIGIBLE", len(publie["jobs"]))], etats

    prescrits = _placements_v4()
    programmes = _programmes_v4()
    base = publie["produit"]
    placements = base["placements"]
    assert {(p[2], p[1]) for p in placements} == set(publie["cibles"])
    par_collection: dict[str, set[tuple[str, str]]] = {}
    for (placement_id, artefact, collection, actualite, statut, revue, autorisation,
         _attestation, programme, visibilite, source) in placements:
        attendu = prescrits[(collection, artefact)]
        assert placement_id == attendu["placement_id"], (collection, artefact)
        assert source == attendu["source_placement_id"]
        assert programme == programmes[collection] == attendu["programme_version"]
        assert visibilite == attendu["visibility"] == "internal"
        assert (actualite, statut, revue) == ("official_snapshot", "active", "reviewed")
        assert autorisation == autorites["r4"][collection]
        par_collection.setdefault(collection, set()).add((programme, visibilite))
    print("REAL_V4_PRODUCT_PER_COLLECTION", {c: sorted(v) for c, v in sorted(par_collection.items())})
    attestations = {j["attestation_id"] for j in publie["jobs"].values()}
    assert {str(p[7]) for p in placements} == attestations

    for (artefact, collection, _n, dmin, dmax, nuls, programmes_c, visibilites, droits) in base["chunks"]:
        assert (dmin, dmax, nuls) == (1024, 1024, 0), (artefact, collection)
        assert programmes_c == [programmes[collection]], (artefact, collection, programmes_c)
        assert visibilites == ["internal"], (artefact, collection, visibilites)
        assert droits == ["officiel_public"], (artefact, collection, droits)
    print(
        "REAL_V4_PRODUCT_TOTALS artifacts=", base["artifacts"], "placements=", len(placements),
        "chunks=", sum(c[2] for c in base["chunks"]),
    )


def test_3b_les_chunks_publies_sont_ceux_que_la_release_scelle(publie: dict[str, Any]) -> None:
    """La release scelle, par contenu, ses chunks (chunk_id, chunk_sha256,
    chunk_index) ; le produit doit porter exactement ceux-là."""
    assert publie["succes"], publie["erreurs"][:5]
    base = publie["produit"]
    catalogue = {
        a["content_sha256"]: a for a in json.loads((V4_DIR / "artifacts.release.json").read_bytes())["artifacts"]
    }
    # Identité des chunks : chaque (chunk_id, chunk_sha256, chunk_index) publié
    # est celui que la release scelle, et aucun ne manque. Tous les écarts
    # sont collectés avant d'échouer : un premier écart n'en cache aucun autre.
    publies: dict[tuple[str, str], set[tuple[str, str, int]]] = {}
    for artefact, collection, chunk_id, chunk_sha, index in base["identites"]:
        publies.setdefault((artefact, collection), set()).add((chunk_id, chunk_sha, index))
    ecarts_de_chunks = {}
    for collection, artefact in publie["cibles"]:
        scelles = {
            (c["chunk_id"], c["chunk_sha256"], c["chunk_index"]) for c in catalogue[artefact]["chunks"]
        }
        obtenus = publies.get((artefact, collection), set())
        if obtenus != scelles:
            sha_scelles = {(i, s) for _x, s, i in scelles}
            sha_obtenus = {(i, s) for _x, s, i in obtenus}
            ecarts_de_chunks[(collection, artefact[:12])] = {
                "scelles": len(scelles),
                "publies": len(obtenus),
                "chunk_id_egaux": len({x for x, _s, _i in scelles} & {x for x, _s, _i in obtenus}),
                "chunk_sha256_egaux_au_meme_index": len(sha_scelles & sha_obtenus),
                "chunk_sha256_egaux_tous_index": len({s for _x, s, _i in scelles} & {s for _x, s, _i in obtenus}),
            }
    print("REAL_V4_CHUNK_IDENTITY_GAPS", len(ecarts_de_chunks), "of", len(publie["cibles"]), ecarts_de_chunks)
    assert not ecarts_de_chunks, ecarts_de_chunks


SONDE = REPOSITORY_ROOT / "scripts/go_live/staging_retrieval_probe.py"


def test_4_retrieval_v4_sous_les_scopes_emis(publie: dict[str, Any], produit_pg: dict[str, str]) -> None:
    """La sonde que le staging exécutera (``staging_retrieval_probe``), sur le
    banc : scope émis par collection, chaque chunk publié interrogé par son
    vecteur, rien hors du jeu publié, refus dense constaté à sa source,
    ``student`` refusé. Le même code, pas une réplique."""
    import importlib.util

    assert publie["succes"], publie["erreurs"][:5]
    spec = importlib.util.spec_from_file_location("staging_retrieval_probe", SONDE)
    assert spec and spec.loader
    sonde = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sonde)
    publiees = sorted({c for c, _a in publie["cibles"]})
    rapport = sonde.sonder(
        REPOSITORY_ROOT,
        connexion=lambda: psycopg.connect(produit_pg["retrieval_dsn"]),
        collections=publiees,
    )
    print("REAL_V4_RETRIEVAL", json.dumps(rapport, sort_keys=True))
    assert sorted(rapport["collections"]) == publiees
    totaux = rapport["totaux"]
    assert totaux["chunks"] == len(publie["produit"]["identites"])
    assert totaux["rappel_a_5"] + totaux["manques"] + totaux["refus_egalite"] == totaux["chunks"]
    assert all(c["student"] == "refuse" for c in rapport["collections"].values())


# --- Contre-épreuves ----------------------------------------------------------


def test_a_une_qualification_nommant_v3_est_refusee(
    publie: dict[str, Any], control_pg: dict[str, str], produit_pg: dict[str, str],
    banc: dict[str, Any], github: LocalGitHub,
) -> None:
    refus = lancer_worker_b(
        control_pg, produit_pg, github=github, jeton=banc["jeton"], readiness_env=banc["readiness_v3"],
        arguments=[*_arguments_b(banc), "--once"],
    )
    print("REAL_V4_A", refus_au_demarrage(refus))
    assert "staging readiness authorises release manifest" in refus.stderr
    assert produit(produit_pg) == publie["produit"]


def test_b_les_profils_de_v3_avec_la_release_v4_sont_refuses(
    publie: dict[str, Any], control_pg: dict[str, str], produit_pg: dict[str, str],
    banc: dict[str, Any], github: LocalGitHub,
) -> None:
    arguments = remplacer(_arguments_b(banc), "--profiles-dir", str(PROFILES_V2))
    arguments = remplacer(arguments, "--profile-manifest-path", str(PROFILE_MANIFEST_V2))
    arguments = remplacer(arguments, "--profile-manifest-sha256", sha(PROFILE_MANIFEST_V2))
    refus = lancer_worker_b(
        control_pg, produit_pg, github=github, jeton=banc["jeton"], readiness_env=banc["readiness_v4"],
        arguments=[*arguments, "--once"],
    )
    print("REAL_V4_B", refus_au_demarrage(refus))
    assert produit(produit_pg) == publie["produit"]


def test_g_une_reprise_apres_ecriture_produit_ne_duplique_ni_ne_change_l_autorite(
    publie: dict[str, Any], control_pg: dict[str, str], produit_pg: dict[str, str],
    banc: dict[str, Any], github: LocalGitHub,
) -> None:
    """Interruption APRÈS l'écriture produit, AVANT l'acquittement : les MÊMES
    jobs redeviennent réclamables et sont repris sans rien dupliquer."""
    assert publie["succes"], f"no first publication to resume: {publie['erreurs'][:3]}"
    repris_ids = sorted(publie["jobs"])[:3]
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        remis = conn.execute(
            "UPDATE ingestion_control.jobs SET status = 'queued', lease_token = NULL,"
            "       lease_expires_at = NULL, claimed_by = NULL"
            " WHERE job_id = ANY(%s) RETURNING job_id",
            (repris_ids,),
        ).fetchall()
        conn.commit()
    assert len(remis) == 3
    repris = lancer_worker_b(
        control_pg, produit_pg, github=github, jeton=banc["jeton"], readiness_env=banc["readiness_v4"],
        arguments=[*_arguments_b(banc), "--poll-interval-s", "1", "--max-iterations", "3"],
    )
    print("REAL_V4_G", repris.stdout.splitlines()[-3:], erreurs_d_iteration(repris.stderr))
    assert repris.returncode == 0, repris.stderr
    assert repris.stdout.count("status=succeeded") == 3, repris.stdout
    assert produit(produit_pg) == publie["produit"]
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        etats = conn.execute(
            "SELECT status, count(*) FROM ingestion_control.jobs WHERE job_id = ANY(%s) GROUP BY 1",
            (repris_ids,),
        ).fetchall()
        conn.rollback()
    assert etats == [("succeeded", 3)], etats
