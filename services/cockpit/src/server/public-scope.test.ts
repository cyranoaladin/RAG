import { describe, expect, it } from 'vitest'

import type { InternalIdentity, InternalIdentityEnvelope } from '@/generated/contracts'
import {
  assertPublicScopeIndex,
  findPublicScopeForIdentity,
  assertEnvelopeMatchesPublicScope,
} from '@/server/public-scope'

const scope = {
  artifact_version: '3',
  scope_id: 'prod_nsi_terminale_specialite_v4',
  status: 'eligible_for_promotion',
  source_sha256: 'a'.repeat(64),
  target_policy: {
    tenant: 'libre_terminale', niveau: 'terminale', voie: 'generale',
    matiere: 'nsi', statut_enseignement: 'specialite',
    audiences: ['libre'], candidates: ['libre'], roles: ['student'],
  },
  evidence_subject: {
    collection: 'rag_nexus_nsi_terminale_specialite',
    tenant: 'libre_terminale', niveau: 'terminale', voie: 'generale',
    matiere: 'nsi', statut_enseignement: 'specialite', candidat: 'libre',
    audiences: ['libre'], visibility: 'public', rights: ['officiel_public'],
    school_year: '2026-2027', programme_version: 'BOEN_2026',
  },
}

const identity: InternalIdentity = {
  iss: 'nexus-issuer', aud: 'nexus-cockpit', sub: 'psn_1234567890abcdef',
  jti: 'jti-12345', exp: 1800000600, tenant: 'libre_terminale',
  niveau: 'terminale', role: 'student', school_year: '2026-2027',
  pedagogical_profile: {
    voie: 'generale', matieres: ['nsi'], statut_enseignement: 'specialite',
    candidat: 'libre', audience: 'libre',
  },
}

describe('index public V3', () => {
  it('sélectionne un seul scope public pour une identité étudiante mono-matière exacte', () => {
    const index = assertPublicScopeIndex([scope])
    expect(Object.isFrozen(index[0].artifact)).toBe(true)
    expect(Object.isFrozen(index[0].artifact.target_policy)).toBe(true)
    expect(findPublicScopeForIdentity(identity, index)?.artifact.scope_id).toBe(scope.scope_id)
    expect(findPublicScopeForIdentity({ ...identity, role: 'teacher' }, index)).toBeNull()
    expect(findPublicScopeForIdentity({ ...identity, pedagogical_profile: {
      ...identity.pedagogical_profile, matieres: ['nsi', 'maths'],
    } }, index)).toBeNull()
  })

  it('refuse une visibilité interne, un doublon, un scope non final et une identité hors cible', () => {
    expect(() => assertPublicScopeIndex([{ ...scope, evidence_subject: {
      ...scope.evidence_subject, visibility: 'internal',
    } }])).toThrow()
    expect(() => assertPublicScopeIndex([{ ...scope, evidence_subject: {
      ...scope.evidence_subject, rights: ['usage_interne'],
    } }])).toThrow()
    expect(() => assertPublicScopeIndex([scope, scope])).toThrow()
    expect(() => assertPublicScopeIndex([{ ...scope, scope_id: 'student_public_nsi_v1' }])).toThrow()
    const index = assertPublicScopeIndex([scope])
    expect(findPublicScopeForIdentity({ ...identity, tenant: 'libre_premiere' }, index)).toBeNull()
  })

  it('lie l’enveloppe au digest, à la collection et à l’identité exacts du scope', () => {
    const index = assertPublicScopeIndex([scope])
    const envelope = {
      protocol_version: '1', iss: 'cockpit-internal', aud: 'rag-engine',
      sub: identity.sub, jti: identity.jti, iat: 1800000000, exp: 1800000300,
      identity, scope_id: scope.scope_id, scope_digest: index[0].digest,
      allowed_collections: [scope.evidence_subject.collection],
    } as InternalIdentityEnvelope
    expect(() => assertEnvelopeMatchesPublicScope(envelope, index)).not.toThrow()
    expect(() => assertEnvelopeMatchesPublicScope({ ...envelope, scope_digest: 'b'.repeat(64) }, index)).toThrow()
    expect(() => assertEnvelopeMatchesPublicScope({ ...envelope, allowed_collections: ['other'] }, index)).toThrow()
  })
})
