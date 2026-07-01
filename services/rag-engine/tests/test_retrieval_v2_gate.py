"""Tests for retrieval_v2 gate retrievable — fail-closed (HH-01, GG-01)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Import the gate function from the script
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from retrieval_v2 import CollectionNotRetrievableError, _check_retrievable

# --- Fixtures ---

FULL_CFG = {
    "version": 2,
    "collections": {
        "rag_nexus_nsi_terminale_specialite": {
            "matiere": "nsi", "niveau": "terminale", "statut": "specialite",
            "domain": "education", "instanciee": True,
        },
        "rag_nexus_quarantine": {
            "matiere": None, "niveau": None, "statut": None,
            "domain": "quarantine", "instanciee": True,
        },
        "col_no_domain": {
            "matiere": "test", "instanciee": True,
            # domain intentionally absent
        },
        "col_renamed_but_domain_set": {
            "matiere": "nsi", "niveau": "premiere", "statut": "specialite",
            "domain": "education", "instanciee": True,
        },
    },
    "domains": {
        "education": {"audiences": ["tous"], "retrievable": True},
        "quarantine": {"retrievable": False},
        "no_retrievable_key": {"audiences": ["tous"]},
    },
}


class TestGateRetrievable:
    """HH-01: 7 tests proving fail-closed behavior."""

    def test_quarantine_refused(self) -> None:
        """Case 1: rag_nexus_quarantine → CollectionNotRetrievableError."""
        with pytest.raises(CollectionNotRetrievableError, match="not retrievable"):
            _check_retrievable("rag_nexus_quarantine", FULL_CFG)

    def test_domains_absent_refused(self) -> None:
        """Case 2: domains absent from cfg → refus."""
        cfg_no_domains = {**FULL_CFG, "domains": "not_a_dict"}
        with pytest.raises(CollectionNotRetrievableError, match="absent or malformed"):
            _check_retrievable("rag_nexus_nsi_terminale_specialite", cfg_no_domains)

    def test_domain_entry_absent_refused(self) -> None:
        """Case 3: domain entry absent in domains → refus."""
        cfg_missing_entry = {
            **FULL_CFG,
            "domains": {"other": {"retrievable": True}},  # no "education"
        }
        with pytest.raises(CollectionNotRetrievableError, match="not found in config"):
            _check_retrievable("rag_nexus_nsi_terminale_specialite", cfg_missing_entry)

    def test_domain_not_declared_in_collection_refused(self) -> None:
        """Case 4: domain not declared in collection definition → refus."""
        with pytest.raises(CollectionNotRetrievableError, match="no declared domain"):
            _check_retrievable("col_no_domain", FULL_CFG)

    def test_retrievable_absent_refused(self) -> None:
        """Case 5: retrievable key absent (neither True nor False) → refus (default = refuse)."""
        cfg_with_no_ret = {
            **FULL_CFG,
            "collections": {
                **FULL_CFG["collections"],
                "col_domain_no_ret": {
                    "matiere": "test", "domain": "no_retrievable_key", "instanciee": True,
                },
            },
        }
        with pytest.raises(CollectionNotRetrievableError, match="not retrievable"):
            _check_retrievable("col_domain_no_ret", cfg_with_no_ret)

    def test_education_retrievable_passes(self) -> None:
        """Case 6: collection with retrievable:true → passes, returns definition."""
        result = _check_retrievable("rag_nexus_nsi_terminale_specialite", FULL_CFG)
        assert result["matiere"] == "nsi"
        assert result["domain"] == "education"

    def test_renamed_collection_reads_declared_domain(self) -> None:
        """Case 7: renaming collection doesn't change domain (reads field, not name)."""
        # col_renamed_but_domain_set has domain=education, which is retrievable:true
        result = _check_retrievable("col_renamed_but_domain_set", FULL_CFG)
        assert result["domain"] == "education"


class TestCatalogueGuard:
    """HH-02: guard — every instanciee:true collection MUST declare a domain."""

    def test_all_instanciated_have_domain(self) -> None:
        """Every instanciee:true entry in rag_collections.yml must have a non-empty domain."""
        import yaml

        config_path = Path(__file__).resolve().parents[1] / "configs" / "rag_collections.yml"
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))

        for name, defn in cfg["collections"].items():
            if not isinstance(defn, dict):
                continue
            if defn.get("instanciee") is not True:
                continue
            domain = defn.get("domain")
            assert isinstance(domain, str) and domain, (
                f"Collection '{name}' is instanciee:true but has no declared domain. "
                f"Add 'domain: <name>' to the collection definition."
            )
