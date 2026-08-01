import { NextResponse } from 'next/server'

import collectionsSeed from '@/data/collections.json'
import { requireBffAuth } from '@/server/bff-auth'
import type { RagCollection } from '@/types/ui'

import { fetchEngine } from '../_engine'

type EngineCatalogue = { collections?: unknown }
type EngineReadiness = {
  launch_ready?: unknown
  total_collections?: unknown
  ready_collections?: unknown
  blockers?: unknown
}

function fallback() {
  return {
    items: collectionsSeed as RagCollection[],
    live: false,
    launchReady: false,
    totalCollections: collectionsSeed.length,
    readyCollections: 0,
    blockers: ['validation de lancement indisponible'],
  }
}

function mapCatalogue(payload: unknown): RagCollection[] | null {
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
  return {
    launchReady: readiness.launch_ready,
    totalCollections: readiness.total_collections,
    readyCollections: readiness.ready_collections,
    blockers: readiness.blockers,
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
    const items = catalogueResult.status === 200 ? mapCatalogue(catalogueResult.payload) : null
    const readiness = readinessResult.status === 200 ? mapReadiness(readinessResult.payload) : null
    if (!items || !readiness) {
      return NextResponse.json(fallback(), { status: 503 })
    }
    return NextResponse.json({ items, live: true, ...readiness })
  } catch {
    return NextResponse.json(fallback(), { status: 503 })
  }
}
