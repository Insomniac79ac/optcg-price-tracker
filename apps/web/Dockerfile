FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}

RUN npm run build

# Docker sets HOSTNAME to the container ID by default, which Next.js's
# server would otherwise try to bind to instead of all interfaces - pin it
# to 0.0.0.0 so `next start` (see package.json's start script, which also
# passes -H 0.0.0.0 -p 3000 explicitly) is reachable via the published port.
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

EXPOSE 3000

CMD ["npm", "start"]
