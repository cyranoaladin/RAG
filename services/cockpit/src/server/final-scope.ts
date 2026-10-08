import scopeSources from '@/generated/final-retrieval-scopes-v4-v5.json'
import type {
  InternalIdentity,
  InternalIdentityEnvelope,
  PilotRetrievalScopeArtifact,
  RetrievalScopeArtifactV2,
} from '@/generated/contracts'
import {
  validateInternalIdentity,
  validateInternalIdentityEnvelope,
  validateRetrievalScopeArtifactV2,
} from '@/generated/validators'
import {
  PILOT_RETRIEVAL_SCOPE,
  assertEnvelopeMatchesPilotScope,
  assertIdentityMatchesPilotScope,
  canonicalScopeDigest,
  deepFreeze,
} from '@/server/pilot-scope'

export type BffRetrievalScope = PilotRetrievalScopeArtifact | RetrievalScopeArtifactV2

const scopes: RetrievalScopeArtifactV2[] = scopeSources.map((source) => {
  if (!validateRetrievalScopeArtifactV2(source) || source.evidence_subject.visibility !== 'internal') {
    throw new Error('Scope final BFF invalide')
  }
  return deepFreeze(source)
})
if (
  scopes.length !== 11 ||
  new Set(scopes.map((scope) => scope.scope_id)).size !== 11 ||
  new Set(scopes.map((scope) => scope.evidence_subject.collection)).size !== 11
) {
  throw new Error('Registre BFF final incomplet ou ambigu')
}
export const FINAL_RETRIEVAL_SCOPES: readonly RetrievalScopeArtifactV2[] = Object.freeze(scopes)

function matchesV2Identity(scope: RetrievalScopeArtifactV2, identity: InternalIdentity): boolean {
  const target = scope.target_identity
  const profile = identity.pedagogical_profile
  return identity.tenant === target.tenant
    && identity.niveau === target.niveau
    && identity.school_year === scope.evidence_subject.school_year
    && profile.voie === target.voie
    && profile.matieres.length === 1
    && profile.matieres[0] === target.matiere
    && profile.statut_enseignement === target.statut_enseignement
    && target.candidates.includes(profile.candidat)
    && profile.audience === target.audience
}

/** Each profile resolves to one pinned contract artifact; legacy pilot stays immutable. */
export function scopeForIdentity(identity: InternalIdentity, pinnedScopeId?: string): BffRetrievalScope {
  if (!validateInternalIdentity(identity)) {
    throw new Error('Identité interne invalide')
  }
  if (pinnedScopeId === PILOT_RETRIEVAL_SCOPE.scope_id) {
    assertIdentityMatchesPilotScope(identity)
    return PILOT_RETRIEVAL_SCOPE
  }
  const matches = FINAL_RETRIEVAL_SCOPES.filter((scope) =>
    (pinnedScopeId === undefined || scope.scope_id === pinnedScopeId)
    && matchesV2Identity(scope, identity))
  if (matches.length === 1) return matches[0]
  if (matches.length > 1 || pinnedScopeId !== undefined) {
    throw new Error('Identité hors scope final BFF')
  }
  assertIdentityMatchesPilotScope(identity)
  return PILOT_RETRIEVAL_SCOPE
}

export function effectiveCollectionsForIdentity(
  identity: InternalIdentity,
  scope: BffRetrievalScope = scopeForIdentity(identity),
): string[] {
  if ('evidence_subject' in scope) return [scope.evidence_subject.collection]
  const signedMatieres = new Set(identity.pedagogical_profile.matieres)
  return scope.subjects
    .filter((subject) => signedMatieres.has(subject.matiere))
    .map((subject) => subject.collection)
}

export function subjectForIdentityCollection(
  identity: InternalIdentity,
  collection: string,
  scope: BffRetrievalScope = scopeForIdentity(identity),
): { matiere: string } | null {
  if ('evidence_subject' in scope) {
    return scope.evidence_subject.collection === collection ? scope.evidence_subject : null
  }
  return scope.subjects.find((subject) => subject.collection === collection
    && identity.pedagogical_profile.matieres.includes(subject.matiere)) ?? null
}

export function assertEnvelopeMatchesBffScope(envelope: InternalIdentityEnvelope): BffRetrievalScope {
  if (!validateInternalIdentityEnvelope(envelope)) {
    throw new Error('Enveloppe BFF invalide')
  }
  const scope = scopeForIdentity(envelope.identity, envelope.scope_id)
  if (!('evidence_subject' in scope)) {
    assertEnvelopeMatchesPilotScope(envelope)
    return scope
  }
  if (
    envelope.sub !== envelope.identity.sub ||
    envelope.jti !== envelope.identity.jti ||
    envelope.iat > envelope.exp ||
    envelope.exp > envelope.identity.exp ||
    envelope.scope_digest !== canonicalScopeDigest(scope) ||
    envelope.allowed_collections.length !== 1 ||
    envelope.allowed_collections[0] !== scope.evidence_subject.collection
  ) {
    throw new Error('Enveloppe BFF hors scope final')
  }
  return scope
}
