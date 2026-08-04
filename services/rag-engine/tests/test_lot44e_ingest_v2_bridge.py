"""LOT44e : pont best-effort /ingest/v2 -> job (aucun réseau, aucun Postgres réel).

Périmètre strict : preuve unitaire que ``best_effort_create_ingest_job``
ne lève **jamais**, quelle que soit la cause d'échec, et ne retourne un
identifiant de job que lorsque la création a réellement réussi. Le cas
nominal réel (écriture PostgreSQL) est couvert par le test d'intégration
(``tests/integration/test_lot44e_ingest_v2_bridge.py``), pas ici.
"""
from __future__ import annotations

from ingestor.ingestion_worker.ingest_v2_bridge import best_effort_create_ingest_job


def _call(**overrides: object) -> object:
    kwargs: dict[str, object] = {
        "collection": "rag_nexus_nsi_terminale_specialite",
        "source_label": "eduscol.education.fr",
        "source_uri": "https://eduscol.education.fr/nsi/algo",
        "rights": "public_allowed",
        "type_doc": "cours",
        "matiere": "nsi",
        "niveau": "terminale",
        "voie": "generale",
        "audience": ["tous"],
        "default_tenant": "libre_terminale",
        "default_candidat": "libre",
        "default_visibility": "internal",
        "default_school_year": "2026-2027",
        "default_programme_version": "BOEN_special_8_2019-07-25",
        "dedup_key": "f" * 64,
    }
    kwargs.update(overrides)
    return best_effort_create_ingest_job(**kwargs)  # type: ignore[arg-type]


class TestInvalidScopeNeverRaises:
    def test_invalid_niveau_returns_none_without_raising(self) -> None:
        assert _call(niveau="not_a_real_niveau_value") is None

    def test_invalid_voie_returns_none_without_raising(self) -> None:
        # "gen" est la valeur par défaut historique côté /ingest/v2 (ingest_v2.py),
        # mais ne correspond à aucune valeur de l'énumération Voie gouvernée —
        # exactement la divergence de vocabulaire documentée (ADR-0028).
        assert _call(voie="gen") is None

    def test_empty_audience_returns_none_without_raising(self) -> None:
        assert _call(audience=[]) is None


class TestUnreachableDatabaseNeverRaises:
    def test_unreachable_dsn_returns_none_without_raising(self, monkeypatch) -> None:  # noqa: ANN001
        monkeypatch.setenv(
            "PG_INGESTION_CONTROL_DSN",
            "host=127.0.0.1 port=1 dbname=nonexistent user=nobody connect_timeout=1",
        )
        assert _call() is None

    def test_missing_dsn_env_var_returns_none_without_raising(self, monkeypatch) -> None:  # noqa: ANN001
        monkeypatch.delenv("PG_INGESTION_CONTROL_DSN", raising=False)
        assert _call() is None
