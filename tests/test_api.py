import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

import api


@pytest.fixture(autouse=True)
def reports_dir(tmp_path, monkeypatch):
    """Point the API's default report paths at a temp folder.

    autouse, and must run before the `client` fixture below: it patches the
    built-in defaults that the app's lifespan reads when TestClient starts it up.
    Pytest instantiates autouse fixtures before non-autouse ones in the same
    scope, so this is safe regardless of parameter order.
    """
    csv_path = tmp_path / "report.csv"
    html_path = tmp_path / "report.html"
    monkeypatch.setitem(api.log_analyzer.DEFAULT_CONFIG["reports"], "csv_output", str(csv_path))
    monkeypatch.setitem(api.log_analyzer.DEFAULT_CONFIG["reports"], "html_output", str(html_path))
    return {"csv": csv_path, "html": html_path}


@pytest.fixture
def client():
    with TestClient(api.app) as client:
        yield client


def read_sample(text, name):
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.name == name:
                return sample.value
    return None


# Health
def test_health_returns_ok(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# Analyze
def test_analyze_returns_summary(client, sample_log_path, reports_dir):
    response = client.post("/analyze", json={"log_path": str(sample_log_path)})
    assert response.status_code == 200

    body = response.json()
    assert body["lines_read"] == 8
    assert body["summary"]["total"] == 8
    assert body["summary"]["counts"]["ERROR"] == 4
    assert body["csv_report"] == str(reports_dir["csv"])
    assert body["html_report"] == str(reports_dir["html"])


def test_analyze_writes_the_reports(client, sample_log_path, reports_dir):
    response = client.post("/analyze", json={"log_path": str(sample_log_path)})
    assert response.status_code == 200
    assert reports_dir["csv"].exists()
    assert reports_dir["html"].exists()


def test_analyze_missing_log_file_is_404(client, tmp_path):
    response = client.post("/analyze", json={"log_path": str(tmp_path / "missing.log")})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_analyze_rejects_invalid_severity(client, sample_log_path):
    response = client.post(
        "/analyze", json={"log_path": str(sample_log_path), "severity": "DEBUG"}
    )
    assert response.status_code == 422


def test_analyze_severity_is_case_insensitive(client, sample_log_path, reports_dir):
    response = client.post(
        "/analyze", json={"log_path": str(sample_log_path), "severity": "error"}
    )
    assert response.status_code == 200
    # the severity filter only trims the CSV/HTML detail table; the summary covers the whole log
    assert response.json()["summary"]["counts"]["ERROR"] == 4


def test_analyze_rejects_same_output_paths(client, sample_log_path, tmp_path):
    same = str(tmp_path / "same.out")
    response = client.post(
        "/analyze",
        json={"log_path": str(sample_log_path), "output": same, "html_output": same},
    )
    assert response.status_code == 400
    assert "must be different" in response.json()["detail"]


def test_analyze_records_metrics(client, sample_log_path, reports_dir):
    client.post("/analyze", json={"log_path": str(sample_log_path)})
    text = client.get("/metrics").text
    assert read_sample(text, "logs_processed_total") == 8
    assert read_sample(text, "analyzer_runs_total") == 1


def test_analyze_custom_output_paths(client, sample_log_path, tmp_path):
    csv_path = tmp_path / "custom.csv"
    html_path = tmp_path / "custom.html"
    response = client.post(
        "/analyze",
        json={
            "log_path": str(sample_log_path),
            "output": str(csv_path),
            "html_output": str(html_path),
        },
    )
    assert response.status_code == 200
    assert csv_path.exists()
    assert html_path.exists()


# Reports
def test_get_csv_report_before_any_analyze_is_404(client, reports_dir):
    response = client.get("/reports/csv")
    assert response.status_code == 404


def test_get_csv_report_after_analyze(client, sample_log_path, reports_dir):
    client.post("/analyze", json={"log_path": str(sample_log_path)})
    response = client.get("/reports/csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "date,time,severity,ip,message" in response.text


def test_get_html_report_before_any_analyze_is_404(client, reports_dir):
    response = client.get("/reports/html")
    assert response.status_code == 404


def test_get_html_report_after_analyze(client, sample_log_path, reports_dir):
    client.post("/analyze", json={"log_path": str(sample_log_path)})
    response = client.get("/reports/html")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<title>Network Log Analyzer</title>" in response.text


# Metrics
def test_metrics_endpoint_starts_at_zero(client):
    text = client.get("/metrics").text
    assert read_sample(text, "analyzer_runs_total") == 0


def test_metrics_endpoint_content_type(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
