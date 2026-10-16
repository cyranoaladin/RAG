import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchEngine } from '../_engine'
import { GET } from './route'

vi.mock('../_engine', () => ({ fetchEngine: vi.fn() }))
vi.mock('@/server/public-scope', () => ({
  configuredPublicScopes: vi.fn(() => [{}]),
  publicScopeIndexDigest: vi.fn(() => 'a'.repeat(64)),
}))

const mockedFetchEngine = vi.mocked(fetchEngine)

describe('identité du build dans la readiness publique', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    process.env.NEXUS_COCKPIT_SCOPE_MODE = 'public_v3'
    process.env.NEXUS_COCKPIT_PUBLIC_SCOPE_INDEX_SHA256 = 'a'.repeat(64)
    mockedFetchEngine.mockResolvedValue({ status: 200, payload: { status: 'healthy' } })
  })

  afterEach(() => {
    delete process.env.NEXUS_COCKPIT_SCOPE_MODE
    delete process.env.NEXUS_COCKPIT_PUBLIC_SCOPE_INDEX_SHA256
    delete process.env.NEXUS_COCKPIT_BUILD_SHA
  })

  it('refuse une réponse verte si le SHA du build est absent', async () => {
    const response = await GET()
    expect(response.status).toBe(503)
    expect(await response.json()).toEqual({ status: 'unavailable' })
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it('refuse une réponse verte si le SHA du build est invalide', async () => {
    process.env.NEXUS_COCKPIT_BUILD_SHA = 'not-a-sha'
    const response = await GET()
    expect(response.status).toBe(503)
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it('expose le SHA exact quand le build public est identifié', async () => {
    process.env.NEXUS_COCKPIT_BUILD_SHA = 'b'.repeat(40)
    const response = await GET()
    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({
      status: 'ok',
      build_sha: 'b'.repeat(40),
      public_scope_index_sha256: 'a'.repeat(64),
    })
  })
})
