// @vitest-environment jsdom

import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import sourcesData from '@/data/sources.json'
import type { RagCollection } from '@/types/ui'
import OverviewSection from './OverviewSection'

describe('OverviewSection', () => {
  afterEach(cleanup)

  it('affiche le nombre de sources vérifiées dérivé du snapshot', () => {
    const verified = sourcesData.filter((source) => source.status === 'verified').length

    const { container } = render(<OverviewSection collections={[]} demo={false} />)

    expect(container.textContent).toContain(
      `${verified}/${sourcesData.length} sources`,
    )
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
    }

    const { container } = render(
      <OverviewSection collections={[collection]} demo={false} />,
    )

    expect(container.textContent).toContain('Quatrième')
    expect(container.textContent).toContain('0/1 collections instanciées')
  })
})
