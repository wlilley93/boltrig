# The WhatsApp bridge image (decision 0003, condition 9): the Baileys SDK is a
# Node library and lives in THIS image only - it never enters the kernel or the
# Python gateway image. Derived from the MIT-licensed Hermes bridge (Copyright
# (c) 2025 Nous Research) - see LICENSE.md.
#
# The bridge terminates WhatsApp's E2EE and holds the session credentials on
# disk: mount an operator-owned volume at /data and keep it off the host's
# casual path. It binds loopback-only by default; in compose it must listen on
# the container interface (the gateway adapter reaches it over the sandbox
# network), so the compose service passes --host via env (see docker-compose
# snippet in the port report / README operator section).
#
# Tag+digest pinned (re-pin on upgrade: tags are mutable):
#   node:22-alpine, multi-arch digest as of 2026-07-22.
FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32

WORKDIR /app

# Reproducible install from the vendored lockfile; production deps only.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY bridge.js LICENSE.md ./

# Drop root: the bridge needs only /app (read) and /data (read/write).
RUN mkdir -p /data && chown -R node:node /data /app
USER node

EXPOSE 3000

# Pairing: docker run --rm -it -v whatsapp-session:/data <image> \
#   node bridge.js --pair-only --session /data
CMD ["node", "bridge.js", "--port", "3000", "--session", "/data"]
