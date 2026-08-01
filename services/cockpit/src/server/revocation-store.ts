import { createClient } from 'redis'

interface SetOptions {
  EX: number
  NX?: boolean
}

export interface SessionBackend {
  get(key: string): Promise<string | null>
  set(key: string, value: string, options: SetOptions): Promise<string | null>
  clearForTests?(): void
}

interface MemoryEntry {
  expiresAt: number
  value: string
}

export class MemorySessionBackend implements SessionBackend {
  private readonly values = new Map<string, MemoryEntry>()

  async get(key: string): Promise<string | null> {
    const entry = this.values.get(key)
    if (!entry) return null
    if (entry.expiresAt <= Date.now()) {
      this.values.delete(key)
      return null
    }
    return entry.value
  }

  async set(key: string, value: string, options: SetOptions): Promise<string | null> {
    if (options.NX && await this.get(key) !== null) return null
    this.values.set(key, {
      expiresAt: Date.now() + options.EX * 1000,
      value,
    })
    return 'OK'
  }

  clearForTests(): void {
    this.values.clear()
  }
}

const KEY_PREFIX = 'nexus:session:v1'
const DEFAULT_SESSION_TTL_SECONDS = 3600

function boundedSeconds(name: string, fallback: number, minimum: number, maximum: number): number {
  const parsed = Number((process.env[name] || '').trim())
  if (!Number.isFinite(parsed) || parsed < minimum) return fallback
  return Math.min(Math.floor(parsed), maximum)
}

function sessionTtlSeconds(): number {
  return boundedSeconds('NEXUS_SESSION_TTL_SECONDS', DEFAULT_SESSION_TTL_SECONDS, 60, 86_400)
}

function revocationKey(sub: string, tenant: string): string {
  return `${KEY_PREFIX}:revoked:${tenant}:${sub}`
}

function tenantKey(sub: string): string {
  return `${KEY_PREFIX}:tenant:${sub}`
}

function replayKey(jti: string): string {
  return `${KEY_PREFIX}:jti:${jti}`
}

export class SharedSessionSecurityStore {
  constructor(private readonly backend: SessionBackend) {}

  async assertTenantBoundary(sub: string, tenant: string): Promise<void> {
    const key = tenantKey(sub)
    const inserted = await this.backend.set(key, tenant, {
      EX: sessionTtlSeconds(),
      NX: true,
    })
    if (inserted === 'OK') return

    const currentTenant = await this.backend.get(key)
    if (currentTenant === tenant) return
    if (currentTenant === null) {
      const retried = await this.backend.set(key, tenant, {
        EX: sessionTtlSeconds(),
        NX: true,
      })
      if (retried === 'OK') return
    }
    throw new Error('jeton externe: tenant incompatible pour cette identité')
  }

  async revokeSession(sub: string, tenant: string): Promise<void> {
    await this.backend.set(revocationKey(sub, tenant), '1', {
      EX: sessionTtlSeconds(),
    })
  }

  async isRevoked(sub: string, tenant: string): Promise<boolean> {
    return await this.backend.get(revocationKey(sub, tenant)) === '1'
  }

  async consumeOnce(jti: string, exp: number, tenant: string, sub: string): Promise<void> {
    const now = Math.floor(Date.now() / 1000)
    if (!Number.isFinite(exp) || exp <= now) {
      throw new Error('jeton externe: exp invalide')
    }
    const ttl = Math.max(1, Math.floor(exp - now))
    const inserted = await this.backend.set(
      replayKey(jti),
      JSON.stringify({ tenant, sub }),
      { EX: ttl, NX: true },
    )
    if (inserted !== 'OK') {
      throw new Error('jeton externe: jti déjà consommé')
    }
  }

  clearForTests(): void {
    this.backend.clearForTests?.()
  }
}

class RedisSessionBackend implements SessionBackend {
  private constructor(private readonly client: ReturnType<typeof createClient>) {}

  static async connect(url: string): Promise<RedisSessionBackend> {
    const client = createClient({
      url,
      socket: {
        connectTimeout: 1000,
        reconnectStrategy: false,
      },
    })
    client.on('error', () => undefined)
    await client.connect()
    return new RedisSessionBackend(client)
  }

  async get(key: string): Promise<string | null> {
    return this.client.get(key)
  }

  async set(key: string, value: string, options: SetOptions): Promise<string | null> {
    return this.client.set(key, value, options)
  }
}

let storePromise: Promise<SharedSessionSecurityStore> | null = null

function createConfiguredStore(): Promise<SharedSessionSecurityStore> {
  if ((process.env.NEXUS_SESSION_STORE_MODE || '').trim() === 'memory') {
    if (
      process.env.NODE_ENV !== 'test' ||
      process.env.NEXUS_SESSION_MEMORY_STORE_FOR_TESTS !== 'true'
    ) {
      throw new Error('Store mémoire de session interdit hors tests explicitement configurés')
    }
    return Promise.resolve(new SharedSessionSecurityStore(new MemorySessionBackend()))
  }

  const url = (process.env.NEXUS_SESSION_REDIS_URL || '').trim()
  if (!url) {
    throw new Error('Configuration session manquante: NEXUS_SESSION_REDIS_URL')
  }
  return RedisSessionBackend.connect(url).then((backend) => new SharedSessionSecurityStore(backend))
}

function configuredStore(): Promise<SharedSessionSecurityStore> {
  storePromise ??= createConfiguredStore()
  return storePromise
}

export async function assertTenantBoundary(sub: string, tenant: string): Promise<void> {
  return (await configuredStore()).assertTenantBoundary(sub, tenant)
}

export async function revokeSession(sub: string, tenant: string): Promise<void> {
  return (await configuredStore()).revokeSession(sub, tenant)
}

export async function isRevoked(sub: string, tenant: string): Promise<boolean> {
  return (await configuredStore()).isRevoked(sub, tenant)
}

export async function consumeSessionJti(
  jti: string,
  exp: number,
  tenant: string,
  sub: string,
): Promise<void> {
  return (await configuredStore()).consumeOnce(jti, exp, tenant, sub)
}

export async function clearRevocationStoreForTests(): Promise<void> {
  const store = await configuredStore()
  store.clearForTests()
}

export function resetSessionStoreForTests(): void {
  storePromise = null
}
