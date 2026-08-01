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
} as never

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
    mockedRequireBffAuth.mockResolvedValue(authContext)
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

  it('dérive le profil du chat uniquement de l’identité signée', async () => {
    const response = await POST(chatRequest(['rag_nexus_nsi_terminale_specialite']))

    expect(response.status).toBe(200)
    expect(mockedIsPublicLaunchReady).toHaveBeenCalledWith('signed-identity-token')
    expect(mockedFetchEngine).toHaveBeenCalledWith('/chat', {
      method: 'POST',
      identityToken: 'signed-identity-token',
      body: expect.objectContaining({
        collections: ['rag_nexus_nsi_terminale_specialite'],
        student_profile: expect.objectContaining({
          niveau: 'terminale',
          voie: 'generale',
          matieres: ['nsi'],
          statut_enseignement: 'specialite',
          candidat: 'cned_libre',
          school_year: '2026-2027',
          zone: 'libre',
        }),
      }),
    })
  })
})
