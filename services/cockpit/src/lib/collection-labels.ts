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
 * Règle D-21 : Libellé composé déterministe dérivé d'une table de correspondance stricte.
 * Un code inconnu est un défaut signalé (« [code non répertorié] »), jamais un repli silencieux.
 * Formule : [Matière] — [Niveau] — [Voie sauf générale/commune] — [Statut]
 */
export function formatCollectionLabel(collection: RagCollection | {
  matiere?: string | null
  niveau?: string | null
  voie?: string | null
  statut?: string | null
  name?: string
}): string {
  const rawMatiere = collection.matiere?.trim()
  let matiereFormatted = ''
  if (rawMatiere) {
    const lookup = MATIERE_LABELS[rawMatiere]
    matiereFormatted = lookup ?? `[Matière inconnue: ${rawMatiere}]`
  }

  const rawNiveau = collection.niveau?.trim()
  let niveauFormatted = ''
  if (rawNiveau) {
    const lookup = NIVEAU_LABELS[rawNiveau]
    niveauFormatted = lookup ?? `[Niveau inconnu: ${rawNiveau}]`
  }

  const rawVoie = collection.voie?.toLowerCase().trim()
  let voieFormatted = ''
  if (rawVoie && rawVoie !== 'commun' && rawVoie !== 'none' && rawVoie !== 'null' && rawVoie !== 'generale' && rawVoie !== 'gen') {
    const lookup = VOIE_LABELS[rawVoie]
    voieFormatted = lookup ?? `[Voie inconnue: ${rawVoie}]`
  }

  const rawStatut = collection.statut?.trim()
  let statutFormatted = ''
  if (rawStatut) {
    const lookup = STATUT_LABELS[rawStatut]
    statutFormatted = lookup ?? `[Statut inconnu: ${rawStatut}]`
  }

  const parts = [matiereFormatted, niveauFormatted, voieFormatted, statutFormatted].filter(Boolean)
  return parts.length > 0 ? parts.join(' — ') : (collection.name ? `[Collection: ${collection.name}]` : '[Collection sans nom]')
}
