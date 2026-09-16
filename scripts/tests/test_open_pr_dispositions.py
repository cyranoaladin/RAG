"""Épreuves des dispositions des PR ouvertes et de leur conformité gouvernée.

Garantit le comportement fail-closed :
- Aucune PR ne peut être débloquée sans disposition prouvée ;
- observed_at_main_sha ne peut pas être obsolète ou inventé ;
- La PR #134 ne peut en aucun cas être recommandée à la fusion ;
- La PR #98 ne peut être classée CLOSE_SUPERSEDED que sur preuve complète ;
- Le gate calcule exactement le nombre et la liste des PRs bloquantes.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import check_go_live_readiness as readiness  # noqa: E402
import reconcile_open_prs as reconciler  # noqa: E402

DISPOSITIONS_PATH = RACINE / "docs/reports/go_live/open_pr_dispositions.json"
MARKDOWN_PATH = RACINE / "docs/reports/go_live/OPEN_PR_DISPOSITIONS.md"


@pytest.fixture(scope="module")
def dispositions_doc() -> dict:
    return json.loads(DISPOSITIONS_PATH.read_text(encoding="utf-8"))


def test_fichier_dispositions_existe_et_bien_forme(dispositions_doc):
    assert dispositions_doc["kind"] == "NEXUS-OPEN-PR-DISPOSITIONS-V1"
    assert "observed_at_main_sha" in dispositions_doc
    assert "dispositions" in dispositions_doc
    assert "summary" in dispositions_doc
    assert dispositions_doc["summary"]["total_open_prs"] == len(dispositions_doc["dispositions"])


def test_observed_at_main_sha_est_commit_valide_et_conforme(dispositions_doc):
    sha = dispositions_doc["observed_at_main_sha"]
    assert re.fullmatch(r"[0-9a-f]{40}", sha), f"sha invalide : {sha}"

    # Vérifier que ce commit existe bien dans l'historique du dépôt
    result = subprocess.run(
        ["git", "cat-file", "-t", sha],
        cwd=str(RACINE),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"observed_at_main_sha non trouvé dans git : {sha}"
    assert result.stdout.strip() == "commit"


def test_impossible_de_laisser_observed_at_main_sha_obsolete():
    """Un SHA invalide ou mal formé doit être rejeté par le constructeur."""
    with pytest.raises(ValueError, match="main_sha invalide"):
        reconciler.construire_dispositions("")
    with pytest.raises(ValueError, match="main_sha invalide"):
        reconciler.construire_dispositions("court")


def test_impossible_de_recommander_ou_merger_134(dispositions_doc):
    """La PR #134 porte une règle impérative NO_MERGE : elle ne peut jamais être MERGE_CANDIDATE."""
    pr134 = dispositions_doc["dispositions"].get("134")
    assert pr134 is not None
    assert pr134["disposition"] != "MERGE_CANDIDATE", (
        "Violation critique de gouvernance : la PR #134 a été classée MERGE_CANDIDATE "
        "alors que son autorité interdit formellement toute fusion."
    )
    assert pr134["disposition"] == "KEEP_OPEN_GOVERNED_NO_MERGE"
    assert "NE PAS LA FUSIONNER" in pr134["reason"]
    assert "MUST_REMAIN_OPEN_NO_MERGE" in pr134["measured"]


def test_impossible_de_classer_98_superseded_sans_preuve_structuree(dispositions_doc):
    """PR #98 ne peut être CLOSE_SUPERSEDED que si ses contenus sont prouvés CANDIDATE et repris."""
    pr98 = dispositions_doc["dispositions"].get("98")
    assert pr98 is not None
    assert pr98["disposition"] == "CLOSE_SUPERSEDED"
    # Doit prouver qu'il s'agit d'un LOT41A-V2 / ScopeAuthorizationArtifactV2
    assert "LOT41A-V2" in pr98["measured"]
    assert "ScopeAuthorizationArtifactV2" in pr98["measured"]
    # Doit prouver l'expiration
    assert "EXPIRED" in pr98["measured"]
    # Doit prouver que les 5 contenus sont dans la servability matrix sans blocage
    assert "5/5 (CANDIDATE)" in pr98["measured"]
    # Doit prouver le remplacement par #134
    assert "SUPERSEDED_BY_PR134=true" in pr98["measured"]


def test_impossible_de_fermer_une_pr_bloquante_sans_disposition_prouvee():
    """Une disposition non autorisée ou inventée doit être rejetée par le reconciler."""
    fausse_disposition = {
        "disposition": "IGNORE_TEMPORARILY",
        "reason": "aucune",
        "measured": "aucune",
    }
    catalogue_muté = dict(reconciler.DISPOSITIONS_CATALOGUE)
    catalogue_muté["999"] = fausse_disposition
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(reconciler, "DISPOSITIONS_CATALOGUE", catalogue_muté)
    try:
        with pytest.raises(ValueError, match="disposition non autorisée"):
            reconciler.construire_dispositions("a" * 40)
    finally:
        monkeypatch.undo()


def test_dispositions_reconnues_par_le_gate_readiness(dispositions_doc):
    """Toutes les dispositions du document doivent appartenir aux ensembles du gate."""
    toutes_autorisees = readiness.DISPOSITIONS_BLOQUANTES | readiness.DISPOSITIONS_NON_BLOQUANTES
    for num, item in dispositions_doc["dispositions"].items():
        assert item["disposition"] in toutes_autorisees, (
            f"PR #{num} a une disposition non reconnue par le gate : {item['disposition']}"
        )


def test_open_prs_blocking_zero_apres_arbitrage_humain(dispositions_doc):
    """Le calcul doit donner exactement 0 PR bloquante après arbitrage humain de #138 et #140."""
    bloquantes = [
        num
        for num, item in dispositions_doc["dispositions"].items()
        if item["disposition"] in readiness.DISPOSITIONS_BLOQUANTES
    ]
    assert len(bloquantes) == 0
    assert bloquantes == []


def test_138_closed_rejected_apres_arbitrage_humain(dispositions_doc):
    """PR #138 est CLOSE_REJECTED suite à arbitrage formel humain."""
    pr138 = dispositions_doc["dispositions"].get("138")
    assert pr138 is not None
    assert pr138["disposition"] == "CLOSE_REJECTED"
    assert "ARBITRATED_CLOSED=true" in pr138["measured"]
    assert "VIOLATES_ADR_0050=true" in pr138["measured"]
    assert "HUMAN_DECISIONS_PR_138_140.md" in pr138["measured"]
    assert "GITHUB_STATE=closed" in pr138["measured"]


def test_140_closed_superseded_apres_arbitrage_humain(dispositions_doc):
    """PR #140 est CLOSE_SUPERSEDED suite à arbitrage formel humain."""
    pr140 = dispositions_doc["dispositions"].get("140")
    assert pr140 is not None
    assert pr140["disposition"] == "CLOSE_SUPERSEDED"
    assert "ARBITRATED_CLOSED=true" in pr140["measured"]
    assert "CHANGED_FILES=343" in pr140["measured"]
    assert "HUMAN_DECISIONS_PR_138_140.md" in pr140["measured"]
    assert "GITHUB_STATE=closed" in pr140["measured"]


def test_132_superseded_apres_integration_rehearsal_v2(dispositions_doc):
    """PR #132 est CLOSE_SUPERSEDED après intégration du rehearsal Docker V2."""
    pr132 = dispositions_doc["dispositions"].get("132")
    assert pr132 is not None
    assert pr132["disposition"] == "CLOSE_SUPERSEDED"
    assert "INTEGRATED_ON_MAIN=true" in pr132["measured"]
    assert "REHEARSAL_REPLAYED_PASS=true" in pr132["measured"]


def test_151_superseded_apres_extraction_registre_url(dispositions_doc):
    """PR #151 est CLOSE_SUPERSEDED après extraction de url_source_registry."""
    pr151 = dispositions_doc["dispositions"].get("151")
    assert pr151 is not None
    assert pr151["disposition"] == "CLOSE_SUPERSEDED"
    assert "AUTONOMOUS_COMPONENTS_INTEGRATED=true" in pr151["measured"]


def test_rendu_markdown_est_coherent(dispositions_doc):
    assert MARKDOWN_PATH.is_file()
    rendu = MARKDOWN_PATH.read_text(encoding="utf-8")
    assert "PR ouvertes totales : **10**" in rendu
    assert "PR bloquantes : **0**" in rendu
    assert "`#134`" in rendu
    assert "`#138`" in rendu
    assert "`#140`" in rendu
    assert "`KEEP_OPEN_GOVERNED_NO_MERGE`" in rendu
    assert "`#98`" in rendu
    assert "`CLOSE_SUPERSEDED`" in rendu
