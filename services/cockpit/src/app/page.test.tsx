// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import Page from './page'

vi.mock('@/lib/api', () => ({
  getCollections: vi.fn().mockResolvedValue({ items: [], live: false }),
}))

const simulatedSession = Object.freeze({
  status: 'authenticated',
  user: { displayName: 'Élève Nexus' },
})

describe('shell Next.js', () => {
  afterEach(cleanup)

  it('rend le cockpit dans un état de session authentifié minimal', () => {
    const { container } = render(
      <div data-session-status={simulatedSession.status}>
        <Page />
      </div>,
    )

    expect(
      container.firstElementChild?.getAttribute('data-session-status'),
    ).toBe('authenticated')
    expect(screen.getByText('Nexus Réussite')).toBeTruthy()
  })

  it('n’expose aucun secret ni endpoint interne dans le rendu', () => {
    const { container } = render(<Page />)
    const rendered = container.textContent ?? ''

    expect(rendered).not.toContain('Bearer ')
    expect(rendered).not.toContain('OPENROUTER_API_KEY')
    expect(rendered).not.toContain('RAG_ENGINE_INTERNAL_URL')
    expect(rendered).not.toContain('.internal')
  })
})
