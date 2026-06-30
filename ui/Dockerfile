# Multi-stage: build the static SPA with node, then serve it with nginx.
# nginx also reverse-proxies /v1 and /healthz to the kernel service.

FROM node:20-alpine AS build
WORKDIR /app

# Install dependencies first for better layer caching.
COPY package.json package-lock.json* ./
RUN npm install

COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -q --spider http://localhost/index.html || exit 1
CMD ["nginx", "-g", "daemon off;"]
