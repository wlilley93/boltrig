# Production-doctor execution context assembled from the admitted fleet image.
# The only separately probed stack tool is the image-owned Browser Use CLI;
# Codex has its own admission path and no host installation is consulted.

ARG BOLTRIG_FLEET_IMAGE=scratch
FROM ${BOLTRIG_FLEET_IMAGE} AS release_doctor

ENTRYPOINT ["/usr/local/bin/python3"]
