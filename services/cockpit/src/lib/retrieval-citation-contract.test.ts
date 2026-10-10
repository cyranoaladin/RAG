import { describe, expect, it } from 'vitest'

import { validateRetrievalResponse } from '@/generated/validators'

const legacyCitation = {
  source_label: 'Programme NSI',
  source_uri: 'https://eduscol.education.gouv.fr/document.pdf',
  rights: 'officiel_public',
  page: 3,
}

function responseWithCitation(citation: Record<string, unknown>) {
  return {
    results: [{
      chunk_id: 'chunk-1',
      doc_id: 'doc-1',
      score: 0.9,
      excerpt: 'Un extrait vérifié.',
      citation,
    }],
    warnings: [],
    filters_applied: {},
  }
}

describe('contrat BFF des citations dérivées publiques', () => {
  it('accepte la citation historique', () => {
    expect(validateRetrievalResponse(responseWithCitation(legacyCitation))).toBe(true)
  })

  it('accepte une attribution publique complète liée à la page source', () => {
    expect(validateRetrievalResponse(responseWithCitation({
      ...legacyCitation,
      licensor: 'Ministère de l’Éducation nationale – Dgesco / Éduscol',
      licence_id: 'ETALAB-2.0',
      source_updated_at: '2026-10-10T06:04:23.168Z',
      derivative_notice: 'Extrait textuel dérivé.',
    }))).toBe(true)
  })

  it('refuse une attribution publique partielle', () => {
    expect(validateRetrievalResponse(responseWithCitation({
      ...legacyCitation,
      licence_id: 'ETALAB-2.0',
    }))).toBe(false)
  })

  it('refuse une attribution publique sans page', () => {
    expect(validateRetrievalResponse(responseWithCitation({
      ...legacyCitation,
      page: null,
      licensor: 'Ministère de l’Éducation nationale – Dgesco / Éduscol',
      licence_id: 'ETALAB-2.0',
      source_updated_at: '2026-10-10T06:04:23.168Z',
      derivative_notice: 'Extrait textuel dérivé.',
    }))).toBe(false)
  })
})
