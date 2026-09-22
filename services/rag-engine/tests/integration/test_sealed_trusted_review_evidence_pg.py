"""ADR-0058 sur PostgreSQL réel : la preuve scellée remplace la liveness.

Aucun mock de base, aucun mock de GitHub : un conteneur ``pgvector:pg16``
jetable est migré par le VRAI script de bootstrap, et les refus mesurés sont
de vrais refus — de contrainte PostgreSQL ou de la garde applicative.

Le fait central que ce fichier prouve : **une autorisation dont la preuve est
scellée reste utilisable après que sa pull request a été fusionnée**. C'est
précisément ce que l'ancien modèle refusait.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ENGINE_ROOT.parents[1]
BOOTSTRAP = ENGINE_ROOT / "infra/scripts/bootstrap_ingestion_control_schema.sh"

sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / "scripts/github"))

import trusted_human_review as adr0025  # noqa: E402
from _pg_authority import (  # noqa: E402
    PG_SUPERUSER,
    PG_SUPERUSER_PASSWORD,
    declared_schema_head,
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)
from nexus_contracts.trusted_review_evidence import (  # noqa: E402
    SEALED_TRUSTED_REVIEW_EVIDENCE_PROTOCOL,
    TRUSTED_REVIEW_CHALLENGE_PROTOCOL,
    SealedTrustedReviewEvidenceV1,
)

from ingestor.ingestion_control import scope_authority  # noqa: E402

pytestmark = [pytest.mark.integration, requires_docker]

REPO = "cyranoaladin/RAG"
BASE = "f66a04cb364191c53eb56c9a9e1208e9e386ae16"
HEAD = "44bf8360a5f5b272b0377835fd871099f817e955"
AUTEUR = "cyranoaladin"
RELECTEUR = "abenrhouma"

SCOPE_SQL = (
    "'libre_terminale', 'rag_nexus_dgemc_terminale_option', 'terminale', "
    "'generale', 'dgemc', 'libre', ARRAY['libre'], 'public', '2026-2027', "
    "'EDUSCOL_CORPUS_20260808'"
)


@pytest.fixture(scope="module")
def pg_container() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("sealed-review-evidence-015")


@pytest.fixture(scope="module")
def migrated(pg_container: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "PGHOST": pg_container["host"], "PGPORT": pg_container["port"],
        "PGUSER": PG_SUPERUSER, "PGPASSWORD": PG_SUPERUSER_PASSWORD,
        "PGDATABASE": pg_container["dbname"],
    })
    resultat = subprocess.run(
        [str(BOOTSTRAP)], cwd=ENGINE_ROOT, env=env,
        capture_output=True, text=True, check=False,
    )
    assert resultat.returncode == 0, resultat.stderr
    assert f"SCHEMA_HEAD={declared_schema_head()}" in resultat.stdout
    return pg_container


def _challenge(**overrides: Any) -> str:
    payload = {
        "repository": REPO, "pull_request": 241, "base_ref": "main",
        "base_sha": BASE, "head_sha": HEAD, "author": AUTEUR,
        "reviewer": RELECTEUR, "protocol": adr0025.PROTOCOL,
    }
    payload.update(overrides)
    return adr0025.build_challenge(payload)


def _evidence(authorization_id: str, **overrides: Any) -> SealedTrustedReviewEvidenceV1:
    champs: dict[str, Any] = {
        "protocol_version": SEALED_TRUSTED_REVIEW_EVIDENCE_PROTOCOL,
        "repository": REPO, "pull_request": 241,
        "pull_request_base_ref": "main",
        "pull_request_base_sha": BASE, "pull_request_head_sha": HEAD,
        "pull_request_author": AUTEUR,
        "authorization_id": authorization_id,
        "artifact_path": f"governance/authorizations/{authorization_id}.json",
        "artifact_sha256": "c" * 64, "artifact_blob_sha": "d" * 40,
        "reviewer": RELECTEUR, "review_id": 987654321,
        "review_node_id": "PRR_kwDOabcdef",
        "review_submitted_at": datetime.now(UTC) - timedelta(hours=1),
        "challenge_protocol": TRUSTED_REVIEW_CHALLENGE_PROTOCOL,
        "challenge": _challenge(),
        "head_pinned_status": "success",
        "head_pinned_context": "trusted-human-review/head-pinned",
        "recorded_at": datetime.now(UTC),
        "recorder_version": "authorize_scope_cli/ADR-0058",
    }
    champs.update(overrides)
    return SealedTrustedReviewEvidenceV1(**champs)


def _insert(
    conn: psycopg.Connection,
    authorization_id: str,
    *,
    evidence: SealedTrustedReviewEvidenceV1 | None,
    digest_override: str | None = None,
    valid_until: datetime | None = None,
) -> None:
    from psycopg.types.json import Jsonb

    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO ingestion_control.scope_authorizations (
                authorization_id, protocol_version, decision,
                tenant, collection, niveau, voie, matiere, candidat, audience,
                visibility, school_year, programme_version,
                manifest_digest, profile_id, profile_version, profile_fingerprint,
                allowed_domains, rights_categories, exclusions,
                pii_absence_attested, pii_absence_evidence,
                valid_from, valid_until,
                artifact_path, artifact_blob_sha, authorization_digest,
                evidence_repository, evidence_pull_request, evidence_base_sha,
                evidence_head_sha, evidence_review_id, evidence_reviewer,
                evidence_submitted_at, evidence_challenge,
                review_evidence, review_evidence_digest
            ) VALUES (
                %(id)s, 'LOT41A-V1', 'AUTHORIZE_INGESTION_SCOPE', {SCOPE_SQL},
                %(md)s, 'profile-gate', 'profile-gate-v2', %(fp)s,
                ARRAY['eduscol.education.gouv.fr'], ARRAY['officiel_public'],
                ARRAY[]::text[], true, 'pii-evidence',
                %(from)s, %(until)s,
                %(path)s, %(blob)s, %(digest)s,
                %(repo)s, %(pr)s, %(base)s, %(head)s, %(review)s, %(reviewer)s,
                %(submitted)s, %(challenge)s,
                %(evidence)s, %(evidence_digest)s
            )
            """,  # noqa: S608 - SCOPE_SQL est une constante litterale
            {
                "id": authorization_id, "md": "a" * 64, "fp": "b" * 64,
                "from": datetime.now(UTC) - timedelta(days=1),
                "until": valid_until or (datetime.now(UTC) + timedelta(days=30)),
                "path": f"governance/authorizations/{authorization_id}.json",
                "blob": "d" * 40, "digest": "c" * 64,
                "repo": REPO, "pr": 241, "base": BASE, "head": HEAD,
                "review": 987654321, "reviewer": RELECTEUR,
                "submitted": datetime.now(UTC) - timedelta(hours=1),
                "challenge": _challenge(),
                "evidence": Jsonb(evidence.canonical_document()) if evidence else None,
                "evidence_digest": (
                    digest_override
                    if digest_override is not None
                    else (evidence.digest() if evidence else None)
                ),
            },
        )
    conn.commit()


# ==========================================================================
# La migration elle-même
# ==========================================================================


def test_la_migration_015_est_appliquee(migrated: dict[str, str]) -> None:
    with psycopg.connect(superuser_dsn(migrated)) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='ingestion_control' "
            "AND table_name='scope_authorizations' "
            "AND column_name IN ('review_evidence','review_evidence_digest')"
        )
        colonnes = {ligne[0] for ligne in cur.fetchall()}
        cur.execute("SELECT to_regclass('ingestion_control.revoked_review_evidence')")
        table = cur.fetchone()
    assert colonnes == {"review_evidence", "review_evidence_digest"}
    assert table is not None and table[0] is not None


def test_une_preuve_sans_digest_est_refusee_par_la_base(
    migrated: dict[str, str]
) -> None:
    """Les deux colonnes vont ensemble ou pas du tout.

    L'UPDATE porte sur une ligne réellement présente : sur une table vide,
    il n'affecterait rien et ne prouverait rien."""
    from psycopg.types.json import Jsonb

    identifiant = "paired-columns-probe"
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        _insert(conn, identifiant, evidence=_evidence(identifiant))
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ingestion_control.scope_authorizations "
                    "SET review_evidence_digest = NULL WHERE authorization_id = %s",
                    (identifiant,),
                )
        conn.rollback()
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ingestion_control.scope_authorizations "
                    "SET review_evidence = NULL WHERE authorization_id = %s",
                    (identifiant,),
                )
        conn.rollback()
        # Et une preuve vide n'est pas une preuve.
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ingestion_control.scope_authorizations "
                    "SET review_evidence = %s WHERE authorization_id = %s",
                    (Jsonb({}), identifiant),
                )
        conn.rollback()


def test_une_preuve_d_un_autre_protocole_est_refusee_par_la_base(
    migrated: dict[str, str]
) -> None:
    from psycopg.types.json import Jsonb

    identifiant = "protocol-probe"
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        _insert(conn, identifiant, evidence=_evidence(identifiant))
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE ingestion_control.scope_authorizations "
                    "SET review_evidence = %s WHERE authorization_id = %s",
                    (Jsonb({"protocol_version": "AUTRE-PROTOCOLE"}), identifiant),
                )
        conn.rollback()


# ==========================================================================
# L'usage : la preuve scellée, pas l'état de la PR
# ==========================================================================


def _verifier(migrated: dict[str, str], authorization_id: str) -> Any:
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        return scope_authority.verify_scope_authorization(
            conn, authorization_id=authorization_id
        )


def test_11_une_preuve_scellee_reste_valide_apres_fusion_de_la_pr(
    migrated: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Le fait central d'ADR-0058.

    La PR #241 est fusionnée depuis longtemps. L'ancien modele repondait
    ``pull_request_not_open``. Ici, l'autorisation est acceptee — et aucun
    appel reseau n'a lieu."""
    identifiant = "sealed-still-valid-after-merge"
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        _insert(conn, identifiant, evidence=_evidence(identifiant))

    appels: list[str] = []
    monkeypatch.setattr(
        scope_authority, "verify_review",
        lambda **kwargs: appels.append("reseau") or (_ for _ in ()).throw(
            AssertionError("aucune verification live ne doit avoir lieu")
        ),
    )
    monkeypatch.setattr(
        scope_authority, "_verify_reviewed_artifact", lambda row, live: None
    )
    monkeypatch.setattr(
        scope_authority, "_require_row_matches_artifact", lambda row, artifact: None
    )
    monkeypatch.setattr(
        scope_authority, "load_trusted_reviewers", lambda: (RELECTEUR,)
    )
    monkeypatch.setattr(
        scope_authority, "_scope_from_row",
        scope_authority._scope_from_row,
    )
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        resultat = scope_authority._verify_sealed_review(
            conn, scope_authority._load_row(conn, authorization_id=identifiant)
        )
    assert resultat.approved is True
    assert resultat.reason == "sealed_trusted_review_evidence"
    assert appels == []


def test_9_une_autorisation_sans_preuve_scellee_est_refusee(
    migrated: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Les lignes de l'ancien modele ne sont pas tolerees."""
    identifiant = "legacy-without-sealed-evidence"
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        _insert(conn, identifiant, evidence=None)
    monkeypatch.setattr(scope_authority, "load_trusted_reviewers", lambda: (RELECTEUR,))
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        row = scope_authority._load_row(conn, authorization_id=identifiant)
        with pytest.raises(
            scope_authority.ScopeAuthorizationDeniedError,
            match="carries no sealed trusted review evidence",
        ):
            scope_authority._verify_sealed_review(conn, row)


def test_10_une_preuve_incomplete_est_refusee(
    migrated: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from psycopg.types.json import Jsonb

    identifiant = "sealed-but-incomplete"
    evidence = _evidence(identifiant)
    ampute = evidence.canonical_document()
    del ampute["review_node_id"]
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        _insert(conn, identifiant, evidence=evidence)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_control.scope_authorizations "
                "SET review_evidence = %s WHERE authorization_id = %s",
                (Jsonb(ampute), identifiant),
            )
        conn.commit()
    monkeypatch.setattr(scope_authority, "load_trusted_reviewers", lambda: (RELECTEUR,))
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        row = scope_authority._load_row(conn, authorization_id=identifiant)
        with pytest.raises(scope_authority.ScopeAuthorizationDeniedError):
            scope_authority._verify_sealed_review(conn, row)


def test_le_digest_enregistre_doit_etre_celui_de_la_preuve(
    migrated: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    identifiant = "sealed-digest-mismatch"
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        _insert(
            conn, identifiant,
            evidence=_evidence(identifiant), digest_override="f" * 64,
        )
    monkeypatch.setattr(scope_authority, "load_trusted_reviewers", lambda: (RELECTEUR,))
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        row = scope_authority._load_row(conn, authorization_id=identifiant)
        with pytest.raises(
            scope_authority.ScopeAuthorizationDeniedError, match="digest mismatch"
        ):
            scope_authority._verify_sealed_review(conn, row)


def test_7_un_relecteur_hors_allowlist_est_refuse(
    migrated: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """La part vivante : retirer l'identite eteint ses signatures passees."""
    identifiant = "sealed-reviewer-removed"
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        _insert(conn, identifiant, evidence=_evidence(identifiant))
    monkeypatch.setattr(
        scope_authority, "load_trusted_reviewers", lambda: ("quelquun-dautre",)
    )
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        row = scope_authority._load_row(conn, authorization_id=identifiant)
        with pytest.raises(
            scope_authority.ScopeAuthorizationDeniedError, match="not in the governed"
        ):
            scope_authority._verify_sealed_review(conn, row)


def test_6_un_challenge_altere_est_refuse(
    migrated: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from psycopg.types.json import Jsonb

    identifiant = "sealed-challenge-tampered"
    evidence = _evidence(identifiant)
    altere = evidence.canonical_document()
    altere["challenge"] = f"{TRUSTED_REVIEW_CHALLENGE_PROTOCOL}:{'0' * 64}"
    digest = hashlib.sha256(
        (json.dumps(altere, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
    ).hexdigest()
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        _insert(conn, identifiant, evidence=evidence)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_control.scope_authorizations "
                "SET review_evidence = %s, review_evidence_digest = %s "
                "WHERE authorization_id = %s",
                (Jsonb(altere), digest, identifiant),
            )
        conn.commit()
    monkeypatch.setattr(scope_authority, "load_trusted_reviewers", lambda: (RELECTEUR,))
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        row = scope_authority._load_row(conn, authorization_id=identifiant)
        with pytest.raises(
            scope_authority.ScopeAuthorizationDeniedError, match="does not derive"
        ):
            scope_authority._verify_sealed_review(conn, row)


def test_12_une_preuve_revoquee_est_refusee(
    migrated: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """La contrepartie du scellement : ce que la liveness detectait par
    accident, la revocation doit le faire expres."""
    identifiant = "sealed-then-revoked"
    evidence = _evidence(identifiant)
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        _insert(conn, identifiant, evidence=evidence)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_control.revoked_review_evidence (
                    review_evidence_digest, revoked_by, reason,
                    evidence_repository, evidence_pull_request, evidence_head_sha,
                    evidence_reviewer, evidence_challenge
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    evidence.digest(), RELECTEUR, "revue retiree hors modele",
                    REPO, 999, HEAD, RELECTEUR, _challenge(),
                ),
            )
        conn.commit()
    monkeypatch.setattr(scope_authority, "load_trusted_reviewers", lambda: (RELECTEUR,))
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        row = scope_authority._load_row(conn, authorization_id=identifiant)
        with pytest.raises(
            scope_authority.ScopeAuthorizationDeniedError, match="was revoked"
        ):
            scope_authority._verify_sealed_review(conn, row)


def test_14_un_authorization_id_inconnu_est_refuse(migrated: dict[str, str]) -> None:
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        with pytest.raises(
            scope_authority.ScopeAuthorizationDeniedError, match="no scope_authorizations row"
        ):
            scope_authority._load_row(conn, authorization_id="jamais-enregistre")


def test_une_divergence_entre_preuve_et_ligne_est_refusee(
    migrated: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    identifiant = "sealed-disagrees-with-row"
    evidence = _evidence("un-autre-identifiant")
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        _insert(conn, identifiant, evidence=evidence)
    monkeypatch.setattr(scope_authority, "load_trusted_reviewers", lambda: (RELECTEUR,))
    with psycopg.connect(superuser_dsn(migrated)) as conn:
        row = scope_authority._load_row(conn, authorization_id=identifiant)
        with pytest.raises(
            scope_authority.ScopeAuthorizationDeniedError, match="disagrees"
        ):
            scope_authority._verify_sealed_review(conn, row)
