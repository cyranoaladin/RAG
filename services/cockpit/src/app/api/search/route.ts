import { NextResponse } from 'next/server'

import type {
  RetrievalRequest,
  RetrievalResult,
  RetrievalResponse,
  SearchPayload,
} from '@/generated/contracts'
import {
  validateRetrievalRequest,
  validateRetrievalResponse,
  validateSearchPayload,
} from '@/generated/validators'
import { requireBffAuth } from '@/server/bff-auth'
import type { BffAuthContext } from '@/server/bff-auth'
import { PILOT_RETRIEVAL_SCOPE } from '@/server/pilot-scope'

import { fetchEngine, isPublicLaunchReady } from '../_engine'

const MAX_COLLECTIONS_PER_REQUEST = 8

function buildRetrievalRequest(
  auth: BffAuthContext,
  payload: SearchPayload,
  collection: string,
): RetrievalRequest | null {
  const subject = PILOT_RETRIEVAL_SCOPE.subjects.find(
    (candidate) => candidate.collection === collection,
  )
  if (!subject || !auth.identity.pedagogical_profile.matieres.includes(subject.matiere)) {
    return null
  }
  const profile = auth.identity.pedagogical_profile
  const request: RetrievalRequest = {
    student_profile: {
      niveau: auth.identity.niveau,
      voie: profile.voie,
      matieres: [subject.matiere],
      statut_enseignement: profile.statut_enseignement,
      candidat: profile.candidat,
      school_year: auth.identity.school_year,
      zone: profile.audience,
    },
    need: {
      intent: 'context',
      query: payload.query,
    },
    retrieval: {
      k: payload.k ?? 8,
      hybrid: true,
      rerank: true,
      include_citations: true,
    },
  }
  return validateRetrievalRequest(request) ? request : null
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

  if (!await isPublicLaunchReady(authContext.identityToken)) {
    return NextResponse.json({ error: 'launch_not_ready' }, { status: 503 })
  }

  try {
    const engineRequests = payload.collections.map((collection) =>
      buildRetrievalRequest(authContext, payload, collection))
    if (engineRequests.some((engineRequest) => engineRequest === null)) {
      return NextResponse.json({ error: 'service_unavailable' }, { status: 503 })
    }
    const results = await Promise.all(
      engineRequests.map((engineRequest) => fetchEngine('/search/v2', {
        method: 'POST',
        body: engineRequest as RetrievalRequest,
        identityToken: authContext.identityToken,
      })),
    )
    if (results.some((result) => result.status !== 200)) {
      return NextResponse.json({ error: 'service_unavailable' }, { status: 503 })
    }
    if (results.some((result) => !validateRetrievalResponse(result.payload))) {
      return NextResponse.json({ error: 'invalid_upstream_response' }, { status: 502 })
    }
    const hitsByCollection = results.map(
      (result) => (result.payload as RetrievalResponse).results ?? [],
    )
    const response: RetrievalResponse = {
      results: mergeCollectionHeads(hitsByCollection, payload.k ?? 8),
      warnings: results.flatMap(
        (result) => (result.payload as RetrievalResponse).warnings ?? [],
      ),
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
