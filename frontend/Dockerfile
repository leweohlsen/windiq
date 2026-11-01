# ---------- build: compile the Vite production bundle ----------
FROM node:26.13.0-alpine@sha256:c6ad9e9c1d80f6eb607c26b4b0a132ff7a2344fad1c78ea3baa2a7d4c8de6d94 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# ---------- runtime: nginx serves the static bundle (final/default stage) ----------
FROM nginx:1.30.6-alpine@sha256:47928bf67eb62a1863cb08d9ecb52d3e704304ba614eaee17884204677702951 AS runtime
RUN apk add --no-cache apache2-utils
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY 95-basic-auth.sh /docker-entrypoint.d/95-basic-auth.sh
RUN chmod 0755 /docker-entrypoint.d/95-basic-auth.sh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
