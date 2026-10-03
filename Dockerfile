FROM node:22-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY server.js coach.js ./
COPY public ./public
# Mount a persistent volume at /data or your sessions vanish on every redeploy.
ENV NODE_ENV=production HOST=0.0.0.0 PORT=3000 DATA_DIR=/data TRUST_PROXY=1
EXPOSE 3000
CMD ["node", "server.js"]
