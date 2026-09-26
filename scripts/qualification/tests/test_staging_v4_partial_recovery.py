"""DI — reprise partielle de la publication V4 sous #262, sans serveur.

Identité de la reprise partielle confrontée aux fichiers de la release V4 ;
autorisation DI seulement PROPOSÉE (image en attente : inactive) et ses états
d'activation, hermétiques ; orchestrateur : essai à blanc et gardes sourcées.
Le parcours sur PostgreSQL réel est ``services/rag-engine/tests/integration/
test_di_partial_recovery_pg.py`` ; la dérivation des exclusions par les
mappings scellés est éprouvée dans ``services/rag-engine/tests/
test_di_release_subject_governance.py`` (elle importe ``ingestor``).
"""

from __future__ import annotations

import copy
import glob
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "scripts/go_live"))

import check_staging_authorization as autorisation  # noqa: E402
import staging_v4_partial_recovery as di  # noqa: E402

SCRIPT = RACINE / "scripts/go_live/staging_v4_partial_recovery.sh"
RELEASE = RACINE / autorisation.RELEASE_V4["release_dir"]
HGGSP = {"rag_nexus_hggsp_premiere_specialite", "rag_nexus_hggsp_terminale_specialite"}
IMAGE_DH = "sha256:57e079792ecfdd3720ac5936c66ea72b7efc766430407be3bb74057eec2bb20d"
COMMIT_DI = "c" * 40


def _sha(relatif: str) -> str:
    return hashlib.sha256((RACINE / relatif).read_bytes()).hexdigest()


# ── identité de la reprise partielle ───────────────────────────────────────


def _placements_par_collection() -> dict[str, list[str]]:
    return {
        (sujet := json.loads(Path(f).read_text()))["collection"]: [p["artifact_id"] for p in sujet["placements"]]
        for f in sorted(glob.glob(str(RELEASE / "subjects/*.release.json")))
    }


def test_l_identite_correspond_aux_fichiers_de_la_release():
    perimetre = di.charger_perimetre(RACINE / di.IDENTITE_PAR_DEFAUT)
    assert (perimetre.release_id, perimetre.release_manifest_sha256) == (
        autorisation.RELEASE_V4["release_id"], autorisation.RELEASE_V4["release_manifest_sha256"])
    assert (perimetre.database, perimetre.pull_request, perimetre.head_sha) == (
        "ragdb_profile_gate_v4", 262, autorisation.REVUE_ACTIVE_DI["head_sha"])
    assert set(perimetre.exclues) == HGGSP == set(autorisation.PERIMETRE_DI["excluded_collections"])
    par = _placements_par_collection()
    artefacts = {a["artifact_id"]: a for a in json.loads((RELEASE / "artifacts.release.json").read_text())["artifacts"]}
    repris = [c for c in par if c not in HGGSP]
    assert sorted(repris) == list(autorisation.COLLECTIONS_REPRISES_DI)
    uniques = {x for c in repris for x in par[c]}
    attendu = dict(perimetre.attendu)
    assert attendu["active_attestations"] == sum(len(v) for v in par.values()) == 479
    assert attendu["scope_collections"] == len(repris) == 9
    assert attendu["scope_placements"] == sum(len(par[c]) for c in repris) == 405
    assert attendu["excluded_placements"] == sum(len(par[c]) for c in HGGSP) == 74
    assert attendu["product_after_partial"] == autorisation.PERIMETRE_DI["expected_product_after"] == {
        "collections": 9, "artifacts": len(uniques), "placements": 405,
        "chunks": sum(len(artefacts[x]["chunks"]) for x in uniques),
    }
    # Aucun artefact partagé : publier les neuf collections ne publie rien de HGGSP.
    assert not uniques & {x for c in HGGSP for x in par[c]}


@pytest.mark.parametrize("alteration", [
    lambda d: d.update(kind="AUTRE"),
    lambda d: d.update(excluded_collections={}),
    lambda d: d["expected"].pop("scope_placements"),
    lambda d: d.update(extra=1),
])
def test_une_identite_non_conforme_est_refusee(tmp_path, alteration):
    document = json.loads((RACINE / di.IDENTITE_PAR_DEFAUT).read_text())
    alteration(document)
    chemin = tmp_path / "identite.json"
    chemin.write_text(json.dumps(document))
    with pytest.raises(di.RepriseRefusee):
        di.charger_perimetre(chemin)


def test_l_empreinte_des_exclus_voit_toute_reclamation_tentative_ou_report():
    job = {"job_id": "j", "attestation_id": "a", "status": "queued", "attempt_count": 1, "max_attempts": 3,
           "next_attempt_at": "2026-09-26T10:00:00+00:00", "last_error": "external subject 'hggsp' is not governed",
           "leased": False}
    reference = di.empreinte_des_jobs_exclus([job])
    for champ, valeur in (("status", "running"), ("attempt_count", 2), ("next_attempt_at", "2026-09-26T10:01:00"),
                          ("last_error", "github_rate_limited"), ("leased", True)):
        assert di.empreinte_des_jobs_exclus([{**job, champ: valeur}]) != reference, champ
    assert di.empreinte_des_jobs_exclus([job, {**job, "job_id": "k"}]) == di.empreinte_des_jobs_exclus(
        [{**job, "job_id": "k"}, job]), "indépendante de l'ordre de lecture"


# ── autorisation DI ────────────────────────────────────────────────────────


def _dh() -> dict:
    return json.loads((RACINE / autorisation.AUTORISATION_DH).read_text())


def _document_candidat() -> dict:
    return {
        **copy.deepcopy(autorisation.GABARIT_DI),
        "extends_dh": {"path": autorisation.AUTORISATION_DH, "sha256": _sha(autorisation.AUTORISATION_DH)},
        "extends_v4": {"path": autorisation.AUTORISATION_V4, "sha256": _sha(autorisation.AUTORISATION_V4)},
        "execution_plan": {"path": autorisation.PLAN_DI, "sha256": _sha(autorisation.PLAN_DI)},
        "partial_identity": {"path": autorisation.IDENTITE_DI, "sha256": _sha(autorisation.IDENTITE_DI)},
        "runtime_image": {
            "status": autorisation.IMAGE_EN_ATTENTE,
            "image_repository": autorisation.DEPOT_IMAGE,
            "build_workflow": ".github/workflows/production-image-provenance.yml",
            "build_ref": "main, après fusion de la PR DI",
            "required_fix_markers": autorisation.MARQUEURS_CORRECTIF_DI,
            "replaces_for_this_lot": _dh()["runtime_image"]["reference"],
            "activation": (
                "la PR d'activation remplace ce bloc par l'image épinglée par digest et sa preuve de provenance"
            ),
        },
        "probe_image": _dh()["probe_image"],
    }


def _image_construite(digest: str = "sha256:" + "a" * 64, commit: str = COMMIT_DI) -> dict:
    return {
        **autorisation.GABARIT_V4["runtime_image"],
        "image_digest": digest,
        "reference": f"{autorisation.DEPOT_IMAGE}@{digest}",
        "source_commit_sha": commit,
        "build_workflow_run_id": 36999999999,
        "evidence": {"path": "docs/reports/evidence/staging_worker_image_provenance_di.json", "sha256": "e" * 64},
    }


def _document_active(**image: str) -> dict:
    return {**_document_candidat(), "runtime_image": _image_construite(**image)}


def _octets(document: dict) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _liens(racine: Path = RACINE) -> dict[str, str]:
    return {
        relatif: hashlib.sha256((racine / relatif).read_bytes()).hexdigest()
        for relatif in (autorisation.AUTORISATION_DH, autorisation.AUTORISATION_V4,
                        autorisation.PLAN_DI, autorisation.IDENTITE_DI)
    }


def test_la_proposition_est_le_document_candidat_et_reste_inactive():
    assert (RACINE / autorisation.PROPOSITION_DI).read_bytes() == _octets(_document_candidat())
    assert not (RACINE / autorisation.AUTORISATION_DI).exists()
    assert autorisation.evaluer_di(RACINE, _document_candidat(), liens=_liens(), document_dh=_dh()) == [
        "DI : runtime_image en attente de construction depuis main — l'autorisation reste inactive"
    ]


def test_les_operations_di_sont_distinctes_et_ne_touchent_jamais_hggsp():
    assert not set(autorisation.OPERATIONS_DI) & (set(autorisation.OPERATIONS_DH) | set(autorisation.OPERATIONS_V4))
    worker = autorisation.OPERATIONS_DI["partial_worker_b_publication"]["cible"]
    assert set(worker["claimed_collections"]) & HGGSP == set()
    assert len(worker["claimed_collections"]) == 9
    assert (worker["control_role"], worker["product_role"]) == ("ingestion_control_app", "rag_publisher")
    assert worker["min_job_interval_s"] >= 60
    for interdit in ("hggsp_job_claim", "hggsp_job_cancellation", "manual_job_sql", "attempt_count_reset",
                     "review_262_merge_or_close", "review_verification_caching", "github_permission_widening",
                     "v4_subject_mapping_change", "new_release"):
        assert interdit in autorisation.GABARIT_DI["forbidden"], interdit


def _fichiers_lies() -> list[str]:
    base = json.loads((RACINE / autorisation.AUTORISATION).read_text())
    return [autorisation.AUTORISATION, base["execution_plan"]["path"], autorisation.AUTORISATION_V4,
            autorisation.AUTORISATION_DH, autorisation.PLAN_DI, autorisation.IDENTITE_DI]


def _etat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, document: dict, arbre: str,
          sur_main: str | None, correctif: bool = True, sur_la_branche_main: bool = True) -> Path:
    """Racine temporaire hermétique ; ``origin/main`` et le commit de build
    de l'image sont SIMULÉS (aucun accès git réel)."""
    racine = tmp_path / "depot"
    principal: dict[str, str] = {}
    for relatif in _fichiers_lies():
        (racine / relatif).parent.mkdir(parents=True, exist_ok=True)
        (racine / relatif).write_bytes((RACINE / relatif).read_bytes())
        principal[relatif] = (RACINE / relatif).read_text(encoding="utf-8")
    octets = _octets(document)
    (racine / arbre).parent.mkdir(parents=True, exist_ok=True)
    (racine / arbre).write_bytes(octets)
    if sur_main is not None:
        principal[sur_main] = octets.decode("utf-8")
    build = {chemin: (f"...{marqueur}..." if correctif else "...")
             for chemin, marqueur in autorisation.MARQUEURS_CORRECTIF_DI.items()}

    def git_simule(depot: Path, *args: str) -> subprocess.CompletedProcess[str]:
        assert depot == racine, depot
        if args[:1] == ("fetch",):
            return subprocess.CompletedProcess(list(args), 0, "", "")
        if args[:2] == ("merge-base", "--is-ancestor"):
            return subprocess.CompletedProcess(list(args), 0 if sur_la_branche_main else 1, "", "")
        assert args[0] == "show", args
        reference, _, chemin = args[1].partition(":")
        contenu = principal.get(chemin) if reference == "origin/main" else (
            build.get(chemin) if reference == COMMIT_DI else None)
        if contenu is None:
            return subprocess.CompletedProcess(list(args), 128, "", "fatal: path does not exist")
        return subprocess.CompletedProcess(list(args), 0, contenu, "")

    monkeypatch.setattr(autorisation, "_git", git_simule)
    return racine


def _cible(operation: str) -> dict:
    return copy.deepcopy(autorisation.OPERATIONS_DI[operation]["cible"])


@pytest.mark.parametrize("operation", autorisation.ORDRE_DI)
def test_1_pre_activation_toute_operation_di_est_refusee(tmp_path, monkeypatch, operation):
    racine = _etat(tmp_path, monkeypatch, document=_document_candidat(), arbre=autorisation.PROPOSITION_DI,
                   sur_main=autorisation.PROPOSITION_DI)
    ecarts = autorisation.verifier_operation_di(racine, operation, _cible(operation))
    assert ecarts and all("aucune autorisation DI" in e for e in ecarts), ecarts


@pytest.mark.parametrize("operation", autorisation.ORDRE_DI)
def test_2_une_image_en_attente_n_autorise_rien_meme_fusionnee(tmp_path, monkeypatch, operation):
    racine = _etat(tmp_path, monkeypatch, document=_document_candidat(), arbre=autorisation.AUTORISATION_DI,
                   sur_main=autorisation.AUTORISATION_DI)
    ecarts = autorisation.verifier_operation_di(racine, operation, _cible(operation))
    assert ecarts == ["DI : runtime_image en attente de construction depuis main — l'autorisation reste inactive"]


@pytest.mark.parametrize("operation", autorisation.ORDRE_DI)
def test_3_activation_non_fusionnee_reste_refusee(tmp_path, monkeypatch, operation):
    racine = _etat(tmp_path, monkeypatch, document=_document_active(), arbre=autorisation.AUTORISATION_DI,
                   sur_main=None)
    ecarts = autorisation.verifier_operation_di(racine, operation, _cible(operation))
    assert ecarts == [f"{autorisation.AUTORISATION_DI} n'est pas (ou pas à l'identique) sur origin/main"]


@pytest.mark.parametrize("operation", autorisation.ORDRE_DI)
def test_4_post_fusion_chaque_operation_di_sur_sa_cible_canonique_est_autorisee(tmp_path, monkeypatch, operation):
    racine = _etat(tmp_path, monkeypatch, document=_document_active(), arbre=autorisation.AUTORISATION_DI,
                   sur_main=autorisation.AUTORISATION_DI)
    assert autorisation.verifier_operation_di(racine, operation, _cible(operation)) == []


@pytest.mark.parametrize("champ,valeur,attendu", [
    ("database", "ragdb", "database = 'ragdb', autorisé 'ragdb_profile_gate_v4'"),
    ("claimed_collections", [*autorisation.COLLECTIONS_REPRISES_DI, "rag_nexus_hggsp_terminale_specialite"],
     "claimed_collections"),
    ("min_job_interval_s", 0, "min_job_interval_s = 0"),
])
def test_4_post_fusion_une_cible_falsifiee_reste_refusee(tmp_path, monkeypatch, champ, valeur, attendu):
    racine = _etat(tmp_path, monkeypatch, document=_document_active(), arbre=autorisation.AUTORISATION_DI,
                   sur_main=autorisation.AUTORISATION_DI)
    ecarts = autorisation.verifier_operation_di(
        racine, "partial_worker_b_publication", {**_cible("partial_worker_b_publication"), champ: valeur})
    assert len(ecarts) == 1 and attendu in ecarts[0], ecarts


@pytest.mark.parametrize("etat,attendu", [
    ({"document": _document_active(digest=IMAGE_DH)}, "l'image de DH ne contient pas le correctif"),
    ({"document": _document_active(), "correctif": False}, "ne porte pas le correctif"),
    ({"document": _document_active(), "sur_la_branche_main": False}, "n'est pas sur origin/main"),
    ({"document": _document_active(commit="d" * 40)}, "introuvable"),
])
def test_4_une_image_sans_le_correctif_est_refusee(tmp_path, monkeypatch, etat, attendu):
    racine = _etat(tmp_path, monkeypatch, arbre=autorisation.AUTORISATION_DI,
                   sur_main=autorisation.AUTORISATION_DI, **etat)
    ecarts = autorisation.verifier_operation_di(racine, "partial_preflight", _cible("partial_preflight"))
    assert any(attendu in e for e in ecarts), ecarts


@pytest.mark.parametrize("alteration,motif", [
    (lambda d: d["partial_scope"]["claimed_collections"].append("rag_nexus_hggsp_premiere_specialite"),
     "partial_scope"),
    (lambda d: d["worker_b_pacing"].update(min_job_interval_s=1), "worker_b_pacing"),
    (lambda d: d["active_review"].update(pull_request=257), "active_review"),
    (lambda d: d["forbidden"].remove("hggsp_job_claim"), "interdits manquants"),
    (lambda d: d["forbidden"].remove("review_verification_caching"), "interdits manquants"),
    (lambda d: d.update(consumed=True), "consommée"),
    (lambda d: d["extends_dh"].update(sha256="0" * 64), "extends_dh"),
    (lambda d: d["partial_identity"].update(sha256="0" * 64), "partial_identity"),
    (lambda d: d["probe_image"].update(image_digest="sha256:" + "0" * 64), "probe_image"),
    (lambda d: d.update(authorization_statement="tout"), "mention manquante"),
])
def test_une_autorisation_di_alteree_est_refusee(tmp_path, monkeypatch, alteration, motif):
    document = _document_active()
    alteration(document)
    racine = _etat(tmp_path, monkeypatch, document=document, arbre=autorisation.AUTORISATION_DI,
                   sur_main=autorisation.AUTORISATION_DI)
    ecarts = autorisation.evaluer_di(racine, document, liens=_liens(racine), document_dh=_dh())
    assert any(motif in e for e in ecarts), ecarts


# ── orchestrateur ──────────────────────────────────────────────────────────


def _env(tmp: Path, **extra: str) -> dict[str, str]:
    etat, v4, pret = tmp / "etat", tmp / "v4", tmp / "pret"
    for d in (etat, v4, pret):
        d.mkdir(exist_ok=True)
    etat.chmod(0o700)
    (pret / "staging-readiness-v4-di.json").write_text("{}")
    (v4 / "transfer_manifest_v4.done").write_text("sha256=" + "c" * 64 + "\n")
    return {
        "PATH": os.environ["PATH"], "HOME": str(tmp), "STATE_DIR": str(etat), "V4_STATE_DIR": str(v4),
        "PYTHON": sys.executable, "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        "READINESS_LOCAL": str(pret), "DRY_RUN_OFFLINE": "1", **extra,
    }


def _essai(tmp: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), "--dry-run", "run"], capture_output=True, text=True,
                          check=False, env=_env(tmp, **extra), cwd=RACINE)


def test_l_essai_a_blanc_va_jusqu_au_controle_partiel_sans_toucher_hggsp(tmp_path):
    essai = _essai(tmp_path)
    texte = essai.stdout + essai.stderr + (tmp_path / "etat" / "execution.log").read_text()
    assert essai.returncode == 0, texte[-3000:]
    # La signature de la readiness est LOCALE (détenteur de la clé, script
    # distinct) : jamais une étape de l'orchestrateur, qui parle à l'hôte.
    etapes = [op for op in autorisation.ORDRE_DI if op != "partial_readiness_resign"]
    assert sorted(p.stem for p in (tmp_path / "etat").glob("*.done")) == sorted(etapes)
    assert "sign_staging" not in texte
    # Pré-vol (précondition partielle + revue #262 en direct) AVANT Worker B.
    assert texte.index("partial-precondition") < texte.index("multilevel_publication_resume_cli")
    assert texte.index("--stage worker-b") < texte.index("multilevel_publication_resume_cli")
    lancement = next(ligne for ligne in texte.splitlines() if "multilevel_publication_resume_cli" in ligne)
    for collection in autorisation.COLLECTIONS_REPRISES_DI:
        assert f"--collection {collection}" in lancement, collection
    assert "hggsp" not in lancement
    for option in ("--min-job-interval-s 60", "--rate-limit-max-wait-s 900",
                   "--max-consecutive-rate-limits 3", "--max-idle-polls 5"):
        assert option in lancement, option
    assert "--name nexus-v4-worker-b-di-1" in texte
    assert "staging-readiness-v4-di.json" in texte
    assert "--collection rag_nexus_dgemc_terminale_option" in texte.split("staging_retrieval_probe.py", 1)[1]
    assert "ATTENTE_HUMAINE: la revue #262 reste OUVERTE" in texte
    for interdit in ("DELETE FROM", "UPDATE ingestion_control", "TRUNCATE", "dropdb", "cancel-stale-jobs",
                     "invalidate-stale-attestations", "gh pr merge", "gh pr close", "git push",
                     "staging_v4_enqueue_publication.py", "docker rm "):
        assert interdit not in texte, interdit


def _bash(tmp: Path, corps: str, **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-c", f'source "{SCRIPT}"\n{corps}\n'], capture_output=True, text=True,
                          check=False, env={**_env(tmp), "DRY_RUN_OFFLINE": "0", **extra}, cwd=RACINE)


MESURES = "\n".join([
    "LEGACY_PRODUCT_HEAD=4", "LEGACY_CONTROL_HEAD=15", "LEGACY_RESOURCES=479:x", "LEGACY_ARTIFACTS=479:x",
    "LEGACY_PLACEMENTS=26:x", "LEGACY_CHUNKS=730:x", "LEGACY_SCOPE_AUTHORIZATIONS=22",
    "PRODUCT_ROWS=72:76:1532", "WORKER_B nexus-v4-worker-b exited", "WORKER_B nexus-v4-worker-b-dh exited",
    "WORKER_B nexus-v4-worker-b-di-1 absent", "GITHUB_TOKEN ok",
])


@pytest.mark.parametrize("remplacer,motif", [
    (None, None),
    (("nexus-v4-worker-b-dh exited", "nexus-v4-worker-b-dh running"), "Worker B est actif"),
    (("nexus-v4-worker-b-di-1 absent", "nexus-v4-worker-b-di-1 restarting"), "Worker B est actif"),
    (("GITHUB_TOKEN ok", ""), "jeton GitHub"),
    (("LEGACY_CHUNKS=730:x\n", ""), "incomplète"),
])
def test_la_decision_du_prevol_di(tmp_path, remplacer, motif):
    mesures = MESURES if remplacer is None else MESURES.replace(*remplacer)
    sortie = _bash(tmp_path, 'decision_prevol_di "$MESURES"', MESURES=mesures)
    if motif is None:
        assert sortie.returncode == 0, sortie.stderr
    else:
        assert sortie.returncode == 3 and motif in sortie.stderr, sortie.stderr


def test_la_relance_exige_un_arret_pour_limitation(tmp_path):
    refus = subprocess.run(["bash", str(SCRIPT), "--dry-run", "run"], capture_output=True, text=True, check=False,
                           env=_env(tmp_path, DI_RELAUNCH="1"), cwd=RACINE)
    assert refus.returncode == 3 and "aucun arrêt pour limitation constaté" in refus.stderr, refus.stderr
