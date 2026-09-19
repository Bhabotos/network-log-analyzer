import pytest

from log_analyzer import parse_log_line

BGP_LINE = "2026-09-19 08:10:21 ERROR BGP neighbor 10.10.10.1 is DOWN"


# A. Log parsing
def test_valid_line_returns_all_fields():
    entry = parse_log_line(BGP_LINE)
    assert set(entry) == {"date", "time", "severity", "message", "ip"}


def test_trailing_newline_is_ignored():
    assert parse_log_line(BGP_LINE + "\n")["message"] == "BGP neighbor 10.10.10.1 is DOWN"


@pytest.mark.parametrize(
    "bad_line",
    [
        "",
        "garbage line",
        "2026-09-19 ERROR missing time",
        "2026-09-19 08:10:21 DEBUG unknown severity",
        "19-09-2026 08:10:21 ERROR wrong date format",
    ],
)
def test_invalid_lines_return_none(bad_line):
    assert parse_log_line(bad_line) is None


# B. Date/time extraction
def test_date_extraction():
    assert parse_log_line(BGP_LINE)["date"] == "2026-09-19"


def test_time_extraction():
    assert parse_log_line(BGP_LINE)["time"] == "08:10:21"


# C. Severity extraction
@pytest.mark.parametrize("severity", ["INFO", "WARNING", "ERROR", "CRITICAL"])
def test_severity_extraction(severity):
    line = f"2026-09-19 08:00:00 {severity} something happened"
    assert parse_log_line(line)["severity"] == severity


# D. IP extraction
def test_ip_is_extracted_from_message():
    assert parse_log_line(BGP_LINE)["ip"] == "10.10.10.1"


def test_missing_ip_becomes_na():
    line = "2026-09-19 08:01:12 INFO Router started successfully"
    assert parse_log_line(line)["ip"] == "N/A"


def test_only_first_ip_is_used():
    line = "2026-09-19 08:00:00 INFO route from 10.0.0.1 to 10.0.0.2"
    assert parse_log_line(line)["ip"] == "10.0.0.1"


def test_interface_name_is_not_mistaken_for_ip():
    line = "2026-09-19 08:02:15 INFO Interface GigabitEthernet0/1 is UP"
    assert parse_log_line(line)["ip"] == "N/A"


# E. Message extraction
def test_message_extraction():
    assert parse_log_line(BGP_LINE)["message"] == "BGP neighbor 10.10.10.1 is DOWN"


def test_message_keeps_special_characters():
    line = "2026-09-19 08:05:33 WARNING High CPU utilization detected: 82%"
    assert parse_log_line(line)["message"] == "High CPU utilization detected: 82%"
