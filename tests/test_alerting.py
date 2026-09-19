import re
from pathlib import Path

import yaml

from analyzer_metrics import AnalyzerMetrics
from prometheus_client import generate_latest
from prometheus_client.parser import text_string_to_metric_families

REPO_ROOT = Path(__file__).parent.parent
PROMETHEUS_CONFIG = REPO_ROOT / "prometheus" / "prometheus.yml"
ALERTS_FILE = REPO_ROOT / "prometheus" / "alerts.yml"
ALERTMANAGER_CONFIG = REPO_ROOT / "alertmanager" / "alertmanager.yml"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"

EXPECTED_ALERT_NAMES = {
    "HighErrorRate",
    "AnalyzerNotRunningRecently",
    "ParseErrorsDetected",
    "CriticalLogEventsDetected",
}

# Same narrow, non-parser token match used for the Grafana dashboard check:
# catches a renamed/typo'd metric in an alert's PromQL expression.
METRIC_TOKEN = re.compile(r"\b(?:analyzer_|logs?_)[a-zA-Z0-9_]*\b")


def known_metric_names():
    text = generate_latest(AnalyzerMetrics().registry).decode()
    return {
        sample.name
        for family in text_string_to_metric_families(text)
        for sample in family.samples
    }


# Alerting rules
def test_alerts_file_is_valid_yaml_with_the_expected_group():
    config = yaml.safe_load(ALERTS_FILE.read_text())
    groups = config["groups"]
    assert len(groups) == 1
    assert groups[0]["name"] == "network-log-analyzer"


def test_alert_rules_have_the_expected_names():
    config = yaml.safe_load(ALERTS_FILE.read_text())
    names = {rule["alert"] for rule in config["groups"][0]["rules"]}
    assert names == EXPECTED_ALERT_NAMES


def test_every_alert_rule_has_a_severity_label_and_annotations():
    config = yaml.safe_load(ALERTS_FILE.read_text())
    for rule in config["groups"][0]["rules"]:
        assert rule["labels"]["severity"] in ("warning", "critical")
        assert "summary" in rule["annotations"]
        assert "description" in rule["annotations"]


def test_alert_rules_only_reference_known_metrics():
    """Catches a renamed/typo'd metric before an alert silently stops firing."""
    config = yaml.safe_load(ALERTS_FILE.read_text())
    known = known_metric_names()

    exprs = [rule["expr"] for rule in config["groups"][0]["rules"]]
    tokens = {token for expr in exprs for token in METRIC_TOKEN.findall(expr)}
    assert tokens  # sanity: the rules actually reference some metric

    for token in tokens:
        assert token in known, f"alert rule references unknown metric: {token}"


# Prometheus wiring to Alertmanager
def test_prometheus_config_loads_the_alert_rules_file():
    config = yaml.safe_load(PROMETHEUS_CONFIG.read_text())
    assert "alerts.yml" in config["rule_files"]


def test_prometheus_config_points_at_the_alertmanager_service():
    config = yaml.safe_load(PROMETHEUS_CONFIG.read_text())
    targets = config["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"]
    assert targets == ["alertmanager:9093"]


# Alertmanager config
def test_alertmanager_config_is_valid_yaml_with_a_route_and_receiver():
    config = yaml.safe_load(ALERTMANAGER_CONFIG.read_text())
    assert config["route"]["receiver"] == "default"
    assert config["receivers"][0]["name"] == "default"


def test_alertmanager_config_ships_no_real_notification_channel():
    """Enforces "no real notification credentials" as an automated check,
    not just a promise: the shipped receiver must have no integration
    configured (no slack_configs/webhook_configs/email_configs/etc.)."""
    config = yaml.safe_load(ALERTMANAGER_CONFIG.read_text())
    receiver = config["receivers"][0]
    assert set(receiver.keys()) == {"name"}


# Docker Compose wiring
def test_compose_defines_alertmanager_with_a_pinned_image():
    compose = yaml.safe_load(COMPOSE_FILE.read_text())
    services = compose["services"]

    assert "alertmanager" in services
    assert not services["alertmanager"]["image"].endswith(":latest")


def test_compose_prometheus_mounts_the_alert_rules_file():
    compose = yaml.safe_load(COMPOSE_FILE.read_text())
    volumes = compose["services"]["prometheus"]["volumes"]
    assert any("alerts.yml" in volume for volume in volumes)
