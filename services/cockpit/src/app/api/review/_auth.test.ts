import { describe, expect, it } from 'vitest'

import { isReviewCollectionAllowed } from './_auth'

const context = {
  allowedCollections: ['rag_nexus_nsi_terminale_specialite'],
} as never

describe('isReviewCollectionAllowed', () => {
  it.each([undefined, null])('autorise une collection omise (%s)', (collection) => {
    expect(isReviewCollectionAllowed(context, collection)).toBe(true)
  })

  it('autorise une collection présente dans le scope signé', () => {
    expect(isReviewCollectionAllowed(context, 'rag_nexus_nsi_terminale_specialite')).toBe(true)
  })

  it('refuse une collection absente du scope signé', () => {
    expect(isReviewCollectionAllowed(context, 'collection_hors_scope')).toBe(false)
  })
})
