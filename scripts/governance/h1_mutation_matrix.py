#!/usr/bin/env python3
"""Matrice de non-vacuité GATE H1 (item N).

**Le problème.** Un test adverse qui passe ne prouve rien par lui-même : il
peut passer parce que la protection fonctionne, ou parce que l'assertion ne
mesure rien. La seule preuve est de *casser la protection* et de vérifier
que le test devient rouge.

Ce script fait exactement cela, pour douze invariants critiques :

1. liaison à l'artefact revu        7. scope divergent
2. liaison à l'authorization_id     8. qualité négative
3. liaison au review_id GitHub      9. gate négatif
4. liaison au reviewer             10. droits interdits
5. liaison au challenge            11. échéance globale (timeout)
6. révocation                      12. isolation des privilèges PostgreSQL

Pour chacun : mutation ciblée -> le test DOIT devenir rouge -> restauration
-> le test DOIT redevenir vert. Une mutation qui laisse le test vert est un
échec de ce script, et signale un test vacant.

**La mutation n'est jamais commitée.** Les octets d'origine sont conservés
en mémoire et restaurés dans un ``finally`` ; le script vérifie en sortie
que l'arbre de travail est identique à son état initial, et échoue
bruyamment sinon.

Usage :

    python scripts/governance/h1_mutation_matrix.py            # tout
    python scripts/governance/h1_mutation_matrix.py --only 3 7 # ciblé
    python scripts/governance/h1_mutation_matrix.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_ROOT = REPO_ROOT / "services" / "rag-engine"
SRC = ENGINE_ROOT / "src" / "ingestor"
INFRA = ENGINE_ROOT / "infra"
PYTEST = [str(ENGINE_ROOT / ".venv" / "bin" / "python"), "-m", "pytest", "-q", "-x"]


@dataclass(frozen=True)
class Mutation:
    """Une mutation = un remplacement textuel exact dans un fichier.

    ``old`` doit apparaître **exactement une fois** : une correspondance
    multiple ou absente signifie que le code a bougé et que la mutation ne
    vise plus ce qu'elle croit viser — le script échoue alors plutôt que de
    muter au hasard."""

    path: Path
    old: str
    new: str


@dataclass(frozen=True)
class Check:
    number: int
    invariant: str
    protection: str
    mutations: tuple[Mutation, ...]
    test: str
    #: Fragment attendu dans la sortie rouge — garantit que le test échoue
    #: pour LA bonne raison, pas pour une erreur d'import provoquée par la
    #: mutation elle-même.
    expected_failure_contains: str = ""
    extra_env: dict[str, str] = field(default_factory=dict)


def source(relative: str) -> Path:
    return SRC / relative


CHECKS: tuple[Check, ...] = (
    Check(
        number=1,
        invariant="artifact binding",
        protection=(
            "scope_authority._verify_reviewed_artifact compare le SHA de blob "
            "relu au SHA persisté"
        ),
        mutations=(
            Mutation(
                path=source("ingestion_control/scope_authority.py"),
                old='''    _require_equal(
        field="artifact_blob_sha", stored=row["artifact_blob_sha"],
        live=blob.blob_sha, authorization_id=authorization_id,
    )''',
                new="    pass  # MUTATION",
            ),
            Mutation(
                path=source("ingestion_control/scope_authority.py"),
                old='''    _require_equal(
        field="authorization_digest", stored=row["authorization_digest"],
        live=artifact.digest(), authorization_id=authorization_id,
    )''',
                new="    pass  # MUTATION",
            ),
        ),
        test=(
            "tests/integration/test_lot41a_scope_authority.py::"
            "TestArtifactBytesAreBinding::test_modified_bytes_at_the_same_head_are_denied"
        ),
    ),
    Check(
        number=2,
        invariant="authorization_id binding",
        protection=(
            "scope_enforcement.enforce_before_fetch exige que l'autorisation "
            "vérifiée soit celle que le job nomme"
        ),
        mutations=(
            Mutation(
                path=source("ingestion_control/scope_enforcement.py"),
                old="    if authorization.authorization_id != authorization_id:",
                new="    if False:  # MUTATION",
            ),
        ),
        test=(
            "tests/test_lot41a_scope_enforcement.py::TestPreFetchCheckpoint::"
            "test_a_different_authorization_id_is_refused"
        ),
    ),
    Check(
        number=3,
        invariant="GitHub review-id binding",
        protection="scope_authority._verify_live_review compare evidence_review_id",
        mutations=(
            Mutation(
                path=source("ingestion_control/scope_authority.py"),
                old='''    _require_equal(
        field="evidence_review_id", stored=row["evidence_review_id"],
        live=live.review_id, authorization_id=authorization_id,
    )''',
                new="    pass  # MUTATION",
            ),
        ),
        test=(
            "tests/integration/test_lot41a_scope_authority.py::"
            "TestLiveGitHubProofIsFieldByField::"
            "test_a_single_diverging_evidence_field_is_denied[evidence_review_id-999999]"
        ),
    ),
    Check(
        number=4,
        invariant="reviewer binding",
        protection="scope_authority._verify_live_review compare evidence_reviewer",
        mutations=(
            Mutation(
                path=source("ingestion_control/scope_authority.py"),
                old='''    _require_equal(
        field="evidence_reviewer", stored=row["evidence_reviewer"],
        live=live.reviewer, authorization_id=authorization_id,
    )''',
                new="    pass  # MUTATION",
            ),
        ),
        test=(
            "tests/integration/test_lot41a_scope_authority.py::"
            "TestLiveGitHubProofIsFieldByField::"
            "test_a_single_diverging_evidence_field_is_denied[evidence_reviewer-someone-else]"
        ),
    ),
    Check(
        number=5,
        invariant="challenge binding",
        protection="scope_authority._verify_live_review compare evidence_challenge",
        mutations=(
            Mutation(
                path=source("ingestion_control/scope_authority.py"),
                old='''    _require_equal(
        field="evidence_challenge", stored=row["evidence_challenge"],
        live=live.challenge, authorization_id=authorization_id,
    )''',
                new="    pass  # MUTATION",
            ),
        ),
        test=(
            "tests/integration/test_lot41a_scope_authority.py::"
            "TestLiveGitHubProofIsFieldByField::"
            "test_a_challenge_belonging_to_another_pr_is_denied"
        ),
    ),
    Check(
        number=6,
        invariant="revocation",
        protection=(
            "scope_authority.verify_scope_authorization refuse une ligne "
            "révoquée, ET refuse une review GitHub dismissée"
        ),
        mutations=(
            Mutation(
                path=source("ingestion_control/scope_authority.py"),
                old="    if not live.approved:",
                new="    if False:  # MUTATION",
            ),
        ),
        test=(
            "tests/integration/test_lot41a_scope_authority.py::"
            "TestLiveGitHubProofIsFieldByField::test_review_dismissal_is_denied"
        ),
    ),
    Check(
        number=7,
        invariant="scope mismatch",
        protection=(
            "scope_authority.verify_scope_authorization compare les dix "
            "dimensions du scope demandé à celles de l'autorisation"
        ),
        mutations=(
            Mutation(
                path=source("ingestion_control/scope_authority.py"),
                old="    if scope is not None and scope_key(scope) != scope_key(stored_scope):",
                new="    if False:  # MUTATION",
            ),
        ),
        test=(
            "tests/integration/test_lot41a_scope_authority.py::"
            "TestScopeBindingIsExplicit::test_a_different_scope_is_denied"
        ),
    ),
    Check(
        number=8,
        invariant="quality false",
        protection=(
            "attest_publication_cli._reject_negative_chain refuse une "
            "quality_passed=false avant toute construction d'artefact"
        ),
        mutations=(
            Mutation(
                path=source("ingestion_worker/attest_publication_cli.py"),
                old="    if not facts.quality_passed:",
                new="    if False:  # MUTATION",
            ),
        ),
        test=(
            "tests/integration/test_lot42_publication_attestation.py::"
            "TestNegativeChainsNeverPublish::"
            "test_a_failing_quality_chain_is_refused_at_proposal"
        ),
    ),
    Check(
        number=9,
        invariant="gate false",
        protection=(
            "PublicationReviewArtifact rend une décision à gate_passed=false "
            "irreprésentable"
        ),
        mutations=(
            Mutation(
                path=REPO_ROOT / "packages" / "contracts" / "src" / "nexus_contracts"
                / "authority_artifacts.py",
                old="""        if not self.gate_passed:
            raise ValueError(
                "gate_passed must be true — a publication review artifact can "
                "never be constructed for a resource that failed the gate"
            )""",
                new="        pass  # MUTATION",
            ),
        ),
        test=(
            "tests/test_lot41a_authority_artifacts.py::"
            "TestPublicationReviewArtifactRefusesNegativeChains::"
            "test_negative_chains_cannot_be_constructed[overrides1-gate_passed must be true]"
        ),
    ),
    Check(
        number=10,
        invariant="rights forbidden",
        protection=(
            "scope_enforcement.enforce_rights refuse une catégorie hors de "
            "rights_categories"
        ),
        mutations=(
            Mutation(
                path=source("ingestion_control/scope_enforcement.py"),
                old="    if value not in authorization.rights_categories:",
                new="    if False:  # MUTATION",
            ),
        ),
        test=(
            "tests/integration/test_lot41a_worker_enforcement.py::"
            "TestRightsCheckpoint::test_a_forbidden_rights_category_denies_before_quality"
        ),
    ),
    Check(
        number=11,
        invariant="global timeout",
        protection="github_authority._Deadline borne l'opération complète (item J)",
        mutations=(
            Mutation(
                path=source("ingestion_control/github_authority.py"),
                old="""        left = self.remaining()
        if left <= 0:""",
                new="""        left = self.remaining()
        if False:  # MUTATION""",
            ),
            Mutation(
                path=source("ingestion_control/github_authority.py"),
                old="""            response = self._client.get(
                url, timeout=httpx.Timeout(min(self._request_timeout_s, remaining))
            )""",
                new="""            response = self._client.get(url, timeout=httpx.Timeout(600.0))""",
            ),
        ),
        test=(
            "tests/test_lot41a_github_authority_transport.py::"
            "TestOutageAndTimeoutAreBounded::"
            "test_total_deadline_is_enforced_across_multiple_requests"
        ),
    ),
    Check(
        number=12,
        invariant="PostgreSQL privilege isolation",
        protection=(
            "provision_ingestion_control_roles.sh n'accorde jamais INSERT sur "
            "scope_authorizations au rôle applicatif"
        ),
        mutations=(
            Mutation(
                path=INFRA / "scripts" / "provision_ingestion_control_roles.sh",
                old='GRANT SELECT ON ingestion_control.scope_authorizations TO :"app_role" ;',
                new=(
                    'GRANT SELECT ON ingestion_control.scope_authorizations TO :"app_role" ;\n'
                    '-- MUTATION\n'
                    'GRANT INSERT ON ingestion_control.scope_authorizations TO :"app_role" ;'
                ),
            ),
        ),
        test=(
            "tests/integration/test_lot41a_operator_role_isolation.py::"
            "TestWorkerRoleCannotWriteAuthorityTables::"
            "test_insert_scope_authorization_is_denied"
        ),
    ),
)


def run_test(node: str) -> tuple[bool, str]:
    result = subprocess.run(
        [*PYTEST, node],
        cwd=ENGINE_ROOT,
        capture_output=True,
        text=True,
        env={**_base_env(), "PYTHONPATH": "src"},
        check=False,
        timeout=3600,
    )
    return result.returncode == 0, result.stdout + result.stderr


def _base_env() -> dict[str, str]:
    import os

    return dict(os.environ)


def apply_mutations(mutations: tuple[Mutation, ...]) -> dict[Path, str]:
    """Applique les mutations et rend les contenus d'origine, indexés par
    chemin. Toute mutation dont ``old`` n'apparaît pas exactement une fois
    fait échouer le script : muter approximativement ne prouve rien."""
    originals: dict[Path, str] = {}
    for mutation in mutations:
        text = mutation.path.read_text(encoding="utf-8")
        originals.setdefault(mutation.path, text)
        occurrences = text.count(mutation.old)
        if occurrences != 1:
            restore(originals)
            raise SystemExit(
                f"MUTATION_ANCHOR_LOST: {mutation.path} contains {occurrences} "
                f"occurrences of the anchor (expected exactly 1). The protection "
                f"has moved; update the matrix rather than mutating blindly."
            )
        mutation.path.write_text(text.replace(mutation.old, mutation.new), encoding="utf-8")
    return originals


def restore(originals: dict[Path, str]) -> None:
    for path, text in originals.items():
        path.write_text(text, encoding="utf-8")


def mutated_files_are_restored(baseline: dict[Path, str]) -> list[Path]:
    """Compare les octets ACTUELS des seuls fichiers mutés à leur état
    d'avant-run.

    Volontairement restreint à ces fichiers : comparer `git status` global
    ferait échouer le script sur une édition concurrente sans aucun rapport
    (un fichier de documentation modifié pendant la campagne, par exemple),
    ce qui masquerait le seul signal qui compte — une mutation non
    restaurée."""
    return [
        path for path, text in baseline.items()
        if path.read_text(encoding="utf-8") != text
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", type=int, default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    selected_paths = {
        mutation.path
        for check in CHECKS
        for mutation in check.mutations
    }
    baseline = {path: path.read_text(encoding="utf-8") for path in selected_paths}

    selected = [c for c in CHECKS if args.only is None or c.number in args.only]
    results: list[dict[str, object]] = []
    failures = 0

    for check in selected:
        print(f"\n=== [{check.number}/12] {check.invariant} ===", flush=True)

        green_before, _ = run_test(check.test)
        print(f"  baseline (protection en place)      : {'GREEN' if green_before else 'RED'}")

        originals = apply_mutations(check.mutations)
        try:
            green_mutated, output = run_test(check.test)
        finally:
            restore(originals)
        print(f"  sous mutation (protection retirée)  : {'GREEN' if green_mutated else 'RED'}")

        green_after, _ = run_test(check.test)
        print(f"  après restauration                  : {'GREEN' if green_after else 'RED'}")

        reason_ok = (
            not check.expected_failure_contains
            or check.expected_failure_contains in output
        )
        verdict = green_before and (not green_mutated) and green_after and reason_ok
        if not verdict:
            failures += 1
        print(f"  -> {'NON-VACUOUS' if verdict else 'VACUOUS / INCONCLUSIVE'}")

        results.append({
            "number": check.number,
            "invariant": check.invariant,
            "protection": check.protection,
            "test": check.test,
            "green_before": green_before,
            "red_under_mutation": not green_mutated,
            "green_after_restore": green_after,
            "verdict": "NON_VACUOUS" if verdict else "VACUOUS",
        })

    unrestored = mutated_files_are_restored(baseline)
    if unrestored:
        print(
            "\nFATAL: these files differ from their pre-run state — a mutation "
            "was NOT restored. Investigate before committing anything:\n  "
            + "\n  ".join(str(path) for path in unrestored),
            file=sys.stderr,
        )
        return 2

    print(f"\nMUTATION_CHECKS_PASSED={len(selected) - failures}/{len(selected)}")
    if args.json:
        args.json.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        print(f"matrix written to {args.json}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
