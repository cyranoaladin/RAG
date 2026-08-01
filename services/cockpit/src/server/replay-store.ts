import {
  clearRevocationStoreForTests,
  consumeSessionJti,
} from '@/server/revocation-store'

export async function consumeOnce(
  jti: string,
  exp: number,
  tenant: string,
  sub: string,
): Promise<void> {
  return consumeSessionJti(jti, exp, tenant, sub)
}

export async function clearReplayStoreForTests(): Promise<void> {
  return clearRevocationStoreForTests()
}
