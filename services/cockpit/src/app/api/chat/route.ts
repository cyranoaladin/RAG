import { NextResponse } from 'next/server'

import type { ChatPayload } from '@/generated/contracts'
import { validateChatPayload } from '@/generated/validators'
import { requireBffAuth } from '@/server/bff-auth'

const MAX_COLLECTIONS_PER_REQUEST = 8

export async function POST(request: Request) {
  const authContext = await requireBffAuth(request)
  if (!authContext) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }

  let payload: ChatPayload
  try {
    const body: unknown = await request.json()
    if (!validateChatPayload(body) || body.collections.length > MAX_COLLECTIONS_PER_REQUEST) {
      return NextResponse.json({ error: 'invalid_request' }, { status: 400 })
    }
    payload = body
  } catch {
    return NextResponse.json({ error: 'invalid_request' }, { status: 400 })
  }

  const allowedCollections = new Set(authContext.allowedCollections)
  if (!payload.collections.every((collection) => allowedCollections.has(collection))) {
    return NextResponse.json({ error: 'forbidden_collection' }, { status: 403 })
  }

  // ADR-0012/0037: answer_generation_allowed=false pour cette release.
  return NextResponse.json({ error: 'answer_generation_disabled' }, { status: 503 })
}
