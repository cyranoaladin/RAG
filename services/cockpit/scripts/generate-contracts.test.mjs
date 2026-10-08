import { readFile } from 'node:fs/promises'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { verifyGovernedFinalScopes } from './generate-contracts.mjs'

const root = path.resolve(process.cwd(), '../../packages/contracts/src')
const artifactRoot = path.join(root, 'nexus_contracts/artifacts')

describe('projection des scopes gouvernés', () => {
  it('refuse une altération compatible avec le schéma mais non autorisée par le registre épinglé', async () => {
    const scope = JSON.parse(await readFile(path.join(artifactRoot, 'retrieval-scope-prod-nsi-terminale-specialite-v3.json'), 'utf8'))
    expect(() => verifyGovernedFinalScopes([scope], root)).not.toThrow()
    const altered = structuredClone(scope)
    altered.source_sha256 = '0'.repeat(64)
    expect(() => verifyGovernedFinalScopes([altered], root)).toThrow(/digest|governed|scope/i)
  })
})
