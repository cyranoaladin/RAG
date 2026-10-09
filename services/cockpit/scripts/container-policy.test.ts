import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const cockpitRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dockerfile = path.join(cockpitRoot, 'Dockerfile')

describe('image Cockpit de production', () => {
  it('construit depuis une base épinglée et exécute un bundle non-root', () => {
    const source = readFileSync(dockerfile, 'utf8')

    expect(source).toMatch(/^FROM node:22\.22\.0-bookworm-slim@sha256:[0-9a-f]{64} AS builder/m)
    expect(source).toContain('npm ci --no-audit --no-fund')
    expect(source).toContain('npm run build:container')
    expect(source).toMatch(/COPY --from=builder .*\.next\/standalone/)
    expect(source).toMatch(/^USER node$/m)
    expect(source).toContain('CMD ["node", "server.js"]')
    expect(source).not.toMatch(/^COPY\s+\.\s+/m)
  })

  it('limite le contexte aux sources Cockpit et contrats nécessaires', () => {
    const source = readFileSync(path.join(cockpitRoot, 'Dockerfile.dockerignore'), 'utf8')

    expect(source).toMatch(/^\*\*$/m)
    expect(source).toContain('!services/cockpit/src/**')
    expect(source).toContain('!packages/contracts/schema/**')
    expect(source).toContain('services/cockpit/.env*')
    expect(source).toContain('services/cockpit/node_modules')
  })

  it('rend disponibles les scopes gouvernés et le registre final du BFF', () => {
    const dockerSource = readFileSync(dockerfile, 'utf8')
    const ignoreSource = readFileSync(path.join(cockpitRoot, 'Dockerfile.dockerignore'), 'utf8')

    expect(dockerSource).toContain('retrieval-scope-prod-*.json')
    expect(dockerSource).toContain('release-registry-v4-hggsp-complementary.json')
    expect(ignoreSource).toContain('!packages/contracts/src/nexus_contracts/artifacts/retrieval-scope-prod-*.json')
    expect(ignoreSource).toContain('!services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json')
  })
})
