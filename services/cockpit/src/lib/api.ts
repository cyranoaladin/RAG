import type {
  RagCollection,
  RetrievalResponse,
  RetrievalResult,
  StagingItem,
  GovernanceLock,
} from '@/types/rag'
import collectionsData from '@/data/collections.json'
import { clientEnvironment } from './client-env'

/**
 * Client transitoire du BFF cockpit (LOT 28 / ADR-0017).
 *
 * Sécurité : le navigateur ne connaît que les routes same-origin `/api/*`.
 * L'adresse de rag-engine et les données d'authentification restent côté
 * serveur. Le BFF réel sera raccordé en Task 8b.
 *
 * Le catalogue des collections est versionné dans le dépôt (source de vérité,
 * invariant M-04) : il est embarqué en données statiques. La connectivité API
 * est mesurée par le BFF `GET /api/health`.
 */

async function tryApi<T>(path: string, init?: RequestInit): Promise<T | null> {
  try {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(init?.headers as Record<string, string> | undefined),
    }
    const res = await fetch(path, {
      ...init,
      headers,
      signal: AbortSignal.timeout(8000),
    })
    if (!res.ok) return null
    return (await res.json()) as T
  } catch {
    return null
  }
}

/** Connectivité API via le BFF same-origin. */
export async function getApiHealth(): Promise<boolean> {
  const health = await tryApi<{ status?: string }>('/api/health')
  return health !== null
}

/**
 * Catalogue : source de vérité = fichier versionné du dépôt (embarqué au
 * build). `live` indique si l'API retrieval est joignable (badge UI).
 */
export async function getCollections(): Promise<{ items: RagCollection[]; live: boolean }> {
  const live = await getApiHealth()
  return { items: collectionsData as RagCollection[], live }
}

const MOCK_RESULTS: RetrievalResult[] = [
  {
    chunk_id: 'nsi_tle_graphes_0142',
    doc_id: 'programme_nsi_terminale',
    score: 0.91,
    title: 'Graphes — parcours en profondeur et en largeur',
    excerpt:
      "Un parcours en profondeur (DFS) explore chaque branche jusqu'à son extrémité avant de revenir en arrière, tandis que le parcours en largeur (BFS) explore les sommets par niveau de distance croissante depuis la source…",
    citation: {
      source_label: 'Programme NSI Terminale — BO spécial n°8 du 25 juillet 2019',
      page: null,
      source_uri:
        'https://eduscol.education.gouv.fr/5823/programmes-et-ressources-en-numerique-et-sciences-informatiques-voie-g',
      rights: 'official_public_administrative',
    },
  },
  {
    chunk_id: 'nsi_tle_graphes_0098',
    doc_id: 'ressource_nsi_structures',
    score: 0.87,
    title: 'Graphes — représentation : matrice et listes d’adjacence',
    excerpt:
      "Un graphe peut être implémenté par une matrice d'adjacence (tableau à deux dimensions) ou par des listes d'adjacence (dictionnaire de listes). Le choix dépend de la densité du graphe et des opérations dominantes…",
    citation: {
      source_label: 'Ressource eduscol NSI — structures de données',
      page: null,
      source_uri:
        'https://eduscol.education.gouv.fr/5823/programmes-et-ressources-en-numerique-et-sciences-informatiques-voie-g',
      rights: 'official_public_administrative',
    },
  },
  {
    chunk_id: 'nsi_tle_algo_0207',
    doc_id: 'programme_nsi_terminale',
    score: 0.79,
    title: 'Algorithmique — recherche textuelle (Boyer-Moore)',
    excerpt:
      "L'algorithme de Boyer-Moore compare le motif de droite à gauche et utilise deux règles de saut (mauvais caractère, bon suffixe) pour avancer efficacement dans le texte…",
    citation: {
      source_label: 'Programme NSI Terminale — algorithmique',
      page: null,
      source_uri:
        'https://eduscol.education.gouv.fr/5823/programmes-et-ressources-en-numerique-et-sciences-informatiques-voie-g',
      rights: 'official_public_administrative',
    },
  },
]

export async function search(
  query: string,
  niveau: string,
  audience: string,
): Promise<{ items: RetrievalResult[]; demo: boolean }> {
  if (!query.trim()) {
    return {
      items: [],
      demo: clientEnvironment.mode !== 'production',
    }
  }
  const remote = await tryApi<RetrievalResponse>('/api/search', {
    method: 'POST',
    body: JSON.stringify({ query, top_k: 8, niveau, audience }),
  })
  if (remote) return { items: remote.results ?? [], demo: false }
  if (clientEnvironment.mode === 'production') {
    throw new Error('RAG_API_UNAVAILABLE')
  }
  return { items: MOCK_RESULTS, demo: true }
}

export const MOCK_STAGING: StagingItem[] = [
  {
    id: 'stg-2026-07-26-001',
    source_id: 'eduscol_maths_voie_gt',
    matiere: 'maths',
    niveau: 'terminale',
    collection_cible: 'rag_nexus_maths_terminale_gen_specialite',
    sha256: 'b7f2…9c41',
    depose_le: '26/07/2026 06:12',
    review_status: 'pending',
    taille_octets: 184_220,
  },
  {
    id: 'stg-2026-07-26-002',
    source_id: 'eduscol_philo_voie_gt',
    matiere: 'philosophie',
    niveau: 'terminale',
    collection_cible: 'rag_nexus_philo_terminale_tc',
    sha256: '41aa…02fd',
    depose_le: '26/07/2026 06:13',
    review_status: 'pending',
    taille_octets: 96_410,
  },
  {
    id: 'stg-2026-07-25-007',
    source_id: 'eduscol_nsi_voie_g',
    matiere: 'nsi',
    niveau: 'terminale',
    collection_cible: 'rag_nexus_nsi_terminale_specialite',
    sha256: 'c0d4…77b1',
    depose_le: '25/07/2026 06:09',
    review_status: 'approved',
    taille_octets: 210_884,
  },
]

export const GOVERNANCE_LOCKS: GovernanceLock[] = [
  {
    name: 'runtime_api_allowed',
    value: true,
    adr: 'ADR-0011',
    description: 'API retrieval lecture seule, filtrage imposé serveur',
  },
  {
    name: 'server_start_allowed',
    value: true,
    adr: 'ADR-0011',
    description: "Démarrage de l'API retrieval (pas d'écriture pgvector)",
  },
  {
    name: 'network_allowed',
    value: true,
    adr: 'ADR-0004',
    description: 'Fetch gouverné : GET-only, whitelist, robots.txt, rate limit',
  },
  {
    name: 'data_staging_allowed',
    value: true,
    adr: 'ADR-0004',
    description: 'Dépôt staging avant revue (jamais directement en corpus)',
  },
  {
    name: 'ingestion_allowed',
    value: true,
    adr: 'ADR-0008',
    description: 'Indexation pgvector pilote gatee par la gouvernance',
  },
  {
    name: 'chunking_allowed',
    value: true,
    adr: 'ADR-0006',
    description: 'Chunking de contenu propre en staging',
  },
  {
    name: 'embeddings_allowed',
    value: true,
    adr: 'ADR-0007',
    description: 'Calcul des embeddings sur chunks conformes (e5-large 1024d)',
  },
  {
    name: 'answer_generation_allowed',
    value: false,
    adr: '—',
    description: 'Génération de réponse : INTERDITE (recherche + contexte sourcé uniquement)',
  },
  {
    name: 'ui_runtime_allowed',
    value: false,
    adr: '—',
    description: 'Runtime UI élève : en attente du cockpit validé',
  },
  {
    name: 'curated_ingestion_allowed',
    value: false,
    adr: 'ADR-0009',
    description: 'Ingestion de ressources curées : verrou fermé',
  },
]
