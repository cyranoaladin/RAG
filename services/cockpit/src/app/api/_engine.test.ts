import { afterEach, describe, expect, it, vi } from 'vitest'

import { isPublicLaunchReady } from './_engine'

describe('public launch readiness', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('fails closed when the engine does not prove all collections ready', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ launch_ready: false })))

    await expect(isPublicLaunchReady()).resolves.toBe(false)
  })
})
