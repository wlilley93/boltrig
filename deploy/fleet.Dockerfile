# Boltrig fleet image (the fleet runtime + durable workers, Epics F/G).
#
# Same shape as deploy/kernel.Dockerfile but installs the [durable,inference]
# extras so the worker can talk to Hatchet (durable execution) and to inference
# back ends. Honours the same optional corporate proxy + CA bundle (US-DEP-04).

FROM python:3.12-slim AS base

ARG HTTP_PROXY=""
ARG HTTPS_PROXY=""
ARG NO_PROXY=""
ENV HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    NO_PROXY=${NO_PROXY} \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Optional corporate CA bundle (see deploy/kernel.Dockerfile for details).
COPY deploy/ /app/deploy/
RUN if [ -s /app/deploy/ca-bundle.crt ]; then \
        apt-get update && apt-get install -y --no-install-recommends ca-certificates && \
        cp /app/deploy/ca-bundle.crt /usr/local/share/ca-certificates/corporate.crt && \
        update-ca-certificates && \
        rm -rf /var/lib/apt/lists/*; \
    fi
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

# Install the project plus the durable-execution and inference extras.
COPY pyproject.toml /app/pyproject.toml
COPY boltrig/ /app/boltrig/
RUN pip install ".[durable,inference]"

# Run as an unprivileged user (INF-01). Writes nothing to disk; compose runs it
# read-only with a tmpfs for /tmp.
RUN useradd --create-home --uid 10001 boltrig
USER boltrig

# Compose overrides this; it is the sensible default for `docker run`.
CMD ["python", "-m", "boltrig.api.worker"]
