import { describe, expect, it } from 'vitest'

import {
  PILOT_RETRIEVAL_SCOPE,
  PILOT_RETRIEVAL_SCOPE_DIGEST,
} from '@/server/pilot-scope'

describe('projection canonique du scope pilote', () => {
  it('reste profondément immuable avec le digest publié par le contrat', () => {
    expect(PILOT_RETRIEVAL_SCOPE_DIGEST).toBe(
      'a1ed0fb1c7ec6344c17b155004d5bb61172b77f4b5bff6f5a250cc8b968fdd24',
    )
    expect(Object.isFrozen(PILOT_RETRIEVAL_SCOPE)).toBe(true)
    expect(Object.isFrozen(PILOT_RETRIEVAL_SCOPE.identity)).toBe(true)
    expect(Object.isFrozen(PILOT_RETRIEVAL_SCOPE.subjects)).toBe(true)
    expect(PILOT_RETRIEVAL_SCOPE.subjects.every(Object.isFrozen)).toBe(true)
  })
})
