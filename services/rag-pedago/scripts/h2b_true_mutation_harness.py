#!/usr/bin/env python3
"""Exécute douze vraies mutations H2-B et restaure exactement les octets.

Chaque contrôle suit la même séquence : test ciblé vert, neutralisation
textuelle exacte du garde, test rouge pour la raison attendue, restauration
dans ``finally``, vérification SHA-256, puis retour au vert. Une ancre
absente ou multiple est un échec, jamais une mutation approximative.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[3]
PEDAGO_ROOT = REPO_ROOT / "services" / "rag-pedago"
ENGINE_ROOT = REPO_ROOT / "services" / "rag-engine"
PEDAGO_SRC = PEDAGO_ROOT / "rag_pedago" / "imports"
ENGINE_SRC = ENGINE_ROOT / "src" / "ingestor"

REPORT_FIELDS = (
    "BASELINE_GREEN",
    "MUTATION_APPLIED",
    "TARGET_TEST",
    "MUTANT_RED",
    "EXPECTED_FAILURE",
    "ACTUAL_FAILURE",
    "DIRECT_CAUSE",
    "MASKED_BY_OTHER_GUARD",
    "RESTORED_BYTES",
    "RESTORED_GREEN",
    "NON_VACUOUS",
)


class Mutation(NamedTuple):
    path: Path
    old: str
    new: str


class Check(NamedTuple):
    number: int
    invariant: str
    protection: str
    service: str
    mutations: tuple[Mutation, ...]
    test: str
    expected_failure_contains: str


def pedago_source(name: str) -> Path:
    return PEDAGO_SRC / name


def engine_source(name: str) -> Path:
    return ENGINE_SRC / name


CHECKS: tuple[Check, ...] = (
    Check(
        1,
        "rights",
        "_apply_mandatory_ingest_gates refuse un SHA absent des droits autorisés",
        "pedago",
        (
            Mutation(
                pedago_source("corpus_catalog_compiler.py"),
                "if content_sha256 in rights_cleared_sha256",
                "if True  # MUT-H2B-01",
            ),
        ),
        "tests/test_h2b_true_mutation_targets.py::test_mut_h2b_01_rights_guard_blocks_uncleared_ingest",
        "MUT-H2B-01 rights guard was neutralized",
    ),
    Check(
        2,
        "PII",
        "_apply_mandatory_ingest_gates donne priorité à la quarantaine PII",
        "pedago",
        (
            Mutation(
                pedago_source("corpus_catalog_compiler.py"),
                "if content_sha256 in pii_quarantined_sha256",
                "if False  # MUT-H2B-02",
            ),
        ),
        "tests/test_h2b_true_mutation_targets.py::test_mut_h2b_02_pii_guard_quarantines_detected_signal",
        "MUT-H2B-02 PII guard was neutralized",
    ),
    Check(
        3,
        "currentness",
        "classify_document ne rend éligible que Currentness.ACTUEL",
        "pedago",
        (
            Mutation(
                pedago_source("currentness_gate.py"),
                "    ingest_eligible = currentness == Currentness.ACTUEL",
                "    ingest_eligible = True  # MUT-H2B-03",
            ),
        ),
        "tests/test_h2b_true_mutation_targets.py::test_mut_h2b_03_currentness_guard_denies_non_current_ingest",
        "MUT-H2B-03 currentness guard was neutralized",
    ),
    Check(
        4,
        "exclusion",
        "corpus_zone_routing exclut explicitement 00_ADMIN",
        "pedago",
        (
            Mutation(
                PEDAGO_ROOT / "configs" / "corpus_zone_routing.yml",
                '  - zone_prefix: "00_ADMIN/"\n    disposition: EXCLUDE',
                '  - zone_prefix: "00_ADMIN/"\n    disposition: REVIEW_REQUIRED  # MUT-H2B-04',
            ),
        ),
        "tests/test_h2b_true_mutation_targets.py::test_mut_h2b_04_exclusion_guard_keeps_admin_out",
        "MUT-H2B-04 exclusion guard was neutralized",
    ),
    Check(
        5,
        "unsupported format",
        "corpus_zone_routing maintient GeoGebra hors ingestion",
        "pedago",
        (
            Mutation(
                PEDAGO_ROOT / "configs" / "corpus_zone_routing.yml",
                '  - zone_prefix: "03_RESSOURCES_INTERACTIVES/"\n    disposition: UNSUPPORTED',
                '  - zone_prefix: "03_RESSOURCES_INTERACTIVES/"\n    disposition: REVIEW_REQUIRED  # MUT-H2B-05',
            ),
        ),
        "tests/test_h2b_true_mutation_targets.py::test_mut_h2b_05_unsupported_guard_keeps_ggb_out",
        "MUT-H2B-05 unsupported-format guard was neutralized",
    ),
    Check(
        6,
        "unknown object",
        "_attach_eduscol_placements refuse un SHA absent du manifest physique",
        "pedago",
        (
            Mutation(
                pedago_source("corpus_catalog_compiler.py"),
                '''            if artifact is None or not any(
                item.path.startswith("01_EDUSCOL_OFFICIEL/")
                for item in artifact.physical_objects
            ):
                raise ValueError(
                    "unknown Eduscol content SHA256 at placement line "
                    f"{line_number}: {content_sha256}"
                )''',
                '''            if artifact is None or not any(
                item.path.startswith("01_EDUSCOL_OFFICIEL/")
                for item in artifact.physical_objects
            ):
                continue  # MUT-H2B-06''',
            ),
        ),
        "tests/test_corpus_catalog_compiler.py::TestSealedCorpusCompilation::test_rejects_unknown_placement_content",
        "DID NOT RAISE",
    ),
    Check(
        7,
        "content SHA",
        "scan_remote_corpus bloque les octets dont le SHA diffère du manifest",
        "pedago",
        (
            Mutation(
                pedago_source("remote_pii_scan.py"),
                "                if _file_sha256(local_target) != content_sha256:",
                "                if False:  # MUT-H2B-07",
            ),
        ),
        "tests/test_remote_pii_scan.py::test_sha_mismatch_blocks_before_scanner_execution",
        "scan_calls == 0",
    ),
    Check(
        8,
        "manifest",
        "compile_sealed_catalog lie les octets au digest de manifest attendu",
        "pedago",
        (
            Mutation(
                pedago_source("corpus_catalog_compiler.py"),
                "    if manifest_sha256 != expected_manifest_sha256:",
                "    if False:  # MUT-H2B-08",
            ),
        ),
        "tests/test_corpus_catalog_compiler.py::TestSealedCorpusCompilation::test_rejects_manifest_digest_drift",
        "DID NOT RAISE",
    ),
    Check(
        9,
        "scope authority",
        "enforce_before_fetch exige l'égalité des dix dimensions de scope",
        "engine",
        (
            Mutation(
                engine_source("ingestion_control/scope_enforcement.py"),
                "    if scope_key(authorization.scope) != scope_key(scope):",
                "    if False:  # MUT-H2B-09",
            ),
        ),
        "tests/test_lot41a_scope_enforcement.py::TestPreFetchCheckpoint::test_a_different_scope_is_refused",
        "DID NOT RAISE",
    ),
    Check(
        10,
        "revocation",
        "verify_scope_authorization refuse une ligne révoquée avant GitHub",
        "engine",
        (
            Mutation(
                engine_source("ingestion_control/scope_authority.py"),
                '    if row["revoked_at"] is not None:',
                "    if False:  # MUT-H2B-10",
            ),
        ),
        "tests/integration/test_lot41a_scope_authority.py::TestRevocationAndValidityWindow::test_revoked_authorization_is_denied",
        "DID NOT RAISE",
    ),
    Check(
        11,
        "extraction failure",
        "scan_remote_corpus ne délivre jamais un PDF dont l'extraction a échoué",
        "pedago",
        (
            Mutation(
                pedago_source("remote_pii_scan.py"),
                "                    if scan_result.extraction_error:",
                "                    if False:  # MUT-H2B-11",
            ),
        ),
        "tests/test_remote_pii_scan.py::test_external_evidence_never_contains_raw_pii_or_exception_text",
        "pii_extraction_failed",
    ),
    Check(
        12,
        "single primary disposition",
        "SealedCorpusCatalog.verify contrôle la somme des dispositions primaires",
        "pedago",
        (
            Mutation(
                pedago_source("artifact_placement_model.py"),
                "        if sum(self.disposition_counts.values()) != self.physical_object_count:",
                "        if False:  # MUT-H2B-12",
            ),
        ),
        "tests/test_h2b_true_mutation_targets.py::test_mut_h2b_12_single_disposition_sum_guard_detects_corruption",
        "MUT-H2B-12 single-disposition sum guard was neutralized",
    ),
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _runner(check: Check) -> tuple[Path, list[str], dict[str, str]]:
    if check.service == "pedago":
        root = PEDAGO_ROOT
        python = root / ".venv" / "bin" / "python"
        pythonpath = "."
    elif check.service == "engine":
        root = ENGINE_ROOT
        python = root / ".venv" / "bin" / "python"
        pythonpath = "src"
    else:  # pragma: no cover - CHECKS est un tuple statique méta-testé
        raise ValueError(f"unknown mutation service {check.service!r}")
    if not python.is_file():
        raise RuntimeError(f"validated Python environment is absent: {python}")
    env = dict(os.environ)
    env["PYTHONPATH"] = pythonpath
    return root, [str(python), "-m", "pytest", "-q", "-x", "-rs", check.test], env


def _run_test(check: Check) -> tuple[bool, str, int]:
    root, command, env = _runner(check)
    completed = subprocess.run(
        command,
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=900,
    )
    output = completed.stdout + completed.stderr
    skipped = " SKIPPED " in output or " skipped" in output.lower()
    return completed.returncode == 0 and not skipped, output, completed.returncode


def _apply(mutations: tuple[Mutation, ...]) -> dict[Path, bytes]:
    originals: dict[Path, bytes] = {}
    try:
        for mutation in mutations:
            raw = mutation.path.read_bytes()
            originals.setdefault(mutation.path, raw)
            old = mutation.old.encode()
            occurrences = raw.count(old)
            if occurrences != 1:
                raise RuntimeError(
                    f"MUTATION_ANCHOR_LOST path={mutation.path} occurrences={occurrences}"
                )
            mutation.path.write_bytes(raw.replace(old, mutation.new.encode()))
    except BaseException:
        _restore(originals)
        raise
    return originals


def _restore(originals: dict[Path, bytes]) -> None:
    for path, raw in originals.items():
        path.write_bytes(raw)


def _actual_failure(output: str, expected: str, returncode: int) -> str:
    for line in output.splitlines():
        if expected in line:
            return line.strip()[:500]
    return f"pytest_exit={returncode}; expected fragment not observed"


def _run_check(check: Check) -> dict[str, object]:
    baseline_green, _baseline_output, _ = _run_test(check)
    originals = _apply(check.mutations)
    mutant_output = ""
    mutant_returncode = 0
    try:
        mutant_green, mutant_output, mutant_returncode = _run_test(check)
    finally:
        _restore(originals)

    restored_bytes = all(path.read_bytes() == raw for path, raw in originals.items())
    restored_green, _restored_output, _ = _run_test(check)
    reason_seen = check.expected_failure_contains in mutant_output
    non_vacuous = (
        baseline_green
        and not mutant_green
        and reason_seen
        and restored_bytes
        and restored_green
    )
    return {
        "MUTATION_ID": f"MUT-H2B-{check.number:02d}",
        "INVARIANT": check.invariant,
        "BASELINE_GREEN": baseline_green,
        "MUTATION_APPLIED": True,
        "TARGET_TEST": check.test,
        "MUTANT_RED": not mutant_green,
        "EXPECTED_FAILURE": check.expected_failure_contains,
        "ACTUAL_FAILURE": _actual_failure(
            mutant_output, check.expected_failure_contains, mutant_returncode
        ),
        "DIRECT_CAUSE": check.protection,
        "MASKED_BY_OTHER_GUARD": False if reason_seen else None,
        "RESTORED_BYTES": restored_bytes,
        "RESTORED_GREEN": restored_green,
        "NON_VACUOUS": non_vacuous,
        "ORIGINAL_SHA256": {
            str(path.relative_to(REPO_ROOT)): _sha256(raw)
            for path, raw in sorted(originals.items())
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", type=int)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)

    selected = [
        check for check in CHECKS if args.only is None or check.number in args.only
    ]
    if not selected:
        parser.error("no mutation selected")

    all_paths = {mutation.path for check in selected for mutation in check.mutations}
    session_baseline = {path: path.read_bytes() for path in all_paths}
    results: list[dict[str, object]] = []
    try:
        for check in selected:
            print(f"MUT-H2B-{check.number:02d} {check.invariant}: START", flush=True)
            result = _run_check(check)
            results.append(result)
            print(
                f"MUT-H2B-{check.number:02d}="
                f"{'NON_VACUOUS' if result['NON_VACUOUS'] else 'FAILED'}",
                flush=True,
            )
    finally:
        _restore(session_baseline)

    temporary_mutations_restored = all(
        path.read_bytes() == raw for path, raw in session_baseline.items()
    )
    passed = sum(result["NON_VACUOUS"] is True for result in results)
    payload = {
        "evidence_kind": "H2B_TRUE_MUTATION_MATRIX",
        "executed_mutations": len(selected),
        "non_vacuous_mutations": passed,
        "H2B_TRUE_MUTATIONS_NON_VACUOUS": f"{passed}/{len(selected)}",
        "TEMPORARY_MUTATIONS_RESTORED": temporary_mutations_restored,
        "results": results,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.report.with_suffix(args.report.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        temporary.replace(args.report)
    print(f"H2B_TRUE_MUTATIONS_NON_VACUOUS={passed}/{len(selected)}")
    print(f"TEMPORARY_MUTATIONS_RESTORED={str(temporary_mutations_restored).lower()}")
    return 0 if passed == len(selected) and temporary_mutations_restored else 1


if __name__ == "__main__":
    raise SystemExit(main())
