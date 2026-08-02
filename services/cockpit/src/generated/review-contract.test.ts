import { describe, expect, it } from 'vitest'

import type { ReviewQueueResponse } from './contracts'
import { validateReviewQueueResponse } from './validators'

const validResponse: ReviewQueueResponse = {
  total_pending_docs: 1,
  returned: 1,
  offset: 0,
  documents: [
    {
      doc_id: 'doc-1',
      collection: 'libre_terminale_maths',
      source_label: 'Programme de mathématiques',
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

describe('validateReviewQueueResponse', () => {
  it('accepts a structurally and semantically valid response', () => {
    expect(validateReviewQueueResponse(validResponse)).toBe(true)
  })

  it('accepts RFC 3339 timestamps', () => {
    expect(validateReviewQueueResponse({
      ...validResponse,
      documents: [{
        ...validResponse.documents[0],
        first_indexed: '2026-08-02T12:34:56Z',
        last_indexed: '2026-08-02T13:34:56+01:00',
      }],
    })).toBe(true)
  })

  it.each(['first_indexed', 'last_indexed'] as const)(
    'rejects an invalid %s date-time',
    (field) => {
      expect(validateReviewQueueResponse({
        ...validResponse,
        documents: [{
          ...validResponse.documents[0],
          [field]: 'not-a-date-time',
        }],
      })).toBe(false)
    },
  )

  it('rejects a returned count that differs from the document count', () => {
    expect(validateReviewQueueResponse({ ...validResponse, returned: 0 })).toBe(false)
  })
})
