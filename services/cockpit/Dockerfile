FROM node:22.22.0-bookworm-slim@sha256:7cc56ef285a8568121537d17b05e72128f01b89c54607b51acf084a50ef483f3 AS builder

ARG SOURCE_COMMIT_SHA
ENV NEXUS_COCKPIT_BUILD_SHA=${SOURCE_COMMIT_SHA} \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /workspace

COPY services/cockpit/package.json services/cockpit/package-lock.json ./services/cockpit/
RUN cd services/cockpit && npm ci --no-audit --no-fund

COPY services/cockpit/ ./services/cockpit/
COPY packages/contracts/schema/ ./packages/contracts/schema/
COPY packages/contracts/src/nexus_contracts/artifacts/pilot-retrieval-scope-v1.json ./packages/contracts/src/nexus_contracts/artifacts/pilot-retrieval-scope-v1.json
COPY packages/contracts/src/nexus_contracts/artifacts/retrieval-scope-prod-*.json ./packages/contracts/src/nexus_contracts/artifacts/
COPY services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json ./services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json

RUN printf '%s' "$SOURCE_COMMIT_SHA" | grep -Eq '^[0-9a-f]{40}$' \
 && cd services/cockpit \
 && mkdir -p public \
 && npm test -- --run \
 && npm run lint \
 && npm run typecheck \
 && npm run build:container \
 && test "$(cat .next/BUILD_ID)" = "$SOURCE_COMMIT_SHA"

FROM node:22.22.0-bookworm-slim@sha256:7cc56ef285a8568121537d17b05e72128f01b89c54607b51acf084a50ef483f3 AS runtime

ARG SOURCE_COMMIT_SHA
LABEL org.opencontainers.image.revision=${SOURCE_COMMIT_SHA}
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app

COPY --from=builder --chown=node:node /workspace/services/cockpit/.next/standalone/ ./
COPY --from=builder --chown=node:node /workspace/services/cockpit/.next/static/ ./.next/static/
COPY --from=builder --chown=node:node /workspace/services/cockpit/public/ ./public/

USER node
EXPOSE 3000
CMD ["node", "server.js"]
