// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { chat, search } from '@/lib/bff-client'

import SearchSection from './SearchSection'

vi.mock('@/lib/bff-client', () => ({
  search: vi.fn(),
  chat: vi.fn(),
}))

const searchMock = vi.mocked(search)
const chatMock = vi.mocked(chat)
const collections = [{
  name: 'rag_nexus_nsi_terminale_specialite',
  matiere: 'nsi',
  niveau: 'terminale',
  voie: 'generale',
  statut: 'specialite',
  domain: 'education',
  taxonomy_file: 'nsi/terminale.yml',
  instanciee: true,
}]

describe('SearchSection', () => {
  afterEach(() => {
    cleanup()
    vi.clearAllMocks()
  })

  it('termine le chargement et affiche un message sûr quand l’API échoue', async () => {
    searchMock.mockRejectedValue(
      new Error('fetch https://rag.internal.example/search: bearer secret'),
    )
    render(<SearchSection collections={collections} launchReady blockers={[]} />)

    fireEvent.change(
      screen.getByPlaceholderText(
        'Ex. : parcours de graphes, loi binomiale, convexité…',
      ),
      { target: { value: 'graphes' } },
    )
    const picker = screen.getByLabelText('Collections à interroger') as HTMLSelectElement
    picker.options[0].selected = true
    fireEvent.change(picker)
    const submit = screen.getByRole('button', { name: 'Rechercher les sources' })
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

  it('bloque toute requête publique tant que la validation exhaustive est rouge', () => {
    render(<SearchSection collections={collections} launchReady={false} blockers={['corpus insuffisant']} />)

    expect(screen.getByRole('alert').textContent).toContain('L’ouverture est bloquée')
    expect((screen.getByRole('button', { name: 'Rechercher les sources' }) as HTMLButtonElement).disabled).toBe(true)
    expect(chatMock).not.toHaveBeenCalled()
  })

  it('affiche l’attribution complète des passages textuels dérivés', async () => {
    searchMock.mockResolvedValue({
      demo: false,
      items: [{
        chunk_id: 'chunk-public',
        doc_id: 'doc-public',
        score: 0.9,
        title: 'Programme NSI',
        excerpt: 'Un extrait vérifié.',
        citation: {
          source_label: 'Programme NSI',
          source_uri: 'https://eduscol.education.gouv.fr/document.pdf',
          page: 3,
          rights: 'officiel_public',
          licensor: 'Ministère de l’Éducation nationale – Dgesco / Éduscol',
          licence_id: 'ETALAB-2.0',
          source_updated_at: '2026-09-12',
          derivative_notice: 'Extrait textuel dérivé ; PDF original non redistribué.',
        },
      }],
    })
    render(<SearchSection collections={collections} launchReady blockers={[]} />)

    fireEvent.change(screen.getByPlaceholderText('Ex. : parcours de graphes, loi binomiale, convexité…'), {
      target: { value: 'graphes' },
    })
    const picker = screen.getByLabelText('Collections à interroger') as HTMLSelectElement
    picker.options[0].selected = true
    fireEvent.change(picker)
    fireEvent.click(screen.getByRole('button', { name: 'Rechercher les sources' }))

    await waitFor(() => expect(screen.getByText('Un extrait vérifié.')).toBeTruthy())
    expect(screen.getByText(/Ministère de l’Éducation nationale – Dgesco \/ Éduscol/)).toBeTruthy()
    expect(screen.getByText(/Licence Ouverte Etalab 2.0/)).toBeTruthy()
    expect(screen.getByText(/2026-09-12/)).toBeTruthy()
    expect(screen.getByText(/Extrait textuel dérivé/)).toBeTruthy()
    expect(screen.getByText(/page 3/)).toBeTruthy()
    expect(screen.getByText('officiel_public')).toBeTruthy()
    const sourceLink = screen.getByRole('link', { name: /Programme NSI/ })
    expect(sourceLink.getAttribute('href')).toBe('https://eduscol.education.gouv.fr/document.pdf')
  })
})
