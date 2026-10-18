# KisanMitra edge image: React PWA static files served by Caddy (TLS, HTTP/3, compression, load balancing).
# Build context: repository root.
#
# Stage 1 builds the Vite PWA with VITE_API_URL="/api" so the compiled bundle
# calls same-origin /api/* paths, which Caddy proxies to the backend with the
# /api prefix stripped (handle_path).

# ── Stage 1: Node build ───────────────────────────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# VITE_API_URL="/api" → API calls go to the same origin under the /api prefix.
# Caddy handle_path /api/* strips the prefix before proxying to api-a / api-b.
# An empty base would send fetches to /prices etc., which Caddy would answer
# with the SPA fallback instead of the API — "/api" is required here.
RUN VITE_API_URL="/api" npm run build

# ── Stage 2: Caddy runtime ────────────────────────────────────────────────────
FROM caddy:2-alpine AS runtime

# Caddyfile is sourced from the deploy directory so it is versioned with the repo.
COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile

# Vite outputs to frontend/dist/
COPY --from=frontend-build /app/dist /srv

EXPOSE 80 443 443/udp
