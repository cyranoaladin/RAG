"""Topologie et arrêts sûrs de l'orchestrateur HGGSP (aucun SSH)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


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
    local_guard = source.split("images_locales() {", 1)[1].split("\n}\n", 1)[0]
    assert "PYTHONPATH=" not in local_guard
    remote_probe = source.split("etape_successor_independent_verification() {", 1)[1].split("\n}\n", 1)[0]
    assert "-e PYTHONPATH=/app" in remote_probe
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


def test_control_020_precedes_scopes_and_adoption_and_adoption_is_v2_under_adopter() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    ordre = source.split("ORDRE_HGGSP=(", 1)[1].split(")", 1)[0].split()
    assert ordre.index("successor_control_schema_020_and_adopter_role") == ordre.index("successor_preflight") + 1
    assert ordre.index("successor_control_schema_020_and_adopter_role") < ordre.index(
        "successor_sealed_ingestion_or_binding")
    adoption = source.split("adopt-predecessor-release", 1)[0].rsplit("worker ", 1)[1]
    assert adoption.startswith('"$REMOTE_ADOPTER_ENV"')
    assert "--adoption-version SEALED-RELEASE-ADOPTION-V2" in source
    assert "--verify-v2-lineage" in source
    assert "written=74 already_present=0|written=0 already_present=74" in source


def test_control_020_step_never_passes_secrets_as_arguments() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    etape = source.split("etape_successor_control_schema_020_and_adopter_role() {", 1)[1].split("\n}\n", 1)[0]
    # Seul le fichier staging.env (connexion administrative) est sourcé ; les
    # mots de passe des rôles historiques ne sont même pas chargés.
    assert '. "$REMOTE_STAGING_ENV"' in etape
    assert "REMOTE_CONTROL_SOURCE_ENV" not in etape
    assert "INGESTION_CONTROL_" not in etape
    assert "--secret-file" in etape and "PASSWORD=" not in etape.replace('PGPASSWORD="\\$PGVECTOR_PASSWORD"', "")
    assert "pg_restore --list" in etape
    assert "HGGSP_CONTROL020_OK head=20" in etape


# ── OPERATOR_ID : l'identité d'audit arrive comme UN seul argv ────────────────

OPERATEUR = "Alaeddine Ben Rhouma"


def _arg_shell(valeur: str) -> str:
    """La vraie fonction du script, extraite et exécutée telle quelle."""
    ligne = next(
        ligne for ligne in SCRIPT.read_text(encoding="utf-8").splitlines()
        if ligne.startswith("arg_shell() {")
    )
    resultat = subprocess.run(
        ["bash", "-c", f'{ligne}\narg_shell "$1"', "_", valeur],
        capture_output=True, text=True, check=True,
    )
    return resultat.stdout


def _argv_distant(ligne_de_commande: str) -> list[str]:
    """Ce que le shell distant lit dans la commande que `worker` reconstruit avec $*."""
    sortie = subprocess.run(
        ["bash", "-c", f"printf '%s\\n' {ligne_de_commande}"],
        capture_output=True, text=True, check=True,
    )
    return sortie.stdout.splitlines()


def test_operator_id_non_echappe_serait_coupe_en_trois_arguments() -> None:
    assert _argv_distant(f"--adopted-by {OPERATEUR}") == [
        "--adopted-by", "Alaeddine", "Ben", "Rhouma",
    ]


def test_operator_id_arrive_comme_un_seul_argv_sans_guillemets_stockes() -> None:
    echappe = _arg_shell(OPERATEUR)
    assert "'" not in echappe and '"' not in echappe
    assert _argv_distant(f"--adopted-by {echappe} --bound-by {echappe} --autre x") == [
        "--adopted-by", OPERATEUR, "--bound-by", OPERATEUR, "--autre", "x",
    ]


@pytest.mark.parametrize("valeur", ["simple", "a b", "Alaeddine Ben Rhouma", "d'Artagnan", 'dit "oui"', "x;y", "$(id)"])
def test_operator_id_aller_retour_exact(valeur: str) -> None:
    assert _argv_distant(f"--adopted-by {_arg_shell(valeur)}") == ["--adopted-by", valeur]


def test_operator_id_est_valide_puis_echappe_aux_deux_sites() -> None:
    etape = SCRIPT.read_text(encoding="utf-8").split(
        "etape_successor_sealed_ingestion_or_binding() {", 1)[1].split("\netape_", 1)[0]
    assert '--adopted-by "$(arg_shell "$OPERATOR_ID")"' in etape
    assert '--bound-by "$(arg_shell "$OPERATOR_ID")"' in etape
    assert "${OPERATOR_ID:?" not in etape
    # validé AVANT le premier appel distant : aucun effet si l'identité manque
    assert etape.index('[ -n "${OPERATOR_ID:-}" ]') < etape.index("remote <<EOF")


def test_l_evaluateur_de_la_revue_batch_est_valide_puis_echappe() -> None:
    """Même défaut que OPERATOR_ID : sans échappement, `--evaluator "Alaeddine Ben Rhouma"` était coupé
    en trois arguments et la proposition refusée (`unrecognized arguments: Ben Rhouma`)."""
    etape = SCRIPT.read_text(encoding="utf-8").split(
        "etape_successor_batch_review_proposal() {", 1)[1].split("\netape_", 1)[0]
    assert '--evaluator "$(arg_shell "$EVALUATOR")"' in etape
    assert "${EVALUATOR:?" not in etape
    assert etape.index('[ -n "${EVALUATOR:-}" ]') < etape.index("worker ")  # validé avant l'appel distant
    echappe = _arg_shell(OPERATEUR)
    assert "'" not in echappe and '"' not in echappe
    assert _argv_distant(f"--evaluator {echappe} --review-id lot42-x") == [
        "--evaluator", OPERATEUR, "--review-id", "lot42-x",
    ]
