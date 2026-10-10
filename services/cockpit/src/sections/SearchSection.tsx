import { useState } from 'react'
import { ExternalLink, Loader2, Search, ShieldAlert } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import type { RetrievalResult } from '@/generated/contracts'
import { search } from '@/lib/bff-client'
import type { RagCollection } from '@/types/ui'

const SEARCH_UNAVAILABLE_MESSAGE =
  'La recherche est temporairement indisponible. Veuillez réessayer.'

type SearchSectionProps = Readonly<{
  collections: RagCollection[]
  launchReady: boolean
  blockers: string[]
}>

function sourceHost(sourceUri: string): string {
  try {
    return new URL(sourceUri).hostname
  } catch {
    return 'source déclarée'
  }
}

export default function SearchSection({
  collections,
  launchReady,
  blockers,
}: SearchSectionProps) {
  const [query, setQuery] = useState('')
  const [selectedCollection, setSelectedCollection] = useState('')
  const [results, setResults] = useState<RetrievalResult[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canSubmit = launchReady && Boolean(query.trim()) && Boolean(selectedCollection) && !loading

  async function runRetrieval() {
    if (!canSubmit) return
    setLoading(true)
    setSearched(true)
    setError(null)
    try {
      const response = await search(query, [selectedCollection], 8)
      setResults(response.items)
    } catch {
      setResults([])
      setError(SEARCH_UNAVAILABLE_MESSAGE)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recherche pédagogique avec passages cités</CardTitle>
          <p className="text-sm text-slate-500">
            Sélectionnez une collection pour retrouver des passages validés et leurs sources.
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          {!launchReady && (
            <p role="alert" className="flex items-start gap-2 rounded-md bg-amber-50 p-3 text-sm text-amber-900">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
              <span>
                L’ouverture est bloquée tant que chaque collection ne dispose pas d’un corpus validé substantiel.
                {blockers.length > 0 ? ` ${blockers[0]}` : ''}
              </span>
            </p>
          )}
          <Input
            placeholder="Ex. : parcours de graphes, loi binomiale, convexité…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => event.key === 'Enter' && runRetrieval()}
            disabled={!launchReady}
          />
          <label className="block text-sm font-medium text-slate-700" htmlFor="collection-picker">
            Collection à interroger
          </label>
          <select
            id="collection-picker"
            aria-label="Collection à interroger"
            className="h-10 w-full rounded-md border border-slate-200 bg-white p-2 text-sm"
            value={selectedCollection}
            disabled={!launchReady}
            onChange={(event) => setSelectedCollection(event.currentTarget.value)}
          >
            <option value="">Choisissez une collection</option>
            {collections.map((collection) => (
              <option key={collection.name} value={collection.name}>
                {[collection.matiere, collection.niveau, collection.statut]
                  .filter(Boolean)
                  .join(' · ') || collection.name}
              </option>
            ))}
          </select>
          <div className="flex flex-wrap gap-2">
            <Button onClick={runRetrieval} disabled={!canSubmit} className="bg-blue-700 hover:bg-blue-800">
              {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
              Rechercher les sources
            </Button>
          </div>
          {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        </CardContent>
      </Card>

      {searched && !loading && !error && results.length === 0 && (
        <Card><CardContent className="py-10 text-center text-sm text-slate-500">
          Aucune source validée ne permet de répondre à cette requête.
        </CardContent></Card>
      )}

      <div className="space-y-3">
        {results.map((result) => (
          <Card key={result.chunk_id}>
            <CardContent className="space-y-2 pt-5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-slate-900">{result.title ?? result.chunk_id}</span>
                <Badge variant="outline" className="border-blue-300 text-blue-700">score {result.score.toFixed(2)}</Badge>
                <Badge variant="outline" className="border-slate-300 font-mono text-xs text-slate-500">{result.doc_id}</Badge>
              </div>
              <p className="text-sm leading-relaxed text-slate-600">{result.excerpt}</p>
              {result.citation && (
                <div className="flex flex-wrap items-center gap-2 pt-1 text-xs text-slate-500">
                  <span className="font-medium">Source :</span>
                  <a href={result.citation.source_uri} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-blue-600 hover:underline">
                    {result.citation.source_label} · {sourceHost(result.citation.source_uri)}
                    <ExternalLink className="h-3 w-3" />
                  </a>
                  <Badge variant="outline" className="border-emerald-300 text-emerald-700">{result.citation.rights}</Badge>
                  {result.citation.licensor && result.citation.licence_id && result.citation.source_updated_at && result.citation.derivative_notice && (
                    <span className="basis-full text-slate-600">
                      Source : {result.citation.licensor} · {result.citation.source_label} · page {result.citation.page ?? 'non précisée'} · date de référence {result.citation.source_updated_at} · {result.citation.licence_id === 'ETALAB-2.0' ? 'Licence Ouverte Etalab 2.0' : result.citation.licence_id} · {result.citation.derivative_notice}
                    </span>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
