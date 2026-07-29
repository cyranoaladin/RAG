import HomeClient from './HomeClient'

export type ShellSession = Readonly<{
  status: 'authenticated' | 'unauthenticated' | 'unverified'
  user?: Readonly<{ displayName?: string }>
  accessToken?: string
}>

export function CockpitShell({
  session,
}: Readonly<{ session: ShellSession }>) {
  return (
    <div data-session-status={session.status}>
      <HomeClient />
    </div>
  )
}
