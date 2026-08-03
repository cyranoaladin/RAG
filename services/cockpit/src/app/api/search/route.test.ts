import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

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
const MATHS_COLLECTION = 'rag_nexus_maths_terminale_gen_specialite'
const NSI_COLLECTION = 'rag_nexus_nsi_terminale_specialite'
const authIdentity = {
  sub: 'psn_1234567890abcdef',
  niveau: 'terminale',
  school_year: '2026-2027',
  pedagogical_profile: {
    voie: 'generale',
    matieres: ['maths', 'nsi'],
    statut_enseignement: 'specialite',
    candidat: 'individuel',
    audience: 'libre',
  },
}
const authContext = {
  identityToken: 'signed-identity-token',
  allowedCollections: [MATHS_COLLECTION, NSI_COLLECTION],
  identity: authIdentity,
} as never

function engineResult(
  chunkId: string,
  scoreFinal: unknown,
  overrides: Record<string, unknown> = {},
) {
  const page = overrides.page === undefined ? null : overrides.page
  const metadataOverrides = { ...overrides }
  delete metadataOverrides.page
  return {
    chunk_id: chunkId,
    doc_id: `doc-${chunkId}`,
    title: `Source ${chunkId}`,
    excerpt: `Extrait ${chunkId}`,
    score: scoreFinal,
    citation: {
      source_label: `Source ${chunkId}`,
      source_uri: `https://example.test/${chunkId}`,
      rights: 'official_public_administrative',
      page,
    },
    metadata: {
      collection: MATHS_COLLECTION,
      type_doc: 'programme',
      review_status: 'reviewed',
      dense_score: 0.81,
      dense_sim: 0.81,
      lexical_score: 0.42,
      rrf_score: 0.016,
      rerank_score: 2.75,
      mmr_score: 0.61,
      score_final: scoreFinal,
      ...metadataOverrides,
    },
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

  afterEach(() => {
    vi.restoreAllMocks()
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

  it('refuse fail-closed une collection signée absente de l’artefact versionné', async () => {
    mockedRequireBffAuth.mockResolvedValue({
      identityToken: 'signed-identity-token',
      allowedCollections: ['collection-signee-mais-inconnue'],
      identity: authIdentity,
    } as never)

    const response = await POST(searchRequest(['collection-signee-mais-inconnue']))
    const body = await responseBody(response)

    expect(response.status).toBe(503)
    expect(body.error).toBe('service_unavailable')
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it('préserve bit à bit l’ordre MMR du moteur et publie score_final', async () => {
    mockedFetchEngine.mockResolvedValue({
      status: 200,
      payload: {
        results: [
          engineResult('premier-mmr', 0.2, { rerank_score: 9.5 }),
          engineResult('second-mmr', 0.9, { rerank_score: 1.91 }),
        ],
        warnings: [],
        filters_applied: { collection: MATHS_COLLECTION },
      },
    })

    const response = await POST(searchRequest([MATHS_COLLECTION]))
    const body = await responseBody(response)

    expect(response.status).toBe(200)
    expect(body.results?.map((hit) => hit.chunk_id)).toEqual([
      'premier-mmr',
      'second-mmr',
    ])
    expect(body.results?.map((hit) => hit.score)).toEqual([0.2, 0.9])
    expect(mockedIsPublicLaunchReady).toHaveBeenCalledWith(
      'signed-identity-token',
      expect.objectContaining({
        signal: expect.any(AbortSignal),
        timeoutMs: expect.any(Number),
      }),
    )
    expect(mockedFetchEngine).toHaveBeenCalledWith('/search/v2', expect.objectContaining({
      identityToken: 'signed-identity-token',
      body: expect.objectContaining({
        student_profile: expect.objectContaining({
          niveau: 'terminale',
          matieres: ['maths'],
          school_year: '2026-2027',
        }),
        need: {
          intent: 'context',
          query: 'Explique la récursivité',
        },
        retrieval: expect.objectContaining({ k: 8 }),
      }),
    }))
    const engineRequest = mockedFetchEngine.mock.calls[0]?.[1]?.body as Record<string, unknown>
    expect(engineRequest).not.toHaveProperty('q')
    expect(engineRequest).not.toHaveProperty('collection')
  })

  it('fusionne les collections par leurs têtes sans réordonner une séquence MMR', async () => {
    mockedFetchEngine
      .mockResolvedValueOnce({
        status: 200,
        payload: {
          results: [
            engineResult('a1', 0.8),
            engineResult('a2', 0.99),
            engineResult('a3', 0.4),
          ],
          warnings: [],
          filters_applied: { collection: MATHS_COLLECTION },
        },
      })
      .mockResolvedValueOnce({
        status: 200,
        payload: {
          results: [
            engineResult('b1', 0.8, { collection: NSI_COLLECTION }),
            engineResult('b2', 0.2, { collection: NSI_COLLECTION }),
            engineResult('b3', 0.95, { collection: NSI_COLLECTION }),
          ],
          warnings: [],
          filters_applied: { collection: NSI_COLLECTION },
        },
      })

    const response = await POST(searchRequest([MATHS_COLLECTION, NSI_COLLECTION], 6))
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

  it('sérialise les appels moteur d’une recherche multi-collections', async () => {
    let activeCalls = 0
    let maximumActiveCalls = 0
    let releaseFirstCall: (() => void) | undefined
    const firstCallBlocked = new Promise<void>((resolve) => {
      releaseFirstCall = resolve
    })
    mockedFetchEngine.mockImplementation(async () => {
      const callIndex = mockedFetchEngine.mock.calls.length
      activeCalls += 1
      maximumActiveCalls = Math.max(maximumActiveCalls, activeCalls)
      if (callIndex === 1) {
        await firstCallBlocked
      }
      activeCalls -= 1
      return {
        status: 200,
        payload: {
          results: [],
          warnings: [],
          filters_applied: {},
        },
      }
    })

    const responsePromise = POST(searchRequest([MATHS_COLLECTION, NSI_COLLECTION]))
    await vi.waitFor(() => expect(mockedFetchEngine).toHaveBeenCalledTimes(1))
    expect(maximumActiveCalls).toBe(1)
    releaseFirstCall?.()

    const response = await responsePromise

    expect(response.status).toBe(200)
    expect(mockedFetchEngine).toHaveBeenCalledTimes(2)
    expect(maximumActiveCalls).toBe(1)
  })

  it('n’entame pas une nouvelle collection lorsque le budget BFF global est épuisé', async () => {
    let nowMs = 1_000
    vi.spyOn(Date, 'now').mockImplementation(() => nowMs)
    mockedFetchEngine.mockImplementation(async () => {
      nowMs += 8_000
      return {
        status: 200,
        payload: {
          results: [],
          warnings: [],
          filters_applied: {},
        },
      }
    })

    const response = await POST(searchRequest([MATHS_COLLECTION, NSI_COLLECTION]))
    const body = await responseBody(response)

    expect(response.status).toBe(503)
    expect(body.error).toBe('service_unavailable')
    expect(mockedFetchEngine).toHaveBeenCalledTimes(1)
  })

  it('propage les avertissements du contrat moteur sans les réinterpréter', async () => {
    mockedFetchEngine.mockResolvedValue({
      status: 200,
      payload: {
        results: [engineResult('warning', 0.7)],
        warnings: ['retrieval_notice'],
        filters_applied: { collection: MATHS_COLLECTION },
      },
    })

    const response = await POST(searchRequest([MATHS_COLLECTION]))
    const body = await response.json() as { warnings?: string[] }

    expect(response.status).toBe(200)
    expect(body.warnings).toEqual(['retrieval_notice'])
  })

  it('propage page et tous les diagnostics avec des nombres finis ou null', async () => {
    mockedFetchEngine.mockResolvedValue({
      status: 200,
      payload: {
        results: [
          engineResult('page-positive', 0.72, { page: 12 }),
          engineResult('page-null', 0.63, {
            page: null,
            dense_score: Number.NaN,
            dense_sim: Number.POSITIVE_INFINITY,
            lexical_score: null,
          }),
        ],
        warnings: [],
        filters_applied: { collection: MATHS_COLLECTION },
      },
    })

    const response = await POST(searchRequest([MATHS_COLLECTION]))
    const body = await responseBody(response)

    expect(response.status).toBe(200)
    expect(body.results?.[0]?.citation).toMatchObject({ page: 12 })
    expect(body.results?.[1]?.citation).toMatchObject({ page: null })
    expect(body.results?.[0]?.metadata).toEqual({
      collection: MATHS_COLLECTION,
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
    ['négatif', -0.01],
  ])('rejette un score contractuel %s', async (_label, scoreFinal) => {
    mockedFetchEngine.mockResolvedValue({
      status: 200,
      payload: {
        results: [engineResult('invalide', scoreFinal)],
        warnings: [],
        filters_applied: { collection: MATHS_COLLECTION },
      },
    })

    const response = await POST(searchRequest([MATHS_COLLECTION]))
    const body = await responseBody(response)

    expect(response.status).toBe(502)
    expect(body.error).toBe('invalid_upstream_response')
  })
})
