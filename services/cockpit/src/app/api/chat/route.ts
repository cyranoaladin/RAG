import { NextResponse } from 'next/server'

import type { ChatPayload, ChatRequest, InternalIdentity } from '@/generated/contracts'
import { validateChatPayload, validateChatRequest, validateChatResponse } from '@/generated/validators'
import { requireBffAuth } from '@/server/bff-auth'
import { PILOT_RETRIEVAL_SCOPE } from '@/server/pilot-scope'

import { fetchEngine, isPublicLaunchReady } from '../_engine'

const MAX_COLLECTIONS_PER_REQUEST = 8

function signedProfile(
  identity: InternalIdentity,
  collections: string[],
): ChatRequest['student_profile'] {
  const requestedMatieres = collections.map((collection) =>
    PILOT_RETRIEVAL_SCOPE.subjects.find((subject) => subject.collection === collection)?.matiere,
  )
  if (!requestedMatieres.every((matiere): matiere is string => typeof matiere === 'string')) {
    throw new Error('collection hors scope')
  }
  const [primaryMatiere, ...otherMatieres] = requestedMatieres
  if (!primaryMatiere) {
    throw new Error('collection hors scope')
  }
  const profile = identity.pedagogical_profile
  return {
    niveau: identity.niveau,
    voie: profile.voie,
    matieres: [primaryMatiere, ...otherMatieres],
    statut_enseignement: profile.statut_enseignement,
    candidat: profile.candidat,
    school_year: identity.school_year,
    zone: profile.audience,
  }
}

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

  if (!await isPublicLaunchReady()) {
    return NextResponse.json({ error: 'launch_not_ready' }, { status: 503 })
  }

  const enginePayload: ChatRequest = {
    student_profile: signedProfile(authContext.identity, payload.collections),
    query: payload.query,
    collections: payload.collections,
    top_k: payload.top_k ?? 5,
    history: (payload.history ?? []).slice(-12),
    answer_max_chars: 1600,
    include_retrieval: true,
  }
  if (!validateChatRequest(enginePayload)) {
    return NextResponse.json({ error: 'invalid_request' }, { status: 400 })
  }

  try {
    const result = await fetchEngine('/chat', {
      method: 'POST',
      body: enginePayload,
      identityToken: authContext.identityToken,
    })
    if (result.status !== 200 || !validateChatResponse(result.payload)) {
      return NextResponse.json({ error: 'service_unavailable' }, { status: 503 })
    }
    return NextResponse.json(result.payload)
  } catch {
    return NextResponse.json({ error: 'service_unavailable' }, { status: 503 })
  }
}
