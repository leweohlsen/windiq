# ---------- build: compile the Vite production bundle ----------
FROM node:26.11.1-alpine@sha256:143494b1da2945f061539253adc65e4f1569ddf07da2d384c022c791a9d90a4a AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# ---------- runtime: nginx serves the static bundle (final/default stage) ----------
FROM nginx:1.31.0-alpine@sha256:2f07d83bf561b506400dc183b1b2003803e39efbd22451f848adaba14d28c7c7 AS runtime
RUN apk add --no-cache apache2-utils
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY 95-basic-auth.sh /docker-entrypoint.d/95-basic-auth.sh
RUN chmod 0755 /docker-entrypoint.d/95-basic-auth.sh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
