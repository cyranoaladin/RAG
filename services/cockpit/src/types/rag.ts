export interface RagCollection {
  name: string
  matiere: string | null
  niveau: string | null
  voie: string | null
  statut: string | null
  domain: string
  taxonomy_file: string | null
  instanciee: boolean
}

export interface IngestionSource {
  id: string
  url: string
  status: 'verified' | 'to_verify'
  matiere: string
  niveaux: string[]
  collections: string[]
}

export interface SearchResult {
  chunk_id: string
  titre: string
  extrait: string
  score: number
  collection: string
  source_label: string
  source_uri: string
  rights: string
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

export const NIVEAU_LABELS: Record<string, string> = {
  troisieme: 'Troisième',
  seconde: 'Seconde',
  premiere: 'Première',
  terminale: 'Terminale',
}

export const MATIERE_LABELS: Record<string, string> = {
  maths: 'Mathématiques',
  francais: 'Français',
  hg: 'Histoire-Géographie',
  emc: 'EMC',
  langues: 'Langues vivantes',
  svt: 'SVT',
  pc: 'Physique-Chimie',
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
}
