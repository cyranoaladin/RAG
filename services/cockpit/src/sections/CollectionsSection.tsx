import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { RagCollection } from '@/types/ui'
import { MATIERE_LABELS, NIVEAU_LABELS } from '@/types/ui'

const DOMAINS_BADGE: Record<string, string> = {
  education: 'border-blue-300 bg-blue-50 text-blue-700',
  exam: 'border-violet-300 bg-violet-50 text-violet-700',
  quarantine: 'border-red-300 bg-red-50 text-red-700',
  official: 'border-slate-300 bg-slate-50 text-slate-700',
  nexus_owned: 'border-emerald-300 bg-emerald-50 text-emerald-700',
}

export default function CollectionsSection({ collections }: { collections: RagCollection[] }) {
  const [query, setQuery] = useState('')
  const [niveau, setNiveau] = useState<string>('tous')
  const [etat, setEtat] = useState<string>('tous')

  const filtered = useMemo(() => {
    return collections.filter((c) => {
      if (niveau !== 'tous' && c.niveau !== niveau) return false
      if (etat === 'instanciees' && !c.instanciee) return false
      if (etat === 'en_attente' && c.instanciee) return false
      if (query) {
        const q = query.toLowerCase()
        const hay = `${c.name} ${c.matiere ?? ''} ${MATIERE_LABELS[c.matiere ?? ''] ?? ''}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [collections, query, niveau, etat])

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <CardTitle className="text-base">Catalogue des collections — {filtered.length} / {collections.length}</CardTitle>
            <p className="mt-1 text-sm text-slate-500">
              Invariant M-04 : seules les collections <em>instanciées</em> sont exposées. Pas d’auto-création.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
              <Input
                placeholder="Rechercher une matière…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-56 pl-8"
              />
            </div>
            <Select value={niveau} onValueChange={setNiveau}>
              <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="tous">Tous niveaux</SelectItem>
                {Object.entries(NIVEAU_LABELS).map(([k, v]) => (
                  <SelectItem key={k} value={k}>{v}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={etat} onValueChange={setEtat}>
              <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="tous">Tous états</SelectItem>
                <SelectItem value="instanciees">Instanciées</SelectItem>
                <SelectItem value="en_attente">En attente de vague</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="max-h-[560px] overflow-auto rounded-md border">
          <Table>
            <TableHeader className="sticky top-0 bg-slate-50">
              <TableRow>
                <TableHead>Collection</TableHead>
                <TableHead>Matière</TableHead>
                <TableHead>Niveau</TableHead>
                <TableHead>Voie</TableHead>
                <TableHead>Statut</TableHead>
                <TableHead>Domaine</TableHead>
                <TableHead className="text-right">État</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((c) => (
                <TableRow key={c.name}>
                  <TableCell className="font-mono text-xs">{c.name}</TableCell>
                  <TableCell className="font-medium">
                    {c.matiere ? MATIERE_LABELS[c.matiere] ?? c.matiere : '—'}
                  </TableCell>
                  <TableCell>{c.niveau ? NIVEAU_LABELS[c.niveau] ?? c.niveau : '—'}</TableCell>
                  <TableCell className="text-slate-500">{c.voie ?? '—'}</TableCell>
                  <TableCell className="text-slate-500">{c.statut ?? '—'}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className={DOMAINS_BADGE[c.domain] ?? ''}>{c.domain}</Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    {c.ready ? (
                      <Badge className="bg-emerald-600">Prête</Badge>
                    ) : c.instanciee ? (
                      <Badge variant="outline" className="border-amber-400 bg-amber-50 text-amber-800">En validation</Badge>
                    ) : (
                      <Badge variant="outline" className="border-slate-300 text-slate-500">En attente</Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  )
}
