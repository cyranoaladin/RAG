import { afterEach, describe, expect, it } from 'vitest'

import {
  MemorySessionBackend,
  SharedSessionSecurityStore,
  isRevoked,
  resetSessionStoreForTests,
} from '@/server/revocation-store'

describe('store partagé de sécurité de session', () => {
  afterEach(() => {
    delete process.env.NEXUS_SESSION_REDIS_URL
    delete process.env.NEXUS_SESSION_STORE_MODE
    delete process.env.NEXUS_SESSION_MEMORY_STORE_FOR_TESTS
    resetSessionStoreForTests()
  })

  it('partage la révocation entre instances et après recréation logique', async () => {
    const backend = new MemorySessionBackend()
    const instanceA = new SharedSessionSecurityStore(backend)
    const instanceB = new SharedSessionSecurityStore(backend)

    await instanceA.revokeSession('psn_1234567890abcdef', 'libre_terminale')

    await expect(
      instanceB.isRevoked('psn_1234567890abcdef', 'libre_terminale'),
    ).resolves.toBe(true)
    const restartedInstance = new SharedSessionSecurityStore(backend)
    await expect(
      restartedInstance.isRevoked('psn_1234567890abcdef', 'libre_terminale'),
    ).resolves.toBe(true)
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
      store.isRevoked('psn_1234567890abcdef', 'libre_terminale'),
    ).rejects.toThrow('redis unavailable')
  })

  it('échoue fermé sans URL Redis', async () => {
    await expect(
      isRevoked('psn_1234567890abcdef', 'libre_terminale'),
    ).rejects.toThrow('Configuration session manquante: NEXUS_SESSION_REDIS_URL')
  })

  it('n’autorise la mémoire qu’en test avec un opt-in explicite', async () => {
    process.env.NEXUS_SESSION_STORE_MODE = 'memory'
    await expect(
      isRevoked('psn_1234567890abcdef', 'libre_terminale'),
    ).rejects.toThrow('Store mémoire de session interdit')

    process.env.NEXUS_SESSION_MEMORY_STORE_FOR_TESTS = 'true'
    resetSessionStoreForTests()
    await expect(
      isRevoked('psn_1234567890abcdef', 'libre_terminale'),
    ).resolves.toBe(false)
  })
})
