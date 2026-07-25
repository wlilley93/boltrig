# Multi-stage: build the static SPA with node, then serve it with nginx.
# nginx also reverse-proxies /v1 and /healthz to the kernel service.

FROM node:26.5.0-alpine3.24@sha256:e88a35be04478413b7c71c455cd9865de9b9360e1f43456be5951032d7ac1a66 AS build
WORKDIR /app
RUN corepack enable

# Install with pnpm (the dev package manager) from the frozen lockfile, so the
# image is built from the SAME dependency graph developers run - reproducible.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
# The committed .npmrc points the @wlilley93 scope at GitHub Packages (the shared
# UI-SDK source of truth). GitHub Packages requires auth even to READ a public
# package, so builds mount a token-bearing user .npmrc as a BuildKit secret
# (id=gh_npmrc); pnpm merges it with the project .npmrc. Uses a read:packages
# token - no new credential class. Dev host installs use ~/.npmrc directly.
RUN --mount=type=secret,id=gh_npmrc,target=/root/.npmrc \
    pnpm install --frozen-lockfile --ignore-scripts && pnpm rebuild esbuild

COPY . .
RUN pnpm run build

FROM nginx:1.30.4-alpine@sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46 AS runtime
# Security refreshes released after the immutable nginx image was built.
RUN apk add --no-cache c-ares=1.34.8-r0 expat=2.8.2-r0 libexpat=2.8.2-r0
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
# 127.0.0.1 (not "localhost"): nginx binds IPv4 0.0.0.0:80, but localhost can
# resolve to IPv6 ::1 first inside the container -> connection refused. The
# compose service overrides this healthcheck; keep them in sync.
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -q --spider http://127.0.0.1/index.html || exit 1
CMD ["nginx", "-g", "daemon off;"]
