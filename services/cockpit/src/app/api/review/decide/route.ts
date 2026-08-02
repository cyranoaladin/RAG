import type { NextResponse } from 'next/server'

import type {
  ReviewDecisionPayload,
  ReviewDecisionRequest,
} from '@/generated/contracts'
import {
  validateReviewDecisionPayload,
  validateReviewDecisionRequest,
  validateReviewDecisionResponse,
} from '@/generated/validators'

import { fetchEngine } from '../../_engine'
import { requireReviewAuth, reviewJson } from '../_auth'

function invalidRequest(): NextResponse {
  return reviewJson({ error: 'invalid_request' }, { status: 400 })
}

function unavailable(): NextResponse {
  return reviewJson({ error: 'review_unavailable' }, { status: 503 })
}

export async function POST(request: Request): Promise<NextResponse> {
  const auth = await requireReviewAuth(request)
  if (!auth.ok) return auth.response

  let payload: ReviewDecisionPayload
  try {
    const body: unknown = await request.json()
    if (!validateReviewDecisionPayload(body)) return invalidRequest()
    payload = body
  } catch {
    return invalidRequest()
  }

  if (
    payload.collection !== undefined
    && payload.collection !== null
    && !auth.context.allowedCollections.includes(payload.collection)
  ) {
    return reviewJson({ error: 'forbidden' }, { status: 403 })
  }

  const outbound: ReviewDecisionRequest = {
    ...payload,
    tenant: auth.context.identity.tenant,
  }
  if (!validateReviewDecisionRequest(outbound)) return invalidRequest()

  try {
    const result = await fetchEngine('/review/v2/decide', {
      method: 'POST',
      identityToken: auth.context.identityToken,
      body: outbound,
    })
    if (result.status === 404) {
      return reviewJson({ error: 'review_target_unavailable' }, { status: 404 })
    }
    if (result.status !== 200 || !validateReviewDecisionResponse(result.payload)) {
      return unavailable()
    }
    if (
      result.payload.target_id !== payload.target_id
      || result.payload.target_type !== (payload.target_type ?? 'doc')
      || result.payload.decision !== payload.decision
    ) {
      return unavailable()
    }
    return reviewJson(result.payload)
  } catch {
    return unavailable()
  }
}
