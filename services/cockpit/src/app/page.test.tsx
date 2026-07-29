// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { getCollections } from '@/lib/api'
import { CockpitShell } from './CockpitShell'

vi.mock('@/lib/api', () => ({
  getCollections: vi.fn().mockResolvedValue({ items: [], live: false }),
}))

const simulatedSession = Object.freeze({
  status: 'authenticated',
  user: { displayName: 'Élève Nexus' },
  accessToken: 'TOKEN_SENTINEL_MUST_NOT_LEAK',
})

describe('shell Next.js', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
    vi.unstubAllGlobals()
  })

  it('consomme une session authentifiée sans sérialiser son jeton', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    const { container } = render(
      <CockpitShell session={simulatedSession} />,
    )

    expect(
      container.firstElementChild?.getAttribute('data-session-status'),
    ).toBe('authenticated')
    expect(screen.getByText('Nexus Réussite')).toBeTruthy()

    const rendered = `${container.innerHTML}\n${container.outerHTML}`

    expect(rendered).not.toContain(simulatedSession.accessToken)
    expect(rendered).not.toContain('Bearer ')
    expect(rendered).not.toContain('OPENROUTER_API_KEY')
    expect(rendered).not.toContain('RAG_ENGINE_INTERNAL_URL')
    expect(rendered).not.toContain('.internal')
    expect(getCollections).toHaveBeenCalledOnce()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
