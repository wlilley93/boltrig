# Boltrig kernel image (the dispatch chokepoint HTTP surface, P2).
#
# Identical base across environments; config is injected via env + manifest
# (P7, NFR-PORT-01). Honours an optional corporate egress proxy and a custom CA
# bundle for installs behind a TLS-inspecting proxy (US-DEP-04).
#
# Corporate proxy: pass --build-arg HTTPS_PROXY=http://proxy:3128 (and HTTP_PROXY
#                  / NO_PROXY) at build time; set them again in .env for runtime.
# Corporate CA:    drop your PEM at deploy/ca-bundle.crt before building; it is
#                  installed into the trust store automatically (else skipped).

# IAC-002: pinned to a stable tag + digest.
FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7 AS base

# Build-time egress proxy (harmless when empty). pip honours these env vars.
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

# Optional corporate CA bundle. We copy the whole deploy/ dir (so the build
# never fails when no PEM is present) and install it only if a non-empty
# deploy/ca-bundle.crt exists.
COPY deploy/ /app/deploy/
RUN if [ -s /app/deploy/ca-bundle.crt ]; then \
        apt-get update && apt-get install -y --no-install-recommends ca-certificates && \
        cp /app/deploy/ca-bundle.crt /usr/local/share/ca-certificates/corporate.crt && \
        update-ca-certificates && \
        rm -rf /var/lib/apt/lists/*; \
    fi
# Make Python / requests / httpx trust the system store at runtime too.
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

# DEP-001: install from a frozen, hash-verified lockfile instead of mutable
# ranges. The lockfile is generated from pyproject.toml with `uv pip compile`.
COPY pyproject.toml requirements-lock.txt /app/
RUN pip install --require-hashes -r /app/requirements-lock.txt

# Install the local package without re-resolving its dependencies.
COPY boltrig/ /app/boltrig/
RUN pip install --no-deps .

# Run as an unprivileged user (INF-01 defence in depth). The app reads /app + the
# read-only mounts and writes nothing to disk (logs go to stdout); the compose
# runs the container read-only with a tmpfs for /tmp.
RUN useradd --create-home --uid 10001 boltrig
USER boltrig

EXPOSE 8000

# Compose overrides this; it is the sensible default for `docker run`.
CMD ["uvicorn", "boltrig.api.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
