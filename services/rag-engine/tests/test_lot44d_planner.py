"""LOT44d : Planner — génération déterministe de SearchPlan.

Périmètre strict : tests unitaires purs sur fixtures. Aucun réseau réel :
``validate_destination`` est toujours injecté (doublure), jamais la vraie
garde SSRF dans ce fichier.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from nexus_contracts.ingestion import CollectionProfile

from ingestor.ingestion_agents.planner import plan_search_core, run_planner
from ingestor.ssrf_guard import SSRFValidationError

VALID_SCOPE = {
    "tenant": "libre_terminale",
    "collection": "rag_nexus_nsi_terminale_specialite",
    "niveau": "terminale",
    "voie": "generale",
    "matiere": "nsi",
    "candidat": "libre",
    "audience": ["libre", "tous"],
    "visibility": "internal",
    "school_year": "2026-2027",
    "programme_version": "BOEN_special_8_2019-07-25",
}


def _profile(**overrides: object) -> CollectionProfile:
    payload: dict[str, object] = {
        "profile_version": "v1",
        "enabled": True,
        "scope": VALID_SCOPE,
        "title": "NSI Terminale Spécialité",
        "owner": "equipe-nsi",
        "expected_topics": ["algorithmique", "structures de données"],
        "expected_resource_types": ["cours"],
        "allowed_domains": ["eduscol.education.fr"],
        "source_authority": "official",
        "search_cadence": "weekly",
        "max_queries_per_run": 10,
        "max_documents_per_run": 20,
        "max_chunk_size": 800,
        "chunk_overlap": 100,
        "min_source_confidence": 0.7,
        "min_scope_confidence": 0.7,
        "min_extraction_quality": 0.6,
    }
    payload.update(overrides)
    return CollectionProfile.model_validate(payload)


class TestPlanSearchCore:
    def test_queries_prioritize_gap_targets_before_expected_topics(self) -> None:
        plan = plan_search_core(
            profile=_profile(),
            run_id=uuid4(),
            search_plan_id=uuid4(),
            generated_at=datetime(2026, 8, 4, tzinfo=UTC),
            reason="couverture insuffisante détectée par CoverageAgent",
            gap_targets=("récursivité",),
        )
        assert plan.queries == ["récursivité", "algorithmique", "structures de données"]

    def test_no_duplicate_query_when_gap_target_already_expected(self) -> None:
        plan = plan_search_core(
            profile=_profile(),
            run_id=uuid4(),
            search_plan_id=uuid4(),
            generated_at=datetime(2026, 8, 4, tzinfo=UTC),
            reason="cadence hebdomadaire",
            gap_targets=("algorithmique",),
        )
        assert plan.queries == ["algorithmique", "structures de données"]

    def test_allowed_domains_and_max_results_come_from_profile(self) -> None:
        plan = plan_search_core(
            profile=_profile(allowed_domains=["eduscol.education.fr", "lumni.fr"]),
            run_id=uuid4(),
            search_plan_id=uuid4(),
            generated_at=datetime(2026, 8, 4, tzinfo=UTC),
            reason="cadence hebdomadaire",
        )
        assert plan.allowed_domains == ["eduscol.education.fr", "lumni.fr"]
        assert plan.max_results == 20

    def test_deterministic_for_identical_inputs(self) -> None:
        run_id = uuid4()
        search_plan_id = uuid4()
        generated_at = datetime(2026, 8, 4, tzinfo=UTC)
        profile = _profile()
        plan_a = plan_search_core(
            profile=profile,
            run_id=run_id,
            search_plan_id=search_plan_id,
            generated_at=generated_at,
            reason="cadence hebdomadaire",
        )
        plan_b = plan_search_core(
            profile=profile,
            run_id=run_id,
            search_plan_id=search_plan_id,
            generated_at=generated_at,
            reason="cadence hebdomadaire",
        )
        assert plan_a == plan_b


class TestPlanSearchCoreMaxQueriesPerRunBudget:
    """Revue incrémentale PR#90 : ``ordered_queries`` doit être borné par
    ``profile.max_queries_per_run`` — un profil porte ce budget
    explicitement (LOT44a) ; le laisser sans effet était inacceptable pour
    une release gouvernée. L'ordre gap-targets-d'abord (déjà établi par
    ``TestPlanSearchCore``) doit rester respecté même sous contrainte de
    budget."""

    def test_budget_of_one_keeps_only_the_single_highest_priority_query(self) -> None:
        plan = plan_search_core(
            profile=_profile(
                max_queries_per_run=1,
                expected_topics=["algorithmique", "structures de données"],
            ),
            run_id=uuid4(),
            search_plan_id=uuid4(),
            generated_at=datetime(2026, 8, 4, tzinfo=UTC),
            reason="budget serré",
            gap_targets=("récursivité",),
        )
        assert plan.queries == ["récursivité"]

    def test_budget_smaller_than_gap_target_count_truncates_within_gap_targets(self) -> None:
        plan = plan_search_core(
            profile=_profile(max_queries_per_run=2, expected_topics=["algorithmique"]),
            run_id=uuid4(),
            search_plan_id=uuid4(),
            generated_at=datetime(2026, 8, 4, tzinfo=UTC),
            reason="budget serré",
            gap_targets=("récursivité", "tri fusion", "complexité"),
        )
        assert plan.queries == ["récursivité", "tri fusion"]

    def test_budget_larger_than_available_queries_keeps_everything(self) -> None:
        plan = plan_search_core(
            profile=_profile(
                max_queries_per_run=50,
                expected_topics=["algorithmique", "structures de données"],
            ),
            run_id=uuid4(),
            search_plan_id=uuid4(),
            generated_at=datetime(2026, 8, 4, tzinfo=UTC),
            reason="budget large",
            gap_targets=("récursivité",),
        )
        assert plan.queries == ["récursivité", "algorithmique", "structures de données"]

    def test_deduplication_happens_before_the_budget_is_applied(self) -> None:
        """Une cible de couverture déjà présente dans expected_topics ne
        doit jamais consommer deux fois le budget — la déduplication
        s'applique avant la troncature, jamais après."""
        plan = plan_search_core(
            profile=_profile(
                max_queries_per_run=2,
                expected_topics=["algorithmique", "structures de données"],
            ),
            run_id=uuid4(),
            search_plan_id=uuid4(),
            generated_at=datetime(2026, 8, 4, tzinfo=UTC),
            reason="budget serré avec doublon",
            gap_targets=("algorithmique",),
        )
        assert plan.queries == ["algorithmique", "structures de données"]

    def test_gap_targets_retain_priority_over_expected_topics_under_budget(self) -> None:
        plan = plan_search_core(
            profile=_profile(
                max_queries_per_run=3,
                expected_topics=["algorithmique", "structures de données", "récursion"],
            ),
            run_id=uuid4(),
            search_plan_id=uuid4(),
            generated_at=datetime(2026, 8, 4, tzinfo=UTC),
            reason="priorité gap-targets",
            gap_targets=("tri fusion", "complexité"),
        )
        assert plan.queries == ["tri fusion", "complexité", "algorithmique"]

    def test_result_never_exceeds_the_declared_budget(self) -> None:
        plan = plan_search_core(
            profile=_profile(
                max_queries_per_run=2,
                expected_topics=["a", "b", "c", "d", "e"],
            ),
            run_id=uuid4(),
            search_plan_id=uuid4(),
            generated_at=datetime(2026, 8, 4, tzinfo=UTC),
            reason="pas de dépassement",
            gap_targets=("g1", "g2", "g3"),
        )
        assert len(plan.queries) <= 2


class TestRunPlannerSeedUrlValidation:
    def test_valid_seed_urls_are_validated_then_plan_is_built(self) -> None:
        calls: list[str] = []

        def fake_validate_destination(url: str) -> str:
            calls.append(url)
            return url

        plan = run_planner(
            profile=_profile(seed_urls=["https://eduscol.education.fr/nsi"]),
            run_id=uuid4(),
            search_plan_id=uuid4(),
            generated_at=datetime(2026, 8, 4, tzinfo=UTC),
            reason="cadence hebdomadaire",
            validate_destination=fake_validate_destination,
        )
        assert calls == ["https://eduscol.education.fr/nsi"]
        assert plan.reason == "cadence hebdomadaire"

    def test_blocked_seed_url_raises_and_produces_no_plan(self) -> None:
        def blocking_validate_destination(url: str) -> str:
            raise SSRFValidationError(f"blocked: {url}")

        with pytest.raises(SSRFValidationError):
            run_planner(
                profile=_profile(seed_urls=["http://169.254.169.254/latest/meta-data"]),
                run_id=uuid4(),
                search_plan_id=uuid4(),
                generated_at=datetime(2026, 8, 4, tzinfo=UTC),
                reason="cadence hebdomadaire",
                validate_destination=blocking_validate_destination,
            )

    def test_no_seed_urls_means_no_validation_call(self) -> None:
        calls: list[str] = []

        def fake_validate_destination(url: str) -> str:
            calls.append(url)
            return url

        run_planner(
            profile=_profile(),
            run_id=uuid4(),
            search_plan_id=uuid4(),
            generated_at=datetime(2026, 8, 4, tzinfo=UTC),
            reason="cadence hebdomadaire",
            validate_destination=fake_validate_destination,
        )
        assert calls == []
