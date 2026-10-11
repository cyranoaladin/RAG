"""Émettre LOT41A-V2 seulement après vérification des onze reviews scellées.

Les octets canoniques du set sont écrits sur stdout après le gate complet.
Cette commande ne signe aucune review et n'écrit pas dans une cible distante.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from nexus_contracts.authority_artifacts import canonical_authorization_path
from nexus_contracts.authorization_set import canonical_review_binding_path
from nexus_contracts.review_binding import parse_trust_anchor
from nexus_release_chain.public_lot41a_adapter import build_public_lot41a_set

REPO_ROOT = Path(__file__).resolve().parents[2]


def _material(root: Path, relative: str) -> bytes:
    if root.is_symlink():
        raise ValueError("review material root symlink refused")
    path = root
    for component in Path(relative).parts:
        path = path / component
        if path.is_symlink():
            raise ValueError(f"review material symlink refused: {relative}")
    if not path.is_file():
        raise ValueError(f"review material missing: {relative}")
    return path.read_bytes()


def _trusted_reviewers() -> tuple[str, ...]:
    policy = json.loads(
        (REPO_ROOT / "scripts/github/trusted-reviewers.json").read_bytes()
    )
    if (
        policy.get("protocol") != "NEXUS-TRUSTED-REVIEW-V1"
        or policy.get("repository") != "cyranoaladin/RAG"
        or policy.get("base_ref") != "main"
        or not isinstance(policy.get("reviewers"), list)
        or not policy["reviewers"]
        or any(not isinstance(value, str) or not value for value in policy["reviewers"])
    ):
        raise ValueError("trusted reviewer policy invalid")
    return tuple(policy["reviewers"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor-path", type=Path, required=True)
    parser.add_argument("--anchor-sha256", required=True)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--material-root", type=Path, required=True)
    parser.add_argument("--authorization-id", action="append", required=True)
    args = parser.parse_args(argv)
    try:
        ids = tuple(args.authorization_id)
        files = {
            relative: _material(args.material_root, relative)
            for authorization_id in ids
            for relative in (
                canonical_authorization_path(authorization_id),
                canonical_review_binding_path(authorization_id),
            )
        }
        result = build_public_lot41a_set(
            anchor_path=args.anchor_path,
            anchor_sha256=args.anchor_sha256,
            release_root=args.release_root,
            authorization_ids=ids,
            release_files=files,
            trust_anchor=parse_trust_anchor(
                (
                    REPO_ROOT / "governance/trust-anchors/review-binding-v1.json"
                ).read_bytes()
            ),
            environment="production",
            now_utc=datetime.now(UTC),
            accepted_reviewers=_trusted_reviewers(),
            revocation_registry_raw=(
                REPO_ROOT / "governance/trust-anchors/authorization-revocations-v1.json"
            ).read_bytes(),
        )
    except (ValueError, OSError, KeyError) as error:
        print(f"public LOT41A-V2 refused: {error}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(result.canonical_bytes())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
