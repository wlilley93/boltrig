# Boltrig channel gateway image (decision 0003, Phase 2).
#
# A STANDALONE daemon terminating the socket (persistent-connection) channel
# class. It is not the boltrig package and ships its own pinned deps (condition
# 9: no messaging SDKs in the kernel image - they live HERE, per platform port).
#
# SECURITY (decision 0003, conditions 2 + 7): this container must have its
# egress RESTRICTED at the network layer to exactly two destination classes:
#   1) the kernel intake (BOLTRIG_KERNEL_URL), and
#   2) the platform endpoints of the channels it serves.
# It holds no persistent credential and no policy: the run-scoped kernel token
# and the per-channel connect-time secrets arrive as ENV AT SPAWN only and are
# never logged. Enforce the restriction with a Docker network policy / egress
# firewall (an internal compose network plus an allow-list proxy); the image
# itself holds no secrets and opens no inbound ports beyond 8091 (health).

# IAC-002: pinned to a stable tag + digest (same base as the pi_sidecar image).
FROM python:3.14.6-slim-bookworm@sha256:86f975aca15cf04a40b399eebede9aea7c82eae084d1f1a0a6ef6bcaae871a30 AS base

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
COPY adapters.py /app/adapters.py
COPY egress.py /app/egress.py
COPY kernel_client.py /app/kernel_client.py
# The platform ports (imported by app.py at boot so they self-register).
COPY slack_adapter.py /app/slack_adapter.py
COPY telegram_adapter.py /app/telegram_adapter.py
COPY discord_adapter.py /app/discord_adapter.py
COPY signal_adapter.py /app/signal_adapter.py
COPY whatsapp_adapter.py /app/whatsapp_adapter.py
# The custom-surface client kit (embedded by/mimicked in off-box surfaces).
COPY clients /app/clients

# Run as an unprivileged user (defence in depth; condition 2).
RUN useradd --create-home --uid 10002 gateway
USER gateway

EXPOSE 8091

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8091"]
