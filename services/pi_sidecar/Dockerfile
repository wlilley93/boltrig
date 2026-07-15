# Boltrig Pi sidecar image (Round Two, Epic RUN; SRS S5.3).
#
# A STANDALONE reasoning-loop service reached over HTTP by Boltrig's PiRuntime.
# It is not the boltrig package and ships its own pinned deps.
#
# SECURITY (SEC-24, SEC-27): this container must have its egress RESTRICTED at
# the network layer to exactly two destinations:
#   1) the kernel MCP endpoint (mcp.url in the /run body), and
#   2) the model endpoint (model.endpoint in the /run body).
# It must NOT be granted any other outbound network access, and it is given no
# tool credentials of its own - only a model key and a run-scoped MCP token,
# both per request. Enforce this with a Docker network policy / egress firewall
# (for example an internal compose network plus an allow-list proxy); the image
# itself holds no secrets and opens no inbound ports beyond 8090.

# IAC-002: pinned to a stable tag + digest.
FROM python:3.12.13-slim-bookworm@sha256:8a7e7cc04fd3e2bd787f7f24e22d5d119aa590d429b50c95dfe12b3abe52f48b AS base

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install the complete CPython 3.12 graph from its hash-locked generated file so
# a compromised package index cannot substitute an unreviewed distribution.
COPY requirements.txt /app/requirements.txt
RUN pip install --require-hashes -r /app/requirements.txt

COPY app.py /app/app.py

# Run as an unprivileged user (defence in depth; SEC-24).
RUN useradd --create-home --uid 10001 sidecar
USER sidecar

EXPOSE 8090

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
