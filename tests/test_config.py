import pytest

import log_analyzer
from log_analyzer import (
    ConfigError,
    DEFAULT_CONFIG,
    compute_operations_summary,
    find_config_path,
    load_config,
    main,
    parse_arguments,
)


def write_config(tmp_path, text):
    path = tmp_path / "test_config.ini"
    path.write_text(text)
    return str(path)


# load_config
def test_missing_default_config_uses_builtin_defaults(tmp_path):
    config = load_config(str(tmp_path / "missing.ini"))
    assert config["reports"]["csv_output"] == "reports/log_report.csv"
    assert config["logging"]["level"] == "INFO"
    assert config["application"]["top_n"] == 5


def test_missing_required_config_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="config file not found"):
        load_config(str(tmp_path / "missing.ini"), required=True)


def test_file_values_override_defaults(tmp_path):
    path = write_config(
        tmp_path,
        "[logging]\nlevel = debug\nfile = my/app.log\n"
        "[reports]\ncsv_output = out/a.csv\nhtml_output = out/a.html\n"
        "[application]\ntop_n = 3\n",
    )
    config = load_config(path)

    assert config["logging"] == {"level": "DEBUG", "file": "my/app.log"}
    assert config["reports"] == {"csv_output": "out/a.csv", "html_output": "out/a.html"}
    assert config["application"]["top_n"] == 3


def test_partial_config_keeps_other_defaults(tmp_path):
    config = load_config(write_config(tmp_path, "[application]\ntop_n = 2\n"))

    assert config["application"]["top_n"] == 2
    assert config["logging"]["file"] == DEFAULT_CONFIG["logging"]["file"]


def test_loading_does_not_change_builtin_defaults(tmp_path):
    load_config(write_config(tmp_path, "[application]\ntop_n = 9\n"))
    assert DEFAULT_CONFIG["application"]["top_n"] == 5


@pytest.mark.parametrize(
    "text, message",
    [
        ("[logging]\nlevel = LOUD\n", "invalid log level"),
        ("[application]\ntop_n = many\n", "top_n must be a whole number"),
        ("[application]\ntop_n = 0\n", "top_n must be 1 or more"),
        ("[reports]\ncsv_output =\n", "must not be empty"),
        ("this is not an ini file\n", "could not read config file"),
    ],
)
def test_invalid_config_values_are_rejected(tmp_path, text, message):
    with pytest.raises(ConfigError, match=message):
        load_config(write_config(tmp_path, text))


def test_percent_sign_in_a_path_is_allowed(tmp_path):
    config = load_config(write_config(tmp_path, "[reports]\ncsv_output = out/100%.csv\n"))
    assert config["reports"]["csv_output"] == "out/100%.csv"


# find_config_path and parse_arguments
def test_find_config_path_default():
    path, given = find_config_path(["--log", "x.log"])
    assert path == log_analyzer.DEFAULT_CONFIG_PATH
    assert given is False


def test_find_config_path_explicit():
    path, given = find_config_path(["--log", "x.log", "--config", "my.ini"])
    assert (path, given) == ("my.ini", True)


def test_config_supplies_report_defaults(sample_log_path, tmp_path):
    config = load_config(
        write_config(tmp_path, "[reports]\ncsv_output = c.csv\nhtml_output = h.html\n")
    )
    args = parse_arguments(["--log", str(sample_log_path)], config)

    assert args.output == "c.csv"
    assert args.html_output == "h.html"


def test_command_line_beats_config(sample_log_path, tmp_path):
    config = load_config(write_config(tmp_path, "[reports]\ncsv_output = c.csv\n"))
    args = parse_arguments(["--log", str(sample_log_path), "--output", "cli.csv"], config)

    assert args.output == "cli.csv"


# top_n
def test_top_n_limits_top_lists(sample_df):
    result = compute_operations_summary(sample_df, top_n=1)

    assert result["top_ips"] == [("10.0.0.1", 2)]
    assert len(result["top_errors"]) == 1


def test_top_n_defaults_to_five(sample_df):
    assert len(compute_operations_summary(sample_df)["top_errors"]) == 3


# main() with a config file
def test_main_uses_paths_from_config(sample_log_path, tmp_path, capsys):
    config = write_config(
        tmp_path,
        f"[logging]\nfile = {tmp_path}/my.log\n"
        f"[reports]\ncsv_output = {tmp_path}/c.csv\nhtml_output = {tmp_path}/h.html\n",
    )
    main(["--log", str(sample_log_path), "--config", config])

    assert (tmp_path / "c.csv").exists()
    assert (tmp_path / "h.html").exists()
    assert f"File: {tmp_path}/c.csv" in capsys.readouterr().out


def test_main_top_n_from_config(sample_log_path, tmp_path, capsys):
    config = write_config(
        tmp_path,
        f"[logging]\nfile = {tmp_path}/my.log\n[application]\ntop_n = 1\n"
        f"[reports]\ncsv_output = {tmp_path}/c.csv\nhtml_output = {tmp_path}/h.html\n",
    )
    main(["--log", str(sample_log_path), "--config", config])

    out = capsys.readouterr().out
    assert "10.0.0.1" in out.split("Top IP addresses:")[1]
    assert "192.168.5.5" not in out.split("Top IP addresses:")[1].split("Failure counts:")[0]


def test_main_missing_config_file_exits_with_error(sample_log_path, tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--log", str(sample_log_path), "--config", str(tmp_path / "nope.ini")])

    assert exc.value.code == 2
    assert "config file not found" in capsys.readouterr().err


def test_main_bad_config_value_exits_with_error(sample_log_path, tmp_path, capsys):
    config = write_config(tmp_path, "[logging]\nlevel = LOUD\n")

    with pytest.raises(SystemExit) as exc:
        main(["--log", str(sample_log_path), "--config", config])

    assert exc.value.code == 2
    assert "invalid log level" in capsys.readouterr().err
