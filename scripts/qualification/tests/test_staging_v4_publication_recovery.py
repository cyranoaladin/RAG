"""DH — reprise de la publication V4 après la fermeture de la revue #257, sans serveur.

Identité de la revue périmée tirée du dépôt, autorisation DH seulement
PROPOSÉE (inactive), orchestrateur : essai à blanc et gardes sourcées. Le
parcours sur PostgreSQL réel est ``services/rag-engine/tests/integration/
test_dh_publication_recovery_pg.py``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RACINE / "scripts/go_live"))
sys.path.insert(0, str(RACINE / "packages/contracts/src"))

import check_staging_authorization as autorisation  # noqa: E402
import staging_v4_publication_recovery as dh  # noqa: E402

SCRIPT = RACINE / "scripts/go_live/staging_v4_publication_recovery.sh"
ARTEFACT_257 = (
    "governance/publication-reviews/lot42-release-batch-v4-staging-20260924-"
    "19ba49a2b56b3075b0f26ac75998cadcc696dab44864e6940d4f004c862279b9.json"
)


def _sha(relatif: str) -> str:
    return hashlib.sha256((RACINE / relatif).read_bytes()).hexdigest()


# ── identité de la revue périmée ───────────────────────────────────────────


def test_l_identite_de_257_est_tiree_de_l_artefact_revu():
    revue = dh.charger_revue_perimee(RACINE / dh.IDENTITE_PAR_DEFAUT, racine=RACINE)
    v4 = autorisation.RELEASE_V4
    assert revue.release["release_id"] == v4["release_id"]
    assert revue.release["release_manifest_sha256"] == v4["release_manifest_sha256"]
    assert (revue.repository, revue.pull_request) == ("cyranoaladin/RAG", 257)
    assert revue.head_sha == autorisation.REVUE_PERIMEE_DH["head_sha"]
    assert revue.review_digest == autorisation.REVUE_PERIMEE_DH["review_artifact_sha256"] == _sha(ARTEFACT_257)
    assert revue.review_id == autorisation.REVUE_PERIMEE_DH["review_id"]
    assert revue.review_artifact_path == ARTEFACT_257
    assert len(revue.collections) == 11 and len(revue.scope_authorization_ids) == 11
    assert all(i.startswith("lot41a-staging-v4-") and i.endswith("-r4") for i in revue.scope_authorization_ids)
    assert dict(revue.attendu) == {
        "attestations": 479, "resources": 479, "unique_contents": 315, "collections": 11, "publication_jobs": 479,
    }
    assert (revue.database, revue.legacy_database) == ("ragdb_profile_gate_v4", "ragdb")


@pytest.mark.parametrize("champ,valeur,motif", [
    ("review_artifact_sha256", "0" * 64, "sha256"),
    ("kind", "AUTRE", "kind"),
    ("expected", {"attestations": 480, "resources": 479, "unique_contents": 315, "collections": 11,
                  "publication_jobs": 479}, "attestations"),
])
def test_une_identite_alteree_est_refusee(tmp_path, champ, valeur, motif):
    document = json.loads((RACINE / dh.IDENTITE_PAR_DEFAUT).read_text())
    document[champ] = valeur
    chemin = tmp_path / "identite.json"
    chemin.write_text(json.dumps(document))
    with pytest.raises(dh.RecuperationRefusee, match=motif):
        dh.charger_revue_perimee(chemin, racine=RACINE)


def test_expiration_et_annulation_sont_deux_classes_distinctes():
    empreinte = "e" * 64
    marque = {dh.CLE_ANNULATION: {"attestation_set_sha256": empreinte}}
    cas = [
        ("running", True, {}, "running_lease_active"),
        ("running", False, {}, "running_lease_expired"),
        ("cancelled", False, marque, "cancelled_dh"),
        ("cancelled", False, {}, "cancelled_other"),
        ("queued", False, {}, "queued"),
        ("dead_letter", False, {}, "dead_letter"),
    ]
    for statut, actif, charge, attendu in cas:
        assert dh._classe_job({"status": statut, "lease_active": actif, "payload": charge}, empreinte) == attendu


def test_le_motif_d_invalidation_ne_reconnait_que_le_meme_ensemble():
    revue = dh.charger_revue_perimee(RACINE / dh.IDENTITE_PAR_DEFAUT, racine=RACINE)
    motif = dh.motif_invalidation(revue, empreinte="a" * 64, raison_live="pull_request_not_open")
    assert dh._invalidee_par_dh({"invalidated_reason": motif}, "a" * 64)
    assert not dh._invalidee_par_dh({"invalidated_reason": motif}, "b" * 64)
    assert not dh._invalidee_par_dh({"invalidated_reason": "human_review is no longer approved"}, "a" * 64)
    assert "cyranoaladin/RAG#257@85f9000115df" in motif


def test_l_outil_n_importe_que_des_primitives_deja_dans_l_image():
    """Exécuté depuis /repo dans l'image épinglée : aucun module ajouté par DH."""
    source = (RACINE / "scripts/go_live/staging_v4_publication_recovery.py").read_text()
    imports = {ligne.strip() for ligne in source.splitlines() if ligne.strip().startswith(("from ingestor", "import ingestor", "from nexus_contracts"))}
    assert imports == {
        "from ingestor.ingestion_control.github_authority import (  # noqa: PLC0415",
        "from nexus_contracts.authority_artifacts import (  # noqa: PLC0415",
    }, imports


# ── autorisation DH : proposée, jamais active ici ──────────────────────────


def _proposition() -> dict:
    return json.loads((RACINE / autorisation.PROPOSITION_DH).read_text())


def _evaluer(document: dict) -> list[str]:
    return autorisation.evaluer_dh(
        document,
        base_sha256=_sha(autorisation.AUTORISATION),
        v4_sha256=_sha(autorisation.AUTORISATION_V4),
        plan_sha256=_sha(autorisation.PLAN_DH),
        identite_sha256=_sha(autorisation.IDENTITE_PERIMEE_DH),
        document_v4=json.loads((RACINE / autorisation.AUTORISATION_V4).read_text()),
    )


def test_la_proposition_est_conforme_mais_n_est_pas_l_autorisation():
    assert _evaluer(_proposition()) == []
    # La PR DH ne vaut pas autorisation : le chemin canonique n'existe pas.
    assert not (RACINE / autorisation.AUTORISATION_DH).exists()


@pytest.mark.parametrize("operation", sorted(autorisation.OPERATIONS_DH))
def test_aucune_operation_dh_n_est_autorisee_sans_la_pr_d_activation(operation):
    ecarts = autorisation.verifier_operation_dh(
        RACINE, operation, copy.deepcopy(autorisation.OPERATIONS_DH[operation]["cible"])
    )
    assert any("aucune autorisation DH" in e for e in ecarts), ecarts


@pytest.mark.parametrize("alteration,motif", [
    (lambda d: d["runtime_image"].update(image_digest="sha256:" + "0" * 64), "runtime_image"),
    (lambda d: d["stale_review"].update(pull_request=258), "stale_review"),
    (lambda d: d["forbidden"].remove("row_deletion"), "interdits manquants"),
    (lambda d: d["forbidden"].remove("automatic_review_merge"), "interdits manquants"),
    (lambda d: d.update(consumed=True), "consommée"),
    (lambda d: d["extends_v4"].update(sha256="0" * 64), "extends_v4"),
    (lambda d: d["stale_review_identity"].update(sha256="0" * 64), "stale_review_identity"),
    (lambda d: d["operations"].append("reingestion"), "operations"),
    (lambda d: d["review_lifecycle"].update(merge_or_close="automatique"), "review_lifecycle"),
    (lambda d: d.update(authorization_statement="tout"), "mention manquante"),
])
def test_une_proposition_alteree_est_refusee(alteration, motif):
    document = _proposition()
    alteration(document)
    assert any(motif in e for e in _evaluer(document)), _evaluer(document)


def test_les_roles_des_operations_dh_sont_separes():
    ops = autorisation.OPERATIONS_DH
    assert ops["stale_job_cancellation"]["cible"]["control_role"] == "ingestion_control_app"
    assert ops["stale_attestation_invalidation"]["cible"]["control_role"] == "ingestion_control_attestor"
    assert ops["recovery_worker_b_publication"]["cible"]["control_role"] == "ingestion_control_app"
    assert ops["recovery_review_record"]["cible"]["forbidden_pull_request"] == 257
    for op, spec in ops.items():
        assert spec["cible"]["database"] == "ragdb_profile_gate_v4", op
    # Les opérations V4 ne sont pas réutilisées sous un autre nom, ni l'inverse.
    assert not set(ops) & set(autorisation.OPERATIONS_V4)


# ── orchestrateur ──────────────────────────────────────────────────────────


def _env(tmp: Path, **extra: str) -> dict[str, str]:
    etat, v4, pret = tmp / "etat", tmp / "v4", tmp / "pret"
    for d in (etat, v4, pret):
        d.mkdir(exist_ok=True)
    etat.chmod(0o700)
    (pret / "staging-readiness-v4.json").write_text("{}")
    (v4 / "transfer_manifest_v4.done").write_text("sha256=" + "c" * 64 + "\n")
    return {
        "PATH": os.environ["PATH"], "HOME": str(tmp), "STATE_DIR": str(etat), "V4_STATE_DIR": str(v4),
        "PYTHON": sys.executable, "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        "READINESS_LOCAL": str(pret), "DRY_RUN_OFFLINE": "1",
        "BATCH_REVIEW_ID": "revue-dh-essai", "EVALUATOR": "essai", **extra,
    }


def _essai(tmp: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), "--dry-run", "run"], capture_output=True, text=True,
                          check=False, env=_env(tmp, **extra))


def test_l_essai_s_arrete_a_la_revue_humaine_puis_va_jusqu_au_controle_de_fermeture(tmp_path):
    premier = _essai(tmp_path)
    texte = premier.stdout + premier.stderr
    assert premier.returncode == 0, texte[-2000:]
    assert "ATTENTE_HUMAINE: revue de reprise" in texte and "ARRET" not in texte
    faites = sorted(p.stem for p in (tmp_path / "etat").glob("*.done"))
    ordre = list(autorisation.ORDRE_DH)
    assert faites == sorted(ordre[: ordre.index("recovery_review_proposal") + 1])

    suite = _essai(tmp_path, BATCH_REVIEW_PR="259", BATCH_REVIEW_HEAD="d" * 40,
                   BATCH_REVIEW_ARTIFACT="governance/publication-reviews/x.json")
    texte = suite.stdout + suite.stderr
    assert suite.returncode == 0, texte[-2000:]
    assert sorted(p.stem for p in (tmp_path / "etat").glob("*.done")) == sorted(ordre)
    # Préconditions de revue AVANT la mise en file et AVANT Worker B.
    assert texte.index("--stage enqueue") < texte.index("staging_v4_enqueue_publication.py")
    assert texte.index("--stage worker-b") < texte.index("multilevel_publication_resume_cli")
    assert "ATTENTE_HUMAINE: la PR de revue de reprise peut être fusionnée ou fermée par un humain" in texte


def test_l_essai_nomme_les_bons_roles_et_ne_supprime_rien(tmp_path):
    _essai(tmp_path)
    suite = _essai(tmp_path, BATCH_REVIEW_PR="259", BATCH_REVIEW_HEAD="d" * 40,
                   BATCH_REVIEW_ARTIFACT="governance/publication-reviews/x.json")
    texte = (tmp_path / "etat" / "execution.log").read_text() + suite.stderr
    annulation = next(l for l in texte.splitlines() if "cancel-stale-jobs" in l)
    invalidation = next(l for l in texte.splitlines() if "invalidate-stale-attestations" in l)
    assert "ingestion-control-app.env" in texte and "ingestion-control-attestor.env" in texte
    assert "--attestation-set-sha256" in annulation and "--job-set-sha256" in annulation
    assert "--attestation-set-sha256" in invalidation
    for interdit in ("DELETE FROM", "dropdb", "drop database", "TRUNCATE", "docker rm nexus-v4-worker-b ",
                     "docker rm nexus-v4-worker-b\n", "gh pr merge", "git push"):
        assert interdit not in texte, interdit
    assert "--name nexus-v4-worker-b-dh" in texte
    for ligne in texte.splitlines():
        if " -d ragdb " in ligne or "-d ragdb\\" in ligne:
            assert "default_transaction_read_only=on" in ligne, ligne


def test_la_revue_257_ne_fonde_jamais_une_reprise(tmp_path):
    _essai(tmp_path)
    refus = _essai(tmp_path, BATCH_REVIEW_PR="257", BATCH_REVIEW_HEAD="d" * 40,
                   BATCH_REVIEW_ARTIFACT="governance/publication-reviews/x.json")
    assert refus.returncode == 3 and "la revue #257 est fermée" in refus.stderr
    autre = tmp_path / "identifiant-de-257"
    autre.mkdir()
    identique = _essai(autre, BATCH_REVIEW_ID="lot42-release-batch-v4-staging-20260924")
    assert identique.returncode == 3 and "celui de #257" in identique.stderr


def _bash(tmp: Path, corps: str, **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", "-c", f'source "{SCRIPT}"\n{corps}\n'], capture_output=True, text=True,
                          check=False, env={**_env(tmp), "DRY_RUN_OFFLINE": "0", **extra})


MESURES_SAINES = "\n".join([
    "LEGACY_PRODUCT_HEAD=4", "LEGACY_CONTROL_HEAD=15", "LEGACY_RESOURCES=479:x", "LEGACY_ARTIFACTS=479:x",
    "LEGACY_PLACEMENTS=26:x", "LEGACY_CHUNKS=730:x", "LEGACY_SCOPE_AUTHORIZATIONS=22", "TARGET_EXISTS=1",
    "PRODUCT_ROWS=0:0:0", "WORKER_B nexus-v4-worker-b exited", "WORKER_B nexus-v4-worker-b-dh absent",
    "TRANSFER_MANIFEST=" + "c" * 64, "GITHUB_TOKEN ok",
])


@pytest.mark.parametrize("remplacer,motif", [
    (None, None),
    (("PRODUCT_ROWS=0:0:0", "PRODUCT_ROWS=1:2:30"), "lignes produit"),
    (("WORKER_B nexus-v4-worker-b exited", "WORKER_B nexus-v4-worker-b running"), "Worker B est actif"),
    (("TARGET_EXISTS=1", "TARGET_EXISTS=0"), "DH ne crée aucune base"),
    (("TRANSFER_MANIFEST=" + "c" * 64, "TRANSFER_MANIFEST=" + "0" * 64), "manifeste de transfert"),
    (("GITHUB_TOKEN ok", ""), "jeton GitHub"),
    (("LEGACY_CHUNKS=730:x\n", ""), "incomplète"),
])
def test_la_decision_du_prevol_dh(tmp_path, remplacer, motif):
    mesures = MESURES_SAINES if remplacer is None else MESURES_SAINES.replace(*remplacer)
    sortie = _bash(tmp_path, 'decision_prevol_dh "$MESURES"', MESURES=mesures)
    if motif is None:
        assert sortie.returncode == 0, sortie.stderr
        assert (tmp_path / "etat" / "legacy_baseline.txt").read_text().count("LEGACY_") == 7
    else:
        assert sortie.returncode == 3 and motif in sortie.stderr, sortie.stderr


def test_l_annulation_exige_l_accuse_de_lecture_de_l_apercu(tmp_path):
    (tmp_path / "etat").mkdir(exist_ok=True)
    corps = (
        'autoriser_dh() { :; }; remote() { cat >/dev/null; echo "STALE_JOBS_CANCELLED review=x"; }\n'
        'verifier_historique() { :; }\n'
        f'printf "attestation_set_sha256={"a" * 64}\\njob_set_sha256={"b" * 64}\\n" > "$STATE_DIR/recovery_plan.txt"\n'
        "AUTH_COMMIT=x IMAGE=x\n"
    )
    refus = _bash(tmp_path, corps + "etape_stale_job_cancellation")
    assert refus.returncode == 3 and "DH_PREVIEW_ACK" in refus.stderr, refus.stderr
    accepte = _bash(tmp_path, corps + f"DH_PREVIEW_ACK={'a' * 64} etape_stale_job_cancellation")
    assert accepte.returncode == 0, accepte.stderr
    assert (tmp_path / "etat" / "stale_job_cancellation.done").is_file()
