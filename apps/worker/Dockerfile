# Boltrig Worker web client. This is the only first-party browser surface.

FROM node:22.23.1-alpine3.24@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS worker-build
WORKDIR /workspace
RUN corepack enable

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
RUN cd apps/worker && pnpm run build

FROM nginx:1.30.4-alpine@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46 AS runtime
RUN apk add --no-cache c-ares=1.34.8-r0 expat=2.8.2-r0 libexpat=2.8.2-r0
COPY apps/worker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=worker-build /workspace/apps/worker/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -q --spider http://127.0.0.1/index.html || exit 1
CMD ["nginx", "-g", "daemon off;"]
