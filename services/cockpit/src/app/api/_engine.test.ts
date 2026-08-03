import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  fetchEngine,
  isPublicLaunchReady,
  resolveEngineTimeoutMs,
  type EngineReviewQueueQuery,
} from './_engine'

function assertEngineTypes(): void {
  // @ts-expect-error Les endpoints moteur restent une allowlist fermée.
  void fetchEngine('/proxy/non-autorise')
  // @ts-expect-error Seule la queue de review accepte des query params.
  void fetchEngine('/review/v2/decide', { query: { limit: 25 } })

  // @ts-expect-error Le tenant provient exclusivement de l'identité BFF.
  const queryWithTenant: EngineReviewQueueQuery = { tenant: 'libre_terminale' }
  // @ts-expect-error Une raison libre ne fait pas partie du contrat de queue.
  const queryWithReason: EngineReviewQueueQuery = { reason: 'contournement' }
  void queryWithTenant
  void queryWithReason
}
void assertEngineTypes

describe('public launch readiness', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    delete process.env.RAG_ENGINE_INTERNAL_TOKEN
    delete process.env.RAG_ENGINE_INTERNAL_URL
  })

  it('fails closed when the engine does not prove all collections ready', async () => {
    process.env.RAG_ENGINE_INTERNAL_TOKEN = 'service-token'
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json({ launch_ready: false })))

    await expect(isPublicLaunchReady('signed-identity-token')).resolves.toBe(false)

    const init = vi.mocked(fetch).mock.calls[0]?.[1] as RequestInit
    const headers = init.headers as Headers
    expect(headers.get('Authorization')).toBe('Bearer service-token')
    expect(headers.get('X-Nexus-Identity')).toBe('signed-identity-token')
  })

  it('conserve un délai BFF supérieur au budget PostgreSQL maximal', () => {
    expect(resolveEngineTimeoutMs(undefined)).toBe(8000)
    expect(resolveEngineTimeoutMs('7999')).toBe(8000)
    expect(resolveEngineTimeoutMs('invalid')).toBe(8000)
    expect(resolveEngineTimeoutMs('12000')).toBe(12000)
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

  it('borne un appel moteur par le reliquat partagé et le signal appelant', async () => {
    process.env.RAG_ENGINE_INTERNAL_TOKEN = 'service-token'
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ hits: [] }))
    vi.stubGlobal('fetch', fetchMock)
    const caller = new AbortController()
    const timeoutSpy = vi.spyOn(AbortSignal, 'timeout')

    await fetchEngine('/search/v2', {
      method: 'POST',
      body: { q: 'test' },
      signal: caller.signal,
      timeoutMs: 1_200,
    })

    expect(timeoutSpy).toHaveBeenCalledWith(1_200)
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    const combinedSignal = init.signal as AbortSignal
    expect(combinedSignal.aborted).toBe(false)
    caller.abort()
    expect(combinedSignal.aborted).toBe(true)
  })

  it('refuse tout appel moteur sans jeton service BFF', async () => {
    vi.stubGlobal('fetch', vi.fn())

    await expect(fetchEngine('/search/v2')).rejects.toThrow(
      'Configuration moteur manquante: RAG_ENGINE_INTERNAL_TOKEN',
    )
    expect(fetch).not.toHaveBeenCalled()
  })

  it('encode les seuls filtres autorisés dans l’URL de la queue de review', async () => {
    process.env.RAG_ENGINE_INTERNAL_URL = 'http://engine.internal:8001/'
    process.env.RAG_ENGINE_INTERNAL_TOKEN = 'service-token'
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ documents: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchEngine('/review/v2/queue', {
      method: 'GET',
      identityToken: 'signed-identity-token',
      query: {
        collection: 'algèbre / Terminale',
        limit: 25,
        offset: 50,
      },
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      'http://engine.internal:8001/review/v2/queue?collection=alg%C3%A8bre+%2F+Terminale&limit=25&offset=50',
    )
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    const headers = init.headers as Headers
    expect(init.method).toBe('GET')
    expect(init.body).toBeUndefined()
    expect(headers.get('Authorization')).toBe('Bearer service-token')
    expect(headers.get('X-Nexus-Identity')).toBe('signed-identity-token')
  })

  it('préserve le préfixe de chemin configuré devant la queue de review', async () => {
    process.env.RAG_ENGINE_INTERNAL_URL = 'https://gateway.internal/rag-engine/'
    process.env.RAG_ENGINE_INTERNAL_TOKEN = 'service-token'
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ documents: [] }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchEngine('/review/v2/queue', { query: { limit: 25 } })

    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      'https://gateway.internal/rag-engine/review/v2/queue?limit=25',
    )
  })

  it('transmet une décision de review sans mélanger corps et jetons', async () => {
    process.env.RAG_ENGINE_INTERNAL_URL = 'http://engine.internal:8001/'
    process.env.RAG_ENGINE_INTERNAL_TOKEN = 'service-token'
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ document_id: 'doc-42' }))
    vi.stubGlobal('fetch', fetchMock)
    const body = {
      document_id: 'doc-42',
      decision: 'approve',
      tenant: 'libre_terminale',
    }

    await fetchEngine('/review/v2/decide', {
      method: 'POST',
      body,
      identityToken: 'signed-identity-token',
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0]?.[0]).toBe('http://engine.internal:8001/review/v2/decide')
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    const headers = init.headers as Headers
    expect(init.method).toBe('POST')
    expect(init.body).toBe(JSON.stringify(body))
    expect(String(init.body)).not.toContain('service-token')
    expect(String(init.body)).not.toContain('signed-identity-token')
    expect(headers.get('Authorization')).toBe('Bearer service-token')
    expect(headers.get('X-Nexus-Identity')).toBe('signed-identity-token')
  })
})
