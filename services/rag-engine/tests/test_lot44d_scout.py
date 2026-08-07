"""LOT44d : Scout — découverte déterministe de ResourceCandidate.

Périmètre strict : cœur pur testé sans E/S ; ``run_scout`` testé avec une
doublure de ``validate_destination`` et un double d'``apply_resource_transition``
(monkeypatché) — aucun réseau réel, aucun PostgreSQL réel dans ce fichier.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from nexus_contracts.ingestion import SearchPlan
from nexus_contracts.resource_state import ResourceState

from ingestor.ingestion_agents import scout as scout_module
from ingestor.ingestion_agents.scout import (
    DomainNotAllowedError,
    discover_candidate_core,
    run_scout,
)
from ingestor.ingestion_agents.transitions import TransitionResult
from ingestor.ssrf_guard import SSRFValidationError

SCOPE = {
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


def _search_plan(**overrides: object) -> SearchPlan:
    payload: dict[str, object] = {
        "search_plan_id": uuid4(),
        "run_id": uuid4(),
        "scope": SCOPE,
        "generated_at": datetime(2026, 8, 4, tzinfo=UTC),
        "profile_version": "v1",
        "queries": ["algorithmique"],
        "allowed_domains": ["eduscol.education.fr"],
        "max_results": 20,
        "reason": "cadence hebdomadaire",
    }
    payload.update(overrides)
    return SearchPlan.model_validate(payload)


class TestDiscoverCandidateCore:
    def test_domain_within_allowed_domains_produces_candidate(self) -> None:
        candidate = discover_candidate_core(
            search_plan=_search_plan(),
            resource_id=uuid4(),
            candidate_id=uuid4(),
            discovered_at=datetime(2026, 8, 4, tzinfo=UTC),
            source_url="https://eduscol.education.fr/nsi/algo",
            canonical_url="https://eduscol.education.fr/nsi/algo",
            domain="eduscol.education.fr",
            proposed_type_doc="cours",
        )
        assert candidate.domain == "eduscol.education.fr"
        assert len(candidate.dedup_key) == 64

    def test_domain_outside_allowed_domains_is_rejected(self) -> None:
        with pytest.raises(DomainNotAllowedError):
            discover_candidate_core(
                search_plan=_search_plan(),
                resource_id=uuid4(),
                candidate_id=uuid4(),
                discovered_at=datetime(2026, 8, 4, tzinfo=UTC),
                source_url="https://evil.example.com/nsi/algo",
                canonical_url="https://evil.example.com/nsi/algo",
                domain="evil.example.com",
                proposed_type_doc="cours",
            )

    def test_declared_domain_disagreeing_with_source_url_host_is_rejected(self) -> None:
        """Revue PR#90 (Codex + Cubic) : un opérateur ne doit jamais pouvoir
        déclarer ``domain="eduscol.education.fr"`` (allowlisté) tout en
        fournissant une ``source_url`` pointant vers un tout autre hôte —
        avant ce correctif, seule la chaîne déclarée était comparée à
        ``allowed_domains``, jamais l'hôte réel de l'URL."""
        with pytest.raises(DomainNotAllowedError, match="does not match"):
            discover_candidate_core(
                search_plan=_search_plan(allowed_domains=["eduscol.education.fr"]),
                resource_id=uuid4(),
                candidate_id=uuid4(),
                discovered_at=datetime(2026, 8, 4, tzinfo=UTC),
                source_url="https://evil.example.com/nsi/algo",
                canonical_url="https://evil.example.com/nsi/algo",
                domain="eduscol.education.fr",
                proposed_type_doc="cours",
            )

    def test_canonical_url_host_outside_allowed_domains_is_rejected(self) -> None:
        """``canonical_url`` sert d'identité de source faisant autorité
        (``dedup_key`` en dépend) — son hôte doit lui aussi être
        allowlisté, même quand ``source_url``/``domain`` sont cohérents."""
        with pytest.raises(DomainNotAllowedError):
            discover_candidate_core(
                search_plan=_search_plan(allowed_domains=["eduscol.education.fr"]),
                resource_id=uuid4(),
                candidate_id=uuid4(),
                discovered_at=datetime(2026, 8, 4, tzinfo=UTC),
                source_url="https://eduscol.education.fr/nsi/algo",
                canonical_url="https://evil.example.com/nsi/algo",
                domain="eduscol.education.fr",
                proposed_type_doc="cours",
            )

    def test_domain_case_and_trailing_dot_are_normalized(self) -> None:
        candidate = discover_candidate_core(
            search_plan=_search_plan(allowed_domains=["eduscol.education.fr"]),
            resource_id=uuid4(),
            candidate_id=uuid4(),
            discovered_at=datetime(2026, 8, 4, tzinfo=UTC),
            source_url="https://EDUSCOL.education.fr./nsi/algo",
            canonical_url="https://EDUSCOL.education.fr./nsi/algo",
            domain="eduscol.education.fr",
            proposed_type_doc="cours",
        )
        assert candidate.domain == "eduscol.education.fr"

    def test_declared_domain_with_mixed_case_and_trailing_dot_is_normalized(self) -> None:
        """Revue incrémentale PR#90 (Cubic P2) : avant ce correctif, seul
        l'hôte dérivé de l'URL (``_hostname_of``) était normalisé —
        ``domain`` (fourni par l'appelant) était comparé tel quel. Un
        appelant déclarant ``domain="EDUSCOL.education.fr."`` alors que
        ``source_url``/``canonical_url`` pointent vers l'hôte équivalent en
        minuscules aurait été rejeté à tort (``source_host != domain``,
        chaîne normalisée vs chaîne brute)."""
        candidate = discover_candidate_core(
            search_plan=_search_plan(allowed_domains=["eduscol.education.fr"]),
            resource_id=uuid4(),
            candidate_id=uuid4(),
            discovered_at=datetime(2026, 8, 4, tzinfo=UTC),
            source_url="https://eduscol.education.fr/nsi/algo",
            canonical_url="https://eduscol.education.fr/nsi/algo",
            domain="EDUSCOL.education.fr.",
            proposed_type_doc="cours",
        )
        assert candidate.domain == "eduscol.education.fr"

    def test_allowed_domains_entry_with_mixed_case_still_matches(self) -> None:
        """Revue incrémentale PR#90 (Cubic P2) : une entrée
        ``allowed_domains`` saisie avec une casse différente (ex. par un
        opérateur éditant un profil YAML à la main) ne doit jamais rejeter
        à tort un hôte légitimement autorisé — les trois sources (domaine
        déclaré, entrées d'allowlist, hôtes dérivés d'URL) doivent être
        normalisées de façon identique avant toute comparaison."""
        candidate = discover_candidate_core(
            search_plan=_search_plan(allowed_domains=["Eduscol.Education.FR"]),
            resource_id=uuid4(),
            candidate_id=uuid4(),
            discovered_at=datetime(2026, 8, 4, tzinfo=UTC),
            source_url="https://eduscol.education.fr/nsi/algo",
            canonical_url="https://eduscol.education.fr/nsi/algo",
            domain="eduscol.education.fr",
            proposed_type_doc="cours",
        )
        assert candidate.domain == "eduscol.education.fr"

    def test_dedup_key_is_deterministic_for_same_canonical_url(self) -> None:
        kwargs = dict(
            search_plan=_search_plan(),
            resource_id=uuid4(),
            candidate_id=uuid4(),
            discovered_at=datetime(2026, 8, 4, tzinfo=UTC),
            source_url="https://eduscol.education.fr/nsi/algo",
            canonical_url="https://eduscol.education.fr/nsi/algo",
            domain="eduscol.education.fr",
            proposed_type_doc="cours",
        )
        candidate_a = discover_candidate_core(**kwargs)
        candidate_b = discover_candidate_core(**{**kwargs, "candidate_id": uuid4()})
        assert candidate_a.dedup_key == candidate_b.dedup_key

    def test_dedup_key_differs_for_different_canonical_url(self) -> None:
        search_plan = _search_plan()
        candidate_a = discover_candidate_core(
            search_plan=search_plan,
            resource_id=uuid4(),
            candidate_id=uuid4(),
            discovered_at=datetime(2026, 8, 4, tzinfo=UTC),
            source_url="https://eduscol.education.fr/nsi/algo",
            canonical_url="https://eduscol.education.fr/nsi/algo",
            domain="eduscol.education.fr",
            proposed_type_doc="cours",
        )
        candidate_b = discover_candidate_core(
            search_plan=search_plan,
            resource_id=uuid4(),
            candidate_id=uuid4(),
            discovered_at=datetime(2026, 8, 4, tzinfo=UTC),
            source_url="https://eduscol.education.fr/nsi/autre",
            canonical_url="https://eduscol.education.fr/nsi/autre",
            domain="eduscol.education.fr",
            proposed_type_doc="cours",
        )
        assert candidate_a.dedup_key != candidate_b.dedup_key


class TestRunScoutWiring:
    def test_validates_destination_before_building_candidate(self) -> None:
        def blocking_validate_destination(url: str) -> str:
            raise SSRFValidationError(f"blocked: {url}")

        with pytest.raises(SSRFValidationError):
            run_scout(
                conn=MagicMock(),
                search_plan=_search_plan(),
                resource_id=uuid4(),
                candidate_id=uuid4(),
                discovered_at=datetime(2026, 8, 4, tzinfo=UTC),
                source_url="http://169.254.169.254/latest/meta-data",
                canonical_url="http://169.254.169.254/latest/meta-data",
                domain="169.254.169.254",
                proposed_type_doc="cours",
                expected_version=1,
                actor="scout-test",
                validate_destination=blocking_validate_destination,
            )

    def test_calls_apply_resource_transition_with_discovered_to_candidate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        resource_id = uuid4()
        run_id = uuid4()
        fake_transition = TransitionResult(
            resource_id=resource_id,
            from_state=ResourceState.DISCOVERED,
            to_state=ResourceState.CANDIDATE,
            state_version=2,
        )
        mock_apply = MagicMock(return_value=fake_transition)
        monkeypatch.setattr(scout_module, "apply_resource_transition", mock_apply)

        candidate, transition = run_scout(
            conn=MagicMock(),
            search_plan=_search_plan(run_id=run_id),
            resource_id=resource_id,
            candidate_id=uuid4(),
            discovered_at=datetime(2026, 8, 4, tzinfo=UTC),
            source_url="https://eduscol.education.fr/nsi/algo",
            canonical_url="https://eduscol.education.fr/nsi/algo",
            domain="eduscol.education.fr",
            proposed_type_doc="cours",
            expected_version=1,
            actor="scout-test",
            validate_destination=lambda url: url,
        )

        assert transition is fake_transition
        mock_apply.assert_called_once()
        _, kwargs = mock_apply.call_args
        assert kwargs["resource_id"] == resource_id
        assert kwargs["expected_state"] == ResourceState.DISCOVERED
        assert kwargs["new_state"] == ResourceState.CANDIDATE
        assert kwargs["run_id"] == run_id
        assert candidate.candidate_id is not None

    def test_job_id_is_forwarded_to_apply_resource_transition(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_transition = TransitionResult(
            resource_id=uuid4(), from_state=ResourceState.DISCOVERED,
            to_state=ResourceState.CANDIDATE, state_version=2,
        )
        mock_apply = MagicMock(return_value=fake_transition)
        monkeypatch.setattr(scout_module, "apply_resource_transition", mock_apply)
        job_id = uuid4()

        run_scout(
            conn=MagicMock(),
            search_plan=_search_plan(),
            resource_id=uuid4(),
            candidate_id=uuid4(),
            discovered_at=datetime(2026, 8, 4, tzinfo=UTC),
            source_url="https://eduscol.education.fr/nsi/algo",
            canonical_url="https://eduscol.education.fr/nsi/algo",
            domain="eduscol.education.fr",
            proposed_type_doc="cours",
            expected_version=1,
            actor="scout-test",
            job_id=job_id,
            validate_destination=lambda url: url,
        )

        assert mock_apply.call_args.kwargs["job_id"] == job_id

    def test_job_id_defaults_to_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_transition = TransitionResult(
            resource_id=uuid4(), from_state=ResourceState.DISCOVERED,
            to_state=ResourceState.CANDIDATE, state_version=2,
        )
        mock_apply = MagicMock(return_value=fake_transition)
        monkeypatch.setattr(scout_module, "apply_resource_transition", mock_apply)

        run_scout(
            conn=MagicMock(),
            search_plan=_search_plan(),
            resource_id=uuid4(),
            candidate_id=uuid4(),
            discovered_at=datetime(2026, 8, 4, tzinfo=UTC),
            source_url="https://eduscol.education.fr/nsi/algo",
            canonical_url="https://eduscol.education.fr/nsi/algo",
            domain="eduscol.education.fr",
            proposed_type_doc="cours",
            expected_version=1,
            actor="scout-test",
            validate_destination=lambda url: url,
        )

        assert mock_apply.call_args.kwargs["job_id"] is None
