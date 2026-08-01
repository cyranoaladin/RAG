import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { InternalIdentity } from '@/generated/contracts'
import { authOptions } from '@/auth'
import { mintInternalIdentityToken } from '@/server/internal-token'
import { decodeJwt } from 'jose'
import { requireBffAuth } from '@/server/bff-auth'
import {
  resetSessionStoreForTests,
  revokeSession,
} from '@/server/revocation-store'

const NOW_SECONDS = 1_800_000_000

const identity: InternalIdentity = {
  aud: 'nexus-cockpit',
  exp: NOW_SECONDS + 600,
  iss: 'nexus-issuer',
  jti: 'jti-12345',
  tenant: 'libre_terminale',
  niveau: 'terminale',
  role: 'student',
  school_year: '2026-2027',
  sub: 'psn_1234567890abcdef',
  pedagogical_profile: {
    voie: 'generale',
    matieres: ['maths', 'nsi'],
    statut_enseignement: 'specialite',
    candidat: 'individuel',
    audience: 'libre',
  },
}

function configure(): void {
  process.env.NEXUS_INTERNAL_TOKEN_SECRET = 'internal-secret-long-enough-for-tests'
  process.env.NEXUS_INTERNAL_TOKEN_ISSUER = 'cockpit-internal'
  process.env.NEXUS_INTERNAL_TOKEN_AUDIENCE = 'rag-engine'
  process.env.NEXUS_SSO_ISSUER = 'nexus-issuer'
  process.env.NEXUS_SSO_AUDIENCE = 'nexus-cockpit'
  process.env.NEXUS_SESSION_STORE_MODE = 'memory'
  process.env.NEXUS_SESSION_MEMORY_STORE_FOR_TESTS = 'true'
}

describe('authentification serveur des routes BFF', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(NOW_SECONDS * 1000)
    configure()
    resetSessionStoreForTests()
  })

  afterEach(() => {
    vi.useRealTimers()
    for (const name of [
      'NEXUS_INTERNAL_TOKEN_SECRET',
      'NEXUS_INTERNAL_TOKEN_ISSUER',
      'NEXUS_INTERNAL_TOKEN_AUDIENCE',
      'NEXUS_SSO_ISSUER',
      'NEXUS_SSO_AUDIENCE',
      'NEXUS_SESSION_STORE_MODE',
      'NEXUS_SESSION_MEMORY_STORE_FOR_TESTS',
    ]) delete process.env[name]
    resetSessionStoreForTests()
  })

  it('retourne le contexte signé uniquement depuis le JWT httpOnly', async () => {
    const internalAccessToken = await mintInternalIdentityToken(identity)
    const context = await requireBffAuth(
      new Request('http://cockpit.test/api/search'),
      async () => ({ sub: identity.sub, internalAccessToken }),
    )

    expect(context?.identity).toEqual(identity)
    expect(context?.identityToken).toBe(internalAccessToken)
    expect(context?.allowedCollections).toEqual([
      'rag_nexus_maths_terminale_gen_specialite',
      'rag_nexus_nsi_terminale_specialite',
    ])
  })

  it.each([
    [['maths'], ['rag_nexus_maths_terminale_gen_specialite']],
    [['nsi'], ['rag_nexus_nsi_terminale_specialite']],
    [['maths', 'nsi'], [
      'rag_nexus_maths_terminale_gen_specialite',
      'rag_nexus_nsi_terminale_specialite',
    ]],
  ])('borne les collections effectives aux matières signées %j', async (matieres, expected) => {
    const scopedIdentity = {
      ...identity,
      pedagogical_profile: { ...identity.pedagogical_profile, matieres },
    } as InternalIdentity
    const internalAccessToken = await mintInternalIdentityToken(scopedIdentity)

    const context = await requireBffAuth(
      new Request('http://cockpit.test/api/search'),
      async () => ({ sub: identity.sub, internalAccessToken }),
    )

    expect(context?.allowedCollections).toEqual(expected)
  })

  it('refuse une session absente ou non liée au sujet interne', async () => {
    const internalAccessToken = await mintInternalIdentityToken(identity)

    await expect(
      requireBffAuth(new Request('http://cockpit.test/api/search'), async () => null),
    ).resolves.toBeNull()
    await expect(
      requireBffAuth(
        new Request('http://cockpit.test/api/search'),
        async () => ({ sub: 'psn_abcdef1234567890', internalAccessToken }),
      ),
    ).resolves.toBeNull()
  })

  it('refuse une session révoquée avant de la remettre à une route', async () => {
    const internalAccessToken = await mintInternalIdentityToken(identity)
    await revokeSession(identity.jti, identity.sub, identity.tenant)

    await expect(
      requireBffAuth(
        new Request('http://cockpit.test/api/chat'),
        async () => ({ sub: identity.sub, internalAccessToken }),
      ),
    ).resolves.toBeNull()
  })

  it('révoque réellement le jti lors de la déconnexion Auth.js', async () => {
    const internalAccessToken = await mintInternalIdentityToken(identity)
    const signOut = authOptions.events?.signOut
    if (!signOut) throw new Error('événement signOut absent')

    await signOut({
      token: { sub: identity.sub, internalAccessToken },
    } as never)

    await expect(
      requireBffAuth(
        new Request('http://cockpit.test/api/search'),
        async () => ({ sub: identity.sub, internalAccessToken }),
      ),
    ).resolves.toBeNull()
  })

  it('rafraîchit le transport expiré tant que session et identité restent valides', async () => {
    const staleIdentityToken = await mintInternalIdentityToken(identity)
    vi.setSystemTime((NOW_SECONDS + 310) * 1000)

    const context = await requireBffAuth(
      new Request('http://cockpit.test/api/search'),
      async () => ({ sub: identity.sub, internalAccessToken: staleIdentityToken }),
    )

    expect(context).not.toBeNull()
    expect(context?.identityToken).not.toBe(staleIdentityToken)
    expect(decodeJwt(context?.identityToken || '').exp).toBeGreaterThan(NOW_SECONDS + 310)
  })
})
