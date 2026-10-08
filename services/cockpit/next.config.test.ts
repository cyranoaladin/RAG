import { beforeEach, describe, expect, it, vi } from 'vitest'

const { gitCall } = vi.hoisted(() => ({
  gitCall: vi.fn(() => '1'.repeat(40)),
}))

vi.mock('node:child_process', () => ({ execFileSync: gitCall }))

describe('provenance du build Cockpit', () => {
  beforeEach(() => {
    vi.resetModules()
    gitCall.mockClear()
    delete process.env.NEXUS_COCKPIT_BUILD_SHA
  })

  it('borne la résolution Git du SHA source', async () => {
    await import('./next.config')
    expect(gitCall).toHaveBeenCalledWith('git', ['rev-parse', 'HEAD'], expect.objectContaining({
      timeout: 5_000,
    }))
  })
})
