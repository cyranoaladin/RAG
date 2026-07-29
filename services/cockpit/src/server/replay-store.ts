export interface ReplayRecord {
  exp: number
  tenant: string
  sub: string
}

type ReplayMap = Map<string, ReplayRecord>

const replayStore: ReplayMap = new Map()

const DEFAULT_TTL_SECONDS = 900

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000)
}

function parseReplayWindow(): number {
  const raw = (process.env.NEXUS_REPLAY_WINDOW_SECONDS || '').trim()
  if (!raw) {
    return DEFAULT_TTL_SECONDS
  }

  const value = Number(raw)
  if (!Number.isFinite(value) || value <= 0) {
    return DEFAULT_TTL_SECONDS
  }

  return Math.min(Math.max(Math.floor(value), 1), 3600)
}

function cleanupReplayStore(): void {
  const now = nowSeconds()
  for (const [jti, record] of replayStore.entries()) {
    if (record.exp <= now) {
      replayStore.delete(jti)
    }
  }
}

export async function consumeOnce(
  jti: string,
  exp: number,
  tenant: string,
  sub: string,
): Promise<void> {
  cleanupReplayStore()
  const ttl = parseReplayWindow()
  if (!Number.isFinite(exp) || exp <= 0) {
    throw new Error('jeton externe: exp invalide')
  }

  if (replayStore.has(jti)) {
    throw new Error('jeton externe: jti déjà consommé')
  }

  const now = nowSeconds()
  const maxExp = now + ttl
  const safeExp = Math.min(exp, maxExp)
  replayStore.set(jti, { exp: safeExp, tenant, sub })
}

export async function clearReplayStoreForTests(): Promise<void> {
  replayStore.clear()
}
