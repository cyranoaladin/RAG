import { afterEach, describe, expect, it, vi } from 'vitest'

const INTERNAL_SENTINEL = 'https://rag-engine.internal'
const TOKEN_SENTINEL = 'CLIENT_TOKEN_SENTINEL_MUST_NOT_LEAK'

async function loadSearch(mode: 'development' | 'production') {
  vi.stubEnv('MODE', mode)
  vi.stubEnv('VITE_RAG_API_BASE', INTERNAL_SENTINEL)
  vi.stubEnv('VITE_RAG_PROFILE_TOKEN', TOKEN_SENTINEL)
  return (await import('./api')).search
}

describe('search', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    vi.resetModules()
  })

  it('échoue explicitement quand l’API production est indisponible', async () => {
    vi.stubEnv('MODE', 'production')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))
    const { search } = await import('./api')

    await expect(search('graphes', 'terminale', 'eleve')).rejects.toThrow(
      'RAG_API_UNAVAILABLE',
    )
  })

  it.each([
    {
      mode: 'production' as const,
      expectedDemo: false,
      label: 'production',
    },
    {
      mode: 'development' as const,
      expectedDemo: true,
      label: 'développement',
    },
  ])(
    'traite une requête vide sans fallback de résultats ($label)',
    async ({ mode, expectedDemo }) => {
      vi.stubEnv('MODE', mode)
      const fetchMock = vi.fn()
      vi.stubGlobal('fetch', fetchMock)
      const { search } = await import('./api')

      const result = await search('   ', 'terminale', 'eleve')

      expect(result).toEqual({ items: [], demo: expectedDemo })
      expect(fetchMock).not.toHaveBeenCalled()
    },
  )

  it('normalise un rejet réseau en production', async () => {
    const failure = new TypeError('BFF same-origin indisponible')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(failure))
    const search = await loadSearch('production')

    await expect(search('graphes', 'terminale', 'eleve')).rejects.toThrow(
      /^RAG_API_UNAVAILABLE$/,
    )
  })

  it('transmet un signal d’expiration de huit secondes à fetch', async () => {
    const timeoutSignal = new AbortController().signal
    const timeoutSpy = vi
      .spyOn(AbortSignal, 'timeout')
      .mockReturnValue(timeoutSignal)
    const fetchMock = vi
      .fn()
      .mockRejectedValue(new DOMException('upstream timeout', 'AbortError'))
    vi.stubGlobal('fetch', fetchMock)
    const search = await loadSearch('production')

    await expect(search('graphes', 'terminale', 'eleve')).rejects.toThrow(
      /^RAG_API_UNAVAILABLE$/,
    )
    expect(timeoutSpy).toHaveBeenCalledWith(8000)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/search',
      expect.objectContaining({
        signal: timeoutSignal,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
  })

  it('ignore les anciennes variables et appelle seulement le BFF same-origin', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      Response.json({ results: [], warnings: [], filters_applied: {} }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const search = await loadSearch('production')

    await expect(
      search('graphes', 'terminale', 'eleve'),
    ).resolves.toEqual({ items: [], demo: false })

    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/search')
    expect(url).not.toContain(INTERNAL_SENTINEL)
    expect(init.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(init.headers).not.toHaveProperty('Authorization')
    expect(JSON.stringify(init)).not.toContain(TOKEN_SENTINEL)
  })

  it('sonde la santé uniquement par le BFF same-origin', async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ status: 'ok' }))
    vi.stubGlobal('fetch', fetchMock)
    vi.stubEnv('VITE_RAG_API_BASE', INTERNAL_SENTINEL)
    vi.stubEnv('VITE_RAG_PROFILE_TOKEN', TOKEN_SENTINEL)
    const { getApiHealth } = await import('./api')

    await expect(getApiHealth()).resolves.toBe(true)

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/health',
      expect.objectContaining({
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(init.headers).not.toHaveProperty('Authorization')
  })

  it('normalise une réponse HTTP non-2xx en production', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('upstream stack trace', {
          status: 503,
          statusText: 'Service Unavailable',
        }),
      ),
    )
    const search = await loadSearch('production')

    await expect(search('graphes', 'terminale', 'eleve')).rejects.toThrow(
      /^RAG_API_UNAVAILABLE$/,
    )
  })

  it('normalise une réponse JSON invalide en production', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response('{invalid', {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    const search = await loadSearch('production')

    await expect(search('graphes', 'terminale', 'eleve')).rejects.toThrow(
      /^RAG_API_UNAVAILABLE$/,
    )
  })

  it('conserve le fallback de démonstration en développement', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(new TypeError('development API unavailable')),
    )
    const search = await loadSearch('development')

    const result = await search('graphes', 'terminale', 'eleve')

    expect(result.demo).toBe(true)
    expect(result.items).toHaveLength(3)
  })
})
