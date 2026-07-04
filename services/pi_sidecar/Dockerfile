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
FROM python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7 AS base

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install deps first so the layer caches across app-only edits.
COPY requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt

COPY app.py /app/app.py

# Run as an unprivileged user (defence in depth; SEC-24).
RUN useradd --create-home --uid 10001 sidecar
USER sidecar

EXPOSE 8090

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
