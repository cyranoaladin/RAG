#!/usr/bin/env python3
"""Construire la release production exacte issue du gate de profils 2026-2027."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple, Protocol

import nexus_pdf_page_policy as page_policy
import yaml
from nexus_contracts.embedding_utils import format_passage
from nexus_contracts.review_binding import (
    ReviewBindingError,
    TrustAnchor,
    verify_pii_review_decision_authority,
)
from nexus_release_chain.collection_config import load_collection_config
from nexus_release_chain.ingestion_profiles.manifest import verify_profile_manifest
from nexus_release_chain.ingestion_profiles.registry import (
    load_profile_registry,
    profile_fingerprint,
)
from nexus_release_chain.publication_chunking import chunk_publication
from nexus_release_chain.release_readiness import (
    load_release_expectation,
    load_release_registry_file,
)

from rag_pedago.imports.pii_review_projection import (
    PiiProjectionError,
    ScannedContent,
    ScannedFinding,
    finding_context,
    finding_identity,
    project_pii_review,
)
from rag_pedago.imports.pii_scanner import (
    extract_pdf_pages_with_structural_empty_pages,
    load_patterns_from_config,
    scan_pdf_bytes,
)
from rag_pedago.imports.raw_pii_guard import require_no_raw_pii

REPOSITORY_ROOT = Path(os.environ.get("NEXUS_REPO_ROOT") or Path(__file__).resolve().parents[3])

SCHOOL_YEAR = "2026-2027"
RELEASE_ID = "production-profile-gate-2026-2027-v1"
#: Empreinte de l'ensemble de contenus que la lignée canonique produit. Ce
#: n'est pas une affirmation : un test recalcule l'ensemble depuis la matrice
#: et les profils déclarés, et exige ce digest. Il coïncide par ailleurs avec
#: le `content_set_sha256` de l'index de la campagne de revue PII — le corpus
#: scellé et le corpus revu sont le même.
CANONICAL_CONTENT_SET_SHA256 = (
    "77f01c824c6be14ba6fd66eda99c2179fd87d9a2aaaf3c58e56a917d1ad5c31d"
)
#: Valeur que le fichier d'autorité de manifeste DÉCLARE (`authority_sha256`).
#: C'est elle que la release embarque sous `corpus_manifest_sha256`.
CORPUS_MANIFEST_AUTHORITY = (
    "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
)


def corpus_manifest_authority_file_sha256() -> str:
    """Empreinte des OCTETS du fichier d'autorité de manifeste.

    **Pourquoi ce n'est pas `CORPUS_MANIFEST_AUTHORITY`.** L'ensemble de
    décisions scellé enregistre l'empreinte du FICHIER ; la release embarque la
    valeur que ce fichier DÉCLARE. Deux mesures de la même autorité, jamais
    égales. Les confondre faisait refuser à la projection le corpus même sur
    lequel la revue humaine avait été rendue — « the decisions describe another
    corpus », sur les décisions qui le décrivent exactement — et rendait la
    candidate de production irreproductible.

    La liaison déclarée est vérifiée au passage : le fichier doit annoncer
    l'autorité que la release embarque, faute de quoi les deux grandeurs ne
    décrivent plus le même objet et l'égalité d'empreinte ne prouverait rien."""
    # Résolu à l'usage : `RELEASE_ROOT` est défini plus bas dans ce module, et
    # une constante de niveau module créerait une dépendance d'ordre inutile.
    path = RELEASE_ROOT / "corpus_manifest_authority.json"
    if not path.is_file():
        raise ValueError(
            f"corpus manifest authority is missing at {path.name} — the human "
            "review cannot be bound to a corpus nobody can read"
        )
    raw = path.read_bytes()
    declared = json.loads(raw.decode("utf-8")).get("authority_sha256")
    if declared != CORPUS_MANIFEST_AUTHORITY:
        raise ValueError(
            f"corpus manifest authority declares {str(declared)[:16]}… while this "
            f"release ships {CORPUS_MANIFEST_AUTHORITY[:16]}… — the file and the "
            "release do not describe the same corpus authority"
        )
    return hashlib.sha256(raw).hexdigest()
CANONICAL_EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
CANONICAL_EMBEDDING_REVISION = "3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3"
CANONICAL_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
CANONICAL_RERANKER_REVISION = "c5ee24cb16019beea0893ab7796b1df96625c6b8"
TARGET_TOKENS = 384
#: D-41 — le runtime fait partie des entrées de la release.
#:
#: `chunk_id` dérive du TEXTE des chunks, et le texte dépend de la version de
#: pypdf : 6.14.2 et 6.16.1 produisent deux découpages différents du même PDF.
#: Chacune est déterministe ; la release ne l'est qu'à interpréteur fixé. Le
#: 29/08/2026, une release a été produite hors du venv déclaré et a divergé de
#: la base sur 5 chunks — alors que `check_runtime_conformance.py` avait signalé
#: la divergence le matin même, classée « préexistante » et ignorée.
#:
#: 6.16.1 est en outre MOINS bonne : elle fragmente les mots sur la capitale
#: initiale (`Yoko` -> `Y` + `oko`, `République` -> `R` + `épublique`).
#:
#: La garde ne demande PAS que tous les runtimes concordent — l'image de
#: l'ingestor ne porte aucun pypdf et n'en portera jamais, elle n'extrait pas.
#: Elle demande : mon interpréteur est-il celui qui est déclaré ?
CANONICAL_PYPDF_VERSION = page_policy.CANONICAL_PYPDF_VERSION


def require_canonical_runtime() -> str:
    """D-41 : refuser de sceller hors du runtime déclaré. À la porte."""
    import pypdf as _pypdf

    version = str(_pypdf.__version__)
    if version != CANONICAL_PYPDF_VERSION:
        raise ValueError(
            f"D-41 : pypdf {version} n'est pas le runtime déclaré "
            f"({CANONICAL_PYPDF_VERSION}). Le découpage des chunks en dépend : "
            "produire ici donnerait une release irreproductible ailleurs. "
            "Exécuter le producteur dans le venv du service."
        )
    return version

RELEASE_ROOT = (
    REPOSITORY_ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate"
)
CURRENTNESS_NETWORK_AUDIT_PATH = RELEASE_ROOT / "currentness_network_audit.json"
_HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class ReleaseLineage:
    """Ce qui définit le corpus d'une release : matrice, profils, empreinte.

    Les trois voyagent ENSEMBLE. Les résoudre séparément, en trois endroits,
    est ce qui a permis à `build_release` de travailler sur une lignée que les
    constantes du module ne décrivaient pas."""

    matrix_path: Path
    profile_root: Path
    profile_manifest_path: Path
    expected_content_set_sha256: str
    is_overridden: bool


#: La lignée SERVIE, déclarée ici et nulle part ailleurs : la matrice de
#: production du 31 août et les onze profils de la livraison 319. Une exécution
#: par défaut, depuis le commit candidat, reproduit ce corpus sans qu'aucune
#: variable d'environnement n'ait à être connue.
CANONICAL_LINEAGE = ReleaseLineage(
    matrix_path=REPOSITORY_ROOT / "docs/reports/evidence-index/matrice_production_20260831.json",
    profile_root=REPOSITORY_ROOT
    / "services/rag-engine/configs/ingestion_profiles/v2_livraison_319",
    profile_manifest_path=REPOSITORY_ROOT
    / "services/rag-engine/configs/ingestion_profiles/ingestion_manifest_v2_livraison_319.yml",
    expected_content_set_sha256=CANONICAL_CONTENT_SET_SHA256,
    is_overridden=False,
)


def resolve_release_lineage() -> ReleaseLineage:
    """Résout la lignée, une seule fois, pour tout le producteur.

    **Une surcharge n'éteint jamais l'invariant d'ensemble.** L'expression
    précédente — `FINAL_SET_SHA256 if not NEXUS_FINAL_MATRIX else ""` — faisait
    exactement cela : changer la matrice retirait la vérification d'empreinte,
    si bien qu'une émission surchargée pouvait produire n'importe quel corpus
    sans qu'aucun ensemble déclaré ne s'y oppose. C'était un défaut fail-open
    dans un producteur dont tout le reste est fail-closed.

    Une émission qui vise une autre lignée DOIT donc déclarer l'ensemble
    qu'elle attend, via `NEXUS_FINAL_SET_SHA256`. Épingler reste toujours
    permis ; éteindre ne l'est plus."""
    matrix = os.environ.get("NEXUS_FINAL_MATRIX")
    root = os.environ.get("NEXUS_PROFILE_ROOT")
    manifest = os.environ.get("NEXUS_PROFILE_MANIFEST")
    declared = os.environ.get("NEXUS_FINAL_SET_SHA256")
    overridden = any(value is not None for value in (matrix, root, manifest))

    if overridden and not declared:
        raise ValueError(
            "a lineage override (NEXUS_FINAL_MATRIX / NEXUS_PROFILE_ROOT / "
            "NEXUS_PROFILE_MANIFEST) requires NEXUS_FINAL_SET_SHA256: targeting "
            "another corpus never removes the obligation to declare which one"
        )
    expected = declared or CANONICAL_LINEAGE.expected_content_set_sha256
    if not _HEX64.match(expected):
        raise ValueError(
            f"NEXUS_FINAL_SET_SHA256 must be a lowercase 64-hex SHA-256, got {expected!r}"
        )
    return ReleaseLineage(
        matrix_path=Path(matrix) if matrix else CANONICAL_LINEAGE.matrix_path,
        profile_root=Path(root) if root else CANONICAL_LINEAGE.profile_root,
        profile_manifest_path=(
            Path(manifest) if manifest else CANONICAL_LINEAGE.profile_manifest_path
        ),
        expected_content_set_sha256=expected,
        is_overridden=overridden or bool(declared),
    )


#: Entrées par défaut = celles de la release scellée des onze (lignée B, LOT 1c) :
#: la matrice de production dérivée du 31/08, les onze profils `v2_livraison_319`
#: et leur manifeste au chemin que `authority_bindings.json` lie. Les surcharges
#: d'environnement restent possibles pour une émission différente, mais une
#: production « par défaut » reproduit la lignée servie — plus la lignée A.
#: Vues de la lignée CANONIQUE, pour les appelants qui n'ont pas de contexte
#: d'exécution. Elles ne lisent pas l'environnement : un import ne doit pas
#: échouer, ni changer de sens, selon les variables du shell qui l'entoure.
#: Les usages qui décident quelque chose passent par `resolve_release_lineage()`.
FINAL_MATRIX_PATH = CANONICAL_LINEAGE.matrix_path
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
#: Registre de contenus successeur, dérivé par exécution du registre du 14/08
#: (`deriver_content_ledger.py`, provenance à côté). Le registre du 14/08 reste
#: à son état attesté et n'est plus lu ici.
CONTENT_LEDGER_PATH = (
    REPOSITORY_ROOT / "docs/reports/evidence-index/content_ledger_20260902.jsonl"
)
PLACEMENT_LEDGER_PATH = (
    REPOSITORY_ROOT / "docs/reports/evidence-index/placement_ledger_20260814.jsonl"
)
OLD_RELEASE_ROOT = (
    REPOSITORY_ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027/multilevel"
)
P24_POLICY_PATH = REPOSITORY_ROOT / "services/rag-engine/configs/h2_initial_placement_policy.yml"
#: Quatrième autorité de fait de source, autorisée par ADR-0053 et scellée par
#: son empreinte externe. Elle vit DANS le corpus, sous 00_INDEX_PROVENANCE/ —
#: la zone que le README du corpus désigne comme celle de la traçabilité.
#:
#: Ce qu'elle atteste : `url_source`, l'URL de listing officielle dont le
#: document provient ; `type_document`, sa nature ; les faits bibliographiques.
#: Ce qu'elle N'ATTESTE PAS : aucune affirmation pédagogique, aucune décision de
#: niveau — son champ `niveau` est celui du catalogue amont, faux sur 72,3 % des
#: documents où l'éditeur s'est prononcé.
CATALOGUE_PROVENANCE_PATH = (
    REPOSITORY_ROOT / "docs/reports/evidence-index/eduscol_catalogue_par_scope_20260829.tsv"
)
CATALOGUE_PROVENANCE_SHA256 = (
    "ec5ccbf7a30fec012734061c5fd14761d2079a0bca527320847468a23523c79b"
)
#: Les trois entrées de périmètre sont surchargeables par l'environnement : une
#: seconde émission vise d'autres profils, un autre manifeste et une autre
#: matrice, sans que le producteur ait à être dupliqué. Les défauts restent ceux
#: de la release historique — aucune émission existante ne change de cible.
PROFILE_ROOT = CANONICAL_LINEAGE.profile_root
PROFILE_MANIFEST_PATH = CANONICAL_LINEAGE.profile_manifest_path
COLLECTION_CONFIG_PATH = REPOSITORY_ROOT / "services/rag-engine/configs/rag_collections.yml"


#: Dépôt dont un reçu de revue peut faire autorité ici. Constante du module,
#: comme dans l'outillage de provenance : une revue faite ailleurs ne décide
#: rien pour cette release. Ce n'est pas l'identité d'une campagne, qui,
#: elle, n'apparaît jamais dans ce fichier.
CANONICAL_REPOSITORY = "cyranoaladin/RAG"

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


class VerifiedPdf(NamedTuple):
    """Path identity and immutable bytes verified in one read."""

    path: Path
    content: bytes


def validate_pdf_mirror(
    *, pdf_root: Path, content_sha256: list[str]
) -> dict[str, VerifiedPdf]:
    # Un contenu correspond à UN fichier du miroir : le miroir est 1:1 par
    # nature. Un même document demandé plusieurs fois est la conséquence normale
    # du multi-placement — il est placé dans plusieurs collections — et non une
    # anomalie. La demande se déduplique ; ce qui doit rester unique, c'est le
    # couple (collection, contenu), et c'est `stable_release_order` qui le tient.
    demandes = sorted(set(content_sha256))
    resolved: dict[str, VerifiedPdf] = {}
    root = pdf_root.resolve()
    for content_sha in demandes:
        path = (root / f"{content_sha}.pdf").resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"PDF mirror is missing content {content_sha}")
        content = path.read_bytes()
        if _sha256_bytes(content) != content_sha:
            raise ValueError(f"PDF mirror digest differs for {content_sha}")
        resolved[content_sha] = VerifiedPdf(path=path, content=content)
    return resolved


def stable_release_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ordonner les lignes de release, en refusant le seul doublon qui en est un.

    L'INVARIANT CONSERVÉ — un même contenu ne peut pas être placé deux fois dans
    la MÊME collection. C'est le doublon réel, et il reste refusé.

    LE CONTRÔLE RETIRÉ — un contrôle d'unicité globale du `content_sha256`
    interdisait qu'un contenu apparaisse dans deux collections différentes,
    c'est-à-dire interdisait le MULTI-PLACEMENT. Il contredisait trois sources
    indépendantes du dépôt :

      1. le modèle de données — la migration `004_artifact_placements` déclare
         « identité produit liée au contenu et placements 1:N » ;
      2. le mandat, qui consacre un chapitre au multi-placement ;
      3. la conception du corpus — son README énonce une seule copie canonique
         pour plusieurs affectations : 2 956 affectations pour 2 451 documents,
         dont 505 pour cette raison exacte.

    Il n'avait jamais été éprouvé : la release historique porte 26 placements
    pour 26 artefacts. Ce n'est donc pas un garde-fou que l'on lève, c'est une
    contradiction que l'on retire. Décision opérateur du 29/08/2026.
    """
    keys = [(row.get("collection"), row.get("content_sha256")) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("release contains duplicate collection/content")
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
    """Sceller la totalité du snapshot, sous-répertoires compris.

    Le parcours était `snapshot.iterdir()` — non récursif — filtré par
    `is_file()`, qui écarte les répertoires **sans erreur ni avertissement**.
    Tout sous-répertoire disparaissait donc du sceau, et l'artefact construit
    sur cet inventaire en était amputé.

    Le 27/08/2026, cela a produit un artefact embedding sans `1_Pooling/` :
    conforme à son empreinte, et incapable de se charger — `sentence_transformers`
    lit `modules.json`, ne trouve pas le module de pooling en local, et retombe
    sur un téléchargement distant qui échoue. Le seul garde-fou existant
    (« model inventory has no weights ») protégeait les poids, pas la structure.

    `rglob` aligne ce producteur sur `scripts/e2e/prepare-embedding-model-artifact.sh`,
    qui scelle par `find . -type f`. Les chemins restent relatifs à la racine du
    snapshot, avec un tri déterministe sur le chemin POSIX complet.
    """
    if not snapshot.is_dir():
        raise ValueError(f"model snapshot is missing: {snapshot}")
    manifest_bytes = canonical_json_bytes(manifest)
    rows = [f"{_sha256_bytes(manifest_bytes)}  manifest.json"]
    # `is_file()` suit les liens symboliques, et c'est requis : le cache hub
    # HuggingFace — passé tel quel en `--embedding-snapshot`, son nom devant être
    # la révision — ne contient que des liens vers `../../blobs`. Les exclure
    # viderait l'inventaire. `_file_sha256` scelle le contenu pointé, ce qui est
    # la propriété voulue.
    entries = sorted(
        (path for path in snapshot.rglob("*") if path.is_file()),
        key=lambda item: item.relative_to(snapshot).as_posix(),
    )
    for path in entries:
        relative = path.relative_to(snapshot).as_posix()
        if relative in {"manifest.json", "SHA256SUMS"}:
            continue
        rows.append(f"{_file_sha256(path)}  {relative}")
    if not any(row.endswith("model.safetensors") for row in rows):
        raise ValueError("model inventory has no weights")
    _require_declared_modules_are_present(snapshot)
    return manifest_bytes, ("\n".join(rows) + "\n").encode()


#: Types de modules `sentence_transformers` qui ne portent AUCUN fichier. Un
#: module de ce type n'a pas de répertoire, même dans un artefact complet :
#: exiger le sien refuserait l'instantané qui sert aujourd'hui.
_PARAMETERLESS_MODULE_TYPES = frozenset({"sentence_transformers.models.Normalize"})


def _require_declared_modules_are_present(snapshot: Path) -> None:
    """Un instantané doit contenir les modules que `modules.json` déclare.

    Le 27/08/2026, un artefact embedding a été scellé sans `1_Pooling/` :
    conforme à son empreinte, et incapable de se charger — `sentence_transformers`
    lit `modules.json`, ne trouve pas le module de pooling en local, et retombe
    sur un téléchargement distant qui échoue hors ligne. « Pas de poids, pas
    d'inventaire » protégeait les poids ; rien ne protégeait la structure.

    La règle appliquée est celle que le fichier énonce lui-même, et non une
    liste de fichiers devinée : chaque module déclaré avec un chemin doit
    exister. Un type inconnu et absent fait échouer — un garde-fou qui ne
    reconnaît pas quelque chose se ferme, il ne suppose pas."""
    modules_path = snapshot / "modules.json"
    if not modules_path.is_file():
        # Tout instantané n'est pas un sentence-transformer : le reranker, par
        # exemple, n'a pas de `modules.json` et n'a donc rien à déclarer.
        return
    try:
        declared = json.loads(modules_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"modules.json is not readable in {snapshot}: {exc}") from exc
    if not isinstance(declared, list):
        raise ValueError(f"modules.json must declare a list in {snapshot}")
    for module in declared:
        if not isinstance(module, dict):
            raise ValueError(f"modules.json carries a non-object module in {snapshot}")
        relative = str(module.get("path") or "")
        if not relative:
            continue  # le transformeur racine, déjà couvert par les poids
        if str(module.get("type")) in _PARAMETERLESS_MODULE_TYPES:
            continue
        if not (snapshot / relative).is_dir():
            raise ValueError(
                f"model snapshot {snapshot.name} declares module {relative!r} "
                f"({module.get('type')}) in modules.json but does not carry it — "
                "the artifact would seal cleanly and fail to load"
            )


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


def _load_catalogue_provenance() -> dict[str, dict[str, str]]:
    """Charger le catalogue de provenance après vérification de son empreinte.

    Une autorité non scellée dérive en silence : l'empreinte est vérifiée à
    chaque chargement, et un écart refuse la production plutôt que de sceller
    une release sur une source qui a changé sans qu'on le sache.
    """
    import csv as _csv

    octets = CATALOGUE_PROVENANCE_PATH.read_bytes()
    empreinte = hashlib.sha256(octets).hexdigest()
    if empreinte != CATALOGUE_PROVENANCE_SHA256:
        raise ValueError(
            f"catalogue de provenance non conforme : attendu "
            f"{CATALOGUE_PROVENANCE_SHA256}, obtenu {empreinte}"
        )
    lignes = _csv.DictReader(
        octets.decode("utf-8").splitlines(), delimiter="\t")
    return {ligne["sha256"]: ligne for ligne in lignes}


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
    provenance = _load_catalogue_provenance()
    placement_rows: list[dict[str, Any]] = []
    subject_names = {
        "maths": "mathematiques",
        "physique_chimie": "physique-chimie",
    }
    for matrix_row in matrix:
        collection = matrix_row["dimensions"]["collection"]["value"]
        if collection not in profiles:
            continue
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
            # `OFFICIAL_DOWNLOAD_URLS` est la table figée des documents de la
            # release historique. Un document présent dans `primary_evidence`
            # mais absent de cette table n'a pas d'URL de téléchargement
            # connue : il descend à l'autorité suivante plutôt que de lever.
            elif primary_row and content_sha in OFFICIAL_DOWNLOAD_URLS:
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
                prov = provenance.get(content_sha)
                if prov and prov.get("url_source"):
                    # Quatrième autorité : le catalogue de provenance du corpus.
                    # Il porte l'URL de listing et le type documentaire ; il ne
                    # porte AUCUNE décision de niveau, qui vient des placements.
                    listing_url = prov["url_source"]
                    title = prov.get("titre") or ""
                    type_doc = prov.get("type_document") or "ressource_officielle"
                    # Le catalogue de provenance porte l'URL de LISTING, jamais
                    # l'URL de téléchargement direct. Les deux ne sont pas la
                    # même chose, et présenter l'une pour l'autre serait
                    # affirmer une provenance qu'on n'a pas. Le champ reste vide.
                    download_url = None
                    evidence = _repo_relative(CATALOGUE_PROVENANCE_PATH)
                else:
                    raise ValueError(
                        f"content {content_sha} has no release source fact")
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
            placement_rows.append(
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
    ordered = stable_release_order(placement_rows)
    # L'INVARIANT : l'ensemble produit doit être EXACTEMENT l'ensemble déclaré.
    # Il vaut, et il reste. C'est la CONSTANTE qui figeait le périmètre d'un
    # jour — `!= 26` et une empreinte gravée — comme le faisait `!= 18` pour les
    # profils. Un producteur qui ne peut produire qu'une seule release n'est pas
    # un producteur.
    #
    # L'ensemble déclaré se lit désormais dans son fichier, surchargeable. Le
    # défaut reste celui de la release historique : aucune émission existante ne
    # change de référence.
    attendu = sorted({
        contenu
        for ligne in matrix
        if ligne["dimensions"]["collection"]["value"] in profiles
        for contenu in ligne["content_sha256"]
    })
    produit = sorted({row["content_sha256"] for row in ordered})
    if produit != attendu:
        manquants = len(set(attendu) - set(produit))
        surnumeraires = len(set(produit) - set(attendu))
        raise ValueError(
            f"release source placement_rows differ from the final set: "
            f"{manquants} manquants, {surnumeraires} surnuméraires"
        )
    attendue = resolve_release_lineage().expected_content_set_sha256
    if _final_set_digest(produit) != attendue:
        raise ValueError("release source placement_rows differ from the sealed final set")
    return ordered


def _catalog_documents(placement_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    unique_artifacts = _group_artifact_rows(placement_rows)
    additions = [
        {
            "collection": row["collection"],
            "content_sha256": row["content_sha256"],
            "physical_path": row["physical_path"],
            "source_placement_id": row["source_placement_id"],
        }
        for row in placement_rows
    ]
    payload_sha = _sha256_bytes(_compact_json_bytes(additions))
    delta = {
        "catalog_delta_kind": "PRODUCTION_PROFILE_GATE_CATALOG_PROJECTION_V1",
        "school_year": SCHOOL_YEAR,
        "parent_catalog_path": _repo_relative(DRIVE_MAPPING_PATH),
        "parent_catalog_sha256": _file_sha256(DRIVE_MAPPING_PATH),
        "catalog_delta_payload_sha256": payload_sha,
        "counts": {
            "unique_artifacts": len(unique_artifacts),
            "placements": len(placement_rows),
        },
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
    placement_rows: list[dict[str, Any]], *, delta: Mapping[str, Any], effective: Mapping[str, Any]
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in placement_rows:
        grouped[row["collection"]].append(row)
    collections = []
    # D-44 appliquée aux variables. Ces trois noms ont produit deux fois la même
    # faute dans ce fichier, à mille lignes d'écart : `records` ne disait pas
    # qu'il s'agit de PLACEMENTS, et `all_shas` ne disait pas que la liste en
    # porte un par placement — donc 486 pour 319 documents. Une fois les
    # variables nommées, `len(placement_shas)` sous un champ `unique_artifacts`
    # devient inécrivable.
    placement_shas = sorted(row["content_sha256"] for row in placement_rows)
    unique_shas = sorted(set(placement_shas))
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
            "unique_artifacts": len(unique_shas),
            "placements": len(placement_rows),
            # `physical_objects` compte les FICHIERS SOURCE ; `unique_artifacts`
            # compte les CONTENUS distincts. Ils coïncident tant qu'aucun document
            # n'a été téléchargé deux fois, et l'invariant qui suit le dit :
            # physical_objects >= unique_artifacts, l'égalité signifiant « aucun
            # doublon de fichier ». Deux champs qui doivent s'accorder valent mieux
            # qu'un seul — À CONDITION que quelque chose vérifie l'accord. Rien ne
            # le vérifiait : ils étaient faux ENSEMBLE.
            "physical_objects": len({row["source_path"] for row in placement_rows})
            if all("source_path" in row for row in placement_rows)
            else len(unique_shas),
            # Littéral `0` jusqu'au 30/08/2026 — le champ qui aurait révélé les
            # deux précédents affirmait que leur erreur était impossible. Quatre
            # producteurs frères le CALCULENT déjà (`build_multilevel_release`,
            # `build_wave0_release`, `wave0_release`, `artifact_placement_model`) ;
            # celui-ci était le seul à l'écrire en dur.
            "multi_placement_artifacts": sum(
                1 for count in Counter(placement_shas).values() if count > 1
            ),
        },
        "collection_partition": {
            "production_profile_exact": sorted(grouped),
            "review_required": [],
            "unevaluated": [],
        },
        "candidate_partition": {
            # Une PARTITION de candidats, donc des documents distincts. Elle
            # portait `all_shas` — un sha par placement — et listait donc 167
            # documents deux fois. Le défaut est le même que celui des comptes,
            # dans la charge utile plutôt que dans son cardinal.
            "exact_grade_gate_pending": unique_shas,
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
        if collection not in profiles:
            continue
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
    placements = sorted(
        placements,
        key=lambda row: (row["content_sha256"], row["collection"]),
    )
    contents = sorted({row["content_sha256"] for row in placements})
    # Même famille que `!= 18` et `!= 26` plus haut : l'invariant — l'ensemble
    # des placements couvre exactement l'ensemble déclaré — vaut et reste. La
    # constante figeait le périmètre d'un jour.
    attendu_scope = sorted(
        {
            c
            for ligne in matrix
            if ligne["dimensions"]["collection"]["value"] in profiles
            for c in ligne["content_sha256"]
        }
    )
    if sorted(set(contents)) != attendu_scope:
        raise ValueError(
            f"release scope inputs differ from the final set: "
            f"{len(set(attendu_scope) - set(contents))} manquants, "
            f"{len(set(contents) - set(attendu_scope))} surnuméraires")
    attendue = resolve_release_lineage().expected_content_set_sha256
    if _final_set_digest(contents) != attendue:
        raise ValueError("release scope inputs differ from the sealed final set")
    # La provenance enregistre la source RÉELLEMENT LUE. Ce chemin était figé sur
    # `v2_corpus_complet` alors que le répertoire est paramétré par
    # NEXUS_PROFILE_ROOT : une release produite depuis `v2_livraison_319`
    # affirmait que ses profils venaient des 121. La provenance est précisément ce
    # que cette chaîne existe pour garantir ; un chemin en dur la rendait fausse
    # dès que le paramètre servait.
    profile_root = resolve_release_lineage().profile_root.resolve()
    profile_root_relative = (
        profile_root.relative_to(REPOSITORY_ROOT).as_posix()
        if profile_root.is_relative_to(REPOSITORY_ROOT)
        else profile_root.as_posix()
    )
    for collection in profiles:
        if collection not in profile_sources:
            profile_sources[collection] = f"{profile_root_relative}/{collection}.yml"

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
    # L'invariant est que TOUS les profils du registre sont vérifiés — pas qu'ils
    # soient dix-huit. Le manifeste est la référence, comme pour le verrou du
    # registre corrigé plus haut.
    if len(verified_profiles["profiles"]) != len(profiles):
        raise ValueError(
            f"verified production profile count differs: "
            f"{len(verified_profiles['profiles'])} vérifiés pour "
            f"{len(profiles)} profils")
    return (
        ("\n".join(contents) + "\n").encode("utf-8"),
        canonical_json_bytes(placements),
        canonical_json_bytes(verified_profiles),
    )


def _verify_official_downloads(placement_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    audit = []
    for group in _group_artifact_rows(placement_rows).values():
        row = group["artifact_row"]
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


def _corpus_binding(placement_rows: list[dict[str, Any]]) -> dict[str, str]:
    """Ce que tout audit de fraîcheur NOMME : le corpus qu'il a mesuré.

    Un audit rescellé à côté d'une autre preuve doit rester refusable par le
    lecteur : il porte donc le manifeste corpus et l'ensemble exact de contenus
    (même canonicalisation que `_final_set_digest`)."""
    return {
        "corpus_manifest_sha256": CORPUS_MANIFEST_AUTHORITY,
        "content_set_sha256": _final_set_digest(sorted(_group_artifact_rows(placement_rows))),
    }


def _currentness_network_audit_document(
    network_rows: list[dict[str, Any]],
    *,
    placement_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "audit_kind": "PRODUCTION_PROFILE_GATE_CURRENTNESS_AUDIT_V1",
        **_corpus_binding(placement_rows),
        "verified_at": "2026-08-25T00:00:00Z",
        "network_mode": "READ_ONLY",
        "write_operations": 0,
        "counts": {"verified": len(network_rows), "digest_mismatch": 0},
        "artifacts": network_rows,
    }


def _expected_currentness_network_rows(
    placement_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "content_sha256": row["content_sha256"],
            "current_source_listing_url": row["source_url"],
            "current_download_url": row["current_download_url"],
            "downloaded_sha256": row["content_sha256"],
            "byte_identity": True,
        }
        for group in _group_artifact_rows(placement_rows).values()
        for row in (group["artifact_row"],)
    ]


def _out_of_band_currentness_evidence() -> list[dict[str, str]]:
    """Les rapports qui relatent l'enquête de fraîcheur, avec CE QU'ILS ÉTABLISSENT.

    Le producteur ne fait aucune tentative réseau dans la branche hors ligne ; il
    ne peut donc consigner aucun essai. Ce qu'il peut faire — et ce qui est
    vérifiable — c'est NOMMER les documents qui relatent l'enquête, en sceller
    l'empreinte, et dire ce que chacun établit. Un lecteur peut les ouvrir et
    juger ; il ne peut pas juger un nombre.

    `establishes` décrit ce que le rapport DIT, jamais un décompte d'hypothèses :
    aucune trace structurée n'existe des essais eux-mêmes — ni horodatage par
    requête, ni code de retour par URL. Cette lacune est déclarée ici plutôt que
    comblée : l'inventer serait fabriquer la preuve que cet artefact résume.

    DETTE, ET SON DÉCLENCHEUR — la branche `--verify-official-downloads` de
    `resolve_currentness_network_audit` PRODUIT des lignes de vérification par
    document. Elle n'a pas été empruntée, la source étant injoignable. La première
    émission qui l'empruntera portera des tentatives structurées, et ce champ
    n'aura plus lieu d'être.
    """
    rapports = (
        (
            "docs/reports/gate_currentness_audit_20260829.md",
            "Éduscol répond 403 à toute requête programmée — vérifié sur une URL du "
            "corpus, et constaté aussi avec un User-Agent de navigateur. Le "
            "catalogue de provenance porte l'URL de LISTING, jamais celle de "
            "téléchargement direct.",
        ),
        (
            "docs/reports/lecture_par_agents_20260829.md",
            "Les 24 pages de listing du corpus répondent HTTP 403 Forbidden à une "
            "requête programmée. Aucun document acquis, aucun scellé.",
        ),
        (
            "docs/reports/justification_trois_extensions_20260829.md",
            "education.gouv.fr ET eduscol.education.gouv.fr rendent 403 depuis la "
            "machine de production des releases — le blocage porte sur deux "
            "domaines, non sur un chemin isolé.",
        ),
    )
    sortie: list[dict[str, str]] = []
    for relatif, etablit in rapports:
        chemin = REPOSITORY_ROOT / relatif
        if not chemin.is_file():
            raise FileNotFoundError(
                f"preuve de fraîcheur hors bande introuvable : {relatif}"
            )
        sortie.append(
            {"path": relatif, "sha256": _file_sha256(chemin), "establishes": etablit}
        )
    return sortie


def resolve_currentness_network_audit(
    placement_rows: list[dict[str, Any]],
    *,
    verify_official_downloads: bool,
    audit_path: Path = CURRENTNESS_NETWORK_AUDIT_PATH,
    release_id: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Separate optional live acquisition from deterministic offline replay."""
    if verify_official_downloads:
        network_rows = _verify_official_downloads(placement_rows)
        return (
            _currentness_network_audit_document(network_rows, placement_rows=placement_rows),
            network_rows,
        )

    # LACUNE NOMMÉE ET BORNÉE — décision opérateur du 29/08/2026.
    #
    # Une release ne peut attester que ce qu'elle a vérifié : l'empreinte du
    # contenu et sa date d'acquisition. Pas sa fraîcheur à la source, si la
    # source est injoignable.
    #
    # Le blocage est de CHEMIN, non de source : un fichier direct
    # (`/sites/default/files/document/…pdf`) répond 200, une page de listing
    # (`/5718/ressources-…`) répond 403 — protection anti-robot du CMS. Or les
    # URL de fichier direct n'existent dans aucune preuve en notre possession :
    # ni le catalogue de provenance, ni les registres de contenu et de
    # placement, ni le snapshot Drive. Les découvrir exigerait les pages de
    # listing, qui sont précisément ce qui refuse.
    #
    # On NOMME le trou, on ne le comble pas d'une affirmation. C'est le
    # précédent COVERAGE_GAP, appliqué à la fraîcheur. Cette lacune est bornée :
    # elle ne relâche AUCUN autre contrôle — empreintes, scellement, unicité,
    # gate de revue restent exercés à l'identique.
    # La déclaration prime sur la lecture : l'audit scellé du dépôt couvre un
    # AUTRE périmètre — les 26 documents de la release historique. Le confronter
    # à une émission de 2 389 documents ne mesurerait rien.
    if os.environ.get("NEXUS_CURRENTNESS_UNVERIFIED") == "SOURCE_UNREACHABLE":
        return {
            "audit_kind": "PRODUCTION_PROFILE_GATE_CURRENTNESS_AUDIT_V1",
            **_corpus_binding(placement_rows),
            "network_mode": "UNVERIFIED",
            "currentness_status": "CURRENTNESS_UNVERIFIED_SOURCE_UNREACHABLE",
            "reason": (
                "eduscol.education.gouv.fr répond 403 aux pages de listing "
                "(protection anti-robot) ; les URL de fichier direct, seules "
                "joignables, ne figurent dans aucune preuve du corpus"
            ),
            "corpus_harvested_at": "2026-08-04/2026-08-05",
            "corpus_sealed_at": "2026-08-08",
            "verified_at": None,
            "artifacts": [],
            # CE QUI A RÉELLEMENT EU LIEU — et rien de plus.
            #
            # Cette branche ne fait AUCUNE requête réseau : c'est le rejeu hors
            # ligne. Elle ne peut donc consigner aucune tentative, et le déclare.
            # Le verdict repose sur une enquête menée HORS de ce producteur, dont
            # les rapports sont nommés et scellés par leur empreinte : ils sont
            # vérifiables, eux.
            "attempts": [],
            "attempts_made_by_this_producer": False,
            "out_of_band_evidence": _out_of_band_currentness_evidence(),
            # La portée du verdict est DÉRIVÉE de la release, jamais recomptée
            # ici : « s'applique aux documents de cette release ».
            "verdict_scope": {
                "kind": "RELEASE_WIDE",
                # La portée nomme LA release qui embarque ce verdict, pas la
                # constante historique du module. Une candidate qui hériterait
                # de l'identifiant d'une autre release ferait lire à l'auditeur
                # — seul consommateur déclaré de ce champ — une portée qui
                # n'est pas la sienne.
                "release_id": release_id or RELEASE_ID,
                "school_year": SCHOOL_YEAR,
                # Un champ scellé que rien ne lit à l'exécution a exactement un
                # consommateur : l'humain qui vérifie une release et ne peut pas
                # la recompter à la main. Sans ce champ, il ignore si le verdict
                # d'invérifiabilité porte sur quelques documents ou sur toute la
                # livraison — et c'est la première question qu'il se posera.
                # Le consommateur est donc DÉCLARÉ, plutôt que laissé implicite.
                "consumer": "auditeur humain ; aucun consommateur machine",
            },
            # `verified` et `digest_mismatch` valent 0 et s'accordent à une charge
            # utile vide : zéro tentative, zéro vérification, zéro divergence.
            #
            # `unverified_source_unreachable: len(placement_rows)` est RETIRÉ. Il
            # valait 486 pour une charge utile de 0 entrée — un compte sans sujet.
            # Son nom promettait N déterminations individuelles que personne n'a
            # faites ; le peupler de 319 entrées fabriquerait la preuve qu'il
            # prétendait résumer, ce qui est la seule façon de rendre un artefact
            # de preuve pire qu'un artefact vide. Aucun lecteur ne s'en servait.
            "counts": {"verified": 0, "digest_mismatch": 0},
            "write_operations": 0,
        }, []
    if not audit_path.is_file():
        raise ValueError("sealed currentness audit is missing")
    network_audit = _load_json(audit_path)
    expected_rows = _expected_currentness_network_rows(placement_rows)
    expected_audit = _currentness_network_audit_document(
        expected_rows, placement_rows=placement_rows
    )
    if network_audit != expected_audit:
        raise ValueError("sealed currentness audit differs from release inputs")
    return network_audit, expected_rows


def _currentness_documents(
    placement_rows: list[dict[str, Any]],
    *,
    inventory: Mapping[str, Any],
    inventory_sha256: str,
    network_audit: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    network_rows = network_audit["artifacts"]
    audit_sha = _sha256_bytes(canonical_json_bytes(network_audit))
    by_sha = {row["content_sha256"]: row for row in network_rows}
    #: Quand la fraîcheur n'a pas pu être vérifiée, chaque document porte la
    #: LACUNE NOMMÉE plutôt qu'une ligne réseau absente. On ne fabrique pas une
    #: vérification qui n'a pas eu lieu : on inscrit qu'elle n'a pas eu lieu, et
    #: pourquoi. `byte_identity` reste `None` — ni vrai, ni faux : inconnu.
    non_verifie = network_audit.get(
        "currentness_status") == "CURRENTNESS_UNVERIFIED_SOURCE_UNREACHABLE"
    grouped = _group_artifact_rows(placement_rows)
    artifacts = []
    for group in grouped.values():
        row = group["artifact_row"]
        placement_facts = [
            {
                "collection": placement["collection"],
                "source_placement_id": placement["source_placement_id"],
                "external_level": placement["external_level"],
                "external_subject": placement["external_subject"],
                "external_scope": placement["external_scope"],
                "external_document_type": placement["external_document_type"],
            }
            for placement in group["placement_rows"]
        ]
        if non_verifie:
            network = {
                "content_sha256": row["content_sha256"],
                "byte_identity": None,
                "current_download_url": row.get("current_download_url"),
                "current_source_listing_url": row.get("source_url"),
                "currentness_status": "CURRENTNESS_UNVERIFIED_SOURCE_UNREACHABLE",
                "http_status": None,
                "verified_at": None,
            }
        else:
            network = by_sha[row["content_sha256"]]
        decision = "REVIEW_REQUIRED" if non_verifie else "CURRENT"
        effective_currentness = None if non_verifie else "actuel"
        current_source_listing_url = None if non_verifie else row["source_url"]
        current_download_url = None if non_verifie else network["current_download_url"]
        current_download_sha256 = None if non_verifie else row["content_sha256"]
        byte_identity = None if non_verifie else True
        artifacts.append(
            {
                "content_sha256": row["content_sha256"],
                "exact_path": row["physical_path"],
                "collections": sorted(
                    placement["collection"]
                    for placement in group["placement_rows"]
                ),
                "placement_facts": placement_facts,
                "decision": decision,
                "reason_codes": [
                    "CURRENT_SOURCE_UNREACHABLE_NOT_AUDITED"
                    if non_verifie
                    else "OFFICIAL_CURRENT_BYTE_IDENTITY_EXACT"
                ],
                "effective_currentness": effective_currentness,
                "current_for_school_year": SCHOOL_YEAR,
                "current_source_listing_url": current_source_listing_url,
                "current_download_url": current_download_url,
                "current_download_sha256": current_download_sha256,
                "byte_identity": byte_identity,
                # `drive_file_id` NE FIGURE PLUS ICI, délibérément.
                #
                # Le dossier Drive du corpus est en {"role":"writer","type":"anyone"} :
                # un identifiant de fichier y est un CHEMIN D'ACCÈS EN ÉCRITURE, pas
                # une référence documentaire. Publier 389 identifiants sur un dépôt
                # public, c'était publier 389 poignées permettant d'altérer les
                # documents sources — et une altération non détectée serait servie
                # à des élèves avec l'apparence de l'officiel.
                #
                # La preuve n'y perd rien : `byte_identity` est établie par
                # `current_download_sha256 == content_sha256`, et c'est elle qui
                # atteste la fraîcheur. L'identifiant n'ajoutait que
                # l'ATTEIGNABILITÉ, qui est précisément ce qui ne doit pas être
                # publié. `drive_modified_time` reste : c'est une date, pas une
                # poignée.
                "drive_modified_time": row["drive_modified_time"],
            }
        )
    evidence = {
        "evidence_kind": "MULTILEVEL_ARTIFACT_CURRENTNESS_V2",
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
        "decision_basis": (
            "Official source unreachable; no currentness fact measured"
            if non_verifie
            else "Official Eduscol URL downloaded read-only and byte-matched"
        ),
        "counts": {
            "unique_artifacts": len(grouped),
            "evaluated": len(grouped),
            "current": 0 if non_verifie else len(grouped),
            "review_required": len(grouped) if non_verifie else 0,
            "unevaluated": 0,
        },
        "partition": {
            "current": [] if non_verifie else sorted(grouped),
            "review_required": sorted(grouped) if non_verifie else [],
            "unevaluated": [],
        },
        "artifacts": artifacts,
    }
    return network_audit, evidence


_INTRINSIC_ARTIFACT_ROW_FIELDS = (
    "physical_path",
    "drive_file_id",
    "drive_modified_time",
    "drive_size",
    "source_url",
    "current_download_url",
    "title",
    "external_document_type",
    "year",
    "source_evidence",
)


def _group_artifact_rows(
    placement_rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Regrouper les placements sans choisir arbitrairement des faits documentaires."""
    rows_by_sha: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in placement_rows:
        rows_by_sha[str(row["content_sha256"])].append(row)

    grouped: dict[str, dict[str, Any]] = {}
    for sha in sorted(rows_by_sha):
        rows = sorted(
            rows_by_sha[sha],
            key=lambda row: (
                str(row.get("collection", "")),
                str(row.get("source_placement_id", "")),
                str(row.get("external_scope", "")),
            ),
        )
        reference = rows[0]
        for field in _INTRINSIC_ARTIFACT_ROW_FIELDS:
            expected = (field in reference, reference.get(field))
            if any((field in row, row.get(field)) != expected for row in rows[1:]):
                raise ValueError(
                    f"intrinsic artifact field {field} differs for {sha}"
                )
        grouped[sha] = {
            "artifact_row": reference,
            "placement_rows": rows,
        }
    return grouped


def _corpus_descriptor(placement_rows: list[dict[str, Any]]) -> dict[str, Any]:
    unique_shas = sorted(_group_artifact_rows(placement_rows))
    return {
        "authority_kind": "SEALED_CORPUS_MANIFEST_REFERENCE_V1",
        "authority_sha256": CORPUS_MANIFEST_AUTHORITY,
        "content_ledger_path": _repo_relative(CONTENT_LEDGER_PATH),
        "content_ledger_sha256": _file_sha256(CONTENT_LEDGER_PATH),
        "final_content_count": len(unique_shas),
        "final_content_set_sha256": _final_set_digest(unique_shas),
    }


class ReviewAuthorityInputs(NamedTuple):
    """Les quatre entrées qui portent la décision humaine, toutes injectées.

    Aucune n'est dérivée d'un chemin en dur : faire tourner une autre campagne
    de revue ne doit toucher aucune ligne de ce producteur."""

    decision_set_path: Path | None
    receipt_path: Path | None
    trust_anchor_path: Path | None
    review_index_path: Path | None
    reviewers: tuple[str, ...]
    environment: str = "production"

    @property
    def declared(self) -> bool:
        return self.decision_set_path is not None


#: « Aucune autorité de revue fournie ». Ce n'est pas une permission : toute
#: détection rencontrée sans décision scellée est alors refusée. Le défaut
#: existe pour qu'un appelant qui n'a rien à projeter n'ait pas à fabriquer
#: une autorité vide, jamais pour rendre la revue facultative.
NO_REVIEW_AUTHORITY = ReviewAuthorityInputs(None, None, None, None, ())


def _load_review_authority(
    inputs: ReviewAuthorityInputs,
) -> tuple[dict[str, Any] | None, dict[str, str], dict[str, str]]:
    """Vérifie la chaîne d'autorité et rend (décisions, paquets, empreintes).

    Les paquets viennent de l'INDEX, jamais de la décision elle-même :
    confronter une décision à sa propre revendication de paquet ne prouverait
    rien. Les empreintes rendues rejoignent la chaîne d'autorité de la release
    (§7) — celle du NOUVEAU candidat, jamais d'une release historique."""
    if not inputs.declared:
        return None, {}, {}

    assert inputs.decision_set_path is not None
    for label, path in (
        ("decision set", inputs.decision_set_path),
        ("review receipt", inputs.receipt_path),
        ("trust anchor", inputs.trust_anchor_path),
        ("review index", inputs.review_index_path),
    ):
        if path is None or not path.is_file():
            raise ValueError(
                f"the PII {label} is required to project a human review and is absent"
            )
    assert inputs.receipt_path and inputs.trust_anchor_path and inputs.review_index_path

    raw_decision_set = inputs.decision_set_path.read_bytes()
    raw_receipt = inputs.receipt_path.read_bytes()
    anchor_bytes = inputs.trust_anchor_path.read_bytes()
    try:
        anchor = TrustAnchor.model_validate(json.loads(anchor_bytes.decode("utf-8")))
    except Exception as exc:  # noqa: BLE001 - frontière de parsing
        raise ValueError(f"the review trust anchor is not usable: {exc}") from exc

    try:
        decision_set, _binding = verify_pii_review_decision_authority(
            decision_set_bytes=raw_decision_set,
            receipt_bytes=raw_receipt,
            trust_anchor=anchor,
            environment=inputs.environment,  # type: ignore[arg-type]
            expected_repository=CANONICAL_REPOSITORY,
            accepted_reviewers=inputs.reviewers or None,
            now=datetime.now(UTC),
        )
    except ReviewBindingError as exc:
        raise ValueError(f"the PII review authority is refused: {exc}") from exc

    index = json.loads(inputs.review_index_path.read_text(encoding="utf-8"))
    bundles = {
        str(entry["content_sha256"]): str(entry["bundle_sha256"])
        for entry in index.get("bundles", [])
    }
    # Inconditionnel. La comparaison était sautée si l'index déclarait
    # `review_index_sha256_declared` — une clé qui vit DANS le fichier vérifié.
    # Quiconque fournissait l'index pouvait donc la poser et éteindre le seul
    # contrôle qui le lie à la campagne scellée. Un champ ne décide jamais s'il
    # est lui-même vérifié.
    indexed_digest = _sha256_bytes(inputs.review_index_path.read_bytes())
    if indexed_digest != decision_set.review_index_sha256:
        raise ValueError(
            "the decision set was sealed against review index "
            f"{decision_set.review_index_sha256[:16]}… while the supplied review index "
            f"hashes to {indexed_digest[:16]}… — they are not the same campaign"
        )

    digests = {
        "pii_decision_set_sha256": _sha256_bytes(raw_decision_set),
        "pii_review_receipt_sha256": _sha256_bytes(raw_receipt),
        "pii_review_trust_anchor_sha256": _sha256_bytes(anchor_bytes),
        "pii_review_index_sha256": _sha256_bytes(inputs.review_index_path.read_bytes()),
    }
    return json.loads(raw_decision_set.decode("utf-8")), bundles, digests


#: Statuts qui rendraient une release promouvable ou activable. Une candidate
#: n'a jamais le droit de les porter : le gate PII n'est qu'un des gates de
#: go-live, et C1-C6 restent ouverts tant qu'ils ne sont pas prouvés.
_ACTIVATING_PROMOTION = "PROMOTABLE"
_ACTIVATING_ACTIVATION = "PRODUCTION_ACTIVATION_ALLOWED"


#: Les seuls modes de release que le producteur sait traiter. Un mode absent de
#: cet ensemble est refusé, jamais rattaché par défaut au cas permissif.
_SUPPORTED_RELEASE_MODES = frozenset({"production", "rehearsal"})


def resolve_release_lifecycle_statuses(
    *,
    release_mode: str,
    release_id: str | None = None,
    promotion_status: str | None,
    activation_status: str | None,
    review_status: str | None,
) -> dict[str, str | None]:
    """Résout les statuts d'une release, et refuse une production activable.

    **Le cycle de vie ne se déduit pas du NOM.** La version précédente écrivait
    `is_candidate = release_id is not None` : une production utilisant le
    `release_id` par défaut — cas légitime, le paramètre valant `None` — était
    donc traitée comme non-candidate et transmettait des statuts activables au
    manifeste. Le nom d'une release ne dit rien de son cycle de vie.

    Le signal juste est le MODE. Une release de production n'est jamais émise
    activable : la promotion se gagne aux gates de go-live, pas par un argument
    de producteur. `release_id` n'entre pas dans la décision, et n'est présent
    ici que pour rendre cette indifférence explicite et testable.

    Une demande activante n'est pas silencieusement corrigée mais REFUSÉE : un
    appel qui la formule est un appel qui se trompe, et écraser sa demande sans
    rien dire lui laisserait croire qu'il l'a obtenue."""
    del release_id  # jamais un signal de cycle de vie — voir la docstring
    # Un mode inconnu n'est pas « pas la production » : c'est une demande qui
    # ne veut rien dire. La traiter comme un simple non-production faisait
    # passer `staging` — ou une faute de frappe — à travers la garde, en
    # conservant des statuts activables. Le refus est explicite.
    if release_mode not in _SUPPORTED_RELEASE_MODES:
        raise ValueError(
            f"release_mode={release_mode!r} is not supported — expected one of "
            f"{sorted(_SUPPORTED_RELEASE_MODES)}; an unknown mode must not inherit "
            "the lenient branch and keep activatable statuses"
        )
    if release_mode != "production":
        return {
            "promotion_status": promotion_status,
            "activation_status": activation_status,
            "review_status": review_status,
        }
    refused = []
    if promotion_status == _ACTIVATING_PROMOTION:
        refused.append(f"promotion_status={_ACTIVATING_PROMOTION}")
    if activation_status == _ACTIVATING_ACTIVATION:
        refused.append(f"activation_status={_ACTIVATING_ACTIVATION}")
    if refused:
        raise ValueError(
            f"a production release cannot be asked to be activable ({', '.join(refused)}): "
            "promotion is earned at the go-live gates, not requested from the producer"
        )
    return {
        "promotion_status": promotion_status or "NOT_PROMOTABLE",
        "activation_status": activation_status or "NO_PRODUCTION_ACTIVATION",
        "review_status": review_status,
    }


def _pii_evidence(
    placement_rows: list[dict[str, Any]],
    *,
    pdfs: Mapping[str, VerifiedPdf],
    inventory_sha256: str,
    review_authority: ReviewAuthorityInputs = NO_REVIEW_AUTHORITY,
) -> dict[str, Any]:
    patterns = load_patterns_from_config(PII_POLICY_PATH)
    grouped = _group_artifact_rows(placement_rows)
    policy_sha = _file_sha256(PII_POLICY_PATH)
    scanner_sha = _file_sha256(PII_SCANNER_PATH)
    page_policy_sha = page_policy.policy_source_sha256()

    decision_document, review_bundles, authority_digests = _load_review_authority(
        review_authority
    )

    # ── LE SCAN MESURE, LA REVUE DÉCIDE ─────────────────────────────────
    #
    # Le scan enregistre ce qu'il trouve, sans rien exclure ni rien admettre :
    # sa précision mesurée (2 vrais positifs sur 20 correspondances tirées au
    # hasard) ne lui donne pas qualité à trancher. La raison est structurelle,
    # pas un défaut de réglage — le corpus ENSEIGNE le courriel, les en-têtes,
    # l'encodage et les formats de contact, si bien qu'un détecteur de données
    # personnelles passé sur du matériel pédagogique qui porte sur les formats
    # de données personnelles se déclenche sur la pédagogie.
    #
    # C'est donc une revue humaine, décision par décision, contenu par contenu,
    # scellée et signée, qui décide (ADR-0047). Ce producteur ne fait que
    # projeter son résultat : il n'ajoute aucun jugement, et il refuse dès que
    # son scan et cette revue ne décrivent pas le même monde.
    scanned: list[ScannedContent] = []
    for sha, group in grouped.items():
        row = group["artifact_row"]
        pdf = pdfs[sha]
        result = scan_pdf_bytes(
            pdf.content,
            source_path=str(pdf.path),
            patterns=patterns,
        )
        if result.sha256 != row["content_sha256"]:
            raise ValueError(f"PII scan digest differs for {row['content_sha256']}")
        if result.extraction_error:
            raise ValueError(
                f"PII scan could not read {row['content_sha256']} — "
                f"{result.extraction_error}"
            )
        findings: list[ScannedFinding] = []
        if result.matches:
            # Les textes de page ne sont ré-extraits que pour les contenus qui
            # portent une correspondance — 23 sur 320 — parce que le contexte
            # scellé se calcule sur le texte de page brut, et sur lui seul.
            pages_text, _ignored, page_error = (
                extract_pdf_pages_with_structural_empty_pages(pdf.content)
            )
            if page_error:
                raise ValueError(
                    f"page text extraction failed for {row['content_sha256']} — {page_error}"
                )
        for match in result.matches:
            match_sha = _sha256_bytes(match.match_text.encode("utf-8"))
            page_text = pages_text[(match.page_number or 1) - 1]
            findings.append(
                ScannedFinding(
                    # Identité et contexte viennent de l'autorité unique : ce
                    # sont eux qui rendent les findings du scan comparables à
                    # ceux que la revue humaine a dispositionnés. Le contexte
                    # de confort du scanner (50 caractères, sauts de ligne
                    # remplacés) n'est PAS celui que le paquet a figé.
                    finding_id=finding_identity(
                        content_sha256=row["content_sha256"],
                        pattern_id=match.pattern_id,
                        page_number=match.page_number,
                        char_offset=match.char_offset,
                        match_sha256=match_sha,
                    ),
                    pattern_id=match.pattern_id,
                    page=match.page_number or 1,
                    match_sha256=match_sha,
                    context_sha256=_sha256_bytes(
                        finding_context(
                            page_text,
                            char_offset=match.char_offset,
                            match_length=len(match.match_text),
                        ).encode("utf-8")
                    ),
                )
            )
        scanned.append(
            ScannedContent(
                content_sha256=row["content_sha256"],
                pages_scanned=result.pages_scanned,
                characters_scanned=result.characters_scanned,
                ignored_empty_pages=tuple(result.ignored_empty_pages),
                findings=tuple(findings),
            )
        )

    try:
        projection = project_pii_review(
            scanned,
            decision_set_document=decision_document,
            review_bundles=review_bundles,
            policy_sha256=policy_sha,
            scanner_sha256=scanner_sha,
            page_policy_sha256=page_policy_sha,
            # L'empreinte du FICHIER, jamais la valeur qu'il déclare : c'est
            # celle que l'ensemble de décisions humaines a enregistrée.
            corpus_manifest_sha256=corpus_manifest_authority_file_sha256(),
        )
    except PiiProjectionError as exc:
        raise ValueError(f"the PII review cannot be projected on this scan: {exc}") from exc

    source_by_sha = {
        group["artifact_row"]["content_sha256"]: group["artifact_row"]["physical_path"]
        for group in grouped.values()
    }
    results = [
        {
            **entry,
            "evidence_sha256": _sha256_bytes(_compact_json_bytes(entry)),
            "source_path": source_by_sha[entry["content_sha256"]],
        }
        for entry in projection.entries
    ]

    # `raw_pii_in_output: false`, plus bas, était une CONSTANTE : le producteur
    # certifiait que sa preuve ne porte aucune matière brute sans l'avoir
    # regardée. La mesure a lieu ici, sur les résultats réellement produits, et
    # avant l'attestation qui en dépend. Un finding est un refus.
    require_no_raw_pii({"results": results}, label="pii_evidence.results", patterns=patterns)

    return {
        "evidence_kind": "REAL_CORPUS_PII_SCAN",
        "school_year": SCHOOL_YEAR,
        "candidate_inventory_sha256": inventory_sha256,
        "corpus_manifest_sha256": CORPUS_MANIFEST_AUTHORITY,
        "policy_version": "pii_gate_policy_h2b_v5",
        "policy_sha256": _file_sha256(PII_POLICY_PATH),
        "scanner_version": "production-profile-gate-v1",
        "scanner_sha256": _file_sha256(PII_SCANNER_PATH),
        "page_policy_id": page_policy.POLICY_ID,
        "page_policy_sha256": page_policy.policy_source_sha256(),
        "required_pdf_path_count": len(grouped),
        "remote_access_mode": "READ_ONLY",
        "remote_write_operations": 0,
        "raw_pii_in_output": False,
        "raw_pii_in_logs": False,
        "decision_set_id": projection.decision_set_id,
        **authority_digests,
        "summary": {
            "unique_contents_required": len(grouped),
            "unique_contents_scanned": len(grouped),
            "pii_scan_coverage": 1.0,
            "unique_contents_not_scanned": 0,
            "sha256_mismatches": 0,
            # Sept dimensions distinctes, toutes DÉRIVÉES des ensembles. Les
            # fondre en « combien sont propres » rendrait invisible la
            # différence entre « rien trouvé » et « trouvé, examiné, admis ».
            **projection.counts,
        },
        "results": results,
    }


def _preflight(
    placement_rows: list[dict[str, Any]],
    *,
    pdfs: Mapping[str, VerifiedPdf],
    token_counter: CanonicalTokenCounter,
    pii_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    require_canonical_token_counter(token_counter)
    artifacts = []
    chunks_total = 0
    grouped = _group_artifact_rows(placement_rows)
    if set(pdfs) != set(grouped):
        raise ValueError("verified PDF SHA population differs from preflight")
    raw_pii_results = pii_evidence.get("results")
    if not isinstance(raw_pii_results, list):
        raise ValueError("PII evidence results must be a list")
    pii_by_sha: dict[str, tuple[int, ...]] = {}
    for evidence_row in raw_pii_results:
        if not isinstance(evidence_row, dict):
            raise ValueError("PII evidence result must be an object")
        evidence_sha = evidence_row.get("content_sha256")
        if not isinstance(evidence_sha, str) or evidence_sha in pii_by_sha:
            raise ValueError("PII evidence SHA population is not unique")
        raw_ignored = evidence_row.get("ignored_empty_pages")
        if not isinstance(raw_ignored, list) or any(
            type(page) is not int for page in raw_ignored
        ):
            raise ValueError("PII ignored_empty_pages must contain strict integers")
        ignored = tuple(raw_ignored)
        if ignored != tuple(sorted(set(ignored))):
            raise ValueError("PII ignored_empty_pages must be strictly increasing")
        pii_by_sha[evidence_sha] = ignored
    if set(pii_by_sha) != set(grouped):
        raise ValueError("PII evidence SHA population differs from preflight")

    for sha, group in grouped.items():
        row = group["artifact_row"]
        content = pdfs[sha].content
        if _sha256_bytes(content) != sha:
            raise ValueError(f"verified PDF digest differs for {sha}")
        pages_text, authoritative_ignored, extraction_error = (
            extract_pdf_pages_with_structural_empty_pages(content)
        )
        if extraction_error:
            raise ValueError(
                f"preflight extraction failed for {sha} — {extraction_error}"
            )
        page_count = len(pages_text)
        declared_ignored = pii_by_sha[sha]
        if any(page < 1 or page > page_count for page in declared_ignored):
            raise ValueError(f"PII ignored_empty_pages is out of bounds for {sha}")
        if declared_ignored != authoritative_ignored:
            raise ValueError(
                f"PII ignored_empty_pages differs from authoritative extraction "
                f"for {sha}"
            )
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
        covered_pages = {
            page
            for chunk in chunk_rows
            for page in range(chunk["page_start"], chunk["page_end"] + 1)
        }
        ignored_pages = set(authoritative_ignored)
        expected_pages = set(range(1, page_count + 1))
        overlap = covered_pages & ignored_pages
        if overlap:
            raise ValueError(
                f"covered/ignored page overlap for {sha}: {sorted(overlap)}"
            )
        out_of_bounds = (covered_pages | ignored_pages) - expected_pages
        if out_of_bounds:
            raise ValueError(
                f"page partition is out of bounds for {sha}: {sorted(out_of_bounds)}"
            )
        unexplained = expected_pages - covered_pages - ignored_pages
        if unexplained:
            raise ValueError(
                f"page partition has uncovered pages for {sha}: "
                f"{sorted(unexplained)}"
            )
        chunks_total += len(chunk_rows)
        artifacts.append(
            {
                "content_sha256": row["content_sha256"],
                "source_path": row["physical_path"],
                "page_count": page_count,
                "ignored_empty_pages": list(authoritative_ignored),
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
            "unique_artifacts": len(artifacts),
            "pages": sum(row["page_count"] for row in artifacts),
            "chunks": chunks_total,
            "empty_pages": sum(
                len(row["ignored_empty_pages"]) for row in artifacts
            ),
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


def _placement(
    row: Mapping[str, Any],
    *,
    profile: Any,
    status: str,
    include_artifact_id: bool,
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
    if include_artifact_id:
        placement["artifact_id"] = sha
    return placement


def _artifact(
    row: Mapping[str, Any],
    *,
    profile: Any,
    status: str,
    preflight: Mapping[str, Any],
    type_doc_mapping: Mapping[str, str],
) -> dict[str, Any]:
    sha = row["content_sha256"]
    placement = _placement(
        row,
        profile=profile,
        status=status,
        include_artifact_id=False,
    )
    placement_id = placement["placement_id"]
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
        "source_url": row["current_download_url"] or row["source_url"],
        "current_download_url": row["current_download_url"],
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


def _global_artifact(
    row: Mapping[str, Any],
    *,
    preflight: Mapping[str, Any],
    type_doc_mapping: Mapping[str, str],
) -> dict[str, Any]:
    sha = str(row["content_sha256"])
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
        "artifact_id": sha,
        "content_sha256": sha,
        "source_path": row["physical_path"],
        "source_url": row["current_download_url"] or row["source_url"],
        "title": row["title"],
        "type_doc": type_doc_mapping[row["external_document_type"]],
        "page_count": preflight["page_count"],
        "ignored_empty_pages": list(preflight["ignored_empty_pages"]),
        "chunks": chunks,
        "chunk_id_set_digest": _set_digest(
            [chunk["chunk_id"] for chunk in chunks]
        ),
        "chunk_sha256_set_digest": _set_digest(
            [chunk["chunk_sha256"] for chunk in chunks]
        ),
        "page_coverage_digest": _set_digest(pages),
    }


def _release_topology_documents(
    placement_rows: list[dict[str, Any]],
    *,
    profiles: Mapping[str, Any],
    profile_manifest_digest: str,
    collection_config: Mapping[str, Any],
    preflight_by_sha: Mapping[str, Mapping[str, Any]],
    type_doc_mapping: Mapping[str, str],
    authorities: Mapping[str, str],
    models: Mapping[str, Any],
    release_root: Path,
    release_id: str,
    school_year: str,
    release_mode: str = "production",
    promotion_status: str | None = None,
    activation_status: str | None = None,
    review_status: str | None = None,
) -> dict[Path, bytes]:

    grouped_artifacts = _group_artifact_rows(placement_rows)
    artifact_shas = set(grouped_artifacts)
    preflight_shas = set(preflight_by_sha)
    if preflight_shas != artifact_shas:
        missing = sorted(artifact_shas - preflight_shas)
        extra = sorted(preflight_shas - artifact_shas)
        raise ValueError(
            "preflight population differs from artifacts: "
            f"missing={missing}, extra={extra}"
        )
    for sha, group in grouped_artifacts.items():
        preflight = preflight_by_sha[sha]
        if preflight.get("content_sha256") != sha:
            raise ValueError(
                f"preflight content identity differs for {sha}: "
                f"{preflight.get('content_sha256')!r}"
            )
        physical_path = group["artifact_row"]["physical_path"]
        if preflight.get("source_path") != physical_path:
            raise ValueError(
                f"preflight source path differs for {sha}: "
                f"{preflight.get('source_path')!r} != {physical_path!r}"
            )

    placement_collections = {
        str(row["collection"])
        for group in grouped_artifacts.values()
        for row in group["placement_rows"]
    }
    profile_collections = set(profiles)
    if profile_collections != placement_collections:
        profiles_without_placement = sorted(
            profile_collections - placement_collections
        )
        placements_without_profile = sorted(
            placement_collections - profile_collections
        )
        raise ValueError(
            "profile collections differ from placement collections: "
            f"profiles_without_placement={profiles_without_placement}, "
            f"placements_without_profile={placements_without_profile}"
        )

    artifacts = [
        _global_artifact(
            group["artifact_row"],
            preflight=preflight_by_sha[sha],
            type_doc_mapping=type_doc_mapping,
        )
        for sha, group in grouped_artifacts.items()
    ]
    unique_chunk_count = sum(len(artifact["chunks"]) for artifact in artifacts)
    artifact_registry = {
        "release_kind": "MULTILEVEL_ARTIFACT_REGISTRY_V2",
        "release_id": release_id,
        "school_year": school_year,
        "expected_counts": {
            "unique_artifacts": len(artifacts),
            "unique_chunks": unique_chunk_count,
        },
        "artifacts": artifacts,
    }
    artifact_registry_path = release_root / "artifacts.release.json"
    artifact_registry_raw = canonical_json_bytes(artifact_registry)
    artifact_registry_sha = _sha256_bytes(artifact_registry_raw)

    placements_by_collection: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sha, group in grouped_artifacts.items():
        for row in group["placement_rows"]:
            collection = str(row["collection"])
            placement = _placement(
                row,
                profile=profiles[collection],
                status=collection_config[collection]["statut"],
                include_artifact_id=True,
            )
            if placement["artifact_id"] != sha:
                raise ValueError("placement artifact identity differs from its group")
            placements_by_collection[collection].append(placement)

    documents: dict[Path, bytes] = {
        artifact_registry_path: artifact_registry_raw,
    }
    subjects: list[dict[str, str]] = []
    for collection in sorted(placements_by_collection):
        profile = profiles[collection]
        placements = sorted(
            placements_by_collection[collection],
            key=lambda placement: (placement["artifact_id"], placement["placement_id"]),
        )
        subject = {
            "release_kind": "MULTILEVEL_SUBJECT_RELEASE_V2",
            "release_id": f"{release_id}-{collection}",
            "school_year": school_year,
            "collection": collection,
            "programme_version": str(profile.scope.programme_version),
            "authorities": dict(authorities),
            "profile": {
                "version": profile.profile_version,
                "fingerprint": profile_fingerprint(profile),
                "manifest_digest": profile_manifest_digest,
            },
            "models": dict(models),
            "artifact_registry": {
                "path": "../artifacts.release.json",
                "sha256": artifact_registry_sha,
            },
            "expected_counts": {
                "unique_artifact_references": len(
                    {placement["artifact_id"] for placement in placements}
                ),
                "placements": len(placements),
            },
            "placements": placements,
        }
        path = release_root / "subjects" / f"{collection}.release.json"
        raw = canonical_json_bytes(subject)
        documents[path] = raw
        subjects.append(
            {
                "path": path.relative_to(release_root).as_posix(),
                "sha256": _sha256_bytes(raw),
                "collection": collection,
            }
        )

    aggregate = {
        "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V2",
        "release_id": release_id,
        "school_year": school_year,
        "authorities": dict(authorities),
        "models": dict(models),
        "artifact_registry": {
            "path": artifact_registry_path.relative_to(release_root).as_posix(),
            "sha256": artifact_registry_sha,
        },
        "expected_counts": {
            "unique_artifacts": len(artifacts),
            "placements": sum(len(rows) for rows in placements_by_collection.values()),
            "unique_chunks": unique_chunk_count,
            "subjects": len(subjects),
        },
        "subjects": subjects,
    }
    if release_mode != "production":
        aggregate["release_mode"] = release_mode
    if promotion_status is not None:
        aggregate["promotion_status"] = promotion_status
    if activation_status is not None:
        aggregate["activation_status"] = activation_status
    if review_status is not None:
        aggregate["review_status"] = review_status
    aggregate_path = release_root / "production-profile-gate.release.json"

    aggregate_raw = canonical_json_bytes(aggregate)
    documents[aggregate_path] = aggregate_raw
    release_registry = {
        "registry_version": "1",
        "school_year": school_year,
        "releases": [
            {
                "release_id": release_id,
                "collections": sorted(placements_by_collection),
                "manifest_path": (
                    Path(release_root.name) / aggregate_path.name
                ).as_posix(),
                "expected_manifest_sha256": _sha256_bytes(aggregate_raw),
                "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V2",
            }
        ],
    }
    documents[release_root.parent / "release-registry.json"] = canonical_json_bytes(
        release_registry
    )
    return documents


def validate_authority_bindings(
    *,
    repository_root: Path,
    bindings: dict[str, Any],
    aggregate: dict[str, Any],
    release_root: Path | None = None,
) -> None:
    if set(bindings) != {
        "binding_kind",
        "school_year",
        "profile_manifest_file_sha256",
        "profile_manifest_fingerprint",
        "runtime",
        "bindings",
    }:
        raise ValueError("authority bindings fields are not exact")
    runtime = bindings["runtime"]
    if not isinstance(runtime, dict) or runtime.get("pypdf") != CANONICAL_PYPDF_VERSION:
        raise ValueError("authority bindings runtime differs from the declared one")
    raw_bindings = bindings["bindings"]
    authorities = aggregate["authorities"]
    if not isinstance(raw_bindings, dict) or set(raw_bindings) != set(authorities):
        raise ValueError("authority binding set differs")
    root = repository_root.resolve()
    rel_root = release_root.resolve() if release_root else None
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
        # Si release_root est fourni et que le fichier existe dans release_root (relatif à RELEASE_ROOT.parent)
        if rel_root is not None:
            # relative est du type 'services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/...'
            # rel_root est '<output_dir>/release-xxx/profile_gate'
            # rel_root.parent est '<output_dir>/release-xxx'
            # Les chemins dans authority_bindings sont relatifs au REPOSITORY_ROOT
            # Les fichiers sous services/rag-pedago/data/releases/prerentree_2026_2027/ sont dans rel_root.parent
            racine_rel = RELEASE_ROOT.parent.relative_to(REPOSITORY_ROOT)
            try:
                sous_rel = relative.relative_to(racine_rel)
                path = (rel_root.parent / sous_rel).resolve()
            except ValueError:
                path = (root / relative).resolve()
        else:
            path = (root / relative).resolve()
        if relative.is_absolute() or path in seen_paths:
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


def _comparer_autorites_a_la_reference(
    racine_ecrite: Path,
    *,
    reference: Path | None,
    motif: str | None,
    ecrites: set[Path],
) -> None:
    """Exiger un motif écrit pour tout écart d'empreinte d'autorité.

    L'auto-cohérence dit qu'une release ne se contredit pas ; elle ne dit rien
    de ce qui a changé depuis la précédente. Les deux sont nécessaires.
    """
    if reference is not None and str(reference).lower() == "none":
        print("AUTHORITY_REFERENCE=none — première émission, comparaison désactivée")
        return
    chemin_ref = (reference or RELEASE_ROOT) / "authority_bindings.json"
    if not chemin_ref.is_file():
        raise ValueError(
            f"référence d'autorité introuvable : {chemin_ref}. Passer "
            f"`--reference-release none` si cette émission n'a pas de précédent.")

    # `bindings` est un dictionnaire nom -> {authority_kind, file_sha256, …},
    # non une liste. Vérifié sur le fichier plutôt que supposé.
    avant = _load_json(chemin_ref)["bindings"]
    apres = _load_json(racine_ecrite / "authority_bindings.json")["bindings"]

    # ── DÉRIVÉE ou EXTERNE, sans liste à maintenir ──────────────────────
    #
    # Une autorité est DÉRIVÉE si ce même passage l'a écrite ; sinon elle est
    # EXTERNE. Le producteur connaît ses propres sorties : `ecrites` porte les
    # chemins relatifs qu'il vient de produire.
    #
    # Une autorité dérivée ne se compare pas à la release précédente : deux
    # releases différentes produisent des artefacts différents, et le constater
    # n'apprend rien. Elle se vérifie contre le passage qui vient de l'écrire —
    # c'est l'auto-cohérence, déjà assurée par `validate_authority_bindings`.
    #
    # Une autorité externe préexiste au passage. C'est elle, et elle seule, qui
    # appelle une comparaison à la référence et un motif si elle diffère.
    #
    # Sans cette distinction, une production exigeait NEUF justifications dont
    # huit sans objet — et un contrôle qu'on remplit sans lire cesse de protéger.
    externes = {
        nom for nom, liaison in apres.items()
        if Path(liaison["path"]) not in ecrites
    }
    derivees = sorted(set(apres) - externes)

    ecarts = [
        (nom, avant[nom]["file_sha256"], apres[nom]["file_sha256"])
        for nom in sorted(set(avant) & set(apres) & externes)
        if avant[nom]["file_sha256"] != apres[nom]["file_sha256"]
    ]
    if derivees:
        print(f"AUTHORITY_DERIVED={len(derivees)} — écrites par ce passage, "
              f"non comparées : {', '.join(derivees)}")
    nouvelles = sorted((set(apres) - set(avant)) & externes)
    disparues = sorted(set(avant) - set(apres))

    if not ecarts and not nouvelles and not disparues:
        print("AUTHORITY_DIGESTS=identiques à la référence")
        return
    if not motif:
        detail = "; ".join(f"{nom} {a[:12]}… -> {b[:12]}…" for nom, a, b in ecarts)
        raise ValueError(
            "des empreintes d'autorité diffèrent de la référence et aucun motif "
            f"n'est donné :\n  écarts : {detail or 'aucun'}\n"
            f"  autorités nouvelles : {nouvelles or 'aucune'}\n"
            f"  autorités disparues : {disparues or 'aucune'}\n"
            "  Passer `--authority-change-motive` avec la raison écrite.")
    print(f"AUTHORITY_DIGESTS_CHANGED={len(ecarts) + len(nouvelles) + len(disparues)}")
    for nom, a, b in ecarts:
        print(f"  {nom}: {a[:12]}… -> {b[:12]}…")
    print(f"AUTHORITY_CHANGE_MOTIVE={motif}")


def _verifier_preconditions(
    profiles: Mapping[str, Any],
    collection_config: Mapping[str, Any],
) -> None:
    """Refuser tout de suite ce qui échouera de toute façon, et le nommer.

    Chaque manque est rapporté avec son compte et un échantillon : un message
    qui nomme une seule collection sur cinquante-trois fait recommencer
    cinquante-trois fois.
    """
    manques: list[str] = []

    declarees = collection_config.get("collections") or {}
    absentes = sorted(set(profiles) - set(declarees))
    if absentes:
        manques.append(
            f"{len(absentes)} collection(s) absente(s) de rag_collections.yml : "
            f"{', '.join(absentes[:5])}"
            + (f" … et {len(absentes) - 5} autres" if len(absentes) > 5 else "")
        )

    racine_taxo = REPOSITORY_ROOT / "services/rag-pedago/taxonomy"
    sans_taxo: list[str] = []
    illisibles: list[str] = []
    for collection in sorted(set(profiles) & set(declarees)):
        fichier = declarees[collection].get("taxonomy_file")
        if not fichier:
            sans_taxo.append(collection)
            continue
        chemin = racine_taxo / fichier
        if not chemin.is_file():
            sans_taxo.append(f"{collection} -> {fichier}")
            continue
        try:
            donnees = _load_yaml(chemin)
            if not isinstance(donnees, dict) or "niveau" not in donnees:
                illisibles.append(f"{collection} -> {fichier} (niveau absent)")
        except Exception as exc:                             # noqa: BLE001
            illisibles.append(f"{collection} -> {fichier} ({type(exc).__name__})")
    if sans_taxo:
        manques.append(
            f"{len(sans_taxo)} taxonomie(s) absente(s) : "
            f"{', '.join(sans_taxo[:5])}"
            + (f" … et {len(sans_taxo) - 5} autres" if len(sans_taxo) > 5 else "")
        )
    if illisibles:
        manques.append(
            f"{len(illisibles)} taxonomie(s) illisible(s) : "
            f"{', '.join(illisibles[:5])}"
        )

    if manques:
        raise ValueError(
            "préconditions non réunies, aucun calcul n'a été engagé :\n  - "
            + "\n  - ".join(manques)
        )


def _build_rehearsal_release(
    *,
    source_release_root: Path,
    release_id: str,
    release_mode: str,
    promotion_status: str,
    activation_status: str,
    review_status: str,
) -> dict[Path, bytes]:
    src_root = source_release_root.resolve()
    profile_root = REPOSITORY_ROOT / "services/rag-engine/configs/ingestion_profiles"
    profile_dir = profile_root / "v2_livraison_319"
    profile_manifest_path = profile_root / "ingestion_manifest_v2_livraison_319.yml"
    registry = load_profile_registry(profile_dir)
    manifest = verify_profile_manifest(registry, profile_manifest_path)
    profiles = {p.scope.collection: p for p in registry.values()}



    subjects_dir = src_root / "subjects"
    preflight_by_sha: dict[str, dict[str, Any]] = {}
    placement_rows: list[dict[str, Any]] = []
    for subj_file in sorted(subjects_dir.glob("*.release.json")):
        subj = _load_json(subj_file)
        col = subj["collection"]
        for art in subj["artifacts"]:
            sha = art["content_sha256"]
            if sha not in preflight_by_sha:
                preflight_by_sha[sha] = {
                    "content_sha256": sha,
                    "source_path": art["source_path"],
                    "page_count": art["page_count"],
                    "ignored_empty_pages": art.get("ignored_empty_pages", []),
                    "chunks": art["chunks"],
                }
            for pl in art["placements"]:
                placement_rows.append({
                    "content_sha256": sha,
                    "physical_path": art["source_path"],
                    "source_url": art.get("source_url", ""),
                    "current_download_url": art.get("current_download_url", ""),
                    "title": art["title"],
                    "external_document_type": art["type_doc"],
                    "collection": col,
                    "source_placement_id": pl["source_placement_id"],
                    "external_scope": pl["source_scope"],
                })

    collection_config = load_collection_config(COLLECTION_CONFIG_PATH)["collections"]
    type_doc_mapping = _load_yaml(DOCUMENT_TYPE_MAPPING_PATH)["document_types"]
    effective_type_doc_mapping = {**type_doc_mapping, **{v: v for v in type_doc_mapping.values()}}

    auth_doc = _load_json(src_root / "authority_bindings.json")
    raw_bindings = dict(auth_doc["bindings"])
    authorities = {k: v["authority_sha256"] for k, v in raw_bindings.items()}

    authorities["document_type_mapping_sha256"] = _file_sha256(DOCUMENT_TYPE_MAPPING_PATH)
    raw_bindings["document_type_mapping_sha256"] = {
        "path": _repo_relative(DOCUMENT_TYPE_MAPPING_PATH),
        "file_sha256": authorities["document_type_mapping_sha256"],
        "authority_sha256": authorities["document_type_mapping_sha256"],
        "authority_kind": "FILE_SHA256",
    }

    authorities["pii_scanner_sha256"] = _file_sha256(PII_SCANNER_PATH)
    raw_bindings["pii_scanner_sha256"] = {
        "path": _repo_relative(PII_SCANNER_PATH),
        "file_sha256": authorities["pii_scanner_sha256"],
        "authority_sha256": authorities["pii_scanner_sha256"],
        "authority_kind": "FILE_SHA256",
    }

    authorities["profile_manifest_sha256"] = manifest.manifest_fingerprint
    raw_bindings["profile_manifest_sha256"] = {
        "path": _repo_relative(profile_manifest_path),
        "file_sha256": _file_sha256(profile_manifest_path),
        "authority_sha256": manifest.manifest_fingerprint,
        "authority_kind": "SEMANTIC_PROFILE_FINGERPRINT",
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


    documents = _release_topology_documents(
        placement_rows,
        profiles=profiles,
        profile_manifest_digest=manifest.manifest_fingerprint,
        collection_config=collection_config,
        preflight_by_sha=preflight_by_sha,
        type_doc_mapping=effective_type_doc_mapping,
        authorities=authorities,
        models=models,
        release_root=RELEASE_ROOT,
        release_id=release_id,
        school_year=SCHOOL_YEAR,
        release_mode=release_mode,
        promotion_status=promotion_status,
        activation_status=activation_status,
        review_status=review_status,
    )

    for evidence_file in (
        "catalog_delta.json",
        "effective_catalog_authority.json",
        "candidate_inventory.json",
        "corpus_manifest_authority.json",
        "currentness_network_audit.json",
        "currentness_evidence.json",
        "pii_evidence.json",
        "preflight_evidence.json",
        "programme_registry.json",
        "models/embedding/manifest.json",
        "models/embedding/SHA256SUMS",
        "models/reranker/manifest.json",
        "models/reranker/SHA256SUMS",
    ):

        p = src_root / evidence_file
        if p.exists():
            documents[RELEASE_ROOT / evidence_file] = p.read_bytes()

    bindings = {

        "binding_kind": "PRODUCTION_PROFILE_RELEASE_AUTHORITY_BINDINGS_V1",
        "school_year": SCHOOL_YEAR,
        "profile_manifest_file_sha256": _file_sha256(profile_manifest_path),
        "profile_manifest_fingerprint": manifest.manifest_fingerprint,
        "runtime": {"pypdf": require_canonical_runtime()},
        "bindings": raw_bindings,
    }
    documents[RELEASE_ROOT / "authority_bindings.json"] = canonical_json_bytes(bindings)
    return documents


def build_release(
    *,
    pdf_root: Path | None = None,
    embedding_snapshot: Path | None = None,
    reranker_snapshot: Path | None = None,
    verify_official_downloads: bool = False,
    release_mode: str = "production",
    promotion_status: str | None = None,
    activation_status: str | None = None,
    review_status: str | None = None,
    release_id: str | None = None,
    source_release_root: Path | None = None,
    review_authority: ReviewAuthorityInputs | None = None,
) -> dict[Path, bytes]:
    if release_mode == "rehearsal":
        return _build_rehearsal_release(
            source_release_root=source_release_root or RELEASE_ROOT,
            release_id=release_id or "production-profile-gate-2026-2027-v2-rehearsal",
            release_mode=release_mode,
            promotion_status=promotion_status or "NOT_PROMOTABLE",
            activation_status=activation_status or "NO_PRODUCTION_ACTIVATION",
            review_status=review_status or "PRE_REVIEW",
        )
    if pdf_root is None or embedding_snapshot is None or reranker_snapshot is None:
        raise ValueError("pdf_root, embedding_snapshot, and reranker_snapshot are required in production mode")

    # Une seule lignée, résolue une fois. `build_release` redéfinissait ici ses
    # propres défauts — la matrice du 25 août et les dix-huit profils — alors
    # que les constantes du module en documentaient d'autres. Un lecteur qui
    # lisait les constantes se trompait, et une exécution « par défaut »
    # rendait 26 documents au lieu de 320.
    lineage = resolve_release_lineage()
    matrix_path = lineage.matrix_path
    matrix = _load_json(matrix_path)
    profile_root = lineage.profile_root
    profile_manifest_path = lineage.profile_manifest_path
    registry = load_profile_registry(profile_root)
    manifest = verify_profile_manifest(registry, profile_manifest_path)
    profiles = {profile.scope.collection: profile for profile in registry.values()}
    # L'invariant est juste et il survit : le registre de profils et le manifeste
    # doivent déclarer le MÊME compte. Un manifeste qui annonce un nombre que le
    # répertoire ne contient pas est un manifeste qui affirme plus qu'il n'a
    # vérifié — la famille de défauts de ce dépôt.
    #
    # Ce qui était fautif, c'est la CONSTANTE. `!= 18` figeait l'invariant sur le
    # périmètre d'un jour, et interdisait toute release additionnelle sans rien
    # garantir de plus. Le manifeste est la référence, pas un nombre en dur.
    if len(profiles) != manifest.declared_count:
        raise ValueError(
            f"production profile registry declares {len(profiles)} profiles, "
            f"manifest declares {manifest.declared_count}"
        )
    if not profiles:
        raise ValueError("production profile registry declares no profile")
    # ── PRÉCONDITIONS, VALIDÉES AVANT DE DÉPENSER ──────────────────────
    #
    # Le 29/08/2026, un build a rendu la main après 57 MINUTES — scan PII de
    # 2 348 documents, puis chunking — sur un `KeyError` de collection non
    # déclarée. Le producteur avait tout calculé avant de vérifier qu'il pouvait
    # écrire quoi que ce soit.
    #
    # Valider les préconditions coûte une seconde ; les valider après coûte une
    # heure par tentative. C'est la différence entre itérer et attendre.
    _verifier_preconditions(profiles, _load_yaml(COLLECTION_CONFIG_PATH))

    placement_rows = _source_records(matrix=matrix, profiles=profiles)
    final_set_raw, accepted_placements_raw, verified_profiles_raw = (
        _release_scope_inputs(
            matrix=matrix,
            profiles=profiles,
            profile_manifest_digest=manifest.manifest_fingerprint,
        )
    )
    pdfs = validate_pdf_mirror(
        pdf_root=pdf_root,
        content_sha256=[row["content_sha256"] for row in placement_rows],
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
    delta, effective = _catalog_documents(placement_rows)
    inventory = _candidate_inventory(placement_rows, delta=delta, effective=effective)
    inventory_sha = _sha256_bytes(canonical_json_bytes(inventory))
    network_audit, _network_rows = resolve_currentness_network_audit(
        placement_rows,
        verify_official_downloads=verify_official_downloads,
        release_id=release_id,
    )
    network_audit, currentness = _currentness_documents(
        placement_rows,
        inventory=inventory,
        inventory_sha256=inventory_sha,
        network_audit=network_audit,
    )
    pii = _pii_evidence(
        placement_rows,
        pdfs=pdfs,
        inventory_sha256=inventory_sha,
        review_authority=review_authority or NO_REVIEW_AUTHORITY,
    )
    preflight = _preflight(
        placement_rows,
        pdfs=pdfs,
        token_counter=token_counter,
        pii_evidence=pii,
    )
    programme = _programme_registry(profiles)

    corpus_descriptor = _corpus_descriptor(placement_rows)
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
        # ADR-0047 §7 : la décision humaine et son reçu appartiennent à la
        # chaîne d'autorité de CE candidat. On ne réécrit jamais les liens
        # d'une release historique pour les y faire entrer après coup.
        **(
            {
                "pii_decision_set_sha256": review_authority.decision_set_path,
                "pii_review_receipt_sha256": review_authority.receipt_path,
                "pii_review_trust_anchor_sha256": review_authority.trust_anchor_path,
                "pii_review_index_sha256": review_authority.review_index_path,
            }
            if review_authority is not None and review_authority.declared
            else {}
        ),
        "rights_registry_sha256": RIGHTS_REGISTRY_PATH,
        "preflight_evidence_sha256": RELEASE_ROOT / "preflight_evidence.json",
        "programme_registry_sha256": RELEASE_ROOT / "programme_registry.json",
        "profile_manifest_sha256": lineage.profile_manifest_path,
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
    documents.update(
        _release_topology_documents(
            placement_rows,
            profiles=profiles,
            profile_manifest_digest=manifest.manifest_fingerprint,
            collection_config=collection_config,
            preflight_by_sha=preflight_by_sha,
            type_doc_mapping=type_doc_mapping,
            authorities=authorities,
            models=models,
            release_root=RELEASE_ROOT,
            # §8 : une candidate porte SA propre identité. Réemployer
            # l'identifiant historique ferait passer une nouvelle release pour
            # celle dont la sémantique a déjà dérivé — et rendrait indécidable
            # laquelle des deux un registre désigne.
            release_id=release_id or RELEASE_ID,
            school_year=SCHOOL_YEAR,
            # §9-§10 : le corpus peut être final et la release rester non
            # activable. Le gate PII n'est qu'un des gates de go-live, et le
            # runtime refuse déjà mécaniquement NOT_PROMOTABLE /
            # NO_PRODUCTION_ACTIVATION. Ces statuts traversent donc aussi la
            # voie production, sans quoi une candidate serait silencieusement
            # activable au seul motif que sa PII est en règle.
            **resolve_release_lifecycle_statuses(
                release_mode=release_mode,
                release_id=release_id,
                promotion_status=promotion_status,
                activation_status=activation_status,
                review_status=review_status,
            ),
        )
    )
    bindings = {
        "binding_kind": "PRODUCTION_PROFILE_RELEASE_AUTHORITY_BINDINGS_V1",
        "school_year": SCHOOL_YEAR,
        "profile_manifest_file_sha256": _file_sha256(lineage.profile_manifest_path),
        "profile_manifest_fingerprint": manifest.manifest_fingerprint,
        # D-41 : une release nomme l'interpréteur qui l'a produite. Sans cela,
        # « cette release est reproductible » est une phrase sans domaine.
        "runtime": {"pypdf": require_canonical_runtime()},
        "bindings": raw_bindings,
    }
    documents[RELEASE_ROOT / "authority_bindings.json"] = canonical_json_bytes(bindings)
    documents[FINAL_PRODUCTION_SET_PATH] = final_set_raw
    documents[ACCEPTED_PLACEMENTS_PATH] = accepted_placements_raw
    documents[VERIFIED_PROFILES_PATH] = verified_profiles_raw
    return documents


def _identite_de_release(documents: Mapping[Path, bytes]) -> str:
    """Dériver l'identité de la release DE SON CONTENU.

    Un même `release_id` pour deux contenus différents rend toute référence
    ambiguë : aucune vérification a posteriori ne peut plus dire laquelle des
    deux elle a validée. Tout l'appareil de scellement — inventaires
    `SHA256SUMS`, empreintes canoniques, `ReviewBindings`, registres de
    placement — suppose qu'un identifiant désigne UN contenu, et rien
    n'imposait cette unicité.

    Dériver l'identité du contenu la rend structurelle : deux contenus
    différents ne peuvent pas produire le même identifiant.
    """
    racine = RELEASE_ROOT.parent
    normalises: dict[str, bytes] = {}
    for chemin, contenu in documents.items():
        try:
            relatif = chemin.relative_to(racine)
        except ValueError:
            relatif = Path(chemin.name)
        normalises[relatif.as_posix()] = contenu

    empreinte = hashlib.sha256()
    for rel_posix, contenu in sorted(normalises.items(), key=lambda x: x[0]):
        empreinte.update(rel_posix.encode("utf-8"))
        empreinte.update(hashlib.sha256(contenu).digest())
    return empreinte.hexdigest()[:16]


def verify_release_directory_identity(release_dir: Path) -> str:
    """D-15 : Vérifier que le nom du répertoire correspond EXACTEMENT à l'empreinte de son contenu."""
    fichiers = {
        p.relative_to(release_dir).as_posix(): p.read_bytes()
        for p in sorted(release_dir.rglob("*"))
        if p.is_file()
    }
    if not fichiers:
        raise ValueError(f"release directory is empty: {release_dir}")
    empreinte = hashlib.sha256()
    for rel_posix, contenu in sorted(fichiers.items(), key=lambda x: x[0]):
        empreinte.update(rel_posix.encode("utf-8"))
        empreinte.update(hashlib.sha256(contenu).digest())
    fingerprint = empreinte.hexdigest()[:16]
    expected_name = f"release-{fingerprint}"
    if release_dir.name != expected_name:
        raise ValueError(
            f"D-15 VIOLATION: release directory name {release_dir.name} does not match content fingerprint {expected_name} (computed {fingerprint})"
        )
    return fingerprint


def _write_documents(
    documents: Mapping[Path, bytes],
    *,
    output_dir: Path | None = None,
    validate_reference: bool = False,
    reference_release: Path | None = None,
    authority_change_motive: str | None = None,
) -> Path:
    """Écrire la release dans un répertoire NEUF, jamais dans celui qui sert.

    Retourne le répertoire écrit. Le basculement se fait ensuite, à part, par
    un lien symbolique — geste atomique et réversible d'un `ln -sfn`.
    """
    if output_dir is None:
        raise ValueError(
            "output_dir explicite est obligatoire : aucune release ne peut "
            "être écrite dans les chemins historiques"
        )

    output_dir.mkdir(parents=True, exist_ok=True)

    identite = _identite_de_release(documents)
    cible = output_dir / f"release-{identite}"
    if cible.exists():
        # Même identité = même contenu : la réémission est un no-op vérifiable.
        # Une identité différente ne peut pas atterrir ici, par construction.
        raise ValueError(
            f"le répertoire {cible} existe déjà. Une identité de release dérive "
            f"de son contenu : si le contenu est identique, il n'y a rien à "
            f"réécrire ; s'il diffère, il aurait une autre identité.")

    staging_parent = Path(
        tempfile.mkdtemp(prefix=f".{cible.name}.staging-", dir=output_dir)
    )
    staging = staging_parent / cible.name
    try:
        racine = RELEASE_ROOT.parent
        for chemin, contenu in sorted(
            documents.items(), key=lambda x: x[0].as_posix()
        ):
            try:
                relatif = chemin.relative_to(racine)
            except ValueError:
                relatif = Path(chemin.name)
            destination = staging / relatif
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(contenu)

        # D-31 : valider le contrat du consommateur dans le staging. Une
        # release invalide ne reçoit jamais son nom dans le répertoire final.
        racine_ecrite = staging / RELEASE_ROOT.relative_to(RELEASE_ROOT.parent)
        aggregate_manifest = racine_ecrite / "production-profile-gate.release.json"
        if aggregate_manifest.exists():
            manifest_sha = hashlib.sha256(aggregate_manifest.read_bytes()).hexdigest()
            load_release_expectation(aggregate_manifest, manifest_sha)
        release_registry = racine_ecrite.parent / "release-registry.json"
        if release_registry.exists():
            registry_sha = hashlib.sha256(release_registry.read_bytes()).hexdigest()
            load_release_registry_file(release_registry, registry_sha)

        # Toute liaison interne et toute divergence contre la référence sont
        # contrôlées dans le staging. Après le rename, il ne reste aucun garde
        # susceptible de transformer une release déjà publiée en échec.
        bindings_path = racine_ecrite / "authority_bindings.json"
        if aggregate_manifest.exists() and bindings_path.exists():
            validate_authority_bindings(
                repository_root=REPOSITORY_ROOT,
                bindings=_load_json(bindings_path),
                aggregate=_load_json(aggregate_manifest),
                release_root=racine_ecrite,
            )
        if validate_reference:
            _comparer_autorites_a_la_reference(
                racine_ecrite,
                reference=reference_release,
                motif=authority_change_motive,
                ecrites={
                    chemin.resolve().relative_to(REPOSITORY_ROOT)
                    for chemin in documents
                    if chemin.resolve().is_relative_to(REPOSITORY_ROOT)
                },
            )

        # Le répertoire est immuable : on le rend non inscriptible après
        # validation et avant publication.
        for chemin in sorted(staging.rglob("*")):
            if chemin.is_file():
                chemin.chmod(0o444)
        verify_release_directory_identity(staging)

        if cible.exists():
            raise ValueError(f"la cible finale existe déjà: {cible}")
        staging.rename(cible)
        staging_parent.rmdir()
    except Exception:
        shutil.rmtree(staging_parent, ignore_errors=True)
        raise
    return cible


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-root", required=False, type=Path, default=None)
    parser.add_argument("--embedding-snapshot", required=False, type=Path, default=None)
    parser.add_argument("--reranker-snapshot", required=False, type=Path, default=None)
    parser.add_argument(
        "--release-mode",
        choices=["production", "rehearsal"],
        default="production",
        help="Mode de release: 'production' ou 'rehearsal'",
    )
    parser.add_argument(
        "--promotion-status",
        choices=["PROMOTABLE", "NOT_PROMOTABLE"],
        default=None,
        help="Statut de promotion (défaut: NOT_PROMOTABLE si rehearsal)",
    )
    parser.add_argument(
        "--activation-status",
        choices=["PRODUCTION_ACTIVATION_ALLOWED", "NO_PRODUCTION_ACTIVATION"],
        default=None,
        help="Statut d'activation (défaut: NO_PRODUCTION_ACTIVATION si rehearsal)",
    )
    parser.add_argument(
        "--review-status",
        choices=["REVIEWED", "PRE_REVIEW"],
        default=None,
        help="Statut de revue PII (défaut: PRE_REVIEW si rehearsal)",
    )
    parser.add_argument(
        "--release-id",
        default=None,
        help="Identifiant de la release",
    )
    parser.add_argument(
        "--source-release-root",
        type=Path,
        default=None,
        help="Répertoire source pour la génération rehearsal",
    )
    # ── PRODUIRE NE DOIT PAS POUVOIR TOUCHER CE QUI SERT ────────────────
    #
    # Le 29/08/2026, ce producteur a écrasé la release EN SERVICE et rendu le
    # moteur indisponible pendant quatre minutes. Ce n'était que le service
    # local ; la même commande après bascule aurait retiré le service aux
    # familles. Seule la cible différait.
    #
    # Un drapeau `--output-dir` corrige l'occurrence ; il ne rend pas l'accident
    # impossible — il suffit de l'oublier une fois. La propriété visée est plus
    # forte, et la PRODUCTION l'applique déjà :
    #
    #     /opt/rag-v2/current -> /opt/rag-v2/releases/rag-v2-main-27a4558-…
    #
    # Un répertoire de release IMMUABLE nommé par son identité, et un lien
    # `current` basculé d'un geste atomique. Le producteur écrit toujours dans
    # un répertoire neuf ; il ne peut pas écrire dans celui qui sert, parce que
    # celui qui sert n'est jamais sa cible. Le retour arrière est un `ln -sfn`.
    #
    # Même architecture des deux côtés : cela supprime l'écart entre
    # l'environnement où l'on essaie et celui où l'on livre.
    # ── AUTO-COHÉRENCE **ET** ÉCART JUSTIFIÉ ────────────────────────────
    #
    # La vérification des liens d'autorité lisait le répertoire SERVANT, par
    # accident de chemin. Corrigé, elle ne lisait plus que la release écrite —
    # et devenait TAUTOLOGIQUE : une release qui redéfinit une autorité et met à
    # jour son propre lien en conséquence est auto-cohérente, donc passe.
    #
    # C'est pourtant ce contrôle qui a détecté le changement du mappage de types
    # et produit la preuve d'additivité. En le rendant auto-référent, j'avais
    # supprimé le vrai positif avec le faux.
    #
    # La comparaison n'est donc pas supprimée : elle est REDIRIGÉE vers une base
    # de référence CHOISIE — la release précédente — et tout écart d'empreinte
    # d'autorité exige son motif, écrit. On ne remplace pas un contrôle qui gêne
    # par un contrôle qui ne gêne jamais.
    parser.add_argument(
        "--reference-release", type=Path, default=None,
        help="Release servant de référence pour les empreintes d'autorité. "
             "Défaut : la release du dépôt. `none` désactive la comparaison — "
             "réservé à une première émission, qui n'a pas de précédent.")
    parser.add_argument(
        "--authority-change-motive", default=None,
        help="Motif écrit de tout écart d'empreinte d'autorité contre la "
             "référence. Exigé dès qu'un écart existe ; conservé dans la trace.")
    parser.add_argument(
        "--output-dir", type=Path, required=True,
        help="Répertoire de sortie. NEUF et vide — le producteur refuse "
             "d'écrire dans un répertoire existant qui n'est pas le sien.")
    parser.add_argument("--verify-official-downloads", action="store_true")
    # ── L'AUTORITÉ DE REVUE PII S'INJECTE ───────────────────────────────
    #
    # Ni identifiant de campagne, ni chemin de gouvernance en dur : faire
    # tourner une autre campagne demain ne doit toucher aucune ligne de ce
    # fichier. Les quatre entrées sont fournies ensemble ou pas du tout ; une
    # release sans contenu détecté n'a pas de décisions à joindre, et le
    # producteur refuse toute détection non dispositionnée.
    for option, description in (
        ("pii-decision-set", "ensemble scellé des décisions humaines de revue PII"),
        ("pii-review-receipt", "reçu ADR-0035 scellant cet ensemble"),
        ("review-trust-anchor", "ancre de confiance vérifiant le reçu"),
        ("pii-review-index", "index des paquets de revue ayant fondé les décisions"),
    ):
        parser.add_argument(f"--{option}", type=Path, default=None, help=description)
    parser.add_argument(
        "--pii-review-reviewer",
        action="append",
        default=None,
        dest="pii_review_reviewers",
        help=(
            "Login GitHub autorisé à approuver l'ensemble de décisions. Répétable. "
            "Absent signifie qu'aucune revue n'est acceptée — jamais que tout "
            "reviewer convient."
        ),
    )
    args = parser.parse_args(argv)
    review_authority = ReviewAuthorityInputs(
        decision_set_path=args.pii_decision_set,
        receipt_path=args.pii_review_receipt,
        trust_anchor_path=args.review_trust_anchor,
        review_index_path=args.pii_review_index,
        reviewers=tuple(args.pii_review_reviewers or ()),
    )
    if args.release_mode == "production" and (
        args.pdf_root is None
        or args.embedding_snapshot is None
        or args.reranker_snapshot is None
    ):
        parser.error("--pdf-root, --embedding-snapshot, and --reranker-snapshot are required in production mode")

    require_canonical_runtime()  # D-41 : à la porte, avant les huit minutes.
    documents = build_release(
        pdf_root=args.pdf_root,
        embedding_snapshot=args.embedding_snapshot,
        reranker_snapshot=args.reranker_snapshot,
        verify_official_downloads=args.verify_official_downloads,
        release_mode=args.release_mode,
        promotion_status=args.promotion_status,
        activation_status=args.activation_status,
        review_status=args.review_status,
        release_id=args.release_id,
        source_release_root=args.source_release_root,
        review_authority=review_authority,
    )
    ecrit = _write_documents(
        documents,
        output_dir=args.output_dir,
        validate_reference=True,
        reference_release=args.reference_release,
        authority_change_motive=args.authority_change_motive,
    )
    if args.output_dir is not None:
        print(f"PRODUCTION_PROFILE_RELEASE_DIR={ecrit}")
        if args.release_mode == "production":
            print("PRODUCTION_PROFILE_RELEASE_ACTIVATION="
                  f"ln -sfn {ecrit} {args.output_dir / 'current'}")
        else:
            print(f"REHEARSAL_STATUS={args.review_status or 'PRE_REVIEW'}")
            print(f"PROMOTABLE={'true' if args.promotion_status == 'PROMOTABLE' else 'false'}")
            print(f"ACTIVATABLE={'true' if args.activation_status == 'PRODUCTION_ACTIVATION_ALLOWED' else 'false'}")

    # La vérification porte sur la release QUI VIENT D'ÊTRE ÉCRITE, jamais sur
    # celle qui sert. Lire `RELEASE_ROOT` ici confrontait les liens d'autorité
    # de l'ANCIENNE release aux fichiers courants du dépôt : tout changement
    # d'une autorité — même purement additif — faisait échouer une production
    # qui, elle, était parfaitement cohérente avec elle-même.
    #
    # L'invariant qui vaut est l'auto-cohérence : la release enregistre les
    # empreintes des fichiers qu'elle a effectivement utilisés.
    racine_verif = (
        ecrit / RELEASE_ROOT.relative_to(RELEASE_ROOT.parent)
        if args.output_dir is not None else RELEASE_ROOT
    )
    aggregate = _load_json(racine_verif / "production-profile-gate.release.json")
    print(
        "PRODUCTION_PROFILE_RELEASE_UNIQUE_ARTIFACTS="
        f"{aggregate['expected_counts']['unique_artifacts']}"
    )
    print(
        "PRODUCTION_PROFILE_RELEASE_PLACEMENTS="
        f"{aggregate['expected_counts']['placements']}"
    )
    print(f"PRODUCTION_PROFILE_RELEASE_COLLECTIONS={len(aggregate['subjects'])}")
    print(
        "PRODUCTION_PROFILE_RELEASE_SHA256="
        f"{_file_sha256(racine_verif / 'production-profile-gate.release.json')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
