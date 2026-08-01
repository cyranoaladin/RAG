import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchEngine, isPublicLaunchReady } from '../_engine'
import { POST } from './route'
import { requireBffAuth } from '@/server/bff-auth'

vi.mock('../_engine', () => ({
  fetchEngine: vi.fn(),
  isPublicLaunchReady: vi.fn(),
}))
vi.mock('@/server/bff-auth', () => ({
  requireBffAuth: vi.fn(),
}))

const mockedFetchEngine = vi.mocked(fetchEngine)
const mockedIsPublicLaunchReady = vi.mocked(isPublicLaunchReady)
const mockedRequireBffAuth = vi.mocked(requireBffAuth)
const authContext = {
  identityToken: 'signed-identity-token',
  allowedCollections: ['collection-a', 'collection-b'],
  identity: {
    sub: 'psn_1234567890abcdef',
  },
} as never

function engineHit(
  chunkId: string,
  scoreFinal: unknown,
  overrides: Record<string, unknown> = {},
) {
  return {
    chunk_id: chunkId,
    doc_id: `doc-${chunkId}`,
    source_label: `Source ${chunkId}`,
    source_uri: `https://example.test/${chunkId}`,
    rights: 'official_public_administrative',
    type_doc: 'programme',
    review_status: 'reviewed',
    page: null,
    preview: `Extrait ${chunkId}`,
    dense_score: 0.81,
    dense_sim: 0.81,
    lexical_score: 0.42,
    rrf_score: 0.016,
    rerank_score: 2.75,
    mmr_score: 0.61,
    score_final: scoreFinal,
    ...overrides,
  }
}

function searchRequest(collections: string[], k = 8) {
  return new Request('http://cockpit.test/api/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: 'Explique la récursivité', collections, k }),
  })
}

async function responseBody(response: Response) {
  return await response.json() as {
    results?: Array<Record<string, unknown>>
    error?: string
  }
}

describe('POST /api/search', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedIsPublicLaunchReady.mockResolvedValue(true)
    mockedRequireBffAuth.mockResolvedValue(authContext)
  })

  it('répond 401 avant tout appel moteur lorsque la session manque', async () => {
    mockedRequireBffAuth.mockResolvedValue(null)

    const response = await POST(searchRequest(['collection-a']))

    expect(response.status).toBe(401)
    expect(mockedIsPublicLaunchReady).not.toHaveBeenCalled()
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it('refuse une collection hors scope avant tout appel moteur', async () => {
    const response = await POST(searchRequest(['collection-arbitraire']))

    expect(response.status).toBe(403)
    expect(mockedIsPublicLaunchReady).not.toHaveBeenCalled()
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it('préserve bit à bit l’ordre MMR du moteur et publie score_final', async () => {
    mockedFetchEngine.mockResolvedValue({
      status: 200,
      payload: {
        hits: [
          engineHit('premier-mmr', 0.2, { rerank_score: 9.5 }),
          engineHit('second-mmr', 0.9, { rerank_score: 1.91 }),
        ],
      },
    })

    const response = await POST(searchRequest(['collection-a']))
    const body = await responseBody(response)

    expect(response.status).toBe(200)
    expect(body.results?.map((hit) => hit.chunk_id)).toEqual([
      'premier-mmr',
      'second-mmr',
    ])
    expect(body.results?.map((hit) => hit.score)).toEqual([0.2, 0.9])
    expect(mockedIsPublicLaunchReady).toHaveBeenCalledWith('signed-identity-token')
    expect(mockedFetchEngine).toHaveBeenCalledWith('/search/v2', expect.objectContaining({
      identityToken: 'signed-identity-token',
    }))
  })

  it('fusionne les collections par leurs têtes sans réordonner une séquence MMR', async () => {
    mockedFetchEngine
      .mockResolvedValueOnce({
        status: 200,
        payload: {
          hits: [
            engineHit('a1', 0.8),
            engineHit('a2', 0.99),
            engineHit('a3', 0.4),
          ],
        },
      })
      .mockResolvedValueOnce({
        status: 200,
        payload: {
          hits: [
            engineHit('b1', 0.8),
            engineHit('b2', 0.2),
            engineHit('b3', 0.95),
          ],
        },
      })

    const response = await POST(searchRequest(['collection-a', 'collection-b'], 6))
    const body = await responseBody(response)

    expect(response.status).toBe(200)
    expect(body.results?.map((hit) => hit.chunk_id)).toEqual([
      'a1',
      'a2',
      'b1',
      'a3',
      'b2',
      'b3',
    ])
  })

  it('propage page et tous les diagnostics avec des nombres finis ou null', async () => {
    mockedFetchEngine.mockResolvedValue({
      status: 200,
      payload: {
        hits: [
          engineHit('page-positive', 0.72, { page: 12 }),
          engineHit('page-null', 0.63, {
            page: null,
            dense_score: Number.NaN,
            dense_sim: Number.POSITIVE_INFINITY,
            lexical_score: null,
          }),
        ],
      },
    })

    const response = await POST(searchRequest(['collection-a']))
    const body = await responseBody(response)

    expect(response.status).toBe(200)
    expect(body.results?.[0]?.citation).toMatchObject({ page: 12 })
    expect(body.results?.[1]?.citation).toMatchObject({ page: null })
    expect(body.results?.[0]?.metadata).toEqual({
      collection: 'collection-a',
      type_doc: 'programme',
      review_status: 'reviewed',
      dense_score: 0.81,
      dense_sim: 0.81,
      lexical_score: 0.42,
      rrf_score: 0.016,
      rerank_score: 2.75,
      mmr_score: 0.61,
      score_final: 0.72,
    })
    expect(body.results?.[1]?.metadata).toMatchObject({
      dense_score: null,
      dense_sim: null,
      lexical_score: null,
      score_final: 0.63,
    })
  })

  it.each([
    ['absent', undefined],
    ['NaN', Number.NaN],
    ['infini', Number.POSITIVE_INFINITY],
    ['négatif', -0.01],
    ['supérieur à un', 1.01],
  ])('rejette un score_final %s', async (_label, scoreFinal) => {
    mockedFetchEngine.mockResolvedValue({
      status: 200,
      payload: { hits: [engineHit('invalide', scoreFinal)] },
    })

    const response = await POST(searchRequest(['collection-a']))
    const body = await responseBody(response)

    expect(response.status).toBe(200)
    expect(body.results).toEqual([])
  })
})
