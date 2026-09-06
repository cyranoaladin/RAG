#!/usr/bin/env python3
"""Produire, DANS ce dépôt, le préflight que la release multi-niveaux consomme.

**Pourquoi ce script existe.** `build_multilevel_release.py` consomme depuis
toujours une preuve de préflight — la seule source des chunks que la release
scelle — et aucun producteur de ce format n'existait ici. Le fichier consommé
avait été produit le 12/08/2026 par un outil externe, hors du dépôt : personne
ne pouvait le reproduire, le contredire, ni même dire sous quel extracteur il
avait été fabriqué. La release scellée le 13/08 et le banc d'ingestion actuel
divergent aujourd'hui de plusieurs centaines de chunks, sans qu'aucune preuve
ne permette d'imputer l'écart.

**Ce que ce producteur dérive.** Rien d'inventé, tout de seconde main :

  * la SÉLECTION vient de `derive_preflight_requirements` — l'algèbre de
    l'actualité, de la clairance PII et des droits est celle du consommateur,
    lue chez lui, jamais recopiée ;
  * les PAGES viennent de `extract_pdf_pages_with_structural_empty_pages`,
    l'autorité commune du scan PII et de la politique de pages ;
  * les CHUNKS viennent de `chunk_publication`, le chunker de publication
    gouverné, avec son budget déclaré ;
  * les TOKENS viennent du tokenizer de l'instantané embedding scellé, vérifié
    octet par octet avant d'être chargé ;
  * l'IDENTITÉ d'un chunk est celle que le publieur reproduira —
    `sha256(content_sha256:index:chunk_sha256)`.

Le document produit est du schéma `MULTILEVEL_RELEASE_PREFLIGHT_V2` : il
déclare le runtime d'extraction dont ses empreintes dépendent, et il NOMME les
pages que la politique autorise à ignorer. Il n'ouvre aucune porte : un
artefact qui en porte reste refusé par la porte de release.

Aucun horodatage n'y figure : deux dérivations des mêmes entrées doivent rendre
les mêmes octets, faute de quoi le producteur ne peut pas démontrer qu'il
reproduit ce qu'il a scellé.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

import nexus_pdf_page_policy as page_policy
from nexus_contracts.embedding_utils import format_passage
from nexus_release_chain.pdf_extractor import PDF_MIME_TYPE
from nexus_release_chain.publication_chunking import chunk_publication

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
_SERVICE_ROOT = _SCRIPTS_DIR.parent
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))

import build_multilevel_release as release  # noqa: E402

from rag_pedago.imports.pii_scanner import (  # noqa: E402
    extract_pdf_pages_with_structural_empty_pages,
)

EVIDENCE_KIND = release.PREFLIGHT_EVIDENCE_KIND
EMBEDDING_DIMENSION = 1024
_INVENTORY_LINE_SEPARATOR = "  "
#: Le fichier que l'artefact embedding scellé porte pour s'inventorier
#: lui-même. C'est son empreinte que la release déclare, et non celle d'un
#: inventaire recalculé selon une convention de tri différente.
INVENTORY_FILENAME = "SHA256SUMS"
MANIFEST_FILENAME = "manifest.json"


class PassageTokenCounter(Protocol):
    """Compteur qui DÉCLARE de quel modèle scellé il provient."""

    model_id: str
    model_revision: str
    inventory_sha256: str
    max_sequence_length: int

    def passage_token_count(self, text: str) -> int: ...


def require_canonical_token_counter(token_counter: object) -> None:
    """Refuser un compteur qui n'est pas celui du modèle que la release déclare.

    Un `real_e5_tokens` n'a aucun sens absolu : il mesure un texte pour UN
    tokenizer. Inscrire des comptes issus d'un autre modèle sous l'identité du
    modèle scellé rendrait la preuve fausse tout en la laissant vraisemblable."""
    if getattr(token_counter, "model_id", None) != release.EMBEDDING_MODEL:
        raise ValueError("token counter model identity differs")
    if getattr(token_counter, "model_revision", None) != release.EMBEDDING_MODEL_REVISION:
        raise ValueError("token counter model revision differs")
    if getattr(token_counter, "inventory_sha256", None) != release.EMBEDDING_INVENTORY_SHA256:
        raise ValueError("token counter inventory differs from the sealed artifact")
    if int(getattr(token_counter, "max_sequence_length", 0)) < release.CHUNK_TARGET_TOKENS:
        raise ValueError("token counter sequence length is too small")
    if not callable(getattr(token_counter, "passage_token_count", None)):
        raise ValueError("token counter is unavailable")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_embedding_snapshot(
    snapshot: Path,
    *,
    expected_inventory_sha256: str | None = None,
) -> dict[str, Any]:
    """Vérifier qu'un instantané est bien l'artefact embedding scellé.

    Deux contrôles distincts, et les deux sont nécessaires :

      1. l'inventaire que l'instantané porte est CELUI que la release déclare —
         sinon c'est un autre artefact ;
      2. les octets présents sont ceux que cet inventaire décrit, fichier par
         fichier, sans ajout ni retrait — sinon l'inventaire est un titre sans
         objet, et une substitution à effectif constant passerait.

    Un contrôle de cardinalité seul laisserait passer exactement ce second cas.
    """
    expected = expected_inventory_sha256 or release.EMBEDDING_INVENTORY_SHA256
    inventory_path = snapshot / INVENTORY_FILENAME
    if not inventory_path.is_file():
        raise ValueError(f"embedding snapshot carries no {INVENTORY_FILENAME}")
    observed_inventory = _file_sha256(inventory_path)
    if observed_inventory != expected:
        raise ValueError("embedding inventory digest differs")

    declared: dict[str, str] = {}
    for line in inventory_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, relative = line.partition(_INVENTORY_LINE_SEPARATOR)
        if not relative:
            raise ValueError("embedding inventory line is malformed")
        declared[relative] = digest
    observed = {
        path.relative_to(snapshot).as_posix(): _file_sha256(path)
        for path in snapshot.rglob("*")
        if path.is_file() and path.name != INVENTORY_FILENAME
    }
    if declared != observed:
        raise ValueError("embedding snapshot differs from its inventory")

    manifest_path = snapshot / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ValueError(f"embedding snapshot carries no {MANIFEST_FILENAME}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("model_id") != release.EMBEDDING_MODEL
        or manifest.get("upstream_revision") != release.EMBEDDING_MODEL_REVISION
        or manifest.get("canonical_dim") != EMBEDDING_DIMENSION
    ):
        raise ValueError("embedding snapshot manifest declares another model")
    return manifest


class E5TokenCounter:
    """Tokenizer chargé d'un instantané vérifié, et de lui seul."""

    def __init__(self, snapshot: Path) -> None:
        from transformers import AutoTokenizer

        verify_embedding_snapshot(snapshot)
        self.model_id = release.EMBEDDING_MODEL
        self.model_revision = release.EMBEDDING_MODEL_REVISION
        self.inventory_sha256 = release.EMBEDDING_INVENTORY_SHA256
        self._tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True)
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


def _verified_pdf(pdf_mirror: Path, *, relative: str, content_sha256: str) -> bytes:
    """Lire un PDF du miroir et refuser tout ce que son NOM prétendrait seul."""
    root = pdf_mirror.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"PDF mirror path escapes the mirror root: {relative}")
    if not path.is_file():
        raise ValueError(f"PDF mirror is missing content {content_sha256}")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != content_sha256:
        raise ValueError(f"PDF mirror digest differs for {content_sha256}")
    return content


def _required_pii_pages_scanned(row: Mapping[str, Any], *, sha: str) -> int:
    value = row.get("pages_scanned")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"PII evidence declares no page count for {sha}")
    return value


def _artifact_row(
    *,
    sha: str,
    requirements: release.PreflightRequirements,
    content: bytes,
    token_counter: PassageTokenCounter,
) -> dict[str, Any]:
    """Dériver la ligne d'un artefact des seules autorités d'exécution."""
    pages_text, ignored_empty_pages, extraction_error = (
        extract_pdf_pages_with_structural_empty_pages(content)
    )
    if extraction_error:
        raise ValueError(f"preflight extraction failed for {sha} — {extraction_error}")
    page_count = len(pages_text)

    # La preuve PII et le préflight doivent décrire le MÊME document sous la
    # MÊME politique de pages. `pages_scanned` est le nombre de pages que le
    # scan a réellement lues : les pages du document moins celles que la
    # politique écarte. Si la somme ne retombe pas, la clairance PII a été
    # rendue sur un autre objet que celui qui serait indexé.
    declared_scanned = _required_pii_pages_scanned(requirements.pii_rows[sha], sha=sha)
    if declared_scanned != page_count - len(ignored_empty_pages):
        raise ValueError(
            f"PII scan page count differs from the authoritative extraction for {sha}"
        )

    chunks = chunk_publication(
        content=content,
        mime_detected=PDF_MIME_TYPE,
        extracted_text="",
        token_counter=token_counter,
        target_tokens=release.CHUNK_TARGET_TOKENS,
    )
    chunk_rows: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        tokens = token_counter.passage_token_count(chunk.text)
        if tokens > release.CHUNK_TARGET_TOKENS:
            raise ValueError(f"publication chunk exceeds the declared budget for {sha}")
        if chunk.page_start is None or chunk.page_end is None:
            raise ValueError(f"publication chunk carries no page metadata for {sha}")
        chunk_sha = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
        chunk_rows.append(
            {
                "chunk_index": index,
                "chunk_id": hashlib.sha256(f"{sha}:{index}:{chunk_sha}".encode()).hexdigest(),
                "chunk_sha256": chunk_sha,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "real_e5_tokens": tokens,
            }
        )

    covered = {
        page
        for row in chunk_rows
        for page in range(int(row["page_start"]), int(row["page_end"]) + 1)
    }
    overlap = covered & set(ignored_empty_pages)
    if overlap:
        raise ValueError(f"preflight covers a page it also ignores for {sha}: {sorted(overlap)}")
    unexplained = set(range(1, page_count + 1)) - covered - set(ignored_empty_pages)
    if unexplained:
        raise ValueError(f"preflight leaves pages unexplained for {sha}: {sorted(unexplained)}")

    tokens_seen = [int(row["real_e5_tokens"]) for row in chunk_rows]
    collections = sorted(requirements.collections_by_sha[sha])
    return {
        "content_sha256": sha,
        "source_path": requirements.physical_path_by_sha[sha],
        "collections": [
            {
                "collection": collection,
                "profile_version": requirements.profiles[collection][0].profile_version,
                "profile_fingerprint": requirements.profiles[collection][1],
                "programme_version": requirements.programme_facts[collection][
                    "programme_version"
                ],
            }
            for collection in collections
        ],
        "status": "PASS",
        "error_code": None,
        "currentness": "actuel",
        "current_for_school_year": release.SCHOOL_YEAR,
        "rights": requirements.rights_category,
        "rights_decision_id": requirements.rights_decision_id,
        "rights_zone": requirements.rights_zone,
        "pii_status": "CLEARED",
        "pii_pages_scanned": declared_scanned,
        "extraction_complete": True,
        "chunking_complete": True,
        "page_count": page_count,
        "ignored_empty_pages": list(ignored_empty_pages),
        "empty_extracted_pages": len(ignored_empty_pages),
        "page_coverage": len(covered) / page_count,
        "page_coverage_digest": release._set_digest(sorted(covered)),
        "chunk_count": len(chunk_rows),
        "chunks": chunk_rows,
        "chunk_id_set_digest": release._set_digest([row["chunk_id"] for row in chunk_rows]),
        "chunk_sha256_set_digest": release._set_digest(
            [row["chunk_sha256"] for row in chunk_rows]
        ),
        "empty_chunks": 0,
        "oversized_model_chunks": 0,
        "null_page_metadata": 0,
        "min_real_e5_tokens": min(tokens_seen),
        "max_real_e5_tokens": max(tokens_seen),
        "median_real_e5_tokens": statistics.median(tokens_seen),
        "profile_conformity": True,
        "programme_conformity": True,
        "placement_clear": True,
    }


def build_preflight_evidence(
    *,
    requirements: release.PreflightRequirements,
    pdf_mirror: Path,
    token_counter: PassageTokenCounter,
) -> dict[str, Any]:
    """Dériver le préflight V2 de la sélection et des octets du miroir."""
    require_canonical_token_counter(token_counter)
    page_policy.require_canonical_pypdf()
    if not requirements.required_shas:
        raise ValueError("preflight selection is empty: there is nothing to attest")

    artifacts = [
        _artifact_row(
            sha=sha,
            requirements=requirements,
            content=_verified_pdf(
                pdf_mirror,
                relative=requirements.physical_path_by_sha[sha],
                content_sha256=sha,
            ),
            token_counter=token_counter,
        )
        for sha in sorted(requirements.required_shas)
    ]
    total_chunks = sum(int(row["chunk_count"]) for row in artifacts)
    total_pages = sum(int(row["page_count"]) for row in artifacts)
    full_coverage = sum(1 for row in artifacts if float(row["page_coverage"]) == 1.0)
    bindings = requirements.bindings
    return {
        "evidence_kind": EVIDENCE_KIND,
        "school_year": release.SCHOOL_YEAR,
        "candidate_inventory_sha256": bindings["candidate_inventory_sha256"],
        "corpus_manifest_sha256": bindings["corpus_manifest_sha256"],
        "currentness_evidence_sha256": bindings["currentness_evidence_sha256"],
        "pii_evidence_sha256": bindings["pii_evidence_sha256"],
        "pii_policy_sha256": bindings["pii_policy_sha256"],
        "rights_registry_sha256": bindings["rights_registry_sha256"],
        "profile_manifest_sha256": bindings["profile_manifest_sha256"],
        "profile_manifest_declared_count": len(requirements.profiles),
        "programme_registry_sha256": bindings["programme_registry_sha256"],
        "programme_index_sha256_by_path": dict(requirements.programme_index_sha256_by_path),
        "embedding_model_id": release.EMBEDDING_MODEL,
        "embedding_model_revision": release.EMBEDDING_MODEL_REVISION,
        "embedding_inventory_sha256": bindings["embedding_inventory_sha256"],
        "embedding_dimension": EMBEDDING_DIMENSION,
        "embedding_max_sequence_length": int(token_counter.max_sequence_length),
        "chunk_target_tokens": release.CHUNK_TARGET_TOKENS,
        "extraction_runtime": {
            "pypdf_version": page_policy.CANONICAL_PYPDF_VERSION,
            "page_policy_id": page_policy.POLICY_ID,
            "page_policy_sha256": page_policy.policy_source_sha256(),
        },
        "raw_pii_in_evidence": False,
        "raw_text_in_evidence": False,
        "selection": {
            "current_artifacts": len(requirements.current_shas),
            "current_and_pii_cleared": len(requirements.required_shas),
            "excluded_current_pii_sha256": sorted(requirements.excluded_current_pii_shas),
        },
        "summary": {
            "required": len(artifacts),
            "evaluated": len(artifacts),
            "pass": len(artifacts),
            "review_required": 0,
            "extraction_failures": 0,
            "full_page_coverage_artifacts": full_coverage,
            "total_chunks": total_chunks,
            "total_pages": total_pages,
            "empty_chunks": 0,
            "oversized_model_chunks": 0,
            "null_page_metadata": 0,
            "by_collection": _summary_by_collection(artifacts),
        },
        "artifacts": artifacts,
    }


def _summary_by_collection(artifacts: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for row in artifacts:
        for entry in row["collections"]:
            collection = str(entry["collection"])
            counts = summary.setdefault(
                collection, {"artifacts": 0, "chunks": 0, "pass": 0, "review_required": 0}
            )
            counts["artifacts"] += 1
            counts["chunks"] += int(row["chunk_count"])
            counts["pass"] += 1
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in (
        "inventory",
        "currentness",
        "pii",
        "rights-registry",
        "profile-manifest",
        "programme-registry",
        "level-mapping",
        "subject-mapping",
        "document-type-mapping",
    ):
        parser.add_argument(f"--{option}", type=Path, required=True)
        parser.add_argument(f"--{option}-sha256", required=True)
    parser.add_argument("--profiles-dir", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    # Le miroir PDF et l'instantané du modèle sont des ENTRÉES nommées à
    # l'exécution : aucun chemin de poste de travail ne vit dans ce fichier.
    parser.add_argument("--pdf-mirror", type=Path, required=True)
    parser.add_argument("--embedding-snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    requirements = release.derive_preflight_requirements(
        **release.load_authority_cli_inputs(args)
    )
    document = build_preflight_evidence(
        requirements=requirements,
        pdf_mirror=args.pdf_mirror,
        token_counter=E5TokenCounter(args.embedding_snapshot),
    )
    output: Path = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(release.canonical_json_bytes(document))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
