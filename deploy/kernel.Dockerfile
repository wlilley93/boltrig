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
FROM python:3.12.13-slim-bookworm@sha256:8a7e7cc04fd3e2bd787f7f24e22d5d119aa590d429b50c95dfe12b3abe52f48b AS base

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

# Run directly from the copied, read-only source tree. Installing the project
# itself would invoke PEP 517 build isolation and download an unlocked hatchling
# toolchain; /app is the workdir and therefore already on Python's import path.
COPY boltrig/ /app/boltrig/

# Boltrig v2 cockpit runtime: ship Herdr with the stack, not from a developer
# workstation. Pinned release asset + sha256; override all three args together
# when intentionally upgrading.
ARG TARGETARCH
ARG HERDR_VERSION=0.7.3
ARG HERDR_LINUX_AMD64_SHA256=043ef43ecbabda28465dcff1eec3184518150d567b8b8f20cda9c6c88770641d
ARG HERDR_LINUX_ARM64_SHA256=ea490094f2c7c39099870857d00c64c628ef7b5eba1967df4258033455ee2cb1
RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
        amd64) asset="herdr-linux-x86_64"; sha="${HERDR_LINUX_AMD64_SHA256}" ;; \
        arm64) asset="herdr-linux-aarch64"; sha="${HERDR_LINUX_ARM64_SHA256}" ;; \
        *) echo "unsupported Herdr TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    url="https://github.com/ogulcancelik/herdr/releases/download/v${HERDR_VERSION}/${asset}"; \
    python -c 'import hashlib, sys, urllib.request; url, expected, target = sys.argv[1:4]; data = urllib.request.urlopen(url, timeout=120).read(); actual = hashlib.sha256(data).hexdigest(); sys.exit(f"sha256 mismatch for {url}: {actual} != {expected}") if actual != expected else open(target, "wb").write(data)' "$url" "$sha" /usr/local/bin/herdr; \
    chmod 0755 /usr/local/bin/herdr; \
    herdr --version

# Run as an unprivileged user (INF-01 defence in depth). The app reads /app + the
# read-only mounts and writes nothing to disk (logs go to stdout); the compose
# runs the container read-only with a tmpfs for /tmp.
RUN useradd --create-home --uid 10001 boltrig && \
    install -d -o boltrig -g boltrig \
        /var/lib/boltrig/herdr \
        /var/lib/boltrig/herdr/home \
        /var/lib/boltrig/herdr/config \
        /var/lib/boltrig/herdr/data \
        /var/lib/boltrig/herdr/state
USER boltrig

EXPOSE 8000

# Compose overrides this; it is the sensible default for `docker run`.
CMD ["uvicorn", "boltrig.api.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
