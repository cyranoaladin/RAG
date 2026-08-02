import { afterEach, describe, expect, it, vi } from 'vitest'

const redisMock = vi.hoisted(() => {
  const state = new Map<string, string>()
  const connectAttempts: Array<Promise<void>> = []
  const createClient = vi.fn(() => ({
    connect: vi.fn(() => connectAttempts.shift() ?? Promise.resolve()),
    get: vi.fn(async (key: string) => state.get(key) ?? null),
    on: vi.fn(),
    set: vi.fn(async (
      key: string,
      value: string,
      options: { NX?: boolean },
    ) => {
      if (options.NX && state.has(key)) return null
      state.set(key, value)
      return 'OK'
    }),
  }))

  return { connectAttempts, createClient, state }
})

vi.mock('redis', () => ({ createClient: redisMock.createClient }))

import {
  isRevoked,
  resetSessionStoreForTests,
  revokeSession,
} from '@/server/revocation-store'

describe('raccord Redis du store de session', () => {
  afterEach(() => {
    redisMock.state.clear()
    redisMock.connectAttempts.length = 0
    redisMock.createClient.mockClear()
    delete process.env.NEXUS_SESSION_REDIS_URL
    resetSessionStoreForTests()
  })

  it('conserve la révocation après recréation logique du client Redis', async () => {
    process.env.NEXUS_SESSION_REDIS_URL = 'redis://session-store.test:6379/5'

    await revokeSession(
      'jti-12345',
      'psn_1234567890abcdef',
      'libre_terminale',
    )
    resetSessionStoreForTests()

    await expect(
      isRevoked('jti-12345', 'psn_1234567890abcdef', 'libre_terminale'),
    ).resolves.toBe(true)
    expect(redisMock.createClient).toHaveBeenCalledTimes(2)
    expect(redisMock.createClient).toHaveBeenNthCalledWith(1, expect.objectContaining({
      url: 'redis://session-store.test:6379/5',
    }))
  })

  it('partage un rejet de connexion puis réessaie avec un nouveau client', async () => {
    process.env.NEXUS_SESSION_REDIS_URL = 'redis://session-store.test:6379/5'
    const attemptA = deferred<void>()
    const attemptB = deferred<void>()
    redisMock.connectAttempts.push(attemptA.promise, attemptB.promise)

    const firstCall = isRevoked('jti-a', 'psn-a', 'libre_terminale')
    const concurrentCall = isRevoked('jti-b', 'psn-b', 'libre_terminale')
    const firstOutcomes = Promise.allSettled([firstCall, concurrentCall])
    const connectionError = new Error('Redis indisponible')

    attemptA.reject(connectionError)
    const rejected = await firstOutcomes

    expect(rejected).toEqual([
      { status: 'rejected', reason: connectionError },
      { status: 'rejected', reason: connectionError },
    ])
    expect(redisMock.createClient).toHaveBeenCalledTimes(1)

    const retry = isRevoked('jti-c', 'psn-c', 'libre_terminale')
    attemptB.resolve()

    await expect(retry).resolves.toBe(false)
    expect(redisMock.createClient).toHaveBeenCalledTimes(2)
  })

  it('ne laisse pas le rejet tardif d’une tentative réinitialisée effacer le nouveau store', async () => {
    process.env.NEXUS_SESSION_REDIS_URL = 'redis://session-store.test:6379/5'
    const attemptA = deferred<void>()
    const attemptB = deferred<void>()
    redisMock.connectAttempts.push(attemptA.promise, attemptB.promise)

    const staleCall = isRevoked('jti-a', 'psn-a', 'libre_terminale')
    const staleOutcome = Promise.allSettled([staleCall])
    resetSessionStoreForTests()

    const currentCall = isRevoked('jti-b', 'psn-b', 'libre_terminale')
    attemptB.resolve()
    await expect(currentCall).resolves.toBe(false)

    const staleError = new Error('ancienne connexion rejetée')
    attemptA.reject(staleError)
    await expect(staleOutcome).resolves.toEqual([
      { status: 'rejected', reason: staleError },
    ])

    await expect(
      isRevoked('jti-c', 'psn-c', 'libre_terminale'),
    ).resolves.toBe(false)
    expect(redisMock.createClient).toHaveBeenCalledTimes(2)
  })
})

function deferred<T>(): {
  promise: Promise<T>
  reject: (reason?: unknown) => void
  resolve: (value: T | PromiseLike<T>) => void
} {
  let reject!: (reason?: unknown) => void
  let resolve!: (value: T | PromiseLike<T>) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })

  return { promise, reject, resolve }
}
