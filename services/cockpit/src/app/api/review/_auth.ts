import { NextResponse } from 'next/server'

import { requireBffAuth, type BffAuthContext } from '@/server/bff-auth'

type ReviewAuthResult =
  | { readonly ok: true; readonly context: BffAuthContext }
  | { readonly ok: false; readonly response: NextResponse }

const REVIEW_ROLES = new Set(['admin', 'reviewer'])
const REVIEW_CACHE_CONTROL = 'private, no-store, max-age=0'

export function reviewJson(body: unknown, init: ResponseInit = {}): NextResponse {
  const headers = new Headers(init.headers)
  headers.set('Cache-Control', REVIEW_CACHE_CONTROL)
  return NextResponse.json(body, { ...init, headers })
}

export async function requireReviewAuth(request: Request): Promise<ReviewAuthResult> {
  const context = await requireBffAuth(request)
  if (!context) {
    return {
      ok: false,
      response: reviewJson({ error: 'unauthorized' }, { status: 401 }),
    }
  }
  if (!REVIEW_ROLES.has(context.identity.role)) {
    return {
      ok: false,
      response: reviewJson({ error: 'forbidden' }, { status: 403 }),
    }
  }
  return { ok: true, context }
}
