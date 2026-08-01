import { createHash } from 'node:crypto'

import pilotScopeSource from '@/generated/pilot-retrieval-scope-v1.json'
import type {
  InternalIdentity,
  InternalIdentityEnvelope,
  PilotRetrievalScopeArtifact,
} from '@/generated/contracts'
import {
  validateInternalIdentity,
  validateInternalIdentityEnvelope,
  validatePilotRetrievalScopeArtifact,
} from '@/generated/validators'

function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value)
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(',')}]`
  }
  const entries = Object.entries(value as Record<string, unknown>)
    .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
    .map(([key, entry]) => `${JSON.stringify(key)}:${canonicalJson(entry)}`)
  return `{${entries.join(',')}}`
}

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === 'object') {
    for (const entry of Object.values(value as Record<string, unknown>)) {
      deepFreeze(entry)
    }
    Object.freeze(value)
  }
  return value
}

function isConsecutiveSchoolYear(value: string): boolean {
  const match = /^(\d{4})-(\d{4})$/.exec(value)
  return match !== null && Number(match[2]) === Number(match[1]) + 1
}

if (!validatePilotRetrievalScopeArtifact(pilotScopeSource)) {
  throw new Error('Artefact de scope pilote invalide')
}
if (!isConsecutiveSchoolYear(pilotScopeSource.school_year)) {
  throw new Error('Année scolaire du scope pilote invalide')
}

export const PILOT_RETRIEVAL_SCOPE: PilotRetrievalScopeArtifact = deepFreeze(pilotScopeSource)
export const PILOT_RETRIEVAL_SCOPE_DIGEST = createHash('sha256')
  .update(canonicalJson(PILOT_RETRIEVAL_SCOPE), 'utf8')
  .digest('hex')

export function assertIdentityMatchesPilotScope(identity: InternalIdentity): void {
  if (!validateInternalIdentity(identity) || !isConsecutiveSchoolYear(identity.school_year)) {
    throw new Error('Identité interne non conforme au contrat 0.4')
  }

  const expected = PILOT_RETRIEVAL_SCOPE.identity
  const profile = identity.pedagogical_profile
  const allowedSubjects = new Set(PILOT_RETRIEVAL_SCOPE.subjects.map((subject) => subject.matiere))
  if (
    identity.tenant !== expected.tenant ||
    identity.niveau !== expected.niveau ||
    identity.school_year !== PILOT_RETRIEVAL_SCOPE.school_year ||
    profile.voie !== expected.voie ||
    profile.statut_enseignement !== expected.statut_enseignement ||
    profile.audience !== expected.audience ||
    !expected.candidates.includes(profile.candidat) ||
    !profile.matieres.every((matiere) => allowedSubjects.has(matiere))
  ) {
    throw new Error('Identité interne hors du scope pilote')
  }
}

export function assertEnvelopeMatchesPilotScope(envelope: InternalIdentityEnvelope): void {
  if (!validateInternalIdentityEnvelope(envelope)) {
    throw new Error('Enveloppe interne non conforme au contrat 0.4')
  }
  if (
    envelope.sub !== envelope.identity.sub ||
    envelope.jti !== envelope.identity.jti ||
    envelope.exp > envelope.identity.exp ||
    envelope.iat > envelope.exp
  ) {
    throw new Error('Enveloppe interne non liée à son identité')
  }
  const allowedCollections = PILOT_RETRIEVAL_SCOPE.subjects.map((subject) => subject.collection)
  if (
    envelope.scope_id !== PILOT_RETRIEVAL_SCOPE.scope_id ||
    envelope.scope_digest !== PILOT_RETRIEVAL_SCOPE_DIGEST ||
    JSON.stringify(envelope.allowed_collections) !== JSON.stringify(allowedCollections)
  ) {
    throw new Error('Enveloppe interne hors du scope pilote')
  }
  assertIdentityMatchesPilotScope(envelope.identity)
}
