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

La suite de la chaîne V3 est ensuite rejouée : proposition de revue batch
(chaîne PII réelle, SANS accès GitHub), approbation sur la forge du banc,
enregistrement des attestations, puis démarrage de Worker B en répétition
avec les arguments de ``scripts/go_live/staging_v3_arguments.worker_b``.
Worker B refuse V3 au démarrage : ce refus est l'assertion.

Prérequis (sinon le module est ignoré, ou échoue nommément) :

- ``RAG_EMBEDDING_MODEL_CACHE_DIR`` : l'artefact E5 réel (inventaire 58ad18db…) ;

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
    start_rag_product_postgres,
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

#: Le ``manifest_digest`` que portent les autorisations RÉELLES de staging
#: (``lot41a-staging-v2-*-r2``) : l'empreinte des OCTETS du manifeste de
#: profils (``authority_bindings.profile_manifest_file_sha256``).
MANIFEST_DIGEST_DES_AUTORISATIONS = (
    "d8b99a1d75e23baaba478a85b997a7022f52ddb9013dab176deb45b08ce4a7fc"
)
#: La collection dont l'autorisation reproduit le PROTOCOLE des autorisations
#: réelles de staging (LOT41A-V1). Les autres sont en LOT41A-V2.
COLLECTION_V1_COMME_STAGING = "rag_nexus_ses_premiere_specialite"


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
        ScopeAuthorizationArtifact,
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
        document: dict[str, Any] = {
            "protocol_version": "LOT41A-V2",
            "authorization_id": autorisation_id,
            "decision": "AUTHORIZE_INGESTION_SCOPE",
            "scope": profil.scope.model_dump(mode="json"),
            "manifest_digest": MANIFEST_DIGEST_DES_AUTORISATIONS,
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
        artefact: Any
        if collection == COLLECTION_V1_COMME_STAGING:
            # Réplique du FORMAT des autorisations réelles de staging
            # (``lot41a-staging-v2-*-r2``) : protocole V1, sans liste de
            # contenus. Worker B doit dire s'il l'accepte.
            del document["allowed_content_sha256"]
            artefact = ScopeAuthorizationArtifact.model_validate(
                {**document, "protocol_version": "LOT41A-V1"}
            )
        else:
            artefact = ScopeAuthorizationArtifactV2.model_validate(document)
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


@pytest.fixture(scope="module")
def adopte(
    control_pg: dict[str, str], tmp_path_factory: pytest.TempPathFactory
) -> dict[str, Any]:
    """Rattrapage V2 puis adoption V3 — l'état dont part la suite de la chaîne.

    Chaque étape est ASSERTÉE ici : un échec arrête le module à l'étape
    qui a réellement échoué.
    """
    tmp_path = tmp_path_factory.mktemp("adoption")
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
    return {
        "github": github,
        "jeton": jeton,
        "magasin": magasin,
        "transfert_v3": transfert_v3,
        "historique": historique,
        "adoption": adoption,
        "tmp_path": tmp_path,
    }


def test_rattrapage_v2_puis_adoption_v3_sur_les_releases_reelles(
    adopte: dict[str, Any],
) -> None:
    """Les deux étapes sont prouvées par la fixture ; on en relit le verdict."""
    assert adopte["adoption"]["written"] == "479"


# --- Suite de la chaîne V3 : revue batch, attestation, Worker B, retrieval ---

#: La chaîne de revue PII RÉELLE de V3 (ADR-0047), relue par ses chargeurs.
CHAINE_PII_V3 = {
    "--pii-decision-set-path": "governance/pii-review-decisions/pii-review-2026-09-22-profile-gate-v3.json",
    "--pii-review-receipt-path": "governance/pii-review-bindings/pii-review-2026-09-22-profile-gate-v3.json",
    "--review-trust-anchor-path": "governance/trust-anchors/review-binding-v1.json",
    "--pii-review-index-path": "docs/reports/evidence-index/pii_review_index_20260922_profile_gate_v3.json",
}
RELEVEURS = REPOSITORY_ROOT / "scripts/github/trusted-reviewers.json"
REGISTRE_DE_DROITS = REPOSITORY_ROOT / "services/rag-pedago/configs/rights_evidence_registry.yml"
REVUE_V3 = f"lot42-release-batch-v3-reelle-{_RUN_ID}"
MODELE_E5_ENV = "RAG_EMBEDDING_MODEL_CACHE_DIR"

def _arguments_de_proposition_v3(transfert: Path) -> list[str]:
    args = [
        "propose-release-batch-review",
        "--release-id", V3_ID,
        "--release-dir", str(V3_DIR),
        "--release-manifest-sha256", V3_MANIFEST_SHA256,
        "--transfer-manifest-path", str(transfert),
        "--transfer-manifest-sha256", _sha(transfert),
        "--rights-registry-path", str(REGISTRE_DE_DROITS),
        "--review-id", REVUE_V3,
        "--evaluator", "real-release-adoption-bench",
        "--pii-review-reviewers-sha256", _sha(RELEVEURS),
        "--repository-root", str(REPOSITORY_ROOT),
    ]
    for option, chemin in CHAINE_PII_V3.items():
        args += [option, str(REPOSITORY_ROOT / chemin)]
    return args


def _arguments_worker_b(*, magasin: Path, transfert: Path, modele: Path) -> list[str]:
    """La sémantique EXACTE de ``scripts/go_live/staging_v3_arguments.worker_b``
    (lot CY), chemins du conteneur remplacés par ceux du dépôt."""
    manifeste = json.loads((V3_DIR / "production-profile-gate.release.json").read_bytes())
    autorites = manifeste["authorities"]
    liaisons = json.loads((V3_DIR / "authority_bindings.json").read_bytes())
    profile_manifest = (
        ENGINE_ROOT / "configs/ingestion_profiles/ingestion_manifest_v2_livraison_319.yml"
    )
    assert liaisons["profile_manifest_fingerprint"] == autorites["profile_manifest_sha256"]
    assert _sha(profile_manifest) == liaisons["profile_manifest_file_sha256"]
    config = ENGINE_ROOT / "configs/rag_collections.yml"
    args = [
        "--profiles-dir", str(PROFILES_DIR),
        "--artifact-store-dir", str(magasin),
        "--owner", "real-release-adoption-worker-b",
        "--expected-role", "ingestion_control_app",
        # Le rôle produit de STAGING : le banc publie sous un autre nom de
        # rôle, ce qui mesure si cette option est contrôlée en répétition.
        "--expected-product-role", "rag_publisher",
        "--release-manifest-path", str(V3_DIR / "production-profile-gate.release.json"),
        "--release-manifest-sha256", V3_MANIFEST_SHA256,
        "--collection-config-path", str(config),
        "--collection-config-sha256", _sha(config),
        "--corpus-manifest-sha256", autorites["corpus_manifest_sha256"],
        "--repository-root", str(REPOSITORY_ROOT),
        "--pii-review-reviewers-sha256", _sha(RELEVEURS),
        "--artifact-transfer-manifest-path", str(transfert),
        "--artifact-transfer-manifest-sha256", _sha(transfert),
        "--embedding-artifact-root", str(modele),
        "--embedding-inventory-sha256", manifeste["models"]["embedding"]["inventory_sha256"],
        "--profile-manifest-path", str(profile_manifest),
        "--profile-manifest-sha256", _sha(profile_manifest),
    ]
    for option, cle, chemin_depot, nom_release in (
        ("--candidate-inventory", "candidate_inventory_sha256", None, "candidate_inventory.json"),
        ("--currentness-evidence", "currentness_evidence_sha256", None, "currentness_evidence.json"),
        ("--programme-registry", "programme_registry_sha256", None, "programme_registry.json"),
        ("--pii-evidence", "pii_evidence_sha256", None, "pii_evidence.json"),
        ("--levels-mapping", "level_mapping_sha256", "services/rag-engine/configs/mappings/eduscol_multilevel_levels.yml", None),
        ("--subjects-mapping", "subject_mapping_sha256", "services/rag-engine/configs/mappings/eduscol_profile_gate_subjects.yml", None),
        ("--document-types-mapping", "document_type_mapping_sha256", "services/rag-engine/configs/mappings/eduscol_multilevel_document_types.yml", None),
        ("--rights-evidence", "rights_registry_sha256", "services/rag-pedago/configs/rights_evidence_registry.yml", None),
        ("--pii-decision-set", "pii_decision_set_sha256", CHAINE_PII_V3["--pii-decision-set-path"], None),
        ("--pii-review-receipt", "pii_review_receipt_sha256", CHAINE_PII_V3["--pii-review-receipt-path"], None),
        ("--review-trust-anchor", "pii_review_trust_anchor_sha256", CHAINE_PII_V3["--review-trust-anchor-path"], None),
        ("--pii-review-index", "pii_review_index_sha256", CHAINE_PII_V3["--pii-review-index-path"], None),
    ):
        chemin = REPOSITORY_ROOT / chemin_depot if chemin_depot else V3_DIR / str(nom_release)
        reel = _sha(chemin)
        assert reel == autorites[cle], (chemin, reel, autorites[cle])
        args += [f"{option}-path", str(chemin), f"{option}-sha256", reel]
    return args


@pytest.fixture(scope="module")
def produit_pg() -> Iterator[dict[str, str]]:
    yield from start_rag_product_postgres("v3-real-product")


def test_la_chaine_v3_revue_attestation_worker_b_retrieval(
    adopte: dict[str, Any], control_pg: dict[str, str], produit_pg: dict[str, str]
) -> None:

    from _banc_multiniveaux import environnement_de_readiness  # noqa: PLC0415

    modele_brut = os.environ.get(MODELE_E5_ENV, "").strip()
    if not modele_brut:
        pytest.fail(f"{MODELE_E5_ENV} is required: Worker B really embeds")
    modele = Path(modele_brut)
    tmp_path: Path = adopte["tmp_path"]
    github: LocalGitHub = adopte["github"]
    jeton: Path = adopte["jeton"]
    transfert_v3: Path = adopte["transfert_v3"]
    attestor = {"PG_INGESTION_CONTROL_ATTESTOR_DSN": attestor_dsn(control_pg)}

    # ── (1) La chaîne PII est-elle vérifiée HORS LIGNE ? La proposition est
    # lancée SANS aucun accès GitHub : ni forge, ni jeton.
    propose = _run(
        "ingestor.ingestion_worker.attest_publication_cli",
        _arguments_de_proposition_v3(transfert_v3),
        attestor,
    )
    print("REAL_V3_PROPOSE_RC", propose.returncode)
    print("REAL_V3_PROPOSE_STDOUT_HEAD", "\n".join(propose.stdout.splitlines()[:3]))
    print("REAL_V3_PROPOSE_STDERR", propose.stderr[-2000:])
    assert propose.returncode == 0, propose.stderr
    persistee = _champs(propose.stdout, "PROJECTION_PERSISTED")
    assert (persistee["written"], persistee["blocked"]) == ("479", "0"), propose.stdout
    chemin = next(
        ligne.split(" ", 1)[1].strip()
        for ligne in propose.stdout.splitlines()
        if ligne.startswith("REVIEW_ARTIFACT_PATH ")
    )
    octets = propose.stdout[propose.stdout.index("{") :].encode("utf-8")
    revue = json.loads(octets)
    assert revue["release_id"] == V3_ID
    assert revue["placement_evidence"]["currentness"] == "official_snapshot"

    # ── (2) Approbation sur la forge du banc, puis enregistrement ─────────
    tete = hashlib.sha1(f"revue-v3:{_RUN_ID}".encode()).hexdigest()
    github.add_approved_pr(number=8401, head_sha=tete, base_sha="9" * 40, review_id=8411)
    github.put_blob(path=chemin, ref=tete, content=octets)
    with local_github_server(github) as github_url:
        enregistre = _run(
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
            {
                **attestor,
                "NEXUS_GITHUB_API_BASE": github_url,
                "NEXUS_GITHUB_TOKEN_FILE": str(jeton),
            },
        )
    print("REAL_V3_RECORD_STDOUT", enregistre.stdout[-1500:])
    assert enregistre.returncode == 0, enregistre.stderr
    with psycopg.connect(superuser_dsn(control_pg)) as conn:
        attestees = conn.execute(
            "SELECT count(*), count(DISTINCT attestation_digest)"
            "  FROM ingestion_control.publication_attestations"
            " WHERE release_id = %s AND invalidated_at IS NULL",
            (V3_ID,),
        ).fetchone()
        conn.rollback()
    print("REAL_V3_ATTESTATIONS", attestees)
    assert attestees is not None and attestees[0] == 479, attestees

    # ── (3) Worker B, sous readiness de répétition, base produit jetable ──
    # Les arguments sont ceux de ``staging_v3_arguments.worker_b`` (lot CY).
    manifeste = json.loads((V3_DIR / "production-profile-gate.release.json").read_bytes())
    environnement = {
        **environnement_de_readiness(
            tmp_path,
            corpus_manifest_sha256=manifeste["authorities"]["corpus_manifest_sha256"],
        ),
        "PG_INGESTION_CONTROL_DSN": app_dsn(control_pg),
        "PG_RAG_DSN": produit_pg["publisher_dsn"],
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "CUDA_VISIBLE_DEVICES": "",
    }
    arguments = _arguments_worker_b(
        magasin=adopte["magasin"], transfert=transfert_v3, modele=modele
    )
    with local_github_server(github) as github_url:
        acces = {
            **environnement,
            "NEXUS_GITHUB_API_BASE": github_url,
            "NEXUS_GITHUB_TOKEN_FILE": str(jeton),
        }
        worker = _run(
            "ingestor.ingestion_worker.multilevel_publication_resume_cli",
            [*arguments, "--once"],
            acces,
        )
        print("REAL_V3_WORKER_B_YAML_STDERR", worker.stderr.strip())
        # En répétition, Worker B n'accepte qu'un manifeste de profils de
        # STAGING (JSON ``NEXUS_STAGING_PROFILE_MANIFEST_V1``) : le manifeste
        # YAML que V3 lie est refusé avant toute connexion.
        assert worker.returncode == 1
        assert "staging profile manifest cannot be read" in worker.stderr

        # Le même registre, décrit par un manifeste de staging bien formé
        # (document de TEST) : lisible, mais ses octets ne sont pas ceux que
        # V3 déclare (``profile_manifest_sha256``). La release le refuse.
        staging = _manifeste_de_profils_de_staging(tmp_path)
        remplace = list(arguments)
        indice = remplace.index("--profile-manifest-path")
        remplace[indice + 1] = str(staging)
        remplace[indice + 3] = _sha(staging)
        worker = _run(
            "ingestor.ingestion_worker.multilevel_publication_resume_cli",
            [*remplace, "--once"],
            acces,
        )
        print("REAL_V3_WORKER_B_STAGING_JSON_STDERR", worker.stderr.strip())
        assert worker.returncode == 1
        assert "release allowlist authority digest differs" in worker.stderr
    assert manifeste["authorities"]["profile_manifest_sha256"] not in {
        _sha(staging),
        _sha(ENGINE_ROOT / "configs/ingestion_profiles/ingestion_manifest_v2_livraison_319.yml"),
    }

    # Rien n'a été publié ni transité : la base produit est vide.
    with psycopg.connect(produit_pg["admin_dsn"]) as conn:
        totaux = conn.execute(
            "SELECT (SELECT count(*) FROM public.rag_artifacts),"
            "       (SELECT count(*) FROM public.rag_chunks)"
        ).fetchone()
        conn.rollback()
    assert totaux == (0, 0), totaux


def _manifeste_de_profils_de_staging(tmp_path: Path) -> Path:
    """Un manifeste de profils de STAGING décrivant exactement le registre."""
    from ingestor.ingestion_profiles.registry import (  # noqa: PLC0415
        load_profile_registry,
        profile_fingerprint,
    )

    registre = load_profile_registry(PROFILES_DIR)
    chemin = tmp_path / "bench_staging_profile_manifest.json"
    chemin.write_text(
        json.dumps(
            {
                "manifest_kind": "NEXUS_STAGING_PROFILE_MANIFEST_V1",
                "provenance": "real-release adoption bench; test document",
                "generated_at": "2026-09-24T00:00:00Z",
                "authority_mode": "STAGING_LOCAL_GITHUB_ONLY",
                "production_approval": False,
                "profiles": [
                    {
                        "collection": collection,
                        "profile_version": version,
                        "fingerprint": profile_fingerprint(profil),
                    }
                    for (collection, version), profil in sorted(registre.items())
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return chemin


def test_debit_d_embedding_e5_sur_cpu(produit_pg: dict[str, str]) -> None:
    """Le coût d'embedding par chunk, mesuré sur le vrai modèle E5, sur CPU.

    Worker B n'ayant pas pu démarrer sur V3, le débit est mesuré directement
    sur le fournisseur qu'il utilise, avec du texte réel extrait d'un PDF V3.
    """
    import time  # noqa: PLC0415

    from pypdf import PdfReader  # noqa: PLC0415

    from ingestor.embedding_provider import VerifiedE5EmbeddingProvider  # noqa: PLC0415

    modele_brut = os.environ.get(MODELE_E5_ENV, "").strip()
    if not modele_brut:
        pytest.fail(f"{MODELE_E5_ENV} is required: the embedding is measured, not assumed")
    manifeste = json.loads((V3_DIR / "production-profile-gate.release.json").read_bytes())
    anciens = {cle: os.environ.get(cle) for cle in ("CUDA_VISIBLE_DEVICES", "HF_HUB_OFFLINE")}
    os.environ.update({"CUDA_VISIBLE_DEVICES": "", "HF_HUB_OFFLINE": "1"})
    try:
        fournisseur = VerifiedE5EmbeddingProvider.from_artifact(
            artifact_root=Path(modele_brut),
            inventory_sha256=manifeste["models"]["embedding"]["inventory_sha256"],
            pg_dsn=produit_pg["admin_dsn"],
        )
        catalogue = json.loads((V2_DIR / "artifacts.release.json").read_bytes())["artifacts"]
        racines = [
            Path(r) for r in os.environ.get(MIRRORS_ENV, "").split(":") if r.strip()
        ]
        mots: list[str] = []
        for entree in catalogue:
            for racine in racines:
                source = racine / entree["source_path"]
                if source.is_file():
                    for page in PdfReader(str(source)).pages:
                        mots += (page.extract_text() or "").split()
                    break
            if len(mots) > 20000:
                break
        # Des passages de 180 mots, taille de l'ordre d'un chunk de release.
        passages = [" ".join(mots[i : i + 180]) for i in range(0, 180 * 32, 180)]
        passages = [
            p for p in passages if fournisseur.passage_token_count(p) <= fournisseur.max_sequence_length
        ]
        fournisseur.encode(passages[:2])  # chauffe
        debut = time.monotonic()
        vecteurs = fournisseur.encode(passages)
        duree = time.monotonic() - debut
    finally:
        for cle, valeur in anciens.items():
            if valeur is None:
                os.environ.pop(cle, None)
            else:
                os.environ[cle] = valeur
    chunks = sum(
        len(a["chunks"])
        for a in json.loads((V3_DIR / "artifacts.release.json").read_bytes())["artifacts"]
    )
    par_chunk = duree / len(passages)
    print(
        "REAL_V3_E5_CPU passages=", len(passages), "seconds=", round(duree, 2),
        "s_per_chunk=", round(par_chunk, 3),
        "avg_chunks_per_artifact=", round(chunks / 315, 1),
        "s_per_artifact_est=", round(par_chunk * chunks / 315, 1),
        "s_all_8268_est=", round(par_chunk * chunks),
    )
    assert len(vecteurs) == len(passages) and all(len(v) == 1024 for v in vecteurs)
