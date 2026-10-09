# Образ веб-приложения: сборка Vite, раздача статики nginx.
#
#   docker build -f frontend/Dockerfile -t fsp-talent-web frontend
#
# Адрес API вшивается в бандл на этапе сборки (так работает Vite), поэтому
# он передаётся аргументом, а не переменной окружения контейнера.

FROM node:22-alpine AS build

ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=$VITE_API_BASE

WORKDIR /app

# Отдельный слой для зависимостей: переустанавливаются только при смене lock-файла
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

ARG VITE_API_BASE=http://localhost:8000

COPY nginx.conf /etc/nginx/conf.d/default.conf
# адрес API в Content-Security-Policy (connect-src) — тот же, что вшит в бандл
RUN sed -i "s|__API_ORIGIN__|${VITE_API_BASE}|" /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
