"""Le producteur projette la décision humaine, il ne la fabrique pas (ADR-0047).

`_pii_evidence` scannait le corpus et écrivait `DETECTED_RECORDED` pour tout
contenu détecté — un verdict honnête, mais définitif : rien ne pouvait admettre
un contenu après revue. Ces tests fixent le comportement inverse : le
producteur lit un ensemble de décisions scellé et son reçu, les confronte à son
propre scan, et projette leur résultat — ou refuse.

Le point qui compte : la population autorisée est CALCULÉE depuis les preuves.
Aucun compte attendu n'est écrit dans le producteur.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from rag_pedago.imports.pii_review_projection import (
    PiiProjectionError,
    ScannedContent,
    ScannedFinding,
    project_pii_review,
)

PRODUCER = (
    Path(__file__).resolve().parents[1] / "scripts" / "build_production_profile_release.py"
)
REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_DECISION_SET = REPO_ROOT / "governance/pii-review-decisions/pii-review-2026-09-03-final.json"
REAL_RECEIPT = REPO_ROOT / "governance/pii-review-bindings/pii-review-2026-09-03-final.json"
REAL_ANCHOR = REPO_ROOT / "governance/trust-anchors/review-binding-v1.json"
REAL_INDEX = REPO_ROOT / "docs/reports/evidence-index/pii_review_index_20260903.json"


class TestProducerCarriesNoBusinessConstant:
    def test_no_expected_population_is_written_in_the_producer(self) -> None:
        """Ni 297, ni 23, ni 320 comme littéraux du producteur.

        La garde lit l'arbre syntaxique : un commentaire a le droit
        d'expliquer d'où vient un nombre, le code n'a pas le droit de le
        présupposer."""
        literals = {
            node.value
            for node in ast.walk(ast.parse(PRODUCER.read_text(encoding="utf-8")))
            if isinstance(node, ast.Constant) and isinstance(node.value, int)
        }
        assert literals & {297, 23, 320} == set()


class TestProducerExposesTheReviewAuthority:
    def test_producer_declares_injected_review_authority_arguments(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """L'autorité de revue s'injecte ; elle n'est pas devinée d'un chemin.

        On interroge la VRAIE surface d'appel — `--help` — et non le texte du
        fichier : les options sont construites par boucle, et une garde qui
        cherche un littéral dans la source échouerait sur du code correct."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("_producer_cli", PRODUCER)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with pytest.raises(SystemExit):
            module.main(["--help"])
        helptext = capsys.readouterr().out
        for option in (
            "--pii-decision-set",
            "--pii-review-receipt",
            "--review-trust-anchor",
            "--pii-review-index",
            "--pii-review-reviewer",
        ):
            assert option in helptext, f"option {option} absente du producteur"

    def test_producer_binds_the_review_authority_into_the_release(self) -> None:
        """Le decision set et son reçu appartiennent à la chaîne d'autorité
        du NOUVEAU candidat (§7), pas à une release historique."""
        source = PRODUCER.read_text(encoding="utf-8")
        assert "pii_decision_set_sha256" in source
        assert "pii_review_receipt_sha256" in source


class TestRealDecisionSetProjectsOntoARealisticScan:
    """La projection tient sur le decision set réellement scellé."""

    def _decision_set(self) -> dict:
        import json

        return json.loads(REAL_DECISION_SET.read_text(encoding="utf-8"))

    def _scan_from_decisions(self, clean_count: int) -> list[ScannedContent]:
        """Reconstruit un scan cohérent avec les décisions réelles.

        On ne re-scanne pas 320 PDF ici : on vérifie l'ALGÈBRE sur les vraies
        décisions. Le scan réel est confronté aux décisions lors de la
        production de la candidate."""
        document = self._decision_set()
        scanned: list[ScannedContent] = []
        for index in range(clean_count):
            scanned.append(
                ScannedContent(
                    content_sha256=f"{index:064x}",
                    pages_scanned=1,
                    characters_scanned=1,
                    ignored_empty_pages=(),
                    findings=(),
                )
            )
        for decision in document["decisions"]:
            scanned.append(
                ScannedContent(
                    content_sha256=decision["content_sha256"],
                    pages_scanned=1,
                    characters_scanned=1,
                    ignored_empty_pages=(),
                    findings=tuple(
                        ScannedFinding(
                            finding_id=f["finding_id"],
                            pattern_id=f["pattern_id"],
                            page=f["page"],
                            match_sha256=f["match_sha256"],
                            context_sha256=f["context_sha256"],
                        )
                        for f in decision["findings"]
                    ),
                )
            )
        return scanned

    def _bundles(self) -> dict[str, str]:
        import json

        index = json.loads(REAL_INDEX.read_text(encoding="utf-8"))
        return {b["content_sha256"]: b["bundle_sha256"] for b in index["bundles"]}

    def _project(self, clean_count: int):
        document = self._decision_set()
        return project_pii_review(
            self._scan_from_decisions(clean_count),
            decision_set_document=document,
            review_bundles=self._bundles(),
            policy_sha256=document["policy_sha256"],
            scanner_sha256=document["scanner_sha256"],
            page_policy_sha256=document["page_policy_sha256"],
        )

    def test_the_real_decisions_project_without_refusal(self) -> None:
        document = self._decision_set()
        decided = len(document["decisions"])
        projection = self._project(clean_count=7)
        assert projection.counts["detected_count"] == decided
        assert projection.counts["reviewed_accepted_count"] == decided
        assert projection.counts["rejected_count"] == 0
        assert projection.counts["cleared_count"] == 7
        assert projection.counts["authorized_count"] == 7 + decided

    def test_the_index_bundles_found_the_real_decisions(self) -> None:
        """Chaque décision réelle est adossée au paquet que l'index lui donne."""
        document = self._decision_set()
        bundles = self._bundles()
        for decision in document["decisions"]:
            assert bundles[decision["content_sha256"]] == decision["review_bundle_sha256"]

    def test_a_substituted_bundle_is_refused(self) -> None:
        """Sabotage : même cardinalité, un paquet remplacé."""
        document = self._decision_set()
        bundles = self._bundles()
        victim = document["decisions"][0]["content_sha256"]
        bundles[victim] = "0" * 64
        with pytest.raises(PiiProjectionError, match="bundle"):
            project_pii_review(
                self._scan_from_decisions(3),
                decision_set_document=document,
                review_bundles=bundles,
                policy_sha256=document["policy_sha256"],
                scanner_sha256=document["scanner_sha256"],
                page_policy_sha256=document["page_policy_sha256"],
            )

    def test_a_scan_that_lost_one_decided_finding_is_refused(self) -> None:
        """Sabotage : une disposition qui ne porte plus sur rien."""
        document = self._decision_set()
        scanned = self._scan_from_decisions(3)
        # Un contenu à plusieurs findings : en retirer un doit déclencher la
        # garde des FINDINGS. Sur un contenu à finding unique, c'est la garde
        # « décision devenue sans objet » qui se déclenche d'abord — elle est
        # correcte aussi, mais ce n'est pas celle qu'on veut prouver ici.
        victim = next(c for c in scanned if len(c.findings) > 1)
        amputated = ScannedContent(
            content_sha256=victim.content_sha256,
            pages_scanned=victim.pages_scanned,
            characters_scanned=victim.characters_scanned,
            ignored_empty_pages=victim.ignored_empty_pages,
            findings=victim.findings[1:],
        )
        scanned = [amputated if c is victim else c for c in scanned]
        with pytest.raises(PiiProjectionError, match="no longer"):
            project_pii_review(
                scanned,
                decision_set_document=document,
                review_bundles=self._bundles(),
                policy_sha256=document["policy_sha256"],
                scanner_sha256=document["scanner_sha256"],
                page_policy_sha256=document["page_policy_sha256"],
            )


class TestCandidateIsFinalButNotActivable:
    """Corpus final ≠ permission de déployer (§9-§10).

    Une release post-revue contient le corpus autorisé définitif, et n'est
    pourtant pas activable : le gate PII n'est qu'un des gates de go-live. Le
    producteur doit donc pouvoir émettre, en mode PRODUCTION (donc avec le vrai
    corpus, pas une répétition), une release marquée non promouvable et non
    activable — sous les enums qui existent déjà, et que le runtime refuse
    déjà mécaniquement."""

    def test_production_mode_accepts_candidate_status_flags(self) -> None:
        import inspect

        import importlib.util

        spec = importlib.util.spec_from_file_location("_producer_flags", PRODUCER)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        signature = inspect.signature(module._release_topology_documents)
        for parameter in ("promotion_status", "activation_status", "review_status"):
            assert parameter in signature.parameters

    def test_the_production_path_forwards_the_candidate_flags(self) -> None:
        """Le chemin production doit TRANSMETTRE ces statuts, pas seulement
        les accepter : c'est ce qui manquait, et c'est ce qui rendrait une
        candidate silencieusement activable."""
        source = PRODUCER.read_text(encoding="utf-8")
        production_call = source[source.index("        _release_topology_documents("):]
        production_call = production_call[: production_call.index("\n    )")]
        for parameter in ("promotion_status=", "activation_status=", "review_status="):
            assert parameter in production_call, (
                f"{parameter} n'est pas transmis par la voie production"
            )

    def test_the_production_release_id_is_not_silently_reused(self) -> None:
        """§8 : une candidate a sa propre identité, jamais celle d'une
        release historique dont la sémantique a déjà dérivé."""
        source = PRODUCER.read_text(encoding="utf-8")
        production_call = source[source.index("        _release_topology_documents("):]
        production_call = production_call[: production_call.index("\n    )")]
        assert "release_id=RELEASE_ID," not in production_call, (
            "la voie production réemploie l'identifiant historique en dur"
        )
