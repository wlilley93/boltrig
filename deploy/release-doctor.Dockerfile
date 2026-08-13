# Production doctor execution context assembled only from admitted release images.
#
# The fleet image owns OpenCode and Browser Use CLI. The kernel image owns Herdr.
# A host-side doctor cannot truthfully verify either image: it would inspect the
# operator workstation's PATH instead. Release admission therefore builds this
# ephemeral, unpushed context from the two exact digest references *after* their
# signatures, SBOMs, and provenance have verified. It adds only the kernel-owned
# Herdr executable to the fleet image; no deployment-tree bytes enter the image.

ARG BOLTRIG_KERNEL_IMAGE=scratch
ARG BOLTRIG_FLEET_IMAGE=scratch

FROM ${BOLTRIG_KERNEL_IMAGE} AS kernel_release
FROM ${BOLTRIG_FLEET_IMAGE} AS release_doctor

USER root
COPY --from=kernel_release /usr/local/bin/herdr /usr/local/bin/herdr
USER boltrig

ENTRYPOINT ["/usr/local/bin/python3"]
