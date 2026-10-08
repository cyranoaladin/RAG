import { execFileSync } from 'node:child_process'
import path from 'node:path'

import { jwtVerify } from 'jose'
import { describe, expect, it } from 'vitest'

import finalScopes from '@/generated/final-retrieval-scopes-v4-v5.json'
import { canonicalScopeDigest } from '@/server/pilot-scope'

const helper = path.resolve(process.cwd(), 'scripts/mint-session-token.mjs')

describe('session synthétique de qualification BFF', () => {
  it.each(['teacher', 'student'])('signe le scope NSI mono-collection pour %s', async (role) => {
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
    const { payload: claims } = await jwtVerify(
      minted.internal_access_token,
      new TextEncoder().encode('internal-secret-qualification-1234567890'),
    )
    expect(claims.scope_id).toBe('prod_nsi_terminale_specialite_v3')
    expect(claims.scope_digest).toBe('dd6eeafd7749b9cd7f3084fec826707100756f330005a68f385d0dada1979b2d')
    expect(claims.allowed_collections).toEqual(['rag_nexus_nsi_terminale_specialite'])
    expect((claims.identity as { role: string }).role).toBe(role)
  })

  it('refuse de signer un profil sans scope final ni pilote', () => {
    expect(() => execFileSync('node', [helper], {
      cwd: process.cwd(),
      input: JSON.stringify({
        nextauth_secret: 'nextauth-secret-qualification-1234567890',
        internal_token_secret: 'internal-secret-qualification-1234567890',
        matieres: ['nsi'],
        candidat: 'scolarise',
      }),
      encoding: 'utf8',
      stdio: ['pipe', 'pipe', 'pipe'],
    })).toThrow()
  })

  it.each(finalScopes)('signe exactement le scope canonique $scope_id', async (scope) => {
    const target = scope.target_identity
    const output = execFileSync('node', [helper], {
      cwd: process.cwd(),
      input: JSON.stringify({
        nextauth_secret: 'nextauth-secret-qualification-1234567890',
        internal_token_secret: 'internal-secret-qualification-1234567890',
        tenant: target.tenant,
        niveau: target.niveau,
        voie: target.voie,
        matieres: [target.matiere],
        statut_enseignement: target.statut_enseignement,
        candidat: target.candidates[0],
        audience: target.audience,
        school_year: scope.evidence_subject.school_year,
      }),
      encoding: 'utf8',
    })
    const minted = JSON.parse(output)
    const { payload } = await jwtVerify(
      minted.internal_access_token,
      new TextEncoder().encode('internal-secret-qualification-1234567890'),
    )
    expect(payload.scope_id).toBe(scope.scope_id)
    expect(payload.scope_digest).toBe(canonicalScopeDigest(scope))
    expect(payload.allowed_collections).toEqual([scope.evidence_subject.collection])
  })
})
