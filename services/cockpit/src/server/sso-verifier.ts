import {
  type JWTPayload,
  createRemoteJWKSet,
  jwtVerify,
} from 'jose'

import {
  assertTenantBoundary,
  clearRevocationStoreForTests,
  isRevoked,
} from '@/server/revocation-store'
import { consumeOnce } from '@/server/replay-store'
import { clearReplayStoreForTests } from '@/server/replay-store'
import { validateInternalIdentity } from '@/generated/validators'
import type { InternalIdentity } from '@/generated/contracts'

interface SsoProfile {
  voie: InternalIdentity['pedagogical_profile']['voie']
  matieres: InternalIdentity['pedagogical_profile']['matieres']
  statut_enseignement: InternalIdentity['pedagogical_profile']['statut_enseignement']
  candidat: InternalIdentity['pedagogical_profile']['candidat']
  audience: InternalIdentity['pedagogical_profile']['audience']
}

type AllowedRole = InternalIdentity['role']
const ALLOWED_ROLES = new Set<AllowedRole>([
  'student',
  'teacher',
  'admin',
  'ingest_agent',
  'review_agent',
])

function requireEnv(name: string): string {
  const value = (process.env[name] || '').trim()
  if (!value) {
    throw new Error(`Configuration SSO manquante: ${name}`)
  }

  return value
}

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000)
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim().length > 0 ? value : null
}

function normalizeAudience(payload: JWTPayload): string {
  if (typeof payload.aud === 'string') {
    return payload.aud
  }

  if (Array.isArray(payload.aud) && payload.aud.every((entry) => typeof entry === 'string')) {
    return payload.aud[0] ?? ''
  }

  return ''
}

function asPedagogicalProfile(payload: JWTPayload): SsoProfile {
  const rawProfile =
    (payload.pedagogical_profile as Record<string, unknown> | null | undefined) ||
    (payload.pedagogicalProfile as Record<string, unknown> | null | undefined) ||
    {}

  const voie = asString(rawProfile.voie)
  const statutEnseignement = asString(rawProfile.statut_enseignement)
  const audience = asString(rawProfile.audience)
  const candidat = asString(rawProfile.candidat)
  const rawMatieres = Array.isArray(rawProfile.matieres)
    ? rawProfile.matieres
    : []

  const matieres = rawMatieres
    .map((value) => asString(value))
    .filter((value): value is string => value !== null)
    .filter((value, index, all) => all.indexOf(value) === index)


  if (!voie) {
    throw new Error('claim Nexus invalide: pedagogical_profile.voie manquant')
  }
  if (!statutEnseignement) {
    throw new Error('claim Nexus invalide: pedagogical_profile.statut_enseignement manquant')
  }
  if (!candidat) {
    throw new Error('claim Nexus invalide: pedagogical_profile.candidat manquant')
  }
  if (!audience) {
    throw new Error('claim Nexus invalide: pedagogical_profile.audience manquant')
  }
  if (matieres.length < 1) {
    throw new Error('claim Nexus invalide: pedagogical_profile.matieres vide')
  }

  return {
    voie: voie as SsoProfile['voie'],
    matieres: matieres as SsoProfile['matieres'],
    statut_enseignement: statutEnseignement as SsoProfile['statut_enseignement'],
    candidat: candidat as SsoProfile['candidat'],
    audience: audience as SsoProfile['audience'],
  }
}

function toInternalIdentity(payload: JWTPayload): InternalIdentity {
  const sub = asString(payload.sub)
  if (!sub) {
    throw new Error('claim Nexus invalide: sub manquant')
  }

  const aud = normalizeAudience(payload)
  const iss = asString(payload.iss)
  const jti = asString((payload as { jti?: unknown }).jti)
  const tenant = asString((payload as { tenant?: unknown }).tenant) || asString((payload as { tenant_id?: unknown }).tenant_id)
  const niveau = asString((payload as { niveau?: unknown }).niveau)
  const role = asString((payload as { role?: unknown }).role) as AllowedRole | null
  const expRaw = (payload as { exp?: number }).exp

  if (!iss) {
    throw new Error('claim Nexus invalide: iss manquant')
  }
  if (!aud) {
    throw new Error('claim Nexus invalide: aud manquant')
  }
  if (!jti) {
    throw new Error('claim Nexus invalide: jti manquant')
  }
  if (!tenant) {
    throw new Error('claim Nexus invalide: tenant manquant')
  }
  if (!niveau) {
    throw new Error('claim Nexus invalide: niveau manquant')
  }
  if (!role || !ALLOWED_ROLES.has(role)) {
    throw new Error('claim Nexus invalide: role non autorisé')
  }
  if (typeof expRaw !== 'number' || !Number.isFinite(expRaw)) {
    throw new Error('claim Nexus invalide: exp invalide')
  }
  const exp = Math.floor(expRaw)
  if (exp <= nowSeconds()) {
    throw new Error('claim Nexus invalide: token expiré')
  }

  const pedagogical_profile = asPedagogicalProfile(payload)
  const identity: InternalIdentity = {
    aud,
    exp,
    iss,
    jti,
    tenant,
    niveau: niveau as InternalIdentity['niveau'],
    role,
    sub,
    pedagogical_profile,
  }

  if (!validateInternalIdentity(identity)) {
    throw new Error('identité interne non conforme au contrat')
  }

  return identity
}

function resolveKey(): ReturnType<typeof createRemoteJWKSet> | Uint8Array {
  const secret = process.env.NEXUS_SSO_SHARED_SECRET
  if (secret) {
    return new TextEncoder().encode(secret)
  }

  const jwksUrl = process.env.NEXUS_SSO_JWKS_URL
  if (!jwksUrl) {
    throw new Error('Configuration SSO manquante: NEXUS_SSO_JWKS_URL ou NEXUS_SSO_SHARED_SECRET')
  }

  return createRemoteJWKSet(new URL(jwksUrl))
}

function resolveAudiences(): string[] {
  const configured = requireEnv('NEXUS_SSO_AUDIENCE')
  return configured
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean)
}

export async function verifyNexusToken(rawToken: string): Promise<InternalIdentity> {
  if (!rawToken || rawToken.trim().length === 0) {
    throw new Error('Jeton SSO manquant')
  }

  const key = resolveKey()
  const issuer = requireEnv('NEXUS_SSO_ISSUER')
  const audiences = resolveAudiences()

  let payload: JWTPayload
  try {
    const result = await (async () => {
      if (key instanceof Uint8Array) {
        return jwtVerify(rawToken, key, {
          issuer,
          audience: audiences,
          clockTolerance: '5s',
        })
      }

      return jwtVerify(rawToken, key, {
        issuer,
        audience: audiences,
        clockTolerance: '5s',
      })
    })()
    payload = result.payload
  } catch (error) {
    throw new Error('Token SSO invalide ou expiré', { cause: error })
  }

  const identity = toInternalIdentity(payload)

  if (await isRevoked(identity.sub, identity.tenant)) {
    throw new Error('session révoquée')
  }

  await assertTenantBoundary(identity.sub, identity.tenant)
  await consumeOnce(identity.jti, identity.exp, identity.tenant, identity.sub)

  return identity
}

export async function clearVerifierStoresForTests(): Promise<void> {
  await clearRevocationStoreForTests()
  await clearReplayStoreForTests()
}
