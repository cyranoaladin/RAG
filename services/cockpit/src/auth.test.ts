import type { Session } from 'next-auth'
import { describe, expect, it } from 'vitest'

import { authOptions } from '@/auth'

describe('projection navigateur de la session Auth.js', () => {
  it('ne sérialise ni jeton interne ni identité complète', async () => {
    const sessionCallback = authOptions.callbacks?.session
    if (!sessionCallback) throw new Error('session callback absent')

    const session: Session = {
      expires: new Date(Date.now() + 60_000).toISOString(),
      user: { name: 'Nexus 12345678', email: null, image: null },
    }
    const browserSession = await sessionCallback({
      session,
      token: {
        sub: 'psn_1234567890abcdef',
        internalAccessToken: 'signed-internal-secret-token',
        identityRotatedAt: Date.now(),
        identity: {
          tenant: 'libre_terminale',
          niveau: 'terminale',
        },
      },
    } as never)
    const serialized = JSON.stringify(browserSession)

    expect(serialized).not.toContain('signed-internal-secret-token')
    expect(serialized).not.toContain('libre_terminale')
    expect(serialized).not.toContain('internalAccessToken')
    expect(serialized).not.toContain('internalIdentity')
  })

  it('ne duplique pas l’identité complète dans le JWT de session', async () => {
    const jwtCallback = authOptions.callbacks?.jwt
    if (!jwtCallback) throw new Error('jwt callback absent')

    const token = await jwtCallback({
      token: {},
      user: {
        id: 'psn_1234567890abcdef',
        name: 'Nexus 12345678',
        email: null,
        internalIdentity: {
          tenant: 'libre_terminale',
          niveau: 'terminale',
        },
        internalAccessToken: 'signed-internal-secret-token',
        internalTokenIssuedAt: Date.now(),
      },
      account: null,
      profile: undefined,
      isNewUser: false,
      trigger: 'signIn',
    } as never)

    expect(token).not.toHaveProperty('identity')
    expect(token).toMatchObject({
      internalAccessToken: 'signed-internal-secret-token',
    })
  })
})
