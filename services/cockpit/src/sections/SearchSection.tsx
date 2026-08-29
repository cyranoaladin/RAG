import { useState, useMemo } from 'react'
import { ExternalLink, Loader2, Search, ShieldAlert, AlertCircle } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import type { RetrievalResult } from '@/generated/contracts'
import { search } from '@/lib/bff-client'
import { formatCollectionLabel } from '@/lib/collection-labels'
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
  const [selectedCollections, setSelectedCollections] = useState<string[]>([])
  const [results, setResults] = useState<RetrievalResult[]>([])
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // D-10 & D-20 (b) : Séparation stricte sur le prédicat ready (chunks reviewed >= seuil + preuve)
  const readyCollections = useMemo(() => {
    return collections.filter((c) => c.ready)
  }, [collections])

  const unavailableCollections = useMemo(() => {
    return collections.filter((c) => !c.ready)
  }, [collections])

  const canSubmit = launchReady && Boolean(query.trim()) && selectedCollections.length > 0 && !loading

  async function runRetrieval() {
    if (!canSubmit) return
    setLoading(true)
    setSearched(true)
    setError(null)
    try {
      const response = await search(query, selectedCollections, 8)
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
          <CardTitle className="text-base">Recherche documentaire pédagogique sourcée</CardTitle>
          <p className="text-sm text-slate-500">
            Interrogez les corpus validés. Les extraits sont cités avec leurs références officielles.
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          {/* D-20 (b) : Transparence sur les collections disponibles vs en attente */}
          {unavailableCollections.length > 0 && (
            <div role="status" className="flex items-start gap-2 rounded-md bg-blue-50 p-3 text-sm text-blue-900 border border-blue-200">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-blue-700" />
              <div>
                <p className="font-medium">État des matières de votre profil :</p>
                <p className="mt-0.5 text-xs text-blue-800">
                  <span className="font-semibold text-emerald-800">Disponibles ({readyCollections.length}) :</span>{' '}
                  {readyCollections.map((c) => c.matiere ?? c.name).join(', ') || 'Aucune'}
                </p>
                <p className="mt-0.5 text-xs text-slate-600">
                  <span className="font-semibold text-amber-800">À venir ({unavailableCollections.length}) :</span>{' '}
                  {unavailableCollections.map((c) => c.matiere ?? c.name).join(', ')}
                </p>
              </div>
            </div>
          )}

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
            Collections à interroger
          </label>
          {/* D-10 : Seules les collections prêtes (instanciees) sont sélectionnables */}
          <select
            id="collection-picker"
            multiple
            aria-label="Collections à interroger"
            className="min-h-36 w-full rounded-md border border-slate-200 bg-white p-2 text-sm"
            value={selectedCollections}
            disabled={!launchReady}
            onChange={(event) => setSelectedCollections(
              Array.from(event.currentTarget.selectedOptions, (option) => option.value),
            )}
          >
            {readyCollections.map((collection) => (
              <option key={collection.name} value={collection.name}>
                {formatCollectionLabel(collection)}
              </option>
            ))}
          </select>
          <p className="text-xs text-slate-500">Utilisez Ctrl/Cmd pour sélectionner plusieurs collections.</p>
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
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
