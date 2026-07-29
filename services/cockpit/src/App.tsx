import { Routes, Route } from 'react-router'
import { CockpitShell } from './app/CockpitShell'

const transitionalSession = Object.freeze({
  status: 'unverified' as const,
})

export default function App() {
  return (
    <Routes>
      <Route
        path="/"
        element={<CockpitShell session={transitionalSession} />}
      />
    </Routes>
  )
}
