import { beforeEach, describe, expect, it, vi } from 'vitest'

import { requireBffAuth } from '@/server/bff-auth'

import { fetchEngine } from '../_engine'
import { GET } from './route'

vi.mock('@/server/bff-auth', () => ({ requireBffAuth: vi.fn() }))
vi.mock('../_engine', () => ({ fetchEngine: vi.fn() }))

const mockedRequireBffAuth = vi.mocked(requireBffAuth)
const mockedFetchEngine = vi.mocked(fetchEngine)
const request = new Request('http://cockpit.test/api/collections')
const authContext = {
  identityToken: 'signed-identity-token',
  allowedCollections: ['pilot-collection'],
  identity: { sub: 'psn_1234567890abcdef' },
} as never

describe('GET /api/collections', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedRequireBffAuth.mockResolvedValue(authContext)
  })

  it('refuse avant tout appel moteur lorsque la session manque', async () => {
    mockedRequireBffAuth.mockResolvedValue(null)

    const response = await GET(request)

    expect(response.status).toBe(401)
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it('transmet l’identité signée aux seuls endpoints BFF réduits', async () => {
    mockedFetchEngine
      .mockResolvedValueOnce({
        status: 200,
        payload: {
          collections: [{
            name: 'pilot-collection',
            matiere: 'nsi',
            niveau: 'terminale',
            voie: 'generale',
            statut: 'specialite',
            domain: 'education',
            instanciee: true,
          }],
        },
      })
      .mockResolvedValueOnce({
        status: 200,
        payload: {
          launch_ready: false,
          total_collections: 1,
          ready_collections: 0,
          blockers: ['preuve exhaustive de release absente'],
        },
      })

    const response = await GET(request)

    expect(response.status).toBe(200)
    expect(mockedFetchEngine).toHaveBeenNthCalledWith(1, '/collections/v2', {
      identityToken: 'signed-identity-token',
    })
    expect(mockedFetchEngine).toHaveBeenNthCalledWith(2, '/collections/readiness', {
      identityToken: 'signed-identity-token',
    })
  })
})
