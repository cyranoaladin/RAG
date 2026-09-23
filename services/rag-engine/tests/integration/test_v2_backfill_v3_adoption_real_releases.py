"""Rattrapage d'attribution de V2 puis adoption par V3, sur les VRAIES releases.

La séquence staging prévue — ``--only-attributions`` sur V2, puis
``adopt-predecessor-release`` pour V3 — n'avait été exercée que sur des
releases de banc. Ce module la rejoue sur les octets réels :

- V2 : ``profile_gate_v2/release-1b9eba0c0eb0ab13`` (manifeste ``e9506f5a…``) ;
- V3 : ``profile_gate_v3/release-f8fb983d04f4b7c1`` (manifeste ``c0f5897b…``) ;
- les 315 PDF réels, relus depuis les miroirs locaux et rehachés ;
- les profils gouvernés ``v2_livraison_319``.

L'état initial est celui de staging : les 479 placements de V2 écrits par le
VRAI point d'entrée de Worker A (CLI, jusqu'à ``NEEDS_REVIEW``), puis privés
de leurs attributions, comme l'étaient les lignes écrites avant que ce point
d'entrée ne les établisse.

Les autorités de ce module sont des **données de test** : autorisations de
scope servies par une forge locale, manifeste de readiness signé par une clé
de banc. Elles ne sortent jamais des bases jetables et n'autorisent rien.

Prérequis (sinon le module est ignoré, ou échoue nommément) :

- ``NEXUS_REAL_RELEASE_ADOPTION=1`` ;
- ``NEXUS_REAL_RELEASE_ARTIFACT_MIRRORS`` : racines de corpus séparées par
  ``:`` où se trouvent les ``source_path`` du catalogue V2 ;
- Docker (une base de contrôle jetable, supprimée à la sortie).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import uuid
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ENGINE_ROOT.parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _local_github import (  # noqa: E402
    REPOSITORY,
    VALID_TOKEN,
    LocalGitHub,
    local_github_server,
)
from _pg_authority import (  # noqa: E402
    app_dsn,
    attestor_dsn,
    authority_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)

pytestmark = [pytest.mark.integration, requires_docker]

if os.environ.get("NEXUS_REAL_RELEASE_ADOPTION") != "1":
    pytest.skip(
        "real V2 backfill / V3 adoption not requested (NEXUS_REAL_RELEASE_ADOPTION=1)",
        allow_module_level=True,
    )

RELEASES = REPOSITORY_ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027"
V2_DIR = RELEASES / "profile_gate_v2/release-1b9eba0c0eb0ab13/profile_gate"
V3_DIR = RELEASES / "profile_gate_v3/release-f8fb983d04f4b7c1/profile_gate"
V2_ID = "production-profile-gate-2026-2027-v2"
V3_ID = "production-profile-gate-2026-2027-v3"
V2_MANIFEST_SHA256 = "e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864"
V3_MANIFEST_SHA256 = "c0f5897bf0a2d2f388ba0534de2cc4bb3198ab5d68173f4d28713572ce222e16"
TRANSFER_V2 = REPOSITORY_ROOT / (
    "docs/reports/evidence/external_staging_v2_artifact_transfer_manifest.json"
)
PROFILES_DIR = ENGINE_ROOT / "configs/ingestion_profiles/v2_livraison_319"
MIRRORS_ENV = "NEXUS_REAL_RELEASE_ARTIFACT_MIRRORS"

#: L'image que le manifeste de readiness du banc nomme, et que le banc
#: déclare en cours d'exécution. Identité de TEST, jamais une image réelle.
WORKER_IMAGE = "ghcr.io/nexus/ingestion-worker-bench@sha256:" + "a" * 64

_RUN_ID = uuid.uuid4().hex[:10]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digests(release_dir: Path) -> dict[str, str]:
    return {
        "release_manifest_sha256": _sha(release_dir / "production-profile-gate.release.json"),
        "artifacts_release_sha256": _sha(release_dir / "artifacts.release.json"),
        "candidate_inventory_sha256": _sha(release_dir / "candidate_inventory.json"),
    }


def _run(
    module: str, args: Sequence[str], env: Mapping[str, str], timeout: int = 900
) -> subprocess.CompletedProcess[str]:
    """Le vrai CLI, dans un processus à part, sous l'environnement donné SEUL.

    Aucune variable de readiness ou de DSN n'est héritée de l'appelant : ce
    que le CLI exige se lit donc dans ``env``, et nulle part ailleurs.
    """
    pythonpath = ":".join(
        str(p)
        for p in (
            ENGINE_ROOT / "src",
            REPOSITORY_ROOT / "packages/contracts/src",
            REPOSITORY_ROOT / "packages/release-chain/src",
            REPOSITORY_ROOT / "packages/pdf-page-policy/src",
        )
    )
    child_env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        **env,
        "PYTHONPATH": pythonpath,
    }
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=child_env,
        cwd=REPOSITORY_ROOT,
        check=False,
    )


@pytest.fixture(scope="module")
def control_pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("v2-v3-real-adoption")


def _magasin_reel(tmp_path: Path) -> Path:
    """Le magasin d'artefacts de V2, reconstruit depuis les miroirs et rehaché.

    Chaque PDF est copié sous ``<sha256>.pdf`` — la convention du magasin de
    staging — seulement si ses octets ont exactement l'empreinte du catalogue.
    """
    brut = os.environ.get(MIRRORS_ENV, "").strip()
    if not brut:
        pytest.fail(f"{MIRRORS_ENV} is required: the 315 real PDFs are never assumed")
    racines = [Path(r) for r in brut.split(":") if r.strip()]
    catalogue = json.loads((V2_DIR / "artifacts.release.json").read_bytes())
    magasin = tmp_path / "artifact-store"
    magasin.mkdir()
    absents: list[str] = []
    for entree in catalogue["artifacts"]:
        sha = entree["content_sha256"]
        for racine in racines:
            source = racine / entree["source_path"]
            if source.is_file() and _sha(source) == sha:
                shutil.copyfile(source, magasin / f"{sha}.pdf")
                break
        else:
            absents.append(entree["source_path"])
    assert not absents, f"{len(absents)} real PDF(s) not found: {absents[:3]}"
    return magasin


def _readiness(tmp_path: Path, *, release_id: str, manifest_sha256: str) -> dict[str, str]:
    """Un manifeste de readiness de RÉPÉTITION signé par une clé de banc.

    Il nomme UNE release : c'est ce que le CLI d'ingestion confronte.
    """
    from _local_github import REPOSITORY as DEPOT  # noqa: PLC0415
    from nexus_contracts.staging_readiness import (  # noqa: PLC0415
        STAGING_READINESS_PROTOCOL,
        StagingReadinessManifestV1,
        sign_staging_readiness_manifest,
        staging_public_key_hex,
    )

    graine = secrets.token_hex(32)
    key_id = f"banc-v2-v3-{uuid.uuid4().hex[:12]}"
    repertoire = tmp_path / f"readiness-{uuid.uuid4().hex[:8]}"
    repertoire.mkdir(parents=True)
    maintenant = datetime.now(UTC)
    manifeste = StagingReadinessManifestV1(
        protocol_version=STAGING_READINESS_PROTOCOL,
        environment="rehearsal",
        repository=DEPOT,
        merge_sha="c" * 40,
        worker_image=WORKER_IMAGE,
        allowed_release_id=release_id,
        allowed_release_manifest_sha256=manifest_sha256,
        control_dsn_differs_from_product=True,
        key_id=key_id,
        issued_at=maintenant - timedelta(minutes=5),
        expires_at=maintenant + timedelta(hours=6),
    )
    chemin = repertoire / "staging-readiness.json"
    chemin.write_bytes(
        sign_staging_readiness_manifest(
            manifeste, private_key_hex=graine, key_id=key_id
        ).canonical_bytes()
    )
    ancre = repertoire / "staging-readiness-anchor.json"
    ancre.write_text(
        json.dumps(
            {
                "protocol_version": STAGING_READINESS_PROTOCOL,
                "keys": [
                    {
                        "key_id": key_id,
                        "algorithm": "ed25519",
                        "public_key": staging_public_key_hex(graine),
                        "environment": "rehearsal",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return {
        "NEXUS_ENVIRONMENT": "rehearsal",
        "NEXUS_EXPECTED_READINESS_PROTOCOL": STAGING_READINESS_PROTOCOL,
        "NEXUS_READINESS_MANIFEST_PATH": str(chemin),
        "NEXUS_READINESS_MANIFEST_SHA256": _sha(chemin),
        "NEXUS_STAGING_READINESS_TRUST_ANCHOR": str(ancre),
        "NEXUS_ACTUAL_WORKER_IMAGE": WORKER_IMAGE,
    }


def _autorisation_id(collection: str) -> str:
    return f"real-release-adoption-{_RUN_ID}-{collection}"


def _enregistrer_les_autorisations(
    *, facts: Any, github: LocalGitHub, env: Mapping[str, str]
) -> dict[str, str]:
    """Une autorisation LOT41A-V2 par collection, par le VRAI CLI d'autorité.

    Chaque artefact est lié aux contenus exacts de sa collection dans V2.
    """
    from nexus_contracts.authority_artifacts import (  # noqa: PLC0415
        ScopeAuthorizationArtifactV2,
        canonical_authorization_path,
    )
    from nexus_contracts.document import Rights  # noqa: PLC0415

    from ingestor.ingestion_profiles.registry import (  # noqa: PLC0415
        load_profile_registry,
        profile_fingerprint,
    )

    profils = load_profile_registry(PROFILES_DIR)
    ids: dict[str, str] = {}
    for index, collection in enumerate(facts.collections, start=1):
        profil = profils[(collection, facts.profile_versions[collection])]
        autorisation_id = _autorisation_id(collection)
        artefact = ScopeAuthorizationArtifactV2.model_validate(
            {
                "protocol_version": "LOT41A-V2",
                "authorization_id": autorisation_id,
                "decision": "AUTHORIZE_INGESTION_SCOPE",
                "scope": profil.scope.model_dump(mode="json"),
                "manifest_digest": V2_MANIFEST_SHA256,
                "profile_id": profil.scope.collection,
                "profile_version": profil.profile_version,
                "profile_fingerprint": profile_fingerprint(profil),
                "allowed_domains": sorted(profil.allowed_domains),
                "rights_categories": [Rights.officiel_public.value],
                "exclusions": [],
                "allowed_content_sha256": sorted(
                    {p.artifact_id for p in facts.placements if p.collection == collection}
                ),
                "pii_absence_attested": True,
                "pii_absence_evidence": "real-release adoption bench; test authority only",
                "valid_from": "2026-09-01T00:00:00Z",
                "valid_until": "2027-09-01T00:00:00Z",
            }
        )
        numero = 8100 + index
        tete = hashlib.sha1(f"auth:{autorisation_id}".encode()).hexdigest()
        github.add_approved_pr(
            number=numero, head_sha=tete, base_sha="9" * 40, review_id=numero + 10
        )
        github.put_blob(
            path=canonical_authorization_path(autorisation_id),
            ref=tete,
            content=artefact.canonical_bytes(),
        )
        enregistre = _run(
            "ingestor.ingestion_worker.authorize_scope_cli",
            [
                "record-authorization",
                "--authorization-id", autorisation_id,
                "--repository", REPOSITORY,
                "--pull-request", str(numero),
                "--expected-head", tete,
            ],
            env,
        )
        assert enregistre.returncode == 0, enregistre.stderr
        ids[collection] = autorisation_id
    return ids


def _arguments_worker_a(
    *, magasin: Path, autorisations: Mapping[str, str], extra: Sequence[str] = ()
) -> list[str]:
    d = _digests(V2_DIR)
    args = [
        "--release-dir", str(V2_DIR),
        "--release-manifest-sha256", d["release_manifest_sha256"],
        "--artifacts-release-sha256", d["artifacts_release_sha256"],
        "--candidate-inventory-sha256", d["candidate_inventory_sha256"],
        "--artifact-transfer-manifest-path", str(TRANSFER_V2),
        "--artifact-transfer-manifest-sha256", _sha(TRANSFER_V2),
        "--artifact-store-dir", str(magasin),
        "--profiles-dir", str(PROFILES_DIR),
        "--owner", "real-release-adoption-bench",
        "--expected-role", "ingestion_control_app",
    ]
    for collection, autorisation_id in sorted(autorisations.items()):
        args += ["--scope-authorization", f"{collection}={autorisation_id}"]
    return [*args, *extra]


def _arguments_d_adoption(transfert: Path) -> list[str]:
    d = _digests(V3_DIR)
    return [
        "adopt-predecessor-release",
        "--release-id", V3_ID,
        "--release-dir", str(V3_DIR),
        "--release-manifest-sha256", d["release_manifest_sha256"],
        "--artifacts-release-sha256", d["artifacts_release_sha256"],
        "--candidate-inventory-sha256", d["candidate_inventory_sha256"],
        "--transfer-manifest-path", str(transfert),
        "--transfer-manifest-sha256", _sha(transfert),
        "--predecessor-release-id", V2_ID,
        "--predecessor-release-manifest-sha256", V2_MANIFEST_SHA256,
        "--adopted-by", "real-release-adoption-bench",
    ]


def _empreinte(valeur: Any) -> str:
    return hashlib.sha256(
        json.dumps(valeur, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _etat_historique(pg: dict[str, str]) -> dict[str, Any]:
    """Les identités acquises de V2 — ce que ni le rattrapage ni l'adoption
    n'ont le droit de modifier."""
    with psycopg.connect(superuser_dsn(pg)) as conn:
        ressources = conn.execute(
            "SELECT resource_id, collection, dedup_key, resource_state, state_version,"
            "       pipeline_kind, run_id"
            "  FROM ingestion_control.resources ORDER BY resource_id"
        ).fetchall()
        artefacts = conn.execute(
            "SELECT artifact_id, resource_id, sha256, run_id, payload"
            "  FROM ingestion_control.artifacts ORDER BY artifact_id"
        ).fetchall()
        candidats = conn.execute(
            "SELECT * FROM ingestion_control.resource_candidates ORDER BY 1"
        ).fetchall()
        evenements = conn.execute(
            "SELECT event_id, resource_id, from_state, to_state, payload"
            "  FROM ingestion_control.workflow_events"
            " WHERE event_type = 'transition' ORDER BY event_id"
        ).fetchall()
        conn.rollback()
    return {
        "resources": _empreinte(ressources),
        "artifacts": _empreinte(artefacts),
        "resource_candidates": _empreinte(candidats),
        "transitions": _empreinte(evenements),
        "counts": (len(ressources), len(artefacts), len(candidats), len(evenements)),
        "payload_digests": sorted(_empreinte(ligne[4]) for ligne in artefacts),
        "release_ids": sorted({ligne[4]["release_id"] for ligne in artefacts}),
    }


def _compte_par_table(pg: dict[str, str]) -> dict[str, int]:
    """Le nombre de lignes de CHAQUE table du plan de contrôle."""
    with psycopg.connect(superuser_dsn(pg)) as conn:
        tables = [
            ligne[0]
            for ligne in conn.execute(
                "SELECT table_name FROM information_schema.tables"
                " WHERE table_schema = 'ingestion_control' AND table_type = 'BASE TABLE'"
                " ORDER BY table_name"
            ).fetchall()
        ]
        comptes = {}
        for table in tables:
            ligne = conn.execute(
                f'SELECT count(*) FROM ingestion_control."{table}"'  # noqa: S608
            ).fetchone()
            comptes[table] = int(ligne[0]) if ligne else 0
        conn.rollback()
    return comptes


def _champs(sortie: str, marqueur: str) -> dict[str, str]:
    ligne = next(ligne for ligne in sortie.splitlines() if ligne.startswith(marqueur))
    return dict(
        morceau.split("=", 1) for morceau in ligne.split()[1:] if "=" in morceau
    )


def test_les_releases_reelles_sont_celles_attendues() -> None:
    """Un skip n'est pas une exécution : les octets réels sont vérifiés ici."""
    assert _sha(V2_DIR / "production-profile-gate.release.json") == V2_MANIFEST_SHA256
    assert _sha(V3_DIR / "production-profile-gate.release.json") == V3_MANIFEST_SHA256
    assert TRANSFER_V2.is_file()
    assert len(list(PROFILES_DIR.glob("*.yml"))) == 11


def test_rattrapage_v2_puis_adoption_v3_sur_les_releases_reelles(
    control_pg: dict[str, str], tmp_path: Path
) -> None:
    from ingestor.ingestion_worker.sealed_release_ingestion import (  # noqa: PLC0415
        load_sealed_release,
    )

    d2 = _digests(V2_DIR)
    facts = load_sealed_release(
        V2_DIR,
        release_manifest_sha256=d2["release_manifest_sha256"],
        artifacts_release_sha256=d2["artifacts_release_sha256"],
        candidate_inventory_sha256=d2["candidate_inventory_sha256"],
        artifact_transfer_manifest_path=TRANSFER_V2,
        artifact_transfer_manifest_sha256=_sha(TRANSFER_V2),
    )
    assert (len(facts.collections), len(facts.artifact_ids), len(facts.placements)) == (
        11, 315, 479,
    )
    magasin = _magasin_reel(tmp_path)

    github = LocalGitHub()
    jeton = tmp_path / "github-token"
    jeton.write_text(VALID_TOKEN, encoding="utf-8")
    base = {
        "PG_INGESTION_CONTROL_DSN": app_dsn(control_pg),
    }
    readiness_v2 = _readiness(tmp_path, release_id=V2_ID, manifest_sha256=V2_MANIFEST_SHA256)
    readiness_v3 = _readiness(tmp_path, release_id=V3_ID, manifest_sha256=V3_MANIFEST_SHA256)

    with local_github_server(github) as github_url:
        autorite = {
            "PG_INGESTION_CONTROL_AUTHORITY_DSN": authority_dsn(control_pg),
            "NEXUS_GITHUB_API_BASE": github_url,
            "NEXUS_GITHUB_TOKEN_FILE": str(jeton),
        }
        autorisations = _enregistrer_les_autorisations(
            facts=facts, github=github, env=autorite
        )

        # ── État initial : le VRAI Worker A écrit les 479 placements de V2 ──
        # Il relit chaque autorisation sur la forge : lui seul reçoit l'accès.
        ingere = _run(
            "ingestor.ingestion_worker.sealed_release_ingestion_cli",
            _arguments_worker_a(magasin=magasin, autorisations=autorisations),
            {
                **base,
                **readiness_v2,
                "NEXUS_GITHUB_API_BASE": github_url,
                "NEXUS_GITHUB_TOKEN_FILE": str(jeton),
            },
        )
    assert ingere.returncode == 0, ingere.stderr
    fin = _champs(ingere.stdout, "SEALED_RELEASE_INGESTION_DONE")
    assert (fin["resources"], fin["artifacts"], fin["terminal_state"]) == (
        "479", "479", "NEEDS_REVIEW",
    ), ingere.stdout

    # Les lignes de staging ont été écrites AVANT que ce point d'entrée
    # n'établisse les attributions : on reproduit cet état.
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        retirees = conn.execute(
            "DELETE FROM ingestion_control.artifact_attributions RETURNING 1"
        ).fetchall()
        conn.commit()
    assert len(retirees) == 479

    historique = _etat_historique(control_pg)
    assert historique["counts"] == (479, 479, 479, 4790), historique["counts"]
    assert historique["release_ids"] == [V2_ID]
    comptes_initiaux = _compte_par_table(control_pg)
    print("REAL_RELEASE_INITIAL_TABLE_COUNTS", json.dumps(comptes_initiaux, sort_keys=True))

    # ── (1) Rattrapage : une readiness nommant V3 est refusée sur V2 ──────
    mauvaise = _run(
        "ingestor.ingestion_worker.sealed_release_ingestion_cli",
        _arguments_worker_a(
            magasin=magasin, autorisations=autorisations, extra=["--only-attributions"]
        ),
        {**base, **readiness_v3},
    )
    assert mauvaise.returncode == 1
    assert "staging readiness authorises release" in mauvaise.stderr, mauvaise.stderr
    assert _compte_par_table(control_pg) == comptes_initiaux

    # ── (1) Rattrapage sous une readiness nommant V2 ──────────────────────
    rattrape = _run(
        "ingestor.ingestion_worker.sealed_release_ingestion_cli",
        _arguments_worker_a(
            magasin=magasin, autorisations=autorisations, extra=["--only-attributions"]
        ),
        {**base, **readiness_v2},
    )
    print("REAL_RELEASE_BACKFILL_STDOUT", rattrape.stdout)
    assert rattrape.returncode == 0, rattrape.stderr
    bilan = _champs(rattrape.stdout, "SEALED_RELEASE_ATTRIBUTION_BACKFILL_DONE")
    assert bilan == {
        "release_id": V2_ID,
        "examined": "479",
        "written": "479",
        "already_present": "0",
        "missing_rows": "0",
    }, rattrape.stdout
    assert _etat_historique(control_pg) == historique
    apres_rattrapage = _compte_par_table(control_pg)
    ecarts = {
        t: (comptes_initiaux[t], apres_rattrapage[t])
        for t in apres_rattrapage
        if apres_rattrapage[t] != comptes_initiaux.get(t)
    }
    assert ecarts == {"artifact_attributions": (0, 479)}, ecarts

    rejoue = _run(
        "ingestor.ingestion_worker.sealed_release_ingestion_cli",
        _arguments_worker_a(
            magasin=magasin, autorisations=autorisations, extra=["--only-attributions"]
        ),
        {**base, **readiness_v2},
    )
    assert rejoue.returncode == 0, rejoue.stderr
    second = _champs(rejoue.stdout, "SEALED_RELEASE_ATTRIBUTION_BACKFILL_DONE")
    assert (second["written"], second["already_present"]) == ("0", "479"), rejoue.stdout

    # ── (2) Adoption : AUCUNE readiness ni DSN applicatif dans l'environnement
    adoption_env = {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg)}

    # Avec le manifeste de transfert réel (celui de V2), V3 est refusée par
    # son propre chargeur : le transfert nomme une autre release.
    refus = _run(
        "ingestor.ingestion_worker.attest_publication_cli",
        _arguments_d_adoption(TRANSFER_V2),
        adoption_env,
    )
    print("REAL_RELEASE_ADOPTION_WITH_V2_TRANSFER_STDERR", refus.stderr)
    assert refus.returncode == 1
    assert "SUCCESSOR_RELEASE_UNUSABLE" in refus.stderr, refus.stderr
    assert (
        f"release_id {V2_ID!r} ≠ {V3_ID!r}" in refus.stderr
    ), refus.stderr
    assert _compte_par_table(control_pg) == apres_rattrapage

    # Un manifeste de transfert au nom de V3 — ICI un document de TEST, dérivé
    # de celui de V2 (mêmes 315 objets), en attendant celui que staging doit
    # établir en rehachant son magasin sous l'identité V3.
    transfert_v2 = json.loads(TRANSFER_V2.read_bytes())
    transfert_v3 = tmp_path / "bench_v3_artifact_transfer_manifest.json"
    transfert_v3.write_text(
        json.dumps(
            {
                **transfert_v2,
                "release_id": V3_ID,
                "manifest_kind": "REAL_RELEASE_ADOPTION_BENCH_TRANSFER_V1",
                "bench_note": "test document derived from the V2 transfer; not evidence",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    adopte = _run(
        "ingestor.ingestion_worker.attest_publication_cli",
        _arguments_d_adoption(transfert_v3),
        adoption_env,
    )
    print("REAL_RELEASE_ADOPTION_STDOUT", adopte.stdout)
    assert adopte.returncode == 0, adopte.stderr
    adoption = _champs(adopte.stdout, "ADOPTION_RECORDED")
    assert (
        adoption["release_id"], adoption["predecessor"], adoption["placements"],
        adoption["written"], adoption["already_present"], adoption["currentness"],
    ) == (V3_ID, V2_ID, "479", "479", "0", "official_snapshot"), adopte.stdout

    # Aucun fait historique réécrit, aucune ressource ni ligne nouvelle hors
    # des adoptions elles-mêmes.
    assert _etat_historique(control_pg) == historique
    apres_adoption = _compte_par_table(control_pg)
    ecarts = {
        t: (apres_rattrapage[t], apres_adoption[t])
        for t in apres_adoption
        if apres_adoption[t] != apres_rattrapage.get(t)
    }
    assert ecarts == {"sealed_release_adoptions": (0, 479)}, ecarts

    # Bijection : chaque placement acquis de V2 est adopté exactement une fois.
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        paires = conn.execute(
            "SELECT count(*), count(DISTINCT ad.resource_id),"
            "       count(DISTINCT (ad.collection, ad.content_sha256, ad.placement_id)),"
            "       count(*) FILTER (WHERE a.payload->>'release_id' = %s),"
            "       count(*) FILTER (WHERE a.payload->>'placement_id' = ad.placement_id)"
            "  FROM ingestion_control.sealed_release_adoptions ad"
            "  JOIN ingestion_control.artifacts a ON a.artifact_id = ad.artifact_id"
            " WHERE ad.release_id = %s",
            (V2_ID, V3_ID),
        ).fetchone()
        conn.rollback()
    assert paires == (479, 479, 479, 479, 479), paires

    rejoue_adoption = _run(
        "ingestor.ingestion_worker.attest_publication_cli",
        _arguments_d_adoption(transfert_v3),
        adoption_env,
    )
    assert rejoue_adoption.returncode == 0, rejoue_adoption.stderr
    assert "written=0 already_present=479" in rejoue_adoption.stdout
    assert _compte_par_table(control_pg) == apres_adoption
