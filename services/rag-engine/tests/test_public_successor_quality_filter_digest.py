"""Le digest HTTP du scope public est celui des prédicats serveur, pas du jeton V3."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from nexus_contracts import RetrievalScopeArtifactV3

from src.ingestor.retrieval_scope_v2 import ServerRetrievalScope

ROOT = Path(__file__).resolve().parents[3]
SUITE = ROOT / "services/rag-engine/tests/fixtures/public_successor_quality_40b.json"


def test_11_public_filter_digests_match_server_projection() -> None:
    suite = json.loads(SUITE.read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / suite["release_manifest_path"]).read_text(encoding="utf-8"))
    subject_shas = {row["collection"]: row["sha256"] for row in manifest["subjects"]}
    policy = yaml.safe_load((ROOT / suite["scope_policy_path"]).read_text(encoding="utf-8"))
    entries = {row["collection"]: row for row in policy["collections"]}
    assert len(entries) == len(subject_shas) == len(suite["collections"]) == 11
    for name, spec in suite["collections"].items():
        entry = entries[name]
        artifact = RetrievalScopeArtifactV3.model_validate({
            "artifact_version": "3", "scope_id": spec["scope_id"],
            "status": "eligible_for_promotion", "source_sha256": subject_shas[name],
            "target_policy": {
                key: entry[key] for key in (
                    "tenant", "niveau", "voie", "matiere", "statut_enseignement",
                )
            } | {
                "audiences": [entry["target_audience"]],
                "candidates": entry["target_candidates"], "roles": ["student"],
            },
            "evidence_subject": {
                key: entry[key] for key in (
                    "collection", "tenant", "niveau", "voie", "matiere",
                    "statut_enseignement", "candidat", "audiences", "rights",
                    "programme_version",
                )
            } | {
                "visibility": entry["policy_visibility"],
                "school_year": policy["school_year"],
            },
        })
        evidence = artifact.evidence_subject
        server = ServerRetrievalScope(
            tenant=evidence.tenant, niveau=evidence.niveau.value,
            voie=evidence.voie.value, matiere=evidence.matiere,
            statut_enseignement=evidence.statut_enseignement.value,
            candidat=evidence.candidat.value, audiences=tuple(evidence.audiences),
            rights=tuple(evidence.rights), visibilities=(evidence.visibility,),
            school_year=evidence.school_year, collection=evidence.collection,
            programme_version=evidence.programme_version, scope_id=artifact.scope_id,
            scope_digest=artifact.sha256_digest(), source_sha256=artifact.source_sha256,
        )
        assert spec["signed_scope_sha256"] == artifact.sha256_digest()
        assert spec["server_filter_sha256"] == server.filter_digest
        assert server.filter_digest != artifact.sha256_digest()
