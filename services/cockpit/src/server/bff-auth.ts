import type { JWT } from 'next-auth/jwt'
import { getToken } from 'next-auth/jwt'
import type { NextRequest } from 'next/server'

import type { InternalIdentity } from '@/generated/contracts'
import { rotateInternalIdentityToken, verifyInternalIdentityToken } from '@/server/internal-token'
import { PILOT_RETRIEVAL_SCOPE } from '@/server/pilot-scope'
import { isRevoked } from '@/server/revocation-store'

interface ServerSessionToken extends JWT {
  internalAccessToken?: unknown
}

export interface BffAuthContext {
  readonly allowedCollections: readonly string[]
  readonly identity: InternalIdentity
  readonly identityToken: string
}

export type SessionTokenReader = (request: Request) => Promise<JWT | null>

async function readEncryptedSessionToken(request: Request): Promise<JWT | null> {
  const secret = (process.env.NEXTAUTH_SECRET || '').trim()
  if (!secret) return null
  return getToken({ req: request as NextRequest, secret })
}

export async function requireBffAuth(
  request: Request,
  readToken: SessionTokenReader = readEncryptedSessionToken,
): Promise<BffAuthContext | null> {
  try {
    const sessionToken = await readToken(request) as ServerSessionToken | null
    const identityToken = sessionToken?.internalAccessToken
    if (typeof sessionToken?.sub !== 'string' || typeof identityToken !== 'string') {
      return null
    }

    let envelope
    let freshIdentityToken = identityToken
    try {
      envelope = await verifyInternalIdentityToken(identityToken)
    } catch {
      freshIdentityToken = await rotateInternalIdentityToken(identityToken)
      envelope = await verifyInternalIdentityToken(freshIdentityToken)
    }
    if (sessionToken.sub !== envelope.sub) return null
    if (await isRevoked(
      envelope.identity.jti,
      envelope.identity.sub,
      envelope.identity.tenant,
    )) return null

    const signedMatieres = new Set(envelope.identity.pedagogical_profile.matieres)
    const allowedCollections = PILOT_RETRIEVAL_SCOPE.subjects
      .filter((subject) => signedMatieres.has(subject.matiere))
      .map((subject) => subject.collection)
    if (allowedCollections.length === 0) return null

    return {
      allowedCollections,
      identity: envelope.identity,
      identityToken: freshIdentityToken,
    }
  } catch {
    return null
  }
}
