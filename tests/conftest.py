from pathlib import Path

import pytest

import log_analyzer

SAMPLE_LOG = Path(__file__).parent / "data" / "sample.log"


@pytest.fixture(autouse=True)
def isolate_app_environment(tmp_path_factory, monkeypatch):
    """Keep every test away from the real config.ini and logs/application.log."""
    folder = tmp_path_factory.mktemp("app")
    monkeypatch.setattr(log_analyzer, "DEFAULT_CONFIG_PATH", str(folder / "no_config.ini"))
    monkeypatch.setitem(
        log_analyzer.DEFAULT_CONFIG["logging"], "file", str(folder / "logs" / "application.log")
    )
    yield
    log_analyzer.reset_logging()


@pytest.fixture
def sample_log_path():
    """Path to the small test log (8 lines) stored in tests/data."""
    return SAMPLE_LOG


@pytest.fixture
def sample_lines():
    return SAMPLE_LOG.read_text().splitlines(keepends=True)


@pytest.fixture
def sample_df(sample_lines):
    """The parsed DataFrame for sample.log."""
    return log_analyzer.build_dataframe(sample_lines)


@pytest.fixture
def summary(sample_df):
    return log_analyzer.compute_operations_summary(sample_df)
