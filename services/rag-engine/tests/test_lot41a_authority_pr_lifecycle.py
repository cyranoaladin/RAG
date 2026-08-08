"""LOT41A — cycle de vie des PR d'autorité (ADR-0032 § 7, remédiation GATE H1
item H).

Exerce la fonction de décision **réelle et non modifiée** d'ADR-0025
(``scripts/github/trusted_human_review.py::evaluate_trusted_review``) sur les
neuf scénarios de cycle de vie qui décident si une autorité de longue durée
reste valide. Aucun mock de la décision : seuls les documents GitHub d'entrée
sont synthétiques.

Preuve centrale : une PR d'autorité **fusionnée ou fermée** est refusée
(``pull_request_not_open``). C'est ce qui justifie la décision d'ADR-0032 § 7
— les PR d'autorité restent ouvertes, et leur fermeture EST le mécanisme de
révocation. ADR-0025 n'est donc ni étendu ni affaibli.

Test unitaire (pas d'intégration) : aucune base, aucun réseau, aucun Docker.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
GITHUB_DIR = REPO_ROOT / "scripts" / "github"
TRUSTED_REVIEW_PY = GITHUB_DIR / "trusted_human_review.py"
TRUSTED_REVIEWERS_JSON = GITHUB_DIR / "trusted-reviewers.json"

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
OTHER_SHA = "c" * 40


def _load_trusted_review() -> Any:
    """Charge le module partagé par chemin.

    ``sys.modules[spec.name] = module`` **avant** ``exec_module`` n'est pas
    cosmétique : ``@dataclass`` résout ``cls.__module__`` via ``sys.modules``
    et lève ``AttributeError: 'NoneType' object has no attribute '__dict__'``
    si le module n'y est pas encore enregistré. Même motif que
    ``scripts/tests/test-trusted-human-review-github.py``."""
    if str(GITHUB_DIR) not in sys.path:
        sys.path.insert(0, str(GITHUB_DIR))
    spec = importlib.util.spec_from_file_location(
        "nexus_trusted_human_review_lifecycle", TRUSTED_REVIEW_PY
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def thr() -> Any:
    return _load_trusted_review()


@pytest.fixture(scope="module")
def config(thr: Any) -> Any:
    return thr.load_config(TRUSTED_REVIEWERS_JSON)


def _pull_request(
    *,
    state: str = "open",
    draft: bool = False,
    base_ref: str = "main",
    head_repository: str = "cyranoaladin/RAG",
    head_sha: str = HEAD_SHA,
) -> dict[str, Any]:
    return {
        "number": 1,
        "state": state,
        "draft": draft,
        "base": {"ref": base_ref, "sha": BASE_SHA},
        "head": {"sha": head_sha, "repo": {"full_name": head_repository}},
        "user": {"login": "cyranoaladin"},
    }


def _approval(
    thr: Any,
    config: Any,
    pull_request: dict[str, Any],
    *,
    reviewer: str = "abenrhouma",
    body: str | None = None,
    commit_id: str | None = None,
    state: str = "APPROVED",
) -> dict[str, Any]:
    challenge = thr.build_expected_challenges(pull_request, config)[reviewer]
    return {
        "id": 10,
        "state": state,
        "body": challenge if body is None else body,
        "commit_id": commit_id or pull_request["head"]["sha"],
        "submitted_at": "2026-08-08T10:00:00Z",
        "user": {"login": reviewer},
    }


WRITE_PERMS = {"abenrhouma": {"permission": "write", "role_name": "write"}}
READ_PERMS = {"abenrhouma": {"permission": "read", "role_name": "read"}}


def _decide(thr: Any, config: Any, pull_request: Any, reviews: Any, permissions: Any) -> Any:
    return thr.evaluate_trusted_review(
        pull_request=pull_request,
        reviews=reviews,
        permissions=permissions,
        config=config,
        reviews_complete=True,
    )


class TestAuthorityPullRequestStaysOpen:
    """ADR-0032 § 7 : une autorité n'est valide que tant que sa PR est
    ouverte et approuvée au head exact."""

    def test_open_pr_with_approval_at_exact_head_is_the_only_valid_state(
        self, thr: Any, config: Any
    ) -> None:
        pr = _pull_request()
        decision = _decide(thr, config, pr, [_approval(thr, config, pr)], WRITE_PERMS)
        assert decision.approved is True
        assert decision.reason == "approved"
        assert decision.head_sha == HEAD_SHA

    def test_merged_or_closed_authority_pr_is_denied(self, thr: Any, config: Any) -> None:
        """Preuve centrale de la décision ADR-0032 § 7 : fusionner une PR
        d'autorité la rend inopérante. La fermeture est donc un mécanisme de
        révocation réel, et non un effet de bord non géré."""
        pr = _pull_request(state="closed")
        decision = _decide(thr, config, pr, [_approval(thr, config, pr)], WRITE_PERMS)
        assert decision.approved is False
        assert decision.reason == "pull_request_not_open"

    def test_dismissed_review_revokes_the_authority(self, thr: Any, config: Any) -> None:
        pr = _pull_request()
        reviews = [
            _approval(thr, config, pr),
            {
                "id": 11,
                "state": "DISMISSED",
                "body": "",
                "commit_id": HEAD_SHA,
                "submitted_at": "2026-08-08T11:00:00Z",
                "user": {"login": "abenrhouma"},
            },
        ]
        decision = _decide(thr, config, pr, reviews, WRITE_PERMS)
        assert decision.approved is False
        assert decision.reason == "approval_revoked"

    def test_approval_on_a_different_head_is_denied(self, thr: Any, config: Any) -> None:
        """Un push sur la branche d'autorité (y compris ``--force``) déplace le
        head : l'approbation antérieure ne vaut plus."""
        pr = _pull_request()
        decision = _decide(
            thr, config, pr, [_approval(thr, config, pr, commit_id=OTHER_SHA)], WRITE_PERMS
        )
        assert decision.approved is False
        assert decision.reason == "current_head_approval_missing"

    def test_wrong_base_ref_is_denied(self, thr: Any, config: Any) -> None:
        pr = _pull_request(base_ref="develop")
        decision = _decide(thr, config, pr, [_approval(thr, config, pr)], WRITE_PERMS)
        assert decision.approved is False
        assert decision.reason == "base_ref_mismatch"

    def test_wrong_challenge_body_is_denied(self, thr: Any, config: Any) -> None:
        pr = _pull_request()
        decision = _decide(
            thr, config, pr, [_approval(thr, config, pr, body="not-a-challenge")], WRITE_PERMS
        )
        assert decision.approved is False
        assert decision.reason == "current_head_approval_missing"

    def test_reviewer_without_write_permission_is_denied(self, thr: Any, config: Any) -> None:
        pr = _pull_request()
        decision = _decide(thr, config, pr, [_approval(thr, config, pr)], READ_PERMS)
        assert decision.approved is False
        assert decision.reason == "reviewer_permission_insufficient"

    def test_head_on_a_foreign_repository_is_denied(self, thr: Any, config: Any) -> None:
        pr = _pull_request(head_repository="attacker/RAG")
        decision = _decide(thr, config, pr, [_approval(thr, config, pr)], WRITE_PERMS)
        assert decision.approved is False
        assert decision.reason == "head_repository_mismatch"

    def test_draft_authority_pr_is_denied(self, thr: Any, config: Any) -> None:
        pr = _pull_request(draft=True)
        decision = _decide(thr, config, pr, [_approval(thr, config, pr)], WRITE_PERMS)
        assert decision.approved is False
        assert decision.reason == "pull_request_is_draft"

    def test_unknown_reviewer_cannot_authorize(self, thr: Any, config: Any) -> None:
        """Le contrôle d'**identité** du relecteur, isolé de tout autre contrôle
        (remédiation GATE H1, FINDING_4).

        La version antérieure de ce test n'accordait la permission qu'à
        l'identité pirate. Le relecteur de confiance n'ayant alors aucune
        entrée de permission, la décision était refusée par
        ``reviewer_permission_insufficient`` — c'est-à-dire par le contrôle de
        permission, **jamais** par le contrôle d'identité. Neutraliser
        ``review["reviewer"] == reviewer`` laissait donc le test vert : il ne
        prouvait pas ce qu'il prétendait prouver.

        Le scénario est ici construit pour qu'**aucune autre cause de refus ne
        soit disponible** :

        - le relecteur de confiance (``abenrhouma``) a bien la permission
          ``write`` requise — le contrôle de permission est donc satisfait et
          ne peut pas expliquer le refus ;
        - la review est ``APPROVED``, au head exact, et porte le challenge
          canonique **valide pour le relecteur de confiance** ;
        - seule l'identité de l'auteur de la review diffère.

        Le seul contrôle capable de refuser est donc l'égalité d'identité. Si
        elle est retirée, la review pirate est comptée comme celle du
        relecteur de confiance et la décision devient ``approved`` — ce test
        passe alors au rouge, comme il se doit."""
        pr = _pull_request()
        # Challenge et commit_id valides POUR le relecteur de confiance…
        rogue = _approval(thr, config, pr, reviewer="abenrhouma")
        # …mais soumis par une autre identité.
        rogue["user"] = {"login": "mallory"}

        decision = _decide(thr, config, pr, [rogue], WRITE_PERMS)

        assert decision.approved is False
        # Raison canonique exacte : le relecteur de confiance a la permission,
        # mais aucune approbation ne lui appartient au head courant. Jamais
        # ``reviewer_permission_insufficient``, qui signalerait que c'est le
        # contrôle de permission — et non l'identité — qui a refusé.
        assert decision.reason == "current_head_approval_missing", (
            f"expected the identity control to reject, got reason="
            f"{decision.reason!r}"
        )
        assert decision.reviewer is None
        assert decision.challenge is None

    def test_the_identity_control_is_the_only_thing_rejecting_the_rogue_review(
        self, thr: Any, config: Any
    ) -> None:
        """Garde anti-masquage explicite (FINDING_4).

        Vérifie que, dans le scénario ci-dessus, le contrôle de permission est
        réellement satisfait : la même review, soumise par le relecteur de
        confiance lui-même, est acceptée. Si ce contrôle ne passait pas, le
        refus observé plus haut serait attribuable à la permission et le test
        d'identité redeviendrait vacant."""
        pr = _pull_request()
        legitimate = _approval(thr, config, pr, reviewer="abenrhouma")
        decision = _decide(thr, config, pr, [legitimate], WRITE_PERMS)
        assert decision.approved is True, (
            "the permission control must be satisfied in this fixture, otherwise "
            "the identity test above would be proving the permission control instead"
        )
        assert decision.reason == "approved"


class TestAdr0025IsNotWeakened:
    def test_only_open_state_is_ever_accepted(self, thr: Any, config: Any) -> None:
        """Balaye tous les états GitHub non-``open`` : aucun ne doit produire
        une autorité valide. Verrouille la décision d'ADR-0032 § 7 contre une
        future « extension » qui accepterait une PR fusionnée."""
        for state in ("closed", "merged", "locked"):
            pr = _pull_request(state=state)
            decision = _decide(thr, config, pr, [_approval(thr, config, pr)], WRITE_PERMS)
            assert decision.approved is False, f"state={state} must never authorize"
            assert decision.reason == "pull_request_not_open"
