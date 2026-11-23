# syntax=docker/dockerfile:1
ARG POSTGRES_IMAGE
ARG CADDY_IMAGE

FROM ${POSTGRES_IMAGE} AS postgres
COPY --chmod=0555 containers/gcp/10-application.sh /docker-entrypoint-initdb.d/10-application.sh

FROM ${CADDY_IMAGE} AS ingress
COPY containers/gcp/Caddyfile /etc/caddy/Caddyfile
