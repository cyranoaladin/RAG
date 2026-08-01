import { SignJWT, decodeJwt, jwtVerify } from 'jose'

import type { InternalIdentity, InternalIdentityEnvelope } from '@/generated/contracts'
import {
  PILOT_RETRIEVAL_SCOPE,
  PILOT_RETRIEVAL_SCOPE_DIGEST,
  assertEnvelopeMatchesPilotScope,
  assertIdentityMatchesPilotScope,
} from '@/server/pilot-scope'

const DEFAULT_INTERNAL_TTL_SECONDS = 300

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000)
}

function parseInternalTokenTtl(): number {
  const raw = (process.env.COCKPIT_INTERNAL_TOKEN_TTL_SECONDS || '').trim()
  if (!raw) {
    return DEFAULT_INTERNAL_TTL_SECONDS
  }

  const value = Number(raw)
  if (!Number.isFinite(value) || value <= 0) {
    return DEFAULT_INTERNAL_TTL_SECONDS
  }

  return Math.min(Math.max(Math.floor(value), 60), 3600)
}

function requireEnv(name: string): string {
  const value = (process.env[name] || '').trim()
  if (!value) {
    throw new Error(`Configuration interne manquante: ${name}`)
  }
  return value
}

function internalSigningKey(): Uint8Array {
  const key = new TextEncoder().encode(requireEnv('NEXUS_INTERNAL_TOKEN_SECRET'))
  if (key.byteLength < 32) {
    throw new Error('Configuration interne invalide: NEXUS_INTERNAL_TOKEN_SECRET')
  }
  return key
}

function externalAudience(): string {
  const audience = requireEnv('NEXUS_SSO_AUDIENCE')
  if (audience.includes(',')) {
    throw new Error('Configuration interne invalide: NEXUS_SSO_AUDIENCE')
  }
  return audience
}

function assertExternalParties(identity: InternalIdentity): void {
  const issuer = requireEnv('NEXUS_SSO_ISSUER')
  if (identity.iss !== issuer || identity.aud !== externalAudience()) {
    throw new Error('Identité interne incohérente avec la politique SSO')
  }
}

export async function mintInternalIdentityToken(
  identity: InternalIdentity,
): Promise<string> {
  assertIdentityMatchesPilotScope(identity)
  assertExternalParties(identity)
  const issuedAt = nowSeconds()
  const ttl = parseInternalTokenTtl()
  const exp = Math.min(identity.exp, issuedAt + ttl)
  if (exp <= issuedAt) {
    throw new Error('Identité interne expirée')
  }

  const allowedCollections = PILOT_RETRIEVAL_SCOPE.subjects
    .map((subject) => subject.collection) as InternalIdentityEnvelope['allowed_collections']
  const envelope: InternalIdentityEnvelope = {
    protocol_version: '1',
    iss: requireEnv('NEXUS_INTERNAL_TOKEN_ISSUER'),
    aud: requireEnv('NEXUS_INTERNAL_TOKEN_AUDIENCE'),
    sub: identity.sub,
    jti: identity.jti,
    iat: issuedAt,
    exp,
    identity,
    scope_id: PILOT_RETRIEVAL_SCOPE.scope_id,
    scope_digest: PILOT_RETRIEVAL_SCOPE_DIGEST,
    allowed_collections: allowedCollections,
  }
  assertEnvelopeMatchesPilotScope(envelope)

  return new SignJWT({ ...envelope })
    .setProtectedHeader({ alg: 'HS256', typ: 'JWT' })
    .sign(internalSigningKey())
}

async function verifySignedEnvelope(
  token: string,
  currentDate: Date,
): Promise<InternalIdentityEnvelope> {
  if (!token.trim()) {
    throw new Error('Jeton interne absent')
  }
  let payload: unknown
  try {
    const result = await jwtVerify(token, internalSigningKey(), {
      algorithms: ['HS256'],
      issuer: requireEnv('NEXUS_INTERNAL_TOKEN_ISSUER'),
      audience: requireEnv('NEXUS_INTERNAL_TOKEN_AUDIENCE'),
      clockTolerance: '5s',
      currentDate,
    })
    payload = result.payload
  } catch (error) {
    throw new Error('Jeton interne invalide ou expiré', { cause: error })
  }
  const envelope = payload as InternalIdentityEnvelope
  assertEnvelopeMatchesPilotScope(envelope)
  assertExternalParties(envelope.identity)
  return envelope
}

function assertTransportWindow(envelope: InternalIdentityEnvelope): void {
  if (
    envelope.iat > nowSeconds() + 5 ||
    envelope.exp <= envelope.iat ||
    envelope.exp - envelope.iat > parseInternalTokenTtl() ||
    envelope.identity.exp <= nowSeconds()
  ) {
    throw new Error('Jeton interne hors fenêtre temporelle')
  }
}

export async function verifyInternalIdentityToken(token: string): Promise<InternalIdentityEnvelope> {
  const envelope = await verifySignedEnvelope(token, new Date())
  assertTransportWindow(envelope)
  return envelope
}

export async function parseInternalIdentityToken(token: string): Promise<string> {
  return (await verifyInternalIdentityToken(token)).sub
}

export async function rotateInternalIdentityToken(token: string): Promise<string> {
  let issuedAt: number
  try {
    const decoded = decodeJwt(token)
    if (typeof decoded.iat !== 'number' || !Number.isSafeInteger(decoded.iat)) {
      throw new Error('iat invalide')
    }
    issuedAt = decoded.iat
  } catch (error) {
    throw new Error('Jeton interne invalide ou expiré', { cause: error })
  }
  const envelope = await verifySignedEnvelope(token, new Date(issuedAt * 1000))
  assertTransportWindow(envelope)
  return mintInternalIdentityToken(envelope.identity)
}
