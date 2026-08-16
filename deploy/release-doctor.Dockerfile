# Production-doctor execution context assembled from the admitted fleet image.
# The only separately probed stack tool is the image-owned Browser Use CLI;
# Codex has its own admission path and no host installation is consulted.

ARG BOLTRIG_FLEET_IMAGE=scratch
FROM ${BOLTRIG_FLEET_IMAGE} AS release_doctor

# Restating what the fleet image already sets (deploy/fleet.Dockerfile: uid 10001
# boltrig). Behaviourally a no-op -- the base already leaves this user selected --
# but the FROM here is an ARG, so a scanner cannot follow it and reads this stage
# as running unconfigured, i.e. root (DS-0002). Stating it makes the inherited
# fact checkable rather than assumed, and pins it: if the base ever stopped
# dropping privileges, this line would keep the doctor unprivileged instead of
# silently following it back to root.
USER boltrig

ENTRYPOINT ["/usr/local/bin/python3"]
