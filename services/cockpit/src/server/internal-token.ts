import { SignJWT, type JWTPayload, decodeJwt } from 'jose'

import type { InternalIdentity } from '@/generated/contracts'

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

function internalSigningKey(): Uint8Array {
  const secret = process.env.COCKPIT_INTERNAL_TOKEN_SECRET || process.env.NEXUS_INTERNAL_TOKEN_SECRET
  if (!secret) {
    throw new Error('Configuration interne manquante: COCKPIT_INTERNAL_TOKEN_SECRET')
  }

  return new TextEncoder().encode(secret)
}

export async function mintInternalIdentityToken(
  identity: InternalIdentity,
): Promise<string> {
  const issuedAt = nowSeconds()
  const ttl = parseInternalTokenTtl()
  const exp = Math.min(identity.exp, issuedAt + ttl)

  const tokenClaims: JWTPayload = {
    ...identity,
    aud: identity.aud,
    iss: identity.iss,
    exp,
    iat: issuedAt,
  }

  return new SignJWT(tokenClaims)
    .setProtectedHeader({ alg: 'HS256', typ: 'JWT' })
    .setExpirationTime(exp)
    .setIssuedAt(issuedAt)
    .sign(internalSigningKey())
}

export async function parseInternalIdentityToken(token: string): Promise<string> {
  if (!token) {
    throw new Error('Jeton interne absent')
  }

  const payload = decodeJwt(token)
  if (!payload?.iss || !payload.aud || !payload.sub) {
    throw new Error('Jeton interne incomplet')
  }

  return payload.sub
}
