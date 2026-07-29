const DEFAULT_ROTATION_SECONDS = 900

function parseRotationWindow(): number {
  const raw = (process.env.NEXUS_SESSION_ROTATION_SECONDS || '').trim()
  if (!raw) {
    return DEFAULT_ROTATION_SECONDS
  }

  const value = Number(raw)
  if (!Number.isFinite(value) || value <= 0) {
    return DEFAULT_ROTATION_SECONDS
  }

  return Math.min(Math.max(Math.floor(value), 60), 3600)
}

export function shouldRotate(lastRotatedAt: number, now: number = Date.now()): boolean {
  const ageSec = (now - lastRotatedAt) / 1000
  return ageSec >= parseRotationWindow()
}
