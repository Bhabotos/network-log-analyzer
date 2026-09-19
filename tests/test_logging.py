import logging

import pytest

import log_analyzer
from log_analyzer import main, setup_logging, write_csv_report, write_html_report


def run(sample_log_path, tmp_path, *extra, log_level="INFO", log_path=None):
    """Run main() with a temporary config, and return the application log text."""
    log_path = log_path or tmp_path / "application.log"
    config = tmp_path / "run_config.ini"
    config.write_text(
        f"[logging]\nlevel = {log_level}\nfile = {log_path}\n"
        f"[reports]\ncsv_output = {tmp_path}/r.csv\nhtml_output = {tmp_path}/r.html\n"
    )
    main(["--log", str(sample_log_path), "--config", str(config), *extra])
    return log_path.read_text()


# setup_logging
def test_setup_creates_log_file_and_folder(tmp_path):
    log_file = tmp_path / "deep" / "dir" / "app.log"
    setup_logging("INFO", str(log_file))
    log_analyzer.logger.info("hello")

    assert "INFO     | hello" in log_file.read_text()


def test_log_line_format(tmp_path):
    log_file = tmp_path / "app.log"
    setup_logging("WARNING", str(log_file))
    log_analyzer.logger.warning("careful")

    line = log_file.read_text().strip()
    parts = [part.strip() for part in line.split("|")]
    assert len(parts) == 3
    assert parts[1] == "WARNING"
    assert parts[2] == "careful"


def test_level_filters_messages(tmp_path):
    log_file = tmp_path / "app.log"
    setup_logging("WARNING", str(log_file))
    log_analyzer.logger.debug("d")
    log_analyzer.logger.info("i")
    log_analyzer.logger.warning("w")
    log_analyzer.logger.error("e")

    text = log_file.read_text()
    assert "| d" not in text and "| i" not in text
    assert "| w" in text and "| e" in text


def test_debug_level_records_everything(tmp_path):
    log_file = tmp_path / "app.log"
    setup_logging("DEBUG", str(log_file))
    log_analyzer.logger.debug("detail")

    assert "DEBUG    | detail" in log_file.read_text()


def test_repeated_setup_does_not_duplicate_lines(tmp_path):
    log_file = tmp_path / "app.log"
    for _ in range(3):
        setup_logging("INFO", str(log_file))
    log_analyzer.logger.info("once")

    assert log_file.read_text().count("once") == 1


def test_unwritable_log_file_only_warns(tmp_path, capsys):
    blocker = tmp_path / "a_file"
    blocker.write_text("x")

    setup_logging("INFO", str(blocker / "app.log"))
    log_analyzer.logger.info("still works")

    assert "cannot write log file" in capsys.readouterr().err


# events written by main()
def test_normal_run_logs_key_events(sample_log_path, tmp_path):
    text = run(sample_log_path, tmp_path)

    for expected in [
        "Application started",
        "Loaded configuration from",
        "Loading log file:",
        "Read 8 lines",
        "Parsed 8 of 8 lines",
        "CSV report written:",
        "HTML report written:",
        "Application finished successfully",
    ]:
        assert expected in text


def test_normal_run_has_no_warnings_or_errors(sample_log_path, tmp_path):
    text = run(sample_log_path, tmp_path)
    assert "WARNING" not in text
    assert "ERROR" not in text


def test_filtering_is_logged(sample_log_path, tmp_path):
    text = run(sample_log_path, tmp_path, "--severity", "ERROR")
    assert "Filtered by severity ERROR: 4 of 8 rows kept" in text


def test_empty_filter_result_logs_warning(tmp_path):
    log = tmp_path / "only_info.log"
    log.write_text("2026-01-10 10:00:00 INFO all good\n")

    text = run(log, tmp_path, "--severity", "CRITICAL")
    assert "WARNING  | No log entries with severity CRITICAL" in text


def test_unparseable_line_logs_warning(tmp_path):
    log = tmp_path / "mixed.log"
    log.write_text("2026-01-10 10:00:00 INFO ok\ngarbage line\n")

    text = run(log, tmp_path)
    assert "WARNING  | Skipping unparseable line 2: 'garbage line'" in text
    assert "Parsed 1 of 2 lines" in text


def test_info_level_hides_debug_but_debug_level_shows_it(sample_log_path, tmp_path):
    info_text = run(sample_log_path, tmp_path, log_level="INFO")
    assert "DEBUG" not in info_text

    debug_log = tmp_path / "debug.log"
    debug_text = run(sample_log_path, tmp_path, log_level="DEBUG", log_path=debug_log)
    assert "DEBUG    | Parsed line 1:" in debug_text
    assert "DEBUG    | Operations summary:" in debug_text


def test_log_messages_do_not_appear_on_console(sample_log_path, tmp_path, capsys):
    run(sample_log_path, tmp_path)
    captured = capsys.readouterr()

    assert "Application started" not in captured.out + captured.err


def test_log_file_is_appended_not_overwritten(sample_log_path, tmp_path):
    run(sample_log_path, tmp_path)
    text = run(sample_log_path, tmp_path)

    assert text.count("Application started") == 2


# invalid input and exceptions
def test_invalid_input_is_logged_as_error(tmp_path):
    log_file = tmp_path / "app.log"
    config = tmp_path / "c.ini"
    config.write_text(f"[logging]\nfile = {log_file}\n")

    with pytest.raises(SystemExit) as exc:
        main(["--log", str(tmp_path / "nope.log"), "--config", str(config)])

    assert exc.value.code == 2
    assert "ERROR    | Invalid input: log file not found" in log_file.read_text()


def test_invalid_severity_is_logged(sample_log_path, tmp_path):
    log_file = tmp_path / "app.log"
    config = tmp_path / "c.ini"
    config.write_text(f"[logging]\nfile = {log_file}\n")

    with pytest.raises(SystemExit):
        main(["--log", str(sample_log_path), "--severity", "DEBUG", "--config", str(config)])

    assert "Invalid input: argument --severity: invalid choice" in log_file.read_text()


def test_bad_config_is_logged_to_default_log(sample_log_path, tmp_path):
    config = tmp_path / "c.ini"
    config.write_text("[application]\ntop_n = zero\n")

    with pytest.raises(SystemExit):
        main(["--log", str(sample_log_path), "--config", str(config)])

    default_log = log_analyzer.DEFAULT_CONFIG["logging"]["file"]
    with open(default_log) as file:
        assert "ERROR    | Invalid configuration:" in file.read()


def test_csv_failure_is_logged_with_traceback(sample_df, tmp_path, caplog):
    blocker = tmp_path / "a_file"
    blocker.write_text("x")

    with caplog.at_level(logging.ERROR, logger=log_analyzer.LOGGER_NAME):
        with pytest.raises(SystemExit):
            write_csv_report(sample_df, str(blocker / "r.csv"))

    record = caplog.records[0]
    assert record.levelname == "ERROR"
    assert "Could not create CSV report" in record.getMessage()
    assert record.exc_info is not None


def test_html_failure_is_logged_with_traceback(tmp_path, caplog):
    blocker = tmp_path / "a_file"
    blocker.write_text("x")

    with caplog.at_level(logging.ERROR, logger=log_analyzer.LOGGER_NAME):
        with pytest.raises(SystemExit):
            write_html_report(str(blocker / "r.html"), "<html></html>")

    assert caplog.records[0].exc_info is not None
    assert "Could not create HTML report" in caplog.records[0].getMessage()


def test_unexpected_exception_is_logged_and_re_raised(tmp_path):
    no_valid_lines = tmp_path / "bad.log"
    no_valid_lines.write_text("garbage\n")
    log_file = tmp_path / "app.log"

    with pytest.raises(KeyError):
        run(no_valid_lines, tmp_path, log_path=log_file)

    text = log_file.read_text()
    assert "ERROR    | Unexpected error" in text
    assert "Traceback" in text
    assert "KeyError" in text
    assert "Application finished successfully" not in text
