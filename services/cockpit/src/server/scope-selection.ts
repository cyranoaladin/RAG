import type { InternalIdentity, InternalIdentityEnvelope } from '@/generated/contracts'
import {
  PILOT_RETRIEVAL_SCOPE,
  PILOT_RETRIEVAL_SCOPE_DIGEST,
  assertEnvelopeMatchesPilotScope,
  assertIdentityMatchesPilotScope,
} from '@/server/pilot-scope'
import {
  assertEnvelopeMatchesPublicScope,
  configuredPublicScopes,
  findPublicScopeForIdentity,
} from '@/server/public-scope'

export interface ConfiguredScope {
  readonly scopeId: string
  readonly scopeDigest: string
  readonly allowedCollections: readonly string[]
  readonly subjectForCollection: (collection: string) => string | null
}

function scopeMode(): 'pilot' | 'public_v3' {
  const value = process.env.NEXUS_COCKPIT_SCOPE_MODE?.trim() || 'pilot'
  if (value !== 'pilot' && value !== 'public_v3') {
    throw new Error('Mode de scope Cockpit invalide')
  }
  return value
}

export function resolveConfiguredScope(identity: InternalIdentity): ConfiguredScope {
  if (scopeMode() === 'public_v3') {
    const scopes = configuredPublicScopes()
    const selected = findPublicScopeForIdentity(identity, scopes)
    if (selected === null) throw new Error('Identité hors des scopes publics finaux')
    const subject = selected.artifact.evidence_subject
    return {
      scopeId: selected.artifact.scope_id,
      scopeDigest: selected.digest,
      allowedCollections: [subject.collection],
      subjectForCollection: (collection) => collection === subject.collection ? subject.matiere : null,
    }
  }

  assertIdentityMatchesPilotScope(identity)
  return {
    scopeId: PILOT_RETRIEVAL_SCOPE.scope_id,
    scopeDigest: PILOT_RETRIEVAL_SCOPE_DIGEST,
    allowedCollections: PILOT_RETRIEVAL_SCOPE.subjects.map((subject) => subject.collection),
    subjectForCollection: (collection) => PILOT_RETRIEVAL_SCOPE.subjects.find(
      (subject) => subject.collection === collection,
    )?.matiere ?? null,
  }
}

export function assertEnvelopeMatchesConfiguredScope(envelope: InternalIdentityEnvelope): void {
  if (scopeMode() === 'public_v3') {
    assertEnvelopeMatchesPublicScope(envelope, configuredPublicScopes())
    return
  }
  assertEnvelopeMatchesPilotScope(envelope)
}
