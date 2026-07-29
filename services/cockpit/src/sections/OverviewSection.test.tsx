// @vitest-environment jsdom

import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import sourcesData from '@/data/sources.json'
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
})
