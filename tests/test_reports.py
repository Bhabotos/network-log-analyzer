import pandas as pd
import pytest

from log_analyzer import (
    CSV_COLUMNS,
    build_html_report,
    filter_by_severity,
    write_csv_report,
    write_html_report,
)


# H. CSV report generation
def test_csv_has_header_and_all_rows(sample_df, tmp_path):
    report = tmp_path / "report.csv"
    write_csv_report(sample_df, str(report))

    lines = report.read_text().splitlines()
    assert lines[0] == "date,time,severity,ip,message"
    assert len(lines) == 1 + 8


def test_csv_round_trip_keeps_data(sample_df, tmp_path):
    report = tmp_path / "report.csv"
    write_csv_report(sample_df, str(report))

    loaded = pd.read_csv(report, keep_default_na=False)
    assert list(loaded.columns) == CSV_COLUMNS
    assert loaded["message"].tolist() == sample_df["message"].tolist()


def test_csv_has_no_index_column(sample_df, tmp_path):
    report = tmp_path / "report.csv"
    write_csv_report(sample_df, str(report))
    assert report.read_text().splitlines()[1].startswith("2026-01-10,")


def test_csv_contains_only_filtered_rows(sample_df, tmp_path):
    report = tmp_path / "errors.csv"
    write_csv_report(filter_by_severity(sample_df, "ERROR"), str(report))
    assert len(report.read_text().splitlines()) == 1 + 4


def test_csv_creates_missing_directory(sample_df, tmp_path, capsys):
    report = tmp_path / "new" / "sub" / "report.csv"
    write_csv_report(sample_df, str(report))

    assert report.exists()
    assert "CSV report created successfully" in capsys.readouterr().out


def test_csv_bad_directory_exits_with_error(sample_df, tmp_path, capsys):
    blocker = tmp_path / "a_file"
    blocker.write_text("x")

    with pytest.raises(SystemExit) as exc:
        write_csv_report(sample_df, str(blocker / "report.csv"))

    assert exc.value.code == 1
    assert "Could not create CSV report" in capsys.readouterr().out


# K. HTML report generation
@pytest.fixture
def html_text(sample_df, summary):
    return build_html_report(summary, sample_df, None, "2026-01-10 12:00:00")


def test_html_has_title_and_timestamp(html_text):
    assert "<title>Network Log Analyzer</title>" in html_text
    assert "<h1>Network Log Analyzer</h1>" in html_text
    assert "Report generated: 2026-01-10 12:00:00" in html_text


def test_html_has_all_sections(html_text):
    for heading in [
        "Summary",
        "Top Source IPs",
        "Network Issues",
        "Top Error Messages",
        "Detailed Logs",
    ]:
        assert f"<h2>{heading}</h2>" in html_text


def test_html_summary_cards(html_text):
    for label in ["Total Events", "INFO", "WARNING", "ERROR", "CRITICAL", "Error Rate"]:
        assert f'<div class="label">{label}</div>' in html_text
    assert '<div class="value">50.00%</div>' in html_text
    assert '<div class="value">8</div>' in html_text


def test_html_network_issues_and_ips(html_text):
    assert "<td>BGP neighbor failures</td><td>2</td>" in html_text
    assert "<td>10.0.0.1</td><td>2</td>" in html_text


def test_html_detail_table_has_every_row(html_text):
    assert html_text.count("<td>2026-01-10</td>") == 8
    assert '<span class="badge CRITICAL">CRITICAL</span>' in html_text


def test_html_escapes_log_text(summary):
    evil = pd.DataFrame(
        [
            {
                "date": "2026-01-10",
                "time": "10:00:00",
                "severity": "ERROR",
                "ip": "N/A",
                "message": "<script>alert(1)</script>",
            }
        ]
    )
    text = build_html_report(summary, evil, None, "now")

    assert "<script>" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text


def test_html_shows_filter_note(sample_df, summary):
    text = build_html_report(summary, filter_by_severity(sample_df, "ERROR"), "ERROR", "now")
    assert "filtered by severity: ERROR" in text


def test_html_empty_table_message(summary):
    empty = pd.DataFrame(columns=CSV_COLUMNS)
    text = build_html_report(summary, empty, None, "now")
    assert "No log entries to show." in text


def test_write_html_report_creates_file_and_directory(tmp_path, capsys):
    report = tmp_path / "out" / "report.html"
    write_html_report(str(report), "<html></html>")

    assert report.read_text() == "<html></html>"
    output = capsys.readouterr().out
    assert "HTML report created successfully" in output
    assert f"File: {report}" in output


def test_write_html_report_bad_directory_exits(tmp_path, capsys):
    blocker = tmp_path / "a_file"
    blocker.write_text("x")

    with pytest.raises(SystemExit) as exc:
        write_html_report(str(blocker / "report.html"), "<html></html>")

    assert exc.value.code == 1
    assert "Could not create HTML report" in capsys.readouterr().out
