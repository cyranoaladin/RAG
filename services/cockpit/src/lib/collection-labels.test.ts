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
    expect(label).toBe('NSI — Première — Générale — Spécialité')
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
})
