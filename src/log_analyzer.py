import argparse
import configparser
import html
import logging
import os
import re
import signal
import sys
import threading
import time
from datetime import datetime

import pandas as pd

from analyzer_metrics import AnalyzerMetrics, start_metrics_server, write_metrics_file

# Pattern 1: split one log line into date, time, severity and message
LOG_PATTERN = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}) "
    r"(?P<time>\d{2}:\d{2}:\d{2}) "
    r"(?P<severity>INFO|WARNING|ERROR|CRITICAL) "
    r"(?P<message>.*)$"
)

# Pattern 2: find an IP address (like 10.10.10.1) inside the message
IP_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def parse_log_line(line):
    match = LOG_PATTERN.match(line.strip())
    if match is None:
        return None

    data = match.groupdict()

    ip_match = IP_PATTERN.search(data["message"])
    data["ip"] = ip_match.group() if ip_match else "N/A"

    return data


SEVERITIES = ["INFO", "WARNING", "ERROR", "CRITICAL"]

# Phase 9: logging and configuration
LOGGER_NAME = "log_analyzer"  # fixed name, because __name__ is "__main__" when run as a script
LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(message)s"

logger = logging.getLogger(LOGGER_NAME)
logger.addHandler(logging.NullHandler())  # stay silent until setup_logging() is called

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.ini")

# Built-in defaults, used for anything the config file does not set
DEFAULT_CONFIG = {
    "logging": {"level": "INFO", "file": "logs/application.log"},
    "reports": {
        "csv_output": "reports/log_report.csv",
        "html_output": "reports/network_log_report.html",
    },
    "application": {"top_n": 5},
}


class ConfigError(Exception):
    """The configuration file is missing (when required) or has a bad value."""


def load_config(path, required=False):
    """Return the settings: built-in defaults overridden by the config file."""
    config = {name: dict(values) for name, values in DEFAULT_CONFIG.items()}

    if not os.path.isfile(path):
        if required:
            raise ConfigError(f"config file not found: {path}")
        return config

    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"could not read config file {path}: {error}")

    for section, values in config.items():
        for key in values:
            if parser.has_option(section, key):
                values[key] = parser.get(section, key).strip()

    level = str(config["logging"]["level"]).upper()
    if level not in LOG_LEVELS:
        raise ConfigError(
            f"invalid log level '{config['logging']['level']}' in {path} "
            f"(choose from {', '.join(LOG_LEVELS)})"
        )
    config["logging"]["level"] = level

    for section, key in [("logging", "file"), ("reports", "csv_output"), ("reports", "html_output")]:
        if not config[section][key]:
            raise ConfigError(f"[{section}] {key} must not be empty in {path}")

    try:
        top_n = int(config["application"]["top_n"])
    except ValueError:
        raise ConfigError(f"[application] top_n must be a whole number in {path}")
    if top_n < 1:
        raise ConfigError(f"[application] top_n must be 1 or more in {path}")
    config["application"]["top_n"] = top_n

    return config


def find_config_path(argv):
    """Read only --config from the arguments. Returns (path, was_given)."""
    pre_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    pre_parser.add_argument("--config")
    known, _ = pre_parser.parse_known_args(argv)

    if known.config:
        return known.config, True
    return DEFAULT_CONFIG_PATH, False


def reset_logging():
    """Close and remove file handlers, so repeated runs never log twice."""
    for handler in list(logger.handlers):
        if isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)
            handler.close()


def setup_logging(level, log_file):
    """Send application logs to log_file. The console output is not touched."""
    reset_logging()
    logger.setLevel(getattr(logging, level))

    try:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        handler = logging.FileHandler(log_file, encoding="utf-8")
    except OSError as error:
        print(f"Warning: cannot write log file {log_file}: {error}", file=sys.stderr)
        return

    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)


class LoggingArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that also records invalid input in the application log."""

    def error(self, message):
        logger.error("Invalid input: %s", message)
        super().error(message)


def port_number(text):
    """argparse type: a TCP port between 1 and 65535."""
    try:
        port = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid port: {text!r}")
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"port must be between 1 and 65535: {port}")
    return port


def parse_arguments(argv=None, config=None):
    config = config or DEFAULT_CONFIG
    parser = LoggingArgumentParser(
        description="Network Log Analyzer: parse a router log with Regex, "
        "analyze it with Pandas and export a CSV report."
    )
    parser.add_argument(
        "--log",
        required=True,
        help="path to the input log file (example: logs/router.log)",
    )
    parser.add_argument(
        "--severity",
        type=str.upper,  # accept error, Error, ERROR...
        choices=SEVERITIES,
        help="only keep logs with this severity: " + ", ".join(SEVERITIES),
    )
    parser.add_argument(
        "--output",
        default=config["reports"]["csv_output"],
        help="path of the CSV report (default: %(default)s)",
    )

    parser.add_argument(
        "--html-output",
        default=config["reports"]["html_output"],
        help="path of the HTML report (default: %(default)s)",
    )
    parser.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help="path of the configuration file (default: %(default)s)",
    )

    parser.add_argument(
        "--metrics-output",
        help="write Prometheus metrics to this file, e.g. reports/metrics.prom "
        "(default: no metrics file)",
    )
    parser.add_argument(
        "--metrics-port",
        type=port_number,
        help="after the analysis, serve Prometheus metrics at http://ADDR:PORT/metrics "
        "until stopped with Ctrl+C (default: off)",
    )
    parser.add_argument(
        "--metrics-addr",
        default="127.0.0.1",
        help="address for --metrics-port; use 0.0.0.0 inside Docker (default: %(default)s)",
    )

    args = parser.parse_args(argv)

    if not os.path.isfile(args.log):
        parser.error(f"log file not found: {args.log}")

    if os.path.isdir(args.html_output):
        parser.error(f"--html-output must be a file, not a folder: {args.html_output}")

    if os.path.abspath(args.html_output) == os.path.abspath(args.output):
        parser.error("--html-output and --output must be different files")

    if args.metrics_output:
        if os.path.isdir(args.metrics_output):
            parser.error(f"--metrics-output must be a file, not a folder: {args.metrics_output}")
        others = {os.path.abspath(args.output), os.path.abspath(args.html_output)}
        if os.path.abspath(args.metrics_output) in others:
            parser.error("--metrics-output must be different from --output and --html-output")

    return args


def count_matches(data, *words):
    """Count rows whose message contains ALL the given words (any case)."""
    mask = pd.Series(True, index=data.index)
    for word in words:
        mask &= data["message"].str.contains(word, case=False, regex=False)
    return int(mask.sum())


def compute_operations_summary(data, top_n=5):
    """Run the network analysis and return the results as a dictionary."""
    total_events = len(data)
    counts = data["severity"].value_counts()

    error_count = int(counts.get("ERROR", 0))
    top_ips = data[data["ip"] != "N/A"]["ip"].value_counts().head(top_n)
    critical_rows = data[data["severity"] == "CRITICAL"]
    top_errors = data[data["severity"] == "ERROR"]["message"].value_counts().head(top_n)

    return {
        "total": total_events,
        "counts": {level: int(counts.get(level, 0)) for level in SEVERITIES},
        # error rate = ERROR rows / all rows * 100
        "error_rate": error_count / total_events * 100 if total_events else 0,
        "top_ips": [(ip, int(n)) for ip, n in top_ips.items()],
        "interface_failures": count_matches(data, "interface", "down"),
        "bgp_failures": count_matches(data, "bgp", "down"),
        "auth_failures": count_matches(data, "authentication failure"),
        "critical_events": [
            (row.date, row.time, row.message) for row in critical_rows.itertuples()
        ],
        "top_errors": [(msg, int(n)) for msg, n in top_errors.items()],
    }


def print_operations_summary(summary):
    print()
    print("================================")
    print(" Network Operations Summary")
    print("================================")

    # 1-5: total events and one count per severity
    print(f"Total events      : {summary['total']}")
    for level in SEVERITIES:
        print(f"{level + ' count':<18}: {summary['counts'][level]}")

    # 6: error rate
    print(f"Error rate        : {summary['error_rate']:.2f}%")

    # 7: most common IP addresses found in messages
    print()
    print("Top IP addresses:")
    if not summary["top_ips"]:
        print("  None")
    for ip, count in summary["top_ips"]:
        print(f"  {ip:<15} {count} event(s)")

    # 8-10: failure counts found by searching the message text
    print()
    print("Failure counts:")
    print(f"  Interface failures      : {summary['interface_failures']}")
    print(f"  BGP neighbor failures   : {summary['bgp_failures']}")
    print(f"  Authentication failures : {summary['auth_failures']}")

    # 11: every CRITICAL event
    print()
    print("Critical event summary:")
    if not summary["critical_events"]:
        print("  None")
    for date, time, message in summary["critical_events"]:
        print(f"  {date} {time}  {message}")

    # 12: most repeated ERROR messages
    print()
    print("Top error messages:")
    if not summary["top_errors"]:
        print("  None")
    for message, count in summary["top_errors"]:
        print(f"  {count}x  {message}")


# Phase 7: HTML report
HTML_STYLE = """
body { font-family: Arial, Helvetica, sans-serif; margin: 0; background: #f4f6f8; color: #1f2933; }
header { background: #1f3a5f; color: #fff; padding: 24px 40px; }
header h1 { margin: 0 0 6px 0; }
header p { margin: 0; opacity: 0.85; }
main { padding: 24px 40px; }
h2 { border-bottom: 2px solid #d9dee3; padding-bottom: 6px; margin-top: 32px; }
.cards { display: flex; flex-wrap: wrap; gap: 16px; }
.card { background: #fff; border-radius: 8px; padding: 16px 24px; min-width: 130px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.12); border-top: 4px solid #1f3a5f; }
.card .value { font-size: 28px; font-weight: bold; }
.card .label { font-size: 13px; text-transform: uppercase; color: #52606d; }
.card.info { border-top-color: #2f80ed; }
.card.warning { border-top-color: #f2994a; }
.card.error { border-top-color: #eb5757; }
.card.critical { border-top-color: #8e1b1b; }
table { border-collapse: collapse; width: 100%; background: #fff;
        box-shadow: 0 1px 3px rgba(0,0,0,0.12); }
th { background: #1f3a5f; color: #fff; text-align: left; }
th, td { padding: 8px 12px; border-bottom: 1px solid #e4e7eb; }
tr:nth-child(even) td { background: #f8f9fb; }
.badge { padding: 2px 8px; border-radius: 10px; color: #fff; font-size: 12px; font-weight: bold; }
.badge.INFO { background: #2f80ed; }
.badge.WARNING { background: #f2994a; }
.badge.ERROR { background: #eb5757; }
.badge.CRITICAL { background: #8e1b1b; }
.note { color: #52606d; font-style: italic; }
"""


def html_card(label, value, css_class=""):
    return (
        f'<div class="card {css_class}"><div class="value">{value}</div>'
        f'<div class="label">{label}</div></div>'
    )


def html_table(headers, rows):
    """Build an HTML table. rows are lists of ready-to-use HTML cells."""
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f"<table><tr>{head}</tr>{body}</table>"


def build_html_report(summary, detail_df, severity_filter, generated_at):
    esc = html.escape  # turns < > & into safe text, so log text can't break the page

    cards = "".join(
        [
            html_card("Total Events", summary["total"]),
            *[
                html_card(level, summary["counts"][level], level.lower())
                for level in SEVERITIES
            ],
            html_card("Error Rate", f"{summary['error_rate']:.2f}%"),
        ]
    )

    ip_rows = [[esc(ip), count] for ip, count in summary["top_ips"]]
    ips_html = (
        html_table(["IP Address", "Events"], ip_rows)
        if ip_rows
        else '<p class="note">No IP addresses found.</p>'
    )

    issues_html = html_table(
        ["Issue", "Count"],
        [
            ["Interface failures", summary["interface_failures"]],
            ["BGP neighbor failures", summary["bgp_failures"]],
            ["Authentication failures", summary["auth_failures"]],
        ],
    )

    error_rows = [[count, esc(msg)] for msg, count in summary["top_errors"]]
    errors_html = (
        html_table(["Count", "Message"], error_rows)
        if error_rows
        else '<p class="note">No ERROR messages.</p>'
    )

    detail_rows = [
        [
            esc(row.date),
            esc(row.time),
            f'<span class="badge {esc(row.severity)}">{esc(row.severity)}</span>',
            esc(row.ip),
            esc(row.message),
        ]
        for row in detail_df.itertuples()
    ]
    detail_html = (
        html_table(["Date", "Time", "Severity", "IP", "Message"], detail_rows)
        if detail_rows
        else '<p class="note">No log entries to show.</p>'
    )

    filter_note = (
        f'<p class="note">Detailed table filtered by severity: {esc(severity_filter)}. '
        "Summary cards and analysis cover all logs.</p>"
        if severity_filter
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Network Log Analyzer</title>
<style>{HTML_STYLE}</style>
</head>
<body>
<header>
<h1>Network Log Analyzer</h1>
<p>Report generated: {esc(generated_at)}</p>
</header>
<main>
<h2>Summary</h2>
<div class="cards">{cards}</div>
<h2>Top Source IPs</h2>
{ips_html}
<h2>Network Issues</h2>
{issues_html}
<h2>Top Error Messages</h2>
{errors_html}
<h2>Detailed Logs</h2>
{filter_note}
{detail_html}
</main>
</body>
</html>
"""


def write_html_report(path, content):
    try:
        report_dir = os.path.dirname(path)
        if report_dir:
            os.makedirs(report_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as report:
            report.write(content)
    except OSError as error:
        logger.exception("Could not create HTML report %s", path)
        print(f"Could not create HTML report: {error}")
        sys.exit(1)

    logger.info("HTML report written: %s", path)
    print()
    print("HTML report created successfully")
    print(f"File: {path}")


CSV_COLUMNS = ["date", "time", "severity", "ip", "message"]


def build_dataframe(logs):
    """Parse every log line with Regex and return the results as a DataFrame."""
    entries = []

    for number, log in enumerate(logs, start=1):
        entry = parse_log_line(log)

        if entry is None:
            logger.warning("Skipping unparseable line %d: %r", number, log.strip())
            print(f"Could not parse: {log.strip()}")
            continue

        logger.debug("Parsed line %d: %s", number, entry)
        entries.append(entry)

    logger.info("Parsed %d of %d lines", len(entries), len(logs))
    return pd.DataFrame(entries)


def filter_by_severity(data, severity):
    """Keep only rows with the given severity (None means keep everything)."""
    if not severity:
        logger.debug("No severity filter requested")
        return data

    filtered = data[data["severity"] == severity]
    logger.info("Filtered by severity %s: %d of %d rows kept", severity, len(filtered), len(data))
    if filtered.empty:
        logger.warning("No log entries with severity %s", severity)
    return filtered


def write_csv_report(data, report_file):
    try:
        report_dir = os.path.dirname(report_file)
        if report_dir:
            os.makedirs(report_dir, exist_ok=True)
        data[CSV_COLUMNS].to_csv(report_file, index=False)
    except OSError as error:
        logger.exception("Could not create CSV report %s", report_file)
        print(f"Could not create CSV report: {error}")
        sys.exit(1)

    logger.info("CSV report written: %s (%d rows)", report_file, len(data))
    print()
    print("CSV report created successfully")
    print(f"File: {report_file}")


def run_analysis(args, config):
    log_file = args.log

    logger.info("Loading log file: %s", log_file)
    with open(log_file, "r") as file:
        logs = file.readlines()
    logger.info("Read %d lines", len(logs))

    total = len(logs)

    errors = 0
    warnings = 0
    critical = 0

    for log in logs:

        if "ERROR" in log:
            errors += 1

        elif "WARNING" in log:
            warnings += 1

        elif "CRITICAL" in log:
            critical += 1

    print("================================")
    print(" Network Log Analyzer")
    print("================================")

    print(f"Total Logs      : {total}")
    print(f"Errors          : {errors}")
    print(f"Warnings        : {warnings}")
    print(f"Critical Events : {critical}")

    # Step 1-2: parse the lines and build the DataFrame (a table)
    df = build_dataframe(logs)
    full_df = df  # keep the unfiltered table for the operations summary

    # Optional filter from --severity
    df = filter_by_severity(df, args.severity)
    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", None)

    print()
    print("================================")
    print(" DataFrame (Pandas)")
    print("================================")
    print(df[CSV_COLUMNS])

    # Step 3: count rows per severity
    print()
    print("Logs per severity:")
    print(df["severity"].value_counts())

    # Step 4: filter rows (only ERROR and CRITICAL)
    print()
    print("ERROR and CRITICAL events:")
    serious = df[df["severity"].isin(["ERROR", "CRITICAL"])]
    print(serious[["time", "severity", "message"]])

    # Step 5: rows that have an IP address
    print()
    print("Logs per IP address:")
    print(df[df["ip"] != "N/A"]["ip"].value_counts())

    # Phase 6: network operations summary (always uses ALL parsed logs)
    summary = compute_operations_summary(full_df, config["application"]["top_n"])
    logger.debug("Operations summary: %s", summary)
    print_operations_summary(summary)

    # Phase 4: export the DataFrame to a CSV report
    write_csv_report(df, args.output)

    # Phase 7: export the HTML report (table = same rows as the CSV)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html_content = build_html_report(summary, df, args.severity, generated_at)
    write_html_report(args.html_output, html_content)

    return summary, total


def export_metrics_file(metrics, path):
    try:
        write_metrics_file(metrics.registry, path)
    except OSError as error:
        logger.exception("Could not write metrics file %s", path)
        print(f"Could not write metrics file: {error}")
        sys.exit(1)

    logger.info("Metrics file written: %s", path)
    print()
    print("Metrics file created successfully")
    print(f"File: {path}")


def wait_until_stopped():
    """Block until Ctrl+C or docker stop (SIGINT / SIGTERM)."""
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    stop.wait()


def serve_metrics(metrics, port, addr):
    try:
        server = start_metrics_server(port, addr, metrics.registry)
    except OSError as error:
        logger.exception("Could not start metrics server on %s:%s", addr, port)
        print(f"Could not start metrics server on {addr}:{port}: {error}")
        sys.exit(1)

    logger.info("Serving metrics on http://%s:%s/metrics", addr, port)
    print()
    print(f"Serving metrics at http://{addr}:{port}/metrics (Ctrl+C to stop)", flush=True)
    try:
        wait_until_stopped()
    finally:
        server.shutdown()
        server.server_close()
        logger.info("Metrics server stopped")


def main(argv=None):
    config_path, config_was_given = find_config_path(argv)

    try:
        config = load_config(config_path, required=config_was_given)
    except ConfigError as error:
        setup_logging(DEFAULT_CONFIG["logging"]["level"], DEFAULT_CONFIG["logging"]["file"])
        logger.error("Invalid configuration: %s", error)
        print(f"error: {error}", file=sys.stderr)
        sys.exit(2)

    setup_logging(config["logging"]["level"], config["logging"]["file"])
    logger.info("Application started")

    if os.path.isfile(config_path):
        logger.info("Loaded configuration from %s", config_path)
    else:
        logger.warning("Config file not found (%s), using built-in defaults", config_path)
    logger.debug("Configuration: %s", config)

    args = parse_arguments(argv, config)
    logger.info(
        "Arguments: log=%s severity=%s output=%s html_output=%s",
        args.log, args.severity, args.output, args.html_output,
    )

    started = time.perf_counter()
    try:
        summary, lines_read = run_analysis(args, config)
    except Exception:
        logger.exception("Unexpected error")
        raise

    # Phase 13: Prometheus metrics (only for a completed run, only if requested)
    metrics = AnalyzerMetrics()
    metrics.record_run(lines_read, summary, time.perf_counter() - started)
    logger.debug("Metrics recorded for %d lines", lines_read)

    if args.metrics_output:
        export_metrics_file(metrics, args.metrics_output)

    logger.info("Application finished successfully")

    if args.metrics_port:
        serve_metrics(metrics, args.metrics_port, args.metrics_addr)


if __name__ == "__main__":
    main()
