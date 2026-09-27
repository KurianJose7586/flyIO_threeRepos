FROM node:22-alpine AS builder

WORKDIR /app

# Copy root and frontend package files
COPY package*.json ./
COPY frontend/package*.json ./frontend/

# Install dependencies
RUN npm ci
RUN npm ci --prefix frontend

# Copy all source files
COPY . .

# Build frontend and backend
RUN npm run build --prefix frontend
RUN npm run build

# Production runtime stage
FROM node:22-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production

COPY package*.json ./
RUN npm ci --omit=dev

COPY --from=builder /app/dist ./dist
COPY --from=builder /app/frontend/dist ./frontend/dist
COPY --from=builder /app/docs ./docs

EXPOSE 3000

CMD ["node", "dist/app.js"]
