"""La porte publique recalcule les octets des 253 dérivés avant toute écriture."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRIVATE_CANDIDATES = Path(os.environ.get(
    'NEXUS_PRIVATE_CANDIDATE_ROOT',
    Path.home() / 'nexus-student-text-derivatives-20261010',
))
sys.path.insert(0, str(ROOT / 'scripts/go_live'))
sys.path.insert(0, str(ROOT / 'services/rag-pedago/scripts'))
from build_student_public_successor import build_successor_documents  # noqa: E402
from public_rights_release_guard import (  # noqa: E402
    PublicRightsReleaseError,
    require_public_release_rights,
)


class TestCounter:
    model_id = 'intfloat/multilingual-e5-large'
    model_revision = '3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3'
    max_sequence_length = 512

    def passage_token_count(self, text: str) -> int:
        return len(text.split()) + 2


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def _proofs() -> tuple[dict, dict]:
    evidence = ROOT / 'docs/reports/go_live/student_rights_evidence'
    manifest_raw = (evidence / 'public_derivative_candidate_manifest_20261010.json').read_bytes()
    index_raw = (evidence / 'index.json').read_bytes()
    manifest = json.loads(manifest_raw)
    topology, receipts = {}, {}
    for entry in manifest['entries']:
        sha = entry['derivative_content_sha256']
        topology[sha] = dict(Counter(entry['collections']))
        receipts[sha] = entry['derivative_receipt_sha256']
    return ({'PR300_AUTHORITY_APPROVAL_PASS': True,
             'HEAD_SHA': 'a' * 40,
             'EVIDENCE_PACK_SHA256': _sha(index_raw),
             'CANDIDATE_MANIFEST_SHA256': _sha(manifest_raw)},
            {'DELEGATED_RIGHTS_ADJUDICATION_PASS': True,
             'EVIDENCE_PACK_SHA256': _sha(index_raw),
             'INVENTORY_COUNT': 315, 'FINAL_DECISIONS_COUNT': 315,
             'FULL_DOCUMENT_SCAN_COUNT': 315, 'DUAL_REVIEW_COUNT': 0,
             'CFTR_DISPOSITION': 'EXCLUDE', 'POLICY_FAIL_CLOSED': True,
             'MANUAL_PER_FILE_REVIEW_REQUIRED': False,
             'PENDING_COUNT': 0, 'errors': [],
             'APPROVED_DERIVATIVE_CONTENT_SHA256': sorted(topology),
             'APPROVED_DERIVATIVE_PLACEMENTS': topology,
             'APPROVED_DERIVATIVE_RECEIPT_SHA256': receipts,
             'FINAL_POPULATION': {'artifacts': 253, 'placements': 377,
                                  'collections': 11, 'source_pdfs': 315,
                                  'original_pdf_public_count': 0,
                                  'derivative_segments': 2504}})


@pytest.fixture(scope='module')
def public_candidate(tmp_path_factory: pytest.TempPathFactory):
    if not PRIVATE_CANDIDATES.is_dir():
        pytest.skip('private #300 candidate CAS absent')
    temp = tmp_path_factory.mktemp('public-rights')
    authority, gate = _proofs()
    release_root, private_root = temp / 'release' / 'successor', temp / 'private'
    documents, private = build_successor_documents(
        repository_root=ROOT, private_candidate_root=PRIVATE_CANDIDATES,
        release_root=release_root, private_root=private_root,
        release_id='student-public-20261010-guard-test',
        token_counter=TestCounter(), authority_approval=authority, rights_gate=gate,
    )
    return documents, private, authority, gate


def _check(candidate, *, documents=None, private=None, authority=None, gate=None,
           candidate_root=PRIVATE_CANDIDATES):
    docs, sidecars, approved, rights = candidate
    return require_public_release_rights(
        documents if documents is not None else docs,
        repository_root=ROOT, source_mirror_root=ROOT,
        private_candidate_root=candidate_root,
        private_lineage_documents=private if private is not None else sidecars,
        token_counter=TestCounter(), expected_head='f' * 40,
        gate_runner=lambda **_: gate if gate is not None else rights,
        authority_runner=lambda _: authority if authority is not None else approved,
    )


def _reseal(documents: dict[Path, bytes]) -> None:
    aggregate_path = next(p for p in documents if p.name == 'production-profile-gate.release.json')
    release_root = aggregate_path.parent
    artifact_sha = _sha(documents[release_root / 'artifacts.release.json'])
    aggregate = json.loads(documents[aggregate_path])
    aggregate['artifact_registry']['sha256'] = artifact_sha
    for ref in aggregate['subjects']:
        path = release_root / ref['path']
        subject = json.loads(documents[path])
        subject['artifact_registry']['sha256'] = artifact_sha
        documents[path] = _canonical(subject)
        ref['sha256'] = _sha(documents[path])
    documents[aggregate_path] = _canonical(aggregate)
    registry_path = release_root.parent / 'release-registry.json'
    release_registry = json.loads(documents[registry_path])
    release_registry['releases'][0]['expected_manifest_sha256'] = _sha(documents[aggregate_path])
    documents[registry_path] = _canonical(release_registry)


def test_verified_253_public_derivatives_pass(public_candidate):
    result = _check(public_candidate)
    assert result['PUBLIC_RIGHTS_GATE_PASS'] is True
    assert result['FINAL_POPULATION']['artifacts'] == 253
    assert result['FINAL_POPULATION']['placements'] == 377
    assert result['FINAL_POPULATION']['collections'] == 11
    assert result['FINAL_POPULATION']['chunks'] > 2504


def test_public_candidate_requires_private_cas(public_candidate):
    with pytest.raises(PublicRightsReleaseError, match='PRIVATE_CANDIDATE_ROOT_REQUIRED'):
        _check(public_candidate, candidate_root=None)


def test_public_candidate_requires_exact_authority(public_candidate):
    authority = {**public_candidate[2], 'PR300_AUTHORITY_APPROVAL_PASS': False}
    with pytest.raises(PublicRightsReleaseError, match='AUTHORITY'):
        _check(public_candidate, authority=authority)


def test_public_candidate_refuses_authority_without_approved_head(public_candidate):
    authority = {**public_candidate[2], 'HEAD_SHA': None}
    with pytest.raises(PublicRightsReleaseError, match='AUTHORITY'):
        _check(public_candidate, authority=authority)


@pytest.mark.parametrize('key,bad', [
    ('INVENTORY_COUNT', 314), ('FULL_DOCUMENT_SCAN_COUNT', 314),
    ('CFTR_DISPOSITION', 'APPROVE_PUBLIC'),
    ('POLICY_FAIL_CLOSED', False), ('MANUAL_PER_FILE_REVIEW_REQUIRED', True),
])
def test_cached_gate_requires_complete_source_and_policy_proofs(public_candidate, key, bad):
    gate = {**public_candidate[3], key: bad}
    with pytest.raises(PublicRightsReleaseError, match='DELEGATED_GATE'):
        _check(public_candidate, gate=gate)


@pytest.mark.parametrize('extra_name,raw', [
    ('original.pdf', b'%PDF-1.7'),
    ('unrelated.json', b'{}'),
    ('disguised.txt', b'%PDF-1.7'),
])
def test_public_candidate_refuses_extra_material(public_candidate, extra_name, raw):
    docs = dict(public_candidate[0])
    aggregate_path = next(p for p in docs if p.name == 'production-profile-gate.release.json')
    docs[aggregate_path.parent / extra_name] = raw
    with pytest.raises(PublicRightsReleaseError, match='UNEXPECTED|PDF'):
        _check(public_candidate, documents=docs)


def test_public_candidate_refuses_source_scope_drift_after_reseal(public_candidate):
    docs = dict(public_candidate[0])
    path = next(p for p in docs if 'subjects' in p.parts)
    subject = json.loads(docs[path])
    subject['placements'][0]['source_scope'] = 'forged/public/scope'
    docs[path] = _canonical(subject)
    _reseal(docs)
    with pytest.raises(PublicRightsReleaseError, match='SOURCE|SCOPE'):
        _check(public_candidate, documents=docs)


def test_public_candidate_refuses_resealed_tenant_drift(public_candidate):
    docs = dict(public_candidate[0])
    aggregate_path = next(p for p in docs if p.name == 'production-profile-gate.release.json')
    release_root = aggregate_path.parent
    subject_path = next(p for p in docs if 'subjects' in p.parts)
    subject = json.loads(docs[subject_path])
    collection = subject['collection']
    profiles_path = release_root / 'public_profiles.json'
    profiles = json.loads(docs[profiles_path])
    profile = next(row for row in profiles['entries'] if row['collection'] == collection)
    profile['scope']['tenant'] = 'forged_terminale'
    profile['profile_fingerprint'] = _sha(_canonical(profile['scope']))
    docs[profiles_path] = _canonical(profiles)
    profile_sha = _sha(docs[profiles_path])
    for path in [p for p in docs if 'subjects' in p.parts]:
        row = json.loads(docs[path])
        row['authorities']['public_profile_registry_sha256'] = profile_sha
        row['profile']['manifest_digest'] = profile_sha
        if path == subject_path:
            row['profile']['fingerprint'] = profile['profile_fingerprint']
            for placement in row['placements']:
                placement['tenant'] = 'forged_terminale'
                placement.pop('placement_id')
                placement['placement_id'] = _sha(_canonical(placement))
        docs[path] = _canonical(row)
    aggregate = json.loads(docs[aggregate_path])
    aggregate['authorities']['public_profile_registry_sha256'] = profile_sha
    docs[aggregate_path] = _canonical(aggregate)
    _reseal(docs)
    with pytest.raises(PublicRightsReleaseError, match='SOURCE|SCOPE'):
        _check(public_candidate, documents=docs)


def test_public_candidate_refuses_identity_roles_as_pedagogical_audience(public_candidate):
    docs = dict(public_candidate[0])
    aggregate_path = next(p for p in docs if p.name == 'production-profile-gate.release.json')
    release_root = aggregate_path.parent
    profiles_path = release_root / 'public_profiles.json'
    profiles = json.loads(docs[profiles_path])
    for profile in profiles['entries']:
        profile['scope']['audience'] = ['student', 'teacher']
        profile['profile_fingerprint'] = _sha(_canonical(profile['scope']))
    docs[profiles_path] = _canonical(profiles)
    profile_sha = _sha(docs[profiles_path])
    for path in [p for p in docs if 'subjects' in p.parts]:
        row = json.loads(docs[path])
        profile = next(entry for entry in profiles['entries']
                       if entry['collection'] == row['collection'])
        row['authorities']['public_profile_registry_sha256'] = profile_sha
        row['profile']['manifest_digest'] = profile_sha
        row['profile']['fingerprint'] = profile['profile_fingerprint']
        docs[path] = _canonical(row)
    aggregate = json.loads(docs[aggregate_path])
    aggregate['authorities']['public_profile_registry_sha256'] = profile_sha
    docs[aggregate_path] = _canonical(aggregate)
    _reseal(docs)
    with pytest.raises(PublicRightsReleaseError, match='AUDIENCE|SOURCE|SCOPE|PROFILE'):
        _check(public_candidate, documents=docs)


def test_public_candidate_refuses_pending_delegated_decision(public_candidate):
    gate = {**public_candidate[3], 'PENDING_COUNT': 1}
    with pytest.raises(PublicRightsReleaseError, match='DELEGATED_GATE'):
        _check(public_candidate, gate=gate)


def test_public_candidate_requires_all_253_approved_shas(public_candidate):
    gate = copy.deepcopy(public_candidate[3])
    gate['APPROVED_DERIVATIVE_CONTENT_SHA256'].pop()
    with pytest.raises(PublicRightsReleaseError, match='APPROVED|CONTENT_SET'):
        _check(public_candidate, gate=gate)


def test_public_candidate_requires_exact_receipt_binding(public_candidate):
    gate = copy.deepcopy(public_candidate[3])
    sha = gate['APPROVED_DERIVATIVE_CONTENT_SHA256'][0]
    gate['APPROVED_DERIVATIVE_RECEIPT_SHA256'][sha] = '0' * 64
    with pytest.raises(PublicRightsReleaseError, match='RECEIPT'):
        _check(public_candidate, gate=gate)


def test_signed_manifest_supplies_bindings_when_clean_gate_has_no_projection(public_candidate):
    gate = copy.deepcopy(public_candidate[3])
    gate.pop('APPROVED_DERIVATIVE_PLACEMENTS')
    gate.pop('APPROVED_DERIVATIVE_RECEIPT_SHA256')
    gate['APPROVED_CONTENT_SHA256'] = gate.pop('APPROVED_DERIVATIVE_CONTENT_SHA256')
    result = _check(public_candidate, gate=gate)
    assert result['PUBLIC_RIGHTS_GATE_PASS'] is True


def test_public_candidate_refuses_changed_private_lineage(public_candidate):
    private = dict(public_candidate[1])
    path = next(p for p in private if 'chunk_lineage' in p.parts)
    lineage = json.loads(private[path])
    lineage['chunks'][0]['text'] = 'texte falsifié'
    private[path] = _canonical(lineage)
    with pytest.raises(PublicRightsReleaseError, match='LINEAGE'):
        _check(public_candidate, private=private)


def test_public_candidate_refuses_forged_chunk_after_reseal(public_candidate):
    docs = dict(public_candidate[0])
    path = next(p for p in docs if p.name == 'artifacts.release.json')
    registry = json.loads(docs[path])
    registry['artifacts'][0]['chunks'][0]['page_start'] += 1
    docs[path] = _canonical(registry)
    _reseal(docs)
    with pytest.raises(PublicRightsReleaseError, match='CHUNK|LINEAGE'):
        _check(public_candidate, documents=docs)


def test_public_candidate_refuses_pdf_media_type(public_candidate):
    docs = dict(public_candidate[0])
    path = next(p for p in docs if p.name == 'artifacts.release.json')
    registry = json.loads(docs[path])
    registry['artifacts'][0]['media_type'] = 'application/pdf'
    docs[path] = _canonical(registry)
    _reseal(docs)
    with pytest.raises(PublicRightsReleaseError, match='PDF|MEDIA|DERIVATIVE'):
        _check(public_candidate, documents=docs)


def test_public_candidate_refuses_mixed_visibility(public_candidate):
    docs = dict(public_candidate[0])
    path = next(p for p in docs if 'subjects' in p.parts)
    subject = json.loads(docs[path])
    subject['placements'][0]['visibility'] = 'internal'
    docs[path] = _canonical(subject)
    _reseal(docs)
    with pytest.raises(PublicRightsReleaseError, match='MIXED'):
        _check(public_candidate, documents=docs)


def test_public_candidate_refuses_empty_collection(public_candidate):
    docs = dict(public_candidate[0])
    path = next(p for p in docs if 'subjects' in p.parts)
    subject = json.loads(docs[path])
    subject['placements'] = []
    docs[path] = _canonical(subject)
    _reseal(docs)
    with pytest.raises(PublicRightsReleaseError, match='EMPTY|PLACEMENT|TOPOLOGY'):
        _check(public_candidate, documents=docs)


def test_public_candidate_refuses_historical_release_id(public_candidate):
    docs = dict(public_candidate[0])
    path = next(p for p in docs if p.name == 'production-profile-gate.release.json')
    aggregate = json.loads(docs[path])
    aggregate['release_id'] = 'production-profile-gate-2026-2027-v4'
    docs[path] = _canonical(aggregate)
    _reseal(docs)
    with pytest.raises(PublicRightsReleaseError, match='HISTORICAL'):
        _check(public_candidate, documents=docs)


@pytest.mark.parametrize('name', ['public_profiles.json',
                                  'public_rights_registry.json',
                                  'public_pii_registry.json'])
def test_public_candidate_refuses_changed_candidate_registry(public_candidate, name):
    docs = dict(public_candidate[0])
    path = next(p for p in docs if p.name == name)
    registry = json.loads(docs[path])
    registry['status'] = 'AUTHORIZED'
    docs[path] = _canonical(registry)
    with pytest.raises(PublicRightsReleaseError, match='REGISTRY'):
        _check(public_candidate, documents=docs)


def test_candidate_registry_cannot_smuggle_publication_authorization(public_candidate):
    docs = dict(public_candidate[0])
    path = next(p for p in docs if p.name == 'public_rights_registry.json')
    rights = json.loads(docs[path])
    rights['publication_authorized'] = True
    docs[path] = _canonical(rights)
    aggregate_path = next(p for p in docs if p.name == 'production-profile-gate.release.json')
    aggregate = json.loads(docs[aggregate_path])
    aggregate['authorities']['public_rights_registry_sha256'] = _sha(docs[path])
    docs[aggregate_path] = _canonical(aggregate)
    for subject_path in [p for p in docs if 'subjects' in p.parts]:
        subject = json.loads(docs[subject_path])
        subject['authorities']['public_rights_registry_sha256'] = _sha(docs[path])
        docs[subject_path] = _canonical(subject)
    _reseal(docs)
    with pytest.raises(PublicRightsReleaseError, match='REGISTRY'):
        _check(public_candidate, documents=docs)
