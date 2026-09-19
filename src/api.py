"""FastAPI service for the Network Log Analyzer.

A thin HTTP front end over the existing CLI functions: /analyze calls the same
run_analysis() the CLI uses, and /metrics exposes a shared AnalyzerMetrics
registry for Prometheus to scrape continuously (the CLI's --metrics-port only
serves metrics for one run before exiting).
"""

import argparse
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field, field_validator

import log_analyzer
from analyzer_metrics import AnalyzerMetrics


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = log_analyzer.load_config(log_analyzer.DEFAULT_CONFIG_PATH)
    log_analyzer.setup_logging(config["logging"]["level"], config["logging"]["file"])
    app.state.config = config
    app.state.metrics = AnalyzerMetrics()
    yield


app = FastAPI(
    title="Network Log Analyzer API",
    description="Run analyses, fetch the latest reports and scrape Prometheus "
    "metrics over HTTP, backed by the same code as the CLI.",
    lifespan=lifespan,
)


class AnalyzeRequest(BaseModel):
    log_path: str = Field(..., description="Path to the input log file, e.g. logs/router.log")
    severity: str | None = Field(
        None, description="Only keep this severity: " + ", ".join(log_analyzer.SEVERITIES)
    )
    output: str | None = Field(None, description="CSV report path (default: from config.ini)")
    html_output: str | None = Field(None, description="HTML report path (default: from config.ini)")

    @field_validator("severity")
    @classmethod
    def uppercase_and_validate_severity(cls, value):
        if value is None:
            return value
        value = value.upper()
        if value not in log_analyzer.SEVERITIES:
            raise ValueError(f"severity must be one of {', '.join(log_analyzer.SEVERITIES)}")
        return value


class Summary(BaseModel):
    total: int
    counts: dict[str, int]
    error_rate: float
    top_ips: list[tuple[str, int]]
    interface_failures: int
    bgp_failures: int
    auth_failures: int
    critical_events: list[tuple[str, str, str]]
    top_errors: list[tuple[str, int]]


class AnalyzeResponse(BaseModel):
    summary: Summary
    lines_read: int
    csv_report: str
    html_report: str


@app.get("/health")
def health():
    """Liveness/readiness check."""
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest):
    """Run the analyzer on a log file and return the summary as JSON."""
    config = app.state.config

    if not os.path.isfile(request.log_path):
        raise HTTPException(status_code=404, detail=f"log file not found: {request.log_path}")

    output = request.output or config["reports"]["csv_output"]
    html_output = request.html_output or config["reports"]["html_output"]
    if os.path.abspath(output) == os.path.abspath(html_output):
        raise HTTPException(
            status_code=400, detail="output and html_output must be different files"
        )

    args = argparse.Namespace(
        log=request.log_path,
        severity=request.severity,
        output=output,
        html_output=html_output,
    )

    started = time.perf_counter()
    summary, lines_read = log_analyzer.run_analysis(args, config)
    app.state.metrics.record_run(lines_read, summary, time.perf_counter() - started)

    return AnalyzeResponse(
        summary=summary, lines_read=lines_read, csv_report=output, html_report=html_output
    )


@app.get("/reports/csv")
def get_csv_report():
    """Return the most recently generated CSV report."""
    path = app.state.config["reports"]["csv_output"]
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"no CSV report at {path} yet; call /analyze first")
    return FileResponse(path, media_type="text/csv", filename=os.path.basename(path))


@app.get("/reports/html")
def get_html_report():
    """Return the most recently generated HTML report."""
    path = app.state.config["reports"]["html_output"]
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"no HTML report at {path} yet; call /analyze first")
    return FileResponse(path, media_type="text/html")


@app.get("/metrics")
def metrics():
    """Prometheus metrics, scraped continuously (the CLI's --metrics-port only serves one run)."""
    data = generate_latest(app.state.metrics.registry)
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
