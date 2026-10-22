FROM node:22-bookworm-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# The API token and desk password are runtime environment variables.
# They are not build arguments, so they are not compiled into the browser bundle.
RUN npm run build

EXPOSE 8742

CMD ["npm", "start"]
