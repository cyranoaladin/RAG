"""Frontière GitHub fake pour les tests d'adversité LOT41A/LOT42.

N'importe jamais ``trusted_human_review_github.py`` directement : les tests
exercent la VRAIE chaîne (``ingestor.ingestion_control._trusted_review`` ->
sous-processus -> ``scripts/github/trusted_human_review_github.py`` (réel,
non modifié) -> ``gh api`` (réel binaire, remplacé sur PATH par ce module).
Seule la frontière réseau GitHub elle-même (``gh``) est simulée — tout le
reste de la chaîne de vérification live est le code réel.

Usage : ``fake_gh_bin_dir(tmp_path)`` écrit un exécutable ``gh`` sur PATH
qui lit ``scenario.json`` (mutable en place par le test — chaque appel
relit le fichier, permettant de simuler une révocation/un changement de
HEAD entre deux vérifications live) et sert les trois endpoints consommés
par ``trusted_human_review_github`` : PR, reviews, permissions. Le
scénario est indexé par numéro de PR (``write_scenario`` fusionne, jamais
n'écrase les autres PR déjà enregistrées) — plusieurs autorisations/
attestations distinctes, chacune sur sa propre PR, coexistent dans le même
répertoire de scénario au sein d'un même test."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

REPOSITORY = "cyranoaladin/RAG"
BASE_REF = "main"
REVIEWER = "abenrhouma"

_FAKE_GH_SCRIPT = '''#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

SCENARIO_PATH = Path(__file__).with_name("scenario.json")


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] != "api":
        print("unsupported gh invocation", file=sys.stderr)
        return 1
    endpoint = sys.argv[2]
    scenario = json.loads(SCENARIO_PATH.read_text(encoding="utf-8"))
    prs = scenario["prs"]

    pr_match = re.fullmatch(r"repos/([^/]+/[^/]+)/pulls/(\\d+)", endpoint)
    reviews_match = re.fullmatch(
        r"repos/([^/]+/[^/]+)/pulls/(\\d+)/reviews\\?per_page=(\\d+)&page=(\\d+)", endpoint
    )
    perm_match = re.fullmatch(
        r"repos/([^/]+/[^/]+)/collaborators/([^/]+)/permission", endpoint
    )

    if pr_match:
        pr_number = pr_match.group(2)
        if pr_number not in prs:
            print(json.dumps({"message": "Not Found"}))
            return 1
        print(json.dumps(prs[pr_number]["pull_request"]))
        return 0
    if reviews_match:
        pr_number = reviews_match.group(2)
        page = int(reviews_match.group(4))
        reviews = prs.get(pr_number, {}).get("reviews", []) if page == 1 else []
        print(json.dumps(reviews))
        return 0
    if perm_match:
        reviewer = perm_match.group(2)
        # Les permissions ne sont pas indexées par PR (même reviewer,
        # mêmes droits, quelle que soit la PR évaluée) — fusionnées dans
        # scenario["permissions"], jamais par-PR.
        permissions = scenario.get("permissions", {})
        if reviewer not in permissions:
            print(json.dumps({"message": "Not Found"}))
            return 1
        print(json.dumps(permissions[reviewer]))
        return 0

    print(f"FAKE_GH_UNHANDLED_ENDPOINT: {endpoint}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


def approved_pull_request(
    *, number: int, head_sha: str, base_sha: str, author: str = "cyranoaladin"
) -> dict[str, Any]:
    return {
        "number": number,
        "state": "open",
        "draft": False,
        "base": {"ref": BASE_REF, "sha": base_sha},
        "head": {"sha": head_sha, "repo": {"full_name": REPOSITORY}},
        "user": {"login": author},
    }


def write_protocol_challenge(
    *, pull_request: dict[str, Any], reviewer: str = REVIEWER
) -> str:
    """Calcule le challenge attendu pour ``reviewer`` — utilise le module
    réel ``trusted_human_review`` (racine du dépôt) pour ne jamais
    dupliquer la formule de hachage dans les tests."""
    import sys

    repo_root = Path(__file__).resolve().parents[4]
    github_dir = repo_root / "scripts" / "github"
    if str(github_dir) not in sys.path:
        sys.path.insert(0, str(github_dir))
    from trusted_human_review import TrustedReviewerConfig, build_expected_challenges

    config = TrustedReviewerConfig(
        protocol="NEXUS-TRUSTED-REVIEW-V1",
        repository=REPOSITORY,
        base_ref=BASE_REF,
        reviewers=(reviewer,),
    )
    return build_expected_challenges(pull_request, config)[reviewer]


def approved_review(
    *, review_id: int, pull_request: dict[str, Any], reviewer: str = REVIEWER,
    submitted_at: str = "2026-08-07T10:00:00Z", state: str = "APPROVED",
) -> dict[str, Any]:
    challenge = write_protocol_challenge(pull_request=pull_request, reviewer=reviewer)
    return {
        "id": review_id,
        "state": state,
        "body": challenge,
        "commit_id": pull_request["head"]["sha"],
        "submitted_at": submitted_at,
        "user": {"login": reviewer},
    }


def write_permission(*, permission: str = "write", role_name: str = "write") -> dict[str, Any]:
    return {"permission": permission, "role_name": role_name}


def write_scenario(
    scenario_dir: Path, *, pull_request: dict[str, Any], reviews: list[dict[str, Any]],
    permissions: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Fusionne cette PR dans ``scenario.json`` — n'écrase jamais les
    autres PR déjà écrites par un appel précédent (même répertoire de
    scénario réutilisé pour plusieurs autorisations/attestations
    distinctes au sein d'un même test)."""
    scenario_path = scenario_dir / "scenario.json"
    if scenario_path.is_file():
        scenario = json.loads(scenario_path.read_text(encoding="utf-8"))
    else:
        scenario = {"prs": {}, "permissions": {}}

    scenario["prs"][str(pull_request["number"])] = {
        "pull_request": pull_request,
        "reviews": reviews,
    }
    scenario["permissions"].update(
        permissions if permissions is not None else {REVIEWER: write_permission()}
    )
    scenario_path.write_text(json.dumps(scenario), encoding="utf-8")


def fake_gh_bin_dir(tmp_path: Path) -> Path:
    """Écrit l'exécutable ``gh`` fake dans ``tmp_path/bin`` et renvoie ce
    répertoire — l'appelant doit le préfixer à ``PATH``."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh_path = bin_dir / "gh"
    gh_path.write_text(_FAKE_GH_SCRIPT, encoding="utf-8")
    gh_path.chmod(gh_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def prepend_path(bin_dir: Path) -> str:
    return f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


__all__ = [
    "BASE_REF",
    "REPOSITORY",
    "REVIEWER",
    "approved_pull_request",
    "approved_review",
    "fake_gh_bin_dir",
    "prepend_path",
    "write_permission",
    "write_protocol_challenge",
    "write_scenario",
]
