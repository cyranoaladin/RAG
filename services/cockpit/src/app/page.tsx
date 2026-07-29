import { auth } from '@/auth'
import { CockpitShell } from './CockpitShell'

export default async function Page() {
  const session = await auth()

  if (!session?.internalAccessToken || !session?.internalIdentity) {
    return <CockpitShell session={{ status: 'unverified' }} />
  }

  return (
    <CockpitShell
      session={{
        status: 'authenticated',
        user: { displayName: session.user?.name ?? session.internalIdentity.sub },
      }}
    />
  )
}
