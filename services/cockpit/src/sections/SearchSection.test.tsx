// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { search } from '@/lib/bff-client'

import SearchSection from './SearchSection'

vi.mock('@/lib/bff-client', () => ({
  search: vi.fn(),
}))

const searchMock = vi.mocked(search)

describe('SearchSection', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('termine le chargement et affiche un message sûr quand l’API échoue', async () => {
    searchMock.mockRejectedValue(
      new Error('fetch https://rag.internal.example/search: bearer secret'),
    )
    render(<SearchSection />)

    fireEvent.change(
      screen.getByPlaceholderText(
        'Ex. : parcours de graphes, loi binomiale, convexité…',
      ),
      { target: { value: 'graphes' } },
    )
    const submit = screen.getByRole('button', { name: 'Rechercher' })
    fireEvent.click(submit)

    expect((submit as HTMLButtonElement).disabled).toBe(true)
    await waitFor(() => {
      expect((submit as HTMLButtonElement).disabled).toBe(false)
    })
    expect(screen.getByRole('alert').textContent).toBe(
      'La recherche est temporairement indisponible. Veuillez réessayer.',
    )
    expect(document.body.textContent).not.toContain('rag.internal.example')
    expect(document.body.textContent).not.toContain('bearer secret')
  })
})
