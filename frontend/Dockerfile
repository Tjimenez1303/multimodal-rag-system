# Two stages: Node builds the static client, and nginx serves it and proxies /api to
# the API on the same origin (research section 4).

ARG NODE_IMAGE=node:24-alpine@sha256:ebfe2f90462722a7a4de65e91990e97fe0d401c70e0e762c5b53302f905ec1c1
ARG NGINX_IMAGE=nginx:1.30-alpine@sha256:0985e772fb9f729e6fa0980da05fca5d9c468e870eed43071545afa9d2e27d94

# Build stage: install dependencies and compile the client to dist/
FROM ${NODE_IMAGE} AS build
WORKDIR /app
# Dependencies get their own layer so source changes do not reinstall them.
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
# Then the source, type-checked and bundled by Vite
COPY . .
RUN npm run build

# Serve stage: nginx with the template and the built files only
FROM ${NGINX_IMAGE}
# Defaults for the runtime configuration. Compose sets them from .env.
ENV ANSWER_WAIT_SECONDS=105 \
    MAX_FILTER_DOCUMENTS=20 \
    STATUS_POLL_SECONDS=2 \
    NGINX_PROXY_READ_TIMEOUT=120
# The image renders /etc/nginx/templates/*.template into conf.d with envsubst at start.
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
# The static client nginx serves at /
COPY --from=build /app/dist /usr/share/nginx/html
