import { afterEach, describe, expect, it, vi } from 'vitest'

import { fetchEngine, isPublicLaunchReady } from './_engine'

describe('public launch readiness', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    delete process.env.RAG_ENGINE_INTERNAL_TOKEN
  })

  it('fails closed when the engine does not prove all collections ready', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ launch_ready: false })))

    await expect(isPublicLaunchReady()).resolves.toBe(false)
  })

  it('sépare le jeton service du header d’identité signé', async () => {
    process.env.RAG_ENGINE_INTERNAL_TOKEN = 'service-token'
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ hits: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchEngine('/search/v2', {
      method: 'POST',
      body: { q: 'test', collection: 'collection', k: 3 },
      identityToken: 'signed-identity-token',
    })

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    const headers = init.headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer service-token')
    expect(headers.get('X-Nexus-Identity')).toBe('signed-identity-token')
  })

  it('refuse tout appel moteur sans jeton service BFF', async () => {
    vi.stubGlobal('fetch', vi.fn())

    await expect(fetchEngine('/search/v2')).rejects.toThrow(
      'Configuration moteur manquante: RAG_ENGINE_INTERNAL_TOKEN',
    )
    expect(fetch).not.toHaveBeenCalled()
  })
})
