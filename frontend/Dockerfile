# ---------- build: compile the Vite production bundle ----------
FROM node:26.12.1-alpine@sha256:40cd011b55415bc894e45b02fdd5a5dfde056921b7d23a64c74f80497af48797 AS build
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
