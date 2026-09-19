import json
import re
from pathlib import Path

import yaml

from analyzer_metrics import AnalyzerMetrics
from prometheus_client import generate_latest
from prometheus_client.parser import text_string_to_metric_families

REPO_ROOT = Path(__file__).parent.parent
PROMETHEUS_CONFIG = REPO_ROOT / "prometheus" / "prometheus.yml"
GRAFANA_DATASOURCE = REPO_ROOT / "grafana" / "provisioning" / "datasources" / "prometheus.yml"
GRAFANA_DASHBOARD_PROVIDER = REPO_ROOT / "grafana" / "provisioning" / "dashboards" / "dashboard.yml"
GRAFANA_DASHBOARD = REPO_ROOT / "grafana" / "dashboards" / "network-log-analyzer.json"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"

# Matches PromQL tokens shaped like our metric names (analyzer_*, log_*, logs_*).
# Deliberately narrow: it is not a full PromQL parser, just enough to catch a
# renamed/typo'd metric in the dashboard JSON.
METRIC_TOKEN = re.compile(r"\b(?:analyzer_|logs?_)[a-zA-Z0-9_]*\b")


def known_metric_names():
    """The real Prometheus sample names AnalyzerMetrics exposes right now
    (e.g. "analyzer_runs_total", "analyzer_processing_seconds_sum") — the exact
    strings a PromQL query would reference, unlike a metric family's base name."""
    text = generate_latest(AnalyzerMetrics().registry).decode()
    return {
        sample.name
        for family in text_string_to_metric_families(text)
        for sample in family.samples
    }


# Prometheus scrape config
def test_prometheus_config_is_valid_yaml():
    config = yaml.safe_load(PROMETHEUS_CONFIG.read_text())
    assert "scrape_configs" in config


def test_prometheus_scrapes_the_api_service():
    config = yaml.safe_load(PROMETHEUS_CONFIG.read_text())
    jobs = config["scrape_configs"]
    assert len(jobs) == 1

    job = jobs[0]
    assert job["metrics_path"] == "/metrics"
    assert job["static_configs"][0]["targets"] == ["api:8000"]


# Grafana provisioning
def test_grafana_datasource_points_at_the_prometheus_service():
    config = yaml.safe_load(GRAFANA_DATASOURCE.read_text())
    datasource = config["datasources"][0]

    assert datasource["type"] == "prometheus"
    assert datasource["url"] == "http://prometheus:9090"


def test_grafana_dashboard_provider_is_valid_yaml():
    config = yaml.safe_load(GRAFANA_DASHBOARD_PROVIDER.read_text())
    assert config["providers"][0]["type"] == "file"


# Grafana dashboard
def test_grafana_dashboard_is_valid_json():
    dashboard = json.loads(GRAFANA_DASHBOARD.read_text())
    assert dashboard["title"] == "Network Log Analyzer"
    assert len(dashboard["panels"]) > 0


def test_grafana_dashboard_only_queries_known_metrics():
    """Catches a renamed/typo'd metric before it silently breaks a panel."""
    dashboard = json.loads(GRAFANA_DASHBOARD.read_text())
    known = known_metric_names()

    exprs = [
        target["expr"]
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    ]
    tokens = {token for expr in exprs for token in METRIC_TOKEN.findall(expr)}
    assert tokens  # sanity: the dashboard actually queries some metric

    for token in tokens:
        assert token in known, f"dashboard references unknown metric: {token}"


# Docker Compose wiring
def test_compose_defines_prometheus_and_grafana_with_pinned_images():
    compose = yaml.safe_load(COMPOSE_FILE.read_text())
    services = compose["services"]

    for name in ("prometheus", "grafana"):
        assert name in services
        assert not services[name]["image"].endswith(":latest"), f"{name} image is not pinned"
