import { NextResponse } from 'next/server'

import type { RetrievalResult, RetrievalResponse, SearchPayload } from '@/generated/contracts'
import { validateRetrievalResponse, validateSearchPayload } from '@/generated/validators'

import { fetchEngine, isPublicLaunchReady } from '../_engine'

const MAX_COLLECTIONS_PER_REQUEST = 8

type EngineSearchHit = {
  chunk_id?: unknown
  doc_id?: unknown
  source_label?: unknown
  source_uri?: unknown
  rights?: unknown
  type_doc?: unknown
  review_status?: unknown
  preview?: unknown
  rerank_score?: unknown
  dense_sim?: unknown
}

function toRetrievalResult(hit: EngineSearchHit, collection: string): RetrievalResult | null {
  if (
    typeof hit.chunk_id !== 'string' ||
    typeof hit.doc_id !== 'string' ||
    typeof hit.preview !== 'string' ||
    typeof hit.rerank_score !== 'number' ||
    typeof hit.source_label !== 'string' ||
    typeof hit.source_uri !== 'string' ||
    typeof hit.rights !== 'string'
  ) {
    return null
  }
  return {
    chunk_id: hit.chunk_id,
    doc_id: hit.doc_id,
    score: Math.max(0, hit.rerank_score),
    title: hit.source_label || null,
    excerpt: hit.preview,
    citation: hit.source_label && hit.source_uri && hit.rights
      ? { source_label: hit.source_label, source_uri: hit.source_uri, rights: hit.rights }
      : null,
    metadata: {
      collection,
      type_doc: typeof hit.type_doc === 'string' ? hit.type_doc : 'unknown',
      review_status: typeof hit.review_status === 'string' ? hit.review_status : 'unknown',
      dense_sim: typeof hit.dense_sim === 'number' ? hit.dense_sim : null,
    },
  }
}

export async function POST(request: Request) {
  let payload: SearchPayload
  try {
    const body: unknown = await request.json()
    if (!validateSearchPayload(body) || body.collections.length > MAX_COLLECTIONS_PER_REQUEST) {
      return NextResponse.json({ error: 'invalid_request' }, { status: 400 })
    }
    payload = body
  } catch {
    return NextResponse.json({ error: 'invalid_request' }, { status: 400 })
  }

  if (!await isPublicLaunchReady()) {
    return NextResponse.json({ error: 'launch_not_ready' }, { status: 503 })
  }

  try {
    const results = await Promise.all(
      payload.collections.map((collection) => fetchEngine('/search/v2', {
        method: 'POST',
        body: { q: payload.query, collection, k: payload.k ?? 8 },
      })),
    )
    if (results.some((result) => result.status !== 200)) {
      return NextResponse.json({ error: 'service_unavailable' }, { status: 503 })
    }
    const hits = results.flatMap((result, index) => {
      const body = result.payload as { hits?: unknown }
      if (!Array.isArray(body?.hits)) {
        return []
      }
      return body.hits
        .map((hit) => toRetrievalResult(hit as EngineSearchHit, payload.collections[index]))
        .filter((hit): hit is RetrievalResult => hit !== null)
    })
    const response: RetrievalResponse = {
      results: hits.sort((left, right) => right.score - left.score).slice(0, payload.k ?? 8),
      warnings: [],
      filters_applied: { collections: payload.collections },
    }
    if (!validateRetrievalResponse(response)) {
      return NextResponse.json({ error: 'invalid_upstream_response' }, { status: 502 })
    }
    return NextResponse.json(response)
  } catch {
    return NextResponse.json({ error: 'service_unavailable' }, { status: 503 })
  }
}
