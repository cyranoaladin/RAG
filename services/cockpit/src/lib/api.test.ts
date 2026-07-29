import { afterEach, describe, expect, it, vi } from 'vitest'

const API_BASE = 'https://rag.example.test'

async function loadSearch(mode: 'development' | 'production') {
  vi.stubEnv('MODE', mode)
  vi.stubEnv('VITE_RAG_API_BASE', API_BASE)
  return (await import('./api')).search
}

describe('search', () => {
  afterEach(() => {
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

  it.each([
    [
      'un rejet réseau',
      new TypeError('fetch failed for https://rag.internal.example/search'),
    ],
    [
      'une interruption ou expiration',
      new DOMException('upstream timeout: secret', 'AbortError'),
    ],
  ])('normalise %s en production', async (_label, failure) => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(failure))
    const search = await loadSearch('production')

    await expect(search('graphes', 'terminale', 'eleve')).rejects.toThrow(
      /^RAG_API_UNAVAILABLE$/,
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
