import { readFile } from 'node:fs/promises'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchEngine } from '../_engine'
import { GET } from './route'

vi.mock('../_engine', () => ({ fetchEngine: vi.fn() }))
vi.mock('node:fs/promises', () => ({ readFile: vi.fn() }))

const mockedFetchEngine = vi.mocked(fetchEngine)
const mockedReadFile = vi.mocked(readFile)

describe('GET /api/health', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedReadFile.mockResolvedValue('a'.repeat(40))
  })

  it('sonde la route health du runtime v2 sans ressusciter admin legacy', async () => {
    mockedFetchEngine.mockResolvedValue({ status: 200, payload: { status: 'healthy' } })

    const response = await GET()

    expect(mockedFetchEngine).toHaveBeenCalledWith('/health')
    expect(response.status).toBe(200)
    await expect(response.json()).resolves.toEqual({ status: 'ok', build_sha: 'a'.repeat(40) })
  })

  it('masque les détails moteur quand la readiness échoue', async () => {
    mockedFetchEngine.mockResolvedValue({
      status: 503,
      payload: { detail: 'private database error' },
    })

    const response = await GET()

    expect(response.status).toBe(503)
    await expect(response.json()).resolves.toEqual({ status: 'unavailable', build_sha: 'a'.repeat(40) })
  })
})
