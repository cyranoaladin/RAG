import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchEngine } from '../_engine'
import { GET } from './route'

vi.mock('../_engine', () => ({ fetchEngine: vi.fn() }))

const mockedFetchEngine = vi.mocked(fetchEngine)

describe('GET /api/health', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    delete process.env.NEXUS_COCKPIT_BUILD_SHA
    delete process.env.NEXUS_COCKPIT_SCOPE_MODE
    delete process.env.NEXUS_COCKPIT_PUBLIC_SCOPE_INDEX_SHA256
  })

  it('sonde la route health du runtime v2 sans ressusciter admin legacy', async () => {
    mockedFetchEngine.mockResolvedValue({ status: 200, payload: { status: 'healthy' } })

    const response = await GET()

    expect(mockedFetchEngine).toHaveBeenCalledWith('/health')
    expect(response.status).toBe(200)
    await expect(response.json()).resolves.toEqual({ status: 'ok' })
  })

  it('masque les détails moteur quand la readiness échoue', async () => {
    mockedFetchEngine.mockResolvedValue({
      status: 503,
      payload: { detail: 'private database error' },
    })

    const response = await GET()

    expect(response.status).toBe(503)
    await expect(response.json()).resolves.toEqual({ status: 'unavailable' })
  })

  it('expose le SHA exact du build et refuse un index public non émis', async () => {
    process.env.NEXUS_COCKPIT_BUILD_SHA = 'a'.repeat(40)
    mockedFetchEngine.mockResolvedValue({ status: 200, payload: { status: 'healthy' } })
    const pilot = await GET()
    expect(await pilot.json()).toMatchObject({ status: 'ok', build_sha: 'a'.repeat(40) })

    process.env.NEXUS_COCKPIT_SCOPE_MODE = 'public_v3'
    process.env.NEXUS_COCKPIT_PUBLIC_SCOPE_INDEX_SHA256 = 'b'.repeat(64)
    const publicResponse = await GET()
    expect(publicResponse.status).toBe(503)
    expect(await publicResponse.json()).toMatchObject({ status: 'unavailable' })
  })
})
