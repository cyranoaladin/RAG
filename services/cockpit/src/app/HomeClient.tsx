'use client'

import { useEffect, useState } from 'react'
import {
  LayoutDashboard,
  Database,
  Search,
  GraduationCap,
} from 'lucide-react'
import OverviewSection from '@/sections/OverviewSection'
import CollectionsSection from '@/sections/CollectionsSection'
import SearchSection from '@/sections/SearchSection'
import { getCollections } from '@/lib/bff-client'
import type { RagCollection } from '@/types/ui'

type Tab = 'apercu' | 'collections' | 'recherche'

const NAV: { id: Tab; label: string; icon: typeof LayoutDashboard }[] = [
  { id: 'apercu', label: "Vue d'ensemble", icon: LayoutDashboard },
  { id: 'collections', label: 'Collections', icon: Database },
  { id: 'recherche', label: 'Recherche', icon: Search },
]

export default function HomeClient() {
  const [tab, setTab] = useState<Tab>('apercu')
  const [collections, setCollections] = useState<RagCollection[]>([])
  const [apiLive, setApiLive] = useState(false)
  const [launchReady, setLaunchReady] = useState(false)
  const [blockers, setBlockers] = useState<string[]>([])

  useEffect(() => {
    getCollections().then((res) => {
      setCollections(res.items)
      setApiLive(res.live)
      setLaunchReady(res.launchReady)
      setBlockers(res.blockers)
    })
  }, [])

  return (
    <div className="flex min-h-screen bg-slate-100">
      {/* Sidebar */}
      <aside className="flex w-60 shrink-0 flex-col bg-[#0B1F3A] text-white">
        <div className="flex items-center gap-3 border-b border-white/10 px-5 py-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600">
            <GraduationCap className="h-5 w-5" />
          </div>
          <div>
            <div className="text-sm font-bold leading-tight">Nexus Réussite</div>
          <div className="text-xs text-blue-300">Recherche pédagogique sourcée</div>
          </div>
        </div>
        <nav className="flex-1 space-y-1 px-3 py-4">
          {NAV.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setTab(id)}
              className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                tab === id
                  ? 'bg-blue-600 text-white'
                  : 'text-blue-200/80 hover:bg-white/10 hover:text-white'
              }`}
            >
              <Icon className="h-4 w-4" />
              {label}
            </button>
          ))}
        </nav>
        <div className="border-t border-white/10 px-5 py-4 text-xs text-blue-300/70">
          <div>nexusreussite.academy</div>
          <div className="mt-1">Sources contrôlées · citations visibles</div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-auto">
        <header className="sticky top-0 z-10 flex items-center justify-between border-b bg-white px-8 py-4">
          <div>
            <h1 className="text-lg font-bold text-slate-900">
              {NAV.find((n) => n.id === tab)?.label}
            </h1>
            <p className="text-xs text-slate-500">
              Moteur gouverné pgvector · e5-large 1024d · retrieval hybride + rerank
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium ${
              launchReady && apiLive ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'
            }`}>
              <span className={`h-1.5 w-1.5 rounded-full ${launchReady && apiLive ? 'bg-emerald-500' : 'bg-amber-500'}`} />
              {launchReady && apiLive ? 'Ouverture validée' : 'Ouverture bloquée'}
            </span>
          </div>
        </header>

        <div className="p-8">
          {tab === 'apercu' && <OverviewSection collections={collections} demo={!launchReady} />}
          {tab === 'collections' && <CollectionsSection collections={collections} />}
          {tab === 'recherche' && (
            <SearchSection
              collections={collections}
              launchReady={launchReady && apiLive}
              blockers={blockers}
            />
          )}
        </div>
      </main>
    </div>
  )
}
