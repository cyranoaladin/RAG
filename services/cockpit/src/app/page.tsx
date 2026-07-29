import { CockpitShell } from './CockpitShell'

const transitionalSession = Object.freeze({
  status: 'unverified' as const,
})

export default function Page() {
  return <CockpitShell session={transitionalSession} />
}
