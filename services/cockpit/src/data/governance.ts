import type { GovernanceLock } from '@/types/ui'

export const GOVERNANCE_LOCKS: readonly GovernanceLock[] = Object.freeze([
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
    description:
      'Génération de réponse : INTERDITE tant que son verrou reste fermé',
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
])
