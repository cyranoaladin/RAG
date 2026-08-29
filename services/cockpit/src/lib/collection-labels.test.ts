import { describe, expect, it } from 'vitest'
import { formatCollectionLabel } from './collection-labels'

describe('formatCollectionLabel', () => {
  it('formate correctement une collection standard NSI', () => {
    const label = formatCollectionLabel({
      matiere: 'nsi',
      niveau: 'premiere',
      voie: 'gen',
      statut: 'specialite',
      name: 'rag_nexus_nsi_premiere_specialite',
    })
    expect(label).toBe('NSI — Première — Spécialité')
  })

  it('formate de manière déterministe une collection STMG Tronc commun', () => {
    const label = formatCollectionLabel({
      matiere: 'maths',
      niveau: 'terminale',
      voie: 'stmg',
      statut: 'tronc_commun',
      name: 'rag_nexus_maths_terminale_stmg_tc',
    })
    expect(label).toBe('Mathématiques — Terminale — STMG — Tronc commun')
  })

  it('omet la voie si elle vaut commun ou est absente', () => {
    const label = formatCollectionLabel({
      matiere: 'philosophie',
      niveau: 'terminale',
      voie: 'commun',
      statut: 'tronc_commun',
      name: 'rag_nexus_philosophie_terminale_tc',
    })
    expect(label).toBe('Philosophie — Terminale — Tronc commun')
  })

  it('D-21 : signale explicitement les codes inconnus au lieu d’un repli silencieux', () => {
    const label = formatCollectionLabel({
      matiere: 'astronomie_quantique',
      niveau: 'bac_plus_5',
      voie: 'intergalactique',
      statut: 'hors_piste',
      name: 'rag_inconnu',
    })
    expect(label).toBe(
      '[Matière inconnue: astronomie_quantique] — [Niveau inconnu: bac_plus_5] — [Voie inconnue: intergalactique] — [Statut inconnu: hors_piste]',
    )
  })
})
