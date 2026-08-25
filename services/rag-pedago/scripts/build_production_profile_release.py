#!/usr/bin/env python3
"""Construire la release production exacte issue du gate de profils 2026-2027."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

import yaml
from pypdf import PdfReader

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
for source_root in (
    REPOSITORY_ROOT / "services/rag-engine/src",
    REPOSITORY_ROOT / "packages/contracts/src",
    REPOSITORY_ROOT / "services/rag-pedago",
):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from ingestor.collection_config import load_collection_config  # noqa: E402
from ingestor.ingestion_profiles.manifest import verify_profile_manifest  # noqa: E402
from ingestor.ingestion_profiles.registry import (  # noqa: E402
    load_profile_registry,
    profile_fingerprint,
)
from ingestor.publication_chunking import chunk_publication  # noqa: E402
from nexus_contracts.embedding_utils import format_passage  # noqa: E402

from rag_pedago.imports.pii_scanner import (  # noqa: E402
    load_patterns_from_config,
    scan_pdf,
)

SCHOOL_YEAR = "2026-2027"
RELEASE_ID = "production-profile-gate-2026-2027-v1"
FINAL_SET_SHA256 = "fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0"
CORPUS_MANIFEST_AUTHORITY = (
    "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
)
CANONICAL_EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
CANONICAL_EMBEDDING_REVISION = "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"
CANONICAL_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
CANONICAL_RERANKER_REVISION = "c5ee24cb16019beea0893ab7796b1df96625c6b8"
TARGET_TOKENS = 384

RELEASE_ROOT = (
    REPOSITORY_ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate"
)
FINAL_MATRIX_PATH = REPOSITORY_ROOT / "docs/reports/final_production_profile_matrix_20260825.json"
FINAL_PRODUCTION_SET_PATH = (
    REPOSITORY_ROOT / "docs/reports/final_production_eligible_set_20260825.txt"
)
ACCEPTED_PLACEMENTS_PATH = (
    REPOSITORY_ROOT
    / "docs/reports/production_profile_accepted_placements_20260825.json"
)
VERIFIED_PROFILES_PATH = (
    REPOSITORY_ROOT / "docs/reports/verified_production_profiles_20260825.json"
)
PRIMARY_EVIDENCE_PATH = REPOSITORY_ROOT / "docs/reports/production_profile_primary_evidence_20260825.json"
DRIVE_MAPPING_PATH = (
    REPOSITORY_ROOT
    / "docs/reports/evidence-index/drive-snapshot/drive_snapshot_mapping_20260815.json"
)
CONTENT_LEDGER_PATH = (
    REPOSITORY_ROOT / "docs/reports/evidence-index/content_ledger_20260814.jsonl"
)
PLACEMENT_LEDGER_PATH = (
    REPOSITORY_ROOT / "docs/reports/evidence-index/placement_ledger_20260814.jsonl"
)
OLD_RELEASE_ROOT = (
    REPOSITORY_ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027/multilevel"
)
P24_POLICY_PATH = REPOSITORY_ROOT / "services/rag-engine/configs/h2_initial_placement_policy.yml"
PROFILE_ROOT = REPOSITORY_ROOT / "services/rag-engine/configs/ingestion_profiles"
PROFILE_MANIFEST_PATH = REPOSITORY_ROOT / "services/rag-engine/configs/ingestion_manifest.yml"
COLLECTION_CONFIG_PATH = REPOSITORY_ROOT / "services/rag-engine/configs/rag_collections.yml"
PII_POLICY_PATH = REPOSITORY_ROOT / "services/rag-pedago/configs/pii_gate_policy.yml"
PII_SCANNER_PATH = REPOSITORY_ROOT / "services/rag-pedago/rag_pedago/imports/pii_scanner.py"
RIGHTS_REGISTRY_PATH = (
    REPOSITORY_ROOT / "services/rag-pedago/configs/rights_evidence_registry.yml"
)
LEVEL_MAPPING_PATH = (
    REPOSITORY_ROOT / "services/rag-engine/configs/mappings/eduscol_multilevel_levels.yml"
)
SUBJECT_MAPPING_PATH = (
    REPOSITORY_ROOT / "services/rag-engine/configs/mappings/eduscol_profile_gate_subjects.yml"
)
DOCUMENT_TYPE_MAPPING_PATH = (
    REPOSITORY_ROOT
    / "services/rag-engine/configs/mappings/eduscol_multilevel_document_types.yml"
)
DGEMC_INDEX_PATH = (
    RELEASE_ROOT / "programmes/dgemc_terminale_option.index.yml"
)

PROGRAMME_INDEX_PATHS = (
    "corpus/College/Quatrieme/_index.yml",
    "corpus/Lycee/Seconde/_index.yml",
    "corpus/Lycee/Premiere/Specialites/_index.yml",
    "corpus/Lycee/Premiere/Tronc_commun/_index.yml",
    "corpus/Lycee/Terminale/Specialites/_index.yml",
    "corpus/Lycee/Terminale/Tronc_commun/_index.yml",
    "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/programmes/dgemc_terminale_option.index.yml",
)

OFFICIAL_DOWNLOAD_URLS = {
    "03f268dc1f2628dbc76c58921ed868624437f06a15432ea055fff844f12aaf91": "https://eduscol.education.gouv.fr/sites/default/files/document/ra20lyceegtterphiloevaluations1318475pdf-83655.pdf",
    "06e491d369c5164d9f746176edeef45363cef53d3de2d5fb55153e6e96f98f2e": "https://eduscol.education.gouv.fr/sites/default/files/document/spe639annexe1063544pdf-82752.pdf",
    "2f1035c74db485d12e80d7c887cb9090807be32e5f79a6074d2decb1073ec154": "https://eduscol.education.gouv.fr/sites/default/files/document/spe253annexe1158821pdf-82755.pdf",
    "4433fee96b6e803c71edf2764d99bd269e649dcff646aee97327fdfeed143f13": "https://eduscol.education.gouv.fr/sites/default/files/document/ra19lyceeg1-thlpexemple-sujet-commentesujet-zero21205357pdf-83931.pdf",
    "60eeb7dd1ee55d1ed2bb2c7671ecf3c971aeef6996db2bc7cd9c7919ae4b19ac": "https://eduscol.education.gouv.fr/sites/default/files/document/ra19lyceeg1-t-hlplitterature-apprentissage-oral-etude-textes1219746pdf-83940.pdf",
    "64f5b3427dee3b23d421fe03cb2f3aac75e0e47cee31be91b197d4e09c012987": "https://eduscol.education.gouv.fr/sites/default/files/document/ra19lyceeg1-t-hlpphilosophie-apprentissage-oral-etude-textes1219750pdf-83943.pdf",
    "846962c15217af5cfe7ba40b173e94cb225d2153ffd3131d23b2c60a2b5e9a17": "https://eduscol.education.gouv.fr/sites/default/files/document/ra20lyceegtterphiloexercices21307357pdf-83652.pdf",
    "8eb0e41f95bf4aca37e6231c06109579faf6bf410d6bd2bc210574e66e2762fa": "https://eduscol.education.gouv.fr/sites/default/files/document/spe648annexe1063542pdf-82878.pdf",
    "9357dfdebca347264787dfebacb674666d87660b82f789657ddd230c7ff224aa": "https://eduscol.education.gouv.fr/sites/default/files/document/ra19lyceeg1-thlpexemple-sujet-commentesujet-zero31205359pdf-83934.pdf",
    "b5ed52b1a4754298f7ecdbc56cb886a438c580ebd04284be0ca878b82e7c62db": "https://eduscol.education.gouv.fr/sites/default/files/document/ra21lyceegtterphilorecommandations2-73131.pdf",
    "d2cbd06f2e8099d9080f17f3abb5b0fc90460b86b3c11f808b99daa01f77f897": "https://eduscol.education.gouv.fr/sites/default/files/document/spe252annexe1159114pdf-82881.pdf",
    "db43d342edf55e162d0153028b43287e4ece0ce81b4dc75f0730bf368b98c0f0": "https://eduscol.education.gouv.fr/sites/default/files/document/spe635annexe1063432pdf-82266.pdf",
    "e591a87aee633ca3b2593e2d4fd5b183e518ebe0f9d4861e4cdfe0f494f39439": "https://eduscol.education.gouv.fr/sites/default/files/document/annexeprogrammedgemcmodifiepdf-84138.pdf",
    "e7cf3bdb7a1c3831ccc465d842d8ab0dacb688d565cb35510aee4eac4f2bf5f9": "https://eduscol.education.gouv.fr/sites/default/files/document/ra20lyceegtterphiloetudestextes1294343pdf-83649.pdf",
    "f0dec90cafd512cb754fb71ed33dbf0a48f0e67a166be35b5b16a1daa6dd006d": "https://eduscol.education.gouv.fr/sites/default/files/document/ra20lyceegtterphilonotionsauteursreperes1304038pdf-83646.pdf",
}

MATHEMATICS_LISTING_URL = (
    "https://eduscol.education.gouv.fr/5817/"
    "programmes-et-ressources-en-mathematiques-voie-gt"
)


class CanonicalTokenCounter(Protocol):
    model_id: str
    model_revision: str
    max_sequence_length: int

    def passage_token_count(self, text: str) -> int: ...


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _compact_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _set_digest(values: Sequence[object]) -> str:
    if len(values) != len({json.dumps(value, sort_keys=True) for value in values}):
        raise ValueError("set digest input contains duplicate values")
    encoded = json.dumps(
        sorted(values, key=lambda item: json.dumps(item, sort_keys=True)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _final_set_digest(values: Sequence[str]) -> str:
    return _sha256_bytes(("\n".join(sorted(values)) + "\n").encode())


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _repo_relative(path: Path) -> str:
    return path.resolve().relative_to(REPOSITORY_ROOT.resolve()).as_posix()


def validate_pdf_mirror(
    *, pdf_root: Path, content_sha256: list[str]
) -> dict[str, Path]:
    if len(content_sha256) != len(set(content_sha256)):
        raise ValueError("PDF mirror request contains duplicate content")
    resolved: dict[str, Path] = {}
    root = pdf_root.resolve()
    for content_sha in sorted(content_sha256):
        path = (root / f"{content_sha}.pdf").resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"PDF mirror is missing content {content_sha}")
        if _file_sha256(path) != content_sha:
            raise ValueError(f"PDF mirror digest differs for {content_sha}")
        resolved[content_sha] = path
    return resolved


def stable_release_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = [(row.get("collection"), row.get("content_sha256")) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("release contains duplicate collection/content")
    content = [row.get("content_sha256") for row in rows]
    if len(content) != len(set(content)):
        raise ValueError("release contains duplicate content")
    return sorted(rows, key=lambda row: (row["collection"], row["content_sha256"]))


def require_canonical_token_counter(token_counter: object) -> None:
    if getattr(token_counter, "model_id", None) != CANONICAL_EMBEDDING_MODEL:
        raise ValueError("token counter model identity differs")
    if getattr(token_counter, "model_revision", None) != CANONICAL_EMBEDDING_REVISION:
        raise ValueError("token counter model revision differs")
    if getattr(token_counter, "max_sequence_length", 0) < TARGET_TOKENS:
        raise ValueError("token counter sequence length is too small")
    if not callable(getattr(token_counter, "passage_token_count", None)):
        raise ValueError("token counter is unavailable")


class E5TokenCounter:
    model_id = CANONICAL_EMBEDDING_MODEL
    model_revision = CANONICAL_EMBEDDING_REVISION

    def __init__(self, snapshot: Path) -> None:
        from transformers import AutoTokenizer

        if snapshot.name != self.model_revision or not snapshot.is_dir():
            raise ValueError("E5 tokenizer snapshot revision differs")
        self._tokenizer = AutoTokenizer.from_pretrained(
            str(snapshot), local_files_only=True
        )
        self.max_sequence_length = int(self._tokenizer.model_max_length)
        require_canonical_token_counter(self)

    def passage_token_count(self, text: str) -> int:
        encoded = self._tokenizer(
            format_passage(text), add_special_tokens=True, truncation=False
        )
        count = len(encoded["input_ids"])
        if count <= 0:
            raise ValueError("E5 tokenizer returned no token")
        return count


def _model_inventory(
    *, snapshot: Path, manifest: Mapping[str, object]
) -> tuple[bytes, bytes]:
    if not snapshot.is_dir():
        raise ValueError(f"model snapshot is missing: {snapshot}")
    manifest_bytes = canonical_json_bytes(manifest)
    rows = [f"{_sha256_bytes(manifest_bytes)}  manifest.json"]
    for path in sorted(snapshot.iterdir(), key=lambda item: item.name):
        if path.is_file():
            rows.append(f"{_file_sha256(path)}  {path.name}")
    if not any(row.endswith("model.safetensors") for row in rows):
        raise ValueError("model inventory has no weights")
    return manifest_bytes, ("\n".join(rows) + "\n").encode()


def _old_artifacts() -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for path in sorted(OLD_RELEASE_ROOT.rglob("*.release.json")):
        if path.name == "multilevel.release.json":
            continue
        document = _load_json(path)
        for artifact in document.get("artifacts", []):
            artifact = dict(artifact)
            artifact["evidence_path"] = _repo_relative(path)
            artifacts[artifact["content_sha256"]] = artifact
    return artifacts


def _title_from_path(path: str) -> str:
    stem = Path(path).stem.rsplit("--", 1)[0]
    return re.sub(r"\s+", " ", stem.replace("-", " ")).strip().capitalize()


def _source_records(
    *, matrix: list[dict[str, Any]], profiles: Mapping[str, Any]
) -> list[dict[str, Any]]:
    drive = {row["content_sha256"]: row for row in _load_json(DRIVE_MAPPING_PATH)}
    primary = {
        row["content_sha256"]: row
        for row in _load_json(PRIMARY_EVIDENCE_PATH)["records"]
    }
    old = _old_artifacts()
    p24 = _load_yaml(P24_POLICY_PATH)["approved_artifacts"]
    records: list[dict[str, Any]] = []
    subject_names = {
        "maths": "mathematiques",
        "physique_chimie": "physique-chimie",
    }
    for matrix_row in matrix:
        collection = matrix_row["dimensions"]["collection"]["value"]
        profile = profiles[collection]
        for content_sha in matrix_row["content_sha256"]:
            mirror = drive.get(content_sha)
            if mirror is None or mirror.get("mime_type") != "application/pdf":
                raise ValueError(f"Drive snapshot PDF is absent for {content_sha}")
            old_artifact = old.get(content_sha)
            primary_row = primary.get(content_sha)
            p24_row = p24.get(content_sha)
            if old_artifact:
                download_url = old_artifact["source_url"]
                listing_url = (
                    MATHEMATICS_LISTING_URL
                    if "education.gouv.fr" in download_url
                    and "eduscol.education.gouv.fr" not in download_url
                    else download_url
                )
                title = old_artifact["title"]
                type_doc = (
                    "programme-officiel"
                    if old_artifact["type_doc"] == "programme_officiel"
                    else "reperes-attendus"
                )
                evidence = old_artifact["evidence_path"]
            elif primary_row:
                listing_url = primary_row["official_source_url"]
                download_url = OFFICIAL_DOWNLOAD_URLS[content_sha]
                title = _title_from_path(mirror["canonical_path"])
                type_doc = (
                    "programme-officiel"
                    if "/01_PROGRAMMES_OFFICIELS/" in mirror["canonical_path"]
                    else "ressource-accompagnement"
                )
                evidence = _repo_relative(PRIMARY_EVIDENCE_PATH)
            elif p24_row:
                listing_url = p24_row["source_url"]
                download_url = OFFICIAL_DOWNLOAD_URLS[content_sha]
                title = _title_from_path(mirror["canonical_path"])
                type_doc = p24_row["source_document_type"]
                evidence = _repo_relative(P24_POLICY_PATH)
            else:
                raise ValueError(f"content {content_sha} has no release source fact")
            level = profile.scope.niveau.value
            external_level = "4e" if level == "quatrieme" else level
            matiere = str(profile.scope.matiere)
            external_subject = subject_names.get(matiere, matiere)
            external_scope = (
                f"college/{external_level}/{external_subject}"
                if profile.scope.voie.value == "college"
                else f"lycee/general/{external_subject}"
            )
            source_placement_id = _sha256_bytes(
                _compact_json_bytes(
                    {
                        "collection": collection,
                        "content_sha256": content_sha,
                        "source_url": listing_url,
                    }
                )
            )
            year_match = re.search(r"/(20[0-9]{2})/", mirror["canonical_path"])
            records.append(
                {
                    "collection": collection,
                    "content_sha256": content_sha,
                    "physical_path": mirror["canonical_path"],
                    "drive_file_id": mirror["drive_file_id"],
                    "drive_modified_time": mirror["modified_time"],
                    "drive_size": mirror["size"],
                    "source_placement_id": source_placement_id,
                    "source_url": listing_url,
                    "current_download_url": download_url,
                    "title": title,
                    "external_level": external_level,
                    "external_subject": external_subject,
                    "external_scope": external_scope,
                    "external_document_type": type_doc,
                    "year": year_match.group(1) if year_match else "2026",
                    "partition_id": matrix_row["partition_id"],
                    "source_evidence": evidence,
                }
            )
    ordered = stable_release_order(records)
    if len(ordered) != 26 or _final_set_digest(
        [row["content_sha256"] for row in ordered]
    ) != FINAL_SET_SHA256:
        raise ValueError("release source records differ from the final set")
    return ordered


def _catalog_documents(records: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    additions = [
        {
            "collection": row["collection"],
            "content_sha256": row["content_sha256"],
            "physical_path": row["physical_path"],
            "source_placement_id": row["source_placement_id"],
        }
        for row in records
    ]
    payload_sha = _sha256_bytes(_compact_json_bytes(additions))
    delta = {
        "catalog_delta_kind": "PRODUCTION_PROFILE_GATE_CATALOG_PROJECTION_V1",
        "school_year": SCHOOL_YEAR,
        "parent_catalog_path": _repo_relative(DRIVE_MAPPING_PATH),
        "parent_catalog_sha256": _file_sha256(DRIVE_MAPPING_PATH),
        "catalog_delta_payload_sha256": payload_sha,
        "counts": {"contents": 26, "placements": 26},
        "placements": additions,
    }
    delta_sha = _sha256_bytes(canonical_json_bytes(delta))
    effective_sha = _sha256_bytes(
        _compact_json_bytes(
            {
                "parent_sealed_catalog_sha256": _file_sha256(DRIVE_MAPPING_PATH),
                "catalog_delta_sha256": delta_sha,
                "catalog_delta_payload_sha256": payload_sha,
            }
        )
    )
    effective = {
        "authority_kind": "EFFECTIVE_PROFILE_GATE_CATALOG_V1",
        "authority_sha256": effective_sha,
        "parent_sealed_catalog_sha256": _file_sha256(DRIVE_MAPPING_PATH),
        "catalog_delta_sha256": delta_sha,
        "catalog_delta_payload_sha256": payload_sha,
    }
    return delta, effective


def _candidate_inventory(
    records: list[dict[str, Any]], *, delta: Mapping[str, Any], effective: Mapping[str, Any]
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        grouped[row["collection"]].append(row)
    collections = []
    all_shas = sorted(row["content_sha256"] for row in records)
    for collection in sorted(grouped):
        rows = sorted(grouped[collection], key=lambda row: row["content_sha256"])
        candidates = []
        for row in rows:
            candidates.append(
                {
                    "content_sha256": row["content_sha256"],
                    "physical_path": row["physical_path"],
                    "physical_currentness_candidate": "actuel",
                    "physical_disposition_candidate": "INGEST",
                    "placements": [
                        {
                            "source_placement_id": row["source_placement_id"],
                            "source_url": row["source_url"],
                            "title": row["title"],
                            "external_level": row["external_level"],
                            "external_subject": row["external_subject"],
                            "external_scope": row["external_scope"],
                            "external_document_type": row["external_document_type"],
                            "pedagogical_status": "production_eligible",
                            "year": row["year"],
                            "placement_origin": "PRODUCTION_PROFILE_GATE_20260825",
                            "placement_reason_code": row["partition_id"],
                        }
                    ],
                }
            )
        first = rows[0]
        collections.append(
            {
                "phase": "production_profile_gate",
                "collection": collection,
                "external_level": first["external_level"],
                "external_subject": first["external_subject"],
                "external_scope": first["external_scope"],
                "counts": {"unique_artifacts": len(rows), "placements": len(rows)},
                "observed_values": {
                    "document_types": sorted(
                        {row["external_document_type"] for row in rows}
                    )
                },
                "discovery_routes": [first["source_url"]],
                "inventory_disposition": "RELEASE_ELIGIBLE",
                "candidate_partition": {
                    "release_eligible": sorted(row["content_sha256"] for row in rows),
                    "review_required": [],
                },
                "candidates": candidates,
            }
        )
    return {
        "inventory_kind": "MULTILEVEL_CANDIDATE_INVENTORY_V1",
        "school_year": SCHOOL_YEAR,
        "corpus_manifest_sha256": CORPUS_MANIFEST_AUTHORITY,
        "sealed_catalog_sha256": _file_sha256(DRIVE_MAPPING_PATH),
        "placement_catalog_sha256": _file_sha256(PLACEMENT_LEDGER_PATH),
        "catalog_delta_sha256": _sha256_bytes(canonical_json_bytes(delta)),
        "catalog_delta_payload_sha256": delta["catalog_delta_payload_sha256"],
        "effective_catalog_authority_sha256": effective["authority_sha256"],
        "counts": {
            "target_collections": len(collections),
            "unique_artifacts": len(all_shas),
            "placements": len(records),
            "physical_objects": len(all_shas),
            "multi_placement_artifacts": 0,
        },
        "collection_partition": {
            "production_profile_exact": sorted(grouped),
            "review_required": [],
            "unevaluated": [],
        },
        "candidate_partition": {
            "exact_grade_gate_pending": all_shas,
            "named_noneligible": [],
            "unevaluated": [],
        },
        "collections": collections,
    }


def _release_scope_inputs(
    *,
    matrix: list[dict[str, Any]],
    profiles: Mapping[str, Any],
    profile_manifest_digest: str,
) -> tuple[bytes, bytes, bytes]:
    placements: list[dict[str, str]] = []
    profile_sources: dict[str, str] = {}
    for row in matrix:
        dimensions = row["dimensions"]
        collection = dimensions["collection"]["value"]
        profile = profiles[collection]
        sources = {
            dimension["source_of_truth"] for dimension in dimensions.values()
        }
        if len(sources) != 1:
            raise ValueError(f"profile source is ambiguous for {collection}")
        source_path = next(iter(sources))
        expected_prefix = "services/rag-engine/configs/ingestion_profiles/"
        if not source_path.startswith(expected_prefix) or not source_path.endswith(
            ".yml"
        ):
            raise ValueError(f"profile source is not canonical for {collection}")
        if collection in profile_sources and profile_sources[collection] != source_path:
            raise ValueError(f"profile source differs for {collection}")
        profile_sources[collection] = source_path
        for content_sha256 in row["content_sha256"]:
            placements.append(
                {
                    "content_sha256": content_sha256,
                    "release_id": RELEASE_ID,
                    "collection": collection,
                    "profile_version": profile.profile_version,
                }
            )
    placements = sorted(placements, key=lambda row: row["content_sha256"])
    contents = [row["content_sha256"] for row in placements]
    if len(contents) != 26 or _final_set_digest(contents) != FINAL_SET_SHA256:
        raise ValueError("release scope inputs differ from the final set")
    verified_profiles = {
        "profile_manifest_digest": profile_manifest_digest,
        "profiles": [
            {
                "profile_id": collection,
                "profile_version": profiles[collection].profile_version,
                "profile_fingerprint": profile_fingerprint(profiles[collection]),
                "scope": profiles[collection].scope.model_dump(mode="json"),
                "source_path": profile_sources[collection],
            }
            for collection in sorted(profile_sources)
        ],
    }
    if len(verified_profiles["profiles"]) != 18:
        raise ValueError("verified production profile count differs")
    return (
        ("\n".join(contents) + "\n").encode("utf-8"),
        canonical_json_bytes(placements),
        canonical_json_bytes(verified_profiles),
    )


def _verify_official_downloads(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    audit = []
    for row in records:
        completed = subprocess.run(
            [
                "curl",
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                row["current_download_url"],
            ],
            check=True,
            capture_output=True,
        )
        observed = _sha256_bytes(completed.stdout)
        if observed != row["content_sha256"]:
            raise ValueError(
                f"official download digest differs for {row['content_sha256']}"
            )
        audit.append(
            {
                "content_sha256": row["content_sha256"],
                "current_source_listing_url": row["source_url"],
                "current_download_url": row["current_download_url"],
                "downloaded_sha256": observed,
                "byte_identity": True,
            }
        )
    return audit


def _currentness_documents(
    records: list[dict[str, Any]],
    *,
    inventory: Mapping[str, Any],
    inventory_sha256: str,
    network_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    network_audit = {
        "audit_kind": "PRODUCTION_PROFILE_GATE_CURRENTNESS_AUDIT_V1",
        "verified_at": "2026-08-25T00:00:00Z",
        "network_mode": "READ_ONLY",
        "write_operations": 0,
        "counts": {"verified": len(network_rows), "digest_mismatch": 0},
        "artifacts": network_rows,
    }
    audit_sha = _sha256_bytes(canonical_json_bytes(network_audit))
    by_sha = {row["content_sha256"]: row for row in network_rows}
    artifacts = []
    for row in records:
        network = by_sha[row["content_sha256"]]
        artifacts.append(
            {
                "content_sha256": row["content_sha256"],
                "exact_path": row["physical_path"],
                "collections": [row["collection"]],
                "placement_facts": [
                    {
                        "collection": row["collection"],
                        "source_placement_id": row["source_placement_id"],
                        "external_level": row["external_level"],
                        "external_subject": row["external_subject"],
                        "external_scope": row["external_scope"],
                        "external_document_type": row["external_document_type"],
                    }
                ],
                "decision": "CURRENT",
                "effective_currentness": "actuel",
                "current_for_school_year": SCHOOL_YEAR,
                "current_source_listing_url": row["source_url"],
                "current_download_url": network["current_download_url"],
                "current_download_sha256": row["content_sha256"],
                "byte_identity": True,
                "drive_file_id": row["drive_file_id"],
                "drive_modified_time": row["drive_modified_time"],
            }
        )
    evidence = {
        "evidence_kind": "MULTILEVEL_ARTIFACT_CURRENTNESS_V1",
        "school_year": SCHOOL_YEAR,
        "candidate_inventory_sha256": inventory_sha256,
        "corpus_manifest_sha256": inventory["corpus_manifest_sha256"],
        "sealed_catalog_sha256": inventory["sealed_catalog_sha256"],
        "placement_catalog_sha256": inventory["placement_catalog_sha256"],
        "catalog_delta_sha256": inventory["catalog_delta_sha256"],
        "effective_catalog_authority_sha256": inventory[
            "effective_catalog_authority_sha256"
        ],
        "currentness_audit_sha256": audit_sha,
        "decision_basis": "Official Eduscol URL downloaded read-only and byte-matched",
        "counts": {
            "artifacts": 26,
            "evaluated": 26,
            "current": 26,
            "review_required": 0,
            "unevaluated": 0,
        },
        "partition": {
            "current": sorted(row["content_sha256"] for row in records),
            "review_required": [],
            "unevaluated": [],
        },
        "artifacts": artifacts,
    }
    return network_audit, evidence


def _pii_evidence(
    records: list[dict[str, Any]], *, pdfs: Mapping[str, Path], inventory_sha256: str
) -> dict[str, Any]:
    patterns = load_patterns_from_config(PII_POLICY_PATH)
    results = []
    for row in records:
        result = scan_pdf(pdfs[row["content_sha256"]], patterns)
        if result.extraction_error or result.pii_detected or result.matches:
            raise ValueError(f"PII scan did not clear {row['content_sha256']}")
        core = {
            "content_sha256": row["content_sha256"],
            "pages_scanned": result.pages_scanned,
            "characters_scanned": result.characters_scanned,
            "status": "CLEARED",
            "pii_detected": False,
        }
        results.append(
            {
                **core,
                "evidence_sha256": _sha256_bytes(_compact_json_bytes(core)),
                "source_path": row["physical_path"],
            }
        )
    return {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "school_year": SCHOOL_YEAR,
        "candidate_inventory_sha256": inventory_sha256,
        "corpus_manifest_sha256": CORPUS_MANIFEST_AUTHORITY,
        "policy_version": "pii_gate_policy_h2b_v5",
        "policy_sha256": _file_sha256(PII_POLICY_PATH),
        "scanner_version": "production-profile-gate-v1",
        "scanner_sha256": _file_sha256(PII_SCANNER_PATH),
        "required_pdf_path_count": len(records),
        "remote_access_mode": "READ_ONLY",
        "remote_write_operations": 0,
        "raw_pii_in_output": False,
        "raw_pii_in_logs": False,
        "summary": {
            "pii_scan_required": len(records),
            "pii_scanned": len(records),
            "pii_scan_coverage": 1.0,
            "pii_not_scanned": 0,
            "sha256_mismatches": 0,
        },
        "results": results,
    }


def _preflight(
    records: list[dict[str, Any]],
    *,
    pdfs: Mapping[str, Path],
    token_counter: CanonicalTokenCounter,
) -> dict[str, Any]:
    require_canonical_token_counter(token_counter)
    artifacts = []
    chunks_total = 0
    for row in records:
        content = pdfs[row["content_sha256"]].read_bytes()
        page_count = len(PdfReader(BytesIO(content)).pages)
        chunks = chunk_publication(
            content=content,
            mime_detected="application/pdf",
            extracted_text="",
            token_counter=token_counter,
            target_tokens=TARGET_TOKENS,
        )
        chunk_rows = []
        for index, chunk in enumerate(chunks):
            token_count = token_counter.passage_token_count(chunk.text)
            if token_count > TARGET_TOKENS:
                raise ValueError("publication chunk exceeds E5 target budget")
            chunk_sha = _sha256_bytes(chunk.text.encode("utf-8"))
            chunk_id = _sha256_bytes(
                f"{row['content_sha256']}:{index}:{chunk_sha}".encode()
            )
            chunk_rows.append(
                {
                    "chunk_index": index,
                    "chunk_id": chunk_id,
                    "chunk_sha256": chunk_sha,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "token_count": token_count,
                    "character_count": len(chunk.text),
                }
            )
        pages = {
            page
            for chunk in chunk_rows
            for page in range(chunk["page_start"], chunk["page_end"] + 1)
        }
        if pages != set(range(1, page_count + 1)):
            raise ValueError(f"PDF contains an empty/uncovered page: {row['content_sha256']}")
        chunks_total += len(chunk_rows)
        artifacts.append(
            {
                "content_sha256": row["content_sha256"],
                "source_path": row["physical_path"],
                "page_count": page_count,
                "chunks": chunk_rows,
            }
        )
    return {
        "evidence_kind": "PRODUCTION_PROFILE_GATE_PREFLIGHT_V1",
        "school_year": SCHOOL_YEAR,
        "model_id": token_counter.model_id,
        "model_revision": token_counter.model_revision,
        "target_tokens": TARGET_TOKENS,
        "counts": {
            "artifacts": len(artifacts),
            "pages": sum(row["page_count"] for row in artifacts),
            "chunks": chunks_total,
            "empty_pages": 0,
            "empty_chunks": 0,
            "oversized_chunks": 0,
        },
        "artifacts": artifacts,
    }


def _programme_registry(profiles: Mapping[str, Any]) -> dict[str, Any]:
    collection_config = load_collection_config(COLLECTION_CONFIG_PATH)["collections"]
    indexes = [
        {"path": path, "sha256": _file_sha256(REPOSITORY_ROOT / path)}
        for path in PROGRAMME_INDEX_PATHS
    ]
    taxonomies = []
    for collection in sorted(profiles):
        definition = collection_config[collection]
        path = REPOSITORY_ROOT / "services/rag-pedago/taxonomy" / definition[
            "taxonomy_file"
        ]
        taxonomy = _load_yaml(path)
        taxonomies.append(
            {
                "collection": collection,
                "path": _repo_relative(path),
                "sha256": _file_sha256(path),
                "niveau": taxonomy["niveau"],
                "voie": taxonomy["voie"],
                "matiere": taxonomy["matiere"],
                "statut_enseignement": taxonomy["statut_enseignement"],
                "programme_version": taxonomy["programme_version"],
            }
        )
    return {
        "registry_kind": "NEXUS_PROGRAMME_INDEX_REGISTRY_V3",
        "school_year": SCHOOL_YEAR,
        "indexes": indexes,
        "taxonomies": taxonomies,
    }


def _artifact(
    row: Mapping[str, Any],
    *,
    profile: Any,
    status: str,
    preflight: Mapping[str, Any],
    type_doc_mapping: Mapping[str, str],
) -> dict[str, Any]:
    sha = row["content_sha256"]
    placement_document = {
        "artifact_id": sha,
        "audience": sorted(value.value for value in profile.scope.audience),
        "candidat": profile.scope.candidat.value,
        "collection": str(profile.scope.collection),
        "matiere": str(profile.scope.matiere),
        "niveau": profile.scope.niveau.value,
        "programme_version": str(profile.scope.programme_version),
        "school_year": str(profile.scope.school_year),
        "statut_enseignement": status,
        "tenant": str(profile.scope.tenant),
        "visibility": str(profile.scope.visibility),
        "voie": profile.scope.voie.value,
    }
    placement_id = _sha256_bytes(_compact_json_bytes(placement_document))
    placement = {
        "placement_id": placement_id,
        "source_placement_id": row["source_placement_id"],
        "source_scope": row["external_scope"],
        "collection": row["collection"],
        "tenant": str(profile.scope.tenant),
        "niveau": profile.scope.niveau.value,
        "voie": profile.scope.voie.value,
        "matiere": str(profile.scope.matiere),
        "statut_enseignement": status,
        "candidat": profile.scope.candidat.value,
        "visibility": str(profile.scope.visibility),
        "school_year": str(profile.scope.school_year),
        "programme_version": str(profile.scope.programme_version),
        "currentness": "current",
        "placement_status": "active",
        "review_status": "reviewed",
    }
    chunks = [
        {
            key: chunk[key]
            for key in (
                "chunk_index",
                "chunk_id",
                "chunk_sha256",
                "page_start",
                "page_end",
            )
        }
        for chunk in preflight["chunks"]
    ]
    pages = sorted(
        {
            page
            for chunk in chunks
            for page in range(chunk["page_start"], chunk["page_end"] + 1)
        }
    )
    return {
        "content_sha256": sha,
        "source_path": row["physical_path"],
        "source_url": row["current_download_url"],
        "title": row["title"],
        "type_doc": type_doc_mapping[row["external_document_type"]],
        "page_count": preflight["page_count"],
        "placements": [placement],
        "chunks": chunks,
        "placement_id_set_digest": _set_digest([placement_id]),
        "chunk_id_set_digest": _set_digest([chunk["chunk_id"] for chunk in chunks]),
        "chunk_sha256_set_digest": _set_digest(
            [chunk["chunk_sha256"] for chunk in chunks]
        ),
        "page_coverage_digest": _set_digest(pages),
    }


def validate_authority_bindings(
    *,
    repository_root: Path,
    bindings: dict[str, Any],
    aggregate: dict[str, Any],
) -> None:
    if set(bindings) != {
        "binding_kind",
        "school_year",
        "profile_manifest_file_sha256",
        "profile_manifest_fingerprint",
        "bindings",
    }:
        raise ValueError("authority bindings fields are not exact")
    raw_bindings = bindings["bindings"]
    authorities = aggregate["authorities"]
    if not isinstance(raw_bindings, dict) or set(raw_bindings) != set(authorities):
        raise ValueError("authority binding set differs")
    root = repository_root.resolve()
    seen_paths: set[Path] = set()
    for name, binding in raw_bindings.items():
        if set(binding) != {
            "path",
            "file_sha256",
            "authority_sha256",
            "authority_kind",
        }:
            raise ValueError(f"authority binding {name} fields differ")
        relative = Path(binding["path"])
        path = (root / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(root) or path in seen_paths:
            raise ValueError("authority binding path is invalid")
        seen_paths.add(path)
        actual = _file_sha256(path)
        if actual != binding["file_sha256"]:
            raise ValueError(f"authority binding digest differs for {name}")
        if authorities[name] != binding["authority_sha256"]:
            raise ValueError(f"aggregate authority digest differs for {name}")
        kind = binding["authority_kind"]
        if kind == "FILE_SHA256" and actual != binding["authority_sha256"]:
            raise ValueError(f"file authority digest differs for {name}")
        if kind == "SEMANTIC_PROFILE_FINGERPRINT":
            if name != "profile_manifest_sha256" or binding[
                "authority_sha256"
            ] != bindings["profile_manifest_fingerprint"]:
                raise ValueError("profile manifest semantic digest differs")
        elif kind == "LOGICAL_SHA256":
            descriptor = _load_json(path)
            if descriptor.get("authority_sha256") != binding["authority_sha256"]:
                raise ValueError(f"logical authority digest differs for {name}")
        elif kind != "FILE_SHA256":
            raise ValueError(f"authority binding kind is unsupported for {name}")


def build_release(
    *,
    pdf_root: Path,
    embedding_snapshot: Path,
    reranker_snapshot: Path,
    verify_official_downloads: bool,
) -> dict[Path, bytes]:
    matrix = _load_json(FINAL_MATRIX_PATH)
    registry = load_profile_registry(PROFILE_ROOT)
    manifest = verify_profile_manifest(registry, PROFILE_MANIFEST_PATH)
    profiles = {profile.scope.collection: profile for profile in registry.values()}
    if len(profiles) != 18 or manifest.declared_count != 18:
        raise ValueError("production profile registry/manifest count differs")
    records = _source_records(matrix=matrix, profiles=profiles)
    final_set_raw, accepted_placements_raw, verified_profiles_raw = (
        _release_scope_inputs(
            matrix=matrix,
            profiles=profiles,
            profile_manifest_digest=manifest.manifest_fingerprint,
        )
    )
    pdfs = validate_pdf_mirror(
        pdf_root=pdf_root,
        content_sha256=[row["content_sha256"] for row in records],
    )
    token_counter = E5TokenCounter(embedding_snapshot)

    embedding_manifest, embedding_inventory = _model_inventory(
        snapshot=embedding_snapshot,
        manifest={
            "model_id": CANONICAL_EMBEDDING_MODEL,
            "revision": CANONICAL_EMBEDDING_REVISION,
            "canonical_dim": 1024,
        },
    )
    reranker_manifest, reranker_inventory = _model_inventory(
        snapshot=reranker_snapshot,
        manifest={
            "model_id": CANONICAL_RERANKER_MODEL,
            "revision": CANONICAL_RERANKER_REVISION,
        },
    )
    delta, effective = _catalog_documents(records)
    inventory = _candidate_inventory(records, delta=delta, effective=effective)
    inventory_sha = _sha256_bytes(canonical_json_bytes(inventory))
    if verify_official_downloads:
        network_rows = _verify_official_downloads(records)
    else:
        raise ValueError("official download revalidation is required")
    network_audit, currentness = _currentness_documents(
        records,
        inventory=inventory,
        inventory_sha256=inventory_sha,
        network_rows=network_rows,
    )
    pii = _pii_evidence(records, pdfs=pdfs, inventory_sha256=inventory_sha)
    preflight = _preflight(records, pdfs=pdfs, token_counter=token_counter)
    programme = _programme_registry(profiles)

    corpus_descriptor = {
        "authority_kind": "SEALED_CORPUS_MANIFEST_REFERENCE_V1",
        "authority_sha256": CORPUS_MANIFEST_AUTHORITY,
        "content_ledger_path": _repo_relative(CONTENT_LEDGER_PATH),
        "content_ledger_sha256": _file_sha256(CONTENT_LEDGER_PATH),
        "final_content_count": 26,
        "final_content_set_sha256": FINAL_SET_SHA256,
    }
    documents: dict[Path, bytes] = {
        RELEASE_ROOT / "catalog_delta.json": canonical_json_bytes(delta),
        RELEASE_ROOT / "effective_catalog_authority.json": canonical_json_bytes(effective),
        RELEASE_ROOT / "candidate_inventory.json": canonical_json_bytes(inventory),
        RELEASE_ROOT / "currentness_network_audit.json": canonical_json_bytes(network_audit),
        RELEASE_ROOT / "currentness_evidence.json": canonical_json_bytes(currentness),
        RELEASE_ROOT / "pii_evidence.json": canonical_json_bytes(pii),
        RELEASE_ROOT / "preflight_evidence.json": canonical_json_bytes(preflight),
        RELEASE_ROOT / "programme_registry.json": canonical_json_bytes(programme),
        RELEASE_ROOT / "corpus_manifest_authority.json": canonical_json_bytes(
            corpus_descriptor
        ),
        RELEASE_ROOT / "models/embedding/manifest.json": embedding_manifest,
        RELEASE_ROOT / "models/embedding/SHA256SUMS": embedding_inventory,
        RELEASE_ROOT / "models/reranker/manifest.json": reranker_manifest,
        RELEASE_ROOT / "models/reranker/SHA256SUMS": reranker_inventory,
    }
    authority_paths = {
        "corpus_manifest_sha256": RELEASE_ROOT / "corpus_manifest_authority.json",
        "parent_sealed_catalog_sha256": DRIVE_MAPPING_PATH,
        "placement_catalog_sha256": PLACEMENT_LEDGER_PATH,
        "catalog_delta_sha256": RELEASE_ROOT / "catalog_delta.json",
        "effective_catalog_authority_sha256": RELEASE_ROOT
        / "effective_catalog_authority.json",
        "candidate_inventory_sha256": RELEASE_ROOT / "candidate_inventory.json",
        "currentness_evidence_sha256": RELEASE_ROOT / "currentness_evidence.json",
        "pii_evidence_sha256": RELEASE_ROOT / "pii_evidence.json",
        "pii_policy_sha256": PII_POLICY_PATH,
        "pii_scanner_sha256": PII_SCANNER_PATH,
        "rights_registry_sha256": RIGHTS_REGISTRY_PATH,
        "preflight_evidence_sha256": RELEASE_ROOT / "preflight_evidence.json",
        "programme_registry_sha256": RELEASE_ROOT / "programme_registry.json",
        "profile_manifest_sha256": PROFILE_MANIFEST_PATH,
        "level_mapping_sha256": LEVEL_MAPPING_PATH,
        "subject_mapping_sha256": SUBJECT_MAPPING_PATH,
        "document_type_mapping_sha256": DOCUMENT_TYPE_MAPPING_PATH,
        "embedding_inventory_sha256": RELEASE_ROOT / "models/embedding/SHA256SUMS",
        "reranker_inventory_sha256": RELEASE_ROOT / "models/reranker/SHA256SUMS",
    }
    logical_authorities = {
        "corpus_manifest_sha256": CORPUS_MANIFEST_AUTHORITY,
        "effective_catalog_authority_sha256": effective["authority_sha256"],
        "profile_manifest_sha256": manifest.manifest_fingerprint,
    }
    authorities: dict[str, str] = {}
    raw_bindings: dict[str, dict[str, str]] = {}
    for name, path in authority_paths.items():
        file_bytes = documents.get(path, path.read_bytes() if path.is_file() else b"")
        if not file_bytes:
            raise ValueError(f"authority file is absent: {path}")
        file_sha = _sha256_bytes(file_bytes)
        authority_sha = logical_authorities.get(name, file_sha)
        kind = (
            "SEMANTIC_PROFILE_FINGERPRINT"
            if name == "profile_manifest_sha256"
            else "LOGICAL_SHA256"
            if name in logical_authorities
            else "FILE_SHA256"
        )
        authorities[name] = authority_sha
        raw_bindings[name] = {
            "path": _repo_relative(path),
            "file_sha256": file_sha,
            "authority_sha256": authority_sha,
            "authority_kind": kind,
        }

    models = {
        "embedding": {
            "model_id": CANONICAL_EMBEDDING_MODEL,
            "inventory_sha256": authorities["embedding_inventory_sha256"],
            "dimension": 1024,
        },
        "reranker": {
            "model_id": CANONICAL_RERANKER_MODEL,
            "inventory_sha256": authorities["reranker_inventory_sha256"],
        },
    }
    collection_config = load_collection_config(COLLECTION_CONFIG_PATH)["collections"]
    preflight_by_sha = {
        row["content_sha256"]: row for row in preflight["artifacts"]
    }
    type_doc_mapping = _load_yaml(DOCUMENT_TYPE_MAPPING_PATH)["document_types"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        grouped[row["collection"]].append(row)
    subjects = []
    total = {"artifacts": 0, "placements": 0, "chunks": 0}
    for collection in sorted(grouped):
        profile = profiles[collection]
        artifacts = [
            _artifact(
                row,
                profile=profile,
                status=collection_config[collection]["statut"],
                preflight=preflight_by_sha[row["content_sha256"]],
                type_doc_mapping=type_doc_mapping,
            )
            for row in sorted(grouped[collection], key=lambda value: value["content_sha256"])
        ]
        counts = {
            "artifacts": len(artifacts),
            "placements": sum(len(row["placements"]) for row in artifacts),
            "chunks": sum(len(row["chunks"]) for row in artifacts),
        }
        for name in total:
            total[name] += counts[name]
        subject = {
            "release_kind": "MULTILEVEL_SUBJECT_RELEASE_V1",
            "release_id": f"{RELEASE_ID}-{collection}",
            "school_year": SCHOOL_YEAR,
            "collection": collection,
            "programme_version": str(profile.scope.programme_version),
            "authorities": authorities,
            "profile": {
                "version": profile.profile_version,
                "fingerprint": profile_fingerprint(profile),
                "manifest_digest": manifest.manifest_fingerprint,
            },
            "models": models,
            "expected_counts": counts,
            "artifacts": artifacts,
        }
        path = RELEASE_ROOT / "subjects" / f"{collection}.release.json"
        raw = canonical_json_bytes(subject)
        documents[path] = raw
        subjects.append(
            {
                "path": path.relative_to(RELEASE_ROOT).as_posix(),
                "sha256": _sha256_bytes(raw),
                "collection": collection,
            }
        )
    aggregate = {
        "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V1",
        "release_id": RELEASE_ID,
        "school_year": SCHOOL_YEAR,
        "authorities": authorities,
        "models": models,
        "expected_counts": total,
        "subjects": subjects,
    }
    aggregate_path = RELEASE_ROOT / "production-profile-gate.release.json"
    aggregate_raw = canonical_json_bytes(aggregate)
    documents[aggregate_path] = aggregate_raw
    bindings = {
        "binding_kind": "PRODUCTION_PROFILE_RELEASE_AUTHORITY_BINDINGS_V1",
        "school_year": SCHOOL_YEAR,
        "profile_manifest_file_sha256": _file_sha256(PROFILE_MANIFEST_PATH),
        "profile_manifest_fingerprint": manifest.manifest_fingerprint,
        "bindings": raw_bindings,
    }
    documents[RELEASE_ROOT / "authority_bindings.json"] = canonical_json_bytes(bindings)
    release_registry = {
        "registry_version": "1",
        "school_year": SCHOOL_YEAR,
        "releases": [
            {
                "release_id": RELEASE_ID,
                "collections": sorted(grouped),
                "manifest_path": "profile_gate/production-profile-gate.release.json",
                "expected_manifest_sha256": _sha256_bytes(aggregate_raw),
                "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V1",
            }
        ],
    }
    documents[RELEASE_ROOT.parent / "release-registry.json"] = canonical_json_bytes(
        release_registry
    )
    documents[FINAL_PRODUCTION_SET_PATH] = final_set_raw
    documents[ACCEPTED_PLACEMENTS_PATH] = accepted_placements_raw
    documents[VERIFIED_PROFILES_PATH] = verified_profiles_raw
    return documents


def _write_documents(documents: Mapping[Path, bytes]) -> None:
    for path, content in sorted(documents.items(), key=lambda item: item[0].as_posix()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-root", required=True, type=Path)
    parser.add_argument("--embedding-snapshot", required=True, type=Path)
    parser.add_argument("--reranker-snapshot", required=True, type=Path)
    parser.add_argument("--verify-official-downloads", action="store_true")
    args = parser.parse_args(argv)
    documents = build_release(
        pdf_root=args.pdf_root,
        embedding_snapshot=args.embedding_snapshot,
        reranker_snapshot=args.reranker_snapshot,
        verify_official_downloads=args.verify_official_downloads,
    )
    _write_documents(documents)
    aggregate = _load_json(RELEASE_ROOT / "production-profile-gate.release.json")
    bindings = _load_json(RELEASE_ROOT / "authority_bindings.json")
    validate_authority_bindings(
        repository_root=REPOSITORY_ROOT,
        bindings=bindings,
        aggregate=aggregate,
    )
    print(f"PRODUCTION_PROFILE_RELEASE_CONTENTS={aggregate['expected_counts']['artifacts']}")
    print(f"PRODUCTION_PROFILE_RELEASE_COLLECTIONS={len(aggregate['subjects'])}")
    print(
        "PRODUCTION_PROFILE_RELEASE_SHA256="
        f"{_file_sha256(RELEASE_ROOT / 'production-profile-gate.release.json')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
