"""LOT42 — garde-fou dépôt : un seul chemin vers ``RETRIEVAL_ELIGIBLE``
(remédiation GATE H1, item L).

``RETRIEVAL_ELIGIBLE`` est l'état à partir duquel une ressource devient
éligible au retrieval. LOT42 (ADR-0033 § 6) définit **un unique point
d'ancrage** autorisé à l'atteindre :
``ingestion_control.publication_attestation.attempt_retrieval_eligible_transition``,
qui exige d'abord une chaîne d'attestations valide et revérifiée en direct.

Ce test échoue si un second chemin apparaît — c'est-à-dire si un module
quelconque de ``src/`` demande une transition vers ``RETRIEVAL_ELIGIBLE``
ailleurs que dans ce point d'ancrage. Sans lui, un futur lot pourrait
câbler le pipeline jusqu'à ``REVIEWED`` puis appeler directement
``cas_transition(..., new_state=ResourceState.RETRIEVAL_ELIGIBLE)`` et
contourner silencieusement toute la vérification LOT42.

Analyse syntaxique (AST), jamais une simple recherche de chaîne : un
commentaire ou une docstring mentionnant l'état ne déclenche aucun faux
positif, et une écriture détournée (``new_state = ResourceState.
RETRIEVAL_ELIGIBLE`` puis passage par variable) reste détectée puisque
c'est bien l'attribut qui est repéré.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"

#: Seul module autorisé à demander la transition vers RETRIEVAL_ELIGIBLE.
ANCHOR_MODULE = SRC_ROOT / "ingestor" / "ingestion_control" / "publication_attestation.py"

#: Modules autorisés à *mentionner* l'état sans jamais y transitionner —
#: ``claim.py`` l'EXCLUT de l'ensemble réclamable (frozenset - {...}), ce
#: qui est l'inverse d'une transition vers cet état.
_ALLOWED_NON_TRANSITION_REFERENCES = {
    SRC_ROOT / "ingestor" / "ingestion_control" / "claim.py",
}


def _python_files() -> list[Path]:
    return sorted(p for p in SRC_ROOT.rglob("*.py") if p.is_file())


def _references_retrieval_eligible(tree: ast.AST) -> bool:
    """Vrai si le module référence ``ResourceState.RETRIEVAL_ELIGIBLE`` ou
    l'énumération importée directement."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "RETRIEVAL_ELIGIBLE":
            return True
        if isinstance(node, ast.Name) and node.id == "RETRIEVAL_ELIGIBLE":
            return True
    return False


def _transitions_to_retrieval_eligible(tree: ast.AST) -> list[int]:
    """Numéros de ligne des appels passant ``RETRIEVAL_ELIGIBLE`` comme état
    cible d'une transition (``new_state=``/``to_state=``)."""
    offending: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg not in ("new_state", "to_state"):
                continue
            value = keyword.value
            if isinstance(value, ast.Attribute) and value.attr == "RETRIEVAL_ELIGIBLE":
                offending.append(node.lineno)
            elif isinstance(value, ast.Name) and value.id == "RETRIEVAL_ELIGIBLE":
                offending.append(node.lineno)
    return offending


class TestSingleAnchorToRetrievalEligible:
    def test_anchor_module_exists(self) -> None:
        assert ANCHOR_MODULE.is_file(), (
            f"the LOT42 anchor {ANCHOR_MODULE} is missing — the guarantee this "
            "test enforces would be meaningless"
        )

    def test_anchor_actually_performs_the_transition(self) -> None:
        """Garde anti-vacuité : si l'ancre cessait de faire la transition, ce
        fichier passerait trivialement tout en ne garantissant plus rien."""
        tree = ast.parse(ANCHOR_MODULE.read_text(encoding="utf-8"), filename=str(ANCHOR_MODULE))
        assert _transitions_to_retrieval_eligible(tree), (
            "the LOT42 anchor no longer requests a transition to "
            "RETRIEVAL_ELIGIBLE — this guard would then be vacuous"
        )

    def test_no_other_module_transitions_to_retrieval_eligible(self) -> None:
        violations: dict[str, list[int]] = {}
        for path in _python_files():
            if path == ANCHOR_MODULE:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:  # pragma: no cover - src doit toujours parser
                raise AssertionError(f"cannot parse {path}: {exc}") from exc
            lines = _transitions_to_retrieval_eligible(tree)
            if lines:
                violations[str(path.relative_to(SRC_ROOT))] = lines
        assert not violations, (
            "RETRIEVAL_ELIGIBLE must only ever be reached through "
            "publication_attestation.attempt_retrieval_eligible_transition "
            "(ADR-0033 section 6). Direct transitions found: "
            f"{violations}"
        )

    def test_modules_referencing_the_state_are_a_known_closed_set(self) -> None:
        """Toute NOUVELLE mention de l'état hors ancre doit être examinée
        consciemment : ce test force la revue plutôt que de laisser une
        référence s'installer discrètement."""
        referencing = {
            path
            for path in _python_files()
            if path != ANCHOR_MODULE
            and _references_retrieval_eligible(
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            )
        }
        unexpected = referencing - _ALLOWED_NON_TRANSITION_REFERENCES
        assert not unexpected, (
            "unreviewed modules reference RETRIEVAL_ELIGIBLE: "
            f"{sorted(str(p.relative_to(SRC_ROOT)) for p in unexpected)}. "
            "If the reference is legitimate and performs no transition, add it "
            "to _ALLOWED_NON_TRANSITION_REFERENCES with a justification."
        )
