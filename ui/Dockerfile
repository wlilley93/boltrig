# Multi-stage: build the static SPA with node, then serve it with nginx.
# nginx also reverse-proxies /v1 and /healthz to the kernel service.

FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable

# Install with pnpm (the dev package manager) from the frozen lockfile, so the
# image is built from the SAME dependency graph developers run - reproducible.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile --ignore-scripts && pnpm rebuild esbuild

COPY . .
RUN pnpm run build

FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
# 127.0.0.1 (not "localhost"): nginx binds IPv4 0.0.0.0:80, but localhost can
# resolve to IPv6 ::1 first inside the container -> connection refused. The
# compose service overrides this healthcheck; keep them in sync.
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -q --spider http://127.0.0.1/index.html || exit 1
CMD ["nginx", "-g", "daemon off;"]
