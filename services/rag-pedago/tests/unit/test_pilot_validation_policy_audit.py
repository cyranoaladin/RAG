from __future__ import annotations

import ast
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SERVICE_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = SERVICE_ROOT / "scripts" / "pilot_validation_policy_audit.py"
SCOPE = SERVICE_ROOT / "configs" / "pilot_validation_scope.yml"
POLICY = SERVICE_ROOT / "configs" / "pilot_validation_policy.yml"
PUBLIC_CONTRACT = SERVICE_ROOT / "configs" / "pedago_interface_contract.yml"
MAKEFILE = SERVICE_ROOT / "Makefile"

EXPECTED_OUTPUT = """# Audit de la politique de validation pilote LOT38

- État: DORMANT
- Scope: `libre_terminale_maths_nsi_real_v1`
- Taxonomie `maths`: `4a91661a381751573425b30667c53fc8f44df04fa4e0f7a0c4e71f0ec64005a6`
- Taxonomie `nsi`: `b93a3e4017e99f1647861abac46b5f3136ee8611e7142d4fca2a33a5929eb05f`
- Couverture: 39 notions
- Capacité `validation_real_documents_allowed`: fermée
- Capacité `validation_pipeline_allowed`: fermée
- Capacité `validation_answer_generation_allowed`: fermée
- Capacité `validation_openrouter_allowed`: fermée
- GO_LIVE: NO_GO
"""


def _run_cli(
    *arguments: str,
    cwd: Path = SERVICE_ROOT,
    optimized: bool = False,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend((str(SCRIPT), *arguments))
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        check=False,
        text=True,
    )


def _load_mapping(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_bytes())
    assert isinstance(payload, dict)
    return payload


def _write_yaml(path: Path, payload: object) -> Path:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _tree_snapshot(root: Path) -> dict[str, tuple[str, str]]:
    snapshot: dict[str, tuple[str, str]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot[relative] = ("symlink", str(path.readlink()))
        elif path.is_dir():
            snapshot[relative] = ("directory", "")
        else:
            snapshot[relative] = (
                "file",
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
    return snapshot


def _git_status() -> str:
    return subprocess.check_output(
        ["git", "status", "--short", "--branch", "--untracked-files=all"],
        cwd=SERVICE_ROOT,
        text=True,
    )


def _copy_isolated_service(tmp_path: Path) -> Path:
    isolated = tmp_path / "rag-pedago"
    (isolated / "scripts").mkdir(parents=True)
    (isolated / "configs").mkdir()
    (isolated / "taxonomy" / "maths").mkdir(parents=True)
    (isolated / "taxonomy" / "nsi").mkdir(parents=True)
    (isolated / "rag_pedago" / "governance").mkdir(parents=True)

    for source, destination in (
        (SCRIPT, isolated / "scripts" / SCRIPT.name),
        (SCOPE, isolated / "configs" / SCOPE.name),
        (POLICY, isolated / "configs" / POLICY.name),
        (PUBLIC_CONTRACT, isolated / "configs" / PUBLIC_CONTRACT.name),
        (
            SERVICE_ROOT / "taxonomy" / "maths" / "terminale_gen_specialite.yml",
            isolated / "taxonomy" / "maths" / "terminale_gen_specialite.yml",
        ),
        (
            SERVICE_ROOT / "taxonomy" / "nsi" / "terminale.yml",
            isolated / "taxonomy" / "nsi" / "terminale.yml",
        ),
        (
            SERVICE_ROOT / "rag_pedago" / "__init__.py",
            isolated / "rag_pedago" / "__init__.py",
        ),
        (
            SERVICE_ROOT / "rag_pedago" / "governance" / "__init__.py",
            isolated / "rag_pedago" / "governance" / "__init__.py",
        ),
        (
            SERVICE_ROOT / "rag_pedago" / "governance" / "pilot_validation.py",
            isolated / "rag_pedago" / "governance" / "pilot_validation.py",
        ),
    ):
        shutil.copy2(source, destination)
    return isolated


def _copy_uncached_pyyaml(tmp_path: Path) -> Path:
    yaml_package = Path(yaml.__file__).resolve().parent
    third_party = tmp_path / "third-party"
    shutil.copytree(
        yaml_package,
        third_party / "yaml",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    return third_party


class TestCanonicalAudit:
    def test_cli_without_arguments_is_byte_stable_and_dormant(self, tmp_path: Path) -> None:
        first = _run_cli()
        second = _run_cli(cwd=tmp_path)

        assert first.returncode == 0
        assert first.stdout == EXPECTED_OUTPUT
        assert first.stderr == ""
        assert second.returncode == 0
        assert second.stdout == first.stdout
        assert second.stderr == ""

    def test_makefile_exposes_the_planned_audit_target(self) -> None:
        makefile = MAKEFILE.read_text(encoding="utf-8")

        assert "pilot-validation-policy-audit" in makefile.split(".PHONY:", 1)[1].splitlines()[0]
        assert (
            "pilot-validation-policy-audit:\n"
            "\t$(PY) scripts/pilot_validation_policy_audit.py\n"
        ) in makefile

    def test_explicit_paths_load_the_same_canonical_documents(self, tmp_path: Path) -> None:
        scope = tmp_path / "scope.yml"
        policy = tmp_path / "policy.yml"
        public_contract = tmp_path / "contract.yml"
        scope.write_bytes(SCOPE.read_bytes())
        policy.write_bytes(POLICY.read_bytes())
        public_contract.write_bytes(PUBLIC_CONTRACT.read_bytes())

        result = _run_cli(
            "--scope",
            str(scope),
            "--policy",
            str(policy),
            "--public-contract",
            str(public_contract),
        )

        assert result.returncode == 0
        assert result.stdout == EXPECTED_OUTPUT
        assert result.stderr == ""

    @pytest.mark.parametrize(
        "option",
        ["--scope", "--policy", "--public-contract"],
    )
    def test_invalid_input_fails_closed_without_traceback(
        self,
        tmp_path: Path,
        option: str,
    ) -> None:
        invalid = tmp_path / "invalid.yml"
        invalid.write_text("[yaml: invalid", encoding="utf-8")

        result = _run_cli(option, str(invalid))

        assert result.returncode != 0
        assert "PILOT_VALIDATION_AUDIT_ERROR:" in result.stderr
        assert "GO_LIVE: NO_GO" in result.stdout
        assert "Traceback" not in result.stdout + result.stderr

    @pytest.mark.parametrize(
        ("option", "payload"),
        [
            ("--scope", []),
            ("--scope", {}),
            ("--policy", []),
            ("--policy", {}),
            ("--public-contract", []),
            ("--public-contract", {}),
        ],
        ids=(
            "scope-non-mapping",
            "scope-invalid-schema",
            "policy-non-mapping",
            "policy-invalid-schema",
            "public-contract-non-mapping",
            "public-contract-invalid-schema",
        ),
    )
    def test_non_mapping_or_invalid_schema_fails_closed(
        self,
        tmp_path: Path,
        option: str,
        payload: object,
    ) -> None:
        invalid = _write_yaml(tmp_path / "invalid.yml", payload)

        result = _run_cli(option, str(invalid))

        assert result.returncode != 0
        assert "PILOT_VALIDATION_AUDIT_ERROR:" in result.stderr
        assert "GO_LIVE: NO_GO" in result.stdout
        assert "Traceback" not in result.stdout + result.stderr

    @pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
    @pytest.mark.parametrize(
        ("option", "source", "canonical_line", "duplicated_lines"),
        [
            (
                "--scope",
                SCOPE,
                "scope_id: libre_terminale_maths_nsi_real_v1",
                "scope_id: intrus\nscope_id: libre_terminale_maths_nsi_real_v1",
            ),
            (
                "--policy",
                POLICY,
                "  validation_pipeline_allowed: false",
                "  validation_pipeline_allowed: true\n"
                "  validation_pipeline_allowed: false",
            ),
            (
                "--public-contract",
                PUBLIC_CONTRACT,
                "ui_runtime_allowed: false",
                "ui_runtime_allowed: true\nui_runtime_allowed: false",
            ),
        ],
        ids=["scope", "policy", "public-contract"],
    )
    def test_contradictory_duplicate_yaml_key_fails_closed(
        self,
        tmp_path: Path,
        optimized: bool,
        option: str,
        source: Path,
        canonical_line: str,
        duplicated_lines: str,
    ) -> None:
        canonical = source.read_text(encoding="utf-8")
        assert canonical.count(canonical_line) == 1
        duplicate = tmp_path / source.name
        duplicate.write_text(
            canonical.replace(canonical_line, duplicated_lines, 1),
            encoding="utf-8",
        )

        result = _run_cli(option, str(duplicate), optimized=optimized)

        assert result.returncode != 0
        assert result.stdout.endswith("- GO_LIVE: NO_GO\n")
        assert result.stderr == (
            "PILOT_VALIDATION_AUDIT_ERROR: invalid_configuration_or_path\n"
        )
        assert "Traceback" not in result.stdout + result.stderr

    def test_declared_taxonomy_digest_derivation_is_refuted(self, tmp_path: Path) -> None:
        payload = _load_mapping(SCOPE)
        subjects = payload["subjects"]
        assert isinstance(subjects, list)
        maths = subjects[0]
        assert isinstance(maths, dict)
        maths["taxonomy_sha256"] = "0" * 64
        derived_scope = _write_yaml(tmp_path / "scope.yml", payload)

        result = _run_cli("--scope", str(derived_scope))

        assert result.returncode != 0
        assert "scope.taxonomy_sha256_mismatch:maths" in result.stderr
        assert "GO_LIVE: NO_GO" in result.stdout
        assert "Traceback" not in result.stdout + result.stderr

    def test_open_public_lock_is_refuted(self, tmp_path: Path) -> None:
        payload = _load_mapping(PUBLIC_CONTRACT)
        payload["real_documents_allowed"] = True
        contract = _write_yaml(tmp_path / "contract.yml", payload)

        result = _run_cli("--public-contract", str(contract))

        assert result.returncode != 0
        assert "policy.public_lock_mismatch:real_documents_allowed" in result.stderr
        assert "GO_LIVE: NO_GO" in result.stdout
        assert "Traceback" not in result.stdout + result.stderr

    def test_open_validation_capability_is_refuted(self, tmp_path: Path) -> None:
        payload = _load_mapping(POLICY)
        capabilities = payload["capabilities"]
        assert isinstance(capabilities, dict)
        capabilities["validation_pipeline_allowed"] = True
        policy = _write_yaml(tmp_path / "policy.yml", payload)

        result = _run_cli("--policy", str(policy))

        assert result.returncode != 0
        assert (
            "policy.capability_not_dormant:validation_pipeline_allowed"
            in result.stderr
        )
        assert "GO_LIVE: NO_GO" in result.stdout
        assert "Traceback" not in result.stdout + result.stderr


class TestAuditSideEffects:
    def test_script_has_no_environment_network_process_database_or_write_api(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_roots = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported_roots.update(
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        referenced_attributes = {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

        assert imported_roots.isdisjoint(
            {
                "os",
                "socket",
                "subprocess",
                "requests",
                "httpx",
                "urllib",
                "psycopg",
                "sqlalchemy",
            }
        )
        assert referenced_attributes.isdisjoint(
            {
                "environ",
                "getenv",
                "write_bytes",
                "write_text",
                "touch",
                "mkdir",
                "unlink",
                "rename",
                "replace",
                "rmdir",
            }
        )
        assert called_names.isdisjoint(
            {"open", "exec", "eval", "compile", "getenv", "putenv"}
        )
        assert not any(isinstance(node, ast.Assert) for node in ast.walk(tree))
        for forbidden_authority in (
            "load_authorization",
            "load_approval_evidence",
            "evaluate_authorization",
            "ValidationAuthorization",
            "pilot_validation_authorization.yml",
        ):
            assert forbidden_authority not in source

    def test_cli_exposes_no_activation_or_authorization_option(self) -> None:
        result = _run_cli("--authorization", "authorization.yml")

        assert result.returncode == 2
        assert result.stdout == ""
        assert "unrecognized arguments: --authorization authorization.yml" in result.stderr
        assert "Traceback" not in result.stderr

    def test_cli_does_not_change_git_status_or_data_tree(self, tmp_path: Path) -> None:
        data_root = SERVICE_ROOT / "data"
        status_before = _git_status()
        data_before = _tree_snapshot(data_root)

        valid = _run_cli()
        invalid = _run_cli("--scope", str(tmp_path / "absent.yml"))

        assert valid.returncode == 0
        assert invalid.returncode != 0
        assert _git_status() == status_before
        assert _tree_snapshot(data_root) == data_before

    def test_cli_is_fail_closed_with_python_optimization(self, tmp_path: Path) -> None:
        canonical = _run_cli(optimized=True)
        invalid_contract = _write_yaml(tmp_path / "contract.yml", ["not", "a", "mapping"])
        invalid = _run_cli(
            "--public-contract",
            str(invalid_contract),
            optimized=True,
        )

        assert canonical.returncode == 0
        assert canonical.stdout == EXPECTED_OUTPUT
        assert canonical.stderr == ""
        assert invalid.returncode != 0
        assert "PILOT_VALIDATION_AUDIT_ERROR:" in invalid.stderr
        assert "GO_LIVE: NO_GO" in invalid.stdout
        assert "Traceback" not in invalid.stdout + invalid.stderr

    def test_relative_overrides_are_resolved_from_the_explicit_working_directory(
        self,
        tmp_path: Path,
    ) -> None:
        scope = tmp_path / "scope.yml"
        policy = tmp_path / "policy.yml"
        public_contract = tmp_path / "contract.yml"
        scope.write_bytes(SCOPE.read_bytes())
        policy.write_bytes(POLICY.read_bytes())
        public_contract.write_bytes(PUBLIC_CONTRACT.read_bytes())

        result = _run_cli(
            "--scope",
            scope.name,
            "--policy",
            policy.name,
            "--public-contract",
            public_contract.name,
            cwd=tmp_path,
        )

        assert result.returncode == 0
        assert result.stdout == EXPECTED_OUTPUT
        assert result.stderr == ""

    @pytest.mark.parametrize(
        ("option", "invalid_kind"),
        [
            ("--scope", "directory"),
            ("--policy", "symlink_loop"),
            ("--public-contract", "invalid_unicode"),
        ],
    )
    def test_access_unicode_and_path_errors_have_no_traceback(
        self,
        tmp_path: Path,
        option: str,
        invalid_kind: str,
    ) -> None:
        invalid = tmp_path / "invalid"
        if invalid_kind == "directory":
            invalid.mkdir()
        elif invalid_kind == "symlink_loop":
            invalid.symlink_to(invalid.name)
        else:
            invalid.write_bytes(b"\x80invalid-utf8")

        result = _run_cli(option, str(invalid), optimized=True)

        assert result.returncode != 0
        assert result.stdout.endswith("- GO_LIVE: NO_GO\n")
        assert result.stderr == (
            "PILOT_VALIDATION_AUDIT_ERROR: invalid_configuration_or_path\n"
        )
        assert "Traceback" not in result.stdout + result.stderr

    def test_cli_creates_no_file_even_from_an_uncached_service_copy(
        self,
        tmp_path: Path,
    ) -> None:
        isolated = _copy_isolated_service(tmp_path)
        before = _tree_snapshot(isolated)
        secret = "lot38-secret-canary-must-never-be-read-or-printed"
        result = subprocess.run(
            [sys.executable, str(isolated / "scripts" / SCRIPT.name)],
            cwd=tmp_path,
            env={"LOT38_SECRET_CANARY": secret},
            capture_output=True,
            check=False,
            text=True,
        )

        assert result.returncode == 0
        assert result.stdout == EXPECTED_OUTPUT
        assert result.stderr == ""
        assert secret not in result.stdout + result.stderr
        assert _tree_snapshot(isolated) == before

    def test_cli_creates_no_bytecode_in_an_uncached_third_party_package(
        self,
        tmp_path: Path,
    ) -> None:
        third_party = _copy_uncached_pyyaml(tmp_path)
        before = _tree_snapshot(third_party)

        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=tmp_path,
            env={"PYTHONPATH": str(third_party)},
            capture_output=True,
            check=False,
            text=True,
        )

        assert result.returncode == 0
        assert result.stdout == EXPECTED_OUTPUT
        assert result.stderr == ""
        assert _tree_snapshot(third_party) == before

    def test_modified_taxonomy_bytes_are_refuted_without_side_effect(
        self,
        tmp_path: Path,
    ) -> None:
        isolated = _copy_isolated_service(tmp_path)
        taxonomy = isolated / "taxonomy" / "maths" / "terminale_gen_specialite.yml"
        taxonomy.write_bytes(taxonomy.read_bytes() + b"\n# derived taxonomy\n")
        before = _tree_snapshot(isolated)

        result = subprocess.run(
            [sys.executable, str(isolated / "scripts" / SCRIPT.name)],
            cwd=tmp_path,
            env={},
            capture_output=True,
            check=False,
            text=True,
        )

        assert result.returncode != 0
        assert result.stdout.endswith("- GO_LIVE: NO_GO\n")
        assert result.stderr == (
            "PILOT_VALIDATION_AUDIT_ERROR: scope.taxonomy_sha256_mismatch:maths\n"
        )
        assert "Traceback" not in result.stdout + result.stderr
        assert _tree_snapshot(isolated) == before
