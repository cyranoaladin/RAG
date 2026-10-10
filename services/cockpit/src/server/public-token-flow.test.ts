import { decodeJwt } from 'jose'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { InternalIdentity } from '@/generated/contracts'

const NOW = 1_800_000_000
const subjects = ['nsi', 'hggsp', 'hlp', 'ses', 'svt', 'dgemc', 'maths', 'francais', 'philo', 'pc', 'snt']
const scopes = subjects.map((matiere, index) => ({
  artifact_version: '3',
  scope_id: `student_public_${matiere}_terminale_specialite_v1`,
  status: 'eligible_for_promotion',
  source_sha256: String(index).padStart(64, 'a'),
  target_policy: {
    tenant: 'libre_terminale', niveau: 'terminale', voie: 'generale',
    matiere, statut_enseignement: 'specialite', audiences: ['libre'],
    candidates: ['libre'], roles: ['student'],
  },
  evidence_subject: {
    collection: `rag_nexus_${matiere}_terminale_specialite`,
    tenant: 'libre_terminale', niveau: 'terminale', voie: 'generale',
    matiere, statut_enseignement: 'specialite', candidat: 'libre',
    audiences: ['libre'], visibility: 'public', rights: ['public_allowed'],
    school_year: '2026-2027', programme_version: 'BOEN_2026',
  },
}))

const identity: InternalIdentity = {
  iss: 'nexus-issuer', aud: 'nexus-cockpit', sub: 'psn_1234567890abcdef',
  jti: 'jti-12345', exp: NOW + 600, tenant: 'libre_terminale',
  niveau: 'terminale', role: 'student', school_year: '2026-2027',
  pedagogical_profile: {
    voie: 'generale', matieres: ['nsi'], statut_enseignement: 'specialite',
    candidat: 'libre', audience: 'libre',
  },
}

describe('transport signé d’un scope public V3', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.resetModules()
    vi.doUnmock('@/generated/public-retrieval-scopes-v3.json')
    for (const name of [
      'NEXUS_COCKPIT_SCOPE_MODE', 'NEXUS_COCKPIT_PUBLIC_SCOPE_INDEX_SHA256',
      'NEXUS_INTERNAL_TOKEN_SECRET', 'NEXUS_INTERNAL_TOKEN_ISSUER',
      'NEXUS_INTERNAL_TOKEN_AUDIENCE', 'NEXUS_SSO_ISSUER', 'NEXUS_SSO_AUDIENCE',
    ]) delete process.env[name]
  })

  it('signe seulement la collection mono-matière et refuse rôle hors politique ou digest altéré', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(NOW * 1000)
    vi.resetModules()
    vi.doMock('@/generated/public-retrieval-scopes-v3.json', () => ({ default: scopes }))
    process.env.NEXUS_COCKPIT_SCOPE_MODE = 'public_v3'
    process.env.NEXUS_INTERNAL_TOKEN_SECRET = 'internal-secret-long-enough-for-tests'
    process.env.NEXUS_INTERNAL_TOKEN_ISSUER = 'cockpit-internal'
    process.env.NEXUS_INTERNAL_TOKEN_AUDIENCE = 'rag-engine'
    process.env.NEXUS_SSO_ISSUER = 'nexus-issuer'
    process.env.NEXUS_SSO_AUDIENCE = 'nexus-cockpit'

    const { publicScopeIndexDigest } = await import('@/server/public-scope')
    process.env.NEXUS_COCKPIT_PUBLIC_SCOPE_INDEX_SHA256 = publicScopeIndexDigest()
    const { mintInternalIdentityToken, verifyInternalIdentityToken } = await import('@/server/internal-token')
    const token = await mintInternalIdentityToken(identity)
    const claims = decodeJwt(token)
    expect(claims.allowed_collections).toEqual(['rag_nexus_nsi_terminale_specialite'])
    expect(claims.scope_id).toBe('student_public_nsi_terminale_specialite_v1')
    await expect(verifyInternalIdentityToken(token)).resolves.toMatchObject({ identity })
    await expect(mintInternalIdentityToken({ ...identity, role: 'teacher' })).rejects.toThrow()
    await expect(mintInternalIdentityToken({ ...identity, pedagogical_profile: {
      ...identity.pedagogical_profile, matieres: ['nsi', 'maths'],
    } })).rejects.toThrow()
    process.env.NEXUS_COCKPIT_PUBLIC_SCOPE_INDEX_SHA256 = 'b'.repeat(64)
    await expect(verifyInternalIdentityToken(token)).rejects.toThrow()
  })
})
