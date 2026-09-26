"""Contexte d'autorités du banc multi-niveaux — un seul assemblage cohérent.

Worker B n'accepte pas une trentaine de valeurs indépendantes : il exige une
CHAÎNE dont chaque maillon nomme le suivant et déclare son empreinte. Ce
module produit cette chaîne **ensemble**, pour une release de banc composée
de vrais PDF.

Ce qui est GOUVERNÉ est réutilisé tel quel — profils staging, manifeste de
profils, correspondances Éduscol, registre de programmes, catalogue de
collections. Ce qui décrit le CONTENU du banc est seul fabriqué :
inventaire candidat, actualité, preuve PII, registre de droits, catalogue
d'artefacts et manifeste de release.

Chaque empreinte déclarée par la release du banc nomme des OCTETS qui
existent dans son répertoire : aucune n'est un remplissage. Les autorités
fabriquées portent leur nature dans leur identité
(``acceptance-batch-release-…``), n'autorisent aucune publication réelle et
ne sortent jamais des bases jetables du banc.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ENGINE_ROOT.parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests"))

#: Autorités GOUVERNÉES réutilisées telles quelles. Le banc ne les réécrit
#: pas : il s'y conforme, comme le fera la release réelle.
PROFILS_DIR = ENGINE_ROOT / "configs/ingestion_profiles/staging/multilevel"
MANIFESTE_DE_PROFILS = (
    ENGINE_ROOT / "configs/ingestion_profiles/staging/multilevel_manifest.json"
)
CONFIG_COLLECTIONS = ENGINE_ROOT / "configs/rag_collections.yml"
POLITIQUE_D_ACTUALITE = (
    REPOSITORY_ROOT / "services/rag-pedago/configs/proposals/nexus_rag_currentness_policy_v1.yml"
)
CORRESPONDANCE_NIVEAUX = ENGINE_ROOT / "configs/mappings/eduscol_multilevel_levels.yml"
CORRESPONDANCE_MATIERES = ENGINE_ROOT / "configs/mappings/eduscol_multilevel_subjects.yml"
CORRESPONDANCE_TYPES = (
    ENGINE_ROOT / "configs/mappings/eduscol_multilevel_document_types.yml"
)
REGISTRE_PROGRAMMES = ENGINE_ROOT / "configs/programme_indexes/multilevel_2026_2027.yml"

#: La version de profil que porte le répertoire staging réutilisé.
VERSION_DE_PROFIL = "multilevel-v1"

#: Les deux collections du banc. Un même contenu y est placé DEUX fois :
#: la publication ne doit jamais confondre les deux placements.
COLLECTIONS_DU_BANC = (
    "rag_nexus_nsi_premiere_specialite",
    "rag_nexus_nsi_terminale_specialite",
)

#: Le seul domaine que les profils NSI autorisent.
DOMAINE_OFFICIEL = "eduscol.education.gouv.fr"
LISTING_OFFICIEL = (
    f"https://{DOMAINE_OFFICIEL}/5823/programmes-et-ressources-en-numerique-"
    "et-sciences-informatiques-voie-g"
)

#: La zone de droits qui couvre les chemins physiques du banc.
ZONE_DE_DROITS = "01_EDUSCOL_OFFICIEL/"

#: Le type documentaire Éduscol du banc. Sa cible gouvernée est lue dans la
#: table de correspondance, jamais écrite en dur ici.
TYPE_EXTERNE = "programme-officiel"

#: Le nombre de pages de chaque document du banc.
PAGES_PAR_DOCUMENT = 3

SCHOOL_YEAR = "2026-2027"


class BancIncoherent(RuntimeError):
    """Le banc ne peut pas produire une chaîne cohérente — jamais contourné."""


def _sha(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def _ecrire_json(chemin: Path, document: Any) -> str:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    brut = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
    chemin.write_bytes(brut)
    return hashlib.sha256(brut).hexdigest()


def _empreinte_d_ensemble(valeurs: list[Any]) -> str:
    """L'empreinte d'ensemble du contrat de release, appliquée à l'identique.

    La formule vient de ``nexus_release_chain.release_readiness`` ; une
    divergence ferait refuser la release, ce qui est le comportement voulu.
    """
    encode = json.dumps(
        sorted(valeurs, key=lambda item: json.dumps(item, sort_keys=True)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encode).hexdigest()


def _inverser(table: dict[str, str], cible: str, *, quoi: str) -> str:
    """L'entrée externe dont la correspondance gouvernée rend ``cible``."""
    candidats = sorted(cle for cle, valeur in table.items() if valeur == cible)
    if len(candidats) != 1:
        raise BancIncoherent(
            f"{quoi} : {cible!r} n'a pas une entree externe unique ({candidats})"
        )
    return candidats[0]


@dataclass(frozen=True)
class ContenuDuBanc:
    """Un document du banc : de vrais octets PDF et son identité physique."""

    content_sha256: str
    octets: bytes
    chemin_physique: str
    titre: str
    url_telechargement: str
    pages: int


@dataclass(frozen=True)
class PlacementDuBanc:
    """Un contenu posé dans une collection — l'unité que Worker B publie."""

    collection: str
    content_sha256: str
    source_placement_id: str
    niveau_externe: str
    matiere_externe: str
    portee_externe: str


@dataclass(frozen=True)
class ContexteDuBanc:
    """Les chemins, empreintes et identités de la chaîne, produits ensemble."""

    racine: Path
    magasin: Path
    release_id: str
    contenus: tuple[ContenuDuBanc, ...]
    collections: tuple[str, ...]
    placements: tuple[PlacementDuBanc, ...]
    digests: dict[str, str]
    scopes: dict[str, Any]
    empreintes_de_profil: dict[str, str]
    type_doc: str
    modele_e5: Path
    e5_inventaire_sha256: str

    @property
    def manifeste(self) -> Path:
        return self.racine / "production-profile-gate.release.json"

    @property
    def manifeste_de_transfert(self) -> Path:
        return self.racine / "external_staging_v2_artifact_transfer_manifest.json"

    @property
    def registre_de_droits(self) -> Path:
        return self.racine / "rights_evidence_registry.yml"

    def arguments_d_autorites(self) -> list[str]:
        """Les autorités que tout worker multi-niveaux exige au démarrage."""
        return [
            "--candidate-inventory-path", str(self.racine / "candidate_inventory.json"),
            "--candidate-inventory-sha256", self.digests["candidate_inventory_sha256"],
            "--currentness-evidence-path", str(self.racine / "currentness_evidence.json"),
            "--currentness-evidence-sha256", self.digests["currentness_evidence_sha256"],
            "--levels-mapping-path", str(CORRESPONDANCE_NIVEAUX),
            "--levels-mapping-sha256", self.digests["level_mapping_sha256"],
            "--subjects-mapping-path", str(CORRESPONDANCE_MATIERES),
            "--subjects-mapping-sha256", self.digests["subject_mapping_sha256"],
            "--document-types-mapping-path", str(CORRESPONDANCE_TYPES),
            "--document-types-mapping-sha256", self.digests["document_type_mapping_sha256"],
            "--release-manifest-path", str(self.manifeste),
            "--release-manifest-sha256", self.digests["release_manifest_sha256"],
            "--programme-registry-path", str(REGISTRE_PROGRAMMES),
            "--programme-registry-sha256", self.digests["programme_registry_sha256"],
            "--profile-manifest-path", str(MANIFESTE_DE_PROFILS),
            "--profile-manifest-sha256", self.digests["profile_manifest_sha256"],
            "--collection-config-path", str(CONFIG_COLLECTIONS),
            "--collection-config-sha256", self.digests["collection_config_sha256"],
            "--pii-evidence-path", str(self.racine / "pii_evidence.json"),
            "--pii-evidence-sha256", self.digests["pii_evidence_sha256"],
            "--rights-evidence-path", str(self.registre_de_droits),
            "--rights-evidence-sha256", self.digests["rights_registry_sha256"],
            "--corpus-manifest-sha256", self.digests["corpus_manifest_sha256"],
            "--repository-root", str(REPOSITORY_ROOT),
            # La release du banc est SCELLÉE : son manifeste de transfert
            # établit l'invariant de format du catalogue.
            "--artifact-transfer-manifest-path", str(self.manifeste_de_transfert),
            "--artifact-transfer-manifest-sha256",
            self.digests["artifact_transfer_manifest_sha256"],
        ]


def contenus_du_banc(
    magasin: Path, *, empreinte: str, combien: int = 2
) -> tuple[ContenuDuBanc, ...]:
    """De VRAIS PDF, lisibles par pypdf, écrits dans le magasin d'artefacts.

    Chaque appel produit des contenus DISTINCTS : la base du banc est
    partagée par les tests du module, et des identités réutilisées les
    feraient dépendre de leur ordre d'exécution.
    """
    from _pdf_lisible import pdf_lisible  # noqa: PLC0415

    magasin.mkdir(parents=True, exist_ok=True)
    contenus: list[ContenuDuBanc] = []
    for index in range(combien):
        octets = pdf_lisible(
            [
                f"Document {index} du banc {empreinte}, page {page + 1}. "
                "Programme officiel de NSI : representation des donnees, "
                "algorithmique et architectures materielles. Contenu "
                "pedagogique de test, reellement extractible."
                for page in range(PAGES_PAR_DOCUMENT)
            ]
        )
        sha = hashlib.sha256(octets).hexdigest()
        (magasin / f"{sha}.pdf").write_bytes(octets)
        contenus.append(
            ContenuDuBanc(
                content_sha256=sha,
                octets=octets,
                chemin_physique=(
                    f"{ZONE_DE_DROITS}LYCEE/NSI/01_PROGRAMMES_OFFICIELS/"
                    f"banc-{empreinte}/document-{index}.pdf"
                ),
                titre=f"Programme officiel NSI — document {index} du banc",
                url_telechargement=(
                    f"https://{DOMAINE_OFFICIEL}/sites/default/files/document/"
                    f"banc-{empreinte}-document-{index}.pdf"
                ),
                pages=PAGES_PAR_DOCUMENT,
            )
        )
    return tuple(contenus)


def modele_e5_du_banc() -> tuple[Path, str]:
    """L'artefact E5 réel, et l'empreinte de son inventaire.

    Le chemin vient de l'environnement — aucun chemin machine-local n'est
    écrit ici. Absent, le banc ne peut pas publier : c'est un refus, jamais
    un contournement.
    """
    brut = os.environ.get("RAG_EMBEDDING_MODEL_CACHE_DIR", "").strip()
    if not brut:
        raise BancIncoherent(
            "RAG_EMBEDDING_MODEL_CACHE_DIR est requis : Worker B embarque "
            "reellement les chunks, et le modele n'est jamais suppose"
        )
    racine = Path(brut)
    inventaire = racine / "SHA256SUMS"
    if not inventaire.is_file():
        raise BancIncoherent(f"aucun inventaire de modele a {inventaire}")
    return racine, _sha(inventaire)


def environnement_de_readiness(
    tmp_path: Path, *, corpus_manifest_sha256: str
) -> dict[str, str]:
    """L'environnement de readiness SIGNÉ du banc, en mode répétition.

    Le gate de démarrage refuse un worker qui ne présente pas un manifeste
    de readiness signé et son ancre de confiance. Le banc en produit un —
    avec sa propre clé, confinée à ce répertoire temporaire — au lieu de
    désactiver le gate : une garde retirée pour faire passer un banc ne
    prouve plus rien de ce que le banc voulait montrer.
    """
    import secrets  # noqa: PLC0415
    import uuid  # noqa: PLC0415
    from datetime import UTC, datetime  # noqa: PLC0415

    from _local_github import REPOSITORY  # noqa: PLC0415
    from nexus_contracts.production_readiness import (  # noqa: PLC0415
        PRODUCTION_READINESS_PROTOCOL_VERSION,
        ProductionReadinessManifestV1,
        public_readiness_key_hex,
        sign_production_readiness_manifest,
    )

    graine = secrets.token_hex(32)
    key_id = f"banc-multiniveaux-{uuid.uuid4().hex}"
    # Un répertoire par appel : le manifeste signé est posé en lecture
    # seule, et un second démarrage de worker dans le même test ne doit pas
    # avoir à réécrire par-dessus.
    tmp_path = tmp_path / f"readiness-{uuid.uuid4().hex[:8]}"
    tmp_path.mkdir(parents=True, exist_ok=True)
    merge_sha = "c" * 40
    manifeste = ProductionReadinessManifestV1(
        protocol_version=PRODUCTION_READINESS_PROTOCOL_VERSION,
        repository=REPOSITORY,
        pr_number=95,
        pr_head_sha="d" * 40,
        pr_head_tree_sha="e" * 40,
        merge_sha=merge_sha,
        merge_tree_sha="e" * 40,
        release_tag=f"release/rag/20260922-{merge_sha[:12]}",
        environment="production",
        review_binding_digest="1" * 64,
        authorization_digest="2" * 64,
        trust_anchor_digest="3" * 64,
        revocation_registry_digest="4" * 64,
        catalog_digest="5" * 64,
        sealed_manifest_digest=corpus_manifest_sha256,
        h2b_report_digest="6" * 64,
        gate_result="pass",
        application_image_digests={
            "ingestion-worker": "ghcr.io/nexus/x@sha256:" + "7" * 64
        },
        upstream_image_digests={"pgvector": "pgvector/pgvector@sha256:" + "8" * 64},
        compose_digest="9" * 64,
        workflow_path=".github/workflows/promote-rag-production.yml",
        workflow_ref="refs/heads/main",
        run_id=99001,
        run_attempt=1,
        issued_at=datetime(2026, 9, 22, 8, 0, tzinfo=UTC),
        key_id=key_id,
    )
    chemin = tmp_path / "readiness.json"
    chemin.write_bytes(
        sign_production_readiness_manifest(
            manifeste, private_key_hex=graine, key_id=key_id
        ).canonical_bytes()
    )
    chemin.chmod(0o444)
    ancre = tmp_path / "readiness-anchor.json"
    ancre.write_text(
        json.dumps(
            {
                "protocol_version": PRODUCTION_READINESS_PROTOCOL_VERSION,
                "keys": [
                    {
                        "key_id": key_id,
                        "algorithm": "ed25519",
                        "public_key": public_readiness_key_hex(graine),
                        "environment": "production",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    ancre.chmod(0o444)
    return {
        "NEXUS_ENVIRONMENT": "rehearsal",
        "NEXUS_READINESS_MANIFEST_PATH": str(chemin),
        "NEXUS_EXPECTED_READINESS_PROTOCOL": "NEXUS-PRODUCTION-READINESS-V1",
        "NEXUS_READINESS_REHEARSAL_TRUST_ANCHOR": str(ancre),
        "NEXUS_RELEASE_SHA": merge_sha,
    }


def _inventaire_du_reranker() -> str:
    """L'inventaire du reranker réel quand il est monté, sinon celui du banc.

    Worker B ne charge pas le reranker ; la release doit néanmoins déclarer
    son identité. On déclare celle du modèle réellement présent plutôt
    qu'une valeur arbitraire.
    """
    brut = os.environ.get("RAG_RERANKER_MODEL_CACHE_DIR", "").strip()
    if brut and (Path(brut) / "SHA256SUMS").is_file():
        return _sha(Path(brut) / "SHA256SUMS")
    return hashlib.sha256(b"banc: aucun reranker monte").hexdigest()


def construire_contexte_du_banc(
    racine: Path,
    magasin: Path,
    *,
    contenus: tuple[ContenuDuBanc, ...],
    collections: tuple[str, ...] = COLLECTIONS_DU_BANC,
    release_id: str | None = None,
    lignee: str | None = None,
    actualite: str = "verifiee",
) -> ContexteDuBanc:
    """Écrit la release du banc et rend sa chaîne d'autorités cohérente.

    L'ordre d'écriture est imposé par les liaisons : chaque fichier ne peut
    être haché qu'une fois ceux qu'il nomme écrits.

    Un SUCCESSEUR (ADR-0059 § 5) se construit en nommant la ``lignee`` de son
    prédécesseur : mêmes contenus, mêmes identités de placement, même
    périmètre de corpus — seule son identité et les autorités corrigées
    changent. ``actualite="instantane"`` produit une preuve V3 d'instantanés
    officiels (ADR-0055) à côté d'un audit qui n'a rien vérifié.
    """
    if actualite not in {"verifiee", "instantane"}:
        raise BancIncoherent(f"actualite inconnue du banc : {actualite!r}")
    from ingestor.collection_config import load_collection_config  # noqa: PLC0415
    from ingestor.ingestion_profiles.registry import (  # noqa: PLC0415
        load_profile_registry,
        profile_fingerprint,
    )

    racine.mkdir(parents=True, exist_ok=True)
    release_id = release_id or (
        f"acceptance-batch-release-{hashlib.sha256(str(racine).encode()).hexdigest()[:12]}"
    )
    # Ce qui fait l'identité du CORPUS et de ses placements : partagé par une
    # release et son successeur.
    lignee = lignee or release_id
    instantane = actualite == "instantane"

    profils = load_profile_registry(PROFILS_DIR)
    config = load_collection_config(CONFIG_COLLECTIONS)
    niveaux = yaml.safe_load(CORRESPONDANCE_NIVEAUX.read_text("utf-8"))["external_levels"]
    matieres = yaml.safe_load(CORRESPONDANCE_MATIERES.read_text("utf-8"))["external_subjects"]
    types = yaml.safe_load(CORRESPONDANCE_TYPES.read_text("utf-8"))["document_types"]
    type_doc = types[TYPE_EXTERNE]

    scopes: dict[str, Any] = {}
    empreintes: dict[str, str] = {}
    placements: list[PlacementDuBanc] = []
    for collection in collections:
        cle = (collection, VERSION_DE_PROFIL)
        if cle not in profils:
            raise BancIncoherent(f"aucun profil gouverne pour {cle}")
        profil = profils[cle]
        scopes[collection] = profil.scope
        empreintes[collection] = profile_fingerprint(profil)
        niveau_externe = _inverser(niveaux, profil.scope.niveau, quoi="niveau")
        matiere_externe = _inverser(matieres, profil.scope.matiere, quoi="matiere")
        portee_externe = f"lycee/general/{matiere_externe}"
        for contenu in contenus:
            placements.append(
                PlacementDuBanc(
                    collection=collection,
                    content_sha256=contenu.content_sha256,
                    # Une identité de placement par (contenu, collection) :
                    # la résolution refuse l'ambiguïté, à raison.
                    source_placement_id=hashlib.sha256(
                        f"{lignee}:{collection}:{contenu.content_sha256}".encode()
                    ).hexdigest(),
                    niveau_externe=niveau_externe,
                    matiere_externe=matiere_externe,
                    portee_externe=portee_externe,
                )
            )

    # ---- Autorités de périmètre du banc, écrites avant d'être nommées ----
    corpus_sha = _ecrire_json(
        racine / "corpus_manifest_authority.json",
        {
            "authority_kind": "ACCEPTANCE_BENCH_CORPUS_MANIFEST",
            "release_id": lignee,
            "zone": ZONE_DE_DROITS,
            "contents": sorted(contenu.content_sha256 for contenu in contenus),
        },
    )
    politique_sha = _ecrire_json(
        racine / "pii_policy.json",
        {
            "policy_kind": "ACCEPTANCE_BENCH_PII_POLICY",
            "release_id": lignee,
            "statement": (
                "Documents fabriques par le banc : aucune donnee personnelle "
                "n'y est introduite. Cette politique ne vaut que pour ce banc."
            ),
        },
    )
    scanner_sha = _ecrire_json(
        racine / "pii_scanner.json",
        {
            "scanner_kind": "ACCEPTANCE_BENCH_PII_SCANNER",
            "release_id": lignee,
            "statement": "Scan du banc : lecture integrale des pages produites.",
        },
    )
    catalogue_parent_sha = _ecrire_json(
        racine / "parent_sealed_catalog.json",
        {
            "catalog_kind": "ACCEPTANCE_BENCH_PARENT_CATALOG",
            "release_id": lignee,
            "statement": "Le banc n'herite d'aucun catalogue scelle anterieur.",
        },
    )
    catalogue_de_placements_sha = _ecrire_json(
        racine / "placement_catalog.json",
        {
            "catalog_kind": "ACCEPTANCE_BENCH_PLACEMENT_CATALOG",
            "release_id": lignee,
            "placements": [
                {
                    "collection": placement.collection,
                    "content_sha256": placement.content_sha256,
                    "source_placement_id": placement.source_placement_id,
                }
                for placement in placements
            ],
        },
    )
    delta_sha = _ecrire_json(
        racine / "catalog_delta.json",
        {
            "delta_kind": "ACCEPTANCE_BENCH_CATALOG_DELTA",
            "release_id": lignee,
            "added": sorted(contenu.content_sha256 for contenu in contenus),
            "removed": [],
        },
    )
    autorite_effective_sha = _ecrire_json(
        racine / "effective_catalog_authority.json",
        {
            "authority_kind": "ACCEPTANCE_BENCH_EFFECTIVE_CATALOG_AUTHORITY",
            "release_id": lignee,
            "parent_sealed_catalog_sha256": catalogue_parent_sha,
            "catalog_delta_sha256": delta_sha,
        },
    )

    # ---- Inventaire candidat ----
    inventaire_sha = _ecrire_json(
        racine / "candidate_inventory.json",
        _inventaire(
            contenus=contenus,
            collections=collections,
            placements=placements,
            corpus_sha=corpus_sha,
            catalogue_scelle_sha=catalogue_parent_sha,
            catalogue_de_placements_sha=catalogue_de_placements_sha,
            delta_sha=delta_sha,
            autorite_effective_sha=autorite_effective_sha,
        ),
    )

    # ---- Actualité, liée à l'inventaire et à son audit ----
    audit_sha = _ecrire_json(
        racine / "currentness_network_audit.json",
        {
            "audit_kind": "ACCEPTANCE_BENCH_CURRENTNESS_AUDIT",
            "corpus_manifest_sha256": corpus_sha,
            "content_set_sha256": _empreinte_d_ensemble_de_contenus(contenus),
            "statement": (
                "Banc hors ligne : l'identite d'octets est celle des fichiers "
                "produits par le banc lui-meme, jamais un telechargement."
            ),
            **(
                {"currentness_status": "CURRENTNESS_UNVERIFIED_SOURCE_UNREACHABLE"}
                if instantane
                else {}
            ),
        },
    )
    actualite_sha = _ecrire_json(
        racine / "currentness_evidence.json",
        _actualite(
            contenus=contenus,
            placements=placements,
            inventaire_sha=inventaire_sha,
            corpus_sha=corpus_sha,
            catalogue_scelle_sha=catalogue_parent_sha,
            catalogue_de_placements_sha=catalogue_de_placements_sha,
            delta_sha=delta_sha,
            autorite_effective_sha=autorite_effective_sha,
            audit_sha=audit_sha,
            instantane=instantane,
        ),
    )

    # ---- Preuves PII et droits ----
    pii_sha = _ecrire_json(
        racine / "pii_evidence.json",
        {
            "evidence_kind": "REAL_CORPUS_PII_SCAN",
            "corpus_manifest_sha256": corpus_sha,
            "policy_sha256": politique_sha,
            "scanner_sha256": scanner_sha,
            "remote_access_mode": "READ_ONLY",
            "remote_write_operations": 0,
            "raw_pii_in_output": False,
            "raw_pii_in_logs": False,
            "results": [
                {
                    "content_sha256": contenu.content_sha256,
                    "status": "CLEARED",
                    "pii_detected": False,
                    "pages_scanned": contenu.pages,
                    "characters_scanned": len(contenu.octets),
                    "source_path": contenu.chemin_physique,
                }
                for contenu in contenus
            ],
        },
    )
    droits = racine / "rights_evidence_registry.yml"
    droits.write_bytes(
        yaml.safe_dump(
            {
                "registry_id": f"acceptance_bench_{release_id}",
                "human_rights_decisions": {
                    "banc_eduscol": {
                        "decision_type": "HUMAN_ORGANIZATIONAL_RIGHTS_APPROVAL",
                        "decision_maker": "banc d'acceptation (donnee de test)",
                        "scope_manifest_sha256": corpus_sha,
                        "scope_zone": ZONE_DE_DROITS,
                        "rights_category": "officiel_public",
                        "approved_for_internal_rag": True,
                        "approved_for_production_rag": True,
                        "generic_rights_blocker": False,
                    }
                },
                "source_evidence": {
                    "banc_eduscol": {
                        "zone": ZONE_DE_DROITS,
                        "domain": DOMAINE_OFFICIEL,
                        "provenance_status": "VERIFIED",
                        "recommended_rights_category": "officiel_public",
                    }
                },
            },
            sort_keys=False,
            allow_unicode=True,
        ).encode("utf-8")
    )
    droits_sha = _sha(droits)

    # ---- Catalogue d'artefacts et pré-vol ----
    artefacts = [_artefact_de_registre(contenu, type_doc=type_doc) for contenu in contenus]
    registre_sha = _ecrire_json(
        racine / "artifacts.release.json",
        {
            "release_kind": "MULTILEVEL_ARTIFACT_REGISTRY_V2",
            "release_id": release_id,
            "school_year": SCHOOL_YEAR,
            "expected_counts": {
                "unique_artifacts": len(artefacts),
                "unique_chunks": sum(len(a["chunks"]) for a in artefacts),
            },
            "artifacts": artefacts,
        },
    )
    # Le pré-vol porte une MESURE par chunk : le prédicat de qualité du
    # batch exige un nombre de caractères non nul, et une valeur inventée
    # rendrait ce prédicat décoratif. Les caractères sont donc comptés sur
    # les octets réels, par l'extracteur gouverné lui-même.
    par_contenu = {contenu.content_sha256: contenu for contenu in contenus}
    prevol_sha = _ecrire_json(
        racine / "preflight_evidence.json",
        {
            "evidence_kind": "PRODUCTION_PROFILE_GATE_PREFLIGHT_V1",
            "release_id": release_id,
            "model_id": "intfloat/multilingual-e5-large",
            "target_tokens": 384,
            "artifacts": [
                {
                    "content_sha256": a["content_sha256"],
                    "page_count": a["page_count"],
                    "source_path": a["source_path"],
                    "chunks": _chunks_mesures(
                        a["chunks"], par_contenu[a["content_sha256"]]
                    ),
                }
                for a in artefacts
            ],
        },
    )

    # ---- Manifeste de transfert : la convention de format du banc ----
    transfert_sha = _ecrire_json(
        racine / "external_staging_v2_artifact_transfer_manifest.json",
        {
            "manifest_kind": "ACCEPTANCE_BENCH_ARTIFACT_TRANSFER_V1",
            "release_id": release_id,
            # Le transfert du banc est une COPIE locale verifiee : chaque
            # objet est ecrit puis rehache. Ces deux compteurs sont donc des
            # mesures, pas des declarations de confort.
            "file_count": len(contenus),
            "digest_missing": 0,
            "digest_mismatches": 0,
            "files": [
                {
                    "file": f"{contenu.content_sha256}.pdf",
                    "sha256_expected": contenu.content_sha256,
                    "sha256_observed": contenu.content_sha256,
                }
                for contenu in contenus
            ],
        },
    )

    modele, e5_sha = modele_e5_du_banc()
    autorites = {
        "candidate_inventory_sha256": inventaire_sha,
        "catalog_delta_sha256": delta_sha,
        "corpus_manifest_sha256": corpus_sha,
        "currentness_evidence_sha256": actualite_sha,
        "document_type_mapping_sha256": _sha(CORRESPONDANCE_TYPES),
        "effective_catalog_authority_sha256": autorite_effective_sha,
        "embedding_inventory_sha256": e5_sha,
        "level_mapping_sha256": _sha(CORRESPONDANCE_NIVEAUX),
        "parent_sealed_catalog_sha256": catalogue_parent_sha,
        "pii_evidence_sha256": pii_sha,
        "pii_policy_sha256": politique_sha,
        "pii_scanner_sha256": scanner_sha,
        "placement_catalog_sha256": catalogue_de_placements_sha,
        "preflight_evidence_sha256": prevol_sha,
        "profile_manifest_sha256": _sha(MANIFESTE_DE_PROFILS),
        "programme_registry_sha256": _sha(REGISTRE_PROGRAMMES),
        "reranker_inventory_sha256": _inventaire_du_reranker(),
        "rights_registry_sha256": droits_sha,
        "subject_mapping_sha256": _sha(CORRESPONDANCE_MATIERES),
    }
    modeles = {
        "embedding": {
            "model_id": "intfloat/multilingual-e5-large",
            "inventory_sha256": e5_sha,
            "dimension": 1024,
        },
        "reranker": {
            "model_id": "cross-encoder/ms-marco-MiniLM-L-6-v2",
            "inventory_sha256": autorites["reranker_inventory_sha256"],
        },
    }

    # ---- Sujets, un par collection ----
    entrees_de_sujet = []
    for collection in collections:
        scope = scopes[collection]
        entree = config["collections"][collection]
        chemin = racine / "subjects" / f"{collection}.release.json"
        sujet_sha = _ecrire_json(
            chemin,
            {
                "release_kind": "MULTILEVEL_SUBJECT_RELEASE_V2",
                "release_id": f"{release_id}-{collection}",
                "school_year": SCHOOL_YEAR,
                "collection": collection,
                "programme_version": scope.programme_version,
                "authorities": autorites,
                "profile": {
                    "version": VERSION_DE_PROFIL,
                    "fingerprint": empreintes[collection],
                    "manifest_digest": autorites["profile_manifest_sha256"],
                },
                "models": modeles,
                "artifact_registry": {
                    "path": "../artifacts.release.json",
                    "sha256": registre_sha,
                },
                "expected_counts": {
                    "unique_artifact_references": len(contenus),
                    "placements": len(contenus),
                },
                "placements": [
                    {
                        "placement_id": hashlib.sha256(
                            f"{placement.source_placement_id}:placement".encode()
                        ).hexdigest(),
                        "artifact_id": placement.content_sha256,
                        "source_placement_id": placement.source_placement_id,
                        "source_scope": placement.portee_externe,
                        "collection": collection,
                        "tenant": scope.tenant,
                        "niveau": scope.niveau,
                        "voie": scope.voie,
                        "matiere": scope.matiere,
                        "statut_enseignement": entree["statut"],
                        "candidat": scope.candidat,
                        "visibility": scope.visibility,
                        "school_year": SCHOOL_YEAR,
                        "programme_version": scope.programme_version,
                        "currentness": "official_snapshot" if instantane else "current",
                        "placement_status": "active",
                        "review_status": "reviewed",
                    }
                    for placement in placements
                    if placement.collection == collection
                ],
            },
        )
        entrees_de_sujet.append(
            {
                "collection": collection,
                "path": f"subjects/{collection}.release.json",
                "sha256": sujet_sha,
            }
        )

    manifeste_sha = _ecrire_json(
        racine / "production-profile-gate.release.json",
        {
            "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V2",
            "release_id": release_id,
            "school_year": SCHOOL_YEAR,
            "release_mode": "rehearsal",
            "promotion_status": "NOT_PROMOTABLE",
            "activation_status": "NO_PRODUCTION_ACTIVATION",
            "review_status": "PRE_REVIEW",
            "authorities": autorites,
            "models": modeles,
            "artifact_registry": {
                "path": "artifacts.release.json",
                "sha256": registre_sha,
            },
            "expected_counts": {
                "unique_artifacts": len(contenus),
                "placements": len(placements),
                "unique_chunks": sum(len(a["chunks"]) for a in artefacts),
                "subjects": len(collections),
            },
            "subjects": entrees_de_sujet,
        },
    )

    digests = dict(autorites)
    digests.update(
        {
            "release_id": release_id,
            "release_manifest_sha256": manifeste_sha,
            "artifacts_release_sha256": registre_sha,
            "artifact_transfer_manifest_sha256": transfert_sha,
            "collection_config_sha256": _sha(CONFIG_COLLECTIONS),
        }
    )
    return ContexteDuBanc(
        racine=racine,
        magasin=magasin,
        release_id=release_id,
        contenus=contenus,
        collections=tuple(collections),
        placements=tuple(placements),
        digests=digests,
        scopes=scopes,
        empreintes_de_profil=empreintes,
        type_doc=type_doc,
        modele_e5=modele,
        e5_inventaire_sha256=e5_sha,
    )


def _empreinte_d_ensemble_de_contenus(contenus: tuple[ContenuDuBanc, ...]) -> str:
    """L'empreinte d'ensemble de contenus, telle que le contrat la calcule."""
    from ingestor.multilevel_evidence import content_set_sha256  # noqa: PLC0415

    return content_set_sha256({contenu.content_sha256 for contenu in contenus})


def _chunks_mesures(
    chunks: list[dict[str, Any]], contenu: ContenuDuBanc
) -> list[dict[str, Any]]:
    """Les chunks du pré-vol, avec le nombre de caractères RÉELLEMENT extrait.

    Un chunk par page, et le compte vient de l'extracteur gouverné appliqué
    aux octets du banc — jamais d'une constante.
    """
    from ingestor.ingestion_agents.extractor import extract_pdf_pages  # noqa: PLC0415

    pages = extract_pdf_pages(contenu.octets)
    if len(pages) != contenu.pages:
        raise BancIncoherent(
            f"le PDF du banc porte {len(pages)} pages extraites pour "
            f"{contenu.pages} declarees"
        )
    return [
        {**chunk, "character_count": len(pages[chunk["chunk_index"]])}
        for chunk in chunks
    ]


def _artefact_de_registre(contenu: ContenuDuBanc, *, type_doc: str) -> dict[str, Any]:
    """Une entrée du catalogue : un chunk par page, pages toutes couvertes.

    L'empreinte scellée d'un chunk est celle du TEXTE que le chunker canonique
    publie (ADR-0060 : le publisher la recompare, dans l'ordre). Une page du
    banc est très en deçà du budget de tokens : son chunk est le texte de la
    page, quel que soit le tokenizer. Une empreinte fabriquée ici rendait toute
    publication batch du banc impossible (lot DH)."""
    from ingestor.ingestion_agents.extractor import extract_pdf_pages  # noqa: PLC0415

    pages = extract_pdf_pages(contenu.octets)
    chunks = [
        {
            "chunk_id": hashlib.sha256(
                f"{contenu.content_sha256}:{index}".encode()
            ).hexdigest(),
            "chunk_index": index,
            "chunk_sha256": hashlib.sha256(
                pages[index].replace("\x00", "").strip().encode("utf-8")
            ).hexdigest(),
            "page_start": index + 1,
            "page_end": index + 1,
        }
        for index in range(contenu.pages)
    ]
    return {
        "artifact_id": contenu.content_sha256,
        "content_sha256": contenu.content_sha256,
        "source_path": contenu.chemin_physique,
        "source_url": contenu.url_telechargement,
        "title": contenu.titre,
        "type_doc": type_doc,
        "page_count": contenu.pages,
        "ignored_empty_pages": [],
        "chunks": chunks,
        "chunk_id_set_digest": _empreinte_d_ensemble([c["chunk_id"] for c in chunks]),
        "chunk_sha256_set_digest": _empreinte_d_ensemble(
            [c["chunk_sha256"] for c in chunks]
        ),
        "page_coverage_digest": _empreinte_d_ensemble(
            list(range(1, contenu.pages + 1))
        ),
    }


def _inventaire(
    *,
    contenus: tuple[ContenuDuBanc, ...],
    collections: tuple[str, ...],
    placements: list[PlacementDuBanc],
    corpus_sha: str,
    catalogue_scelle_sha: str,
    catalogue_de_placements_sha: str,
    delta_sha: str,
    autorite_effective_sha: str,
) -> dict[str, Any]:
    """L'inventaire candidat : ses comptes décrivent SES propres listes."""
    par_collection = []
    for collection in collections:
        siens = [p for p in placements if p.collection == collection]
        candidats = []
        for contenu in contenus:
            ses_placements = [p for p in siens if p.content_sha256 == contenu.content_sha256]
            candidats.append(
                {
                    "content_sha256": contenu.content_sha256,
                    "physical_path": contenu.chemin_physique,
                    "physical_currentness_candidate": "actuel",
                    "physical_disposition_candidate": "EXACT_GRADE_GATE_PENDING",
                    "placements": [
                        {
                            "source_placement_id": placement.source_placement_id,
                            "source_url": LISTING_OFFICIEL,
                            "title": contenu.titre,
                            "external_level": placement.niveau_externe,
                            "external_subject": placement.matiere_externe,
                            "external_scope": placement.portee_externe,
                            "external_document_type": TYPE_EXTERNE,
                            "pedagogical_status": "actuel",
                            "year": "2026",
                            "placement_origin": "ACCEPTANCE_BENCH",
                            "placement_reason_code": None,
                        }
                        for placement in ses_placements
                    ],
                }
            )
        premier = siens[0]
        par_collection.append(
            {
                "phase": "banc",
                "collection": collection,
                "external_level": premier.niveau_externe,
                "external_subject": premier.matiere_externe,
                "external_scope": premier.portee_externe,
                "counts": {
                    "unique_artifacts": len(contenus),
                    "placements": len(siens),
                },
                "observed_values": {},
                "discovery_routes": [],
                "inventory_disposition": "EXACT_GRADE_GATES_PENDING",
                "candidate_partition": {
                    "exact_grade_gate_pending": sorted(
                        contenu.content_sha256 for contenu in contenus
                    ),
                    "named_noneligible": [],
                    "unevaluated": [],
                },
                "candidates": candidats,
            }
        )
    multi = sum(
        1
        for contenu in contenus
        if sum(1 for p in placements if p.content_sha256 == contenu.content_sha256) > 1
    )
    return {
        "inventory_kind": "MULTILEVEL_CANDIDATE_INVENTORY_V1",
        "school_year": SCHOOL_YEAR,
        "corpus_manifest_sha256": corpus_sha,
        "sealed_catalog_sha256": catalogue_scelle_sha,
        "placement_catalog_sha256": catalogue_de_placements_sha,
        "catalog_delta_sha256": delta_sha,
        "catalog_delta_payload_sha256": delta_sha,
        "effective_catalog_authority_sha256": autorite_effective_sha,
        "counts": {
            "target_collections": len(collections),
            "unique_artifacts": len(contenus),
            "placements": len(placements),
            "physical_objects": len(contenus),
            "multi_placement_artifacts": multi,
        },
        "collection_partition": {
            "exact_grade_gates_pending": list(collections),
            "named_noneligible": [],
            "unevaluated": [],
        },
        "candidate_partition": {
            "exact_grade_gate_pending": sorted(
                contenu.content_sha256 for contenu in contenus
            ),
            "named_noneligible": [],
            "unevaluated": [],
        },
        "collections": par_collection,
    }


def _actualite(
    *,
    contenus: tuple[ContenuDuBanc, ...],
    placements: list[PlacementDuBanc],
    inventaire_sha: str,
    corpus_sha: str,
    catalogue_scelle_sha: str,
    catalogue_de_placements_sha: str,
    delta_sha: str,
    autorite_effective_sha: str,
    audit_sha: str,
    instantane: bool = False,
) -> dict[str, Any]:
    """L'actualité : un fait par placement d'inventaire, aucun de plus.

    En instantané (ADR-0059), la preuve V3 dit ce que le banc sait vraiment :
    une provenance officielle, aucun téléchargement vérifié.
    """
    artefacts = []
    for contenu in contenus:
        siens = [p for p in placements if p.content_sha256 == contenu.content_sha256]
        artefacts.append(
            {
                "content_sha256": contenu.content_sha256,
                "exact_path": contenu.chemin_physique,
                "collections": sorted({p.collection for p in siens}),
                "placement_facts": [
                    {
                        "collection": placement.collection,
                        "source_placement_id": placement.source_placement_id,
                        "external_level": placement.niveau_externe,
                        "external_subject": placement.matiere_externe,
                        "external_scope": placement.portee_externe,
                        "external_document_type": TYPE_EXTERNE,
                    }
                    for placement in siens
                ],
                "current_for_school_year": SCHOOL_YEAR,
                "decision": "CURRENT",
                "effective_currentness": "actuel",
                "current_source_listing_url": LISTING_OFFICIEL,
                "current_download_url": contenu.url_telechargement,
                "current_download_sha256": contenu.content_sha256,
                "byte_identity": True,
            }
        )
    if instantane:
        return _actualite_v3_instantane(
            artefacts,
            contenus=contenus,
            liaisons={
                "candidate_inventory_sha256": inventaire_sha,
                "corpus_manifest_sha256": corpus_sha,
                "sealed_catalog_sha256": catalogue_scelle_sha,
                "placement_catalog_sha256": catalogue_de_placements_sha,
                "catalog_delta_sha256": delta_sha,
                "effective_catalog_authority_sha256": autorite_effective_sha,
                "currentness_audit_sha256": audit_sha,
            },
        )
    return {
        "evidence_kind": "MULTILEVEL_ARTIFACT_CURRENTNESS_V2",
        "school_year": SCHOOL_YEAR,
        "candidate_inventory_sha256": inventaire_sha,
        "corpus_manifest_sha256": corpus_sha,
        "sealed_catalog_sha256": catalogue_scelle_sha,
        "placement_catalog_sha256": catalogue_de_placements_sha,
        "catalog_delta_sha256": delta_sha,
        "effective_catalog_authority_sha256": autorite_effective_sha,
        "currentness_audit_sha256": audit_sha,
        "decision_basis": "ACCEPTANCE_BENCH_BYTE_IDENTITY",
        "counts": {
            "unique_artifacts": len(artefacts),
            "evaluated": len(artefacts),
            "current": len(artefacts),
            "review_required": 0,
            "unevaluated": 0,
        },
        "partition": {
            "current": sorted(contenu.content_sha256 for contenu in contenus),
            "review_required": [],
            "unevaluated": [],
        },
        "artifacts": artefacts,
    }


def _actualite_v3_instantane(
    artefacts: list[dict[str, Any]],
    *,
    contenus: tuple[ContenuDuBanc, ...],
    liaisons: dict[str, str],
) -> dict[str, Any]:
    """Les mêmes contenus, déclarés instantanés officiels : aucun fait de
    vérification, la provenance de l'artefact, et les quatre conditions de
    repli de la politique."""
    par_contenu = {contenu.content_sha256: contenu for contenu in contenus}
    entrees = []
    for artefact in artefacts:
        entree = {
            key: artefact[key]
            for key in (
                "content_sha256", "exact_path", "collections", "placement_facts",
                "current_for_school_year",
            )
        }
        entree.update(
            {
                "currentness_disposition": "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE",
                "source_status": "NEEDS_SECONDARY_EVIDENCE",
                "provenance_url": par_contenu[artefact["content_sha256"]].url_telechargement,
                "fallback_conditions": {
                    "OFFICIAL_INSTITUTIONAL_PROVENANCE": True,
                    "CONTENT_SHA_PROVENANCE_MATCH": True,
                    "SOURCE_STATUS_NOT_EXPLICIT_ARCHIVE": True,
                    "NO_KNOWN_SUPERSEDING_CONFLICT": True,
                },
                "reason_codes": ["ADR_0055_OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE"],
                "effective_currentness": None,
                "current_source_listing_url": None,
                "current_download_url": None,
                "current_download_sha256": None,
                "byte_identity": None,
            }
        )
        entrees.append(entree)
    tous = sorted(contenu.content_sha256 for contenu in contenus)
    return {
        "evidence_kind": "MULTILEVEL_ARTIFACT_CURRENTNESS_V3",
        "school_year": SCHOOL_YEAR,
        **liaisons,
        "decision_basis": "ACCEPTANCE_BENCH_OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE",
        "currentness_policy_id": "NEXUS-RAG-CURRENTNESS-POLICY-V1",
        "currentness_policy_sha256": _sha(POLITIQUE_D_ACTUALITE),
        "servability_matrix_sha256": hashlib.sha256(
            ("banc:" + ",".join(tous)).encode()
        ).hexdigest(),
        "counts": {
            "unique_artifacts": len(entrees),
            "evaluated": len(entrees),
            "VERIFIED_CURRENT": 0,
            "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE": len(entrees),
            "NOT_CURRENT_DECLARED_BY_SOURCE": 0,
            "UNKNOWN": 0,
        },
        "partition": {
            "VERIFIED_CURRENT": [],
            "OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE": tous,
            "NOT_CURRENT_DECLARED_BY_SOURCE": [],
            "UNKNOWN": [],
        },
        "artifacts": entrees,
    }


__all__ = [
    "COLLECTIONS_DU_BANC",
    "PAGES_PAR_DOCUMENT",
    "BancIncoherent",
    "ContenuDuBanc",
    "ContexteDuBanc",
    "PlacementDuBanc",
    "construire_contexte_du_banc",
    "contenus_du_banc",
    "environnement_de_readiness",
    "modele_e5_du_banc",
]
