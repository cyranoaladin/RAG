import { afterEach, describe, expect, it, vi } from 'vitest'

describe('search', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
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
})
