import { Lock, LockOpen, FileText } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { GOVERNANCE_LOCKS } from '@/data/governance'

const INVARIANTS = [
  'Le cockpit ne parle qu\'au contrat de retrieval — jamais d\'accès direct à pgvector ni aux documents bruts.',
  'Aucun agent ni worker n\'écrit dans pgvector sans quality → gate → review.',
  'Aucune clé verrouillée ne passe à true sans ADR référencé (garde-fou CI : check-governance-locks.sh).',
  'Droits résolus par provenance uniquement ; droits inconnus → quarantaine non retrievable.',
  'Session et coefficients : declared_or_null — déclarés depuis la source officielle, jamais devinés.',
  'Pas de secret ni de PII élève dans le dépôt ; pas de chemin absolu machine-local.',
]

export default function GovernanceSection() {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Verrous de gouvernance — pedago_interface_contract.yml</CardTitle>
          <p className="text-sm text-slate-500">
            Comparaison clé par clé contre <code>governance-locks.baseline</code> en CI. Fail-closed en cas d’écart.
          </p>
        </CardHeader>
        <CardContent className="space-y-2">
          {GOVERNANCE_LOCKS.map((lock) => (
            <div key={lock.name} className="flex items-center justify-between rounded-lg border p-3">
              <div className="flex items-start gap-3">
                {lock.value ? (
                  <LockOpen className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                ) : (
                  <Lock className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
                )}
                <div>
                  <div className="font-mono text-sm font-medium">{lock.name}</div>
                  <div className="text-xs text-slate-500">{lock.description}</div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {lock.adr !== '—' && (
                  <Badge variant="outline" className="border-slate-300 text-xs text-slate-500">
                    <FileText className="mr-1 h-3 w-3" />{lock.adr}
                  </Badge>
                )}
                <Badge className={lock.value ? 'bg-emerald-600' : 'bg-red-600'}>
                  {lock.value ? 'true' : 'false'}
                </Badge>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Invariants de la plateforme (AGENTS.md)</CardTitle>
          <p className="text-sm text-slate-500">Non négociables — protégés par la CI, pas par la documentation.</p>
        </CardHeader>
        <CardContent>
          <ul className="space-y-3">
            {INVARIANTS.map((inv, i) => (
              <li key={i} className="flex items-start gap-3 rounded-lg bg-slate-50 p-3 text-sm text-slate-700">
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-blue-700 text-xs font-bold text-white">
                  {i + 1}
                </span>
                {inv}
              </li>
            ))}
          </ul>
          <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">
            <strong>Références :</strong> ADR-0001 (3 plans), ADR-0005 (multi-agents), ADR-0013 (convergence dual-engine),
            ADR-0015 (corpus tous niveaux), ADR-0016 (ingestion continue), ADR-0017 (cockpit v2) — LOT 28.
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
