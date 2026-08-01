import { SignJWT } from 'jose'
import { afterEach, describe, expect, it } from 'vitest'

import {
  clearVerifierStoresForTests,
  verifyNexusToken,
} from '@/server/sso-verifier'
import { resetSessionStoreForTests, revokeSession } from '@/server/revocation-store'

const SHARED_SECRET = 'nexus-shared-secret-for-tests'

const basePayload = {
  iss: 'nexus-cockpit',
  aud: 'nexus-cockpit',
  aud_profile: 'nexus-cockpit',
  sub: 'psn_testsubject0000001',
  tenant: 'default_tenant',
  niveau: 'terminale',
  role: 'student',
  jti: 'jti_valid',
  pedagogical_profile: {
    voie: 'generale',
    matieres: ['mathematiques', 'physique_chimie'],
    statut_enseignement: 'enseignement_commun',
    candidat: 'scolarise',
    audience: 'libre',
  },
}

function withEnv() {
  process.env.NEXUS_SSO_SHARED_SECRET = SHARED_SECRET
  process.env.NEXUS_SSO_ISSUER = basePayload.iss
  process.env.NEXUS_SSO_AUDIENCE = basePayload.aud
  process.env.NEXUS_RELEASE_SCHOOL_YEAR = '2026-2027'
  process.env.NEXUS_SESSION_STORE_MODE = 'memory'
  process.env.NEXUS_SESSION_MEMORY_STORE_FOR_TESTS = 'true'
}

async function mintToken(overrides: Partial<typeof basePayload> = {}, expiresInSeconds = 120): Promise<string> {
  const now = Math.floor(Date.now() / 1000)
  const duration = Math.max(expiresInSeconds, -3600)
  const payload = {
    ...basePayload,
    ...overrides,
    exp: now + duration,
  }

  return new SignJWT(payload)
    .setProtectedHeader({ alg: 'HS256' })
    .setIssuedAt(now)
    .setExpirationTime(duration > 0 ? now + duration : now - 1)
    .setIssuer(basePayload.iss)
    .setAudience(basePayload.aud)
    .sign(new TextEncoder().encode(SHARED_SECRET))
}

describe('vérification des identités SSO', () => {
  afterEach(async () => {
    await clearVerifierStoresForTests()
    delete process.env.NEXUS_SESSION_STORE_MODE
    delete process.env.NEXUS_SESSION_MEMORY_STORE_FOR_TESTS
    resetSessionStoreForTests()
  })

  it('valide un jeton SSO complet et produit l\'identité interne', async () => {
    withEnv()
    const token = await mintToken()

    const identity = await verifyNexusToken(token)

    expect(identity.sub).toBe(basePayload.sub)
    expect(identity.tenant).toBe('default_tenant')
    expect(identity.pedagogical_profile.matieres).toEqual(basePayload.pedagogical_profile.matieres)
    expect(identity.role).toBe('student')
    expect(identity.school_year).toBe('2026-2027')
  })

  it('ignore toute année scolaire fournie par le jeton externe', async () => {
    withEnv()
    const token = await mintToken({ school_year: '2030-2031' } as Partial<typeof basePayload>)

    const identity = await verifyNexusToken(token)

    expect(identity.school_year).toBe('2026-2027')
  })

  it('refuse une année de release absente ou non contiguë', async () => {
    withEnv()
    process.env.NEXUS_RELEASE_SCHOOL_YEAR = '2026-2028'
    const token = await mintToken({ jti: 'invalid-year' })

    await expect(verifyNexusToken(token)).rejects.toThrow(
      'Configuration SSO invalide: NEXUS_RELEASE_SCHOOL_YEAR',
    )
  })

  it('rejette un jeton expiré', async () => {
    withEnv()
    const token = await mintToken({}, -20)

    await expect(verifyNexusToken(token)).rejects.toThrow()
  })

  it('rejette un jeton avec jti déjà consommé', async () => {
    withEnv()
    const token = await mintToken()

    await expect(verifyNexusToken(token)).resolves.toBeDefined()
    await expect(verifyNexusToken(token)).rejects.toThrow()
  })

  it('rejette un jeton revoké', async () => {
    withEnv()
    await revokeSession(basePayload.sub, basePayload.tenant)
    const token = await mintToken({ jti: 'revoked' })

    await expect(verifyNexusToken(token)).rejects.toThrow()
  })

  it('bloque un sujet partagée entre deux tenants', async () => {
    withEnv()
    const tokenA = await mintToken({ jti: 'tenant_a', tenant: 'tenant_a' })
    const tokenB = await mintToken({ jti: 'tenant_b', tenant: 'tenant_b' })

    await expect(verifyNexusToken(tokenA)).resolves.toBeDefined()
    await expect(verifyNexusToken(tokenB)).rejects.toThrow()
  })
})
