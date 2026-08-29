// @vitest-environment jsdom

import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { RagCollection } from '@/types/ui'
import OverviewSection from './OverviewSection'

describe('OverviewSection', () => {
  afterEach(cleanup)

  it('affiche les décomptes de collections dérivées du catalogue live', () => {
    const collections: RagCollection[] = [
      {
        name: 'rag_nexus_nsi_terminale_specialite',
        matiere: 'nsi',
        niveau: 'terminale',
        voie: 'generale',
        statut: 'specialite',
        domain: 'education',
        taxonomy_file: 'nsi/terminale.yml',
        instanciee: true,
        ready: true,
      },
      {
        name: 'rag_nexus_maths_terminale_specialite',
        matiere: 'maths',
        niveau: 'terminale',
        voie: 'generale',
        statut: 'specialite',
        domain: 'education',
        taxonomy_file: 'maths/terminale.yml',
        instanciee: true,
        ready: false,
      },
    ]

    const { container } = render(<OverviewSection collections={collections} demo={false} />)

    expect(container.textContent).toContain('2') // Total catalogue
    expect(container.textContent).toContain('2') // Instanciées
    expect(container.textContent).toContain('1') // Prêtes
  })

  it('affiche la couverture Quatrième sans activer la collection', () => {
    const collection: RagCollection = {
      name: 'rag_nexus_maths_quatrieme_tc',
      matiere: 'maths',
      niveau: 'quatrieme',
      voie: 'college',
      statut: 'tronc_commun',
      domain: 'education',
      taxonomy_file: 'maths/quatrieme.yml',
      instanciee: false,
      ready: false,
    }

    const { container } = render(
      <OverviewSection collections={[collection]} demo={false} />,
    )

    expect(container.textContent).toContain('Quatrième')
    expect(container.textContent).toContain('0/1 collections instanciées')
  })
})
