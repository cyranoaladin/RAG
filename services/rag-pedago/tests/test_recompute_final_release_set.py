from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_ROOT.parents[1]
SCRIPT = SERVICE_ROOT / "scripts" / "recompute_final_release_set.py"
SEALED_ROOT = Path(
    os.environ.get(
        "NEXUS_SEALED_CORPUS_ROOT",
        Path.home() / "Téléchargements" / "NEXUS_RAG_GDRIVE_READY",
    )
)
EVIDENCE_ROOT = Path(
    os.environ.get(
        "NEXUS_H2_EVIDENCE_ROOT",
        Path.home() / "Documents" / "NEXUS_RAG_H2_EVIDENCE",
    )
)
REAL_INPUTS = {
    "manifest": SEALED_ROOT / "00_ADMIN" / "SHA256SUMS.txt",
    "placements": SEALED_ROOT / "00_ADMIN" / "eduscol_affectations.tsv",
    "pii_exhaustive": EVIDENCE_ROOT / "h2b_exhaustive_pii_scan_20260813.jsonl",
    "pii_campaign": EVIDENCE_ROOT / "h2b_pii_evidence_20260808.json",
}
VERSIONED_INPUTS = {
    "routing": SERVICE_ROOT / "configs/corpus_zone_routing.yml",
    "rights": SERVICE_ROOT / "configs/rights_evidence_registry.yml",
    "golden": SERVICE_ROOT / "configs/golden_corpus_h2b.yml",
    "currentness": (
        SERVICE_ROOT / "configs/prerentree_2026_2027/multilevel_currentness_evidence.yml"
    ),
    "production_profile_set": (
        REPO_ROOT / "docs/reports/final_production_eligible_set_20260825.txt"
    ),
}
EXPECTED_REAL_INPUT_DIGESTS = {
    "manifest": "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e",
    "placements": "25cf40cec8a98692d4532a71b58a9685821bbc2b9a4785c25fac7138a49906ec",
    "pii_exhaustive": "0229a0f2d7edbd1bb1b1412a8ccd447b3c6d2ce71dc73a0f2e726751156fa357",
    "pii_campaign": "76e6ba3cd5b1c116c8647b611eb3fdeb2aba6b8c7fdfbad9e71048354956f311",
    "routing": "0d4d25215cb0ed40c439ff172c9dbce3f2a1b0b945313a042285b2e57bffc833",
    "rights": "e3c9a157f1f78171c0052750fa08b7726b99ea4dd348728f1b90db07f93ef1ff",
    "golden": "28856e0655eca7695f273a5934925785c49ecf828d930804984f6e58f4da6f69",
    "currentness": "2ad7209f28cd7cbf9f1ea91724b687983579c36c91619e8d107d28b72b849122",
    "production_profile_set": (
        "fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0"
    ),
}

SHA_A = "a" * 64
SHA_B = "b" * 64


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("recompute_final_release_set", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _physical(
    sha256: str,
    *,
    disposition: str,
    base_disposition: str,
    path: str,
) -> dict[str, object]:
    return {
        "content_sha256": sha256,
        "disposition": disposition,
        "base_disposition": base_disposition,
        "path": path,
    }


def test_required_content_with_conflicting_final_dispositions_is_refused() -> None:
    module = _load_script()
    physical = [
        _physical(
            SHA_A,
            disposition="INGEST",
            base_disposition="INGEST",
            path="a.pdf",
        ),
        _physical(
            SHA_A,
            disposition="REVIEW_REQUIRED",
            base_disposition="INGEST",
            path="alias-a.pdf",
        ),
    ]

    with pytest.raises(ValueError, match="authority-required.*final dispositions"):
        module._terminal_accounting(physical, frozenset({SHA_A}))


def test_required_content_with_conflicting_base_dispositions_is_refused() -> None:
    module = _load_script()
    physical = [
        _physical(
            SHA_A,
            disposition="INGEST",
            base_disposition="INGEST",
            path="a.pdf",
        ),
        _physical(
            SHA_A,
            disposition="INGEST",
            base_disposition="REVIEW_REQUIRED",
            path="alias-a.pdf",
        ),
    ]

    with pytest.raises(ValueError, match="authority-required.*base dispositions"):
        module._terminal_accounting(physical, frozenset({SHA_A}))


def test_non_required_conflict_is_terminal_review_and_does_not_mutate_input() -> None:
    module = _load_script()
    physical = [
        _physical(
            SHA_A,
            disposition="EXCLUDE",
            base_disposition="EXCLUDE",
            path="a.pdf",
        ),
        _physical(
            SHA_A,
            disposition="REVIEW_REQUIRED",
            base_disposition="REVIEW_REQUIRED",
            path="alias-a.pdf",
        ),
    ]
    before = copy.deepcopy(physical)

    rows, conflicts = module._terminal_accounting(physical, frozenset())

    assert physical == before
    assert rows == [
        {
            "base_dispositions": ["EXCLUDE", "REVIEW_REQUIRED"],
            "canonical_disposition": "REVIEW_REQUIRED",
            "content_sha256": SHA_A,
            "paths": ["a.pdf", "alias-a.pdf"],
            "release_terminal_disposition": "REVIEW_REQUIRED",
        }
    ]
    assert conflicts == [
        {
            "base_dispositions": ["EXCLUDE", "REVIEW_REQUIRED"],
            "content_sha256": SHA_A,
            "dispositions": ["EXCLUDE", "REVIEW_REQUIRED"],
        }
    ]


def test_exact_set_and_accounting_are_deterministic() -> None:
    module = _load_script()
    first_input = [
        _physical(
            SHA_B,
            disposition="REVIEW_REQUIRED",
            base_disposition="REVIEW_REQUIRED",
            path="b.pdf",
        ),
        _physical(
            SHA_A,
            disposition="INGEST",
            base_disposition="INGEST",
            path="a.pdf",
        ),
    ]
    second_input = list(reversed(copy.deepcopy(first_input)))
    required = frozenset({SHA_B, SHA_A})

    first_bytes = module._canonical_sha_set_bytes(required)
    second_bytes = module._canonical_sha_set_bytes(frozenset(reversed(tuple(required))))
    first_rows = module._terminal_accounting(first_input, required)
    second_rows = module._terminal_accounting(second_input, required)

    assert first_bytes == second_bytes == f"{SHA_A}\n{SHA_B}\n".encode("ascii")
    assert hashlib.sha256(first_bytes).hexdigest() == module.h2b.authority_required_set_digest(
        required
    )
    assert first_rows == second_rows


def test_profile_gate_moves_preprofile_residuals_to_review_required() -> None:
    module = _load_script()
    physical = [
        _physical(
            SHA_A,
            disposition="INGEST",
            base_disposition="INGEST",
            path="a.pdf",
        ),
        _physical(
            SHA_B,
            disposition="INGEST",
            base_disposition="INGEST",
            path="b.pdf",
        ),
    ]

    rows, conflicts = module._terminal_accounting(
        physical,
        frozenset({SHA_A}),
        profile_review_required=frozenset({SHA_B}),
    )

    assert conflicts == []
    assert [row["release_terminal_disposition"] for row in rows] == [
        "INGEST_CANDIDATE",
        "REVIEW_REQUIRED",
    ]


def test_profile_gate_must_partition_preprofile_authority_set() -> None:
    module = _load_script()

    with pytest.raises(ValueError, match="partition"):
        module._validate_profile_gate_partition(
            pre_profile_set=frozenset({SHA_A, SHA_B}),
            final_profile_set=frozenset({SHA_A}),
            profile_review_required=frozenset(),
        )


def test_versioned_ledger_recomputes_final_profile_gate_accounting(tmp_path: Path) -> None:
    module = _load_script()
    output = tmp_path / "terminal-disposition-summary.json"

    summary = module.recompute_profile_gate_terminal_summary(
        content_ledger=(
            REPO_ROOT / "docs/reports/evidence-index/content_ledger_20260814.jsonl"
        ),
        pre_profile_set=(
            REPO_ROOT / "docs/reports/final_authority_required_set_20260823.txt"
        ),
        production_profile_set=(
            REPO_ROOT / "docs/reports/final_production_eligible_set_20260825.txt"
        ),
        output=output,
    )

    assert json.loads(output.read_text(encoding="utf-8")) == summary
    assert summary["FINAL_PRE_PROFILE_ELIGIBLE_COUNT"] == 72
    assert summary["FINAL_PRODUCTION_ELIGIBLE_COUNT"] == 26
    assert summary["FINAL_PROFILE_REVIEW_REQUIRED_COUNT"] == 46
    assert summary["FINAL_AUTHORITY_REQUIRED_COUNT"] == 26
    assert summary["FINAL_AUTHORITY_REQUIRED_SET_SHA256"] == (
        "fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0"
    )
    assert summary["terminal_disposition_counts"] == {
        "ARCHIVE_ONLY": 19,
        "EXCLUDE": 53,
        "INGEST_CANDIDATE": 26,
        "QUARANTINE": 2,
        "REVIEW_REQUIRED": 2445,
        "UNSUPPORTED": 37,
    }
    assert len(summary["profile_review_required_content_sha256"]) == 46
    resolution = json.loads(
        (
            REPO_ROOT / "docs/reports/production_profile_resolution_records_20260825.json"
        ).read_text(encoding="utf-8")
    )
    assert set(summary["profile_review_required_content_sha256"]) == {
        row["content_sha256"]
        for row in resolution["records"]
        if row["resolution_status"] != "EXACTLY_GROUNDED"
    }
    assert summary["UNIQUE_CONTENTS"] == 2582
    assert summary["UNACCOUNTED_CONTENTS"] == 0
    assert summary["TERMINAL_DISPOSITION_COVERAGE"] == 100.0


def test_parser_uses_portable_evidence_root_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_script()
    sealed = tmp_path / "sealed"
    evidence = tmp_path / "evidence"
    monkeypatch.setenv("NEXUS_SEALED_CORPUS_ROOT", str(sealed))
    monkeypatch.setenv("NEXUS_H2_EVIDENCE_ROOT", str(evidence))

    args = module._parser().parse_args(["--output-dir", str(tmp_path / "out")])

    assert args.manifest == sealed / "00_ADMIN/SHA256SUMS.txt"
    assert args.placements == sealed / "00_ADMIN/eduscol_affectations.tsv"
    assert args.pii_exhaustive == evidence / "h2b_exhaustive_pii_scan_20260813.jsonl"
    assert args.pii_campaign == evidence / "h2b_pii_evidence_20260808.json"
    assert args.production_profile_set == (
        REPO_ROOT / "docs/reports/final_production_eligible_set_20260825.txt"
    )


@pytest.mark.skipif(
    not all(path.is_file() for path in REAL_INPUTS.values()),
    reason="les preuves scellées externes ne sont pas disponibles",
)
def test_recompute_final_release_set_from_real_inputs(tmp_path: Path) -> None:
    output = tmp_path / "release-recalculation"
    command = [
        sys.executable,
        str(SCRIPT),
        "--manifest",
        str(REAL_INPUTS["manifest"]),
        "--placements",
        str(REAL_INPUTS["placements"]),
        "--pii-exhaustive",
        str(REAL_INPUTS["pii_exhaustive"]),
        "--pii-campaign",
        str(REAL_INPUTS["pii_campaign"]),
        "--output-dir",
        str(output),
    ]

    subprocess.run(command, cwd=SERVICE_ROOT, check=True)

    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    exact_set = (output / "final_authority_required_set.txt").read_bytes()
    expected_set = (
        REPO_ROOT / "docs/reports/final_production_eligible_set_20260825.txt"
    ).read_bytes()
    terminal_rows = (
        (output / "terminal_content_dispositions.jsonl").read_text(encoding="utf-8").splitlines()
    )

    for label, path in {**REAL_INPUTS, **VERSIONED_INPUTS}.items():
        assert summary["input_digests"][str(path)] == EXPECTED_REAL_INPUT_DIGESTS[label]

    assert summary["final_base_ingest_candidates"] == 73
    assert summary["final_non_authority_blocked_count"] == 1
    assert summary["final_pre_profile_eligible_count"] == 72
    assert summary["final_pre_profile_eligible_set_sha256"] == (
        "3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0"
    )
    assert summary["final_profile_review_required_count"] == 46
    assert summary["final_authority_required_count"] == 26
    assert summary["final_authority_required_set_sha256"] == (
        "fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0"
    )
    assert exact_set == expected_set
    assert exact_set.endswith(b"\n")
    assert len(exact_set.splitlines()) == 26
    assert hashlib.sha256(exact_set).hexdigest() == summary["final_authority_required_set_sha256"]
    assert len(terminal_rows) == 2582
    assert summary["terminal_content_accounting"]["unaccounted_contents"] == 0
    assert summary["terminal_content_accounting"]["unexpected_contents"] == 0
    assert summary["terminal_content_accounting"]["coverage_percent"] == 100.0
    assert summary["terminal_content_accounting"]["release_terminal_disposition_counts"] == {
        "ARCHIVE_ONLY": 19,
        "EXCLUDE": 53,
        "INGEST_CANDIDATE": 26,
        "QUARANTINE": 2,
        "REVIEW_REQUIRED": 2445,
        "UNSUPPORTED": 37,
    }


class TestFormatEnsembleDeSha:
    """Le fichier V2 porte un SHA par artefact global, jamais par placement."""

    @staticmethod
    def _ecrire(chemin: Path, lignes: list[str]) -> Path:
        chemin.write_bytes(("".join(f"{v}\n" for v in lignes)).encode("ascii"))
        return chemin

    def test_un_contenu_multi_place_ne_peut_pas_etre_repete_dans_le_set_v2(
        self, tmp_path: Path
    ) -> None:
        """Les placements multiples vivent dans les sujets, pas dans ce fichier."""
        module = _load_script()
        a, b = "a" * 64, "b" * 64
        fichier = self._ecrire(tmp_path / "placements.txt", [a, a, b])

        with pytest.raises(ValueError, match="duplicate SHA-256"):
            module._load_canonical_sha_set(fichier)

    def test_v2_refuse_un_sha_de_contenu_duplique(self, tmp_path: Path) -> None:
        """Le jeu final V2 porte un SHA par artefact global, jamais par placement."""
        module = _load_script()
        sha = "a" * 64
        fichier = self._ecrire(tmp_path / "contenus-v2.txt", [sha, sha])

        with pytest.raises(ValueError, match="duplicate SHA-256"):
            module._load_canonical_sha_set(fichier)

    def test_le_fichier_historique_par_placement_est_mesure_et_refuse_en_v2(
        self,
    ) -> None:
        """Le témoin actuel reste 486/319, mais n'est pas un set V2 canonique."""
        module = _load_script()
        chemin = REPO_ROOT / "docs/reports/final_production_eligible_set_20260825.txt"
        lignes = chemin.read_text(encoding="ascii").splitlines()

        assert len(lignes) == 486
        assert len(set(lignes)) == 319
        with pytest.raises(ValueError, match="duplicate SHA-256"):
            module._load_canonical_sha_set(chemin)

    def test_un_fichier_non_trie_est_toujours_refuse(self, tmp_path: Path) -> None:
        module = _load_script()
        fichier = self._ecrire(tmp_path / "desordre.txt", ["b" * 64, "a" * 64])

        with pytest.raises(ValueError, match="must be sorted"):
            module._load_canonical_sha_set(fichier)

    def test_une_serialisation_non_canonique_est_toujours_refusee(
        self, tmp_path: Path
    ) -> None:
        module = _load_script()
        fichier = tmp_path / "sans-fin-de-ligne.txt"
        fichier.write_bytes(("a" * 64).encode("ascii"))

        with pytest.raises(ValueError, match="non-canonical"):
            module._load_canonical_sha_set(fichier)

    def test_un_sha_invalide_est_toujours_refuse(self, tmp_path: Path) -> None:
        module = _load_script()
        fichier = self._ecrire(tmp_path / "invalide.txt", ["z" * 64])

        with pytest.raises(ValueError, match="invalid SHA-256"):
            module._load_canonical_sha_set(fichier)
