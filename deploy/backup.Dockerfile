# Boltrig scheduled backup sidecar image (M10, SEC-70).
#
# This image bakes in the exact tools the backup script needs (pg_dump, rclone,
# openssl) so the sidecar does not run apt-get at runtime (IAC-003). It is used
# by the profile-gated `backup` service in docker-compose.yml.
#
# Pin the base image to a specific PostgreSQL minor + digest. For digest pinning,
# replace the tag with a sha256 reference after pulling the desired image.

# IAC-002: pinned to a stable tag + digest.
FROM postgres:16.4-bookworm@sha256:e62fbf9d3e2b49816a32c400ed2dba83e3b361e6833e624024309c35d334b412 AS base

# IAC-002: rclone copied from an official, pinned image instead of installing
# from the network at build time (which would also be acceptable, but the upstream
# apt key URL has been unstable, so the copy path is more reliable).
FROM rclone/rclone:1.74.3@sha256:623378ad0ff3ebd5cebf77720843c0e02edfe46e2d5b5ac6bed54c6371780dfb AS rclone-src

FROM base
ENV DEBIAN_FRONTEND=noninteractive \
    PGUSER=boltrig \
    PGDATABASE=boltrig

USER root

# openssl is needed for optional passphrase encryption. pg_dump is already
# present in the postgres image; rclone is copied from the pinned rclone image.
RUN apt-get update && apt-get install -y --no-install-recommends \
        openssl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/*

COPY --from=rclone-src /usr/local/bin/rclone /usr/local/bin/rclone
RUN rclone version

WORKDIR /app
COPY scripts/backup.sh /usr/local/bin/backup.sh
RUN chmod +x /usr/local/bin/backup.sh

# The sidecar loops the backup script at BACKUP_INTERVAL seconds. The caller
# mounts the backups directory and the rclone config directory as volumes.
ENTRYPOINT ["/bin/bash", "-c"]
CMD ["while true; do /usr/local/bin/backup.sh || echo 'backup: run failed (retrying next interval)' >&2; sleep \"\\${BACKUP_INTERVAL:-86400}\"; done"]
