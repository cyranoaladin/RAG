"""Lot DI — reprise partielle gouvernée après l'incident Worker B sous #262.

Reproduit sur PostgreSQL jetable, par la VRAIE itération de Worker B
(``run_publication_resume_iteration`` : vérifications live, promotion, pins,
publisher gouverné), les trois faits de l'incident :

1. une limitation de débit GitHub pendant la vérification live ;
2. un 403 GitHub APRÈS l'écriture du pin, avant la publication produit — le
   cas réel ``rag_nexus_nsi_terminale_specialite`` : ressource
   ``RETRIEVAL_ELIGIBLE``, pin présent, placement produit absent, job en file ;
3. une collection que la release ne peut pas publier (le banc tient
   ``rag_nexus_nsi_premiere_specialite`` hors périmètre, à la place de HGGSP).

Épreuves :

C. la limitation diffère le job sans consommer de tentative, sans pin, sans
   promotion, après UN seul appel GitHub ;
D. RETRIEVAL_ELIGIBLE + pin + produit absent -> reprise du même job ->
   publication, sans nouvelle promotion, sans second pin, sans doublon ;
E. la reprise partielle ne régresse aucun job réussi et ne duplique rien ;
F. aucun job exclu n'est réclamé, retenté ni consommé (empreinte exacte) ;
   contre-épreuve : un worker SANS liste d'autorisation le consomme, et le
   contrôle partiel le détecte ;
G. ``closure-check`` (DH) refuse tant que les exclus attendent ; le contrôle
   partiel constate la fin du périmètre et n'annonce JAMAIS la fermeture.

**Autorités de TEST** servies par ``LocalGitHub`` ; **embeddings de TEST**
(identité DEBUG) — mêmes limites que le banc DH, rappelées dans son en-tête.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ENGINE_ROOT.parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts/go_live"))

if os.environ.get("NEXUS_DI_RECOVERY_PG") != "1":
    pytest.skip("banc DI non demandé (NEXUS_DI_RECOVERY_PG=1)", allow_module_level=True)

# Le banc DH est RÉUTILISÉ (forge, Worker B en processus, préparation
# temporelle) ; son module se protège par une variable d'opt-in, posée le
# seul temps de l'import.
_precedent = os.environ.get("NEXUS_DH_RECOVERY_PG")
os.environ["NEXUS_DH_RECOVERY_PG"] = "1"
try:
    import test_dh_publication_recovery_pg as banc_dh  # noqa: E402
finally:
    if _precedent is None:
        os.environ.pop("NEXUS_DH_RECOVERY_PG", None)
    else:
        os.environ["NEXUS_DH_RECOVERY_PG"] = _precedent

import staging_v4_partial_recovery as di  # noqa: E402
import staging_v4_publication_recovery as dh  # noqa: E402
from _local_github import REPOSITORY, VALID_TOKEN, LocalGitHub, local_github_server  # noqa: E402
from _pg_authority import (  # noqa: E402
    app_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    start_rag_product_postgres,
    superuser_dsn,
)

pytestmark = [pytest.mark.integration, requires_docker]

banc_batch = banc_dh.banc_batch
PR, TETE = 7262, hashlib.sha1(b"di-revue-banc").hexdigest()
REVUE = "di-revue-banc"
EXCLUE = "rag_nexus_nsi_premiere_specialite"
PORTEE = "rag_nexus_nsi_terminale_specialite"
#: GET GitHub d'une publication complète, mesurés sur ce banc (un relecteur
#: gouverné) : neuf vérifications live d'ADR-0033 § 7bis, aucune supprimée.
#: La reprise d'un job déjà épinglé saute la promotion : 56.
APPELS_GITHUB_PAR_PUBLICATION = 63
APPELS_GITHUB_PAR_REPRISE_EPINGLEE = 56
LIMITATION = (403, {"Retry-After": "60", "x-ratelimit-remaining": "4210"},
              "You have exceeded a secondary rate limit.")


@pytest.fixture(scope="module")
def modele_de_banc(tmp_path_factory: pytest.TempPathFactory):  # noqa: ANN201
    with banc_dh.modele_du_banc(racine_fictive=tmp_path_factory.mktemp("inventaire-fictif-di")) as selection:
        yield selection


@pytest.fixture(scope="module")
def control() -> Any:
    yield from start_ingestion_control_postgres("di-partial-control")


@pytest.fixture(scope="module")
def product_pg() -> Any:
    yield from start_rag_product_postgres("di-partial-product")


def _preparer_revue_active(control: dict[str, str], tmp_path: Path, github: LocalGitHub, jeton: Path) -> Any:
    """Revue #7262 approuvée ET OUVERTE -> 4 attestations -> 4 jobs (outil DG)."""
    banc = banc_batch._contexte_du_banc(tmp_path)
    github.add_approved_pr(number=PR, head_sha=TETE, base_sha="9" * 40, review_id=PR + 10)
    with local_github_server(github) as url:
        env = banc_batch._environnement_d_autorite(control, github_url=url, jeton=jeton)
        banc_batch._semer_etat_historique(control, contexte=banc, github=github, env=env)
        propose = banc_batch._run(banc_dh.ATTEST_CLI, banc_batch._arguments_de_proposition(banc, revue=REVUE), env)
        assert propose.returncode == 0, propose.stderr
        chemin, octets = banc_batch._artefact_propose(propose.stdout)
        github.put_blob(path=chemin, ref=TETE, content=octets)
        enregistre = banc_batch._run(banc_dh.ATTEST_CLI, banc_batch._arguments_d_enregistrement(
            banc, chemin=chemin, head=TETE, revue=REVUE, pull_request=PR), env)
        assert enregistre.returncode == 0, enregistre.stderr
    enfile = banc_dh._executer(banc_dh.OUTIL_DG, ["--release-id", banc.release_id, "--expected-jobs", "4"],
                               {"PG_INGESTION_CONTROL_DSN": app_dsn(control)})
    assert enfile.returncode == 0 and "crees=4" in enfile.stdout, enfile.stdout + enfile.stderr
    return banc


def _perimetre(banc: Any, tmp_path: Path) -> di.Perimetre:
    identite = tmp_path / "di-identite.json"
    identite.write_text(json.dumps({
        "kind": di.KIND,
        "release": {"release_id": banc.release_id, "release_manifest_sha256": banc.digests["release_manifest_sha256"]},
        "database": "ragdb",
        "review": {"repository": REPOSITORY, "pull_request": PR, "head_sha": TETE},
        "excluded_collections": {EXCLUE: "banc : collection tenue hors du périmètre repris"},
        "exclusion_authority": {"note": "banc : exclusion de test, non dérivée"},
        "expected": {
            "active_attestations": 4, "scope_collections": 1, "scope_placements": 2,
            "excluded_placements": 2, "product_after_partial": {},
        },
    }))
    return di.charger_perimetre(identite)


def _requete(control: dict[str, str], sql: str, params: Any = None) -> list[tuple[Any, ...]]:
    with psycopg.connect(superuser_dsn(control)) as conn:
        lignes = conn.execute(sql, params).fetchall()
        conn.rollback()
    return lignes


def _jobs_par_collection(control: dict[str, str]) -> dict[str, list[tuple[Any, ...]]]:
    """collection -> lignes complètes de ses jobs (tout ce qu'un worker changerait)."""
    lignes = _requete(control, """
        SELECT r.collection, j.job_id, j.status, j.attempt_count, j.next_attempt_at,
               j.last_error, j.lease_token, j.claimed_by, j.updated_at
          FROM ingestion_control.jobs j JOIN ingestion_control.resources r USING (resource_id)
         ORDER BY j.job_id""")
    par: dict[str, list[tuple[Any, ...]]] = {}
    for ligne in lignes:
        par.setdefault(ligne[0], []).append(ligne[1:])
    return par


def _etat_de(control: dict[str, str], job_id: Any) -> dict[str, Any]:
    (ligne,) = _requete(control, """
        SELECT j.status, j.attempt_count, j.next_attempt_at, j.last_error, r.resource_state,
               r.resource_id, j.payload->>'publication_attestation_id'
          FROM ingestion_control.jobs j JOIN ingestion_control.resources r USING (resource_id)
         WHERE j.job_id = %s""", (job_id,))
    statut, tentatives, prochaine, erreur, etat, ressource, attestation = ligne
    pins = _requete(control, "SELECT count(*) FROM ingestion_control.publication_commit_pins"
                    " WHERE publication_attestation_id = %s", (attestation,))[0][0]
    promotions = _requete(control, "SELECT count(*) FROM ingestion_control.workflow_events"
                          " WHERE resource_id = %s AND to_state IN ('REVIEWED', 'RETRIEVAL_ELIGIBLE')",
                          (ressource,))[0][0]
    return {"status": statut, "attempts": tentatives, "next": prochaine, "error": erreur or "",
            "state": etat, "pins": pins, "promotions": promotions}


def _worker(control: dict[str, str], deps: Any, github: LocalGitHub, jeton: Path,
            monkeypatch: pytest.MonkeyPatch, fois: int) -> list[Any]:
    with banc_dh._Forge(github, jeton, monkeypatch):
        return banc_dh._iterer_worker_b(control, deps, fois)


def test_reprise_partielle_de_bout_en_bout(
    modele_de_banc: Any, control: dict[str, str], product_pg: dict[str, str],
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    github, jeton = LocalGitHub(), tmp_path / "github-token"
    jeton.write_text(VALID_TOKEN, encoding="utf-8")
    banc = _preparer_revue_active(control, tmp_path, github, jeton)
    perimetre = _perimetre(banc, tmp_path)
    contenus = sorted(c.content_sha256 for c in banc.contenus)

    # ── précondition : le périmètre et l'empreinte des exclus ──
    with psycopg.connect(app_dsn(control)) as conn:
        pre = di.precondition_partielle(conn, perimetre)
    assert pre["claim_scope"] == [PORTEE]
    assert (pre["to_publish"], pre["already_published"], pre["excluded_pending"]) == (2, 0, 2)
    exclus_avant = _jobs_par_collection(control)[EXCLUE]

    deps = banc_dh._deps_worker_b(banc, product_pg)
    deps.claim_collections = (PORTEE,)

    # ── C. limitation de débit : report, AUCUNE tentative, un seul appel ──
    github.fault = lambda _chemin: LIMITATION
    appels_avant = len(github.request_log)
    avant = datetime.now(UTC)
    (issue,) = _worker(control, deps, github, jeton, monkeypatch, 1)
    github.fault = None
    assert issue.status == "rate_limited" and issue.retry_after_s == 60.0, issue
    assert len(github.request_log) - appels_avant == 1, "aucun appel GitHub après la limitation"
    limite = _etat_de(control, issue.job_id)
    assert (limite["status"], limite["attempts"], limite["pins"], limite["state"]) == (
        "queued", 0, 0, "NEEDS_REVIEW"), limite
    assert limite["next"] >= avant + timedelta(seconds=59), limite
    assert limite["error"].startswith("github_rate_limited kind=secondary wait_s=60"), limite
    assert "retry-after=60" in limite["error"] and VALID_TOKEN not in limite["error"]
    assert banc_batch._compter_dans_le_produit(product_pg, contenus) == (0, 0, 0)
    banc_dh._preparer(control, banc_dh._rendre_prioritaire, job_id=issue.job_id)

    # ── D. 403 APRÈS le pin, avant le produit : l'état réel de NSI terminale ──
    def _pins() -> int:
        return _requete(control, "SELECT count(*) FROM ingestion_control.publication_commit_pins")[0][0]

    github.fault = lambda chemin: (
        (403, {}, "Forbidden") if "/pulls/" in chemin and _pins() > 0 else None
    )
    (echec,) = _worker(control, deps, github, jeton, monkeypatch, 1)
    github.fault = None
    assert echec.job_id == issue.job_id and echec.status == "retried", echec
    assert "GitHub returned HTTP 403" in (echec.error or "") and "rate_limited" not in (echec.error or "")
    epingle = _etat_de(control, echec.job_id)
    assert (epingle["status"], epingle["attempts"], epingle["state"], epingle["pins"], epingle["promotions"]) == (
        "queued", 1, "RETRIEVAL_ELIGIBLE", 1, 2), epingle
    assert banc_batch._compter_dans_le_produit(product_pg, contenus)[1] == 0, "aucun placement produit"
    with psycopg.connect(app_dsn(control)) as conn:
        assert di.precondition_partielle(conn, perimetre)["pinned_awaiting_product"] == 1
    banc_dh._preparer(control, banc_dh._rendre_prioritaire, job_id=echec.job_id)

    # ── D/E. reprise : le job épinglé publie, puis le reste du périmètre ──
    # Une itération à la fois : le coût GitHub de chaque publication est
    # MESURÉ (il fonde la cadence de l'autorisation DI), jamais supposé.
    appels_par_publication = []
    reussis = []
    for _ in range(2):
        avant_appels = len(github.request_log)
        (publie,) = (i for i in _worker(control, deps, github, jeton, monkeypatch, 1) if i.worked)
        appels_par_publication.append(len(github.request_log) - avant_appels)
        reussis.append(publie)
    assert [i.status for i in reussis] == ["succeeded", "succeeded"], reussis
    assert reussis[0].job_id == echec.job_id
    print(f"DI_GITHUB_GET_PAR_PUBLICATION reprise_epinglee={appels_par_publication[0]} "
          f"publication_complete={appels_par_publication[1]}")
    assert appels_par_publication == [APPELS_GITHUB_PAR_REPRISE_EPINGLEE, APPELS_GITHUB_PAR_PUBLICATION]
    repris = _etat_de(control, echec.job_id)
    assert (repris["status"], repris["pins"], repris["promotions"]) == ("succeeded", 1, 2), repris
    apres = banc_batch._compter_dans_le_produit(product_pg, contenus)
    assert apres[1] == 2 and apres[0] == 2 and apres[2] > 0, apres
    reussis_avant = _jobs_par_collection(control)[PORTEE]

    # Rejeu : plus rien de réclamable dans le périmètre ; rien ne bouge.
    assert [i for i in _worker(control, deps, github, jeton, monkeypatch, 3) if i.worked] == []
    assert banc_batch._compter_dans_le_produit(product_pg, contenus) == apres
    assert _jobs_par_collection(control)[PORTEE] == reussis_avant, "aucune régression d'un job réussi"

    # ── F. les exclus : ni réclamés, ni retentés, ni reportés ──
    assert _jobs_par_collection(control)[EXCLUE] == exclus_avant
    assert _requete(control, """
        SELECT count(*) FROM ingestion_control.publication_commit_pins p
          JOIN ingestion_control.resources r ON r.resource_id = p.resource_id
         WHERE r.collection = %s""", (EXCLUE,))[0][0] == 0

    # ── G. fermeture : jamais tant que les exclus attendent ──
    with psycopg.connect(app_dsn(control)) as conn:
        fin = di.controle_partiel(conn, perimetre, empreinte_exclus=pre["excluded_jobs_sha256"])
    assert fin == {"published": 2, "excluded_pending": 2,
                   "excluded_jobs_sha256": pre["excluded_jobs_sha256"], "review_closure": "NOT_SAFE"}
    revue_dh = SimpleNamespace(release={"release_id": banc.release_id}, attendu={"attestations": 4})
    with psycopg.connect(app_dsn(control)) as conn, pytest.raises(dh.RecuperationRefusee) as refus:
        dh.controle_de_fermeture(conn, revue_dh)
    assert "2 ressource(s) pas encore RETRIEVAL_ELIGIBLE" in refus.value.ecarts
    assert "2 job(s) de publication encore en file ou en cours" in refus.value.ecarts

    # ── périmètre faux : refus nommés, rien n'est écrit ──
    identite = json.loads((tmp_path / "di-identite.json").read_text())
    avant_refus = _requete(control, "SELECT job_id, status, attempt_count, updated_at"
                           " FROM ingestion_control.jobs ORDER BY 1")
    for alteration, attendu in (
        ({"database": "ragdb_autre"}, "base 'ragdb', attendu 'ragdb_autre'"),
        ({"review": {**identite["review"], "pull_request": 7001}}, "attendu #7001@"),
        ({"excluded_collections": {"rag_nexus_inconnue": "x"}}, "absentes de la release attestée"),
        ({"expected": {**identite["expected"], "active_attestations": 5}}, "attendu 5"),
    ):
        chemin = tmp_path / "faux.json"
        chemin.write_text(json.dumps({**identite, **alteration}))
        with psycopg.connect(app_dsn(control)) as conn, pytest.raises(di.RepriseRefusee) as refus:
            di.precondition_partielle(conn, di.charger_perimetre(chemin))
        assert any(attendu in ecart for ecart in refus.value.ecarts), (alteration, refus.value.ecarts)
    assert _requete(control, "SELECT job_id, status, attempt_count, updated_at"
                    " FROM ingestion_control.jobs ORDER BY 1") == avant_refus

    # ── F, contre-épreuve : SANS liste d'autorisation, un exclu est consommé ──
    deps.claim_collections = None
    github.fault = lambda chemin: (403, {}, "Forbidden") if "/pulls/" in chemin else None
    (consomme,) = (i for i in _worker(control, deps, github, jeton, monkeypatch, 1) if i.worked)
    github.fault = None
    assert consomme.status == "retried" and _etat_de(control, consomme.job_id)["attempts"] == 1
    with psycopg.connect(app_dsn(control)) as conn, pytest.raises(di.RepriseRefusee) as detecte:
        di.controle_partiel(conn, perimetre, empreinte_exclus=pre["excluded_jobs_sha256"])
    assert any("jobs exclus modifiés" in ecart for ecart in detecte.value.ecarts), detecte.value.ecarts
