import { NextResponse } from 'next/server'

import type { ChatPayload, ChatRequest } from '@/generated/contracts'
import { validateChatPayload, validateChatRequest, validateChatResponse } from '@/generated/validators'

import { fetchEngine, isPublicLaunchReady } from '../_engine'

const MAX_COLLECTIONS_PER_REQUEST = 8

function publicProfile(collections: string[]): ChatRequest['student_profile'] {
  const [primaryMatiere, ...otherMatieres] = collections
  if (!primaryMatiere) {
    throw new Error('collections must not be empty')
  }
  return {
    niveau: 'terminale',
    voie: 'generale',
    matieres: [primaryMatiere, ...otherMatieres],
    statut_enseignement: 'specialite',
    candidat: 'individuel',
    school_year: '2026-2027',
    zone: 'public',
  }
}

export async function POST(request: Request) {
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

  if (!await isPublicLaunchReady()) {
    return NextResponse.json({ error: 'launch_not_ready' }, { status: 503 })
  }

  const enginePayload: ChatRequest = {
    student_profile: publicProfile(payload.collections),
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
    const result = await fetchEngine('/chat', { method: 'POST', body: enginePayload })
    if (result.status !== 200 || !validateChatResponse(result.payload)) {
      return NextResponse.json({ error: 'service_unavailable' }, { status: 503 })
    }
    return NextResponse.json(result.payload)
  } catch {
    return NextResponse.json({ error: 'service_unavailable' }, { status: 503 })
  }
}
