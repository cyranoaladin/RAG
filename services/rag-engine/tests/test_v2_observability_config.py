"""Configuration d'observabilité du runtime v2 (P0-L6A).

`rules/rag-alerts.yml` vise les jobs et les métriques du moteur A. Chargé sous
le runtime v2, il produirait des règles qui ne peuvent jamais se déclencher :
une supervision verte qui n'observe rien. Ces tests lient les règles chargées à
la surface réellement exposée, pour que cette dérive redevienne impossible.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from src.ingestor import metrics as ingest_metrics

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
INFRA_ROOT = REPOSITORY_ROOT / "services" / "rag-engine" / "infra"
PROMETHEUS_CONFIG = INFRA_ROOT / "prometheus" / "prometheus.v2.yml"
V2_RULES = INFRA_ROOT / "prometheus" / "rules" / "rag-engine-v2.rules.yml"
LEGACY_RULES = INFRA_ROOT / "prometheus" / "rules" / "rag-alerts.yml"
ALERTMANAGER_CONFIG = INFRA_ROOT / "alertmanager" / "alertmanager.yml"
COMPOSE = INFRA_ROOT / "docker-compose.v2.yml"

#: Un sélecteur PromQL est un nom suivi d'un filtre de labels ou d'une fenêtre.
#: Les fonctions (`rate(`, `sum(`) sont exclues par construction.
SELECTOR = re.compile(r"\b([a-zA-Z_:][a-zA-Z0-9_:]*)\s*[{\[]")
COUNTER_SUFFIXES = ("", "_total", "_created", "_bucket", "_count", "_sum")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _exposed_series() -> set[str]:
    """Tous les noms de séries que le registre du runtime peut réellement
    produire, plus `up`, synthétisé par Prometheus pour chaque cible."""
    names = {"up"}
    for family in ingest_metrics.REGISTRY.collect():
        for suffix in COUNTER_SUFFIXES:
            names.add(f"{family.name}{suffix}")
        for sample in family.samples:
            names.add(sample.name)
    return names


def _rule_expressions(path: Path) -> list[tuple[str, str]]:
    document = _load(path)
    return [
        (rule.get("alert", "<unnamed>"), str(rule["expr"]))
        for group in document["groups"]
        for rule in group["rules"]
    ]


def test_prometheus_loads_the_versioned_rules_and_reaches_alertmanager() -> None:
    config = _load(PROMETHEUS_CONFIG)

    assert config.get("rule_files"), "aucune règle chargée : rien ne s'évalue"
    assert "/etc/prometheus/rules/rag-engine-v2.rules.yml" in config["rule_files"]

    alertmanagers = config["alerting"]["alertmanagers"]
    targets = [
        target
        for entry in alertmanagers
        for static in entry["static_configs"]
        for target in static["targets"]
    ]
    assert targets == ["alertmanager:9093"], targets


def test_every_alert_cites_only_series_the_runtime_actually_exposes() -> None:
    exposed = _exposed_series()
    for alert_name, expression in _rule_expressions(V2_RULES):
        for series in set(SELECTOR.findall(expression)):
            assert series in exposed, f"{alert_name} cites the absent series {series}"


def test_every_alert_targets_the_declared_scrape_job() -> None:
    config = _load(PROMETHEUS_CONFIG)
    declared_jobs = {scrape["job_name"] for scrape in config["scrape_configs"]}

    for alert_name, expression in _rule_expressions(V2_RULES):
        for job in re.findall(r'job\s*=\s*"([^"]+)"', expression):
            assert job in declared_jobs, f"{alert_name} targets the unknown job {job}"


def test_the_moteur_a_rule_file_is_deliberately_not_loaded() -> None:
    """Exclusion volontaire, pas oubli — et prouvée par sa raison d'être."""
    config = _load(PROMETHEUS_CONFIG)
    assert not any("rag-alerts" in entry for entry in config["rule_files"])

    exposed = _exposed_series()
    legacy_series = {
        series
        for _alert, expression in _rule_expressions(LEGACY_RULES)
        for series in SELECTOR.findall(expression)
    }
    assert legacy_series - exposed, (
        "rag-alerts.yml ne cite plus aucune série absente : "
        "réexaminer son exclusion plutôt que de conserver ce test"
    )


def test_alert_rules_are_mounted_read_only_into_prometheus() -> None:
    """Une règle versionnée mais non montée ne s'évalue pas davantage."""
    compose = _load(COMPOSE)
    mounts = compose["services"]["prometheus"]["volumes"]
    assert any(
        mount.endswith(":/etc/prometheus/rules/rag-engine-v2.rules.yml:ro")
        for mount in mounts
    ), mounts


def test_alertmanager_is_a_service_of_the_canonical_topology() -> None:
    compose = _load(COMPOSE)
    assert "alertmanager" in compose["services"], sorted(compose["services"])

    alertmanager = compose["services"]["alertmanager"]
    assert "@sha256:" in alertmanager["image"], "image non épinglée par digest"
    assert alertmanager["security_opt"] == ["no-new-privileges:true"]
    assert all(
        published.startswith("127.0.0.1:") for published in alertmanager["ports"]
    ), alertmanager["ports"]


def test_prometheus_does_not_wait_for_a_healthy_engine_to_start() -> None:
    """Attendre le moteur rendrait `RagEngineV2Down` inobservable quand elle
    compte : le moteur est fail-closed et peut refuser de démarrer."""
    compose = _load(COMPOSE)
    assert "ingestor" not in compose["services"]["prometheus"].get("depends_on", {})


def test_alertmanager_routes_every_alert_to_a_declared_receiver() -> None:
    config = _load(ALERTMANAGER_CONFIG)
    declared = {receiver["name"] for receiver in config["receivers"]}

    route = config["route"]
    assert route["receiver"] in declared
    for nested in route.get("routes", []):
        assert nested["receiver"] in declared


@pytest.mark.parametrize(
    "severity", ["critical", "warning"]
)
def test_every_alert_carries_a_severity_a_service_and_a_runbook(
    severity: str,
) -> None:
    document = _load(V2_RULES)
    rules = [rule for group in document["groups"] for rule in group["rules"]]
    assert any(rule["labels"]["severity"] == severity for rule in rules)

    for rule in rules:
        assert rule["labels"]["service"] == "rag-engine-v2", rule["alert"]
        assert rule["labels"]["severity"] in {"critical", "warning"}, rule["alert"]
        assert rule["annotations"]["runbook_url"].startswith("https://"), rule["alert"]
        assert rule["annotations"]["summary"], rule["alert"]
