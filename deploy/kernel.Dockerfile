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
FROM python:3.14.7-slim-bookworm@sha256:23c59390fc717bf09f9336908199a0ae75d9c4264bf296123f94ad772fea3b52 AS base

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
# An OPTIONAL pre-fetched wheelhouse. The bracket glob makes this COPY a no-op when the directory
# is absent, so a checkout without one builds exactly as before. Populate it with
# scripts/build-wheelhouse.sh, which fetches ONE REQUIREMENT AT A TIME - the point being that
# `pip download --require-hashes` stages every wheel in a temp dir and only copies on total success,
# so a single truncated wheel discards the whole download and the next attempt starts from nothing.
# Six builds died that way. Per-requirement, a truncation costs one wheel.
#
# THE HASH CONTRACT IS UNCHANGED IN BOTH BRANCHES: --require-hashes verifies every wheel against
# requirements-lock.txt either way. Only the source of the bytes moves.
COPY deploy/wheelhous[e] /wheelhouse/
RUN if [ -n "$(ls -A /wheelhouse 2>/dev/null)" ]; then \
      echo "using pre-fetched wheelhouse ($(ls /wheelhouse | wc -l) wheels)"; \
      pip install --require-hashes --no-index --find-links=/wheelhouse -r /app/requirements-lock.txt; \
    else \
      pip install --require-hashes --retries 10 --timeout 60 -r /app/requirements-lock.txt; \
    fi

ARG TARGETARCH
# Boltrig v2 Codex App Server runtime: ship the pinned Codex CLI in the kernel image
# too, since a console chat turn resolves + spawns the Codex runtime IN the kernel
# process (not only the fleet-worker). Same pin + digest as deploy/fleet.Dockerfile;
# the supervisor re-verifies the exact sha256 at spawn (codex_cell_policy.
# verify_pinned_binary), so this is defence in depth. Inert unless
# BOLTRIG_CODEX_TRUSTED is set - the runtime is dev-gated and refuses under any
# production signal.
#
# 2026-08-05: this block used to skip on non-amd64, on the stated ground that
# codex was "amd64-only". That was NOT true for this pin - the release publishes
# codex-aarch64-unknown-linux-musl for rust-v0.144.3 as well - and the skip was
# not harmless: the kernel's own gate (_prove_the_host_can_enforce_the_cell_wall)
# REFUSES to boot when the binary is absent, so an arm64 host got a container
# that could never start rather than one running without codex. Both arches are
# now fetched and each is pinned to the sha256 of its OWN extracted binary,
# because the checksum is verified against the binary, not the tarball.
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

# bubblewrap is Codex's documented sandbox prerequisite. Without it on PATH the
# App Server emits a configWarning at startup and falls back to a bundled copy;
# that warning is an invalidation-class notification the read-only preflight
# rejects. Installing it removes the warning at the source and gives real cell
# sandboxing. (See https://developers.openai.com/codex/concepts/sandboxing.)
RUN apt-get update && apt-get install -y --no-install-recommends bubblewrap && \
    rm -rf /var/lib/apt/lists/*

# Run directly from the copied, read-only source tree. Installing the project
# itself would invoke PEP 517 build isolation and download an unlocked hatchling
# toolchain; /app is the workdir and therefore already on Python's import path.
# Copied LATE, after the expensive pinned Codex fetch so that an
# ordinary source change re-uses those cached layers instead of re-downloading
# ~300MB every time.
COPY boltrig/ /app/boltrig/

# The `boltrig` console script this project DECLARES in pyproject [project.scripts].
# It was declared and never installed: dependencies come from requirements-lock.txt under
# --require-hashes and the package itself is copied in rather than pip-installed, so no
# entry point was ever generated. `docker exec <kernel> boltrig initiate` therefore failed
# with "executable file not found in $PATH" on every shipped tag including the one
# production runs, which meant genesis-boltrig.sh could not seat a founding owner or mint
# an admin PAT - i.e. NO TENANT COULD BE FOUNDED. Found by running provisioning for real
# on 2026-07-26 (opbox-prod/docs/H1-REHEARSAL-2026-07-26.md).
#
# Written explicitly rather than by `pip install .`, which would put the package outside
# the hash-pinned install and weaken the --require-hashes contract for one console script.
# `sys.path.insert` is load-bearing, not defensive. For a SCRIPT, Python puts the
# script's own directory on sys.path - /usr/local/bin - never the working
# directory, so the first cut imported nothing and the build died on its own smoke
# test with ModuleNotFoundError: No module named 'boltrig'. The package lives at
# /app/boltrig (COPY above), and WORKDIR being /app does not help a script.
RUN printf '%s\n' \
      '#!/usr/local/bin/python3' \
      'import sys' \
      'sys.path.insert(0, "/app")' \
      'from boltrig.api.cli import main' \
      'sys.exit(main())' \
      > /usr/local/bin/boltrig \
 && chmod 0755 /usr/local/bin/boltrig \
 && /usr/local/bin/boltrig --help >/dev/null

# Boltrig v2 Codex App Server runtime: the pinned Codex CLI, mirrored from
# deploy/fleet.Dockerfile (decision 0012). The chat spawner runs codex cells
# in THIS container (the compose kernel service already carries the cell
# posture: uid 0 + SETUID/SETGID, the codex-cells tmpfs, the kernel-entrypoint
# spawner). Keep the version/sha in lockstep with the fleet Dockerfile.
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
ENV BOLTRIG_CODEX_BIN=/opt/boltrig/codex/codex

# The per-cell auth helper and the cell-invariant managed config, root-owned on
# the read-only rootfs (mirrors the fleet image).
COPY deploy/codex/model_auth_helper /opt/boltrig/codex/model_auth_helper
RUN chown 0:0 /opt/boltrig/codex/model_auth_helper && \
    chmod 0555 /opt/boltrig/codex/model_auth_helper
ENV BOLTRIG_CODEX_AUTH_HELPER=/opt/boltrig/codex/model_auth_helper
COPY deploy/codex/managed_config.toml /etc/codex/managed_config.toml
RUN chown 0:0 /etc/codex/managed_config.toml && \
    chmod 0444 /etc/codex/managed_config.toml

# Run as an unprivileged user (INF-01 defence in depth). The app reads /app + the
# read-only mounts and writes nothing to disk (logs go to stdout); the compose
# runs the container read-only with a tmpfs for /tmp.
RUN useradd --create-home --uid 10001 boltrig && \
    install -d -o boltrig -g boltrig \
        /var/lib/boltrig/knowledge \
        /var/lib/boltrig/cognee
# [2026] VJS-CC-VJS 7 J3. The entrypoint privilege-separates when, and ONLY when,
# the kernel reports uid 0 with a non-empty permitted set. Everywhere else it
# execs the command it was given and gets out of the way, verified byte-identical
# to running that command directly, so a deployment that has not granted the
# capability gains no new failure mode from this line.
COPY scripts/kernel-entrypoint.py /opt/boltrig/kernel-entrypoint.py
RUN chown 0:0 /opt/boltrig/kernel-entrypoint.py && \
    chmod 0555 /opt/boltrig/kernel-entrypoint.py
ENTRYPOINT ["/usr/local/bin/python3", "/opt/boltrig/kernel-entrypoint.py"]

USER boltrig

EXPOSE 8000

# Compose overrides this; it is the sensible default for `docker run`.
CMD ["uvicorn", "boltrig.api.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
