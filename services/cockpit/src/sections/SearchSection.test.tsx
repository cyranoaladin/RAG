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
  ready: true,
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

  it('D-10 & D-20 (b) discriminant : une collection instanciee=true mais ready=false est exclue du sélecteur et listée dans À venir', () => {
    const mixedCollections = [
      {
        name: 'rag_nexus_nsi_terminale_specialite',
        matiere: 'nsi',
        niveau: 'terminale',
        voie: 'generale',
        statut: 'specialite',
        domain: 'education',
        taxonomy_file: 'nsi/terminale.yml',
        instanciee: true,
        ready: true, // Chunks relus et validés
      },
      {
        name: 'rag_nexus_maths_terminale_specialite',
        matiere: 'mathematiques',
        niveau: 'terminale',
        voie: 'generale',
        statut: 'specialite',
        domain: 'education',
        taxonomy_file: 'maths/terminale.yml',
        instanciee: true,
        ready: false, // Instanciée au catalogue mais 0 chunk relu (non prête)
      },
    ]

    render(<SearchSection collections={mixedCollections} launchReady blockers={[]} />)

    // 1. Le sélecteur ne doit contenir QUE la collection ready (NSI) et JAMAIS la collection non ready (Maths)
    const picker = screen.getByLabelText('Collections à interroger') as HTMLSelectElement
    const options = Array.from(picker.options).map((opt) => opt.value)
    expect(options).toEqual(['rag_nexus_nsi_terminale_specialite'])
    expect(options).not.toContain('rag_nexus_maths_terminale_specialite')

    // 2. L'encart D-20 (b) doit mentionner explicitement NSI en Disponible et Maths en À venir
    const statusBox = screen.getByRole('status')
    expect(statusBox.textContent).toContain('Disponibles (1) : nsi')
    expect(statusBox.textContent).toContain('À venir (1) : mathematiques')
  })
})
