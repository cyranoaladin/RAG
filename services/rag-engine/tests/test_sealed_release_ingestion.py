"""Point d'entrée d'ingestion orienté release scellée — refus et couverture.

Deux matières premières, et c'est délibéré :

* la **vraie** release ``production-profile-gate-2026-2027-v2`` du dépôt, pour
  tout ce qui se prouve en comptant (11 / 315 / 479 / 8268). Recompter un
  fixture inventé ne prouverait que l'arithmétique du fixture ;
* une release synthétique minuscule mais **complète** (manifeste, subjects,
  artefacts, inventaire, manifeste de transfert, PDF réels), pour les refus
  qui exigent de casser quelque chose — on ne mute jamais la release réelle.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingestor.ingestion_control import provisioning  # noqa: E402
from ingestor.ingestion_profiles.registry import load_profile_registry  # noqa: E402
from ingestor.ingestion_worker import sealed_release_ingestion as sri  # noqa: E402
from ingestor.ingestion_worker import sealed_release_ingestion_cli as cli  # noqa: E402

REAL_RELEASE_DIR = (
    REPO_ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2"
    / "release-1b9eba0c0eb0ab13/profile_gate"
)
REAL_TRANSFER_MANIFEST = (
    REPO_ROOT
    / "docs/reports/evidence/external_staging_v2_artifact_transfer_manifest.json"
)
REAL_PROFILES_DIR = ENGINE_ROOT / "configs/ingestion_profiles/v2_livraison_319"

EXPECTED_COLLECTIONS = (
    "rag_nexus_dgemc_terminale_option",
    "rag_nexus_hggsp_premiere_specialite",
    "rag_nexus_hggsp_terminale_specialite",
    "rag_nexus_hlp_premiere_specialite",
    "rag_nexus_hlp_terminale_specialite",
    "rag_nexus_nsi_premiere_specialite",
    "rag_nexus_nsi_terminale_specialite",
    "rag_nexus_ses_premiere_specialite",
    "rag_nexus_ses_terminale_specialite",
    "rag_nexus_svt_premiere_specialite",
    "rag_nexus_svt_terminale_specialite",
)

SYNTHETIC_COLLECTIONS = (
    "rag_nexus_hggsp_premiere_specialite",
    "rag_nexus_hlp_terminale_specialite",
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest_of(path: Path) -> str:
    return _sha256(path.read_bytes())


# --------------------------------------------------------------------------
# La release réelle du dépôt — jamais modifiée.
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_facts() -> sri.SealedReleaseFacts:
    manifest_digest = _digest_of(REAL_RELEASE_DIR / "production-profile-gate.release.json")
    manifest = json.loads(
        (REAL_RELEASE_DIR / "production-profile-gate.release.json").read_text("utf-8")
    )
    return sri.load_sealed_release(
        REAL_RELEASE_DIR,
        release_manifest_sha256=manifest_digest,
        artifacts_release_sha256=manifest["artifact_registry"]["sha256"],
        candidate_inventory_sha256=manifest["authorities"]["candidate_inventory_sha256"],
        artifact_transfer_manifest_path=REAL_TRANSFER_MANIFEST,
        artifact_transfer_manifest_sha256=_digest_of(REAL_TRANSFER_MANIFEST),
    )


# --------------------------------------------------------------------------
# Une release synthétique complète, que l'on peut casser.
# --------------------------------------------------------------------------


def _profile_scope(collection: str) -> dict[str, Any]:
    document = yaml.safe_load((REAL_PROFILES_DIR / f"{collection}.yml").read_text("utf-8"))
    return dict(document["scope"])


def _build_synthetic_release(root: Path) -> dict[str, Any]:
    """Écrit une release scellée complète et cohérente, PDF compris.

    Les scopes sont lus dans les VRAIS profils gouvernés : un fixture qui
    inventerait son propre scope ne prouverait rien de la confrontation
    entre release et profil."""
    release_dir = root / "release"
    (release_dir / "subjects").mkdir(parents=True)
    store = root / "store"
    store.mkdir()

    # Deux artefacts réels (octets écrits, digest recalculé), dont le premier
    # est placé dans les deux collections : 3 placements, 2 artefacts.
    artifacts: dict[str, dict[str, Any]] = {}
    contents = {
        "a": b"%PDF-1.4 hggsp+hlp partage\n",
        "b": b"%PDF-1.4 hlp seul\n",
    }
    identifiers: dict[str, str] = {}
    chunk_counts = {"a": 2, "b": 3}
    for key, payload in contents.items():
        identifier = _sha256(payload)
        identifiers[key] = identifier
        (store / f"{identifier}.pdf").write_bytes(payload)
        artifacts[identifier] = {
            "artifact_id": identifier,
            "content_sha256": identifier,
            "source_url": f"https://eduscol.education.gouv.fr/fichier-{key}.pdf",
            "type_doc": "ressource_officielle",
            "title": f"Artefact {key}",
            "page_count": 1,
            "chunks": [
                {"chunk_id": f"{identifier}-{index}", "chunk_index": index,
                 "chunk_sha256": _sha256(f"{identifier}-{index}".encode()),
                 "page_start": 1, "page_end": 1}
                for index in range(chunk_counts[key])
            ],
        }

    placements = [
        (SYNTHETIC_COLLECTIONS[0], "a", "spid-a-hggsp"),
        (SYNTHETIC_COLLECTIONS[1], "a", "spid-a-hlp"),
        (SYNTHETIC_COLLECTIONS[1], "b", "spid-b-hlp"),
    ]

    inventory_collections: list[dict[str, Any]] = []
    subjects: list[dict[str, Any]] = []
    for collection in SYNTHETIC_COLLECTIONS:
        scope = _profile_scope(collection)
        own = [entry for entry in placements if entry[0] == collection]
        subject = {
            "collection": collection,
            "release_id": f"synthetic-{collection}",
            "release_kind": "MULTILEVEL_SUBJECT_RELEASE_V2",
            "school_year": scope["school_year"],
            "programme_version": scope["programme_version"],
            "profile": {
                "version": "profile-gate-v2",
                "fingerprint": "0" * 64,
                "manifest_digest": "1" * 64,
            },
            "expected_counts": {
                "placements": len(own),
                "unique_artifact_references": len(own),
            },
            "placements": [
                {
                    "artifact_id": identifiers[key],
                    "placement_id": f"pid-{key}-{collection}",
                    "source_placement_id": source_placement_id,
                    "placement_status": "active",
                    "review_status": "reviewed",
                    "currentness": "current",
                    "tenant": scope["tenant"],
                    "collection": collection,
                    "niveau": scope["niveau"],
                    "voie": scope["voie"],
                    "matiere": scope["matiere"],
                    "candidat": scope["candidat"],
                    "visibility": scope["visibility"],
                    "school_year": scope["school_year"],
                    "programme_version": scope["programme_version"],
                }
                for _, key, source_placement_id in own
            ],
        }
        path = f"subjects/{collection}.release.json"
        (release_dir / path).write_text(
            json.dumps(subject, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        subjects.append(
            {
                "collection": collection,
                "path": path,
                "sha256": _digest_of(release_dir / path),
            }
        )
        inventory_collections.append(
            {
                "collection": collection,
                "candidates": [
                    {
                        "content_sha256": identifiers[key],
                        "placements": [
                            {
                                "source_placement_id": source_placement_id,
                                "external_document_type": "ressource-accompagnement",
                                "source_url": (
                                    "https://eduscol.education.gouv.fr/"
                                    f"page-{collection}"
                                ),
                                "title": f"Artefact {key}",
                            }
                        ],
                    }
                    for _, key, source_placement_id in own
                ],
            }
        )

    artifacts_document = {
        "release_id": "synthetic-release",
        "release_kind": "MULTILEVEL_AGGREGATE_ARTIFACTS_V2",
        "school_year": "2026-2027",
        "expected_counts": {"unique_artifacts": len(artifacts)},
        "artifacts": list(artifacts.values()),
    }
    (release_dir / "artifacts.release.json").write_text(
        json.dumps(artifacts_document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    inventory_document = {
        "inventory_kind": "MULTILEVEL_CANDIDATE_INVENTORY_V1",
        "school_year": "2026-2027",
        "collections": inventory_collections,
    }
    (release_dir / "candidate_inventory.json").write_text(
        json.dumps(inventory_document, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest = {
        "release_id": "synthetic-release",
        "release_kind": sri.SEALED_RELEASE_KIND,
        "release_mode": "rehearsal",
        "activation_status": "NO_PRODUCTION_ACTIVATION",
        "promotion_status": "NOT_PROMOTABLE",
        "review_status": "PRE_REVIEW",
        "school_year": "2026-2027",
        "expected_counts": {
            "subjects": len(SYNTHETIC_COLLECTIONS),
            "unique_artifacts": len(artifacts),
            "placements": len(placements),
            "unique_chunks": sum(chunk_counts.values()),
        },
        "artifact_registry": {
            "path": "artifacts.release.json",
            "sha256": _digest_of(release_dir / "artifacts.release.json"),
        },
        "authorities": {
            "candidate_inventory_sha256": _digest_of(
                release_dir / "candidate_inventory.json"
            ),
        },
        "subjects": subjects,
    }
    (release_dir / "production-profile-gate.release.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    transfer = {
        "manifest_kind": "NEXUS-STAGING-ARTIFACT-TRANSFER-V1",
        "release_id": "synthetic-release",
        "file_count": len(artifacts),
        "digest_missing": 0,
        "digest_mismatches": 0,
        "files": [
            {
                "file": f"{identifier}.pdf",
                "sha256_expected": identifier,
                "sha256_observed": identifier,
            }
            for identifier in sorted(artifacts)
        ],
    }
    transfer_path = root / "transfer_manifest.json"
    transfer_path.write_text(
        json.dumps(transfer, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    profiles_dir = root / "profiles"
    profiles_dir.mkdir()
    for collection in SYNTHETIC_COLLECTIONS:
        shutil.copy(
            REAL_PROFILES_DIR / f"{collection}.yml", profiles_dir / f"{collection}.yml"
        )

    return {
        "release_dir": release_dir,
        "store": store,
        "profiles_dir": profiles_dir,
        "transfer_path": transfer_path,
        "identifiers": identifiers,
        "chunk_counts": chunk_counts,
    }


def _load_synthetic(build: dict[str, Any]) -> sri.SealedReleaseFacts:
    release_dir: Path = build["release_dir"]
    manifest = json.loads(
        (release_dir / "production-profile-gate.release.json").read_text("utf-8")
    )
    return sri.load_sealed_release(
        release_dir,
        release_manifest_sha256=_digest_of(
            release_dir / "production-profile-gate.release.json"
        ),
        artifacts_release_sha256=manifest["artifact_registry"]["sha256"],
        candidate_inventory_sha256=manifest["authorities"]["candidate_inventory_sha256"],
        artifact_transfer_manifest_path=build["transfer_path"],
        artifact_transfer_manifest_sha256=_digest_of(build["transfer_path"]),
    )


@pytest.fixture
def synthetic(tmp_path: Path) -> dict[str, Any]:
    return _build_synthetic_release(tmp_path)


def _reseal(release_dir: Path, mutate) -> str:
    """Muter le manifeste puis le resceller — le digest reste cohérent.

    Sans ce rescellement, chaque mutation échouerait sur le digest et on ne
    prouverait jamais le refus qu'on vise."""
    path = release_dir / "production-profile-gate.release.json"
    manifest = json.loads(path.read_text("utf-8"))
    mutate(manifest)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return _digest_of(path)


# ==========================================================================
# 1. Release non scellée refusée
# ==========================================================================


def test_1_une_release_sans_expected_counts_est_refusee(synthetic: dict[str, Any]) -> None:
    digest = _reseal(synthetic["release_dir"], lambda m: m.pop("expected_counts"))
    with pytest.raises(sri.SealedReleaseIngestionError, match="release non scellée"):
        sri.load_sealed_release(
            synthetic["release_dir"],
            release_manifest_sha256=digest,
            artifacts_release_sha256="0" * 64,
            candidate_inventory_sha256="0" * 64,
            artifact_transfer_manifest_path=synthetic["transfer_path"],
            artifact_transfer_manifest_sha256=_digest_of(synthetic["transfer_path"]),
        )


def test_1bis_une_release_dont_le_kind_nest_pas_scelle_est_refusee(
    synthetic: dict[str, Any],
) -> None:
    digest = _reseal(
        synthetic["release_dir"],
        lambda m: m.__setitem__("release_kind", "MULTILEVEL_DRAFT"),
    )
    with pytest.raises(sri.SealedReleaseIngestionError, match="release_kind"):
        sri.load_sealed_release(
            synthetic["release_dir"],
            release_manifest_sha256=digest,
            artifacts_release_sha256="0" * 64,
            candidate_inventory_sha256="0" * 64,
            artifact_transfer_manifest_path=synthetic["transfer_path"],
            artifact_transfer_manifest_sha256=_digest_of(synthetic["transfer_path"]),
        )


def test_1ter_une_release_sans_autorites_declarees_est_refusee(
    synthetic: dict[str, Any],
) -> None:
    digest = _reseal(synthetic["release_dir"], lambda m: m.pop("authorities"))
    with pytest.raises(sri.SealedReleaseIngestionError, match="autorités absentes"):
        sri.load_sealed_release(
            synthetic["release_dir"],
            release_manifest_sha256=digest,
            artifacts_release_sha256="0" * 64,
            candidate_inventory_sha256="0" * 64,
            artifact_transfer_manifest_path=synthetic["transfer_path"],
            artifact_transfer_manifest_sha256=_digest_of(synthetic["transfer_path"]),
        )


# ==========================================================================
# 2. Digest de release divergent refusé
# ==========================================================================


def test_2_un_digest_de_manifeste_divergent_est_refuse(synthetic: dict[str, Any]) -> None:
    with pytest.raises(sri.SealedReleaseIngestionError, match="manifeste de release"):
        sri.load_sealed_release(
            synthetic["release_dir"],
            release_manifest_sha256="f" * 64,
            artifacts_release_sha256="0" * 64,
            candidate_inventory_sha256="0" * 64,
            artifact_transfer_manifest_path=synthetic["transfer_path"],
            artifact_transfer_manifest_sha256=_digest_of(synthetic["transfer_path"]),
        )


def test_2bis_un_digest_dartefacts_qui_nest_pas_celui_nomme_est_refuse(
    synthetic: dict[str, Any],
) -> None:
    release_dir: Path = synthetic["release_dir"]
    manifest = json.loads(
        (release_dir / "production-profile-gate.release.json").read_text("utf-8")
    )
    with pytest.raises(sri.SealedReleaseIngestionError, match="artifacts.release.json"):
        sri.load_sealed_release(
            release_dir,
            release_manifest_sha256=_digest_of(
                release_dir / "production-profile-gate.release.json"
            ),
            artifacts_release_sha256="0" * 64,
            candidate_inventory_sha256=manifest["authorities"][
                "candidate_inventory_sha256"
            ],
            artifact_transfer_manifest_path=synthetic["transfer_path"],
            artifact_transfer_manifest_sha256=_digest_of(synthetic["transfer_path"]),
        )


def test_2ter_un_subject_modifie_apres_scellement_est_refuse(
    synthetic: dict[str, Any],
) -> None:
    release_dir: Path = synthetic["release_dir"]
    subject = release_dir / "subjects" / f"{SYNTHETIC_COLLECTIONS[0]}.release.json"
    document = json.loads(subject.read_text("utf-8"))
    document["placements"][0]["review_status"] = "pending"
    subject.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    manifest = json.loads(
        (release_dir / "production-profile-gate.release.json").read_text("utf-8")
    )
    with pytest.raises(sri.SealedReleaseIngestionError, match="subject "):
        sri.load_sealed_release(
            release_dir,
            release_manifest_sha256=_digest_of(
                release_dir / "production-profile-gate.release.json"
            ),
            artifacts_release_sha256=manifest["artifact_registry"]["sha256"],
            candidate_inventory_sha256=manifest["authorities"][
                "candidate_inventory_sha256"
            ],
            artifact_transfer_manifest_path=synthetic["transfer_path"],
            artifact_transfer_manifest_sha256=_digest_of(synthetic["transfer_path"]),
        )


def test_2quater_un_manifeste_de_transfert_divergent_est_refuse(
    synthetic: dict[str, Any],
) -> None:
    release_dir: Path = synthetic["release_dir"]
    manifest = json.loads(
        (release_dir / "production-profile-gate.release.json").read_text("utf-8")
    )
    with pytest.raises(sri.SealedReleaseIngestionError, match="manifeste de transfert"):
        sri.load_sealed_release(
            release_dir,
            release_manifest_sha256=_digest_of(
                release_dir / "production-profile-gate.release.json"
            ),
            artifacts_release_sha256=manifest["artifact_registry"]["sha256"],
            candidate_inventory_sha256=manifest["authorities"][
                "candidate_inventory_sha256"
            ],
            artifact_transfer_manifest_path=synthetic["transfer_path"],
            artifact_transfer_manifest_sha256="e" * 64,
        )


# ==========================================================================
# 3 & 4. Le store d'artefacts
# ==========================================================================


def test_3_un_store_incomplet_est_refuse(synthetic: dict[str, Any], tmp_path: Path) -> None:
    facts = _load_synthetic(synthetic)
    vide = tmp_path / "vide"
    vide.mkdir()
    with pytest.raises(sri.SealedReleaseIngestionError, match="absent"):
        sri.require_artifact_store_is_complete(facts, vide)


def test_3bis_un_seul_artefact_manquant_suffit_a_refuser(
    synthetic: dict[str, Any],
) -> None:
    facts = _load_synthetic(synthetic)
    store: Path = synthetic["store"]
    (store / f"{synthetic['identifiers']['b']}.pdf").unlink()
    with pytest.raises(sri.SealedReleaseIngestionError, match="1 artefact"):
        sri.require_artifact_store_is_complete(facts, store)


def test_4_un_pdf_au_digest_divergent_est_refuse(synthetic: dict[str, Any]) -> None:
    facts = _load_synthetic(synthetic)
    store: Path = synthetic["store"]
    (store / f"{synthetic['identifiers']['b']}.pdf").write_bytes(b"%PDF-1.4 substitue\n")
    with pytest.raises(sri.SealedReleaseIngestionError, match="digest divergent"):
        sri.require_artifact_store_is_complete(facts, store)


def test_4bis_un_transfert_qui_declare_un_digest_divergent_est_refuse(
    synthetic: dict[str, Any],
) -> None:
    transfer_path: Path = synthetic["transfer_path"]
    transfer = json.loads(transfer_path.read_text("utf-8"))
    transfer["digest_mismatches"] = 1
    transfer_path.write_text(json.dumps(transfer, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(sri.SealedReleaseIngestionError, match="digests manquants"):
        _load_synthetic(synthetic)


def test_4ter_un_store_complet_et_exact_est_accepte(synthetic: dict[str, Any]) -> None:
    facts = _load_synthetic(synthetic)
    resolus = sri.require_artifact_store_is_complete(facts, synthetic["store"])
    assert set(resolus) == set(facts.artifact_ids)


# ==========================================================================
# 5. Autorisation LOT41A
# ==========================================================================


def test_5_une_collection_sans_autorisation_lot41a_est_refusee(
    synthetic: dict[str, Any],
) -> None:
    facts = _load_synthetic(synthetic)
    profiles = load_profile_registry(synthetic["profiles_dir"])
    scopes = sri.resolve_scopes(facts, profiles)
    appels: list[str] = []

    def verifier(conn: Any, **kwargs: Any) -> Any:  # pragma: no cover - jamais appelé
        appels.append(str(kwargs.get("authorization_id")))
        raise AssertionError("aucune vérification ne doit avoir lieu")

    with pytest.raises(sri.SealedReleaseIngestionError, match="non fournie"):
        sri.require_scope_authorizations(
            object(),  # type: ignore[arg-type]
            facts=facts,
            scopes=scopes,
            scope_authorization_ids={SYNTHETIC_COLLECTIONS[0]: "lot41a-staging-v2-a"},
            verifier=verifier,
        )
    assert appels == []


def test_5bis_une_autorisation_hors_release_est_refusee(
    synthetic: dict[str, Any],
) -> None:
    facts = _load_synthetic(synthetic)
    profiles = load_profile_registry(synthetic["profiles_dir"])
    scopes = sri.resolve_scopes(facts, profiles)
    mapping = {collection: f"lot41a-{collection}" for collection in SYNTHETIC_COLLECTIONS}
    mapping["rag_nexus_nsi_premiere_specialite"] = "lot41a-intrus"
    with pytest.raises(sri.SealedReleaseIngestionError, match="hors release"):
        sri.require_scope_authorizations(
            object(),  # type: ignore[arg-type]
            facts=facts,
            scopes=scopes,
            scope_authorization_ids=mapping,
            verifier=lambda *a, **k: pytest.fail("jamais appelé"),
        )


def test_5ter_le_refus_du_verificateur_canonique_nest_jamais_rattrape(
    synthetic: dict[str, Any],
) -> None:
    facts = _load_synthetic(synthetic)
    profiles = load_profile_registry(synthetic["profiles_dir"])
    scopes = sri.resolve_scopes(facts, profiles)

    def verifier(conn: Any, **kwargs: Any) -> Any:
        raise RuntimeError("authorization was revoked")

    with pytest.raises(RuntimeError, match="revoked"):
        sri.require_scope_authorizations(
            object(),  # type: ignore[arg-type]
            facts=facts,
            scopes=scopes,
            scope_authorization_ids={
                collection: f"lot41a-{collection}" for collection in SYNTHETIC_COLLECTIONS
            },
            verifier=verifier,
        )


def test_5quater_le_scope_gouverne_est_transmis_au_verificateur(
    synthetic: dict[str, Any],
) -> None:
    """L'autorisation est vérifiée CONTRE le scope, pas seulement nommée."""
    facts = _load_synthetic(synthetic)
    profiles = load_profile_registry(synthetic["profiles_dir"])
    scopes = sri.resolve_scopes(facts, profiles)
    vus: list[tuple[str, str]] = []

    def verifier(conn: Any, *, authorization_id: str, scope: Any) -> Any:
        vus.append((authorization_id, scope.collection))
        return _FakeAuthorization(authorization_id)

    sri.require_scope_authorizations(
        object(),  # type: ignore[arg-type]
        facts=facts,
        scopes=scopes,
        scope_authorization_ids={
            collection: f"lot41a-{collection}" for collection in SYNTHETIC_COLLECTIONS
        },
        verifier=verifier,
    )
    assert vus == [
        (f"lot41a-{collection}", collection)
        for collection in sorted(SYNTHETIC_COLLECTIONS)
    ]


class _FakeAuthorization:
    """Autorisation déjà vérifiée — seuls les champs lus ici sont portés."""

    def __init__(self, authorization_id: str) -> None:
        self.authorization_id = authorization_id
        self.authorization_digest = "d" * 64
        self.allowed_domains = ("eduscol.education.gouv.fr",)


def test_5quinquies_une_provenance_hors_domaine_autorise_est_refusee(
    synthetic: dict[str, Any],
) -> None:
    facts = _load_synthetic(synthetic)
    profiles = load_profile_registry(synthetic["profiles_dir"])
    scopes = sri.resolve_scopes(facts, profiles)

    class _Etroite(_FakeAuthorization):
        def __init__(self, authorization_id: str) -> None:
            super().__init__(authorization_id)
            self.allowed_domains = ("www.education.gouv.fr",)

    with pytest.raises(sri.SealedReleaseIngestionError, match="hors des domaines"):
        sri.require_scope_authorizations(
            object(),  # type: ignore[arg-type]
            facts=facts,
            scopes=scopes,
            scope_authorization_ids={
                collection: f"lot41a-{collection}" for collection in SYNTHETIC_COLLECTIONS
            },
            verifier=lambda conn, *, authorization_id, scope: _Etroite(authorization_id),
        )


# ==========================================================================
# 6 & 7. Le périmètre de collections
# ==========================================================================


def test_6_une_collection_manquante_est_refusee(real_facts: sri.SealedReleaseFacts) -> None:
    with pytest.raises(sri.SealedReleaseIngestionError, match="manquantes"):
        sri.require_collections_match(
            real_facts, (*EXPECTED_COLLECTIONS, "rag_nexus_maths_terminale_gen_specialite")
        )


def test_7_une_collection_supplementaire_est_refusee(
    real_facts: sri.SealedReleaseFacts,
) -> None:
    with pytest.raises(sri.SealedReleaseIngestionError, match="surplus"):
        sri.require_collections_match(real_facts, EXPECTED_COLLECTIONS[:-1])


def test_7bis_le_perimetre_exact_est_accepte(real_facts: sri.SealedReleaseFacts) -> None:
    sri.require_collections_match(real_facts, EXPECTED_COLLECTIONS)


# ==========================================================================
# 8 à 14. La couverture réellement recomptée sur la release du dépôt
# ==========================================================================


def test_8_les_onze_collections_sont_couvertes(real_facts: sri.SealedReleaseFacts) -> None:
    assert real_facts.collections == tuple(sorted(EXPECTED_COLLECTIONS))
    assert len(real_facts.collections) == 11


def test_9_les_315_artefacts_uniques_sont_couverts(
    real_facts: sri.SealedReleaseFacts,
) -> None:
    assert len(real_facts.artifact_ids) == 315
    assert len(real_facts.transferred_artifact_ids) == 315
    assert real_facts.artifact_ids == real_facts.transferred_artifact_ids


def test_10_les_479_placements_sont_couverts(real_facts: sri.SealedReleaseFacts) -> None:
    assert len(real_facts.placements) == 479


def test_11_les_8268_chunks_sont_couverts(real_facts: sri.SealedReleaseFacts) -> None:
    assert real_facts.unique_chunk_count == 8268


def test_11bis_les_quatre_comptes_sont_recomptes_et_concordent(
    real_facts: sri.SealedReleaseFacts,
) -> None:
    sri.require_expected_counts(real_facts)
    assert real_facts.expected_counts == {
        "subjects": 11,
        "unique_artifacts": 315,
        "placements": 479,
        "unique_chunks": 8268,
    }


def test_11ter_un_compte_annonce_faux_est_refuse(real_facts: sri.SealedReleaseFacts) -> None:
    menteuse = sri.SealedReleaseFacts(
        release_id=real_facts.release_id,
        release_kind=real_facts.release_kind,
        release_manifest_sha256=real_facts.release_manifest_sha256,
        artifacts_release_sha256=real_facts.artifacts_release_sha256,
        candidate_inventory_sha256=real_facts.candidate_inventory_sha256,
        artifact_transfer_manifest_sha256=real_facts.artifact_transfer_manifest_sha256,
        expected_counts={**real_facts.expected_counts, "placements": 33},
        collections=real_facts.collections,
        profile_versions=real_facts.profile_versions,
        artifact_ids=real_facts.artifact_ids,
        transferred_artifact_ids=real_facts.transferred_artifact_ids,
        placements=real_facts.placements,
        _artifact_chunk_counts=real_facts.artifact_chunk_counts,
    )
    with pytest.raises(sri.SealedReleaseIngestionError, match="expected_counts.placements"):
        sri.require_expected_counts(menteuse)


def _placements_de(facts: sri.SealedReleaseFacts, collection: str) -> int:
    return sum(1 for placement in facts.placements if placement.collection == collection)


def test_12_hggsp_premiere_est_couverte(real_facts: sri.SealedReleaseFacts) -> None:
    assert _placements_de(real_facts, "rag_nexus_hggsp_premiere_specialite") == 39


def test_13_hggsp_terminale_est_couverte(real_facts: sri.SealedReleaseFacts) -> None:
    assert _placements_de(real_facts, "rag_nexus_hggsp_terminale_specialite") == 35


def test_14_hlp_terminale_est_couverte(real_facts: sri.SealedReleaseFacts) -> None:
    assert _placements_de(real_facts, "rag_nexus_hlp_terminale_specialite") == 89


def test_14bis_les_onze_collections_totalisent_bien_479(
    real_facts: sri.SealedReleaseFacts,
) -> None:
    par_collection = {
        collection: _placements_de(real_facts, collection)
        for collection in real_facts.collections
    }
    assert sum(par_collection.values()) == 479
    assert all(compte > 0 for compte in par_collection.values())


def test_14ter_le_type_ecrit_est_le_type_nexus_gouverne_pas_le_type_externe(
    real_facts: sri.SealedReleaseFacts,
) -> None:
    """``proposed_type_doc`` reçoit ``type_doc``, jamais le vocabulaire externe.

    ``programme-officiel`` n'est pas une valeur de ``TypeDoc`` — l'écrire
    tel quel serait un type inventé, refusé par le contrat."""
    from nexus_contracts.document import TypeDoc

    connus = {member.value for member in TypeDoc}
    externes = {placement.external_document_type for placement in real_facts.placements}
    assert externes - connus, "le fixture ne prouverait rien si les deux coïncidaient"
    assert all(placement.type_doc in connus for placement in real_facts.placements)


# ==========================================================================
# 15 & 16. canonical_url et source_url
# ==========================================================================


def test_15_aucune_primitive_de_release_scellee_nexpose_de_canonical_url() -> None:
    """Le paramètre n'existe pas : on ne peut pas en fournir un par erreur."""
    signature = inspect.signature(provisioning.persist_sealed_release_candidate)
    assert "canonical_url" not in signature.parameters


def test_15bis_lecriture_du_candidat_scelle_pose_null_litteralement() -> None:
    source = inspect.getsource(provisioning.persist_sealed_release_candidate)
    assert "canonical_url, domain" in source
    assert "VALUES (%s, %s, %s, %s, %s, NULL," in source


def test_15ter_le_module_dingestion_necrit_jamais_de_canonical_url() -> None:
    source = (
        ENGINE_ROOT / "src/ingestor/ingestion_worker/sealed_release_ingestion.py"
    ).read_text("utf-8")
    assert "canonical_url=" not in source
    assert '"canonical_url"' not in source


def test_16_la_provenance_est_nommee_provenance_et_jamais_identite(
    real_facts: sri.SealedReleaseFacts,
) -> None:
    """Les deux URL portées sont des provenances, et le disent."""
    placement = real_facts.placements[0]
    assert placement.discovery_url.startswith("https://")
    assert placement.provenance_url.startswith("https://")
    source = (
        ENGINE_ROOT / "src/ingestor/ingestion_worker/sealed_release_ingestion.py"
    ).read_text("utf-8")
    assert '"provenance_discovery_url"' in source
    assert '"provenance_artifact_url"' in source


def test_16bis_toutes_les_provenances_viennent_du_domaine_officiel(
    real_facts: sri.SealedReleaseFacts,
) -> None:
    from urllib.parse import urlsplit

    hotes = {
        urlsplit(url).hostname
        for placement in real_facts.placements
        for url in (placement.discovery_url, placement.provenance_url)
    }
    assert hotes == {"eduscol.education.gouv.fr"}


def test_16ter_la_cle_de_deduplication_derive_du_contenu_pas_de_lurl(
    real_facts: sri.SealedReleaseFacts,
) -> None:
    """479 placements, 27 URL : une clé par URL effacerait le corpus."""
    urls = {placement.provenance_url for placement in real_facts.placements}
    contenus = {
        (placement.collection, placement.artifact_id)
        for placement in real_facts.placements
    }
    assert len(urls) < 30
    assert len(contenus) == 479


# ==========================================================================
# 17, 18, 20, 21, 22. Ce que ce point d'entrée ne peut pas faire
# ==========================================================================


MODULE_SOURCES = (
    "src/ingestor/ingestion_worker/sealed_release_ingestion.py",
    "src/ingestor/ingestion_worker/sealed_release_ingestion_cli.py",
)


def _code_sans_prose(relative: str) -> str:
    """Le code seul — voir ``tests/_source_inspection`` pour le pourquoi."""
    from _source_inspection import code_sans_prose

    return code_sans_prose(ENGINE_ROOT / relative)


def test_17_aucune_publication_nest_atteignable_depuis_ce_point_dentree() -> None:
    for relative in MODULE_SOURCES:
        code = _code_sans_prose(relative)
        assert "rag_chunks" not in code
        assert "rag_artifacts" not in code
        assert "publication_resume" not in code
        assert "PUBLISHED" not in code


def test_17bis_pg_rag_dsn_nest_lu_que_pour_prouver_le_cloisonnement() -> None:
    """Depuis le lot CQ, le CLI LIT ``PG_RAG_DSN`` — pour refuser, jamais
    pour s'y connecter.

    Le manifeste de readiness DÉCLARE que le plan de contrôle et le produit
    sont deux connexions distinctes. Une déclaration qu'on ne peut pas
    contredire ne prouve rien : le CLI la mesure. La seule connexion qu'il
    ouvre reste celle du plan de contrôle."""
    module = _code_sans_prose(
        "src/ingestor/ingestion_worker/sealed_release_ingestion.py"
    )
    assert "PG_RAG_DSN" not in module

    cli_code = _code_sans_prose(
        "src/ingestor/ingestion_worker/sealed_release_ingestion_cli.py"
    )
    assert cli_code.count("PG_RAG_DSN") == 1
    lecture = cli_code[
        cli_code.index("require_control_dsn_differs_from_product") :
        cli_code.index("PG_RAG_DSN") + 20
    ]
    assert "product_dsn = os . environ . get ( \"PG_RAG_DSN\" )" in lecture
    # Une seule connexion est ouverte, et c'est celle du plan de controle.
    assert cli_code.count("psycopg . connect") == 1
    assert "psycopg . connect ( get_ingestion_control_dsn ( ) )" in cli_code


def test_17bis_le_rapport_declare_zero_publication() -> None:
    rapport = sri.IngestionReport(release_id="x")
    assert rapport.published_rows == 0
    assert rapport.as_dict()["published_rows"] == 0


def test_18_aucune_attestation_nest_atteignable_depuis_ce_point_dentree() -> None:
    for relative in MODULE_SOURCES:
        code = _code_sans_prose(relative)
        assert "publication_attestations" not in code
        assert "attest_publication" not in code
    rapport = sri.IngestionReport(release_id="x")
    assert rapport.attestations == 0


def test_19_letat_terminal_declare_est_needs_review() -> None:
    from nexus_contracts.resource_state import ResourceState

    assert sri.TERMINAL_STATE is ResourceState.NEEDS_REVIEW
    assert sri.STATE_SEQUENCE[-1] is ResourceState.NEEDS_REVIEW
    assert ResourceState.REVIEWED not in sri.STATE_SEQUENCE
    assert ResourceState.RETRIEVAL_ELIGIBLE not in sri.STATE_SEQUENCE


def test_19bis_la_sequence_detats_est_celle_que_la_machine_autorise() -> None:
    """Chaque pas est valide, et aucun raccourci ne l'est."""
    from nexus_contracts.resource_state import (
        ResourceState,
        is_valid_resource_transition,
    )

    precedent = ResourceState.DISCOVERED
    for cible in sri.STATE_SEQUENCE:
        assert is_valid_resource_transition(precedent, cible)
        precedent = cible
    assert not is_valid_resource_transition(
        ResourceState.DISCOVERED, ResourceState.NEEDS_REVIEW
    )


def test_20_lot42_v1_est_inchange() -> None:
    """Le protocole unitaire garde son ``canonical_url`` obligatoire."""
    from nexus_contracts.authority_artifacts import PublicationReviewArtifact

    champs = PublicationReviewArtifact.model_fields
    assert champs["canonical_url"].is_required()
    assert "LOT42-V1" in str(champs["protocol_version"].annotation)


def test_21_le_resource_pipeline_est_inchange() -> None:
    """Le pipeline de découverte écrit exactement la même ligne qu'avant."""
    from nexus_contracts.ingestion import ResourceCandidate

    assert ResourceCandidate.model_fields["canonical_url"].is_required()

    signature = inspect.signature(provisioning.create_resource)
    assert signature.parameters["pipeline_kind"].default == provisioning.RESOURCE_PIPELINE

    candidate_signature = inspect.signature(provisioning.persist_resource_candidate)
    assert set(candidate_signature.parameters) == {"conn", "candidate"}


def test_21bis_une_ligne_de_release_scellee_nest_jamais_relue_comme_un_candidat() -> None:
    source = inspect.getsource(provisioning.find_resource_candidate)
    assert "SEALED_RELEASE_PIPELINE" in source
    assert "SealedReleaseRowError" in source


def test_22_la_production_est_impossible() -> None:
    assert cli.REQUIRED_ENVIRONMENT == "rehearsal"
    source = (
        ENGINE_ROOT / "src/ingestor/ingestion_worker/sealed_release_ingestion_cli.py"
    ).read_text("utf-8")
    assert "readiness.environment != REQUIRED_ENVIRONMENT" in source


def test_22bis_le_cli_refuse_de_demarrer_hors_rehearsal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Depuis le lot CQ, le refus vient du gate de repetition lui-meme."""

    class _Production:
        environment = "production"
        manifest = None
        manifest_sha256 = "0" * 64

    monkeypatch.setattr(
        cli, "enforce_staging_readiness_gate", lambda: _Production()
    )
    code = cli.main(
        [
            "--release-dir", str(REAL_RELEASE_DIR),
            "--release-manifest-sha256", "0" * 64,
            "--artifacts-release-sha256", "0" * 64,
            "--candidate-inventory-sha256", "0" * 64,
            "--artifact-transfer-manifest-path", str(REAL_TRANSFER_MANIFEST),
            "--artifact-transfer-manifest-sha256", "0" * 64,
            "--artifact-store-dir", str(REAL_RELEASE_DIR),
            "--profiles-dir", str(REAL_PROFILES_DIR),
            "--owner", "operateur",
            "--expected-role", "ingestion_control_app",
            "--scope-authorization", "rag_nexus_hlp_terminale_specialite=lot41a-x",
        ]
    )
    assert code == 1
    erreur = capsys.readouterr().err
    assert "refusing to run under 'production'" in erreur


def test_22ter_le_cli_refuse_deux_autorisations_pour_une_meme_collection() -> None:
    with pytest.raises(sri.SealedReleaseIngestionError, match="ambiguïté"):
        cli._scope_authorization_ids([("c", "a1"), ("c", "a2")])


# ==========================================================================
# Le scope vient du profil gouverné
# ==========================================================================


def test_le_scope_est_refuse_quand_la_release_contredit_le_profil(
    synthetic: dict[str, Any],
) -> None:
    release_dir: Path = synthetic["release_dir"]
    subject = release_dir / "subjects" / f"{SYNTHETIC_COLLECTIONS[0]}.release.json"
    document = json.loads(subject.read_text("utf-8"))
    document["placements"][0]["visibility"] = "restricted"
    subject.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path = release_dir / "production-profile-gate.release.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    for entry in manifest["subjects"]:
        entry["sha256"] = _digest_of(release_dir / entry["path"])
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    facts = _load_synthetic(synthetic)
    profiles = load_profile_registry(synthetic["profiles_dir"])
    with pytest.raises(sri.SealedReleaseIngestionError, match="visibility"):
        sri.resolve_scopes(facts, profiles)


def test_le_scope_est_refuse_sans_profil_gouverne(
    synthetic: dict[str, Any], tmp_path: Path
) -> None:
    facts = _load_synthetic(synthetic)
    vide = tmp_path / "profils-vides"
    vide.mkdir()
    with pytest.raises(sri.SealedReleaseIngestionError, match="aucun profil gouverné"):
        sri.resolve_scopes(facts, load_profile_registry(vide))


def test_le_scope_gouverne_porte_laudience_que_la_release_ne_declare_pas(
    synthetic: dict[str, Any],
) -> None:
    facts = _load_synthetic(synthetic)
    scopes = sri.resolve_scopes(facts, load_profile_registry(synthetic["profiles_dir"]))
    for collection in SYNTHETIC_COLLECTIONS:
        assert scopes[collection].audience
        assert all(
            "audience" not in placement.scope_dimensions
            for placement in facts.placements
        )

