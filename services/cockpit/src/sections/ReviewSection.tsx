import { useState } from 'react'
import { CheckCircle2, XCircle, Hourglass, ShieldAlert, Bot, Play } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { StagingItem } from '@/types/ui'
import { MATIERE_LABELS, NIVEAU_LABELS } from '@/types/ui'

/**
 * Page « Revue agents » (LOT 29 / ADR-0018).
 * La revue est effectuée par le panel d'agents experts (rights/subject/quality),
 * consensus unanime, quarantaine par défaut. Plus de boutons d'approbation
 * manuels : l'opérateur supervise les verdicts signés et peut lancer une passe.
 */

interface PanelVerdict extends StagingItem {
  verdicts?: { reviewer: string; status: string; signature: string }[]
  panel_signature?: string
}

const DEMO_QUEUE: PanelVerdict[] = [
  {
    id: 'stg-2026-07-26-001',
    source_id: 'eduscol_maths_voie_gt',
    matiere: 'maths',
    niveau: 'terminale',
    collection_cible: 'rag_nexus_maths_terminale_gen_specialite',
    sha256: 'b7f2…9c41',
    depose_le: '26/07/2026 06:12',
    review_status: 'pending',
    taille_octets: 184_220,
  },
  {
    id: 'stg-2026-07-26-002',
    source_id: 'eduscol_philo_voie_gt',
    matiere: 'philosophie',
    niveau: 'terminale',
    collection_cible: 'rag_nexus_philo_terminale_tc',
    sha256: '41aa…02fd',
    depose_le: '26/07/2026 06:13',
    review_status: 'approved',
    taille_octets: 96_410,
    verdicts: [
      { reviewer: 'rights_expert', status: 'approved', signature: 'a1b2c3d4e5f60708' },
      { reviewer: 'subject_expert', status: 'approved', signature: '1122334455667788' },
      { reviewer: 'quality_expert', status: 'approved', signature: '90abcdef12345678' },
    ],
    panel_signature: 'f47ac10b58cc',
  },
  {
    id: 'stg-2026-07-25-007',
    source_id: 'eduscol_nsi_voie_g',
    matiere: 'nsi',
    niveau: 'terminale',
    collection_cible: 'rag_nexus_nsi_terminale_specialite',
    sha256: 'c0d4…77b1',
    depose_le: '25/07/2026 06:09',
    review_status: 'approved',
    taille_octets: 210_884,
    verdicts: [
      { reviewer: 'rights_expert', status: 'approved', signature: '0011223344556677' },
      { reviewer: 'subject_expert', status: 'approved', signature: '8899aabbccddeeff' },
      { reviewer: 'quality_expert', status: 'approved', signature: 'abcdef0123456789' },
    ],
    panel_signature: '9d2f1c7aa3e0',
  },
]

const REVIEWER_LABELS: Record<string, string> = {
  rights_expert: 'Droits',
  subject_expert: 'Programme',
  quality_expert: 'Qualité',
}

export default function ReviewSection() {
  const [items] = useState<PanelVerdict[]>(DEMO_QUEUE)
  const pending = items.filter((i) => i.review_status === 'pending').length

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Bot className="h-5 w-5 text-blue-700" />
              Revue par panel d’agents experts — {pending} artefact{pending > 1 ? 's' : ''} en attente
            </CardTitle>
            <p className="mt-1 text-sm text-slate-500">
              ADR-0018 : la revue est effectuée par 3 reviewers experts (droits, programme, qualité),
              <strong> consensus unanime</strong>, quarantaine par défaut. Chaque verdict est signé et
              consigné au ledger — réversible et rejouable.
            </p>
          </div>
          <Button
            variant="outline"
            disabled
            title="La passe est exécutée côté serveur : python -m agents.review_panel --run (aucune action revue n'est déclenchée depuis le navigateur — ADR-0018)"
            className="border-slate-300 text-slate-400"
          >
            <Play className="mr-2 h-4 w-4" />
            Lancer une passe de revue (serveur uniquement)
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="overflow-auto rounded-md border">
          <Table>
            <TableHeader className="bg-slate-50">
              <TableRow>
                <TableHead>Artefact</TableHead>
                <TableHead>Matière / Niveau</TableHead>
                <TableHead>Collection cible</TableHead>
                <TableHead>Verdicts du panel</TableHead>
                <TableHead>Signature</TableHead>
                <TableHead>Décision</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((it) => (
                <TableRow key={it.id}>
                  <TableCell className="font-mono text-xs">{it.source_id}</TableCell>
                  <TableCell>
                    {MATIERE_LABELS[it.matiere] ?? it.matiere} · {NIVEAU_LABELS[it.niveau] ?? it.niveau}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{it.collection_cible}</TableCell>
                  <TableCell>
                    {it.verdicts ? (
                      <div className="flex flex-col gap-1">
                        {it.verdicts.map((v) => (
                          <div key={v.reviewer} className="flex items-center gap-1.5 text-xs">
                            {v.status === 'approved' ? (
                              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                            ) : v.status === 'rejected' ? (
                              <XCircle className="h-3.5 w-3.5 text-red-600" />
                            ) : (
                              <ShieldAlert className="h-3.5 w-3.5 text-amber-600" />
                            )}
                            <span className="text-slate-600">{REVIEWER_LABELS[v.reviewer] ?? v.reviewer}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <span className="text-xs text-slate-400">En attente de passe</span>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-slate-500">
                    {it.panel_signature ?? '—'}
                  </TableCell>
                  <TableCell>
                    {it.review_status === 'pending' && (
                      <Badge variant="outline" className="border-amber-300 text-amber-700">
                        <Hourglass className="mr-1 h-3 w-3" />En attente
                      </Badge>
                    )}
                    {it.review_status === 'approved' && (
                      <Badge className="bg-emerald-600"><CheckCircle2 className="mr-1 h-3 w-3" />Approuvé (3/3)</Badge>
                    )}
                    {it.review_status === 'rejected' && (
                      <Badge variant="destructive"><XCircle className="mr-1 h-3 w-3" />Rejeté</Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-900">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            <strong>Règle dure non délégable :</strong> droits inconnus pour une provenance →
            quarantaine automatique, sans exception possible — y compris pour les agents.
            Le panel n’écrit jamais dans pgvector ; l’indexation reste soumise à la chaîne
            quality → gate → review. (Démonstration : en production, la passe appelle
            <code className="mx-1 rounded bg-red-100 px-1">python -m agents.review_panel --run</code>.)
          </span>
        </div>
      </CardContent>
    </Card>
  )
}
