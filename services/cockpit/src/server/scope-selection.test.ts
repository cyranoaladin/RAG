import { afterEach, describe, expect, it } from 'vitest'

import type { InternalIdentity } from '@/generated/contracts'
import { resolveConfiguredScope } from '@/server/scope-selection'

const identity = {
  iss: 'nexus-issuer', aud: 'nexus-cockpit', sub: 'psn_1234567890abcdef',
  jti: 'jti-12345', exp: 1800000600, tenant: 'libre_terminale',
  niveau: 'terminale', role: 'student', school_year: '2026-2027',
  pedagogical_profile: {
    voie: 'generale', matieres: ['nsi'], statut_enseignement: 'specialite',
    candidat: 'individuel', audience: 'libre',
  },
} as InternalIdentity

describe('sélection du scope BFF', () => {
  afterEach(() => {
    delete process.env.NEXUS_COCKPIT_SCOPE_MODE
    delete process.env.NEXUS_COCKPIT_PUBLIC_SCOPE_INDEX_SHA256
  })

  it('préserve la projection pilote hors mode public explicite', () => {
    expect(resolveConfiguredScope(identity).scopeId).toBe('libre_terminale_maths_nsi_real_v1')
  })

  it('refuse la publication quand l’index final public est vide', () => {
    process.env.NEXUS_COCKPIT_SCOPE_MODE = 'public_v3'
    process.env.NEXUS_COCKPIT_PUBLIC_SCOPE_INDEX_SHA256 = 'a'.repeat(64)
    expect(() => resolveConfiguredScope(identity)).toThrow('Index public final absent ou non scellé')
  })

  it('refuse un mode inconnu plutôt que revenir au pilote', () => {
    process.env.NEXUS_COCKPIT_SCOPE_MODE = 'public'
    expect(() => resolveConfiguredScope(identity)).toThrow('Mode de scope Cockpit invalide')
  })
})
