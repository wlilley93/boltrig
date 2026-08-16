# Boltrig fleet image (the fleet runtime + durable workers, Epics F/G).
#
# Same shape as deploy/kernel.Dockerfile; the worker talks to Hatchet and the
# pinned Codex runtime without installing provider-native model SDKs. Honours
# the same optional corporate proxy + CA bundle (US-DEP-04).

# IAC-002: pinned to a stable tag + digest.
FROM python:3.14.7-slim-bookworm@sha256:23c59390fc717bf09f9336908199a0ae75d9c4264bf296123f94ad772fea3b52 AS base

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
# --retries/--timeout help a link that DROPS or stalls. They do NOT help the
# failure that prompted them, and the first version of this comment claimed they
# did: when a large wheel is TRUNCATED - the server closes early and pip considers
# the download complete - the hash check fails immediately and pip does not retry,
# because from its point of view nothing went wrong with the transfer. Three
# builds died that way on a lossy 300kB/s link, each reporting "THESE PACKAGES DO
# NOT MATCH THE HASHES ... someone may have tampered with them", which sends the
# reader hunting for an attack. Measured: the same wheels download intact outside
# Docker on the same box, twice, matching the pin.
#
# So these flags stay because they are correct for connection errors, and the real
# answer to truncation is to build somewhere the link holds. The hash contract is
# unchanged either way; only the patience is.
# Same optional wheelhouse as deploy/kernel.Dockerfile - see the note there. Absent directory =>
# no-op COPY => unchanged behaviour. --require-hashes verifies every wheel in either branch.
COPY deploy/wheelhous[e] /wheelhouse/
RUN if [ -n "$(ls -A /wheelhouse 2>/dev/null)" ]; then \
      echo "using pre-fetched wheelhouse ($(ls /wheelhouse | wc -l) wheels)"; \
      pip install --require-hashes --no-index --find-links=/wheelhouse -r /app/requirements-lock.txt; \
    else \
      pip install --require-hashes --retries 10 --timeout 60 -r /app/requirements-lock.txt; \
    fi

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
# Since 2026-07-31 the entrypoint starts Chromium only where a manifest declares
# browser automation, so this smoke has to declare it - in exactly the language a
# tenant uses, rather than through an override that would double as a bypass. The
# build IS the test for that wiring: without the manifest below the smoke reports
# "Chromium not started" and the layer fails, which is how the gate found this
# consumer in the first place.
RUN printf '%s\n' \
      'organisation: boltrig-build-smoke' \
      'tenant_id: build-smoke' \
      'browser_cli:' \
      '  enabled: true' \
      > /tmp/browser-smoke-manifest.yaml && \
    BOLTRIG_BROWSER_CLI_HOME=/tmp/browser-cli-smoke \
    BOLTRIG_MANIFEST=/tmp/browser-smoke-manifest.yaml \
    fleet-entrypoint sh -c \
    'printf "%s\n" "new_tab(\"data:text/html,<title>boltrig-browser-smoke</title>\")" "print(page_info())" | browser-use | grep -F boltrig-browser-smoke' && \
    rm -f /tmp/browser-smoke-manifest.yaml

ARG TARGETARCH
# Boltrig v2 Codex App Server runtime: ship the pinned Codex CLI with the stack
# (the reasoning/subagent runtime that supersedes Pi under decision 0012). Pinned
# by reviewed version + the sha256 of the executable; the fleet supervisor
# RE-VERIFIES this exact digest at spawn (codex_cell_policy.verify_pinned_binary,
# CODEX_CLI_SHA256), so this is defence in depth, not the only check. The binary
# is large (~200MB), so it is streamed to disk (tar/sha256sum/install), never held
# in memory.
#
# 2026-08-05: was amd64-only with a silent skip on other arches, described as not
# failing the image. It did fail it, just later and less legibly - the worker
# resolves the pinned binary at startup and crash-loops when it is absent, so an
# arm64 build produced an image that could not run. The aarch64-unknown-linux-musl
# build IS published for this same pin, so both arches are fetched now. Each is
# pinned to the sha256 of its OWN extracted binary (the checksum is verified
# against the binary, not the tarball). Kept in step with deploy/kernel.Dockerfile.
ARG CODEX_VERSION=0.144.3
ARG CODEX_SHA256=37e6f5953f191b04f7b62cb07dae90f51d0947ad89f0355665b421fbde28700b
ARG CODEX_SHA256_ARM64=afb0d0379242b598de8a2d44174e0c7ccdf1512b7b41a32adf2c6c9a6f5b6f15
RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
        amd64) triple="x86_64-unknown-linux-musl"; want="$CODEX_SHA256" ;; \
        arm64) triple="aarch64-unknown-linux-musl"; want="$CODEX_SHA256_ARM64" ;; \
        *) echo "codex ${CODEX_VERSION}: no pinned build for ${TARGETARCH:-unknown}" >&2; exit 1 ;; \
    esac; \
    url="https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-${triple}.tar.gz"; \
    python -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], "/tmp/codex.tgz")' "$url"; \
    tar -xzf /tmp/codex.tgz -C /tmp "codex-${triple}"; \
    printf '%s  %s\n' "$want" "/tmp/codex-${triple}" | sha256sum -c -; \
    install -D -m 0755 "/tmp/codex-${triple}" /opt/boltrig/codex/codex; \
    rm -f /tmp/codex.tgz "/tmp/codex-${triple}"; \
    /opt/boltrig/codex/codex --version
# Default location the fleet composition root resolves the pinned binary from
# (a normalized absolute path; the supervisor still re-verifies the digest).
ENV BOLTRIG_CODEX_BIN=/opt/boltrig/codex/codex

# [2026] VJS-CC-VJS 5 G2: the per-cell auth helper used to be written into the
# MUTABLE cell root at 0700, which under a single shared cell uid stopped nothing
# between siblings. There is now ONE shared helper, baked here root-owned and
# non-writable on the read-only rootfs, extending the exact rule the pinned codex
# binary above already relies on. No new container privileges are required.
COPY deploy/codex/model_auth_helper /opt/boltrig/codex/model_auth_helper
RUN chown 0:0 /opt/boltrig/codex/model_auth_helper && \
    chmod 0555 /opt/boltrig/codex/model_auth_helper
ENV BOLTRIG_CODEX_AUTH_HELPER=/opt/boltrig/codex/model_auth_helper

# [2026] VJS-CC-VJS 6 H5: the cell-INVARIANT security-critical config, installed
# root-owned on the read-only image mount. Verified on the pinned binary that a
# leaf set here BEATS the same leaf in a hostile $CODEX_HOME/config.toml, which a
# sibling cell can rewrite. It does NOT stop a key being ADDED (tables merge), so
# it hardens, it does not discharge G3.
COPY deploy/codex/managed_config.toml /etc/codex/managed_config.toml
RUN chown 0:0 /etc/codex/managed_config.toml && \
    chmod 0444 /etc/codex/managed_config.toml

# [2026] VJS-CC-VJS 7 J4: strip every setuid/setgid bit in the image.
#
# The court corrected a claim I made about why a dropped cell cannot regain
# privilege. An empty permitted set does NOT make the capability bounding set
# inert: the bounding set is the ceiling on what an execve of a file bearing file
# capabilities may place in the permitted set. What makes it inert is
# no_new_privileges, and ONLY that. Since the bounding set cannot be cleared
# without CAP_SETPCAP (refused), the property rested on a single control while
# this image shipped eleven setuid-root binaries (su, mount, passwd and friends)
# on a rootfs that is not nosuid. Stripping them gives the property a second,
# independent leg. It is free, so there was never a reason not to.
RUN find / -xdev -perm /6000 -type f -exec chmod a-s {} + 2>/dev/null; \
    test -z "$(find / -xdev -perm /6000 -type f 2>/dev/null)"

# Run as an unprivileged user (INF-01). Writes nothing to disk; compose runs it
# read-only with a tmpfs for /tmp.
RUN useradd --create-home --uid 10001 boltrig && \
    install -d -o boltrig -g boltrig \
        /var/lib/boltrig/browser-cli \
        /var/lib/boltrig/browser-cli/home \
        /var/lib/boltrig/browser-cli/config \
        /var/lib/boltrig/browser-cli/data \
        /var/lib/boltrig/browser-cli/state \
        /var/lib/boltrig/browser-cli/cache \
        /run/boltrig-browser
USER boltrig

# Compose overrides this; it is the sensible default for `docker run`.
ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/fleet-entrypoint"]
CMD ["python", "-m", "boltrig.api.worker"]
