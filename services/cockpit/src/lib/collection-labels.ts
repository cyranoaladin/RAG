import type { RagCollection } from '@/types/ui'
import { MATIERE_LABELS, NIVEAU_LABELS } from '@/types/ui'

export const VOIE_LABELS: Readonly<Record<string, string>> = Object.freeze({
  gen: 'Générale',
  generale: 'Générale',
  stmg: 'STMG',
  college: 'Collège',
  pro: 'Professionnelle',
})

export const STATUT_LABELS: Readonly<Record<string, string>> = Object.freeze({
  tronc_commun: 'Tronc commun',
  tc: 'Tronc commun',
  specialite: 'Spécialité',
  option: 'Option',
  examen: 'Examen',
  remediation: 'Remédiation',
})

/**
 * Règle déterministe de libellé canonique (fixe, sans condition d'exception) :
 * Formule : [Matière] — [Niveau] — [Voie sauf commun] — [Statut]
 */
export function formatCollectionLabel(collection: RagCollection | {
  matiere?: string | null
  niveau?: string | null
  voie?: string | null
  statut?: string | null
  name?: string
}): string {
  const rawMatiere = collection.matiere ?? ''
  const matiereLabel = (MATIERE_LABELS[rawMatiere] ?? rawMatiere.replace(/_/g, ' ')).trim()
  const matiereFormatted = matiereLabel ? matiereLabel.charAt(0).toUpperCase() + matiereLabel.slice(1) : ''

  const rawNiveau = collection.niveau ?? ''
  const niveauFormatted = NIVEAU_LABELS[rawNiveau] ?? (rawNiveau ? rawNiveau.charAt(0).toUpperCase() + rawNiveau.slice(1) : '')

  const rawVoie = (collection.voie ?? '').toLowerCase().trim()
  const isCommun = !rawVoie || rawVoie === 'commun' || rawVoie === 'none' || rawVoie === 'null'
  const voieFormatted = isCommun ? '' : (VOIE_LABELS[rawVoie] ?? rawVoie.toUpperCase())

  const rawStatut = collection.statut ?? ''
  const statutFormatted = STATUT_LABELS[rawStatut] ?? (rawStatut ? rawStatut.replace(/_/g, ' ').charAt(0).toUpperCase() + rawStatut.slice(1) : '')

  const parts = [matiereFormatted, niveauFormatted, voieFormatted, statutFormatted].filter(Boolean)
  return parts.length > 0 ? parts.join(' — ') : (collection.name ?? '?')
}
