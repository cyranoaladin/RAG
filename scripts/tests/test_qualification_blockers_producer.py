"""Épreuves du producteur de blocages de qualification.

La liste était tenue à la main. Deux défauts en découlaient : un blocage dont
la preuve existait pouvait rester ouvert par oubli, et un blocage pouvait être
fermé d'un coup d'éditeur sans preuve. Ces épreuves portent sur les deux.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import build_qualification_blockers as blocages  # noqa: E402

RAPPORT = RACINE / "docs/reports/go_live/qualification_blockers.json"


def test_fermer_sans_preuve_est_refuse_a_la_construction(monkeypatch):
    """LA règle du mandat, tenue par le code et non par la vigilance."""
    faux = (("X", "titre", "operateur", "condition", lambda _r: {"closed": True, "proof": None}),)
    monkeypatch.setattr(blocages, "BLOCAGES", faux)
    with pytest.raises(blocages.PreuveAbsente, match="sans preuve"):
        blocages.construire(RACINE)


def test_un_blocage_sans_verificateur_reste_ouvert(monkeypatch):
    """Ne pas savoir n'est pas fermer."""
    monkeypatch.setattr(
        blocages, "BLOCAGES", (("X", "titre", "operateur", "condition", None),)
    )
    etat = blocages.construire(RACINE)
    assert etat["blockers"][0]["closed"] is False
    assert etat["blockers"][0]["proof"] is None
    assert "ne pas savoir" in etat["blockers"][0]["why_still_open"]


def test_un_verificateur_qui_prouve_ferme(monkeypatch):
    """Le refus doit discriminer, sinon rien ne se fermerait jamais."""
    monkeypatch.setattr(
        blocages,
        "BLOCAGES",
        (
            (
                "X", "titre", "operateur", "condition",
                lambda _r: {"closed": True, "proof": {"verification": "mesurée"}},
            ),
        ),
    )
    etat = blocages.construire(RACINE)
    assert etat["blockers"][0]["closed"] is True
    assert etat["closed_count"] == 1


def test_un_store_absent_ne_ferme_pas(tmp_path, monkeypatch):
    """Une preuve qui ne peut pas être recalculée n'est pas une preuve.

    L'emplacement est ici DANS la racine canonique : ce que le cas éprouve est
    bien l'absence, pas le hors-périmètre, qui a son propre cas.
    """
    monkeypatch.setenv("NEXUS_NON_PDF_STORE", str(tmp_path / "store"))
    (tmp_path / "docs/reports/go_live").mkdir(parents=True)
    for nom, contenu in (
        (blocages.RECONCILIATION, {"rows": [], "gate_counts": {"NON_PDF_SERVABLE": 0}}),
        (
            blocages.MANIFESTE_STORE,
            {"durable_location": str(tmp_path / "store" / "absent"), "sha256sums": []},
        ),
        (
            blocages.POLITIQUE,
            {
                "adopted": True,
                "closes_blocker_when": "x",
                "durable_store": {
                    "canonical_root": str(tmp_path / "store"),
                    "env_override": "NEXUS_NON_PDF_STORE",
                },
            },
        ),
    ):
        (tmp_path / nom).write_text(json.dumps(contenu), encoding="utf-8")
    resultat = blocages.verifier_non_pdf(tmp_path)
    assert resultat["closed"] is False
    assert "store durable absent" in resultat["why"]


def test_une_politique_non_adoptee_ne_ferme_pas(tmp_path):
    (tmp_path / "docs/reports/go_live").mkdir(parents=True)
    for nom, contenu in (
        (blocages.RECONCILIATION, {"rows": [], "gate_counts": {"NON_PDF_SERVABLE": 0}}),
        (blocages.MANIFESTE_STORE, {"durable_location": "/x", "sha256sums": []}),
        (blocages.POLITIQUE, {"adopted": False}),
    ):
        (tmp_path / nom).write_text(json.dumps(contenu), encoding="utf-8")
    assert blocages.verifier_non_pdf(tmp_path)["closed"] is False


def test_une_entree_absente_interrompt(tmp_path):
    with pytest.raises(blocages.EntreeManquante):
        blocages.verifier_non_pdf(tmp_path)


# --- Le rapport VERSIONNÉ -------------------------------------------------


@pytest.fixture(scope="module")
def rapport() -> dict:
    return json.loads(RAPPORT.read_text(encoding="utf-8"))


def test_aucun_blocage_ferme_sans_preuve(rapport):
    for bloc in rapport["blockers"]:
        if bloc["closed"]:
            assert bloc["proof"], bloc["id"]


def test_chaque_blocage_porte_sa_condition_de_fermeture(rapport):
    """Sans condition écrite, son propriétaire ne sait pas quoi produire."""
    for bloc in rapport["blockers"]:
        assert bloc["closing_condition"], bloc["id"]
        assert len(bloc["closing_condition"]) > 20, bloc["id"]


def test_le_rollback_de_production_est_ferme_par_rehearsal_v2(rapport):
    """Le rollback de production est prouvé par le rehearsal Docker V2, pas par staging."""
    rollback = next(b for b in rapport["blockers"] if b["id"] == "ROLLBACK")
    assert rollback["closed"] is True
    assert rollback["proof"]["rollback_pass"] is True
    assert "rehearsal atomique Docker V2" in rollback["proof"]["condition"]


def test_la_reacquisition_non_pdf_est_fermee_par_mesure(rapport):
    bloc = next(b for b in rapport["blockers"] if b["id"] == "NON_PDF_REACQUISITION")
    assert bloc["closed"] is True
    assert bloc["proof"]["servable_resources_verified"] == 37
    assert "RECALCULÉE" in bloc["proof"]["verification"]
    assert bloc["proof"]["does_not_close"]


def test_le_compte_ouvert_correspond_aux_blocages(rapport):
    ouverts = [b for b in rapport["blockers"] if not b["closed"]]
    assert rapport["open_count"] == len(ouverts)
    assert rapport["closed_count"] + rapport["open_count"] == len(rapport["blockers"])


# --- Le store doit être le CANONIQUE, pas n'importe lequel ----------------


def _poser_non_pdf(tmp_path, *, store: Path, taille: int | None = 10,
                   canonical_root: str = "/backup/rag/non-pdf-reacquired"):
    (tmp_path / "docs/reports/go_live").mkdir(parents=True, exist_ok=True)
    store.mkdir(parents=True, exist_ok=True)
    octets = b"x" * 10
    (store / "ressource").write_bytes(octets)
    import hashlib

    empreinte = hashlib.sha256(octets).hexdigest()
    entree = {"name": "ressource", "sha256": empreinte}
    if taille is not None:
        entree["size"] = taille
    for nom, contenu in (
        (
            blocages.RECONCILIATION,
            {
                "rows": [{"sha256": empreinte, "counted_in_37": True}],
                "gate_counts": {"NON_PDF_SERVABLE": 1},
            },
        ),
        (
            blocages.MANIFESTE_STORE,
            {"durable_location": str(store), "sha256sums": [entree]},
        ),
        (
            blocages.POLITIQUE,
            {
                "adopted": True,
                "closes_blocker_when": "condition",
                "does_not_close": [],
                "durable_store": {
                    "canonical_root": canonical_root,
                    "env_override": "NEXUS_NON_PDF_STORE",
                },
            },
        ),
    ):
        (tmp_path / nom).write_text(json.dumps(contenu), encoding="utf-8")
    return empreinte


def test_un_store_hors_racine_canonique_ne_ferme_pas(tmp_path, monkeypatch):
    """La sauvegarde de secours contient les bonnes empreintes — et ne compte pas.

    La politique dit `emergency_is_not_canonical`. Faire confiance au chemin
    que le manifeste NOMME laisserait fermer le blocage sur elle.
    """
    monkeypatch.delenv("NEXUS_NON_PDF_STORE", raising=False)
    secours = tmp_path / "secours" / "non-pdf-reacquired" / "20260911T155246Z"
    _poser_non_pdf(tmp_path, store=secours)
    resultat = blocages.verifier_non_pdf(tmp_path)
    assert resultat["closed"] is False
    assert "hors du store canonique" in resultat["why"]


def test_une_surcharge_declaree_par_la_politique_est_honoree(tmp_path, monkeypatch):
    """Le refus doit discriminer : une surcharge légitime doit passer."""
    store = tmp_path / "ailleurs" / "20260911T155246Z"
    monkeypatch.setenv("NEXUS_NON_PDF_STORE", str(tmp_path / "ailleurs"))
    _poser_non_pdf(tmp_path, store=store)
    assert blocages.verifier_non_pdf(tmp_path)["closed"] is True


def test_une_politique_sans_racine_canonique_ne_ferme_pas(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_NON_PDF_STORE", raising=False)
    store = tmp_path / "s" / "t"
    _poser_non_pdf(tmp_path, store=store, canonical_root="")
    resultat = blocages.verifier_non_pdf(tmp_path)
    assert resultat["closed"] is False
    assert "racine de store canonique" in resultat["why"]


# --- La taille doit être LUE, pas seulement prétendue ---------------------


def test_une_taille_absente_du_manifeste_ne_ferme_pas(tmp_path, monkeypatch):
    """Ne pas savoir n'est pas vérifier."""
    monkeypatch.setenv("NEXUS_NON_PDF_STORE", str(tmp_path / "s"))
    _poser_non_pdf(tmp_path, store=tmp_path / "s" / "t", taille=None)
    resultat = blocages.verifier_non_pdf(tmp_path)
    assert resultat["closed"] is False
    assert "sans taille attendue" in resultat["why"]


def test_une_taille_discordante_ne_ferme_pas(tmp_path, monkeypatch):
    """Le contrôle lisait `bytes` quand le champ s'appelle `size` : il était
    inerte, et la preuve affirmait pourtant que les tailles étaient comparées."""
    monkeypatch.setenv("NEXUS_NON_PDF_STORE", str(tmp_path / "s"))
    _poser_non_pdf(tmp_path, store=tmp_path / "s" / "t", taille=999999)
    resultat = blocages.verifier_non_pdf(tmp_path)
    assert resultat["closed"] is False
    assert "tailles discordantes" in resultat["why"]


def test_la_preuve_nomme_la_racine_et_le_nombre_de_tailles_comparees(rapport):
    bloc = next(b for b in rapport["blockers"] if b["id"] == "NON_PDF_REACQUISITION")
    assert bloc["proof"]["canonical_root"]
    assert bloc["proof"]["sizes_compared"] == 37


# --- Épreuves C4 : Contrat de retrieval sur corpus servable ----------------


def test_le_blocage_c4_est_ferme_par_mesure(rapport):
    """C4 doit être fermé sur le SERVABLE_CANDIDATE_SET complet, avec preuve."""
    bloc = next(b for b in rapport["blockers"] if b["id"] == "C4")
    assert bloc["closed"] is True
    assert bloc["proof"]["servable_candidate_scope_size"] == 2264
    assert bloc["proof"]["vectorized_contents_verified"] >= 2264
    assert bloc["proof"]["staging_vectors_count"] == 55251
    assert bloc["proof"]["searchability_conditions_met"] == 8
    assert bloc["proof"]["retrieval_latency_budget_respected"] is True
    assert "SERVABLE_CANDIDATE_SET" in bloc["proof"]["verification"]
    assert "does_not_close" in bloc["proof"]
    assert any("C1" in d for d in bloc["proof"]["does_not_close"])
    assert any("ROLLBACK" in d for d in bloc["proof"]["does_not_close"])


def _poser_c4(tmp_path, *, blocker=False, conditions_not_met=None, target_searchable=True,
              candidats=None, vectorises=2264, staging_vectors=55251):
    (tmp_path / "docs/reports/go_live").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs/reports/handoff").mkdir(parents=True, exist_ok=True)
    if candidats is None:
        candidats = ["sha_" + str(i).zfill(60) for i in range(10)]
    if conditions_not_met is None:
        conditions_not_met = []

    ecart = {
        "rag_searchability_blocker": blocker,
        "conditions_not_met": conditions_not_met,
        "retrieval_contract_validated": True,
        "target_scope_searchable": target_searchable,
        "indexable_scope": {
            "count": len(candidats),
            "indexable": sorted(candidats),
        },
    }
    magasin = {
        "staging_vectors_present": staging_vectors,
        "dedicated": {
            "vectorized_contents": vectorises,
        },
    }
    retrieval = {
        "conditions": {
            "latency_validated": True,
            "retrieval_top_k_validated": True,
        }
    }
    (tmp_path / blocages.ECART_RECHERCHE).write_text(json.dumps(ecart), encoding="utf-8")
    (tmp_path / blocages.MAGASIN_VECTEURS).write_text(json.dumps(magasin), encoding="utf-8")
    (tmp_path / blocages.VALIDATION_RETRIEVAL).write_text(json.dumps(retrieval), encoding="utf-8")


def test_verifier_c4_ferme_sur_preuve(tmp_path):
    _poser_c4(tmp_path)
    res = blocages.verifier_c4(tmp_path)
    assert res["closed"] is True
    assert res["proof"] is not None


def test_verifier_c4_refuse_si_rag_searchability_blocker(tmp_path):
    _poser_c4(tmp_path, blocker=True)
    res = blocages.verifier_c4(tmp_path)
    assert res["closed"] is False
    assert "bloque" in res["why"]


def test_verifier_c4_refuse_si_conditions_searchability_non_met(tmp_path):
    _poser_c4(tmp_path, conditions_not_met=["latency_validated"])
    res = blocages.verifier_c4(tmp_path)
    assert res["closed"] is False
    assert "conditions de recherche non tenues" in res["why"]


def test_verifier_c4_refuse_si_target_scope_searchable_faux(tmp_path):
    _poser_c4(tmp_path, target_searchable=False)
    res = blocages.verifier_c4(tmp_path)
    assert res["closed"] is False
    assert "target_scope_searchable=false" in res["why"]


def test_verifier_c4_refuse_si_perimetre_non_aligne_avec_servable_candidate_set(tmp_path):
    _poser_c4(tmp_path, candidats=["sha_a" * 16])
    # Mutate indexable_scope to have discordant count
    ecart = json.loads((tmp_path / blocages.ECART_RECHERCHE).read_text(encoding="utf-8"))
    ecart["indexable_scope"]["count"] = 999
    (tmp_path / blocages.ECART_RECHERCHE).write_text(json.dumps(ecart), encoding="utf-8")

    res = blocages.verifier_c4(tmp_path)
    assert res["closed"] is False
    assert "périmètre indexable invalide" in res["why"]


def test_verifier_c4_refuse_si_vecteurs_manquants(tmp_path):
    _poser_c4(tmp_path, staging_vectors=0)
    res = blocages.verifier_c4(tmp_path)
    assert res["closed"] is False
    assert "aucun vecteur" in res["why"]


def _poser_rollback(tmp_path: Path, *, status="VERIFIED", rollback_pass=True, containers=0, tamper_sha=False):
    evidence_dir = tmp_path / "docs/reports/evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir = tmp_path / "services/rag-engine/scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    harness = scripts_dir / "atomic_docker_v2_rehearsal.py"
    fixture = scripts_dir / "atomic_docker_v2_rehearsal_fixture.py"
    json_file = evidence_dir / "atomic_docker_v2_rehearsal_20260825.json"
    transcript = evidence_dir / "atomic_docker_v2_rehearsal_20260825.transcript.txt"
    sha_file = evidence_dir / "atomic_docker_v2_rehearsal_20260825.sha256"

    harness.write_text("harness content\n", encoding="utf-8")
    fixture.write_text("fixture content\n", encoding="utf-8")
    transcript.write_text("transcript content\n", encoding="utf-8")

    data = {
        "verification_status": status,
        "verdicts": {
            "ATOMIC_DOCKER_V2_REHEARSAL_PASS": True,
            "ROLLBACK_REHEARSAL_PASS": rollback_pass,
            "BAD_DIGEST_REFUSED": True,
            "BAD_READINESS_REFUSED": True,
            "BAD_AUTHORIZATION_SET_REFUSED": True,
            "ISOLATION_PREFLIGHT_PASS": True,
            "FOREIGN_COLLISION_REFUSED": True,
            "PRODUCTION_PROJECT_NAME_USED": False,
            "REMOVE_ORPHANS_USED": False,
            "PROJECT_CONTAINERS_REMAINING": containers,
            "FOREIGN_SERVICES_TOUCHED": 0,
            "PRODUCTION_PORTS_PUBLISHED": 0,
        },
    }
    json_file.write_text(json.dumps(data), encoding="utf-8")

    if tamper_sha:
        sha_file.write_text(f"{'0' * 64}  services/rag-engine/scripts/atomic_docker_v2_rehearsal.py\n", encoding="utf-8")
    else:
        lignes = [
            f"{hashlib.sha256(harness.read_bytes()).hexdigest()}  services/rag-engine/scripts/atomic_docker_v2_rehearsal.py",
            f"{hashlib.sha256(fixture.read_bytes()).hexdigest()}  services/rag-engine/scripts/atomic_docker_v2_rehearsal_fixture.py",
            f"{hashlib.sha256(json_file.read_bytes()).hexdigest()}  docs/reports/evidence/atomic_docker_v2_rehearsal_20260825.json",
            f"{hashlib.sha256(transcript.read_bytes()).hexdigest()}  docs/reports/evidence/atomic_docker_v2_rehearsal_20260825.transcript.txt",
        ]
        sha_file.write_text("\n".join(lignes) + "\n", encoding="utf-8")


def test_verifier_rollback_nominal(tmp_path):
    _poser_rollback(tmp_path)
    res = blocages.verifier_rollback(tmp_path)
    assert res["closed"] is True
    assert res["proof"]["rollback_pass"] is True
    assert res["proof"]["containers_remaining"] == 0


def test_verifier_rollback_refuse_si_fichier_json_absent(tmp_path):
    res = blocages.verifier_rollback(tmp_path)
    assert res["closed"] is False
    assert "manquante" in res["why"]


def test_verifier_rollback_refuse_si_sha_modifie(tmp_path):
    _poser_rollback(tmp_path, tamper_sha=True)
    res = blocages.verifier_rollback(tmp_path)
    assert res["closed"] is False
    assert "altérée" in res["why"]


def test_verifier_rollback_refuse_si_verdict_rollback_false(tmp_path):
    _poser_rollback(tmp_path, rollback_pass=False)
    res = blocages.verifier_rollback(tmp_path)
    assert res["closed"] is False
    assert "ROLLBACK_REHEARSAL_PASS=False" in res["why"]


def test_verifier_rollback_refuse_si_conteneurs_restants(tmp_path):
    _poser_rollback(tmp_path, containers=2)
    res = blocages.verifier_rollback(tmp_path)
    assert res["closed"] is False
    assert "PROJECT_CONTAINERS_REMAINING=2" in res["why"]


def test_verifier_rollback_sur_depot_reel():
    racine = Path(__file__).resolve().parents[2]
    res = blocages.verifier_rollback(racine)
    assert res["closed"] is True
    assert res["proof"]["rollback_pass"] is True
    assert res["proof"]["containers_remaining"] == 0


def _poser_c5(tmp_path: Path, *, status="VERIFIED", failed_proofs=0, bad_verdict=False, tamper_sha=False):
    evidence_dir = tmp_path / "docs/reports/evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    json_file = evidence_dir / "access_authority_c5_refusal_proof.json"
    sha_file = evidence_dir / "access_authority_c5_refusal_proof.sha256"

    verdicts = {
        "UNKNOWN_SCOPE_ID_REFUSED": True,
        "FORGED_SCOPE_ID_REFUSED": True,
        "SCOPE_DIGEST_CORRUPTION_REFUSED": True,
        "TARGET_LEVEL_DRIFT_REFUSED": True,
        "CURRICULUM_LEVEL_DRIFT_REFUSED": True,
        "CROSS_SUBJECT_DRIFT_REFUSED": True,
        "OMITTED_CURRICULUM_SCOPE_REFUSED": True,
        "AUTHORIZATION_MAPPING_INCOMPLETE_REFUSED": True,
        "AUTHORIZATION_SET_V2_FALSIFIED_OR_DIVERGENT_REFUSED": True,
        "CONTENT_OUTSIDE_AUTHORIZATION_REFUSED": True,
        "OVERLAP_OR_DUPLICATION_REFUSED": True,
        "DENORMALIZED_COLUMNS_CANNOT_WIDEN_AUTHORITY": True,
        "INACTIVE_PLACEMENT_REFUSED": True,
        "STALE_OR_UNREVIEWED_PLACEMENT_REFUSED": True,
        "_EFFECTIVE_SCOPE_FILTER_SQL_ENFORCES_GOVERNED_PLACEMENT": True,
    }
    if bad_verdict:
        verdicts["UNKNOWN_SCOPE_ID_REFUSED"] = False

    data = {
        "kind": "NEXUS-C5-ACCESS-AUTHORITY-REFUSAL-PROOF-V1",
        "verification_status": status,
        "summary": {
            "total_adversarial_proofs": 15,
            "passed_proofs": 15 - failed_proofs,
            "failed_proofs": failed_proofs,
        },
        "verdicts": verdicts,
    }
    octets = (json.dumps(data, indent=2) + "\n").encode("utf-8")
    json_file.write_bytes(octets)

    if tamper_sha:
        sha_file.write_text(f"{'0' * 64}  docs/reports/evidence/access_authority_c5_refusal_proof.json\n", encoding="utf-8")
    else:
        sha_file.write_text(f"{hashlib.sha256(octets).hexdigest()}  docs/reports/evidence/access_authority_c5_refusal_proof.json\n", encoding="utf-8")


def test_verifier_c5_nominal(tmp_path):
    _poser_c5(tmp_path)
    res = blocages.verifier_c5(tmp_path)
    assert res["closed"] is True
    assert res["proof"]["sha256_verified"] is True
    assert res["proof"]["refusals_verified_count"] == 15


def test_verifier_c5_refuse_si_fichier_json_absent(tmp_path):
    res = blocages.verifier_c5(tmp_path)
    assert res["closed"] is False
    assert "manquante" in res["why"]


def test_verifier_c5_refuse_si_sha_modifie(tmp_path):
    _poser_c5(tmp_path, tamper_sha=True)
    res = blocages.verifier_c5(tmp_path)
    assert res["closed"] is False
    assert "altérée" in res["why"]


def test_verifier_c5_refuse_si_verdict_false(tmp_path):
    _poser_c5(tmp_path, bad_verdict=True)
    res = blocages.verifier_c5(tmp_path)
    assert res["closed"] is False
    assert "UNKNOWN_SCOPE_ID_REFUSED=False" in res["why"]


def test_verifier_c5_sur_depot_reel():
    racine = Path(__file__).resolve().parents[2]
    res = blocages.verifier_c5(racine)
    assert res["closed"] is True
    assert res["proof"]["sha256_verified"] is True
    assert res["proof"]["refusals_verified_count"] >= 15


def _poser_c6(
    tmp_path: Path,
    *,
    status="VERIFIED",
    failed_items=0,
    bad_verdict=False,
    tamper_sha=False,
    bad_scope_name=False,
    bad_count=False,
    bad_digest=False,
    bad_schema=False,
):
    evidence_dir = tmp_path / "docs/reports/evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    json_file = evidence_dir / "corpus_cas_c6_proof.json"
    sha_file = evidence_dir / "corpus_cas_c6_proof.sha256"

    verdicts = {
        "CAS_ROOT_EXPLICITLY_NAMED": True,
        "CAS_MANIFEST_EXISTS": True,
        "CAS_MANIFEST_SCHEMA_CONFORMANT": True,
        "ALL_OBJECTS_READ_FROM_DISK": True,
        "SHA256_RECALCULATED_ON_BYTES": True,
        "DECLARED_SIZES_VERIFIED": True,
        "NO_EXPECTED_OBJECTS_MISSING": True,
        "NO_EXTRA_OBJECTS_SILENTLY_ACCEPTED": True,
        "NO_LOCATOR_ESCAPES_CAS_ROOT": True,
        "NO_SYMLINK_TRAVERSAL": True,
        "CONTENT_SET_DIGEST_MATCHES_EXPECTED_AUTHORITY": True,
        "EXPECTED_COUNT_MATCHES_EXACTLY": True,
        "COVERAGE_ON_GOVERNED_SCOPE": True,
        "NO_MATRIX_REFUSED_CONTENT_ADMITTED": True,
        "NO_PII_UNDECIDED_CONTENT_PROMOTED": True,
        "NO_CURRENTNESS_REFUSED_CONTENT_REINTRODUCED": True,
        "RESULT_SEALED_BY_SHA256": True,
    }
    if bad_verdict:
        verdicts["NO_EXPECTED_OBJECTS_MISSING"] = False

    data = {
        "kind": "NEXUS-C6-CORPUS-CAS-QUALIFICATION-PROOF-V1",
        "observed_at_main_sha": "84a235aeb2c7d188ccdf56226a0d0ab73fc8ee0a",
        "verification_status": status,
        "cas_root": "store/corpus_cas_governed",
        "manifest_path": "store/corpus_cas_governed/manifest.json",
        "manifest_schema": "INVALID_SCHEMA" if bad_schema else "NEXUS-CORPUS-CAS-MANIFEST-V1",
        "target_scope": {
            "name": "OTHER_SCOPE" if bad_scope_name else "SERVABLE_CANDIDATE_SET",
            "count": 100 if bad_count else 2264,
            "content_set_digest": (
                "0" * 64
                if bad_digest
                else "227617d4c4364dda1267b15bb30005a26a329414bc151f3c3e5f4c5362a1fbdd"
            ),
            "authority_source": "docs/reports/go_live/rag_searchability_gap.json",
        },
        "summary": {
            "total_checks": 17,
            "passed_checks": 17 - failed_items,
            "failed_items": failed_items,
            "verified_objects": 2264,
        },
        "verdicts": verdicts,
    }
    octets = (json.dumps(data, indent=2) + "\n").encode("utf-8")
    json_file.write_bytes(octets)

    if tamper_sha:
        sha_file.write_text(
            f"{'0' * 64}  docs/reports/evidence/corpus_cas_c6_proof.json\n",
            encoding="utf-8",
        )
    else:
        sha_file.write_text(
            f"{hashlib.sha256(octets).hexdigest()}  docs/reports/evidence/corpus_cas_c6_proof.json\n",
            encoding="utf-8",
        )


def test_verifier_c6_nominal(tmp_path):
    _poser_c6(tmp_path)
    res = blocages.verifier_c6(tmp_path)
    assert res["closed"] is True
    assert res["proof"]["sha256_verified"] is True
    assert res["proof"]["verified_objects_count"] == 2264


def test_verifier_c6_refuse_si_fichier_json_absent(tmp_path):
    res = blocages.verifier_c6(tmp_path)
    assert res["closed"] is False
    assert "manquante" in res["why"]


def test_verifier_c6_refuse_si_sha_modifie(tmp_path):
    _poser_c6(tmp_path, tamper_sha=True)
    res = blocages.verifier_c6(tmp_path)
    assert res["closed"] is False
    assert "altérée" in res["why"]


def test_verifier_c6_refuse_si_verdict_false(tmp_path):
    _poser_c6(tmp_path, bad_verdict=True)
    res = blocages.verifier_c6(tmp_path)
    assert res["closed"] is False
    assert "NO_EXPECTED_OBJECTS_MISSING=False" in res["why"]


def test_verifier_c6_refuse_si_failed_items(tmp_path):
    _poser_c6(tmp_path, failed_items=1)
    res = blocages.verifier_c6(tmp_path)
    assert res["closed"] is False
    assert "échecs" in res["why"]


def test_verifier_c6_refuse_si_perimetre_invalide(tmp_path):
    _poser_c6(tmp_path, bad_scope_name=True)
    res = blocages.verifier_c6(tmp_path)
    assert res["closed"] is False
    assert "périmètre cible" in res["why"]


def test_verifier_c6_refuse_si_count_invalide(tmp_path):
    _poser_c6(tmp_path, bad_count=True)
    res = blocages.verifier_c6(tmp_path)
    assert res["closed"] is False
    assert "nombre de contenus cible" in res["why"]


def test_verifier_c6_refuse_si_digest_invalide(tmp_path):
    _poser_c6(tmp_path, bad_digest=True)
    res = blocages.verifier_c6(tmp_path)
    assert res["closed"] is False
    assert "digest de l'ensemble cible" in res["why"]


def test_verifier_c6_refuse_si_schema_invalide(tmp_path):
    _poser_c6(tmp_path, bad_schema=True)
    res = blocages.verifier_c6(tmp_path)
    assert res["closed"] is False
    assert "schéma de manifeste" in res["why"]


def test_verifier_c6_sur_depot_reel():
    racine = Path(__file__).resolve().parents[2]
    res = blocages.verifier_c6(racine)
    assert res["closed"] is True
    assert res["proof"]["sha256_verified"] is True
    assert res["proof"]["verified_objects_count"] == 2264


def _poser_c2(
    tmp_path: Path,
    *,
    status="VERIFIED",
    main_sha="4e7c40b731823a517f1a29f3838c3794638bde68",
    docker_residues=0,
    prod_touched=False,
    prod_db_writes=0,
    current_switch=0,
    tamper_sha=False,
    bad_auth=False,
    bad_cardinality=False,
    bad_verdict=False,
):
    evidence_dir = tmp_path / "docs/reports/evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    json_file = evidence_dir / "h2c_c2_multilevel_ingestion_e2e_proof.json"
    sha_file = evidence_dir / "h2c_c2_multilevel_ingestion_e2e_proof.sha256"

    exp_auth = "6ec1a4f8e0d644540214660c3568b2c169770b7789cd850186b6c3f1d6bd1c26"
    act_auth = "0" * 64 if bad_auth else exp_auth

    data = {
        "kind": "NEXUS-C2-MULTILEVEL-INGESTION-E2E-PROOF-V1",
        "observed_at_main_sha": main_sha,
        "timestamp": "2026-09-17T07:40:00.000000+00:00",
        "executed_command": "pytest -v services/rag-engine/tests/integration/test_multilevel_real_ingestion.py",
        "ephemeral_environment": {
            "database": "PostgreSQL 16 éphémère",
            "docker_residues_after_test": docker_residues,
            "production_touched": prod_touched,
            "production_db_writes": prod_db_writes,
            "current_switch": current_switch,
            "secrets_contained": 0,
        },
        "authorities": {
            "release_manifest": {
                "path": "services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/multilevel.release.json",
                "expected_sha256": exp_auth,
                "actual_sha256": act_auth,
            },
        },
        "cardinalities": {
            "target_collections": 999 if bad_cardinality else 10,
            "expected_artifacts": 11,
            "ingested_artifacts": 11,
            "expected_placements": 11,
            "published_placements": 11,
            "expected_chunks": 353,
            "stored_chunks": 353,
            "search_queries_passed": 30,
            "citations_verified": 30,
            "cross_scope_isolation_verified": True,
        },
        "verdicts": {
            "MAIN_SHA_MATCHES": True,
            "ALL_AUTHORITY_DIGESTS_MATCH": not bad_auth,
            "TARGET_COLLECTIONS_COVERED": True,
            "ARTIFACT_CARDINALITY_MATCHES": True,
            "PLACEMENT_CARDINALITY_MATCHES": True,
            "CHUNK_CARDINALITY_MATCHES": True,
            "API_V2_ROUTES_AUTHENTICATED": True,
            "SEARCH_ACCEPTANCE_PASSED": True,
            "CITATIONS_VERIFIED": not bad_verdict,
            "CROSS_SCOPE_ISOLATION_VERIFIED": True,
            "NO_DOCKER_RESIDUES": docker_residues == 0,
            "NO_PRODUCTION_MUTATIONS": True,
            "NO_CURRENT_SWITCH": True,
            "NO_SECRETS_EXPOSED": True,
            "TEST_EXECUTION_PASSED": not bad_verdict,
        },
        "verification_status": status,
    }

    content = json.dumps(data, indent=2, sort_keys=True) + "\n"
    json_file.write_text(content, encoding="utf-8")

    if tamper_sha:
        sha_file.write_text(f"{'f' * 64}  docs/reports/evidence/h2c_c2_multilevel_ingestion_e2e_proof.json\n", encoding="utf-8")
    else:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        sha_file.write_text(f"{digest}  docs/reports/evidence/h2c_c2_multilevel_ingestion_e2e_proof.json\n", encoding="utf-8")


def test_verifier_c2_nominal(tmp_path):
    _poser_c2(tmp_path)
    res = blocages.verifier_c2(tmp_path)
    assert res["closed"] is True
    assert res["proof"] is not None
    assert res["proof"]["sha256_verified"] is True
    assert res["proof"]["target_collections"] == 10


def test_verifier_c2_refuse_si_fichier_json_absent(tmp_path):
    res = blocages.verifier_c2(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "manquante" in res["why"]


def test_verifier_c2_refuse_si_sha_modifie(tmp_path):
    _poser_c2(tmp_path, tamper_sha=True)
    res = blocages.verifier_c2(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "altération" in res["why"]


def test_verifier_c2_refuse_si_status_non_verified(tmp_path):
    _poser_c2(tmp_path, status="FAILED")
    res = blocages.verifier_c2(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "non VERIFIED" in res["why"]


def test_verifier_c2_refuse_si_main_sha_stale(tmp_path):
    _poser_c2(tmp_path, main_sha="0" * 40)
    res = blocages.verifier_c2(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "stale" in res["why"]


def test_verifier_c2_refuse_si_docker_residues(tmp_path):
    _poser_c2(tmp_path, docker_residues=1)
    res = blocages.verifier_c2(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "Docker résiduels" in res["why"]


def test_verifier_c2_refuse_si_production_mutations(tmp_path):
    _poser_c2(tmp_path, prod_db_writes=1)
    res = blocages.verifier_c2(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "production_db_writes" in res["why"]

    _poser_c2(tmp_path, current_switch=1)
    res2 = blocages.verifier_c2(tmp_path)
    assert res2["closed"] is False
    assert res2["proof"] is None
    assert "current_switch" in res2["why"]


def test_verifier_c2_refuse_si_autorite_divergente(tmp_path):
    _poser_c2(tmp_path, bad_auth=True)
    res = blocages.verifier_c2(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "divergente" in res["why"]


def test_verifier_c2_refuse_si_cardinalite_invalide(tmp_path):
    _poser_c2(tmp_path, bad_cardinality=True)
    res = blocages.verifier_c2(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "nombre de collections" in res["why"]


def test_verifier_c2_sur_depot_reel():
    racine = Path(__file__).resolve().parents[2]
    res = blocages.verifier_c2(racine)
    assert res["closed"] is True
    assert res["proof"] is not None
    assert res["proof"]["sha256_verified"] is True
    assert res["proof"]["target_collections"] == 10
    assert res["proof"]["stored_chunks"] == 353


def _poser_c3(
    tmp_path: Path,
    *,
    status="VERIFIED",
    main_sha="4e7c40b731823a517f1a29f3838c3794638bde68",
    docker_residues=0,
    prod_touched=False,
    prod_db_writes=0,
    current_switch=0,
    tamper_sha=False,
    bad_auth=False,
    bad_cardinality=False,
    bad_verdict=False,
):
    evidence_dir = tmp_path / "docs/reports/evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    json_file = evidence_dir / "h2c_c3_worker_cli_e2e_proof.json"
    sha_file = evidence_dir / "h2c_c3_worker_cli_e2e_proof.sha256"

    exp_auth = "6ec1a4f8e0d644540214660c3568b2c169770b7789cd850186b6c3f1d6bd1c26"
    act_auth = "0" * 64 if bad_auth else exp_auth

    data = {
        "kind": "NEXUS-C3-WORKER-CLI-E2E-PROOF-V1",
        "observed_at_main_sha": main_sha,
        "timestamp": "2026-09-17T07:40:00.000000+00:00",
        "executed_command": "pytest -v services/rag-engine/tests/integration/test_multilevel_worker_cli_e2e.py",
        "ephemeral_environment": {
            "database": "Deux instances PostgreSQL éphémères",
            "docker_residues_after_test": docker_residues,
            "production_touched": prod_touched,
            "production_db_writes": prod_db_writes,
            "current_switch": current_switch,
            "secrets_contained": 0,
        },
        "authorities": {
            "release_manifest": {
                "path": "services/rag-pedago/data/releases/prerentree_2026_2027/multilevel/multilevel.release.json",
                "expected_sha256": exp_auth,
                "actual_sha256": act_auth,
            },
        },
        "cardinalities": {
            "target_collections": 999 if bad_cardinality else 2,
            "worker_a_executed": not bad_cardinality,
            "worker_b_executed": not bad_cardinality,
            "proposals_generated": 0 if bad_cardinality else 2,
            "publications_attested": 0 if bad_cardinality else 2,
            "collections": [
                "rag_nexus_maths_quatrieme_tc",
                "rag_nexus_nsi_premiere_specialite",
            ],
        },
        "verdicts": {
            "MAIN_SHA_MATCHES": True,
            "ALL_AUTHORITY_DIGESTS_MATCH": not bad_auth,
            "WORKER_A_CLI_EXECUTED": True,
            "WORKER_B_CLI_EXECUTED": True,
            "PROPOSALS_GENERATED": True,
            "PUBLICATIONS_ATTESTED": True,
            "NO_DOCKER_RESIDUES": docker_residues == 0,
            "NO_PRODUCTION_MUTATIONS": True,
            "NO_CURRENT_SWITCH": True,
            "NO_SECRETS_EXPOSED": True,
            "TEST_EXECUTION_PASSED": not bad_verdict,
        },
        "verification_status": status,
    }

    content = json.dumps(data, indent=2, sort_keys=True) + "\n"
    json_file.write_text(content, encoding="utf-8")

    if tamper_sha:
        sha_file.write_text(f"{'f' * 64}  docs/reports/evidence/h2c_c3_worker_cli_e2e_proof.json\n", encoding="utf-8")
    else:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        sha_file.write_text(f"{digest}  docs/reports/evidence/h2c_c3_worker_cli_e2e_proof.json\n", encoding="utf-8")


def test_verifier_c3_nominal(tmp_path):
    _poser_c3(tmp_path)
    res = blocages.verifier_c3(tmp_path)
    assert res["closed"] is True
    assert res["proof"] is not None
    assert res["proof"]["sha256_verified"] is True
    assert res["proof"]["target_collections"] == 2


def test_verifier_c3_refuse_si_fichier_json_absent(tmp_path):
    res = blocages.verifier_c3(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "manquante" in res["why"]


def test_verifier_c3_refuse_si_sha_modifie(tmp_path):
    _poser_c3(tmp_path, tamper_sha=True)
    res = blocages.verifier_c3(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "altération" in res["why"]


def test_verifier_c3_refuse_si_status_non_verified(tmp_path):
    _poser_c3(tmp_path, status="FAILED")
    res = blocages.verifier_c3(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "non VERIFIED" in res["why"]


def test_verifier_c3_refuse_si_main_sha_stale(tmp_path):
    _poser_c3(tmp_path, main_sha="0" * 40)
    res = blocages.verifier_c3(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "stale" in res["why"]


def test_verifier_c3_refuse_si_docker_residues(tmp_path):
    _poser_c3(tmp_path, docker_residues=1)
    res = blocages.verifier_c3(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "Docker résiduels" in res["why"]


def test_verifier_c3_refuse_si_production_mutations(tmp_path):
    _poser_c3(tmp_path, prod_db_writes=1)
    res = blocages.verifier_c3(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "production_db_writes" in res["why"]

    _poser_c3(tmp_path, current_switch=1)
    res2 = blocages.verifier_c3(tmp_path)
    assert res2["closed"] is False
    assert res2["proof"] is None
    assert "current_switch" in res2["why"]


def test_verifier_c3_refuse_si_autorite_divergente(tmp_path):
    _poser_c3(tmp_path, bad_auth=True)
    res = blocages.verifier_c3(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "divergente" in res["why"]


def test_verifier_c3_refuse_si_cardinalite_invalide(tmp_path):
    _poser_c3(tmp_path, bad_cardinality=True)
    res = blocages.verifier_c3(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "nombre de collections" in res["why"]


def test_verifier_c3_sur_depot_reel():
    racine = Path(__file__).resolve().parents[2]
    res = blocages.verifier_c3(racine)
    assert res["closed"] is True
    assert res["proof"] is not None
    assert res["proof"]["sha256_verified"] is True
    assert res["proof"]["target_collections"] == 2


def _poser_cockpit_e2e(
    tmp_path: Path,
    *,
    status="VERIFIED",
    main_sha="7769b72259d8e51749de07ab9a2dbc0a6e86ef28",
    docker_residues=0,
    prod_touched=False,
    prod_db_writes=0,
    current_switch=0,
    tamper_sha=False,
    mock_detected=False,
    unauth_rejected=True,
    cross_scope_rejected=True,
    citations_count=8,
    citations_complete=True,
    bad_verdict=False,
):
    evidence_dir = tmp_path / "docs/reports/evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    json_file = evidence_dir / "cockpit_e2e_retrieval_proof.json"
    sha_file = evidence_dir / "cockpit_e2e_retrieval_proof.sha256"

    data = {
        "kind": "NEXUS-COCKPIT-E2E-RETRIEVAL-PROOF-V1",
        "observed_at_main_sha": main_sha,
        "verification_status": status,
        "executed_command": "pytest -q services/rag-engine/tests/integration/test_cockpit_e2e_retrieval.py",
        "ephemeral_environment": {
            "cockpit_port": 34567,
            "engine_port": 34568,
            "redis_port": 34569,
            "docker_residues_after_test": docker_residues,
            "production_touched": prod_touched,
            "production_db_writes": prod_db_writes,
            "production_deployments": 0,
            "current_switch": current_switch,
        },
        "cockpit_configuration": {
            "cockpit_api_url": "http://127.0.0.1:34567/api/search",
            "engine_internal_url": "http://127.0.0.1:34568",
            "auth_mode": "nextauth_session_with_nexus_identity",
            "session_store": "redis_ephemeral_memory",
            "mock_fallback_detected": mock_detected,
        },
        "tested_queries": [],
        "security_verifications": {
            "unauthenticated_request_rejected": unauth_rejected,
            "unauthorized_scope_collection_rejected": cross_scope_rejected,
            "invalid_payload_request_rejected": True,
        },
        "citations_summary": {
            "total_citations_verified": citations_count,
            "citations_present_on_all_results": citations_complete,
            "pages_verified": True,
            "source_uris_verified": True,
        },
        "verdicts": {
            "COCKPIT_STARTED": True,
            "ENGINE_STARTED": True,
            "AUTHENTICATION_HONORED": True,
            "CROSS_SCOPE_REJECTED": True,
            "RETRIEVAL_REAL_AND_SOURCED": True,
            "CITATIONS_PRESENT_AND_VALID": True,
            "ZERO_MOCK_VERIFIED": True,
            "TEST_EXECUTION_PASSED": not bad_verdict,
        },
    }

    content = json.dumps(data, indent=2, sort_keys=True) + "\n"
    json_file.write_text(content, encoding="utf-8")

    if tamper_sha:
        sha_file.write_text(
            f"{'f' * 64}  docs/reports/evidence/cockpit_e2e_retrieval_proof.json\n",
            encoding="utf-8",
        )
    else:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        sha_file.write_text(
            f"{digest}  docs/reports/evidence/cockpit_e2e_retrieval_proof.json\n",
            encoding="utf-8",
        )


def test_verifier_cockpit_e2e_nominal(tmp_path):
    _poser_cockpit_e2e(tmp_path)
    res = blocages.verifier_cockpit_e2e(tmp_path)
    assert res["closed"] is True
    assert res["proof"] is not None
    assert res["proof"]["sha256_verified"] is True
    assert res["proof"]["citations_count"] == 8


def test_verifier_cockpit_e2e_refuse_si_fichier_json_absent(tmp_path):
    res = blocages.verifier_cockpit_e2e(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "manquante" in res["why"]


def test_verifier_cockpit_e2e_refuse_si_sha_modifie(tmp_path):
    _poser_cockpit_e2e(tmp_path, tamper_sha=True)
    res = blocages.verifier_cockpit_e2e(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "altération" in res["why"]


def test_verifier_cockpit_e2e_refuse_si_status_non_verified(tmp_path):
    _poser_cockpit_e2e(tmp_path, status="FAILED")
    res = blocages.verifier_cockpit_e2e(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "non VERIFIED" in res["why"]


def test_verifier_cockpit_e2e_refuse_si_main_sha_stale(tmp_path):
    _poser_cockpit_e2e(tmp_path, main_sha="0" * 40)
    res = blocages.verifier_cockpit_e2e(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "stale" in res["why"]


def test_verifier_cockpit_e2e_refuse_si_mock_detecte(tmp_path):
    _poser_cockpit_e2e(tmp_path, mock_detected=True)
    res = blocages.verifier_cockpit_e2e(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "mock ou fallback" in res["why"]


def test_verifier_cockpit_e2e_refuse_si_docker_residues(tmp_path):
    _poser_cockpit_e2e(tmp_path, docker_residues=1)
    res = blocages.verifier_cockpit_e2e(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "Docker résiduels" in res["why"]


def test_verifier_cockpit_e2e_refuse_si_production_touchee(tmp_path):
    _poser_cockpit_e2e(tmp_path, prod_touched=True)
    res = blocages.verifier_cockpit_e2e(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "environnement de production touché" in res["why"]

    _poser_cockpit_e2e(tmp_path, prod_db_writes=1)
    res2 = blocages.verifier_cockpit_e2e(tmp_path)
    assert res2["closed"] is False
    assert res2["proof"] is None
    assert "production_db_writes" in res2["why"]

    _poser_cockpit_e2e(tmp_path, current_switch=1)
    res3 = blocages.verifier_cockpit_e2e(tmp_path)
    assert res3["closed"] is False
    assert res3["proof"] is None
    assert "current_switch" in res3["why"]


def test_verifier_cockpit_e2e_refuse_si_securite_non_prouvee(tmp_path):
    _poser_cockpit_e2e(tmp_path, unauth_rejected=False)
    res = blocages.verifier_cockpit_e2e(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "refus 401" in res["why"]

    _poser_cockpit_e2e(tmp_path, cross_scope_rejected=False)
    res2 = blocages.verifier_cockpit_e2e(tmp_path)
    assert res2["closed"] is False
    assert res2["proof"] is None
    assert "refus 403" in res2["why"]


def test_verifier_cockpit_e2e_refuse_si_citations_absentes(tmp_path):
    _poser_cockpit_e2e(tmp_path, citations_count=0)
    res = blocages.verifier_cockpit_e2e(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "aucune citation" in res["why"]

    _poser_cockpit_e2e(tmp_path, citations_complete=False)
    res2 = blocages.verifier_cockpit_e2e(tmp_path)
    assert res2["closed"] is False
    assert res2["proof"] is None
    assert "citations pédagogiques absentes" in res2["why"]


def test_verifier_cockpit_e2e_refuse_si_verdict_echec(tmp_path):
    _poser_cockpit_e2e(tmp_path, bad_verdict=True)
    res = blocages.verifier_cockpit_e2e(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    assert "TEST_EXECUTION_PASSED=false" in res["why"]


def test_verifier_cockpit_e2e_sur_depot_reel():
    racine = Path(__file__).resolve().parents[2]
    res = blocages.verifier_cockpit_e2e(racine)
    assert res["closed"] is True
    assert res["proof"] is not None
    assert res["proof"]["sha256_verified"] is True
    assert res["proof"]["citations_count"] > 0




# --- CONCURRENCE (lot BS) ---------------------------------------------------

_BUDGET_CONCURRENCE = {
    "kind": "NEXUS-CONCURRENCY-LOAD-BUDGET-V1",
    "adopted": True,
    "declared_before_measurement": True,
    "load_profile": {
        "concurrent_clients": 4,
        "measured_requests_total": 20,
        "warmup_requests": 2,
        "client_timeout_ms": 7500,
    },
    "budget": {
        "p50_ms_max": 3000.0,
        "p95_ms_max": 6000.0,
        "p99_ms_max": 7500.0,
        "error_rate_max": 0.0,
        "errors_max": 0,
        "timeouts_max": 0,
        "db_connections_peak_max": 10,
        "db_connections_leaked_max": 0,
        "docker_residues_max": 0,
        "residual_processes_max": 0,
    },
}


def _poser_concurrence(racine: Path, muter=None, *, muter_budget=None, tamper_sha=False) -> None:
    budget = json.loads(json.dumps(_BUDGET_CONCURRENCE))
    if muter_budget:
        muter_budget(budget)
    budget_path = racine / "docs/reports/go_live/concurrency_load_budget.json"
    budget_path.parent.mkdir(parents=True, exist_ok=True)
    budget_octets = (json.dumps(budget, indent=2) + "\n").encode()
    budget_path.write_bytes(budget_octets)

    snapshot = {
        "counts": {"rag_chunks": 353, "rag_artifacts": 11, "rag_artifact_placements": 11},
        "content_sha256": "a" * 64,
        "duplicate_chunk_ids": 0,
    }
    requetes = [
        {"scope_id": "s", "latency_ms": 500.0 + 10 * i, "status": 200, "outcome": "ok", "detail": None}
        for i in range(20)
    ]
    preuve = {
        "kind": "NEXUS-CONCURRENCY-LOAD-PROOF-V1",
        "verification_status": "VERIFIED",
        "observed_at_main_sha": blocages.CONCURRENCE_MAIN_SHA_ATTENDU,
        "executed_command": "python3 scripts/qualification/verify_concurrency_load.py --run",
        "budget": {
            "path": "docs/reports/go_live/concurrency_load_budget.json",
            "sha256": hashlib.sha256(budget_octets).hexdigest(),
        },
        "measurements": {
            "budget_sha256": hashlib.sha256(budget_octets).hexdigest(),
            "load_profile_executed": {"concurrent_clients": 4, "measured_requests_total": 20},
            "engine": {"mock_detected": False, "pg_pool_max_size": 10},
            "corpus": {"indexed_chunks": 353},
            "measured_requests": requetes,
            "db_connections": {"samples_count": 50, "peak_during_load": 8, "after_engine_stop": 0},
            "database_snapshot_before": snapshot,
            "database_snapshot_after": dict(snapshot),
        },
        "summary": blocages.resumer_latences_concurrence(requetes),
        "teardown": {
            "docker_residues_after_test": 0,
            "residual_engine_processes": 0,
            "production_touched": False,
            "production_db_writes": 0,
            "production_deployments": 0,
            "current_switch": 0,
        },
    }
    if muter:
        muter(preuve)
    dossier = racine / "docs/reports/evidence"
    dossier.mkdir(parents=True, exist_ok=True)
    octets = (json.dumps(preuve, indent=2, sort_keys=True) + "\n").encode()
    (dossier / "concurrency_load_proof.json").write_bytes(octets)
    digest = "f" * 64 if tamper_sha else hashlib.sha256(octets).hexdigest()
    (dossier / "concurrency_load_proof.sha256").write_text(
        f"{digest}  docs/reports/evidence/concurrency_load_proof.json\n", encoding="utf-8"
    )


def _refus_concurrence(tmp_path, muter=None, **kw) -> str:
    _poser_concurrence(tmp_path, muter, **kw)
    res = blocages.verifier_concurrence(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    return res["why"]


def test_verifier_concurrence_nominal(tmp_path):
    _poser_concurrence(tmp_path)
    res = blocages.verifier_concurrence(tmp_path)
    assert res["closed"] is True, res["why"]
    assert res["proof"]["sha256_verified"] is True
    assert res["proof"]["p99_ms"] == 690.0
    assert any("STAGING_EXTERNE" in x for x in res["proof"]["does_not_close"])


def test_verifier_concurrence_refuse_preuve_absente(tmp_path):
    res = blocages.verifier_concurrence(tmp_path)
    assert res["closed"] is False and res["proof"] is None
    assert "manquante" in res["why"]


def test_verifier_concurrence_refuse_preuve_alteree(tmp_path):
    assert "altération" in _refus_concurrence(tmp_path, tamper_sha=True)


def test_verifier_concurrence_refuse_statut_non_verified(tmp_path):
    def m(p):
        p["verification_status"] = "BUDGET_FAILED"
    assert "VERIFIED" in _refus_concurrence(tmp_path, m)


def test_verifier_concurrence_refuse_preuve_stale(tmp_path):
    def m(p):
        p["observed_at_main_sha"] = "0" * 40
    assert "stale" in _refus_concurrence(tmp_path, m)


def test_verifier_concurrence_refuse_sans_mesures(tmp_path):
    def m(p):
        p["measurements"]["measured_requests"] = []
    assert "mesure" in _refus_concurrence(tmp_path, m)


def test_verifier_concurrence_refuse_mesures_incompletes(tmp_path):
    def m(p):
        p["measurements"]["measured_requests"] = p["measurements"]["measured_requests"][:5]
    assert "20" in _refus_concurrence(tmp_path, m)


def test_verifier_concurrence_refuse_resume_incoherent_avec_mesures(tmp_path):
    """Un résumé flatteur ne sert à rien : les percentiles sont recalculés."""
    def m(p):
        p["summary"]["p99_ms"] = 1.0
    assert "résumé" in _refus_concurrence(tmp_path, m)


def test_verifier_concurrence_refuse_sans_budget_explicite(tmp_path):
    def mb(b):
        del b["budget"]["p99_ms_max"]
    assert "budget" in _refus_concurrence(tmp_path, muter_budget=mb)


def test_verifier_concurrence_refuse_budget_modifie_apres_mesure(tmp_path):
    _poser_concurrence(tmp_path)
    chemin = tmp_path / "docs/reports/go_live/concurrency_load_budget.json"
    budget = json.loads(chemin.read_text())
    budget["budget"]["p99_ms_max"] = 99999.0
    chemin.write_text(json.dumps(budget))
    res = blocages.verifier_concurrence(tmp_path)
    assert res["closed"] is False and "budget" in res["why"]


def test_verifier_concurrence_refuse_budget_non_declare_avant_mesure(tmp_path):
    def mb(b):
        b["declared_before_measurement"] = False
    assert "avant" in _refus_concurrence(tmp_path, muter_budget=mb)


def test_verifier_concurrence_refuse_latence_hors_budget(tmp_path):
    def m(p):
        for r in p["measurements"]["measured_requests"]:
            r["latency_ms"] = 7000.0
        p["summary"] = blocages.resumer_latences_concurrence(p["measurements"]["measured_requests"])
    assert "p50" in _refus_concurrence(tmp_path, m)


def test_verifier_concurrence_refuse_erreurs_au_dela_du_budget(tmp_path):
    def m(p):
        p["measurements"]["measured_requests"][3].update(outcome="error", status=500)
        p["summary"] = blocages.resumer_latences_concurrence(p["measurements"]["measured_requests"])
    assert "erreur" in _refus_concurrence(tmp_path, m)


def test_verifier_concurrence_refuse_timeout_non_accepte(tmp_path):
    def m(p):
        p["measurements"]["measured_requests"][3].update(outcome="timeout", status=None)
        p["summary"] = blocages.resumer_latences_concurrence(p["measurements"]["measured_requests"])
    assert "timeout" in _refus_concurrence(tmp_path, m)


def test_verifier_concurrence_refuse_mock(tmp_path):
    def m(p):
        p["measurements"]["engine"]["mock_detected"] = True
    assert "mock" in _refus_concurrence(tmp_path, m)


def test_verifier_concurrence_refuse_fuite_de_connexion(tmp_path):
    def m(p):
        p["measurements"]["db_connections"]["after_engine_stop"] = 2
    assert "fuite" in _refus_concurrence(tmp_path, m)

    def m2(p):
        p["measurements"]["db_connections"]["peak_during_load"] = 11
    assert "pic" in _refus_concurrence(tmp_path, m2)

    def m3(p):
        p["measurements"]["db_connections"]["samples_count"] = 0
    assert "échantillon" in _refus_concurrence(tmp_path, m3)


def test_verifier_concurrence_refuse_corruption_db(tmp_path):
    def m(p):
        p["measurements"]["database_snapshot_after"]["content_sha256"] = "b" * 64
    assert "base" in _refus_concurrence(tmp_path, m)

    def m2(p):
        p["measurements"]["database_snapshot_after"]["duplicate_chunk_ids"] = 1
    assert "base" in _refus_concurrence(tmp_path, m2)


def test_verifier_concurrence_refuse_residus(tmp_path):
    def m(p):
        p["teardown"]["docker_residues_after_test"] = 1
    assert "résiduel" in _refus_concurrence(tmp_path, m)

    def m2(p):
        p["teardown"]["residual_engine_processes"] = 1
    assert "résiduel" in _refus_concurrence(tmp_path, m2)


@pytest.mark.parametrize(
    ("cle", "valeur"),
    [
        ("production_db_writes", 1),
        ("production_deployments", 1),
        ("current_switch", 1),
        ("production_touched", True),
    ],
)
def test_verifier_concurrence_refuse_si_production_touchee(tmp_path, cle, valeur):
    def m(p):
        p["teardown"][cle] = valeur
    assert cle in _refus_concurrence(tmp_path, m)


def test_verifier_concurrence_sur_depot_reel():
    """L'état réel est DÉRIVÉ du statut scellé : seule une preuve VERIFIED ferme.
    Une mesure BUDGET_FAILED reste consultable comme diagnostic, jamais comme fermeture."""
    preuve = json.loads((RACINE / blocages.CONCURRENCE_PREUVE).read_text(encoding="utf-8"))
    res = blocages.verifier_concurrence(RACINE)
    if preuve["verification_status"] == "VERIFIED":
        assert res["closed"] is True, res["why"]
        assert res["proof"]["measured_requests"] == 240
    else:
        assert preuve["verification_status"] == "BUDGET_FAILED"
        assert preuve["violations"]
        assert res["closed"] is False
        assert res["proof"] is None
        assert "VERIFIED" in res["why"]


# --- SYNC_INCREMENTALE (lot BT) ---------------------------------------------


def _produit(artefacts: int, chunks: int, empreinte: str) -> dict:
    return {
        "counts": {"rag_artifacts": artefacts, "rag_artifact_placements": artefacts, "rag_chunks": chunks},
        "content_sha256": empreinte * 64,
        "chunk_id_set_sha256": empreinte * 64,
        "chunks_without_vector": 0,
        "duplicates": {"rag_artifacts": 0, "rag_artifact_placements": 0, "rag_chunks": 0},
    }


def _observations_sync() -> dict:
    controle = {"resources_by_state": {"RETRIEVAL_ELIGIBLE": 3}, "duplicate_resources": 0, "stored_artifacts": 3}
    return {
        "kind": "NEXUS-INCREMENTAL-SYNC-RAW-OBSERVATIONS-V1",
        "real_engine": {"mock_detected": False},
        "release_expected": {"artifacts": 3, "placements": 3, "chunks": 30},
        "wave_one": {"content_sha256": ["1" * 64, "2" * 64]},
        "wave_two": {"content_sha256": ["3" * 64]},
        "empty_state": _produit(0, 0, "0"),
        "initial_state": {
            "publications": [{"content_sha256": "1" * 64, "embedded": True}, {"content_sha256": "2" * 64, "embedded": True}],
            "product": _produit(2, 20, "a"),
            "expected_chunk_id_set_sha256": "a" * 64,
            "expected_chunks": 20,
            "full_release_ready": False,
            "control": controle,
        },
        "modification_attempt": {
            "modified_content_sha256": "9" * 64,
            "worker_outcomes": [{"worked": True, "status": "failed", "error": "content"}],
            "modified_content_in_product": 0,
            "publications_triggered": [],
            "product_after": _produit(2, 20, "a"),
        },
        "incremental_run": {
            "sources_submitted": 3,
            "publications": [{"content_sha256": "3" * 64, "embedded": True}],
            "product": _produit(3, 30, "b"),
            "wave_one_rows_after": {**_produit(2, 20, "a")},
            "expected_chunk_id_set_sha256": "b" * 64,
            "full_release_ready": True,
            "control": controle,
        },
        "repeated_run": {
            "replayed_publications": 3,
            "replays": [{"status": "succeeded", "embedded": False}] * 3,
            "product": _produit(3, 30, "b"),
            "control": controle,
        },
        "withdrawal": {
            "supported_by_business_model": False,
            "publisher_privileges": {t: ["INSERT", "SELECT"] for t in ("rag_artifacts", "rag_artifact_placements", "rag_chunks")},
        },
    }


def _poser_sync(racine: Path, muter=None, *, tamper_sha=False) -> None:
    preuve = {
        "kind": "NEXUS-INCREMENTAL-SYNC-PROOF-V1",
        "verification_status": "VERIFIED",
        "observed_at_main_sha": blocages.SYNC_MAIN_SHA_ATTENDU,
        "executed_command": "python3 scripts/qualification/verify_incremental_sync.py --run",
        "observations": _observations_sync(),
        "teardown": {
            "docker_residues_after_test": 0,
            "production_touched": False,
            "production_db_writes": 0,
            "production_deployments": 0,
            "current_switch": 0,
        },
    }
    if muter:
        muter(preuve)
    dossier = racine / "docs/reports/evidence"
    dossier.mkdir(parents=True, exist_ok=True)
    octets = (json.dumps(preuve, indent=2, sort_keys=True) + "\n").encode()
    (dossier / "incremental_sync_proof.json").write_bytes(octets)
    digest = "f" * 64 if tamper_sha else hashlib.sha256(octets).hexdigest()
    (dossier / "incremental_sync_proof.sha256").write_text(
        f"{digest}  docs/reports/evidence/incremental_sync_proof.json\n", encoding="utf-8"
    )


def _refus_sync(tmp_path, muter=None, **kw) -> str:
    _poser_sync(tmp_path, muter, **kw)
    res = blocages.verifier_sync_incrementale(tmp_path)
    assert res["closed"] is False
    assert res["proof"] is None
    return res["why"]


def test_verifier_sync_nominal(tmp_path):
    _poser_sync(tmp_path)
    res = blocages.verifier_sync_incrementale(tmp_path)
    assert res["closed"] is True, res["why"]
    assert res["proof"]["sha256_verified"] is True
    assert res["proof"]["withdrawal_supported_by_business_model"] is False
    assert any("STAGING_EXTERNE" in x for x in res["proof"]["does_not_close"])


def test_verifier_sync_refuse_preuve_absente(tmp_path):
    res = blocages.verifier_sync_incrementale(tmp_path)
    assert res["closed"] is False and res["proof"] is None and "manquante" in res["why"]


def test_verifier_sync_refuse_preuve_alteree(tmp_path):
    assert "altération" in _refus_sync(tmp_path, tamper_sha=True)


def test_verifier_sync_refuse_statut_et_stale(tmp_path):
    def m(p):
        p["verification_status"] = "SYNC_FAILED"
    assert "VERIFIED" in _refus_sync(tmp_path, m)

    def m2(p):
        p["observed_at_main_sha"] = "0" * 40
    assert "stale" in _refus_sync(tmp_path, m2)


def test_verifier_sync_refuse_mock(tmp_path):
    def m(p):
        p["observations"]["real_engine"]["mock_detected"] = True
    assert "mock" in _refus_sync(tmp_path, m)


def test_verifier_sync_refuse_environnement_non_vierge(tmp_path):
    def m(p):
        p["observations"]["empty_state"]["counts"]["rag_chunks"] = 4
    assert "vierge" in _refus_sync(tmp_path, m)


def test_verifier_sync_refuse_perte(tmp_path):
    def m(p):
        p["observations"]["incremental_run"]["product"]["counts"]["rag_chunks"] = 29
    assert "perte" in _refus_sync(tmp_path, m)

    def m2(p):
        p["observations"]["incremental_run"]["full_release_ready"] = False
    assert "perte" in _refus_sync(tmp_path, m2)

    def m3(p):
        p["observations"]["incremental_run"]["product"]["chunk_id_set_sha256"] = "c" * 64
    assert "chunk" in _refus_sync(tmp_path, m3)


def test_verifier_sync_refuse_detecteur_de_perte_vacant(tmp_path):
    """Si l'état partiel est déclaré « prêt », le détecteur de perte ne détecte rien."""
    def m(p):
        p["observations"]["initial_state"]["full_release_ready"] = True
    assert "détecteur" in _refus_sync(tmp_path, m)


def test_verifier_sync_refuse_doublon(tmp_path):
    def m(p):
        p["observations"]["repeated_run"]["product"]["duplicates"]["rag_chunks"] = 1
    assert "doublon" in _refus_sync(tmp_path, m)

    def m2(p):
        p["observations"]["incremental_run"]["control"]["duplicate_resources"] = 1
    assert "doublon" in _refus_sync(tmp_path, m2)


def test_verifier_sync_refuse_derive_de_l_existant(tmp_path):
    def m(p):
        p["observations"]["incremental_run"]["wave_one_rows_after"]["content_sha256"] = "d" * 64
    assert "dérive" in _refus_sync(tmp_path, m)


def test_verifier_sync_refuse_reingestion_inutile(tmp_path):
    def m(p):
        p["observations"]["incremental_run"]["publications"].append({"content_sha256": "1" * 64, "embedded": True})
    assert "delta" in _refus_sync(tmp_path, m)

    def m2(p):
        p["observations"]["repeated_run"]["replays"][0]["embedded"] = True
    assert "ré-embedd" in _refus_sync(tmp_path, m2)


def test_verifier_sync_refuse_run_repete_non_idempotent(tmp_path):
    def m(p):
        p["observations"]["repeated_run"]["product"]["content_sha256"] = "e" * 64
    assert "idempot" in _refus_sync(tmp_path, m)

    def m2(p):
        p["observations"]["repeated_run"]["replays"] = p["observations"]["repeated_run"]["replays"][:1]
    assert "idempot" in _refus_sync(tmp_path, m2)


def test_verifier_sync_refuse_modification_atteignant_le_produit(tmp_path):
    def m(p):
        p["observations"]["modification_attempt"]["modified_content_in_product"] = 1
    assert "modifi" in _refus_sync(tmp_path, m)

    def m2(p):
        p["observations"]["modification_attempt"]["product_after"]["content_sha256"] = "e" * 64
    assert "modifi" in _refus_sync(tmp_path, m2)

    def m3(p):
        p["observations"]["modification_attempt"]["worker_outcomes"] = []
    assert "modifi" in _refus_sync(tmp_path, m3)


def test_verifier_sync_refuse_append_only_non_demontre(tmp_path):
    def m(p):
        p["observations"]["withdrawal"]["publisher_privileges"]["rag_chunks"].append("DELETE")
    assert "append-only" in _refus_sync(tmp_path, m)


@pytest.mark.parametrize(
    ("cle", "valeur"),
    [("production_db_writes", 1), ("production_deployments", 1), ("current_switch", 1),
     ("production_touched", True), ("docker_residues_after_test", 1)],
)
def test_verifier_sync_refuse_production_ou_residus(tmp_path, cle, valeur):
    def m(p):
        p["teardown"][cle] = valeur
    assert cle in _refus_sync(tmp_path, m)


def test_verifier_sync_sur_depot_reel():
    """État DÉRIVÉ du statut scellé : seule une preuve VERIFIED ferme."""
    preuve = json.loads((RACINE / blocages.SYNC_PREUVE).read_text(encoding="utf-8"))
    res = blocages.verifier_sync_incrementale(RACINE)
    assert res["closed"] is (preuve["verification_status"] == "VERIFIED"), res["why"]
    assert (res["proof"] is not None) is res["closed"]
