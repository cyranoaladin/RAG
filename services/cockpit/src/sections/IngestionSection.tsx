import { useState } from 'react'
import { Upload, Link2, HardDrive, CheckCircle2, Clock, FileWarning, Globe } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import sourcesData from '@/data/sources.json'
import type { IngestionSource } from '@/types/rag'
import { MATIERE_LABELS } from '@/types/rag'

const sources = sourcesData as IngestionSource[]

export default function IngestionSection() {
  const [tab, setTab] = useState('continue')
  const verified = sources.filter((s) => s.status === 'verified')
  const toVerify = sources.filter((s) => s.status === 'to_verify')

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-3">
        {[
          {
            icon: Upload,
            title: 'Upload de fichiers',
            desc: 'PDF, Markdown, documents enseignants → dépôt staging → quality → gate → review.',
            endpoint: '/ingest/upload-files',
          },
          {
            icon: Link2,
            title: 'Ingestion par URLs',
            desc: 'URLs whitelistées (eduscol, education.gouv.fr, Wikipedia/Wikiversité CC-BY-SA).',
            endpoint: '/ingest/urls',
          },
          {
            icon: HardDrive,
            title: 'Google Drive',
            desc: 'Synchronisation de dossiers partagés avec suivi de progression asynchrone.',
            endpoint: '/ingest/drive',
          },
        ].map(({ icon: Icon, title, desc, endpoint }) => (
          <Card key={title}>
            <CardHeader className="flex flex-row items-center gap-3 pb-2">
              <div className="rounded-lg bg-blue-50 p-2">
                <Icon className="h-5 w-5 text-blue-700" />
              </div>
              <CardTitle className="text-sm">{title}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-slate-600">{desc}</p>
              <p className="mt-2 font-mono text-xs text-slate-400">{endpoint} (ingestor gouverné)</p>
            </CardContent>
          </Card>
        ))}
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="continue">
            Ingestion continue eduscol
            <Badge className="ml-2 bg-emerald-600">{verified.length}</Badge>
          </TabsTrigger>
          <TabsTrigger value="revue_sources">
            Sources en attente de validation
            <Badge variant="outline" className="ml-2 border-amber-300 text-amber-700">{toVerify.length}</Badge>
          </TabsTrigger>
        </TabsList>

        <TabsContent value="continue">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Globe className="h-4 w-4 text-blue-700" />
                Sources vérifiées — passe quotidienne (timer systemd, crawl-delay 10 s)
              </CardTitle>
              <p className="text-sm text-slate-500">
                ADR-0016 : staging uniquement, détection de changement par SHA-256, TTL 7 jours,
                revue humaine obligatoire avant gate.
              </p>
            </CardHeader>
            <CardContent>
              <SourceTable items={verified} statusBadge={
                <Badge className="bg-emerald-600"><CheckCircle2 className="mr-1 h-3 w-3" />Vérifiée</Badge>
              } />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="revue_sources">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <FileWarning className="h-4 w-4 text-amber-600" />
                Sources candidates — activation après revue humaine (ADR-0016 §6)
              </CardTitle>
              <p className="text-sm text-slate-500">
                URLs déduites des conventions eduscol : l'agent les ignore tant que
                <code className="mx-1 rounded bg-slate-100 px-1">status: verified</code> n'est pas confirmé
                dans <code className="rounded bg-slate-100 px-1">eduscol_sources.yml</code>.
              </p>
            </CardHeader>
            <CardContent>
              <SourceTable items={toVerify} statusBadge={
                <Badge variant="outline" className="border-amber-300 text-amber-700">
                  <Clock className="mr-1 h-3 w-3" />À valider
                </Badge>
              } />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}

function SourceTable({ items, statusBadge }: { items: IngestionSource[]; statusBadge: React.ReactNode }) {
  return (
    <div className="max-h-[420px] overflow-auto rounded-md border">
      <Table>
        <TableHeader className="sticky top-0 bg-slate-50">
          <TableRow>
            <TableHead>Source</TableHead>
            <TableHead>Matière</TableHead>
            <TableHead>Niveaux</TableHead>
            <TableHead>Collections cibles</TableHead>
            <TableHead className="text-right">Statut</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((s) => (
            <TableRow key={s.id}>
              <TableCell>
                <div className="max-w-xs">
                  <div className="truncate font-mono text-xs">{s.id}</div>
                  <a
                    href={s.url}
                    target="_blank"
                    rel="noreferrer"
                    className="block truncate text-xs text-blue-600 hover:underline"
                  >
                    {s.url}
                  </a>
                </div>
              </TableCell>
              <TableCell className="font-medium">{MATIERE_LABELS[s.matiere] ?? s.matiere}</TableCell>
              <TableCell className="text-slate-500">{s.niveaux.join(', ')}</TableCell>
              <TableCell>
                <div className="flex max-w-xs flex-wrap gap-1">
                  {s.collections.slice(0, 3).map((c) => (
                    <Badge key={c} variant="outline" className="font-mono text-[10px]">{c.replace('rag_nexus_', '')}</Badge>
                  ))}
                  {s.collections.length > 3 && (
                    <Badge variant="outline" className="text-[10px]">+{s.collections.length - 3}</Badge>
                  )}
                </div>
              </TableCell>
              <TableCell className="text-right">{statusBadge}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
