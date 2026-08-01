import NextAuth, { type AuthOptions, type Session, getServerSession } from 'next-auth'
import type { JWT } from 'next-auth/jwt'
import Credentials from 'next-auth/providers/credentials'

import {
  mintInternalIdentityToken,
  rotateInternalIdentityToken,
  verifyInternalIdentityToken,
} from '@/server/internal-token'
import { AUTH_SESSION_MAX_AGE_SECONDS } from '@/server/auth-policy'
import { revokeSession } from '@/server/revocation-store'
import { verifyNexusToken } from '@/server/sso-verifier'
import { shouldRotate } from '@/server/session-rotation'

interface AuthenticatedToken extends JWT {
  internalAccessToken?: string
  identityRotatedAt?: number
}

export type AuthenticatedSession = Session

interface AuthenticatedUser {
  id: string
  name: string
  internalAccessToken: string
  internalTokenIssuedAt: number
  email?: string | null
}

export const authOptions: AuthOptions = {
  providers: [
    Credentials({
      name: 'nexus',
      credentials: {
        token: {
          label: 'Jeton Nexus',
          type: 'text',
          placeholder: 'eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9...',
        },
      },
      async authorize(credentials) {
        const token = credentials?.token
        if (!token) {
          return null
        }

        const identity = await verifyNexusToken(token)
        const internalAccessToken = await mintInternalIdentityToken(identity)
        const displayName = `Nexus ${identity.sub.slice(0, 8)}`

        return {
          id: identity.sub,
          name: displayName,
          email: null,
          internalAccessToken,
          internalTokenIssuedAt: Date.now(),
        } satisfies AuthenticatedUser
      },
    }),
  ],
  session: {
    strategy: 'jwt',
    maxAge: AUTH_SESSION_MAX_AGE_SECONDS,
  },
  events: {
    async signOut(message) {
      if (!('token' in message)) return
      const sessionToken = message.token as AuthenticatedToken
      if (typeof sessionToken.internalAccessToken !== 'string') return
      let internalToken = sessionToken.internalAccessToken
      let envelope
      try {
        envelope = await verifyInternalIdentityToken(internalToken)
      } catch {
        internalToken = await rotateInternalIdentityToken(internalToken)
        envelope = await verifyInternalIdentityToken(internalToken)
      }
      await revokeSession(
        envelope.identity.jti,
        envelope.identity.sub,
        envelope.identity.tenant,
      )
    },
  },
  callbacks: {
    async jwt({ token, user }) {
      const nextToken = token as AuthenticatedToken
      if (user) {
        const nextUser = user as AuthenticatedUser
        nextToken.internalAccessToken = nextUser.internalAccessToken
        nextToken.identityRotatedAt = nextUser.internalTokenIssuedAt
      }

      if (
        nextToken.internalAccessToken &&
        typeof nextToken.identityRotatedAt === 'number' &&
        shouldRotate(nextToken.identityRotatedAt)
      ) {
        nextToken.internalAccessToken = await rotateInternalIdentityToken(nextToken.internalAccessToken)
        nextToken.identityRotatedAt = Date.now()
      }

      return nextToken
    },
    async session({ session, token }) {
      const nextSession = session as AuthenticatedSession
      const nextToken = token as AuthenticatedToken

      if (nextToken.sub) {
        nextSession.user = nextSession.user || { name: null, email: null, image: null }
        nextSession.user.name = nextSession.user.name || `Nexus ${nextToken.sub.slice(0, 8)}`
      }

      return nextSession
    },
  },
  pages: {
    signIn: '/api/auth/signin',
    error: '/api/auth/error',
  },
  secret: process.env.NEXTAUTH_SECRET,
}

const authHandler = NextAuth(authOptions)

export const auth = (): Promise<AuthenticatedSession | null> =>
  getServerSession(authOptions) as Promise<AuthenticatedSession | null>
export const { GET, POST } = authHandler
