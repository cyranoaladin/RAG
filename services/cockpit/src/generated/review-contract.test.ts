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

  it('rejects a returned count that differs from the document count', () => {
    expect(validateReviewQueueResponse({ ...validResponse, returned: 0 })).toBe(false)
  })
})
