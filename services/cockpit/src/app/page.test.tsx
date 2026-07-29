// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { getCollections } from '@/lib/bff-client'
import { CockpitShell } from './CockpitShell'

vi.mock('@/lib/bff-client', () => ({
  getCollections: vi.fn().mockResolvedValue({ items: [], live: false }),
}))

const simulatedSession = Object.freeze({
  serverOnlySentinel: 'SERVER_ONLY_SENTINEL_MUST_NOT_LEAK',
})

describe('shell Next.js', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('rend le parcours public sans sérialiser les données serveur', () => {
    const { container } = render(<CockpitShell />)

    expect(
      container.firstElementChild?.getAttribute('data-session-status'),
    ).toBe('public')
    expect(screen.getByText('Nexus Réussite')).toBeTruthy()

    const rendered = `${container.innerHTML}\n${container.outerHTML}`

    expect(rendered).not.toContain(simulatedSession.serverOnlySentinel)
    expect(rendered).not.toContain('OPENROUTER_API_KEY')
    expect(rendered).not.toContain('RAG_ENGINE_INTERNAL_URL')
    expect(rendered).not.toContain('.internal')
    expect(getCollections).toHaveBeenCalledOnce()
  })

  it('n’expose pas les écrans internes de gouvernance au public', () => {
    render(<CockpitShell />)
    expect(screen.queryByRole('button', { name: 'Gouvernance' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Ingestion' })).toBeNull()
  })

})
