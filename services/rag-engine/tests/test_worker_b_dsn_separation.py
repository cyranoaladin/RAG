"""Worker B : la séparation des DSN vaut dans TOUS les environnements (lot CH4).

Ce refus vivait dans `_enforce_production_evidence`, donc en production
seulement. Un staging pouvait publier avec un DSN unique et effondrer la
séparation entre contrôle d'ingestion et base produit — précisément là où on
la qualifie. La garde est désormais appliquée avant toute distinction
d'environnement ; ces épreuves le prouvent dans les deux sens.
"""

from __future__ import annotations

import pytest

from ingestor.ingestion_worker import multilevel_publication_resume_cli as cli
from ingestor.ingestion_worker.runtime_authority import RuntimeAuthorityStartupError


def test_deux_dsn_identiques_sont_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    partage = "postgresql://x@127.0.0.1:5432/db"
    monkeypatch.setattr(cli, "get_ingestion_control_dsn", lambda: partage)
    with pytest.raises(RuntimeAuthorityStartupError, match="distinct"):
        cli._require_distinct_control_and_product_dsn(partage)


def test_deux_dsn_distincts_sont_admis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli, "get_ingestion_control_dsn", lambda: "postgresql://x@127.0.0.1:5432/control"
    )
    cli._require_distinct_control_and_product_dsn("postgresql://x@127.0.0.1:5432/ragdb")


def test_la_garde_est_appelee_hors_de_la_branche_production() -> None:
    """Sans cela, elle ne s'exécuterait qu'en production, comme avant."""
    from pathlib import Path

    source = Path(cli.__file__).read_text(encoding="utf-8")
    avant_production = source.split('if readiness.environment == "production":')[0]
    assert "_require_distinct_control_and_product_dsn(product_dsn)" in avant_production
