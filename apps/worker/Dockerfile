# Boltrig Worker web client. This is the only first-party browser surface.

FROM node:22.23.1-alpine3.24@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS worker-build
WORKDIR /workspace
RUN corepack enable

# The hosted, authenticated Worker may expose a reviewed HTTPS distribution
# page for signed desktop packages. Core releases deliberately leave it empty.
ARG VITE_DESKTOP_DOWNLOAD_URL=""
ENV VITE_DESKTOP_DOWNLOAD_URL=${VITE_DESKTOP_DOWNLOAD_URL}

# The Worker resolves the shared SDK from source, so the image never downloads
# a second frontend contract or an OpenWorker service dependency.
COPY sdks/web/package.json sdks/web/tsconfig.json ./sdks/web/
COPY sdks/web/src ./sdks/web/src
COPY apps/worker/package.json apps/worker/pnpm-lock.yaml apps/worker/index.html \
     apps/worker/tsconfig.json apps/worker/vite.config.ts ./apps/worker/
RUN cd apps/worker \
    && pnpm install --frozen-lockfile --ignore-scripts \
    && pnpm rebuild esbuild
COPY apps/worker/src ./apps/worker/src
# The Worker imports the shared VDS token source during the frontend build.
# Keep the image context narrow by packaging only the token files it consumes;
# the design reference and other documentation are not runtime dependencies.
COPY docs/design/imported/tokens/colors.css docs/design/imported/tokens/spacing.css docs/design/imported/tokens/typography.css ./docs/design/imported/tokens/
# Published Worker images always ship the stock companion set (Familiar +
# Jarvis). The stock dependency graph and characterPlugins.ts contain no
# operator-owned companion package, so an environment variable cannot widen the
# release after review.
RUN cd apps/worker && pnpm run build

FROM nginx:1.30.4-alpine@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46 AS runtime
RUN apk add --no-cache c-ares=1.34.8-r0 expat=2.8.2-r0 libexpat=2.8.2-r0
COPY apps/worker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=worker-build /workspace/apps/worker/dist /usr/share/nginx/html

# Run as the unprivileged `nginx` user (DS-0002). A container running as root is
# one escape away from root on the host, and this one serves the only
# first-party browser surface.
#
# THE PORT MOVED WITH THE USER, and had to. Binding below 1024 needs
# CAP_NET_BIND_SERVICE, so a non-root nginx cannot listen on 80 -- adding USER
# without moving the port yields an image that builds, scans clean, and refuses
# to start. The published HOST port is untouched; only the container side is
# 8080 now.
#
# nginx writes three things as itself: the cache, the pid file and the logs. The
# official image leaves all three root-owned, so they are handed over
# explicitly rather than discovered at first boot.
RUN chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx \
    && touch /var/run/nginx.pid \
    && chown nginx:nginx /var/run/nginx.pid
USER nginx

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -q --spider http://127.0.0.1:8080/index.html || exit 1
CMD ["nginx", "-g", "daemon off;"]
