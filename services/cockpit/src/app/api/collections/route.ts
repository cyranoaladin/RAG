import { NextResponse } from 'next/server'

import { requireBffAuth } from '@/server/bff-auth'
import type { RagCollection } from '@/types/ui'

import { fetchEngine } from '../_engine'

type EngineReadinessCollection = {
  name?: unknown
  ready?: unknown
}

type EngineReadiness = {
  launch_ready?: unknown
  total_collections?: unknown
  ready_collections?: unknown
  blockers?: unknown
  collections?: unknown
}

function fallback() {
  return {
    items: [] as RagCollection[],
    live: false,
    launchReady: false,
    totalCollections: 0,
    readyCollections: 0,
    blockers: ['validation de lancement indisponible'],
  }
}

function mapCatalogue(
  payload: unknown,
  readyMap: Map<string, boolean>,
): RagCollection[] | null {
  const catalogue = payload as EngineCatalogue
  if (!Array.isArray(catalogue?.collections)) {
    return null
  }
  const mapped = catalogue.collections.map((value) => {
    const entry = value as Record<string, unknown>
    if (
      typeof entry.name !== 'string' ||
      typeof entry.domain !== 'string' ||
      typeof entry.instanciee !== 'boolean'
    ) {
      return null
    }
    return {
      name: entry.name,
      matiere: typeof entry.matiere === 'string' ? entry.matiere : null,
      niveau: typeof entry.niveau === 'string' ? entry.niveau : null,
      voie: typeof entry.voie === 'string' ? entry.voie : null,
      statut: typeof entry.statut === 'string' ? entry.statut : null,
      domain: entry.domain,
      taxonomy_file: typeof entry.taxonomy_file === 'string' ? entry.taxonomy_file : null,
      instanciee: entry.instanciee,
      ready: readyMap.get(entry.name) ?? false,
    } satisfies RagCollection
  })
  return mapped.every((entry): entry is RagCollection => entry !== null) ? mapped : null
}

function mapReadiness(payload: unknown) {
  const readiness = payload as EngineReadiness
  if (
    typeof readiness?.launch_ready !== 'boolean' ||
    typeof readiness.total_collections !== 'number' ||
    typeof readiness.ready_collections !== 'number' ||
    !Array.isArray(readiness.blockers) ||
    !readiness.blockers.every((item) => typeof item === 'string')
  ) {
    return null
  }

  const readyMap = new Map<string, boolean>()
  if (Array.isArray(readiness.collections)) {
    for (const item of readiness.collections) {
      const col = item as EngineReadinessCollection
      if (typeof col?.name === 'string' && typeof col?.ready === 'boolean') {
        readyMap.set(col.name, col.ready)
      }
    }
  }

  return {
    launchReady: readiness.launch_ready,
    totalCollections: readiness.total_collections,
    readyCollections: readiness.ready_collections,
    blockers: readiness.blockers,
    readyMap,
  }
}

export async function GET(request: Request) {
  const authContext = await requireBffAuth(request)
  if (!authContext) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 })
  }

  try {
    const [catalogueResult, readinessResult] = await Promise.all([
      fetchEngine('/collections/v2', { identityToken: authContext.identityToken }),
      fetchEngine('/collections/readiness', { identityToken: authContext.identityToken }),
    ])
    const readiness = readinessResult.status === 200 ? mapReadiness(readinessResult.payload) : null
    if (!readiness) {
      return NextResponse.json(fallback(), { status: 503 })
    }
    const items = catalogueResult.status === 200 ? mapCatalogue(catalogueResult.payload, readiness.readyMap) : null
    if (!items) {
      return NextResponse.json(fallback(), { status: 503 })
    }
    const { readyMap: _unused, ...readinessPayload } = readiness
    return NextResponse.json({ items, live: true, ...readinessPayload })
  } catch {
    return NextResponse.json(fallback(), { status: 503 })
  }
}
