# Development-only dependency overlay for bind-mounted Jellytot source.
#
# A source bind mount can update /app/boltrig without updating the Python
# environment beneath it.  Build this overlay from the exact currently deployed
# image digest whenever the development source starts importing a newly locked
# dependency.  Production releases must continue to use kernel.Dockerfile and
# fleet.Dockerfile through the signed release workflow.

ARG BASE_IMAGE=scratch
FROM ${BASE_IMAGE}

USER root
COPY requirements-lock.txt /tmp/boltrig-requirements-lock.txt
RUN pip install \
      --require-hashes \
      --retries 10 \
      --timeout 60 \
      -r /tmp/boltrig-requirements-lock.txt \
    && rm -f /tmp/boltrig-requirements-lock.txt

USER boltrig
