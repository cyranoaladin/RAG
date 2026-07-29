import NextAuth, { type AuthOptions, type Session, getServerSession } from 'next-auth'
import type { JWT } from 'next-auth/jwt'
import Credentials from 'next-auth/providers/credentials'

import type { InternalIdentity } from '@/generated/contracts'
import { mintInternalIdentityToken } from '@/server/internal-token'
import { verifyNexusToken } from '@/server/sso-verifier'
import { shouldRotate } from '@/server/session-rotation'

interface AuthenticatedToken extends JWT {
  identity?: InternalIdentity
  internalAccessToken?: string
  identityRotatedAt?: number
}

export interface AuthenticatedSession extends Session {
  internalAccessToken?: string
  internalIdentity?: InternalIdentity
  internalIdentityRotatedAt?: number
}

interface AuthenticatedUser {
  id: string
  name: string
  internalIdentity: InternalIdentity
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
          internalIdentity: identity,
          internalAccessToken,
          internalTokenIssuedAt: Date.now(),
        } satisfies AuthenticatedUser
      },
    }),
  ],
  session: {
    strategy: 'jwt',
    maxAge: 3600,
  },
  callbacks: {
    async jwt({ token, user }) {
      const nextToken = token as AuthenticatedToken
      if (user) {
        const nextUser = user as AuthenticatedUser
        nextToken.identity = nextUser.internalIdentity
        nextToken.internalAccessToken = nextUser.internalAccessToken
        nextToken.identityRotatedAt = Date.now()
      }

      if (
        nextToken.identity &&
        nextToken.internalAccessToken &&
        typeof nextToken.identityRotatedAt === 'number' &&
        shouldRotate(nextToken.identityRotatedAt)
      ) {
        nextToken.internalAccessToken = await mintInternalIdentityToken(nextToken.identity)
        nextToken.identityRotatedAt = Date.now()
      }

      return nextToken
    },
    async session({ session, token }) {
      const nextSession = session as AuthenticatedSession
      const nextToken = token as AuthenticatedToken

      if (nextToken.identity?.sub) {
        nextSession.user = nextSession.user || { name: null, email: null, image: null }
        nextSession.user.name = nextSession.user.name || nextToken.identity.sub
      }

      nextSession.internalIdentity = nextToken.identity
      nextSession.internalAccessToken = nextToken.internalAccessToken
      nextSession.internalIdentityRotatedAt = nextToken.identityRotatedAt

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
