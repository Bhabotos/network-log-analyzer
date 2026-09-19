# Network Log Analyzer

[![CI](https://github.com/Bhabotos/network-log-analyzer/actions/workflows/ci.yml/badge.svg)](https://github.com/Bhabotos/network-log-analyzer/actions/workflows/ci.yml)

A command-line tool that turns raw router log files into structured data, a network operations summary, and shareable CSV and HTML reports.

## Project Overview

Router logs are plain text and hard to scan by eye. This tool reads a log file, extracts the date, time, severity, IP address and message from every line using **regular expressions**, analyzes the result with **Pandas**, and writes a CSV file and a self-contained HTML report. It records its own activity in an application log and can run locally or inside a Docker container.

Example input line:

```
2026-09-19 08:10:21 ERROR BGP neighbor 10.10.10.1 is DOWN
```

Structured result:

| Date | Time | Severity | IP | Message |
|---|---|---|---|---|
| 2026-09-19 | 08:10:21 | ERROR | 10.10.10.1 | BGP neighbor 10.10.10.1 is DOWN |

## Features

- **Regex parsing** of date, time, severity, IP address and message; lines that do not match are reported and skipped
- **Pandas analysis** with severity counts, error rate, top IP addresses and top error messages
- **Network issue detection** for interface failures, BGP neighbor failures and authentication failures, plus a critical event summary
- **Severity filter** (`--severity`) for the detailed table and CSV
- **CSV export** with a header row
- **HTML report** with summary cards, issue tables and a colour-coded log table; log text is HTML-escaped
- **Configuration file** (`config.ini`) for the log level, report paths and the size of the "top" lists; command-line options override it
- **Application logging** to `logs/application.log` with DEBUG, INFO, WARNING and ERROR levels
- **Input validation** with clear errors and exit codes
- **Docker image** that runs as a non-root user and works with mounted `logs/` and `reports/` folders
- **Prometheus metrics** for lines processed, counts per severity, parse failures, run count and run duration, written to a file or served at `/metrics`
- **FastAPI web service** to trigger analyses, fetch the latest reports and scrape metrics over HTTP, with interactive docs at `/docs`
- **Prometheus + Grafana** via Docker Compose: continuous scraping and a pre-provisioned dashboard on top of the existing metrics
- **164 automated tests** with pytest

## Architecture

```
                  +-----------------+
   logs/router.log|  read + validate |  argparse options + config.ini
                  +--------+--------+
                           |
                  +--------v--------+
                  |  Regex parsing  |  one dict per valid line
                  +--------+--------+
                           |
                  +--------v--------+
                  | Pandas DataFrame|  optional --severity filter
                  +---+---------+---+
                      |         |
          +-----------v--+   +--v-----------------+
          |  Operations  |   |  CSV export        |
          |  summary     |   |  reports/*.csv     |
          +------+-------+   +--------------------+
                 |
        +--------v---------+
        |  HTML report     |  reports/*.html
        +------------------+

   Every step writes events to logs/application.log
```

The analysis returns a plain dictionary. The terminal summary and the HTML report both read from it, so the numbers always agree.

## Technologies

- Python 3.14 (pandas 3.x requires Python 3.11 or newer)
- pandas
- prometheus-client
- FastAPI, Uvicorn
- `re`, `argparse`, `configparser`, `logging` (Python standard library)
- pytest, httpx2, PyYAML
- Docker, Docker Compose, Prometheus, Grafana

## Project Structure

```
network-log-analyzer/
├── src/
│   ├── log_analyzer.py        # parsing, analysis, reports, CLI, logging
│   ├── analyzer_metrics.py    # Prometheus metrics
│   └── api.py                 # FastAPI web service
├── tests/
│   ├── data/sample.log        # small log used by the tests
│   ├── conftest.py            # shared fixtures and test isolation
│   ├── test_parsing.py        # regex extraction
│   ├── test_dataframe.py      # DataFrame and severity filter
│   ├── test_analysis.py       # network analysis calculations
│   ├── test_reports.py        # CSV and HTML reports
│   ├── test_cli.py            # arguments, validation, end-to-end runs
│   ├── test_config.py         # configuration file
│   ├── test_logging.py        # application logging
│   ├── test_metrics.py        # Prometheus metrics
│   ├── test_api.py            # FastAPI endpoints
│   └── test_observability.py  # Prometheus scrape config + Grafana dashboard
├── logs/
│   └── router.log             # sample input (application.log is generated here)
├── reports/                   # generated CSV and HTML reports
├── prometheus/
│   └── prometheus.yml         # scrape config (targets the api service)
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/prometheus.yml
│   │   └── dashboards/dashboard.yml
│   └── dashboards/network-log-analyzer.json
├── config.ini                 # default settings
├── Dockerfile
├── docker-compose.yml         # api + analyzer + prometheus + grafana
├── .dockerignore
├── requirements.txt           # runtime dependencies
├── requirements-dev.txt       # runtime + pytest
└── pytest.ini
```

## Installation

```bash
git clone https://github.com/Bhabotos/network-log-analyzer.git
cd network-log-analyzer

python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
```

Use `requirements.txt` instead if you only want to run the tool and not the tests.

## Local Usage

```bash
python3 src/log_analyzer.py --log logs/router.log
```

This prints the analysis, writes `reports/log_report.csv` and `reports/network_log_report.html`, and appends to `logs/application.log`. Open the HTML report with `xdg-open reports/network_log_report.html`.

### Options

| Option | Description | Default |
|---|---|---|
| `--log` | Input log file (required) | |
| `--severity` | Keep only `INFO`, `WARNING`, `ERROR` or `CRITICAL` (case-insensitive) | all |
| `--output` | CSV report path | `reports/log_report.csv` |
| `--html-output` | HTML report path | `reports/network_log_report.html` |
| `--config` | Configuration file | `config.ini` |
| `--metrics-output` | Write Prometheus metrics to this file | off |
| `--metrics-port` | After the analysis, serve `/metrics` on this port until stopped | off |
| `--metrics-addr` | Address for `--metrics-port` | `127.0.0.1` |

Priority for every setting: command-line option, then `config.ini`, then the built-in default. Relative paths are relative to the folder you run the program from. The `--severity` filter applies to the detailed table, CSV and HTML table; the summary always covers the whole log.

### Configuration

```ini
[logging]
level = INFO                     # DEBUG, INFO, WARNING or ERROR
file = logs/application.log

[reports]
csv_output = reports/log_report.csv
html_output = reports/network_log_report.html

[application]
top_n = 5                        # rows in "Top IP addresses" and "Top error messages"
```

## Docker Usage

Build the image:

```bash
docker build -t network-log-analyzer .
```

Run it with your `logs/` and `reports/` folders mounted:

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" \
  -v "$(pwd)/logs:/app/logs" \
  -v "$(pwd)/reports:/app/reports" \
  network-log-analyzer
```

- `--user "$(id -u):$(id -g)"` makes the generated files belong to you instead of another user. Without it the container uses UID 1000.
- The container reads `logs/router.log` and writes both reports and `application.log` back to your host folders.
- Add `-e TZ="$(timedatectl show -p Timezone --value)"` to stamp reports in your timezone; containers use UTC by default.
- Anything after the image name is passed to the tool, so every CLI option works the same way.

## CLI Examples

```bash
# Only ERROR events
python3 src/log_analyzer.py --log logs/router.log --severity ERROR

# Custom report locations
python3 src/log_analyzer.py --log logs/router.log \
    --severity ERROR \
    --output reports/error_report.csv \
    --html-output reports/error_report.html

# A different configuration file
python3 src/log_analyzer.py --log logs/router.log --config my_config.ini

# Help
python3 src/log_analyzer.py --help

# The same options in Docker
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$(pwd)/logs:/app/logs" -v "$(pwd)/reports:/app/reports" \
  network-log-analyzer --log logs/router.log --severity WARNING
```

Invalid input stops with a clear message and exit code 2:

```
$ python3 src/log_analyzer.py --log logs/missing.log
error: log file not found: logs/missing.log

$ python3 src/log_analyzer.py --log logs/router.log --severity DEBUG
error: argument --severity: invalid choice: 'DEBUG' (choose from INFO, WARNING, ERROR, CRITICAL)
```

## Prometheus Metrics

The analyzer is a short-lived batch program, so Prometheus cannot scrape it while it runs. Metrics are therefore **opt-in** and can be exposed in two ways. Each run builds its own metrics, so the values describe that run only, and metrics are recorded only for a run that completes.

| Metric | Type | Meaning |
|---|---|---|
| `logs_processed_total` | Counter | Lines read from the input file |
| `log_info_total`, `log_warning_total`, `log_error_total`, `log_critical_total` | Counter | Parsed lines per severity (always the whole log, even with `--severity`) |
| `log_parse_errors_total` | Counter | Lines that did not match the expected format |
| `analyzer_runs_total` | Counter | Completed runs |
| `analyzer_processing_seconds` | Histogram | Time to process the log file |
| `log_error_rate_percent` | Gauge | ERROR lines as a percentage of parsed lines |
| `analyzer_last_run_timestamp_seconds` | Gauge | Unix time the last run completed |

**Write a text file** (for the Prometheus node exporter's textfile collector, or just to inspect):

```bash
python3 src/log_analyzer.py --log logs/router.log --metrics-output reports/metrics.prom
```

**Serve `/metrics` over HTTP** (Prometheus can scrape it; press Ctrl+C to stop):

```bash
python3 src/log_analyzer.py --log logs/router.log --metrics-port 9108
curl http://127.0.0.1:9108/metrics
```

In Docker the server must listen on all interfaces inside the container:

```bash
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$(pwd)/logs:/app/logs" -v "$(pwd)/reports:/app/reports" \
  -p 127.0.0.1:9108:9108 \
  network-log-analyzer --log logs/router.log --metrics-port 9108 --metrics-addr 0.0.0.0
```

Example (`reports/metrics.prom`, shortened):

```
logs_processed_total 11.0
log_info_total 4.0
log_warning_total 3.0
log_error_total 3.0
log_critical_total 1.0
log_parse_errors_total 0.0
analyzer_runs_total 1.0
analyzer_processing_seconds_count 1.0
log_error_rate_percent 27.27272727272727
```

## Web API

A FastAPI service wraps the same analysis code so it can be triggered over HTTP instead of the command line, and so Prometheus can scrape `/metrics` continuously (the CLI's `--metrics-port` only serves one run before exiting).

Start it locally:

```bash
uvicorn api:app --app-dir src --host 127.0.0.1 --port 8000
```

Interactive docs (Swagger UI) are then at `http://127.0.0.1:8000/docs`.

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Liveness/readiness check |
| `/analyze` | POST | Run the analyzer on a log file, return the JSON summary |
| `/reports/csv` | GET | Return the most recently generated CSV report |
| `/reports/html` | GET | Return the most recently generated HTML report |
| `/metrics` | GET | Prometheus metrics in text format, for continuous scraping |

`POST /analyze` body:

```json
{
  "log_path": "logs/router.log",
  "severity": "ERROR",
  "output": "reports/log_report.csv",
  "html_output": "reports/network_log_report.html"
}
```

Only `log_path` is required; `severity`, `output` and `html_output` default the same way the CLI's `--severity`, `--output` and `--html-output` do.

```bash
curl -X POST http://127.0.0.1:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"log_path": "logs/router.log"}'

curl http://127.0.0.1:8000/metrics
```

### Running the API in Docker

`docker-compose.yml` runs the API from the same image as the CLI, without any changes to the `Dockerfile` — it just overrides the entrypoint for the `api` service (Compose's `entrypoint`/`command` keys), the same override shown above expressed as a reusable service instead of a one-off flag.

```bash
docker compose up -d api
curl http://127.0.0.1:8000/health
docker compose logs -f api      # follow logs
docker compose down             # stop and remove
```

- The container listens on `0.0.0.0` inside Docker but is only published to `127.0.0.1` on the host by default. Set `API_PORT` to publish on a different host port, e.g. `API_PORT=8080 docker compose up -d api`.
- `./logs` and `./reports` are mounted the same way as the plain `docker run` CLI usage above, so files land on your host.
- The service has a `HEALTHCHECK` that polls `GET /health` (visible in `docker compose ps`).

The existing CLI is also available through Compose, unchanged, for one-shot runs:

```bash
docker compose --profile cli run --rm analyzer --log logs/router.log
```

(`analyzer` is behind the `cli` profile so a plain `docker compose up` only starts the long-running `api` service, not a one-shot job.)

## Observability: Prometheus + Grafana

`docker-compose.yml` also runs a Prometheus server that scrapes the API's `/metrics` continuously, and a Grafana dashboard on top of it — so the metrics from [Prometheus Metrics](#prometheus-metrics) above become a history you can actually watch, not just a snapshot from one `curl`.

```bash
docker compose up -d api prometheus grafana
```

- **Prometheus** — `http://127.0.0.1:9090` (override with `PROMETHEUS_PORT`). Configured by `prometheus/prometheus.yml`, which scrapes `api:8000/metrics` every 15s. Check `http://127.0.0.1:9090/targets` to confirm the scrape is `UP`.
- **Grafana** — `http://127.0.0.1:3000` (override with `GRAFANA_PORT`), default login `admin` / `admin` (change `GRAFANA_ADMIN_PASSWORD` before exposing it beyond localhost). The Prometheus datasource and a "Network Log Analyzer" dashboard are auto-provisioned from `grafana/provisioning/` and `grafana/dashboards/` — no manual setup.

The dashboard has 6 panels, all reading the same metrics `analyzer_metrics.py` already defines (no new instrumentation): total runs, current error rate, seconds since the last run, average processing duration, log counts per severity over time, and lines processed vs. parse errors over time. Trigger a few analyses (`docker compose --profile cli run --rm analyzer --log logs/router.log`, or `POST /analyze`) and the panels will show data on the next 15s scrape.

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

```
164 passed in 2.43s
```

GitHub Actions (`.github/workflows/ci.yml`) runs the same tests and builds the Docker image on every push and pull request.

The tests use a small log stored in `tests/data/`, write only to temporary folders, and never touch your real `config.ini`, `logs/` or `reports/`. They cover parsing, the DataFrame and filter, the analysis numbers, CSV and HTML output, CLI validation, configuration and logging.

## Example Output

Running `python3 src/log_analyzer.py --log logs/router.log` on the sample log ends with:

```
================================
 Network Operations Summary
================================
Total events      : 11
INFO count        : 4
WARNING count     : 3
ERROR count       : 3
CRITICAL count    : 1
Error rate        : 27.27%

Top IP addresses:
  10.10.10.1      2 event(s)
  192.168.1.50    1 event(s)

Failure counts:
  Interface failures      : 1
  BGP neighbor failures   : 1
  Authentication failures : 1

Critical event summary:
  2026-09-19 08:20:12  Power supply failure detected

Top error messages:
  1x  Interface GigabitEthernet0/2 is DOWN
  1x  BGP neighbor 10.10.10.1 is DOWN
  1x  Authentication failure from 192.168.1.50

CSV report created successfully
File: reports/log_report.csv

HTML report created successfully
File: reports/network_log_report.html
```

`reports/log_report.csv`:

```
date,time,severity,ip,message
2026-09-19,08:10:21,ERROR,10.10.10.1,BGP neighbor 10.10.10.1 is DOWN
2026-09-19,08:15:42,ERROR,192.168.1.50,Authentication failure from 192.168.1.50
...
```

`logs/application.log`:

```
2026-09-19 11:31:49,446 | INFO     | Application started
2026-09-19 11:31:49,447 | INFO     | Loading log file: logs/router.log
2026-09-19 11:31:49,447 | INFO     | Parsed 11 of 11 lines
2026-09-19 11:31:49,469 | INFO     | CSV report written: reports/log_report.csv (11 rows)
2026-09-19 11:31:49,470 | INFO     | HTML report written: reports/network_log_report.html
2026-09-19 11:31:49,470 | INFO     | Application finished successfully
```

## Future Roadmap

- [x] GitHub Actions to run the tests and build the Docker image on every push
- [x] Web API to trigger analyses and fetch reports over HTTP
- [x] Docker Compose setup for the API, alongside the existing CLI
- [x] Prometheus scrape configuration and a Grafana dashboard
- [ ] Handle a log with no valid lines (currently it stops with a `KeyError`, which is logged)
- [ ] Support more log formats and configurable failure keywords
- [ ] Filter by date and time range
- [ ] Alerting rules on top of the Prometheus metrics
- [ ] File upload for `/analyze` instead of a server-side path
- [ ] Add a licence
