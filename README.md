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
- **109 automated tests** with pytest

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
- `re`, `argparse`, `configparser`, `logging` (Python standard library)
- pytest
- Docker

## Project Structure

```
network-log-analyzer/
├── src/
│   └── log_analyzer.py        # parsing, analysis, reports, CLI, logging
├── tests/
│   ├── data/sample.log        # small log used by the tests
│   ├── conftest.py            # shared fixtures and test isolation
│   ├── test_parsing.py        # regex extraction
│   ├── test_dataframe.py      # DataFrame and severity filter
│   ├── test_analysis.py       # network analysis calculations
│   ├── test_reports.py        # CSV and HTML reports
│   ├── test_cli.py            # arguments, validation, end-to-end runs
│   ├── test_config.py         # configuration file
│   └── test_logging.py        # application logging
├── logs/
│   └── router.log             # sample input (application.log is generated here)
├── reports/                   # generated CSV and HTML reports
├── config.ini                 # default settings
├── Dockerfile
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

## Testing

```bash
pip install -r requirements-dev.txt
pytest
```

```
109 passed in 1.03s
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
- [ ] Handle a log with no valid lines (currently it stops with a `KeyError`, which is logged)
- [ ] Support more log formats and configurable failure keywords
- [ ] Filter by date and time range
- [ ] Docker Compose setup
- [ ] Web API for uploading logs
- [ ] Add a licence
