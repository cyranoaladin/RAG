"""Audit local, déterministe et dormant de la politique pilote LOT38."""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse  # noqa: E402
from collections.abc import Mapping  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import yaml  # noqa: E402

SERVICE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCOPE = SERVICE_ROOT / "configs" / "pilot_validation_scope.yml"
DEFAULT_POLICY = SERVICE_ROOT / "configs" / "pilot_validation_policy.yml"
DEFAULT_PUBLIC_CONTRACT = SERVICE_ROOT / "configs" / "pedago_interface_contract.yml"

sys.path.insert(0, str(SERVICE_ROOT))

from rag_pedago.governance.pilot_validation import (  # noqa: E402
    PilotValidationPolicy,
    PilotValidationScope,
    validate_dormant_policy,
    validate_policy_integrity,
    validate_scope_integrity,
)


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader qui refuse toute clé de mapping dupliquée, récursivement."""

    def construct_mapping(
        self,
        node: yaml.MappingNode,
        deep: bool = False,
    ) -> dict[object, object]:
        self.flatten_mapping(node)
        mapping: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as error:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable key",
                    key_node.start_mark,
                ) from error
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key ({key!r})",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audite la politique dormante de validation pilote LOT38."
    )
    parser.add_argument("--scope", type=Path, default=DEFAULT_SCOPE)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--public-contract", type=Path, default=DEFAULT_PUBLIC_CONTRACT)
    return parser.parse_args(argv)


def _resolved(path: Path) -> Path:
    return path.resolve()


def _load_unique_yaml(path: Path) -> Any:
    raw = path.read_bytes()
    return yaml.load(raw, Loader=_UniqueKeySafeLoader)


def _public_contract(payload: Any) -> Mapping[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("public contract must be a mapping")
    return payload


def _load_inputs(
    scope_path: Path,
    policy_path: Path,
    public_contract_path: Path,
) -> tuple[PilotValidationScope, PilotValidationPolicy, Mapping[str, object]]:
    scope = PilotValidationScope.model_validate(_load_unique_yaml(scope_path))
    policy = PilotValidationPolicy.model_validate(_load_unique_yaml(policy_path))
    public_contract = _public_contract(_load_unique_yaml(public_contract_path))
    return scope, policy, public_contract


def _success_report(
    scope: PilotValidationScope,
    policy: PilotValidationPolicy,
) -> str:
    lines = [
        "# Audit de la politique de validation pilote LOT38",
        "",
        "- État: DORMANT",
        f"- Scope: `{scope.scope_id}`",
    ]
    for subject in sorted(scope.subjects, key=lambda item: item.subject):
        lines.append(
            f"- Taxonomie `{subject.subject}`: `{subject.taxonomy_sha256}`"
        )
    notions_count = sum(len(subject.notions) for subject in scope.subjects)
    lines.append(f"- Couverture: {notions_count} notions")
    for capability in type(policy.capabilities).model_fields:
        lines.append(f"- Capacité `{capability}`: fermée")
    lines.append("- GO_LIVE: NO_GO")
    return "\n".join(lines) + "\n"


def _failure_report(reasons: tuple[str, ...]) -> tuple[str, str]:
    report = "# Audit de la politique de validation pilote LOT38\n\n- GO_LIVE: NO_GO\n"
    errors = "\n".join(
        f"PILOT_VALIDATION_AUDIT_ERROR: {reason}" for reason in sorted(set(reasons))
    )
    return report, errors + "\n"


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        scope_path = _resolved(args.scope)
        policy_path = _resolved(args.policy)
        public_contract_path = _resolved(args.public_contract)
        scope, policy, public_contract = _load_inputs(
            scope_path,
            policy_path,
            public_contract_path,
        )
    except (OSError, RuntimeError, TypeError, UnicodeError, ValueError, yaml.YAMLError):
        report, errors = _failure_report(("invalid_configuration_or_path",))
        print(report, end="")
        print(errors, end="", file=sys.stderr)
        return 1

    reasons = (
        *validate_scope_integrity(scope, service_root=SERVICE_ROOT),
        *validate_dormant_policy(policy),
        *validate_policy_integrity(policy, public_contract),
    )
    if reasons:
        report, errors = _failure_report(reasons)
        print(report, end="")
        print(errors, end="", file=sys.stderr)
        return 1

    print(_success_report(scope, policy), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
