# Nankle kernel image (the dispatch chokepoint HTTP surface, P2).
#
# Identical base across environments; config is injected via env + manifest
# (P7, NFR-PORT-01). Honours an optional corporate egress proxy and a custom CA
# bundle for installs behind a TLS-inspecting proxy (US-DEP-04).
#
# Corporate proxy: pass --build-arg HTTPS_PROXY=http://proxy:3128 (and HTTP_PROXY
#                  / NO_PROXY) at build time; set them again in .env for runtime.
# Corporate CA:    drop your PEM at deploy/ca-bundle.crt before building; it is
#                  installed into the trust store automatically (else skipped).

FROM python:3.12-slim AS base

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

# Install the project from pyproject (kernel needs only the base dependencies).
# Copy metadata + package first so the layer caches across source-only edits.
COPY pyproject.toml /app/pyproject.toml
COPY nankle/ /app/nankle/
RUN pip install .

EXPOSE 8000

# Compose overrides this; it is the sensible default for `docker run`.
CMD ["uvicorn", "nankle.api.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
