# Build context is the repo root:
#   docker build -f addon/Dockerfile --build-arg BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20 .
# CI (.github/workflows/addon.yml) builds amd64 + aarch64 this way and pushes them to GHCR (config.yaml `image:`).
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20

# ---- Frontend: built once on the build machine's platform; the output is plain static files.
FROM --platform=$BUILDPLATFORM node:22-alpine AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# src/api/demo.ts imports ../../../seed/demo.json (type-checked by `npm run build`).
COPY seed /src/seed
RUN npm run build

# ---- Add-on image
FROM ${BUILD_FROM}
ARG BUILD_ARCH=amd64
ARG BUILD_VERSION=0.2.0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MOONLIGHT_DB=/data/moonlight.db \
    MOONLIGHT_SEED=/app/seed/demo.json \
    MOONLIGHT_STATIC=/app/frontend/dist \
    MOONLIGHT_PORT=8091 \
    MOONLIGHT_HTTPS_PORT=8443

# tzdata: zone files so TZ (Home Assistant's timezone, set in run.sh) works with musl.
RUN apk add --no-cache tzdata

WORKDIR /app/backend

COPY backend/requirements.txt /app/backend/requirements.txt
# Every dependency ships musllinux wheels for amd64 and aarch64, so no compiler is needed.
RUN pip3 install --no-cache-dir --prefer-binary -r requirements.txt

COPY backend/moonlight /app/backend/moonlight
COPY seed /app/seed
COPY --from=frontend /src/frontend/dist /app/frontend/dist
COPY addon/run.sh /run.sh
RUN chmod a+x /run.sh

EXPOSE 8091 8443
CMD ["/run.sh"]

LABEL io.hass.type="addon" \
      io.hass.name="Moonlight" \
      io.hass.version="${BUILD_VERSION}" \
      io.hass.arch="${BUILD_ARCH}" \
      org.opencontainers.image.title="Moonlight" \
      org.opencontainers.image.description="Family wall calendar, chores, lists and meal planner for kiosk displays" \
      org.opencontainers.image.version="${BUILD_VERSION}" \
      org.opencontainers.image.source="https://github.com/chris-standley/Moonlight-Calendar"
