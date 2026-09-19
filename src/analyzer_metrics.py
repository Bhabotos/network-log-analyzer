"""Prometheus metrics for the Network Log Analyzer.

The analyzer is a batch program, so nothing is scraped while it runs. Instead:
  * write_metrics_file()   saves the metrics as a text file (textfile collector), or
  * start_metrics_server() serves them at /metrics so Prometheus can pull them.

Every run builds its own registry, so the values always describe that run only.
"""

import os

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    start_http_server,
    write_to_textfile,
)

SEVERITY_COUNTERS = {
    "INFO": ("log_info_total", "INFO log lines seen"),
    "WARNING": ("log_warning_total", "WARNING log lines seen"),
    "ERROR": ("log_error_total", "ERROR log lines seen"),
    "CRITICAL": ("log_critical_total", "CRITICAL log lines seen"),
}

# Seconds. Small logs finish in well under a second, big ones can take longer.
DURATION_BUCKETS = (0.01, 0.05, 0.1, 0.5, 1, 5, 10, 30, 60)


class AnalyzerMetrics:
    def __init__(self, registry=None):
        self.registry = registry if registry is not None else CollectorRegistry()

        self.runs = Counter(
            "analyzer_runs_total", "Completed analyzer runs", registry=self.registry
        )
        self.processed = Counter(
            "logs_processed_total",
            "Log lines read from the input file (parsed or not)",
            registry=self.registry,
        )
        self.parse_errors = Counter(
            "log_parse_errors_total",
            "Log lines that did not match the expected format",
            registry=self.registry,
        )
        self.severity = {
            level: Counter(name, description, registry=self.registry)
            for level, (name, description) in SEVERITY_COUNTERS.items()
        }
        self.duration = Histogram(
            "analyzer_processing_seconds",
            "Time taken to process one log file",
            buckets=DURATION_BUCKETS,
            registry=self.registry,
        )
        self.error_rate = Gauge(
            "log_error_rate_percent",
            "ERROR lines as a percentage of all parsed lines",
            registry=self.registry,
        )
        self.last_run = Gauge(
            "analyzer_last_run_timestamp_seconds",
            "Unix time when the last run completed",
            registry=self.registry,
        )

    def record_run(self, lines_read, summary, duration_seconds):
        """Record one completed run.

        lines_read: every line in the input file.
        summary: the dictionary from compute_operations_summary(); it covers the
                 lines that parsed successfully.
        """
        self.runs.inc()
        self.processed.inc(lines_read)
        self.parse_errors.inc(lines_read - summary["total"])

        for level, counter in self.severity.items():
            counter.inc(summary["counts"][level])

        self.error_rate.set(summary["error_rate"])
        self.duration.observe(duration_seconds)
        self.last_run.set_to_current_time()


def write_metrics_file(registry, path):
    """Write the metrics in Prometheus text format. Raises OSError on failure."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    write_to_textfile(path, registry)


def start_metrics_server(port, addr, registry):
    """Serve /metrics in a background thread. Returns the server (call .shutdown())."""
    server, _thread = start_http_server(port, addr=addr, registry=registry)
    return server
