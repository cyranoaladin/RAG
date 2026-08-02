import { beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchEngine } from '../../_engine'
import { GET } from './route'
import { requireBffAuth } from '@/server/bff-auth'

vi.mock('../../_engine', () => ({ fetchEngine: vi.fn() }))
vi.mock('@/server/bff-auth', () => ({ requireBffAuth: vi.fn() }))

const mockedFetchEngine = vi.mocked(fetchEngine)
const mockedRequireBffAuth = vi.mocked(requireBffAuth)

const validQueue = {
  total_pending_docs: 1,
  returned: 1,
  offset: 0,
  documents: [
    {
      doc_id: 'doc-1',
      collection: 'rag_nexus_nsi_terminale_specialite',
      source_label: 'Programme de NSI',
      source_uri: 'https://example.invalid/programme.pdf',
      rights: 'officiel_public',
      source_kind: 'pdf',
      type_doc: 'programme_officiel',
      chunk_count: 3,
      first_indexed: null,
      last_indexed: null,
    },
  ],
}

function authContext(role: 'admin' | 'reviewer' | 'student' | 'teacher' | 'ingest_agent') {
  return {
    identityToken: 'signed-identity-token',
    allowedCollections: ['rag_nexus_nsi_terminale_specialite'],
    identity: {
      role,
      tenant: 'libre_terminale',
    },
  } as never
}

function queueRequest(search = ''): Request {
  return new Request(`http://cockpit.test/api/review/queue${search}`)
}

async function expectJson(response: Response, status: number, body: unknown): Promise<void> {
  expect(response.status).toBe(status)
  expect(response.headers.get('Cache-Control')).toBe('private, no-store, max-age=0')
  await expect(response.json()).resolves.toEqual(body)
}

describe('GET /api/review/queue', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedRequireBffAuth.mockResolvedValue(authContext('reviewer'))
    mockedFetchEngine.mockResolvedValue({ status: 200, payload: validQueue })
  })

  it('répond 401 avant tout appel moteur lorsque la session manque', async () => {
    mockedRequireBffAuth.mockResolvedValue(null)

    const response = await GET(queueRequest())

    await expectJson(response, 401, { error: 'unauthorized' })
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it.each(['student', 'teacher', 'ingest_agent'] as const)(
    'répond 403 au rôle humain non reviewer ou au rôle technique %s',
    async (role) => {
      mockedRequireBffAuth.mockResolvedValue(authContext(role))

      const response = await GET(queueRequest())

      await expectJson(response, 403, { error: 'forbidden' })
      expect(mockedFetchEngine).not.toHaveBeenCalled()
    },
  )

  it.each(['admin', 'reviewer'] as const)(
    'autorise le rôle de review %s et transmet seulement les paramètres fermés',
    async (role) => {
      mockedRequireBffAuth.mockResolvedValue(authContext(role))

      const response = await GET(queueRequest(
        '?collection=rag_nexus_nsi_terminale_specialite&limit=25&offset=50',
      ))

      await expectJson(response, 200, validQueue)
      expect(mockedFetchEngine).toHaveBeenCalledOnce()
      expect(mockedFetchEngine).toHaveBeenCalledWith('/review/v2/queue', {
        method: 'GET',
        identityToken: 'signed-identity-token',
        query: {
          collection: 'rag_nexus_nsi_terminale_specialite',
          limit: 25,
          offset: 50,
        },
      })
    },
  )

  it.each(['tenant', 'reason', 'arbitrary'])(
    'rejette la clé navigateur inconnue %s avant le moteur',
    async (key) => {
      const response = await GET(queueRequest(`?${key}=secret`))

      await expectJson(response, 400, { error: 'invalid_request' })
      expect(mockedFetchEngine).not.toHaveBeenCalled()
    },
  )

  it.each([
    '?collection=rag_nexus_nsi_terminale_specialite&collection=autre_collection',
    '?limit=25&limit=50',
    '?offset=0&offset=1',
  ])('rejette un paramètre dupliqué avant le moteur : %s', async (search) => {
    const response = await GET(queueRequest(search))

    await expectJson(response, 400, { error: 'invalid_request' })
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it.each([
    '?limit=0',
    '?limit=501',
    '?limit=1.0',
    '?limit=01',
    '?limit=1e2',
    '?limit=abc',
    '?offset=-1',
    '?offset=+1',
    '?offset=1.0',
    '?offset=9007199254740992',
    '?collection=',
    '?collection=NSI-Terminale',
  ])('rejette une borne ou une valeur non canonique avant le moteur : %s', async (search) => {
    const response = await GET(queueRequest(search))

    await expectJson(response, 400, { error: 'invalid_request' })
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it('rejette une collection hors scope avant tout appel moteur', async () => {
    const response = await GET(queueRequest('?collection=collection_hors_scope'))

    await expectJson(response, 403, { error: 'forbidden' })
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it.each([
    null,
    { ...validQueue, returned: 0 },
    { ...validQueue, credential: 'service-token' },
  ])('échoue fermé quand le moteur renvoie un payload 200 invalide', async (payload) => {
    mockedFetchEngine.mockResolvedValue({ status: 200, payload })

    const response = await GET(queueRequest())

    await expectJson(response, 503, { error: 'review_unavailable' })
  })

  it.each([403, 404, 422, 500, 503])(
    'convertit le statut moteur %i en indisponibilité générique sans fuite',
    async (status) => {
      mockedFetchEngine.mockResolvedValue({
        status,
        payload: {
          detail: 'Bearer service-token signed-identity-token tenant=libre_terminale',
        },
      })

      const response = await GET(queueRequest())
      const text = await response.text()

      expect(response.status).toBe(503)
      expect(response.headers.get('Cache-Control')).toBe('private, no-store, max-age=0')
      expect(JSON.parse(text)).toEqual({ error: 'review_unavailable' })
      expect(text).not.toContain('service-token')
      expect(text).not.toContain('signed-identity-token')
      expect(text).not.toContain('libre_terminale')
    },
  )

  it.each([
    new Error('timeout Bearer service-token'),
    new SyntaxError('réponse non JSON signed-identity-token'),
  ])('convertit les rejets moteur en indisponibilité générique sans fuite', async (error) => {
    mockedFetchEngine.mockRejectedValue(error)

    const response = await GET(queueRequest())
    const text = await response.text()

    expect(response.status).toBe(503)
    expect(response.headers.get('Cache-Control')).toBe('private, no-store, max-age=0')
    expect(JSON.parse(text)).toEqual({ error: 'review_unavailable' })
    expect(text).not.toContain('service-token')
    expect(text).not.toContain('signed-identity-token')
  })
})
