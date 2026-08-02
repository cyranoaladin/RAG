import type { NextResponse } from 'next/server'

import type { ReviewQueuePayload } from '@/generated/contracts'
import {
  validateReviewQueuePayload,
  validateReviewQueueResponse,
} from '@/generated/validators'

import { fetchEngine } from '../../_engine'
import { requireReviewAuth, reviewJson } from '../_auth'

const QUEUE_QUERY_KEYS = new Set(['collection', 'limit', 'offset'])
type BrowserReviewQueuePayload = ReviewQueuePayload & { collection?: string }

function parseCanonicalInteger(value: string): number | null {
  if (!/^(0|[1-9]\d*)$/.test(value)) return null
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) ? parsed : null
}

function parseQueuePayload(request: Request): BrowserReviewQueuePayload | null {
  const searchParams = new URL(request.url).searchParams
  for (const key of searchParams.keys()) {
    if (!QUEUE_QUERY_KEYS.has(key) || searchParams.getAll(key).length !== 1) {
      return null
    }
  }

  const payload: BrowserReviewQueuePayload = {}
  if (searchParams.has('collection')) {
    payload.collection = searchParams.get('collection') ?? undefined
  }
  if (searchParams.has('limit')) {
    const limit = parseCanonicalInteger(searchParams.get('limit') ?? '')
    if (limit === null) return null
    payload.limit = limit
  }
  if (searchParams.has('offset')) {
    const offset = parseCanonicalInteger(searchParams.get('offset') ?? '')
    if (offset === null) return null
    payload.offset = offset
  }

  return validateReviewQueuePayload(payload) ? payload : null
}

function unavailable(): NextResponse {
  return reviewJson({ error: 'review_unavailable' }, { status: 503 })
}

export async function GET(request: Request): Promise<NextResponse> {
  const auth = await requireReviewAuth(request)
  if (!auth.ok) return auth.response

  const payload = parseQueuePayload(request)
  if (!payload) {
    return reviewJson({ error: 'invalid_request' }, { status: 400 })
  }
  if (
    payload.collection !== undefined
    && payload.collection !== null
    && !auth.context.allowedCollections.includes(payload.collection)
  ) {
    return reviewJson({ error: 'forbidden' }, { status: 403 })
  }

  try {
    const result = await fetchEngine('/review/v2/queue', {
      method: 'GET',
      identityToken: auth.context.identityToken,
      query: payload,
    })
    if (result.status !== 200 || !validateReviewQueueResponse(result.payload)) {
      return unavailable()
    }
    return reviewJson(result.payload)
  } catch {
    return unavailable()
  }
}
