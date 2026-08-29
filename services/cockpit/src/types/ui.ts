/** Types et libellés strictement locaux à l'interface du cockpit. */
export interface RagCollection {
  name: string
  matiere: string | null
  niveau: string | null
  voie: string | null
  statut: string | null
  domain: string
  taxonomy_file: string | null
  instanciee: boolean
  ready: boolean
}

export interface IngestionSource {
  id: string
  url: string
  status: 'verified' | 'to_verify'
  matiere: string
  niveaux: string[]
  collections: string[]
}

/**
 * Schéma canonique du contrat de retrieval (packages/contracts retrieval.py).
 * Le cockpit consomme RetrievalResult tel quel — aucun schéma local parallèle
 * (fix revue PR : alignement sur le contrat partagé).
 */
export interface RetrievalCitation {
  source_label: string
  page: number | null
  source_uri: string
  rights: string
}

export interface RetrievalResult {
  chunk_id: string
  doc_id: string
  score: number
  title: string | null
  excerpt: string
  citation: RetrievalCitation | null
  metadata?: Record<string, unknown>
}

export interface RetrievalResponse {
  results: RetrievalResult[]
  warnings: string[]
  filters_applied: Record<string, unknown>
}

export interface StagingItem {
  id: string
  source_id: string
  matiere: string
  niveau: string
  collection_cible: string
  sha256: string
  depose_le: string
  review_status: 'pending' | 'approved' | 'rejected'
  taille_octets: number
}

export interface GovernanceLock {
  name: string
  value: boolean
  adr: string
  description: string
}

export const NIVEAU_LABELS: Readonly<Record<string, string>> = Object.freeze({
  quatrieme: 'Quatrième',
  troisieme: 'Troisième',
  seconde: 'Seconde',
  premiere: 'Première',
  terminale: 'Terminale',
})

export const MATIERE_LABELS: Readonly<Record<string, string>> = Object.freeze({
  maths: 'Mathématiques',
  francais: 'Français',
  hg: 'Histoire-Géographie',
  histoire_geo: 'Histoire-Géographie',
  emc: 'EMC',
  langues: 'Langues vivantes',
  svt: 'SVT',
  pc: 'Physique-Chimie',
  physique_chimie: 'Physique-Chimie',
  techno: 'Technologie',
  nsi: 'NSI',
  snt: 'SNT',
  ses: 'SES',
  es: 'Enseignement scientifique',
  eps: 'EPS',
  philosophie: 'Philosophie',
  hggsp: 'HGGSP',
  llce: 'LLCE',
  hlp: 'HLP',
  droit_economie: 'Droit & Économie',
  msdgn: 'Management & SDGN',
  grand_oral: 'Grand Oral',
  exams: 'Examens',
  dnb: 'DNB',
  candidats_libres: 'Candidats libres',
})
