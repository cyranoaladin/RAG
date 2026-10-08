"""Gardes du wrapper de la release HGGSP complémentaire."""

from __future__ import annotations

import os
import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/go_live/build_profile_gate_successor.sh"
V4 = (
    ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v4"
    / "release-024f8625ebfeb7ce/profile_gate"
)
MAPPING = "services/rag-engine/configs/mappings/eduscol_profile_gate_subjects_hggsp.yml"
MAPPING_SHA = "b909c1fb0a8b874b2bbe53cdb1973d5eadce97823c987f4e2b75fefd0d48bb6a"


def _run(tmp_path: Path, **changes: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        RELEASE_ID="production-profile-gate-2026-2027-v5-hggsp",
        REFERENCE_DIR=str(V4),
        OUTPUT_DIR=str(tmp_path / "release"),
        EVIDENCE_DIR=str(tmp_path / "evidence"),
        PDF_ROOT=str(tmp_path / "pdf"),
        MOTIVE_LABEL="Successeur HGGSP complémentaire",
        MOTIVE_PATHS=MAPPING,
        HGGSP_COMPLEMENTARY="1",
        SUBJECT_MAPPING_PATH=MAPPING,
        SUBJECT_MAPPING_SHA256=MAPPING_SHA,
        PEDAGO_PYTHON="/bin/false",
    )
    env.update(changes)
    return subprocess.run(
        ["bash", str(SCRIPT)], cwd=ROOT, env=env, text=True,
        capture_output=True, check=False,
    )


def test_mapping_successeur_sha_errone_refuse_avant_build(tmp_path: Path) -> None:
    result = _run(tmp_path, SUBJECT_MAPPING_SHA256="0" * 64)
    assert result.returncode != 0
    assert "HGGSP_MAPPING_SHA_MISMATCH" in result.stderr
    assert not (tmp_path / "evidence").exists()


def test_reference_autre_que_v4_refusee_avant_build(tmp_path: Path) -> None:
    result = _run(tmp_path, REFERENCE_DIR=str(ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate"))
    assert result.returncode != 0
    assert "HGGSP_V4_SOURCE_REQUIRED" in result.stderr
    assert not (tmp_path / "evidence").exists()


def test_miroir_incomplet_refuse_avant_build(tmp_path: Path) -> None:
    (tmp_path / "pdf").mkdir()
    result = _run(tmp_path)
    assert result.returncode != 0
    assert "HGGSP_PDF_MISSING" in result.stderr
    assert not (tmp_path / "evidence").exists()


def test_pdf_miroir_avec_mauvaise_empreinte_refuse(tmp_path: Path) -> None:
    subject = json.loads(
        (V4 / "subjects/rag_nexus_hggsp_premiere_specialite.release.json").read_text(encoding="utf-8")
    )
    artifacts = {
        row["artifact_id"]: row
        for row in json.loads((V4 / "artifacts.release.json").read_text(encoding="utf-8"))["artifacts"]
    }
    artifact_id = min(row["artifact_id"] for row in subject["placements"])
    target = tmp_path / "pdf" / artifacts[artifact_id]["source_path"]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"PDF inexact")
    result = _run(tmp_path)
    assert result.returncode != 0
    assert "HGGSP_PDF_SHA_MISMATCH" in result.stderr


def test_identite_v4_refusee_avant_build(tmp_path: Path) -> None:
    result = _run(tmp_path, RELEASE_ID="production-profile-gate-2026-2027-v4")
    assert result.returncode != 0
    assert "HGGSP_RELEASE_ID_REQUIRED" in result.stderr


def test_motif_mapping_absent_refuse_avant_build(tmp_path: Path) -> None:
    result = _run(tmp_path, MOTIVE_PATHS="services/rag-engine/configs/mappings/eduscol_profile_gate_subjects.yml")
    assert result.returncode != 0
    assert "HGGSP_MAPPING_MOTIVE_REQUIRED" in result.stderr


def test_lignee_v4_incorrecte_refusee_avant_build(tmp_path: Path) -> None:
    result = _run(tmp_path, NEXUS_FINAL_SET_SHA256="0" * 64)
    assert result.returncode != 0
    assert "HGGSP_PROFILE_LINEAGE_MISMATCH" in result.stderr


@pytest.mark.parametrize("flag", ["", "0"])
def test_option_hggsp_inactive_garde_la_voie_historique(tmp_path: Path, flag: str) -> None:
    result = _run(tmp_path, HGGSP_COMPLEMENTARY=flag)
    assert "HGGSP_" not in result.stderr
    assert "== 1/4 essai à blanc" in result.stdout


def test_voie_historique_transmet_source_historique_sans_options_hggsp(tmp_path: Path) -> None:
    fake = tmp_path / "python-factice"
    fake.write_text("#!/bin/bash\nprintf 'ARGS=%s\\n' \"$*\"\nexit 41\n", encoding="utf-8")
    fake.chmod(0o755)
    result = _run(tmp_path, HGGSP_COMPLEMENTARY="0", PEDAGO_PYTHON=str(fake))
    assert result.returncode == 41
    assert "--source-release-root services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate" in result.stdout
    assert "--collection " not in result.stdout
    assert "--subject-mapping-path " not in result.stdout


def test_voie_hggsp_validee_transmet_mapping_et_deux_collections(tmp_path: Path) -> None:
    mirror = os.environ.get("NEXUS_HGGSP_TEST_PDF_ROOT")
    if mirror is None:
        pytest.skip("miroir PDF local non fourni")
    fake = tmp_path / "python-factice"
    fake.write_text(
        "#!/bin/bash\nprintf 'ARGS=%s\\n' \"$*\"\n"
        "printf 'PROFILE_ROOT=%s\\n' \"$NEXUS_PROFILE_ROOT\"\n"
        "printf 'PROFILE_MANIFEST=%s\\n' \"$NEXUS_PROFILE_MANIFEST\"\n"
        "printf 'FINAL_SET=%s\\n' \"$NEXUS_FINAL_SET_SHA256\"\n"
        "exit 41\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    result = _run(tmp_path, PDF_ROOT=mirror, PEDAGO_PYTHON=str(fake))
    assert result.returncode == 41, result.stderr
    assert "HGGSP_V4_SOURCE_OK placements=74 artifacts=52 chunks=2590 pdfs=52 disjoint=1" in result.stdout
    assert f"--subject-mapping-path {MAPPING} --subject-mapping-sha256 {MAPPING_SHA}" in result.stdout
    assert "--collection rag_nexus_hggsp_premiere_specialite --collection rag_nexus_hggsp_terminale_specialite" in result.stdout
    assert "--source-release-manifest-sha256 bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be" in result.stdout
    assert "--source-authority-bindings-sha256 60bd9df71425e42a20287a88344f74b330510998c451107094786307855673fe" in result.stdout
    assert "PROFILE_ROOT=services/rag-engine/configs/ingestion_profiles/v3_livraison_315" in result.stdout
    assert "PROFILE_MANIFEST=services/rag-engine/configs/ingestion_profiles/ingestion_manifest_v3_livraison_315.yml" in result.stdout
    assert "FINAL_SET=04b731e20a9ebd9dcd08f00fe516489191690f67ec18e4ba4996a8612961bd12" in result.stdout


def _fake_producer(tmp_path: Path) -> Path:
    fake = tmp_path / "producteur-factice"
    fake.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[2:]
if '--dry-run' in args:
    print('FAKE_DRY_RUN_OK')
    sys.exit(0)
source = Path(os.environ['REFERENCE_DIR'])
out = Path(args[args.index('--output-dir') + 1]) / 'release-factice' / 'profile_gate'
out.mkdir(parents=True)
read = lambda path: json.loads(path.read_text(encoding='utf-8'))
write = lambda path, value: path.write_text(json.dumps(value), encoding='utf-8')
base = read(source / 'production-profile-gate.release.json')
names = {'rag_nexus_hggsp_premiere_specialite', 'rag_nexus_hggsp_terminale_specialite'}
mode = os.environ.get('FAKE_MODE', 'good')
if mode == 'third':
    names.add('rag_nexus_dgemc_terminale_option')
head = dict(base)
head['release_id'] = 'production-profile-gate-2026-2027-v5-hggsp'
head['subjects'] = [row for row in base['subjects'] if row['collection'] in names]
if mode == 'duplicate_subject':
    head['subjects'].append(dict(head['subjects'][0]))
head['expected_counts'] = {'placements': 74, 'subjects': 2, 'unique_artifacts': 52, 'unique_chunks': 2590}
head['authorities'] = dict(base['authorities'])
head['authorities']['subject_mapping_sha256'] = os.environ['SUBJECT_MAPPING_SHA256']
if mode == 'mapping':
    head['authorities']['subject_mapping_sha256'] = '0' * 64
write(out / 'production-profile-gate.release.json', head)
(out / 'subjects').mkdir()
ids = set()
for row in head['subjects']:
    subject = read(source / row['path'])
    if mode == 'missing' and row['collection'] == 'rag_nexus_hggsp_premiere_specialite':
        subject['placements'] = subject['placements'][1:]
    if mode == 'duplicate_placement' and row['collection'] == 'rag_nexus_hggsp_premiere_specialite':
        subject['placements'].append(dict(subject['placements'][0]))
    ids.update(placement['artifact_id'] for placement in subject['placements'])
    write(out / row['path'], subject)
artifacts = read(source / 'artifacts.release.json')
artifacts['artifacts'] = [artifact for artifact in artifacts['artifacts'] if artifact['artifact_id'] in ids]
if mode == 'foreign':
    foreign = next(artifact for artifact in read(source / 'artifacts.release.json')['artifacts'] if artifact['artifact_id'] not in ids)
    artifacts['artifacts'].append(foreign)
if mode == 'duplicate_artifact':
    artifacts['artifacts'].append(dict(artifacts['artifacts'][0]))
if mode == 'chunk':
    artifacts['artifacts'][0]['chunks'][0]['chunk_sha256'] = '0' * 64
write(out / 'artifacts.release.json', artifacts)
print('FAKE_BUILD_OK')
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


@pytest.mark.parametrize(
    ("mode", "refusal"),
    [
        ("third", "HGGSP_PRODUCT_SCOPE_MISMATCH"),
        ("missing", "HGGSP_PRODUCT_PLACEMENTS_MISMATCH"),
        ("foreign", "HGGSP_PRODUCT_ARTIFACTS_MISMATCH"),
        ("chunk", "HGGSP_PRODUCT_CHUNKS_MISMATCH"),
        ("mapping", "HGGSP_PRODUCT_MAPPING_SHA_MISMATCH"),
        ("duplicate_subject", "HGGSP_PRODUCT_SCOPE_MISMATCH"),
        ("duplicate_placement", "HGGSP_PRODUCT_PLACEMENTS_MISMATCH"),
        ("duplicate_artifact", "HGGSP_PRODUCT_ARTIFACTS_MISMATCH"),
    ],
)
def test_produit_complementaire_mutant_refuse(
    tmp_path: Path, mode: str, refusal: str,
) -> None:
    mirror = os.environ.get("NEXUS_HGGSP_TEST_PDF_ROOT")
    if mirror is None:
        pytest.skip("miroir PDF local non fourni")
    fake = _fake_producer(tmp_path)
    result = _run(tmp_path, PDF_ROOT=mirror, PEDAGO_PYTHON=str(fake), FAKE_MODE=mode)
    assert result.returncode != 0
    assert refusal in result.stderr
    assert "== 3/4 diff contre la référence" not in result.stdout


def test_produit_complementaire_exact_passe_controle_counts(tmp_path: Path) -> None:
    mirror = os.environ.get("NEXUS_HGGSP_TEST_PDF_ROOT")
    if mirror is None:
        pytest.skip("miroir PDF local non fourni")
    fake = _fake_producer(tmp_path)
    result = _run(tmp_path, PDF_ROOT=mirror, PEDAGO_PYTHON=str(fake))
    assert "HGGSP_PRODUCT_OK placements=74 artifacts=52 chunks=2590 v4_other_placements=405" in result.stdout, result.stderr
    assert (tmp_path / "evidence/hggsp-complementary-counts.txt").is_file()
