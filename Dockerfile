FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Unprivileged user. Override the IDs at build time (--build-arg) or at run
# time (docker run --user) so files written to mounted folders belong to you.
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --no-create-home \
       --shell /usr/sbin/nologin app

WORKDIR /app

# Dependencies first: this layer is cached until requirements.txt changes
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/ src/
COPY config.ini .

# Mount points for host folders (config.ini uses these relative paths)
RUN mkdir -p logs reports && chown app:app logs reports

USER app

# The app runs once and exits, so this only matters for a long-running container.
# It checks that the app, pandas and the config file load.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --start-interval=2s --retries=3 \
    CMD ["python", "-c", "import sys; sys.path.insert(0, 'src'); import log_analyzer as a; a.load_config(a.DEFAULT_CONFIG_PATH, required=True)"]

ENTRYPOINT ["python", "src/log_analyzer.py"]
CMD ["--log", "logs/router.log"]
