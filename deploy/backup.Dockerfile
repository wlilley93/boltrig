# Boltrig scheduled backup sidecar image (M10, SEC-70).
#
# This image bakes in the exact tools the backup script needs (pg_dump, rclone,
# openssl) so the sidecar does not run apt-get at runtime (IAC-003). It is used
# by the profile-gated `backup` service in docker-compose.yml.
#
# Pin the base image to a specific PostgreSQL minor. For digest pinning, replace
# the tag with a sha256 reference after pulling the desired image.

FROM postgres:16.4-bookworm AS base

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DEBIAN_FRONTEND=noninteractive \
    PGUSER=boltrig \
    PGDATABASE=boltrig

# Install rclone from the official upstream repo with a pinned version. The
# apt-transport-https package is required for HTTPS apt sources; curl is used to
# fetch the upstream signing key and repository list. These are build-only and do
# not affect the runtime surface.
ARG RCLONE_VERSION=1.68.2
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        openssl \
    && curl -fsSL https://downloads.rclone.org/keys/rclone_signing_key.asc | \
       gpg --dearmor -o /usr/share/keyrings/rclone-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/rclone-archive-keyring.gpg] \
        https://downloads.rclone.org/apt/ bookworm main" \
        > /etc/apt/sources.list.d/rclone.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends rclone=${RCLONE_VERSION}* \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/*

# pg_dump is already present in the postgres image; openssl was installed above.
RUN command -v pg_dump && command -v rclone && command -v openssl

WORKDIR /app
COPY scripts/backup.sh /usr/local/bin/backup.sh
RUN chmod +x /usr/local/bin/backup.sh

# The sidecar loops the backup script at BACKUP_INTERVAL seconds. The caller
# mounts the backups directory and the rclone config directory as volumes.
ENTRYPOINT ["/bin/bash", "-c"]
CMD ["while true; do /usr/local/bin/backup.sh || echo 'backup: run failed (retrying next interval)' >&2; sleep \"${BACKUP_INTERVAL:-86400}\"; done"]
