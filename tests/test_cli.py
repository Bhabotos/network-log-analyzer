import subprocess
import sys
from pathlib import Path

import pytest

from log_analyzer import main, parse_arguments

SCRIPT = Path(__file__).parent.parent / "src" / "log_analyzer.py"


# I. CLI argument validation
def test_defaults(sample_log_path):
    args = parse_arguments(["--log", str(sample_log_path)])

    assert args.severity is None
    assert args.output == "reports/log_report.csv"
    assert args.html_output == "reports/network_log_report.html"


def test_all_options_are_read(sample_log_path):
    args = parse_arguments(
        [
            "--log", str(sample_log_path),
            "--severity", "ERROR",
            "--output", "a.csv",
            "--html-output", "a.html",
        ]
    )

    assert args.severity == "ERROR"
    assert args.output == "a.csv"
    assert args.html_output == "a.html"


def test_severity_is_case_insensitive(sample_log_path):
    args = parse_arguments(["--log", str(sample_log_path), "--severity", "warning"])
    assert args.severity == "WARNING"


def test_invalid_severity_is_rejected(sample_log_path, capsys):
    with pytest.raises(SystemExit) as exc:
        parse_arguments(["--log", str(sample_log_path), "--severity", "DEBUG"])

    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_log_argument_is_required(capsys):
    with pytest.raises(SystemExit) as exc:
        parse_arguments([])

    assert exc.value.code == 2
    assert "--log" in capsys.readouterr().err


def test_html_output_cannot_be_a_directory(sample_log_path, tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        parse_arguments(["--log", str(sample_log_path), "--html-output", str(tmp_path)])

    assert exc.value.code == 2
    assert "must be a file" in capsys.readouterr().err


def test_html_and_csv_output_must_differ(sample_log_path, tmp_path, capsys):
    same = str(tmp_path / "same.out")
    with pytest.raises(SystemExit) as exc:
        parse_arguments(
            ["--log", str(sample_log_path), "--output", same, "--html-output", same]
        )

    assert exc.value.code == 2
    assert "must be different files" in capsys.readouterr().err


# J. Invalid log file handling
def test_missing_log_file_is_rejected(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        parse_arguments(["--log", str(tmp_path / "nope.log")])

    assert exc.value.code == 2
    assert "log file not found" in capsys.readouterr().err


def test_log_path_that_is_a_folder_is_rejected(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        parse_arguments(["--log", str(tmp_path)])

    assert exc.value.code == 2


# End-to-end runs
def test_main_creates_both_reports(sample_log_path, tmp_path, capsys):
    csv_file = tmp_path / "out.csv"
    html_file = tmp_path / "out.html"

    main(
        [
            "--log", str(sample_log_path),
            "--output", str(csv_file),
            "--html-output", str(html_file),
        ]
    )

    output = capsys.readouterr().out
    assert "Total Logs      : 8" in output
    assert "Error rate        : 50.00%" in output
    assert "CSV report created successfully" in output
    assert "HTML report created successfully" in output
    assert len(csv_file.read_text().splitlines()) == 9
    assert "<h1>Network Log Analyzer</h1>" in html_file.read_text()


def test_main_severity_filter_limits_csv_but_not_summary(sample_log_path, tmp_path, capsys):
    csv_file = tmp_path / "errors.csv"

    main(
        [
            "--log", str(sample_log_path),
            "--severity", "ERROR",
            "--output", str(csv_file),
            "--html-output", str(tmp_path / "errors.html"),
        ]
    )

    assert len(csv_file.read_text().splitlines()) == 1 + 4
    assert "Total events      : 8" in capsys.readouterr().out


def test_script_exit_code_for_invalid_file(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--log", str(tmp_path / "missing.log")],
        capture_output=True,
        text=True,
        cwd=tmp_path,  # relative paths (logs/application.log) stay inside the temp folder
    )

    assert result.returncode == 2
    assert "log file not found" in result.stderr


def test_script_runs_from_command_line(sample_log_path, tmp_path):
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--log", str(sample_log_path),
            "--output", str(tmp_path / "c.csv"),
            "--html-output", str(tmp_path / "h.html"),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,  # relative paths (logs/application.log) stay inside the temp folder
    )

    assert result.returncode == 0
    assert "HTML report created successfully" in result.stdout
