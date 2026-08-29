import { useMemo } from 'react'
import { Database, Layers, CheckCircle2, AlertTriangle, RefreshCw, ShieldCheck } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import type { RagCollection } from '@/types/ui'
import { NIVEAU_LABELS } from '@/types/ui'

const NIVEAUX = ['quatrieme', 'troisieme', 'seconde', 'premiere', 'terminale'] as const

export default function OverviewSection({ collections, demo }: { collections: RagCollection[]; demo: boolean }) {
  const stats = useMemo(() => {
    const instanciees = collections.filter((c) => c.instanciee)
    const ready = collections.filter((c) => c.ready)
    const byNiveau = NIVEAUX.map((n) => {
      const total = collections.filter((c) => c.niveau === n).length
      const inst = collections.filter((c) => c.niveau === n && c.instanciee).length
      const rdy = collections.filter((c) => c.niveau === n && c.ready).length
      return { niveau: n, total, inst, ready: rdy }
    })
    return {
      total: collections.length,
      instanciees: instanciees.length,
      ready: ready.length,
      byNiveau,
    }
  }, [collections])

  return (
    <div className="space-y-6">
      {demo && (
        <div className="flex items-center gap-3 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          <span>
            <strong>Mode démonstration</strong> — données issues du dépôt (catalogue v3, lecture seule).
            Le BFF same-origin n’est pas disponible pour les données temps réel.
          </span>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-slate-500">Collections au catalogue</CardTitle>
            <Database className="h-4 w-4 text-blue-600" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-slate-900">{stats.total}</div>
            <p className="mt-1 text-xs text-slate-500">Référentiel officiel des collections Nexus</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-slate-500">Collections instanciées</CardTitle>
            <Layers className="h-4 w-4 text-amber-600" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-slate-900">{stats.instanciees}</div>
            <p className="mt-1 text-xs text-slate-500">Définies dans le plan de données PostgreSQL</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-slate-500">Collections prêtes</CardTitle>
            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-slate-900">{stats.ready}</div>
            <p className="mt-1 text-xs text-slate-500">Substance et chunks validés (readiness: true)</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Couverture par niveau (4e → Terminale)</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {stats.byNiveau.map(({ niveau, total, inst }) => (
              <div key={niveau} className="space-y-1.5">
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium text-slate-700">{NIVEAU_LABELS[niveau]}</span>
                  <span className="text-slate-500">
                    {inst}/{total} collections instanciées
                  </span>
                </div>
                <Progress value={total ? (inst / total) * 100 : 0} className="h-2" />
              </div>
            ))}
            <p className="pt-2 text-xs text-slate-500">
              Phase B (rapport LOT 28) : instanciation par vagues après revue humaine des stagings —
              maths Tle/1re, puis tronc commun Tle, puis 2de/3e.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">État des plans & alertes</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-start gap-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
              <div className="text-sm">
                <span className="font-semibold text-emerald-900">Moteur gouverné (pgvector 1024d e5-large)</span>
                <p className="text-emerald-800">API /search lecture seule opérationnelle, rerank MiniLM-L-6, security_v2 fail-closed.</p>
              </div>
            </div>
            <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-3">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
              <div className="text-sm">
                <span className="font-semibold text-amber-900">Legacy ChromaDB (17 912 vecteurs, 768d)</span>
                <p className="text-amber-800">Déconnecté du moteur gouverné. Migration des 9 199 chunks admissibles planifiée (Phase C).</p>
              </div>
            </div>
            <div className="flex items-start gap-3 rounded-lg border border-blue-200 bg-blue-50 p-3">
              <RefreshCw className="mt-0.5 h-4 w-4 shrink-0 text-blue-600" />
              <div className="text-sm">
                <span className="font-semibold text-blue-900">Ingestion continue eduscol (LOT 28)</span>
                <p className="text-blue-800">Crawl-delay 10 s respecté · staging-only · revue humaine obligatoire avant gate.</p>
              </div>
            </div>
            <div className="flex items-start gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-slate-600" />
              <div className="text-sm">
                <span className="font-semibold text-slate-900">Génération de réponse</span>
                <p className="text-slate-700">
                  <Badge variant="outline" className="mr-1 border-red-300 text-red-700">Verrou fermé</Badge>
                  answer_generation_allowed: false — recherche et contexte sourcé uniquement.
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
