import { afterEach, describe, expect, it, vi } from 'vitest'

const API_BASE = 'https://rag.example.test'

async function loadSearch(mode: 'development' | 'production') {
  vi.stubEnv('MODE', mode)
  vi.stubEnv('VITE_RAG_API_BASE', API_BASE)
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
    vi.stubEnv('VITE_RAG_API_BASE', '')
    const { search } = await import('./api')

    await expect(search('graphes', 'terminale', 'eleve')).rejects.toThrow(
      'RAG_API_UNAVAILABLE',
    )
  })

  it('normalise un rejet réseau en production', async () => {
    const failure = new TypeError(
      'fetch failed for https://rag.internal.example/search',
    )
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
      `${API_BASE}/search`,
      expect.objectContaining({ signal: timeoutSignal }),
    )
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
