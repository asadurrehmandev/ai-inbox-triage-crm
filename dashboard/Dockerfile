FROM node:22-bookworm-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ENV NEXT_PUBLIC_API_BASE=http://localhost:8741/api
RUN npm run build

EXPOSE 8742

CMD ["npm", "start"]
