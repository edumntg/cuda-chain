# The plasmon engine: coordinator API, scheduler worker, or trainer. CPU PyTorch.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLASMON_DATA_DIR=/data \
    PLASMON_CACHE_DIR=/cache

RUN apt-get update -q && apt-get install -y -q --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 plasmon

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY python ./python
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install ".[engine]"

USER plasmon
VOLUME ["/data", "/cache"]
EXPOSE 7117
HEALTHCHECK --interval=30s --timeout=5s CMD curl -fsS http://127.0.0.1:7117/v1/healthz || exit 1
CMD ["python", "-m", "plasmon.coordinator", "/data/plasmon-server.yaml"]
