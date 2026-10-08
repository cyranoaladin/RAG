import { spawnSync } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { statSync } from 'node:fs'
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

  it('vérifie le digest épinglé sans environnement Python', async () => {
    const scope = JSON.parse(await readFile(path.join(artifactRoot, 'retrieval-scope-prod-nsi-terminale-specialite-v3.json'), 'utf8'))
    const previousPath = process.env.PATH
    process.env.PATH = ''
    try {
      expect(() => verifyGovernedFinalScopes([scope], root)).not.toThrow()
    } finally {
      process.env.PATH = previousPath
    }
  })

  it('importe le générateur sans réécrire les fichiers produits', () => {
    const generated = path.resolve(process.cwd(), 'src/generated/final-retrieval-scopes-v4-v5.json')
    const before = statSync(generated, { bigint: true }).mtimeNs
    const imported = spawnSync(process.execPath, ['--input-type=module', '-e', "await import('./scripts/generate-contracts.mjs')"], {
      cwd: process.cwd(),
      encoding: 'utf8',
    })
    expect(imported.status).toBe(0)
    expect(statSync(generated, { bigint: true }).mtimeNs).toBe(before)
  })
})
