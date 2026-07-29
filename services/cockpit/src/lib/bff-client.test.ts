import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { extname, join, relative } from 'node:path'

import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  BFF_ERROR_CODE,
  getApiHealth,
  search,
} from './bff-client'

const cockpitRoot = join(import.meta.dirname, '../..')
const sourceRoot = join(cockpitRoot, 'src')

function sourceFiles(root: string): string[] {
  return readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const path = join(root, entry.name)
    if (entry.isDirectory()) {
      return entry.name === 'generated' ? [] : sourceFiles(path)
    }
    return ['.ts', '.tsx'].includes(extname(entry.name)) &&
      !entry.name.includes('.test.')
      ? [path]
      : []
  })
}

describe('frontière BFF du cockpit', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('interdit les anciens clients, variables, jetons et appels réseau dans l’UI', () => {
    const violations = sourceFiles(sourceRoot).flatMap((path) => {
      const source = readFileSync(path, 'utf8')
      const name = relative(cockpitRoot, path)
      const findings = [
        ['ancien client API', /@\/lib\/api\b/],
        ['anciens types RAG', /@\/types\/rag\b/],
        ['ancienne variable Vite', /\bVITE_[A-Z0-9_]+\b/],
        ['ancienne variable React', /\bREACT_APP_[A-Z0-9_]+\b/],
        ['jeton Bearer', /\bBearer\b/i],
        [
          'fetch hors client BFF',
          path.endsWith(join('src', 'lib', 'bff-client.ts'))
            ? /$a/
            : /\bfetch\s*\(/,
        ],
      ] as const

      return findings
        .filter(([, pattern]) => pattern.test(source))
        .map(([label]) => `${name}: ${label}`)
    })

    expect(violations).toEqual([])
  })

  it('ne conserve aucun point d’entrée ni aucune configuration Vite', () => {
    const forbidden = [
      'index.html',
      'vite.config.ts',
      'tsconfig.app.json',
      'tsconfig.node.json',
      'src/main.tsx',
      'src/App.tsx',
      'src/App.css',
      'src/lib/api.ts',
      'src/lib/client-env.ts',
      'src/types/rag.ts',
    ].filter((path) => existsSync(join(cockpitRoot, path)))

    expect(forbidden).toEqual([])
  })

  it('appelle uniquement la route retrieval same-origin et valide sa réponse', async () => {
    const response = {
      results: [
        {
          chunk_id: 'chunk-1',
          doc_id: 'document-1',
          score: 0.9,
          excerpt: 'Une explication sourcée.',
          citation: {
            source_label: 'Programme officiel',
            source_uri: 'https://eduscol.education.fr/programme',
            rights: 'official_public_administrative',
          },
        },
      ],
      warnings: [],
      filters_applied: { niveau: 'terminale' },
    }
    const fetchMock = vi.fn().mockResolvedValue(Response.json(response))
    vi.stubGlobal('fetch', fetchMock)

    await expect(
      search('graphes', 'terminale', 'libre'),
    ).resolves.toEqual({ items: response.results, demo: false })

    expect(fetchMock).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/search',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(path.startsWith('/')).toBe(true)
    expect(path.startsWith('//')).toBe(false)
    expect(init.headers).not.toHaveProperty('Authorization')
  })

  it.each([
    ['champ supplémentaire', Response.json({ results: [], unexpected: true })],
    ['forme incorrecte', Response.json({ results: [{ chunk_id: 42 }] })],
    [
      'HTTP non-2xx',
      new Response('upstream details', { status: 503 }),
    ],
    [
      'JSON invalide',
      new Response('{invalid', {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    ],
  ])('rejette une réponse %s sans exposer son contenu', async (_label, response) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))

    await expect(search('graphes', 'terminale', 'libre')).rejects.toThrow(
      BFF_ERROR_CODE,
    )
  })

  it('normalise une panne réseau et impose une expiration bornée', async () => {
    const signal = new AbortController().signal
    const timeoutSpy = vi
      .spyOn(AbortSignal, 'timeout')
      .mockReturnValue(signal)
    vi.stubGlobal(
      'fetch',
      vi.fn().mockRejectedValue(
        new TypeError('https://rag-engine.internal: jeton secret'),
      ),
    )

    await expect(search('graphes', 'terminale', 'libre')).rejects.toThrow(
      BFF_ERROR_CODE,
    )
    expect(timeoutSpy).toHaveBeenCalledWith(8000)
  })

  it('sonde la santé par une route relative sans accepter le corps amont', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('not trusted', { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(getApiHealth()).resolves.toBe(true)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/health',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })
})
