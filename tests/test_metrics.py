import socket
import urllib.request

import pytest
from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.parser import text_string_to_metric_families

import log_analyzer
from analyzer_metrics import AnalyzerMetrics, start_metrics_server, write_metrics_file
from log_analyzer import main, parse_arguments

ALL_METRICS = [
    "logs_processed_total",
    "log_info_total",
    "log_warning_total",
    "log_error_total",
    "log_critical_total",
    "analyzer_runs_total",
    "analyzer_processing_seconds_count",
    "log_parse_errors_total",
    "log_error_rate_percent",
    "analyzer_last_run_timestamp_seconds",
]


def read_sample(text, name, labels=None):
    """Read one value from Prometheus text; parsing it also proves the format is valid."""
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            if sample.name == name and sample.labels == (labels or {}):
                return sample.value
    return None


def sample_summary(sample_df):
    return log_analyzer.compute_operations_summary(sample_df)


@pytest.fixture
def metrics():
    return AnalyzerMetrics()


def value(metrics, name, labels=None):
    return metrics.registry.get_sample_value(name, labels)


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "metrics_config.ini"
    path.write_text(
        f"[logging]\nfile = {tmp_path}/app.log\n"
        f"[reports]\ncsv_output = {tmp_path}/r.csv\nhtml_output = {tmp_path}/r.html\n"
    )
    return str(path)


# The metrics object
def test_all_metrics_exist_and_start_at_zero(metrics):
    for name in ALL_METRICS:
        assert value(metrics, name) == 0, name


def test_metric_types_are_correct(metrics):
    text = generate_latest(metrics.registry).decode()

    for name in [
        "logs_processed_total",
        "log_info_total",
        "log_warning_total",
        "log_error_total",
        "log_critical_total",
        "analyzer_runs_total",
        "log_parse_errors_total",
    ]:
        assert f"# TYPE {name} counter" in text, name
    assert "# TYPE analyzer_processing_seconds histogram" in text
    assert "# TYPE log_error_rate_percent gauge" in text
    assert "# TYPE analyzer_last_run_timestamp_seconds gauge" in text


def test_counters_increase_after_a_run(metrics, sample_df):
    metrics.record_run(8, sample_summary(sample_df), 0.02)

    assert value(metrics, "logs_processed_total") == 8
    assert value(metrics, "analyzer_runs_total") == 1


def test_severity_counters_match_the_log(metrics, sample_df):
    metrics.record_run(8, sample_summary(sample_df), 0.02)

    assert value(metrics, "log_info_total") == 2
    assert value(metrics, "log_warning_total") == 1
    assert value(metrics, "log_error_total") == 4
    assert value(metrics, "log_critical_total") == 1


def test_parse_errors_are_counted(metrics, sample_df):
    # 10 lines were read but only 8 parsed, so 2 failed
    metrics.record_run(10, sample_summary(sample_df), 0.02)

    assert value(metrics, "log_parse_errors_total") == 2
    assert value(metrics, "logs_processed_total") == 10


def test_no_parse_errors_when_every_line_parses(metrics, sample_df):
    metrics.record_run(8, sample_summary(sample_df), 0.02)
    assert value(metrics, "log_parse_errors_total") == 0


def test_processing_duration_is_recorded(metrics, sample_df):
    metrics.record_run(8, sample_summary(sample_df), 0.03)

    assert value(metrics, "analyzer_processing_seconds_count") == 1
    assert value(metrics, "analyzer_processing_seconds_sum") == pytest.approx(0.03)


def test_duration_lands_in_the_right_histogram_buckets(metrics, sample_df):
    metrics.record_run(8, sample_summary(sample_df), 0.03)

    def bucket(le):
        return value(metrics, "analyzer_processing_seconds_bucket", {"le": le})

    assert bucket("0.01") == 0  # 0.03 s is slower than 10 ms
    assert bucket("0.05") == 1
    assert bucket("60.0") == 1
    assert bucket("+Inf") == 1


def test_error_rate_gauge(metrics, sample_df):
    metrics.record_run(8, sample_summary(sample_df), 0.02)
    assert value(metrics, "log_error_rate_percent") == pytest.approx(50.0)


def test_error_rate_gauge_can_go_down(metrics, sample_df):
    metrics.record_run(8, sample_summary(sample_df), 0.02)
    only_info = log_analyzer.filter_by_severity(sample_df, "INFO")
    metrics.record_run(2, sample_summary(only_info), 0.02)

    assert value(metrics, "log_error_rate_percent") == 0


def test_last_run_timestamp_is_recent(metrics, sample_df):
    import time

    metrics.record_run(8, sample_summary(sample_df), 0.02)
    assert abs(value(metrics, "analyzer_last_run_timestamp_seconds") - time.time()) < 5


def test_two_runs_on_one_registry_accumulate(metrics, sample_df):
    summary = sample_summary(sample_df)
    metrics.record_run(8, summary, 0.02)
    metrics.record_run(8, summary, 0.02)

    assert value(metrics, "analyzer_runs_total") == 2
    assert value(metrics, "log_error_total") == 8
    assert value(metrics, "analyzer_processing_seconds_count") == 2


def test_separate_instances_do_not_share_state(sample_df):
    first, second = AnalyzerMetrics(), AnalyzerMetrics()
    first.record_run(8, sample_summary(sample_df), 0.02)

    assert value(first, "logs_processed_total") == 8
    assert value(second, "logs_processed_total") == 0


def test_empty_log_records_zeros_without_dividing_by_zero(metrics):
    summary = {"total": 0, "counts": {"INFO": 0, "WARNING": 0, "ERROR": 0, "CRITICAL": 0}, "error_rate": 0}
    metrics.record_run(0, summary, 0.01)

    assert value(metrics, "logs_processed_total") == 0
    assert value(metrics, "analyzer_runs_total") == 1


# Exposing the metrics: text file
def test_metrics_file_is_valid_prometheus_text(metrics, sample_df, tmp_path):
    metrics.record_run(8, sample_summary(sample_df), 0.02)
    path = tmp_path / "metrics.prom"
    write_metrics_file(metrics.registry, str(path))

    text = path.read_text()
    assert read_sample(text, "logs_processed_total") == 8
    assert read_sample(text, "log_error_total") == 4
    assert read_sample(text, "analyzer_processing_seconds_count") == 1


def test_metrics_file_creates_missing_directory(metrics, tmp_path):
    path = tmp_path / "new" / "dir" / "metrics.prom"
    write_metrics_file(metrics.registry, str(path))
    assert path.exists()


def test_metrics_file_bad_directory_raises(metrics, tmp_path):
    blocker = tmp_path / "a_file"
    blocker.write_text("x")

    with pytest.raises(OSError):
        write_metrics_file(metrics.registry, str(blocker / "metrics.prom"))


# Exposing the metrics: HTTP /metrics
def test_http_endpoint_serves_metrics(metrics, sample_df):
    metrics.record_run(8, sample_summary(sample_df), 0.02)
    server = start_metrics_server(0, "127.0.0.1", metrics.registry)

    try:
        url = f"http://127.0.0.1:{server.server_port}/metrics"
        with urllib.request.urlopen(url, timeout=5) as response:
            body = response.read().decode()
            content_type = response.headers["Content-Type"]
            status = response.status
    finally:
        server.shutdown()
        server.server_close()

    assert status == 200
    assert content_type.startswith("text/plain")
    assert read_sample(body, "logs_processed_total") == 8
    assert read_sample(body, "log_critical_total") == 1


# Command line and main()
def test_metrics_options_are_off_by_default(sample_log_path):
    args = parse_arguments(["--log", str(sample_log_path)])

    assert args.metrics_output is None
    assert args.metrics_port is None
    assert args.metrics_addr == "127.0.0.1"


@pytest.mark.parametrize("port", ["0", "70000", "-1", "abc"])
def test_invalid_metrics_port_is_rejected(sample_log_path, port, capsys):
    with pytest.raises(SystemExit) as exc:
        parse_arguments(["--log", str(sample_log_path), "--metrics-port", port])

    assert exc.value.code == 2
    assert "--metrics-port" in capsys.readouterr().err


def test_metrics_output_cannot_be_a_folder(sample_log_path, tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        parse_arguments(["--log", str(sample_log_path), "--metrics-output", str(tmp_path)])

    assert exc.value.code == 2
    assert "must be a file" in capsys.readouterr().err


def test_metrics_output_must_differ_from_reports(sample_log_path, tmp_path, capsys):
    same = str(tmp_path / "same.out")
    with pytest.raises(SystemExit) as exc:
        parse_arguments(["--log", str(sample_log_path), "--output", same, "--metrics-output", same])

    assert exc.value.code == 2
    assert "must be different" in capsys.readouterr().err


def test_main_writes_no_metrics_file_by_default(sample_log_path, config_file, tmp_path):
    main(["--log", str(sample_log_path), "--config", config_file])
    assert not list(tmp_path.glob("*.prom"))


def test_main_writes_metrics_file(sample_log_path, config_file, tmp_path, capsys):
    prom = tmp_path / "out" / "metrics.prom"
    main(["--log", str(sample_log_path), "--config", config_file, "--metrics-output", str(prom)])

    text = prom.read_text()
    assert read_sample(text, "logs_processed_total") == 8
    assert read_sample(text, "log_info_total") == 2
    assert read_sample(text, "log_warning_total") == 1
    assert read_sample(text, "log_error_total") == 4
    assert read_sample(text, "log_critical_total") == 1
    assert read_sample(text, "analyzer_runs_total") == 1
    assert read_sample(text, "log_parse_errors_total") == 0
    assert read_sample(text, "analyzer_processing_seconds_count") == 1
    assert read_sample(text, "analyzer_processing_seconds_sum") > 0

    out = capsys.readouterr().out
    assert "Metrics file created successfully" in out
    assert f"File: {prom}" in out


def test_main_counts_unparseable_lines(config_file, tmp_path):
    log = tmp_path / "mixed.log"
    log.write_text("2026-01-10 10:00:00 INFO ok\ngarbage\nmore garbage\n2026-01-10 10:01:00 ERROR bad\n")
    prom = tmp_path / "m.prom"

    main(["--log", str(log), "--config", config_file, "--metrics-output", str(prom)])

    text = prom.read_text()
    assert read_sample(text, "logs_processed_total") == 4
    assert read_sample(text, "log_parse_errors_total") == 2
    assert read_sample(text, "log_info_total") == 1
    assert read_sample(text, "log_error_total") == 1


def test_severity_filter_does_not_change_metrics(sample_log_path, config_file, tmp_path):
    prom = tmp_path / "m.prom"
    main(["--log", str(sample_log_path), "--config", config_file,
          "--severity", "ERROR", "--metrics-output", str(prom)])

    text = prom.read_text()
    assert read_sample(text, "logs_processed_total") == 8
    assert read_sample(text, "log_info_total") == 2  # metrics describe the whole log


def test_main_metrics_file_failure_exits_with_error(sample_log_path, config_file, tmp_path, capsys):
    blocker = tmp_path / "a_file"
    blocker.write_text("x")

    with pytest.raises(SystemExit) as exc:
        main(["--log", str(sample_log_path), "--config", config_file,
              "--metrics-output", str(blocker / "m.prom")])

    assert exc.value.code == 1
    assert "Could not write metrics file" in capsys.readouterr().out


def test_failed_run_records_no_metrics(config_file, tmp_path):
    no_valid_lines = tmp_path / "bad.log"
    no_valid_lines.write_text("garbage\n")
    prom = tmp_path / "m.prom"

    with pytest.raises(KeyError):  # known limitation: a log with no valid lines
        main(["--log", str(no_valid_lines), "--config", config_file, "--metrics-output", str(prom)])

    assert not prom.exists()


def test_main_serves_metrics_over_http(sample_log_path, config_file, monkeypatch, capsys):
    port = free_port()
    fetched = {}

    def fake_wait():  # stands in for "wait for Ctrl+C": read /metrics while the server is up
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5) as response:
            fetched["body"] = response.read().decode()

    monkeypatch.setattr(log_analyzer, "wait_until_stopped", fake_wait)
    main(["--log", str(sample_log_path), "--config", config_file, "--metrics-port", str(port)])

    assert read_sample(fetched["body"], "log_error_total") == 4
    assert f"http://127.0.0.1:{port}/metrics" in capsys.readouterr().out

    with pytest.raises(OSError):  # server was shut down afterwards
        urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=2)


def test_main_metrics_port_already_in_use_exits(sample_log_path, config_file, capsys):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        port = sock.getsockname()[1]

        with pytest.raises(SystemExit) as exc:
            main(["--log", str(sample_log_path), "--config", config_file, "--metrics-port", str(port)])

    assert exc.value.code == 1
    assert "Could not start metrics server" in capsys.readouterr().out
