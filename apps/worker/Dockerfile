# Candidate two-surface payload: Worker at /, maintained Operator at /operator/.
# This image is profile-gated in Compose until decision 0021's cutover gates pass.

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
RUN cd apps/worker && pnpm run build

FROM node:22.23.1-alpine3.24@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS operator-build
WORKDIR /app
RUN corepack enable
COPY ui/package.json ui/pnpm-lock.yaml ui/pnpm-workspace.yaml ui/.npmrc ./
RUN --mount=type=secret,id=gh_npmrc,target=/root/.npmrc \
    pnpm install --frozen-lockfile --ignore-scripts \
    && pnpm rebuild esbuild
COPY ui .
ENV BOLTRIG_UI_BASE=/operator/
# PIN THE API PREFIX TO THE ROOT, and it must stay pinned.
#
# ui/src/api/transport.ts derives its API prefix from window.location.pathname
# when VITE_API_BASE is unset. That is correct for a tenant mount, where the edge
# STRIPS the prefix (<host>/boltrig -> the container sees / and /v1). It is wrong
# here: nginx.conf serves this operator build at a real /operator/ path while
# proxying /v1/ at the ROOT, so a derived prefix sends every kernel call to
# /operator/v1/..., which `location /operator/`'s try_files answers with the
# operator's own index.html at HTTP 200. Not a 404 - a 200 full of HTML. Every
# request "succeeds" and returns the wrong thing.
#
# An empty VITE_API_BASE overrides the derivation because `?? ` only falls through
# on null/undefined. Verified at the artefact, not argued: built with this line,
# `location.pathname` appears 0 times in dist/assets/index-*.js; built without it,
# once.
ENV VITE_API_BASE=
RUN pnpm run build

FROM nginx:1.30.4-alpine@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46 AS runtime
RUN apk add --no-cache c-ares=1.34.8-r0 expat=2.8.2-r0 libexpat=2.8.2-r0
COPY apps/worker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=worker-build /workspace/apps/worker/dist /usr/share/nginx/html
COPY --from=operator-build /app/dist /usr/share/nginx/html/operator
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -q --spider http://127.0.0.1/index.html \
   && wget -q --spider http://127.0.0.1/operator/index.html || exit 1
CMD ["nginx", "-g", "daemon off;"]
