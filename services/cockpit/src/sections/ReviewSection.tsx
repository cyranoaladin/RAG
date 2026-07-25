import { useState } from 'react'
import { CheckCircle2, XCircle, Hourglass } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { MOCK_STAGING } from '@/lib/api'
import type { StagingItem } from '@/types/rag'
import { MATIERE_LABELS, NIVEAU_LABELS } from '@/types/rag'

export default function ReviewSection() {
  const [items, setItems] = useState<StagingItem[]>(MOCK_STAGING)

  const decide = (id: string, status: 'approved' | 'rejected') =>
    setItems((prev) => prev.map((it) => (it.id === id ? { ...it, review_status: status } : it)))

  const pending = items.filter((i) => i.review_status === 'pending').length

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          File de revue humaine — {pending} artefact{pending > 1 ? 's' : ''} en attente
        </CardTitle>
        <p className="text-sm text-slate-500">
          Invariant : aucun chunk n'entre dans pgvector sans <strong>quality → gate → review</strong>.
          L'approbation signe le manifeste (chunk_id + sha256) ; le rejet part en quarantaine.
        </p>
      </CardHeader>
      <CardContent>
        <div className="overflow-auto rounded-md border">
          <Table>
            <TableHeader className="bg-slate-50">
              <TableRow>
                <TableHead>Artefact</TableHead>
                <TableHead>Matière / Niveau</TableHead>
                <TableHead>Collection cible</TableHead>
                <TableHead>SHA-256</TableHead>
                <TableHead>Déposé le</TableHead>
                <TableHead>Statut</TableHead>
                <TableHead className="text-right">Décision</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((it) => (
                <TableRow key={it.id}>
                  <TableCell className="font-mono text-xs">{it.id}</TableCell>
                  <TableCell>
                    {MATIERE_LABELS[it.matiere] ?? it.matiere} · {NIVEAU_LABELS[it.niveau] ?? it.niveau}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{it.collection_cible}</TableCell>
                  <TableCell className="font-mono text-xs text-slate-500">{it.sha256}</TableCell>
                  <TableCell className="text-slate-500">{it.depose_le}</TableCell>
                  <TableCell>
                    {it.review_status === 'pending' && (
                      <Badge variant="outline" className="border-amber-300 text-amber-700">
                        <Hourglass className="mr-1 h-3 w-3" />En attente
                      </Badge>
                    )}
                    {it.review_status === 'approved' && (
                      <Badge className="bg-emerald-600"><CheckCircle2 className="mr-1 h-3 w-3" />Approuvé</Badge>
                    )}
                    {it.review_status === 'rejected' && (
                      <Badge variant="destructive"><XCircle className="mr-1 h-3 w-3" />Rejeté</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {it.review_status === 'pending' ? (
                      <div className="flex justify-end gap-2">
                        <Button size="sm" variant="outline" className="border-emerald-300 text-emerald-700 hover:bg-emerald-50"
                          onClick={() => decide(it.id, 'approved')}>
                          Approuver
                        </Button>
                        <Button size="sm" variant="outline" className="border-red-300 text-red-700 hover:bg-red-50"
                          onClick={() => decide(it.id, 'rejected')}>
                          Rejeter
                        </Button>
                      </div>
                    ) : (
                      <span className="text-xs text-slate-400">Décision enregistrée</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <p className="mt-3 text-xs text-slate-500">
          Mode démonstration : les décisions sont locales. En production, la décision appelle l'endpoint de revue
          gouverné et alimente le manifeste de revue (<code>data/embeddings/review_manifest.json</code>) et le ledger.
        </p>
      </CardContent>
    </Card>
  )
}
