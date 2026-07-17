FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

# Release/build metadata - read at runtime (not NEXT_PUBLIC_*, so never
# baked into the client bundle) by src/app/api/version/route.ts. See
# services/api/Dockerfile's identical block and the Makefile's prod-build
# target for how these get computed and passed in.
ARG GIT_COMMIT=unknown
ARG BUILD_TIME=unknown
ARG APP_VERSION=0.1.0
ENV GIT_COMMIT=${GIT_COMMIT}
ENV BUILD_TIME=${BUILD_TIME}
ENV APP_VERSION=${APP_VERSION}

# Production Next.js build/runtime - also what scripts/check-env.js reads to
# decide whether a failed check is fatal (see package.json's "start" script
# and the check-env.js docstring). Set once here so both this build stage
# and the deployed container agree on it.
ENV NODE_ENV=production

# Build-phase check: catches a secret-like NEXT_PUBLIC_* var (it would be
# baked into the client bundle by the build below) and a missing
# NEXT_PUBLIC_API_URL. Skips API_INTERNAL_URL - that's a runtime-only server
# env var not available at build time (checked again in the "start" script
# instead, right before `next start`).
RUN node scripts/check-env.js build
RUN npm run build

# Docker sets HOSTNAME to the container ID by default, which Next.js's
# server would otherwise try to bind to instead of all interfaces - pin it
# to 0.0.0.0 so `next start` (see package.json's start script, which also
# passes -H 0.0.0.0 -p 3000 explicitly) is reachable via the published port.
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

EXPOSE 3000

CMD ["npm", "start"]
