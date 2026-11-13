FROM node:22-bookworm-slim
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build && chown -R node:node /app
USER node
# Inside the container the dev server must listen on all interfaces; Compose publishes it
# on the loopback interface only. Outside a container `npm run dev` binds to localhost.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
