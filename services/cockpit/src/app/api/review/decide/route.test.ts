import { beforeEach, describe, expect, it, vi } from 'vitest'

import { requireBffAuth } from '@/server/bff-auth'

import { fetchEngine } from '../../_engine'
import { POST } from './route'

vi.mock('@/server/bff-auth', () => ({ requireBffAuth: vi.fn() }))
vi.mock('../../_engine', () => ({ fetchEngine: vi.fn() }))

const mockedRequireBffAuth = vi.mocked(requireBffAuth)
const mockedFetchEngine = vi.mocked(fetchEngine)

const allowedCollection = 'rag_nexus_nsi_terminale_specialite'
const validPayload = {
  collection: allowedCollection,
  decision: 'reviewed',
  target_id: 'doc-1',
  target_type: 'doc',
} as const
const validDecision = {
  cache_invalidated_this_worker: true,
  chunks_affected: 3,
  decision: 'reviewed',
  max_stale_other_workers_s: 0,
  target_id: 'doc-1',
  target_type: 'doc',
} as const

function authContext(
  role: 'admin' | 'reviewer' | 'student' | 'teacher' | 'ingest_agent',
  tenant = 'libre_terminale',
) {
  return {
    identityToken: 'signed-identity-token',
    allowedCollections: [allowedCollection],
    identity: {
      role,
      tenant,
    },
  } as never
}

function decideRequest(body: unknown): Request {
  return new Request('http://cockpit.test/api/review/decide', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

function malformedRequest(body: string): Request {
  return new Request('http://cockpit.test/api/review/decide', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
  })
}

async function expectJson(response: Response, status: number, body: unknown): Promise<void> {
  expect(response.status).toBe(status)
  expect(response.headers.get('Cache-Control')).toBe('private, no-store, max-age=0')
  await expect(response.json()).resolves.toEqual(body)
}

describe('POST /api/review/decide', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedRequireBffAuth.mockResolvedValue(authContext('reviewer'))
    mockedFetchEngine.mockResolvedValue({ status: 200, payload: validDecision })
  })

  it('répond 401 avant de lire le corps ou d’appeler le moteur lorsque la session manque', async () => {
    mockedRequireBffAuth.mockResolvedValue(null)

    const response = await POST(malformedRequest('{'))

    await expectJson(response, 401, { error: 'unauthorized' })
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it.each(['student', 'teacher', 'ingest_agent'] as const)(
    'répond 403 au rôle non autorisé %s avant tout appel moteur',
    async (role) => {
      mockedRequireBffAuth.mockResolvedValue(authContext(role))

      const response = await POST(decideRequest(validPayload))

      await expectJson(response, 403, { error: 'forbidden' })
      expect(mockedFetchEngine).not.toHaveBeenCalled()
    },
  )

  it.each([
    ['JSON mal formé', malformedRequest('{')],
    ['null', decideRequest(null)],
    ['un tableau', decideRequest([validPayload])],
    ['une chaîne', decideRequest('reviewed')],
    ['un nombre', decideRequest(1)],
  ])('rejette %s avant tout appel moteur', async (_label, request) => {
    const response = await POST(request)

    await expectJson(response, 400, { error: 'invalid_request' })
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it.each([
    ['tenant', { ...validPayload, tenant: 'tenant_navigateur' }],
    ['reason', { ...validPayload, reason: 'texte libre interdit' }],
    ['arbitrary', { ...validPayload, arbitrary: 'champ inattendu' }],
  ])('rejette le champ navigateur supplémentaire %s avant le moteur', async (_field, body) => {
    const response = await POST(decideRequest(body))

    await expectJson(response, 400, { error: 'invalid_request' })
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it.each([
    {},
    { ...validPayload, target_id: '' },
    { ...validPayload, target_type: 'document' },
    { ...validPayload, decision: 'pending' },
    { ...validPayload, collection: 'NSI-Terminale' },
  ])('rejette un payload hors contrat avant le moteur : %j', async (body) => {
    const response = await POST(decideRequest(body))

    await expectJson(response, 400, { error: 'invalid_request' })
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it('rejette une collection hors scope avant tout appel moteur', async () => {
    const response = await POST(decideRequest({
      ...validPayload,
      collection: 'collection_hors_scope',
    }))

    await expectJson(response, 403, { error: 'forbidden' })
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it.each(['admin', 'reviewer'] as const)(
    'autorise %s et ajoute exclusivement le tenant signé au corps moteur',
    async (role) => {
      mockedRequireBffAuth.mockResolvedValue(authContext(role))

      const response = await POST(decideRequest(validPayload))

      await expectJson(response, 200, validDecision)
      expect(mockedFetchEngine).toHaveBeenCalledOnce()
      expect(mockedFetchEngine).toHaveBeenCalledWith('/review/v2/decide', {
        method: 'POST',
        identityToken: 'signed-identity-token',
        body: {
          ...validPayload,
          tenant: 'libre_terminale',
        },
      })
    },
  )

  it('revalide le corps enrichi et refuse un tenant signé hors contrat avant le moteur', async () => {
    mockedRequireBffAuth.mockResolvedValue(authContext('reviewer', 'Tenant-Invalide'))

    const response = await POST(decideRequest(validPayload))

    await expectJson(response, 400, { error: 'invalid_request' })
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it('rend un 404 générique sans identifiant ni détail moteur', async () => {
    mockedFetchEngine.mockResolvedValue({
      status: 404,
      payload: {
        detail: 'doc-1 Bearer service-token signed-identity-token tenant=libre_terminale',
      },
    })

    const response = await POST(decideRequest(validPayload))
    const text = await response.text()

    expect(response.status).toBe(404)
    expect(response.headers.get('Cache-Control')).toBe('private, no-store, max-age=0')
    expect(JSON.parse(text)).toEqual({ error: 'review_target_unavailable' })
    expect(text).not.toContain('doc-1')
    expect(text).not.toContain('service-token')
    expect(text).not.toContain('signed-identity-token')
    expect(text).not.toContain('libre_terminale')
  })

  it.each([
    null,
    { ...validDecision, chunks_affected: 0 },
    { ...validDecision, cache_invalidated_this_worker: 'true' },
    { ...validDecision, max_stale_other_workers_s: 1 },
    { ...validDecision, max_stale_other_workers_s: false },
    { ...validDecision, credential: 'service-token' },
  ])('échoue fermé quand le moteur renvoie un payload 200 hors contrat : %j', async (payload) => {
    mockedFetchEngine.mockResolvedValue({ status: 200, payload })

    const response = await POST(decideRequest(validPayload))

    await expectJson(response, 503, { error: 'review_unavailable' })
  })

  it.each([
    [
      'target_id',
      { ...validDecision, target_id: 'doc-cible-autre-secrete' },
      'doc-cible-autre-secrete',
    ],
    ['target_type', { ...validDecision, target_type: 'chunk' }, 'chunk'],
    ['decision', { ...validDecision, decision: 'quarantined' }, 'quarantined'],
  ])(
    'échoue fermé quand la réponse 200 diverge de la requête sur %s',
    async (_field, payload, leakedValue) => {
      mockedFetchEngine.mockResolvedValue({ status: 200, payload })

      const response = await POST(decideRequest(validPayload))
      const text = await response.text()

      expect(response.status).toBe(503)
      expect(response.headers.get('Cache-Control')).toBe('private, no-store, max-age=0')
      expect(JSON.parse(text)).toEqual({ error: 'review_unavailable' })
      expect(text).not.toContain(leakedValue)
    },
  )

  it.each([400, 401, 403, 409, 422, 500, 503])(
    'convertit le statut moteur %i en indisponibilité générique sans fuite',
    async (status) => {
      mockedFetchEngine.mockResolvedValue({
        status,
        payload: {
          detail: 'doc-1 Bearer service-token signed-identity-token tenant=libre_terminale',
        },
      })

      const response = await POST(decideRequest(validPayload))
      const text = await response.text()

      expect(response.status).toBe(503)
      expect(response.headers.get('Cache-Control')).toBe('private, no-store, max-age=0')
      expect(JSON.parse(text)).toEqual({ error: 'review_unavailable' })
      expect(text).not.toContain('doc-1')
      expect(text).not.toContain('service-token')
      expect(text).not.toContain('signed-identity-token')
      expect(text).not.toContain('libre_terminale')
    },
  )

  it.each([
    new Error('timeout Bearer service-token doc-1'),
    new SyntaxError('réponse non JSON signed-identity-token'),
  ])('convertit les rejets moteur en indisponibilité générique sans fuite', async (error) => {
    mockedFetchEngine.mockRejectedValue(error)

    const response = await POST(decideRequest(validPayload))
    const text = await response.text()

    expect(response.status).toBe(503)
    expect(response.headers.get('Cache-Control')).toBe('private, no-store, max-age=0')
    expect(JSON.parse(text)).toEqual({ error: 'review_unavailable' })
    expect(text).not.toContain('doc-1')
    expect(text).not.toContain('service-token')
    expect(text).not.toContain('signed-identity-token')
  })
})
