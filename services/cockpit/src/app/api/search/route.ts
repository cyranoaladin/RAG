import { NextResponse } from 'next/server'

import type { RetrievalResult, RetrievalResponse, SearchPayload } from '@/generated/contracts'
import { validateRetrievalResponse, validateSearchPayload } from '@/generated/validators'
import { requireBffAuth } from '@/server/bff-auth'

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
  page?: unknown
  preview?: unknown
  dense_score?: unknown
  rerank_score?: unknown
  dense_sim?: unknown
  lexical_score?: unknown
  rrf_score?: unknown
  mmr_score?: unknown
  score_final?: unknown
}

function finiteNumberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function toRetrievalResult(hit: EngineSearchHit, collection: string): RetrievalResult | null {
  if (
    typeof hit.chunk_id !== 'string' ||
    typeof hit.doc_id !== 'string' ||
    typeof hit.preview !== 'string' ||
    typeof hit.score_final !== 'number' ||
    !Number.isFinite(hit.score_final) ||
    hit.score_final < 0 ||
    hit.score_final > 1 ||
    !(hit.page === null || (Number.isInteger(hit.page) && Number(hit.page) >= 1)) ||
    typeof hit.source_label !== 'string' ||
    typeof hit.source_uri !== 'string' ||
    typeof hit.rights !== 'string'
  ) {
    return null
  }
  return {
    chunk_id: hit.chunk_id,
    doc_id: hit.doc_id,
    score: hit.score_final,
    title: hit.source_label || null,
    excerpt: hit.preview,
    citation: hit.source_label && hit.source_uri && hit.rights
      ? {
          source_label: hit.source_label,
          source_uri: hit.source_uri,
          rights: hit.rights,
          page: hit.page as number | null,
        }
      : null,
    metadata: {
      collection,
      type_doc: typeof hit.type_doc === 'string' ? hit.type_doc : 'unknown',
      review_status: typeof hit.review_status === 'string' ? hit.review_status : 'unknown',
      dense_score: finiteNumberOrNull(hit.dense_score),
      dense_sim: finiteNumberOrNull(hit.dense_sim),
      lexical_score: finiteNumberOrNull(hit.lexical_score),
      rrf_score: finiteNumberOrNull(hit.rrf_score),
      rerank_score: finiteNumberOrNull(hit.rerank_score),
      mmr_score: finiteNumberOrNull(hit.mmr_score),
      score_final: hit.score_final,
    },
  }
}

/**
 * Merge déjà-diversified MMR sequences without sorting inside any collection.
 * Only current heads compete; ties retain the requested collection order.
 */
function mergeCollectionHeads(
  collections: RetrievalResult[][],
  limit: number,
): RetrievalResult[] {
  if (collections.length === 1) {
    return collections[0].slice(0, limit)
  }

  const positions = collections.map(() => 0)
  const merged: RetrievalResult[] = []
  while (merged.length < limit) {
    let selectedCollection = -1
    for (let index = 0; index < collections.length; index += 1) {
      const head = collections[index][positions[index]]
      if (head === undefined) {
        continue
      }
      const selected = selectedCollection === -1
        ? undefined
        : collections[selectedCollection][positions[selectedCollection]]
      if (selected === undefined || head.score > selected.score) {
        selectedCollection = index
      }
    }
    if (selectedCollection === -1) {
      break
    }
    merged.push(collections[selectedCollection][positions[selectedCollection]])
    positions[selectedCollection] += 1
  }
  return merged
}

export async function POST(request: Request) {
  const authContext = await requireBffAuth(request)
  if (!authContext) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }

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

  const allowedCollections = new Set(authContext.allowedCollections)
  if (!payload.collections.every((collection) => allowedCollections.has(collection))) {
    return NextResponse.json({ error: 'forbidden_collection' }, { status: 403 })
  }

  if (!await isPublicLaunchReady()) {
    return NextResponse.json({ error: 'launch_not_ready' }, { status: 503 })
  }

  try {
    const results = await Promise.all(
      payload.collections.map((collection) => fetchEngine('/search/v2', {
        method: 'POST',
        body: { q: payload.query, collection, k: payload.k ?? 8 },
        identityToken: authContext.identityToken,
      })),
    )
    if (results.some((result) => result.status !== 200)) {
      return NextResponse.json({ error: 'service_unavailable' }, { status: 503 })
    }
    const hitsByCollection = results.map((result, index) => {
      const body = result.payload as { hits?: unknown }
      if (!Array.isArray(body?.hits)) {
        return []
      }
      return body.hits
        .map((hit) => toRetrievalResult(hit as EngineSearchHit, payload.collections[index]))
        .filter((hit): hit is RetrievalResult => hit !== null)
    })
    const response: RetrievalResponse = {
      results: mergeCollectionHeads(hitsByCollection, payload.k ?? 8),
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
