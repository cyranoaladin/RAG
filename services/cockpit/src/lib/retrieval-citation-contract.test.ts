import { describe, expect, it } from 'vitest'
import Ajv2020 from 'ajv/dist/2020.js'

import ChatResponseSchema from '@/generated/schema/chat-response.json'
import RetrievalResponseSchema from '@/generated/schema/retrieval-response.json'
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

  it('accepte un champ d’attribution nul comme absent', () => {
    expect(validateRetrievalResponse(responseWithCitation({
      ...legacyCitation,
      licensor: null,
    }))).toBe(true)
  })

  it('refuse une date civile impossible', () => {
    expect(validateRetrievalResponse(responseWithCitation({
      ...legacyCitation,
      licensor: 'Ministère de l’Éducation nationale – Dgesco / Éduscol',
      licence_id: 'ETALAB-2.0',
      source_updated_at: '2026-02-30',
      derivative_notice: 'Extrait textuel dérivé.',
    }))).toBe(false)
  })

  it('accepte les dates ISO sans plugin de validation de format dans les deux schémas', () => {
    for (const schema of [RetrievalResponseSchema, ChatResponseSchema]) {
      const validator = new Ajv2020({ strict: false, logger: false }).compile(schema.$defs.Citation)
      for (const source_updated_at of ['2026-09-12', '2026-10-10T06:04:23.168Z']) {
        expect(validator({
          ...legacyCitation,
          licensor: 'Ministère de l’Éducation nationale – Dgesco / Éduscol',
          licence_id: 'ETALAB-2.0',
          source_updated_at,
          derivative_notice: 'Extrait textuel dérivé.',
        })).toBe(true)
      }
      expect(validator({
        ...legacyCitation,
        licensor: 'Ministère de l’Éducation nationale – Dgesco / Éduscol',
        licence_id: 'ETALAB-2.0',
        source_updated_at: 'date-inconnue',
        derivative_notice: 'Extrait textuel dérivé.',
      })).toBe(false)
    }
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
