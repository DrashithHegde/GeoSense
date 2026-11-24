# syntax=docker/dockerfile:1.7
FROM node:20-alpine AS build

WORKDIR /app

ARG VITE_API_URLS=http://localhost:8000
ENV VITE_API_URLS=$VITE_API_URLS

COPY package*.json ./
RUN npm ci

COPY . .
RUN --mount=type=secret,id=mapbox_public_token \
    VITE_MAPBOX_TOKEN="$(cat /run/secrets/mapbox_public_token)" npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
