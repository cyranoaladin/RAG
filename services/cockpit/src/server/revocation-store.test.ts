import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  MemorySessionBackend,
  SharedSessionSecurityStore,
  isRevoked,
  resetSessionStoreForTests,
} from '@/server/revocation-store'

describe('store partagé de sécurité de session', () => {
  afterEach(() => {
    vi.useRealTimers()
    delete process.env.NEXUS_SESSION_REDIS_URL
    delete process.env.NEXUS_SESSION_STORE_MODE
    delete process.env.NEXUS_SESSION_MEMORY_STORE_FOR_TESTS
    delete process.env.NEXUS_SESSION_TTL_SECONDS
    resetSessionStoreForTests()
  })

  it('conserve chaque jti jusqu’à l’expiration réelle du jeton SSO', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(1_800_000_000_000)
    const set = vi.fn(async () => 'OK')
    const store = new SharedSessionSecurityStore({
      get: async () => null,
      set,
    })

    await store.consumeOnce(
      'jti-long-session',
      1_800_007_200,
      'libre_terminale',
      'psn_1234567890abcdef',
    )

    expect(set).toHaveBeenCalledWith(
      'nexus:session:v1:jti:jti-long-session',
      expect.any(String),
      { EX: 7200, NX: true },
    )
  })

  it('partage la révocation entre instances et après recréation logique', async () => {
    const backend = new MemorySessionBackend()
    const instanceA = new SharedSessionSecurityStore(backend)
    const instanceB = new SharedSessionSecurityStore(backend)

    await instanceA.revokeSession(
      'jti-12345',
      'psn_1234567890abcdef',
      'libre_terminale',
    )

    await expect(
      instanceB.isRevoked('jti-12345', 'psn_1234567890abcdef', 'libre_terminale'),
    ).resolves.toBe(true)
    const restartedInstance = new SharedSessionSecurityStore(backend)
    await expect(
      restartedInstance.isRevoked(
        'jti-12345',
        'psn_1234567890abcdef',
        'libre_terminale',
      ),
    ).resolves.toBe(true)
  })

  it('ne raccourcit jamais la révocation sous la durée du cookie Auth.js', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(1_800_000_000_000)
    process.env.NEXUS_SESSION_TTL_SECONDS = '60'
    const set = vi.fn(async () => 'OK')
    const store = new SharedSessionSecurityStore({
      get: async () => null,
      set,
    })

    await store.revokeSession(
      'jti-short-config',
      'psn_1234567890abcdef',
      'libre_terminale',
    )

    expect(set).toHaveBeenCalledWith(
      'nexus:session:v1:revoked:libre_terminale:psn_1234567890abcdef:jti-short-config',
      '1',
      { EX: 3600 },
    )
  })

  it('rend atomiques la frontière tenant et la consommation du jti entre instances', async () => {
    const backend = new MemorySessionBackend()
    const instanceA = new SharedSessionSecurityStore(backend)
    const instanceB = new SharedSessionSecurityStore(backend)
    const exp = Math.floor(Date.now() / 1000) + 300

    await instanceA.assertTenantBoundary('psn_1234567890abcdef', 'libre_terminale')
    await expect(
      instanceB.assertTenantBoundary('psn_1234567890abcdef', 'aefe_terminale'),
    ).rejects.toThrow('tenant incompatible')

    await instanceA.consumeOnce('jti-12345', exp, 'libre_terminale', 'psn_1234567890abcdef')
    await expect(
      instanceB.consumeOnce('jti-12345', exp, 'libre_terminale', 'psn_1234567890abcdef'),
    ).rejects.toThrow('jti déjà consommé')
  })

  it('propage toute indisponibilité backend au lieu de laisser passer', async () => {
    const failingBackend = {
      get: async () => { throw new Error('redis unavailable') },
      set: async () => { throw new Error('redis unavailable') },
      clearForTests: () => undefined,
    }
    const store = new SharedSessionSecurityStore(failingBackend)

    await expect(
      store.isRevoked('jti-12345', 'psn_1234567890abcdef', 'libre_terminale'),
    ).rejects.toThrow('redis unavailable')
  })

  it('échoue fermé sans URL Redis', async () => {
    await expect(
      isRevoked('jti-12345', 'psn_1234567890abcdef', 'libre_terminale'),
    ).rejects.toThrow('Configuration session manquante: NEXUS_SESSION_REDIS_URL')
  })

  it('n’autorise la mémoire qu’en test avec un opt-in explicite', async () => {
    process.env.NEXUS_SESSION_STORE_MODE = 'memory'
    await expect(
      isRevoked('jti-12345', 'psn_1234567890abcdef', 'libre_terminale'),
    ).rejects.toThrow('Store mémoire de session interdit')

    process.env.NEXUS_SESSION_MEMORY_STORE_FOR_TESTS = 'true'
    resetSessionStoreForTests()
    await expect(
      isRevoked('jti-12345', 'psn_1234567890abcdef', 'libre_terminale'),
    ).resolves.toBe(false)
  })
})
