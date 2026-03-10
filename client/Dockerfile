# Étape 1 : Construction de l'app React (Vite)
FROM node:20-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# Étape 2 : Service avec Nginx unifié (3300)
FROM nginx:alpine
# On injecte une config nginx qui écoute sur le port 3300
RUN echo 'server { \
    listen 3300; \
    server_name localhost; \
    location / { \
    root /usr/share/nginx/html; \
    index index.html; \
    try_files $uri $uri/ /index.html; \
    } \
    }' > /etc/nginx/conf.d/default.conf

COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 3300
CMD ["nginx", "-g", "daemon off;"]
