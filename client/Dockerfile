# syntax=docker/dockerfile:1

FROM node:24-bookworm-slim AS build

WORKDIR /app
RUN corepack enable

# Dependencies first so this layer is cached unless package.json/lockfile change.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
# --trust-lockfile: skip pnpm's per-entry minimumReleaseAge/trust-policy
# re-verification -- pnpm-lock.yaml is already a trusted, reviewed artifact
# (frozen-lockfile pins it exactly), and without this a fast-moving
# transitive dep (e.g. baseline-browser-mapping, published almost daily)
# can fail the build purely because it's "too new" relative to build time.
RUN pnpm install --frozen-lockfile --trust-lockfile

COPY . .

# Vite bakes VITE_* vars in at build time. Behind the prod reverse proxy the
# client and API share an origin, so /api (stripped by the proxy) is enough --
# no CORS configuration needed for this deployment.
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN pnpm build

FROM nginx:1.27-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://localhost/ >/dev/null || exit 1
