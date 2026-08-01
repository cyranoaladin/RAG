import { SignJWT, decodeJwt, decodeProtectedHeader } from 'jose'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { InternalIdentity } from '@/generated/contracts'
import {
  mintInternalIdentityToken,
  rotateInternalIdentityToken,
  verifyInternalIdentityToken,
} from '@/server/internal-token'

const NOW_SECONDS = 1_800_000_000

function identity(): InternalIdentity {
  return {
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
}

function configureTransport(): void {
  process.env.NEXUS_INTERNAL_TOKEN_SECRET = 'internal-secret-long-enough-for-tests'
  process.env.NEXUS_INTERNAL_TOKEN_ISSUER = 'cockpit-internal'
  process.env.NEXUS_INTERNAL_TOKEN_AUDIENCE = 'rag-engine'
  process.env.NEXUS_SSO_ISSUER = 'nexus-issuer'
  process.env.NEXUS_SSO_AUDIENCE = 'nexus-cockpit'
}

describe('jeton interne cockpit vers moteur', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(NOW_SECONDS * 1000)
    configureTransport()
  })

  afterEach(() => {
    vi.useRealTimers()
    delete process.env.NEXUS_INTERNAL_TOKEN_SECRET
    delete process.env.NEXUS_INTERNAL_TOKEN_ISSUER
    delete process.env.NEXUS_INTERNAL_TOKEN_AUDIENCE
    delete process.env.NEXUS_SSO_ISSUER
    delete process.env.NEXUS_SSO_AUDIENCE
    delete process.env.COCKPIT_INTERNAL_TOKEN_SECRET
  })

  it('signe exactement une enveloppe 0.4 imbriquée liée au scope canonique', async () => {
    const token = await mintInternalIdentityToken(identity())
    const header = decodeProtectedHeader(token)
    const payload = decodeJwt(token)

    expect(header).toEqual({ alg: 'HS256', typ: 'JWT' })
    expect(payload).toMatchObject({
      protocol_version: '1',
      iss: 'cockpit-internal',
      aud: 'rag-engine',
      sub: identity().sub,
      jti: identity().jti,
      identity: identity(),
      scope_id: 'libre_terminale_maths_nsi_real_v1',
      scope_digest: 'a1ed0fb1c7ec6344c17b155004d5bb61172b77f4b5bff6f5a250cc8b968fdd24',
      allowed_collections: [
        'rag_nexus_maths_terminale_gen_specialite',
        'rag_nexus_nsi_terminale_specialite',
      ],
    })
    expect(payload.exp).toBe(NOW_SECONDS + 300)
  })

  it('préserve strictement identité et scope pendant une rotation', async () => {
    const initial = await mintInternalIdentityToken(identity())
    const before = await verifyInternalIdentityToken(initial)
    vi.setSystemTime((NOW_SECONDS + 120) * 1000)

    const rotated = await rotateInternalIdentityToken(initial)
    const after = await verifyInternalIdentityToken(rotated)

    expect(after.identity).toEqual(before.identity)
    expect(after.sub).toBe(before.sub)
    expect(after.jti).toBe(before.jti)
    expect(after.scope_id).toBe(before.scope_id)
    expect(after.scope_digest).toBe(before.scope_digest)
    expect(after.allowed_collections).toEqual(before.allowed_collections)
    expect(after.iat).toBe(NOW_SECONDS + 120)
  })

  it('refuse une signature interne altérée', async () => {
    const token = await mintInternalIdentityToken(identity())
    const altered = `${token.slice(0, -1)}${token.endsWith('a') ? 'b' : 'a'}`

    await expect(verifyInternalIdentityToken(altered)).rejects.toThrow(
      'Jeton interne invalide ou expiré',
    )
  })

  it('refuse une année scolaire non contiguë malgré le pattern JSON', async () => {
    const invalidIdentity = { ...identity(), school_year: '2026-2028' }

    await expect(mintInternalIdentityToken(invalidIdentity)).rejects.toThrow(
      'Identité interne non conforme au contrat 0.4',
    )
  })

  it.each([
    ['iat futur', NOW_SECONDS + 10, NOW_SECONDS + 300],
    ['TTL trop long', NOW_SECONDS, NOW_SECONDS + 301],
  ])('refuse un transport avec %s', async (_label, iat, exp) => {
    const valid = decodeJwt(await mintInternalIdentityToken(identity()))
    const token = await new SignJWT({ ...valid, iat, exp })
      .setProtectedHeader({ alg: 'HS256', typ: 'JWT' })
      .sign(new TextEncoder().encode(process.env.NEXUS_INTERNAL_TOKEN_SECRET))

    await expect(verifyInternalIdentityToken(token)).rejects.toThrow(
      'Jeton interne hors fenêtre temporelle',
    )
  })
})
