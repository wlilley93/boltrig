# Boltrig scheduled backup sidecar image (M10, SEC-70).
#
# This image bakes in the exact tools the backup script needs (pg_dump, tar,
# rclone, openssl) so the sidecar does not install at runtime (IAC-003). It is used
# by the profile-gated `backup` service in docker-compose.yml.
#
# Pin the base image to a specific PostgreSQL minor + digest. For digest pinning,
# replace the tag with a sha256 reference after pulling the desired image.

# IAC-002: pinned to a stable tag + digest.
FROM postgres:16.14-bookworm@sha256:64154d0babcb1741988719e703419af0382b19953706149f9872fbd0f438efa8 AS base

# IAC-002: rclone copied from an official, pinned image instead of installing
# from the network at build time (which would also be acceptable, but the upstream
# apt key URL has been unstable, so the copy path is more reliable).
FROM rclone/rclone:1.75.0@sha256:b06aed988cf5967de7c25be5925240983981c757f4ed1ac9d2fa659d51d60548 AS rclone-src

FROM base
ENV DEBIAN_FRONTEND=noninteractive \
    PGUSER=boltrig \
    PGDATABASE=boltrig

USER root

# The upstream Postgres entrypoint uses gosu, but this image replaces that
# entrypoint with the backup loop. Remove the otherwise-unused static helper so
# its embedded Go toolchain is not part of the production attack surface.
RUN rm -f /usr/local/bin/gosu

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
COPY scripts/backup-loop.sh /usr/local/bin/backup-loop.sh
COPY scripts/backup-healthcheck.sh /usr/local/bin/backup-healthcheck
RUN chmod +x \
        /usr/local/bin/backup.sh \
        /usr/local/bin/backup-loop.sh \
        /usr/local/bin/backup-healthcheck

# The sidecar loops the backup script at BACKUP_INTERVAL seconds. The caller
# mounts the backups directory and the rclone config directory as volumes. A
# failed run exits PID 1; Docker's restart policy retries it instead of masking a
# permanently broken backup process. The healthcheck also detects stale success.
HEALTHCHECK --interval=60s --timeout=5s --start-period=5m --retries=3 \
    CMD ["/usr/local/bin/backup-healthcheck"]
CMD ["/usr/local/bin/backup-loop.sh"]
