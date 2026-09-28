"""Topologie et arrêts sûrs de l'orchestrateur HGGSP (aucun SSH)."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/go_live/staging_hggsp_complementary.sh"


def test_shell_syntax_and_status_have_no_server_effect() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)
    result = subprocess.run(
        ["bash", str(SCRIPT), "status"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    assert "successor_independent_verification" in result.stdout
    assert "successor_worker_b_publication" in result.stdout


def test_premerge_run_fails_before_ssh() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "run"], cwd=ROOT, capture_output=True, text=True
    )
    assert result.returncode != 0
    assert ("autorisation HGGSP active absente" in result.stderr
            or "checkout opérateur différent de origin/main fusionné" in result.stderr
            or "successor_readiness_install refusée par l'autorité active" in result.stderr)


def test_image_scope_guard_is_local_and_precedes_remote() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.index("images_locales\n        for op") < source.index('preflight_hggsp "$op"')
    assert "load_retrieval_scope_registry" in source
    assert 'sys.path.insert(0, str(Path("packages/contracts/src").resolve()))' in source
    assert "--network none" in source
    assert "PYTHONPATH=" not in source
    assert "cancel" not in " ".join(source.split("ORDRE_HGGSP=(", 1)[1].split(")", 1)[0].split())


def test_container_transfer_path_and_signed_remote_binding_are_explicit() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    transfer = source.split("etape_successor_sealed_ingestion_or_binding() {", 1)[1].split("\netape_", 1)[0]
    assert "$(jeton_present)" in transfer
    assert '-e NEXUS_GITHUB_TOKEN_FILE=/run/secrets/github-token' in transfer
    assert '-v "$REMOTE_GITHUB_TOKEN_FILE:/run/secrets/github-token:ro"' in transfer
    assert 'TRANSFER_HOST="$RUN/transfer_manifest_hggsp_successor.json"' in source
    assert 'TRANSFER_CONTAINER="/run-db/transfer_manifest_hggsp_successor.json"' in source
    assert '--output "$TRANSFER_CONTAINER"' in source
    assert '--transfer-manifest-path "$TRANSFER_CONTAINER"' in source
    assert 'readiness_distante' in source
    assert 'sha256sum "$READINESS_LOCAL/$READINESS_BINDING"' in source


def test_rate_limited_worker_relaunch_uses_new_name_and_preserves_old() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'worker-b.attempt' in source
    assert 'WORKER_B_HGGSP-$attempt' in source
    assert 'exited 75' in source
    assert 'docker rm' not in source.split("etape_successor_worker_b_publication()", 1)[1].split(
        "etape_successor_independent_verification()", 1
    )[0]


def test_historical_database_uses_existing_v4_baseline() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'V4_STATE_DIR="${V4_STATE_DIR:-$HOME/nexus-staging-v4-run}"' in source
    assert 'cmp -s "$V4_STATE_DIR/legacy_baseline.txt" "$STATE_DIR/legacy_baseline.txt"' in source
    assert '[ "$op" = successor_readiness_install ] || [ "$op" = successor_preflight ]' in source


def test_attestation_stage_requires_74_after_batch_record() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'successor_attestations) echo attested' in source
    assert 'successor_readiness_install successor_preflight' in source
    assert 'successor_scope_authorization_registration_r4 successor_sealed_ingestion_or_binding' in source
    assert 'claim_scope=$COLLECTION_P,$COLLECTION_T claim_release_id=$RELEASE_HGGSP' in source


def test_enqueue_is_only_orchestrated_after_live_preflight() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    enqueue = source.split("etape_successor_publication_job_enqueue() {", 1)[1].split("\nargs_worker_hggsp()", 1)[0]
    assert 'require_authority_for_write(Path("/repo"), "successor_publication_job_enqueue")' in enqueue
    assert 'counts = enqueue_successor(conn)' in enqueue
    assert 'conn.commit()' in enqueue
    assert 'preflight_hggsp "$op"' in source
    assert source.index('preflight_hggsp "$op"') < source.index('"etape_$op"')
