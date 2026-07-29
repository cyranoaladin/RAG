import HomeClient from './HomeClient'

export type ShellSession = Readonly<{
  status: 'authenticated' | 'unauthenticated' | 'unverified'
  user?: Readonly<{ displayName?: string }>
}>

export function CockpitShell({
  session,
}: Readonly<{ session: ShellSession }>) {
  if (session.status !== 'authenticated') {
    return (
      <main
        data-session-status={session.status}
        className="flex min-h-screen items-center justify-center bg-slate-50 px-6"
      >
        <div className="max-w-md text-center">
          <h1 className="text-lg font-semibold text-slate-900">
            Accès au cockpit indisponible
          </h1>
          <p className="mt-2 text-sm text-slate-600">
            Une session Nexus vérifiée est nécessaire.
          </p>
        </div>
      </main>
    )
  }

  return (
    <div data-session-status={session.status}>
      <HomeClient />
    </div>
  )
}
