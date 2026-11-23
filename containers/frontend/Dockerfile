ARG NODE_IMAGE
FROM ${NODE_IMAGE} AS dependencies
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM dependencies AS development
RUN chown node:node /app/node_modules
USER node
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM dependencies AS build
COPY frontend ./
RUN npm run build

FROM ${NODE_IMAGE} AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY --from=build --chown=node:node /app/dist ./dist
COPY --chown=node:node frontend/server.mjs ./server.mjs
USER node
CMD ["node", "server.mjs"]

FROM ${NODE_IMAGE} AS ingress
WORKDIR /app
COPY --chown=node:node containers/frontend/ingress.mjs ./ingress.mjs
USER node
CMD ["node", "ingress.mjs"]
