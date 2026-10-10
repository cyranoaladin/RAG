import { createHash } from 'node:crypto'

import publicScopeSource from '@/generated/public-retrieval-scopes-v3.json'
import type {
  InternalIdentity,
  InternalIdentityEnvelope,
  RetrievalScopeArtifactV3,
} from '@/generated/contracts'
import {
  validateInternalIdentity,
  validateInternalIdentityEnvelope,
  validateRetrievalScopeArtifactV3,
} from '@/generated/validators'

export interface PublicScopeBinding {
  readonly artifact: RetrievalScopeArtifactV3
  readonly digest: string
}

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === 'object') {
    for (const entry of Object.values(value as Record<string, unknown>)) deepFreeze(entry)
    Object.freeze(value)
  }
  return value
}

export function canonicalScopeJson(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value)
  if (Array.isArray(value)) return `[${value.map(canonicalScopeJson).join(',')}]`
  const entries = Object.entries(value as Record<string, unknown>)
    .sort(([left], [right]) => left < right ? -1 : left > right ? 1 : 0)
    .map(([key, entry]) => `${JSON.stringify(key)}:${canonicalScopeJson(entry)}`)
  return `{${entries.join(',')}}`
}

function digest(value: unknown): string {
  return createHash('sha256').update(canonicalScopeJson(value), 'utf8').digest('hex')
}

export function assertPublicScopeIndex(value: unknown): readonly PublicScopeBinding[] {
  if (!Array.isArray(value)) throw new Error('Index de scopes publics invalide')
  const ids = new Set<string>()
  const collections = new Set<string>()
  return Object.freeze(value.map((raw: unknown) => {
    if (!validateRetrievalScopeArtifactV3(raw)) {
      throw new Error('Artefact de scope public V3 invalide')
    }
    const artifact = deepFreeze(structuredClone(raw) as RetrievalScopeArtifactV3)
    const subject = artifact.evidence_subject
    const policy = artifact.target_policy
    if (
      !/^prod_[a-z0-9_]+_v[0-9]+$/.test(artifact.scope_id) ||
      subject.visibility !== 'public' ||
      subject.rights.length !== 1 || subject.rights[0] !== 'public_allowed' ||
      !policy.roles.includes('student') ||
      policy.tenant !== subject.tenant ||
      policy.niveau !== subject.niveau ||
      policy.voie !== subject.voie ||
      policy.matiere !== subject.matiere ||
      policy.statut_enseignement !== subject.statut_enseignement ||
      !policy.audiences.every((audience) => subject.audiences.includes(audience) || subject.audiences.includes('tous')) ||
      ids.has(artifact.scope_id) ||
      collections.has(subject.collection)
    ) {
      throw new Error('Scope public non final ou incohérent')
    }
    ids.add(artifact.scope_id)
    collections.add(subject.collection)
    return Object.freeze({ artifact, digest: digest(artifact) })
  }))
}

const bundledPublicScopes = assertPublicScopeIndex(publicScopeSource)

export function configuredPublicScopes(): readonly PublicScopeBinding[] {
  const expected = process.env.NEXUS_COCKPIT_PUBLIC_SCOPE_INDEX_SHA256?.trim()
  if (
    bundledPublicScopes.length !== 11 ||
    !expected || !/^[0-9a-f]{64}$/.test(expected) ||
    digest(publicScopeSource) !== expected
  ) {
    throw new Error('Index public final absent ou non scellé')
  }
  return bundledPublicScopes
}

export function publicScopeIndexDigest(): string {
  return digest(publicScopeSource)
}

function matchesIdentity(identity: InternalIdentity, scope: PublicScopeBinding): boolean {
  const policy = scope.artifact.target_policy
  const subject = scope.artifact.evidence_subject
  const profile = identity.pedagogical_profile
  return (
    identity.tenant === policy.tenant &&
    identity.niveau === policy.niveau &&
    identity.school_year === subject.school_year &&
    policy.roles.includes(identity.role) &&
    profile.voie === policy.voie &&
    profile.statut_enseignement === policy.statut_enseignement &&
    profile.matieres.length === 1 &&
    profile.matieres[0] === policy.matiere &&
    policy.audiences.includes(profile.audience) &&
    policy.candidates.includes(profile.candidat)
  )
}

export function findPublicScopeForIdentity(
  identity: InternalIdentity,
  index: readonly PublicScopeBinding[],
): PublicScopeBinding | null {
  if (!validateInternalIdentity(identity)) return null
  const matching = index.filter((scope) => matchesIdentity(identity, scope))
  return matching.length === 1 ? matching[0] : null
}

export function assertEnvelopeMatchesPublicScope(
  envelope: InternalIdentityEnvelope,
  index: readonly PublicScopeBinding[],
): void {
  if (!validateInternalIdentityEnvelope(envelope)) {
    throw new Error('Enveloppe publique non conforme au contrat')
  }
  const scope = findPublicScopeForIdentity(envelope.identity, index)
  if (
    scope === null ||
    envelope.sub !== envelope.identity.sub ||
    envelope.jti !== envelope.identity.jti ||
    envelope.exp > envelope.identity.exp ||
    envelope.iat > envelope.exp ||
    envelope.scope_id !== scope.artifact.scope_id ||
    envelope.scope_digest !== scope.digest ||
    envelope.allowed_collections.length !== 1 ||
    envelope.allowed_collections[0] !== scope.artifact.evidence_subject.collection
  ) {
    throw new Error('Enveloppe hors du scope public final')
  }
}
