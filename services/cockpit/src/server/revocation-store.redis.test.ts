import { afterEach, describe, expect, it, vi } from 'vitest'

const redisState = vi.hoisted(() => new Map<string, string>())
const createClient = vi.hoisted(() => vi.fn(() => ({
  connect: vi.fn().mockResolvedValue(undefined),
  get: vi.fn(async (key: string) => redisState.get(key) ?? null),
  on: vi.fn(),
  set: vi.fn(async (
    key: string,
    value: string,
    options: { NX?: boolean },
  ) => {
    if (options.NX && redisState.has(key)) return null
    redisState.set(key, value)
    return 'OK'
  }),
})))

vi.mock('redis', () => ({ createClient }))

import {
  isRevoked,
  resetSessionStoreForTests,
  revokeSession,
} from '@/server/revocation-store'

describe('raccord Redis du store de session', () => {
  afterEach(() => {
    redisState.clear()
    createClient.mockClear()
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
    expect(createClient).toHaveBeenCalledTimes(2)
    expect(createClient).toHaveBeenNthCalledWith(1, expect.objectContaining({
      url: 'redis://session-store.test:6379/5',
    }))
  })
})
