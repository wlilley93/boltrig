# Boltrig fleet image (the fleet runtime + durable workers, Epics F/G).
#
# Same shape as deploy/kernel.Dockerfile but installs the [durable,inference]
# extras so the worker can talk to Hatchet (durable execution) and to inference
# back ends. Honours the same optional corporate proxy + CA bundle (US-DEP-04).

# IAC-002: pinned to a stable tag + digest.
FROM python:3.12.13-slim-bookworm@sha256:8a7e7cc04fd3e2bd787f7f24e22d5d119aa590d429b50c95dfe12b3abe52f48b AS base

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

# DEP-001: install from a frozen, hash-verified lockfile instead of mutable
# ranges. The lockfile is generated from pyproject.toml with `uv pip compile`.
COPY pyproject.toml requirements-lock.txt /app/
RUN pip install --require-hashes -r /app/requirements-lock.txt

# Run directly from the copied, read-only source tree. Installing the project
# itself would invoke PEP 517 build isolation and download an unlocked hatchling
# toolchain; /app is the workdir and therefore already on Python's import path.
COPY boltrig/ /app/boltrig/

# Boltrig v2 browser automation runtime: ship Browser Use CLI as an isolated
# tool venv. Its dependency closure is hash-locked separately so it cannot
# upgrade/downgrade the Boltrig app environment.
#
# chromium/tini install UNPINNED from the Debian bookworm repo. Exact apt version
# pins rot: Debian keeps only the newest security build in the pool, so a pinned
# patch (e.g. chromium=150.0.7871.114-1~deb12u1) stops resolving on the next
# security bump and breaks every rebuild (apt exit 100). Taking the current repo
# version keeps the image buildable and on the latest security patch. Exact
# chromium reproducibility, if ever required, belongs behind a snapshot.debian.org
# pinned repo, not a live-repo version pin.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        chromium \
        tini \
        bubblewrap && \
    rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/boltrig/browser-cli && \
    /opt/boltrig/browser-cli/bin/pip install \
        --no-deps \
        --require-hashes \
        -r /app/deploy/browser-cli-requirements.txt && \
    ln -sf /opt/boltrig/browser-cli/bin/browser-use /usr/local/bin/browser-use && \
    browser-use --version && \
    chromium --version

# Start the stack-owned headless Chromium before the worker. The entrypoint also
# primes Browser Harness' local CDP daemon, so browser.health is truthful from
# the first probe and no runtime downloader (uvx/playwright) can be reached.
COPY --chmod=0755 scripts/fleet-entrypoint.sh /usr/local/bin/fleet-entrypoint
RUN BOLTRIG_BROWSER_CLI_HOME=/tmp/browser-cli-smoke \
    fleet-entrypoint sh -c \
    'printf "%s\n" "new_tab(\"data:text/html,<title>boltrig-browser-smoke</title>\")" "print(page_info())" | browser-use | grep -F boltrig-browser-smoke'

# Boltrig v2 coding-agent runtime: ship OpenCode with the stack, not from a
# developer workstation. Use the native npm binary tarball directly rather than
# running npm install scripts in the image.
ARG TARGETARCH
ARG OPENCODE_VERSION=1.17.16
ARG OPENCODE_LINUX_AMD64_SHA256=fee3fea8d03d5bbe70bc9f1258d097ad07090415df029296765c61bb9fb677a4
ARG OPENCODE_LINUX_ARM64_SHA256=2f659f652fae638c49b9e9400f143693af91274c4f1353ce35c9291d27a15f81
RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
        amd64) package="opencode-linux-x64-baseline"; sha="${OPENCODE_LINUX_AMD64_SHA256}" ;; \
        arm64) package="opencode-linux-arm64"; sha="${OPENCODE_LINUX_ARM64_SHA256}" ;; \
        *) echo "unsupported OpenCode TARGETARCH=${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    url="https://registry.npmjs.org/${package}/-/${package}-${OPENCODE_VERSION}.tgz"; \
    python -c 'import hashlib, io, os, stat, sys, tarfile, urllib.request; url, expected, target = sys.argv[1:4]; data = urllib.request.urlopen(url, timeout=120).read(); actual = hashlib.sha256(data).hexdigest(); sys.exit(f"sha256 mismatch for {url}: {actual} != {expected}") if actual != expected else None; tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz"); member = tar.getmember("package/bin/opencode"); source = tar.extractfile(member); os.makedirs(os.path.dirname(target), exist_ok=True); open(target, "wb").write(source.read()); os.chmod(target, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)' "$url" "$sha" /usr/local/bin/opencode; \
    opencode --version

# Boltrig v2 Codex App Server runtime: ship the pinned Codex CLI with the stack
# (the reasoning/subagent runtime that supersedes Pi under decision 0012). Pinned
# by reviewed version + the sha256 of the executable; the fleet supervisor
# RE-VERIFIES this exact digest at spawn (codex_cell_policy.verify_pinned_binary,
# CODEX_CLI_SHA256), so this is defence in depth, not the only check. amd64-only:
# the pin is the x86_64-unknown-linux-musl build (CODEX_CLI_TARGET); other arches
# skip rather than fail the image. The binary is large (~200MB), so it is streamed
# to disk (tar/sha256sum/install), never held in memory.
ARG CODEX_VERSION=0.144.3
ARG CODEX_SHA256=37e6f5953f191b04f7b62cb07dae90f51d0947ad89f0355665b421fbde28700b
RUN set -eux; \
    if [ "${TARGETARCH:-amd64}" != "amd64" ]; then \
        echo "codex ${CODEX_VERSION} is amd64-only; skipping on ${TARGETARCH:-unknown}"; \
    else \
        url="https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-x86_64-unknown-linux-musl.tar.gz"; \
        python -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], "/tmp/codex.tgz")' "$url"; \
        tar -xzf /tmp/codex.tgz -C /tmp codex-x86_64-unknown-linux-musl; \
        printf '%s  %s\n' "$CODEX_SHA256" /tmp/codex-x86_64-unknown-linux-musl | sha256sum -c -; \
        install -D -m 0755 /tmp/codex-x86_64-unknown-linux-musl /opt/boltrig/codex/codex; \
        rm -f /tmp/codex.tgz /tmp/codex-x86_64-unknown-linux-musl; \
        /opt/boltrig/codex/codex --version; \
    fi
# Default location the fleet composition root resolves the pinned binary from
# (a normalized absolute path; the supervisor still re-verifies the digest).
ENV BOLTRIG_CODEX_BIN=/opt/boltrig/codex/codex

# Run as an unprivileged user (INF-01). Writes nothing to disk; compose runs it
# read-only with a tmpfs for /tmp.
RUN useradd --create-home --uid 10001 boltrig && \
    install -d -o boltrig -g boltrig \
        /var/lib/boltrig/opencode \
        /var/lib/boltrig/opencode/home \
        /var/lib/boltrig/opencode/config \
        /var/lib/boltrig/opencode/config/opencode \
        /var/lib/boltrig/opencode/data \
        /var/lib/boltrig/opencode/state \
        /var/lib/boltrig/browser-cli \
        /var/lib/boltrig/browser-cli/home \
        /var/lib/boltrig/browser-cli/config \
        /var/lib/boltrig/browser-cli/data \
        /var/lib/boltrig/browser-cli/state \
        /var/lib/boltrig/browser-cli/cache
USER boltrig

# Compose overrides this; it is the sensible default for `docker run`.
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/fleet-entrypoint"]
CMD ["python", "-m", "boltrig.api.worker"]
