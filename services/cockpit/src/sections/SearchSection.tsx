import { useState } from 'react'
import { Search, ExternalLink, Loader2, ShieldAlert } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { search } from '@/lib/api'
import type { SearchResult } from '@/types/rag'
import { NIVEAU_LABELS } from '@/types/rag'

export default function SearchSection() {
  const [query, setQuery] = useState('')
  const [niveau, setNiveau] = useState('terminale')
  const [audience, setAudience] = useState('libre')
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const [demo, setDemo] = useState(false)
  const [searched, setSearched] = useState(false)

  async function runSearch() {
    setLoading(true)
    setSearched(true)
    const res = await search(query, niveau, audience)
    setResults(res.items)
    setDemo(res.demo)
    setLoading(false)
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recherche gouvernée — API /search (lecture seule)</CardTitle>
          <p className="text-sm text-slate-500">
            Filtrage imposé côté serveur par profil signé (HMAC niveau + audience). Citations obligatoires —
            aucune réponse sans source.
          </p>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input
              placeholder="Ex. : parcours de graphes, loi binomiale, convexité…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && runSearch()}
              className="flex-1"
            />
            <Select value={niveau} onValueChange={setNiveau}>
              <SelectTrigger className="w-36"><SelectValue /></SelectTrigger>
              <SelectContent>
                {Object.entries(NIVEAU_LABELS).map(([k, v]) => (
                  <SelectItem key={k} value={k}>{v}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={audience} onValueChange={setAudience}>
              <SelectTrigger className="w-36"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="libre">Candidat libre</SelectItem>
                <SelectItem value="aefe">Élève AEFE</SelectItem>
                <SelectItem value="tous">Tous publics</SelectItem>
              </SelectContent>
            </Select>
            <Button onClick={runSearch} disabled={loading} className="bg-blue-700 hover:bg-blue-800">
              {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
              Rechercher
            </Button>
          </div>
          {demo && searched && (
            <p className="mt-3 flex items-center gap-2 text-xs text-amber-700">
              <ShieldAlert className="h-3.5 w-3.5" />
              Résultats de démonstration (API non connectée) — extraits NSI Terminale déjà indexés en production gouvernée.
            </p>
          )}
        </CardContent>
      </Card>

      {searched && !loading && results.length === 0 && (
        <Card>
          <CardContent className="py-10 text-center text-sm text-slate-500">
            Saisissez une requête pour interroger l'index. Si aucune source ne répond, le moteur refuse
            explicitement plutôt que d'inventer (refusal_policy).
          </CardContent>
        </Card>
      )}

      <div className="space-y-3">
        {results.map((r) => (
          <Card key={r.chunk_id}>
            <CardContent className="space-y-2 pt-5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold text-slate-900">{r.titre}</span>
                <Badge variant="outline" className="border-blue-300 text-blue-700">
                  score {r.score.toFixed(2)}
                </Badge>
                <Badge variant="outline" className="border-slate-300 font-mono text-xs text-slate-500">
                  {r.collection}
                </Badge>
              </div>
              <p className="text-sm leading-relaxed text-slate-600">{r.extrait}</p>
              <div className="flex flex-wrap items-center gap-2 pt-1 text-xs text-slate-500">
                <span className="font-medium">Source :</span>
                <span>{r.source_label}</span>
                <a
                  href={r.source_uri}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-blue-600 hover:underline"
                >
                  {new URL(r.source_uri).hostname}
                  <ExternalLink className="h-3 w-3" />
                </a>
                <Badge variant="outline" className="border-emerald-300 text-emerald-700">{r.rights}</Badge>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
