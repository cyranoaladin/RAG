type RevocationKey = `${string}:${string}`

const revoked: Set<RevocationKey> = new Set()
const activeTenantBySubject: Map<string, string> = new Map()

function key(sub: string, tenant: string): RevocationKey {
  return `${sub}:${tenant}`
}

export async function assertTenantBoundary(sub: string, tenant: string): Promise<void> {
  const currentTenant = activeTenantBySubject.get(sub)
  if (currentTenant && currentTenant !== tenant) {
    throw new Error('jeton externe: tenant incompatible pour cette identité')
  }

  activeTenantBySubject.set(sub, tenant)
}

export async function revokeSession(sub: string, tenant: string): Promise<void> {
  revoked.add(key(sub, tenant))
}

export async function isRevoked(sub: string, tenant: string): Promise<boolean> {
  return revoked.has(key(sub, tenant))
}

export async function clearRevocationStoreForTests(): Promise<void> {
  revoked.clear()
  activeTenantBySubject.clear()
}
