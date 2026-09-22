FROM node:24-alpine AS build

WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
# The merged router loads the preserved ERP pages from a sibling source tree.
# Keep the same relative layout inside the build image; otherwise Vite's glob
# is valid but resolves to an empty module map and every /erp route is blank.
COPY apps/erp-compat/web /erp-compat/web
RUN ln -s /app/node_modules /node_modules
RUN npm run build

FROM nginx:1.29-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
