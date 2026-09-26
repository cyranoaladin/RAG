"""Lot DI — Worker B face à une limitation de débit GitHub.

Incident réel : 390 jobs ont échoué sur ``GitHub returned HTTP 403 for
repos/cyranoaladin/RAG/pulls/262`` ; chacun a consommé une tentative, et le
worker a continué d'appeler GitHub au même rythme pendant la limitation.

Contrat éprouvé ici :

- une limitation reste un REFUS : rien n'est publié, rien n'est complété ;
- le job est rendu à la file SANS tentative consommée, pas avant le délai
  imposé (``Retry-After``, ``x-ratelimit-reset``, sinon une minute) ;
- tout autre refus — 403 de droits, sujet non gouverné — consomme une
  tentative exactement comme avant ;
- la boucle suspend TOUTE réclamation pendant l'attente, s'arrête avec le
  code 75 au-delà de ses bornes, et respecte la cadence minimale ;
- la liste d'autorisation de collections atteint ``claim_job`` telle quelle.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

import ingestor.ingestion_worker.multilevel_publication_resume_cli as cli
import ingestor.ingestion_worker.publication_resume as resume_module
from ingestor.embedding_provider import CallableEmbeddingProvider
from ingestor.ingestion_control.github_authority import (
    GitHubAuthorityError,
    GitHubRateLimitedError,
    GitHubResponseDiagnostics,
)
from ingestor.ingestion_control.jobs import JobClaim
from ingestor.ingestion_control.publication_attestation import (
    PublicationAttestationInvalidError,
)
from ingestor.ingestion_worker.publication_resume import (
    RATE_LIMIT_FLOOR_S,
    PublicationResumeDeps,
    PublicationResumeOutcome,
    github_rate_limit_in_chain,
    run_publication_resume_iteration,
)
from ingestor.multilevel_verified_placement import MultilevelPlacementResolutionError


class _Conn:
    def __init__(self) -> None:
        self.events: list[str] = []

    def commit(self) -> None:
        self.events.append("commit")

    def rollback(self) -> None:
        self.events.append("rollback")


def _deps(**extra: Any) -> PublicationResumeDeps:
    return PublicationResumeDeps(
        owner="di-test",
        product_dsn="postgresql://product",
        artifact_reader=lambda **_k: b"unused",
        extract_text=lambda _c: "unused",
        embedding_provider=CallableEmbeddingProvider(encoder=lambda _chunks: ()),
        **extra,
    )


def _claim() -> JobClaim:
    return JobClaim(
        job_id=uuid4(), run_id=uuid4(), resource_id=uuid4(), job_type="publication_resume",
        payload={}, lease_token=uuid4(),
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=5), attempt_count=1,
    )


def _limitation(retry_after_s: float | None, kind: str = "secondary") -> GitHubRateLimitedError:
    return GitHubRateLimitedError(
        "GitHub returned HTTP 403 for repos/cyranoaladin/RAG/pulls/262 — failing closed",
        kind=kind,
        retry_after_s=retry_after_s,
        diagnostics=GitHubResponseDiagnostics(status=403, headers=(), message=None),
    )


def _refus_d_attestation(cause: Exception) -> PublicationAttestationInvalidError:
    """Exactement la forme que prend l'incident : l'erreur de transport
    devient un refus d'attestation (``raise … from exc``)."""
    try:
        raise cause
    except GitHubAuthorityError as exc:
        try:
            raise PublicationAttestationInvalidError(
                f"attestation x invalidated: human_review transport failure: {exc}"
            ) from exc
        except PublicationAttestationInvalidError as wrapped:
            return wrapped


@pytest.fixture
def journal(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    appels: dict[str, list[Any]] = {"claim": [], "retry": [], "defer": [], "complete": []}
    claim = _claim()
    monkeypatch.setattr(
        resume_module, "claim_job", lambda _c, **k: appels["claim"].append(k) or claim
    )
    monkeypatch.setattr(
        resume_module, "record_job_retry", lambda _c, **k: appels["retry"].append(k)
    )
    monkeypatch.setattr(
        resume_module, "defer_job_for_external_throttle",
        lambda _c, **k: appels["defer"].append(k),
    )
    monkeypatch.setattr(
        resume_module, "complete_job", lambda _c, **k: appels["complete"].append(k)
    )
    appels["claimed"] = [claim]
    return appels


def _echec(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    def resume(*_a: object, **_k: object) -> None:
        raise exc

    monkeypatch.setattr(resume_module, "resume_publication", resume)


@pytest.mark.parametrize("retry_after_s, attendu", [(120.0, 120.0), (5.0, RATE_LIMIT_FLOOR_S), (None, RATE_LIMIT_FLOOR_S)])
def test_une_limitation_differe_le_job_sans_consommer_de_tentative(
    monkeypatch, journal, retry_after_s, attendu
) -> None:
    _echec(monkeypatch, _refus_d_attestation(_limitation(retry_after_s)))
    avant = datetime.now(UTC)
    issue = run_publication_resume_iteration(_Conn(), deps=_deps())
    assert (issue.status, issue.worked, issue.retry_after_s) == ("rate_limited", True, attendu)
    assert journal["retry"] == [], "aucune tentative consommée"
    assert journal["complete"] == [], "rien n'est complété"
    (report,) = journal["defer"]
    claim = journal["claimed"][0]
    assert (report["job_id"], report["lease_token"]) == (claim.job_id, claim.lease_token)
    assert report["not_before"] >= avant + timedelta(seconds=attendu - 1)
    assert report["reason"].startswith("github_rate_limited kind=secondary")
    assert "pulls/262" in report["reason"]


def test_une_limitation_du_quota_primaire_est_nommee(monkeypatch, journal) -> None:
    _echec(monkeypatch, _refus_d_attestation(_limitation(900.0, kind="primary")))
    issue = run_publication_resume_iteration(_Conn(), deps=_deps())
    assert issue.retry_after_s == 900.0
    assert "kind=primary" in journal["defer"][0]["reason"]


@pytest.mark.parametrize(
    "exc",
    [
        _refus_d_attestation(GitHubAuthorityError(
            "GitHub returned HTTP 403 for repos/x/pulls/1 — failing closed "
            "[message='Resource not accessible by personal access token']"
        )),
        MultilevelPlacementResolutionError("external subject 'hggsp' is not governed"),
        PublicationAttestationInvalidError("human_review is no longer approved (reason=pull_request_not_open)"),
    ],
    ids=["403-droits", "sujet-non-gouverne", "revue-fermee"],
)
def test_tout_autre_refus_consomme_une_tentative_comme_avant(monkeypatch, journal, exc) -> None:
    _echec(monkeypatch, exc)
    issue = run_publication_resume_iteration(_Conn(), deps=_deps())
    assert issue.status == "retried"
    assert journal["defer"] == []
    assert len(journal["retry"]) == 1


def test_la_cause_est_cherchee_dans_la_chaine_jamais_dans_le_texte() -> None:
    assert github_rate_limit_in_chain(RuntimeError("secondary rate limit")) is None
    limitation = _limitation(30.0)
    assert github_rate_limit_in_chain(_refus_d_attestation(limitation)) is limitation
    boucle = RuntimeError("a")
    boucle.__cause__ = RuntimeError("b")
    boucle.__cause__.__cause__ = boucle
    assert github_rate_limit_in_chain(boucle) is None


def test_la_liste_de_collections_atteint_claim_job(monkeypatch, journal) -> None:
    monkeypatch.setattr(resume_module, "resume_publication", lambda *_a, **_k: PublicationResumeOutcome(
        worked=True, job_id=journal["claimed"][0].job_id, status="succeeded", error=None))
    scope = ("rag_nexus_nsi_terminale_specialite", "rag_nexus_svt_premiere_specialite")
    run_publication_resume_iteration(_Conn(), deps=_deps(claim_collections=scope))
    run_publication_resume_iteration(_Conn(), deps=_deps())
    assert [appel["collections"] for appel in journal["claim"]] == [scope, None]


# ── boucle du CLI ──────────────────────────────────────────────────────────


class _Horloge:
    def __init__(self) -> None:
        self.t = 1000.0
        self.pauses: list[float] = []

    def monotonic(self) -> float:
        return self.t

    def sleep(self, secondes: float) -> None:
        self.pauses.append(round(secondes, 3))
        self.t += secondes


def _args(**valeurs: Any) -> argparse.Namespace:
    base = dict(
        min_job_interval_s=0.0, rate_limit_max_wait_s=900.0, max_consecutive_rate_limits=3,
        heartbeat_file=None, once=False, poll_interval_s=5.0, max_idle_polls=None,
    )
    return argparse.Namespace(**{**base, **valeurs})


def _issue(status: str, retry_after_s: float | None = None) -> PublicationResumeOutcome:
    return PublicationResumeOutcome(
        worked=True, job_id=UUID(int=len(status)), status=status, error=None,
        retry_after_s=retry_after_s,
    )


def _boucle(monkeypatch, issues: list[PublicationResumeOutcome], **args: Any) -> tuple[int, _Horloge, int]:
    monkeypatch.setattr(cli, "reap_expired_job_leases", lambda _c: [])
    horloge = _Horloge()
    restantes = list(issues)
    appels = []

    def iterer(_conn: object, *, deps: object) -> PublicationResumeOutcome:
        appels.append(horloge.t)
        return restantes.pop(0)

    code = cli._run_worker_loop(
        _Conn(), deps=_deps(), args=_args(**args), max_iterations=len(issues),
        iterate=iterer, sleep=horloge.sleep, monotonic=horloge.monotonic,
    )
    return code, horloge, len(appels)


def test_la_boucle_suspend_toute_reclamation_pendant_la_limitation(monkeypatch) -> None:
    code, horloge, appels = _boucle(
        monkeypatch, [_issue("succeeded"), _issue("rate_limited", 60.0), _issue("succeeded")]
    )
    assert (code, appels) == (0, 3)
    assert horloge.pauses == [60.0]


def test_la_boucle_s_arrete_apres_trop_de_limitations_consecutives(monkeypatch, capsys) -> None:
    issues = [_issue("rate_limited", 60.0)] * 3 + [_issue("succeeded")]
    code, horloge, appels = _boucle(monkeypatch, issues)
    assert (code, appels) == (cli.EXIT_RATE_LIMITED, 3)
    assert horloge.pauses == [60.0, 60.0], "aucune attente après la décision d'arrêt"
    assert "RATE_LIMITED_STOP" in capsys.readouterr().err


def test_une_attente_au_dela_de_la_borne_arrete_sans_dormir(monkeypatch) -> None:
    code, horloge, appels = _boucle(
        monkeypatch, [_issue("rate_limited", 3600.0), _issue("succeeded")], rate_limit_max_wait_s=900.0
    )
    assert (code, appels, horloge.pauses) == (cli.EXIT_RATE_LIMITED, 1, [])


def test_un_succes_remet_le_compteur_de_limitations_a_zero(monkeypatch) -> None:
    issues = [_issue("rate_limited", 60.0), _issue("rate_limited", 60.0), _issue("succeeded"),
              _issue("rate_limited", 60.0), _issue("rate_limited", 60.0), _issue("succeeded")]
    code, _horloge, appels = _boucle(monkeypatch, issues)
    assert (code, appels) == (0, 6)


def test_la_cadence_minimale_espace_les_reclamations(monkeypatch) -> None:
    code, horloge, appels = _boucle(
        monkeypatch, [_issue("succeeded")] * 3, min_job_interval_s=40.0
    )
    assert (code, appels) == (0, 3)
    assert horloge.pauses == [40.0, 40.0]


def test_sans_option_la_boucle_garde_son_comportement_historique(monkeypatch) -> None:
    code, horloge, appels = _boucle(monkeypatch, [_issue("succeeded"), _issue("retried")])
    assert (code, appels, horloge.pauses) == (0, 2, [])


def test_le_cli_expose_les_options_du_lot_di() -> None:
    args = cli._build_arg_parser().parse_args([
        "--profiles-dir", "p", "--artifact-store-dir", "a", "--owner", "o", "--expected-role", "r",
        "--embedding-artifact-root", "e", "--embedding-inventory-sha256", "0" * 64,
        *[x for c in ("c1", "c2") for x in ("--collection", c)],
        "--min-job-interval-s", "40", "--rate-limit-max-wait-s", "600",
        "--max-consecutive-rate-limits", "2",
        *[x for opt in cli._build_arg_parser()._actions if opt.required and opt.dest not in {
            "profiles_dir", "artifact_store_dir", "owner", "expected_role",
            "embedding_artifact_root", "embedding_inventory_sha256"}
          for x in (opt.option_strings[0], "0" * 64)],
    ])
    assert (args.collection, args.min_job_interval_s, args.rate_limit_max_wait_s,
            args.max_consecutive_rate_limits) == (["c1", "c2"], 40.0, 600.0, 2)


def _vide() -> PublicationResumeOutcome:
    return PublicationResumeOutcome(worked=False, job_id=None, status=None, error=None)


def test_la_boucle_s_arrete_quand_la_file_du_perimetre_reste_vide(monkeypatch, capsys) -> None:
    issues = [_issue("succeeded"), _vide(), _issue("retried"), _vide(), _vide(), _vide(), _issue("succeeded")]
    code, horloge, appels = _boucle(monkeypatch, issues, max_idle_polls=3)
    assert (code, appels) == (0, 6), "un job trouvé remet le compte d'attente à zéro"
    assert horloge.pauses == [5.0, 5.0, 5.0], "attente entre deux réclamations vides, pas après l'arrêt"
    assert "IDLE_STOP idle_polls=3" in capsys.readouterr().out


def test_sans_borne_d_attente_la_boucle_continue_jusqu_a_max_iterations(monkeypatch) -> None:
    code, _horloge, appels = _boucle(monkeypatch, [_vide()] * 4)
    assert (code, appels) == (0, 4)
