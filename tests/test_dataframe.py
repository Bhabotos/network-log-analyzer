import pandas as pd

from log_analyzer import CSV_COLUMNS, build_dataframe, filter_by_severity


# F. DataFrame creation
def test_dataframe_has_one_row_per_valid_line(sample_df):
    assert isinstance(sample_df, pd.DataFrame)
    assert len(sample_df) == 8


def test_dataframe_has_expected_columns(sample_df):
    assert set(CSV_COLUMNS) <= set(sample_df.columns)


def test_dataframe_values(sample_df):
    first = sample_df.iloc[0]
    assert first["date"] == "2026-01-10"
    assert first["time"] == "10:00:00"
    assert first["severity"] == "INFO"
    assert first["ip"] == "N/A"
    assert first["message"] == "System boot complete"


def test_unparseable_lines_are_skipped_and_reported(capsys):
    lines = [
        "2026-01-10 10:00:00 INFO ok\n",
        "garbage line\n",
        "2026-01-10 10:01:00 ERROR bad\n",
    ]
    df = build_dataframe(lines)

    assert len(df) == 2
    assert "Could not parse: garbage line" in capsys.readouterr().out


# G. Severity filtering
def test_filter_keeps_only_requested_severity(sample_df):
    errors = filter_by_severity(sample_df, "ERROR")
    assert len(errors) == 4
    assert set(errors["severity"]) == {"ERROR"}


def test_filter_single_result(sample_df):
    critical = filter_by_severity(sample_df, "CRITICAL")
    assert list(critical["message"]) == ["Power supply failure detected"]


def test_no_filter_returns_everything(sample_df):
    assert len(filter_by_severity(sample_df, None)) == 8


def test_filter_does_not_change_original(sample_df):
    filter_by_severity(sample_df, "INFO")
    assert len(sample_df) == 8
