import { describe, expect, it } from 'vitest'

import type { InternalIdentity } from '@/generated/contracts'
import {
  FINAL_RETRIEVAL_SCOPES,
  effectiveCollectionsForIdentity,
  scopeForIdentity,
  subjectForIdentityCollection,
} from '@/server/final-scope'
import { canonicalScopeDigest } from '@/server/pilot-scope'

const identity: InternalIdentity = {
  aud: 'nexus-cockpit',
  exp: 1_800_000_600,
  iss: 'nexus-issuer',
  jti: 'jti-12345',
  tenant: 'libre_terminale',
  niveau: 'terminale',
  role: 'teacher',
  school_year: '2026-2027',
  sub: 'psn_1234567890abcdef',
  pedagogical_profile: {
    voie: 'generale',
    matieres: ['nsi'],
    statut_enseignement: 'specialite',
    candidat: 'libre',
    audience: 'libre',
  },
}

describe('scopes contractuels du produit V4/V5', () => {
  it('charge les 11 scopes internes exacts de la release finale', () => {
    expect(FINAL_RETRIEVAL_SCOPES).toHaveLength(11)
    expect(new Set(FINAL_RETRIEVAL_SCOPES.map((scope) => scope.evidence_subject.collection)).size).toBe(11)
    expect(FINAL_RETRIEVAL_SCOPES.every((scope) => scope.evidence_subject.visibility === 'internal')).toBe(true)
    expect(FINAL_RETRIEVAL_SCOPES.every((scope) =>
      Object.isFrozen(scope) && Object.isFrozen(scope.evidence_subject) && Object.isFrozen(scope.target_identity),
    )).toBe(true)
  })

  it.each(FINAL_RETRIEVAL_SCOPES)('sélectionne sans ambiguïté $scope_id', (scope) => {
    const target = scope.target_identity
    const signed = {
      ...identity,
      tenant: target.tenant,
      niveau: target.niveau,
      school_year: scope.evidence_subject.school_year,
      pedagogical_profile: {
        voie: target.voie,
        matieres: [target.matiere],
        statut_enseignement: target.statut_enseignement,
        candidat: target.candidates[0],
        audience: target.audience,
      },
    } as InternalIdentity
    expect(scopeForIdentity(signed).scope_id).toBe(scope.scope_id)
    expect(effectiveCollectionsForIdentity(signed)).toEqual([scope.evidence_subject.collection])
  })

  it('sélectionne uniquement NSI terminale pour le profil signé correspondant', () => {
    const scope = scopeForIdentity(identity)
    expect(scope.scope_id).toBe('prod_nsi_terminale_specialite_v3')
    expect(canonicalScopeDigest(scope)).toBe('dd6eeafd7749b9cd7f3084fec826707100756f330005a68f385d0dada1979b2d')
    expect(effectiveCollectionsForIdentity(identity)).toEqual(['rag_nexus_nsi_terminale_specialite'])
    expect(subjectForIdentityCollection(identity, 'rag_nexus_nsi_terminale_specialite')?.matiere).toBe('nsi')
    expect(subjectForIdentityCollection(identity, 'rag_nexus_svt_terminale_specialite')).toBeNull()
  })

  it('préserve le scope pilote historique pour un profil maths hors release finale', () => {
    const maths = {
      ...identity,
      pedagogical_profile: { ...identity.pedagogical_profile, matieres: ['maths'] },
    } as InternalIdentity
    expect(scopeForIdentity(maths).scope_id).toBe('libre_terminale_maths_nsi_real_v1')
    expect(effectiveCollectionsForIdentity(maths)).toEqual(['rag_nexus_maths_terminale_gen_specialite'])
  })

  it('refuse un profil sans correspondance et ne réinterprète pas les droits élève', () => {
    const invalid = { ...identity, pedagogical_profile: { ...identity.pedagogical_profile, candidat: 'scolarise' } }
    expect(() => scopeForIdentity(invalid as InternalIdentity)).toThrow()
    const student = { ...identity, role: 'student' } as InternalIdentity
    const selected = scopeForIdentity(student)
    expect('evidence_subject' in selected ? selected.evidence_subject.visibility : null).toBe('internal')
  })
})
