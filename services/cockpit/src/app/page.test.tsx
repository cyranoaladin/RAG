// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { getCollections } from '@/lib/api'
import App from '@/App'
import { CockpitShell } from './CockpitShell'

vi.mock('@/lib/api', () => ({
  getCollections: vi.fn().mockResolvedValue({ items: [], live: false }),
}))

const simulatedSession = Object.freeze({
  status: 'authenticated',
  user: { displayName: 'Élève Nexus' },
  serverOnlySentinel: 'SERVER_ONLY_SENTINEL_MUST_NOT_LEAK',
})

describe('shell Next.js', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('rend le cockpit authentifié sans sérialiser les données serveur', () => {
    const { container } = render(
      <CockpitShell session={simulatedSession} />,
    )

    expect(
      container.firstElementChild?.getAttribute('data-session-status'),
    ).toBe('authenticated')
    expect(screen.getByText('Nexus Réussite')).toBeTruthy()

    const rendered = `${container.innerHTML}\n${container.outerHTML}`

    expect(rendered).not.toContain(simulatedSession.serverOnlySentinel)
    expect(rendered).not.toContain('OPENROUTER_API_KEY')
    expect(rendered).not.toContain('RAG_ENGINE_INTERNAL_URL')
    expect(rendered).not.toContain('.internal')
    expect(getCollections).toHaveBeenCalledOnce()
  })

  it.each(['unverified', 'unauthenticated'] as const)(
    'refuse le contenu cockpit quand la session est %s',
    (status) => {
      const { container } = render(<CockpitShell session={{ status }} />)
      const rendered = `${container.innerHTML}\n${container.outerHTML}`

      expect(
        container.firstElementChild?.getAttribute('data-session-status'),
      ).toBe(status)
      expect(rendered).toContain('Accès au cockpit indisponible')
      expect(rendered).not.toContain('RAG — Cockpit v2')
      expect(rendered).not.toContain('Gouvernance')
      expect(getCollections).not.toHaveBeenCalled()
    },
  )

  it('maintient aussi le point d’entrée Vite fermé avant le raccord SSO', () => {
    const { container } = render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    )
    const rendered = container.innerHTML

    expect(rendered).toContain('data-session-status="unverified"')
    expect(rendered).toContain('Accès au cockpit indisponible')
    expect(rendered).not.toContain('RAG — Cockpit v2')
    expect(getCollections).not.toHaveBeenCalled()
  })
})
