import { beforeEach, describe, expect, it, vi } from 'vitest'

import { requireBffAuth } from '@/server/bff-auth'

import { fetchEngine, isPublicLaunchReady } from '../_engine'
import { POST } from './route'

vi.mock('@/server/bff-auth', () => ({ requireBffAuth: vi.fn() }))
vi.mock('../_engine', () => ({
  fetchEngine: vi.fn(),
  isPublicLaunchReady: vi.fn(),
}))

const mockedFetchEngine = vi.mocked(fetchEngine)
const mockedIsPublicLaunchReady = vi.mocked(isPublicLaunchReady)
const mockedRequireBffAuth = vi.mocked(requireBffAuth)

const authContext = {
  identityToken: 'signed-identity-token',
  allowedCollections: [
    'rag_nexus_maths_terminale_gen_specialite',
    'rag_nexus_nsi_terminale_specialite',
  ],
  identity: {
    aud: 'nexus-cockpit',
    exp: 1_800_000_600,
    iss: 'nexus-issuer',
    jti: 'jti-12345',
    tenant: 'libre_terminale',
    niveau: 'terminale',
    role: 'student',
    school_year: '2026-2027',
    sub: 'psn_1234567890abcdef',
    pedagogical_profile: {
      voie: 'generale',
      matieres: ['maths', 'nsi'],
      statut_enseignement: 'specialite',
      candidat: 'cned_libre',
      audience: 'libre',
    },
  },
}

function chatRequest(collections: string[]): Request {
  return new Request('http://cockpit.test/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: 'Explique la dérivation', collections }),
  })
}

describe('POST /api/chat', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedRequireBffAuth.mockResolvedValue(authContext as never)
    mockedIsPublicLaunchReady.mockResolvedValue(true)
    mockedFetchEngine.mockResolvedValue({
      status: 200,
      payload: {
        answer: 'Réponse sourcée',
        citations: [],
        grounded: true,
        refusal_reason: null,
        retrieval_hits: [],
        warnings: [],
      },
    })
  })

  it('répond 401 avant tout appel moteur lorsque la session manque', async () => {
    mockedRequireBffAuth.mockResolvedValue(null)

    const response = await POST(chatRequest(['rag_nexus_maths_terminale_gen_specialite']))

    expect(response.status).toBe(401)
    expect(mockedIsPublicLaunchReady).not.toHaveBeenCalled()
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it('refuse une collection hors scope avant tout appel moteur', async () => {
    const response = await POST(chatRequest(['collection-arbitraire']))

    expect(response.status).toBe(403)
    expect(mockedIsPublicLaunchReady).not.toHaveBeenCalled()
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it('ferme explicitement la génération pour un scope final HGGSP sans appel moteur', async () => {
    mockedRequireBffAuth.mockResolvedValue({
      ...authContext,
      scopeId: 'prod_hggsp_terminale_specialite_v3',
      allowedCollections: ['rag_nexus_hggsp_terminale_specialite'],
      identity: {
        ...authContext.identity,
        pedagogical_profile: {
          ...authContext.identity.pedagogical_profile,
          matieres: ['hggsp'],
          candidat: 'libre',
        },
      },
    } as never)

    const response = await POST(chatRequest(['rag_nexus_hggsp_terminale_specialite']))

    expect(response.status).toBe(503)
    expect(await response.json()).toEqual({ error: 'answer_generation_disabled' })
    expect(mockedIsPublicLaunchReady).not.toHaveBeenCalled()
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it('refuse aussi la génération sur le pilote historique', async () => {
    const response = await POST(chatRequest(['rag_nexus_nsi_terminale_specialite']))

    expect(response.status).toBe(503)
    expect(await response.json()).toEqual({ error: 'answer_generation_disabled' })
    expect(mockedIsPublicLaunchReady).not.toHaveBeenCalled()
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })

  it('n’envoie pas non plus une requête dupliquée au moteur', async () => {
    const collection = 'rag_nexus_nsi_terminale_specialite'

    const response = await POST(chatRequest([collection, collection]))

    expect(response.status).toBe(503)
    expect(mockedIsPublicLaunchReady).not.toHaveBeenCalled()
    expect(mockedFetchEngine).not.toHaveBeenCalled()
  })
})
