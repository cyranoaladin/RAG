"""Invocation partagée de ``scripts/github/trusted_human_review_github.py``
(sous-processus, jamais un import direct — script racine, propriété
d'aucun service, cf. AGENTS.md) — factorisé ici car requis à l'identique
par ``scope_authority`` (LOT41A) et ``publication_attestation`` (LOT42),
qui revérifient chacune une évidence GitHub distincte mais via exactement
la même frontière.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

#: services/rag-engine/src/ingestor/ingestion_control/_trusted_review.py ->
#: racine du dépôt (même profondeur/motif que
#: ingestion_profiles/registry.py::_resolve_profiles_dir) — valable pour un
#: checkout complet du dépôt, jamais pour l'image Docker aplatie du worker
#: (``Dockerfile.ingestion-worker``, qui ne copie qu'un sous-ensemble de
#: fichiers sous ``/app``) : cette dernière fournit toujours
#: ``NEXUS_TRUSTED_REVIEW_SCRIPT`` explicitement (override prioritaire,
#: jamais de chemin absolu machine-local codé en dur — AGENTS.md).
_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[5]
_TRUSTED_REVIEW_SCRIPT_RELATIVE = Path("scripts") / "github" / "trusted_human_review_github.py"
_TRUSTED_REVIEW_SCRIPT_ENV = "NEXUS_TRUSTED_REVIEW_SCRIPT"


class TrustedReviewVerificationError(RuntimeError):
    """Échec de transport, de forme, ou verdict non-approuvé lors d'une
    revérification live GitHub — l'appelant (LOT41A ou LOT42) doit
    toujours traduire ceci en son propre type d'erreur fail-closed, jamais
    laisser cette exception générique remonter telle quelle."""


def _trusted_review_script_path(repo_root: Path | None) -> Path:
    if repo_root is None:
        env_override = os.environ.get(_TRUSTED_REVIEW_SCRIPT_ENV, "").strip()
        script = Path(env_override) if env_override else _DEFAULT_REPO_ROOT / _TRUSTED_REVIEW_SCRIPT_RELATIVE
    else:
        script = repo_root / _TRUSTED_REVIEW_SCRIPT_RELATIVE
    if not script.is_file():
        raise TrustedReviewVerificationError(
            f"trusted_human_review_github.py not found at {script} — cannot "
            "verify any GitHub evidence without this shared script"
        )
    return script


def run_check_github_review(
    *, repository: str, pull_request: int, expected_head: str, repo_root: Path | None = None
) -> dict[str, Any]:
    """Invoque ``trusted_human_review_github.py --check`` en sous-processus
    et parse son readback JSON. Lève ``TrustedReviewVerificationError`` sur
    toute erreur de transport/forme ou verdict non-approuvé — jamais un
    résultat partiel ou un ``None`` silencieux."""
    script = _trusted_review_script_path(repo_root)
    result = subprocess.run(  # noqa: S603 - argv fixe, aucune entrée shell
        [
            sys.executable,
            str(script),
            "--repository", repository,
            "--pull-request", str(pull_request),
            "--expected-head", expected_head,
            "--check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 3):
        raise TrustedReviewVerificationError(
            f"trusted_human_review_github.py exited {result.returncode} "
            f"(transport/form error), stderr: {result.stderr.strip()}"
        )
    try:
        payload: dict[str, Any] = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise TrustedReviewVerificationError(
            f"trusted_human_review_github.py produced non-JSON stdout: {exc}"
        ) from exc
    if result.returncode != 0:
        decision = payload.get("decision", {})
        raise TrustedReviewVerificationError(
            f"live GitHub review verification failed: "
            f"approved={decision.get('approved')} reason={decision.get('reason')}"
        )
    return payload


__all__ = ["TrustedReviewVerificationError", "run_check_github_review"]
