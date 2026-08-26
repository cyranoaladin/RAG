"""L'invariant de reprise après restauration (P0-L2).

`pg_dump -Fc` d'une base ne transporte pas les rôles PostgreSQL : ils sont
globaux au cluster. `pg_restore` signale alors les GRANT orphelins en erreurs
ignorées et sort malgré tout en 0 — une base restaurée peut donc être complète
et silencieusement dépourvue de tout privilège runtime.

L'invariant est :

    provision cluster-global roles -> restore database -> verify grants

Ces tests portent sur la troisième jambe : sa présence dans le runbook, et le
fait que le vérificateur refuse chacun des états dégradés qu'il doit détecter.
Le comportement contre un vrai PostgreSQL est exercé par le rehearsal du
runbook, pas ici.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ENGINE_ROOT.parents[1]
VERIFIER = ENGINE_ROOT / "infra" / "scripts" / "verify_runtime_role_grants.sh"
ROLLBACK_RUNBOOK = REPOSITORY_ROOT / "docs" / "runbooks" / "rollback.md"

#: Chaque état dégradé que la restauration peut produire, et le motif exact que
#: l'opérateur doit lire. Un motif générique ne dirait pas quoi rejouer.
REFUSAL_REASONS = (
    "roles_absent_restore_ran_before_provisioning",
    "retrieval_role_lost_its_select_grant",
    "retrieval_role_gained_a_write_grant",
    "review_role_lost_its_select_grant",
    "review_role_gained_an_unexpected_grant",
    "publisher_role_grants_are_incomplete",
    "publisher_role_gained_a_destructive_grant",
    "runtime_role_holds_administrative_attribute",
    "runtime_role_reaches_an_auxiliary_relation",
)


def test_the_verifier_is_executable_and_syntactically_valid() -> None:
    assert VERIFIER.is_file()
    assert VERIFIER.stat().st_mode & 0o111, "le vérificateur doit être exécutable"
    subprocess.run(["bash", "-n", str(VERIFIER)], check=True)


@pytest.mark.parametrize("reason", REFUSAL_REASONS)
def test_every_degraded_restore_state_has_its_own_refusal_reason(
    reason: str,
) -> None:
    assert reason in VERIFIER.read_text(encoding="utf-8")


def test_the_verifier_refuses_rather_than_reporting_when_it_cannot_observe() -> None:
    """Une base injoignable n'est pas une restauration réussie."""
    body = VERIFIER.read_text(encoding="utf-8")
    assert "pgvector_container_not_running" in body
    assert "set -euo pipefail" in body
    # Le motif d'échec est toujours nommé : jamais un simple code de sortie.
    assert re.search(r"RUNTIME_ROLE_GRANTS=FAIL\\nREASON=%s", body)


def test_the_verifier_reads_the_target_from_the_caller_not_from_env_file() -> None:
    """Vérifier les droits d'une autre base que celle restaurée ne prouve rien."""
    body = VERIFIER.read_text(encoding="utf-8")
    assert 'load_deployment_environment "$INFRA_DIR/.env"' in body
    assert 'PGVECTOR_CONTAINER="${PGVECTOR_CONTAINER:-rag_pgvector}"' in body
    assert body.index("load_deployment_environment") < body.index(
        'PGVECTOR_CONTAINER="${PGVECTOR_CONTAINER'
    )


def test_the_rollback_runbook_prescribes_the_three_step_invariant() -> None:
    runbook = ROLLBACK_RUNBOOK.read_text(encoding="utf-8")

    assert "provision cluster-global roles -> restore database -> verify grants" in runbook
    assert "verify_runtime_role_grants.sh" in runbook

    # La vérification vient après la restauration et après le reprovisionnement.
    # Les ancres sont les invocations, pas les définitions de variables : la
    # racine du provisionneur est déclarée bien plus haut dans le bloc.
    restore_position = runbook.index("--no-privileges")
    provision_position = runbook.index("/opt/nexus/provision_runtime_roles.sh")
    verify_position = runbook.index("bash \"$PWD/scripts/verify_runtime_role_grants.sh\"")
    assert restore_position < provision_position < verify_position


def test_the_runbook_explains_why_pg_dump_alone_cannot_recover_the_grants() -> None:
    """Sans la raison, l'étape se fait sauter au premier incident pressé."""
    runbook = ROLLBACK_RUNBOOK.read_text(encoding="utf-8")
    assert "ne transporte pas les rôles" in runbook
    assert "erreurs ignorées" in runbook
