import pandas as pd
import pytest

from log_analyzer import CSV_COLUMNS, compute_operations_summary, count_matches


# L. Network analysis calculations
def test_total_events(summary):
    assert summary["total"] == 8


def test_severity_counts(summary):
    assert summary["counts"] == {"INFO": 2, "WARNING": 1, "ERROR": 4, "CRITICAL": 1}


def test_error_rate(summary):
    assert summary["error_rate"] == pytest.approx(50.0)


def test_top_ips_are_sorted_by_count(summary):
    assert summary["top_ips"] == [("10.0.0.1", 2), ("192.168.5.5", 1)]


def test_interface_failures(summary):
    # only "Interface ... is DOWN"; the "... is UP" line must not count
    assert summary["interface_failures"] == 1


def test_bgp_failures(summary):
    assert summary["bgp_failures"] == 2


def test_authentication_failures(summary):
    assert summary["auth_failures"] == 1


def test_critical_events(summary):
    assert summary["critical_events"] == [
        ("2026-01-10", "10:06:00", "Power supply failure detected")
    ]


def test_top_errors_most_repeated_first(summary):
    assert summary["top_errors"][0] == ("BGP neighbor 10.0.0.1 is DOWN", 2)
    assert len(summary["top_errors"]) == 3


def test_count_matches_is_case_insensitive(sample_df):
    assert count_matches(sample_df, "bgp", "down") == 2
    assert count_matches(sample_df, "BGP", "DOWN") == 2


def test_count_matches_requires_all_words(sample_df):
    assert count_matches(sample_df, "interface", "down") == 1
    assert count_matches(sample_df, "interface") == 2


def test_empty_severity_data_gives_zero_rate_and_empty_lists():
    empty = pd.DataFrame(columns=CSV_COLUMNS)
    result = compute_operations_summary(empty)

    assert result["total"] == 0
    assert result["error_rate"] == 0
    assert result["top_ips"] == []
    assert result["top_errors"] == []
    assert result["critical_events"] == []
