FROM node:22-alpine AS build
WORKDIR /app
# The lockfile is required, not optional (`package-lock.json*` let a build run
# without it), and `npm ci` installs exactly what it pins -- the same command
# CI runs. `npm install` could resolve a different tree from the same ranges.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
