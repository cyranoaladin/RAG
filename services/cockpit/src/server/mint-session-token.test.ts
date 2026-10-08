import { execFileSync } from 'node:child_process'
import path from 'node:path'

import { decodeJwt } from 'jose'
import { describe, expect, it } from 'vitest'

const helper = path.resolve(process.cwd(), 'scripts/mint-session-token.mjs')

describe('session synthétique de qualification BFF', () => {
  it.each(['teacher', 'student'])('signe le scope NSI mono-collection pour %s', (role) => {
    const output = execFileSync('node', [helper], {
      cwd: process.cwd(),
      input: JSON.stringify({
        nextauth_secret: 'nextauth-secret-qualification-1234567890',
        internal_token_secret: 'internal-secret-qualification-1234567890',
        matieres: ['nsi'],
        role,
        candidat: 'libre',
      }),
      encoding: 'utf8',
    })
    const minted = JSON.parse(output)
    const claims = decodeJwt(minted.internal_access_token)
    expect(claims.scope_id).toBe('prod_nsi_terminale_specialite_v3')
    expect(claims.allowed_collections).toEqual(['rag_nexus_nsi_terminale_specialite'])
    expect((claims.identity as { role: string }).role).toBe(role)
  })
})
