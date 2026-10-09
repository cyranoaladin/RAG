import { createHash, randomBytes } from 'node:crypto'
import { mkdtemp, chmod, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawn, type ChildProcess } from 'node:child_process'
import { createConnection, createServer } from 'node:net'

import { afterEach, expect, it } from 'vitest'

import { isRevoked, resetSessionStoreForTests, revokeSession } from './revocation-store'

async function freeLoopbackPort(): Promise<number> {
  const server = createServer()
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const address = server.address()
  if (address === null || typeof address === 'string') throw new Error('loopback port missing')
  await new Promise<void>((resolve) => server.close(() => resolve()))
  return address.port
}

async function awaitReady(port: number): Promise<void> {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    const ready = await new Promise<boolean>((resolve) => {
      const socket = createConnection({ host: '127.0.0.1', port })
      socket.once('connect', () => { socket.destroy(); resolve(true) })
      socket.once('error', () => { socket.destroy(); resolve(false) })
    })
    if (ready) return
    await new Promise((resolve) => setTimeout(resolve, 50))
  }
  throw new Error('Redis local did not become ready')
}

async function stop(server: ChildProcess): Promise<void> {
  if (server.exitCode !== null || server.signalCode !== null) return
  const exited = new Promise<void>((resolve) => server.once('exit', () => resolve()))
  server.kill('SIGTERM')
  await exited
}

afterEach(() => {
  delete process.env.NEXUS_SESSION_REDIS_URL
  resetSessionStoreForTests()
})

const liveRedisIt = process.env.NEXUS_TEST_LIVE_REDIS === '1' ? it : it.skip

liveRedisIt('échoue fermé puis reprend GET/SET après restart Redis sans restart Cockpit', async () => {
  const root = await mkdtemp(join(tmpdir(), 'nexus-redis-restart-'))
  await chmod(root, 0o700)
  const port = await freeLoopbackPort()
  const password = randomBytes(32).toString('base64url')
  const aclPath = join(root, 'session-redis.acl')
  await writeFile(aclPath, `user default on #${createHash('sha256').update(password).digest('hex')} ~nexus:session:v1:* +@connection +get +set\n`)
  await chmod(aclPath, 0o644)
  process.env.NEXUS_SESSION_REDIS_URL = `redis://default:${password}@127.0.0.1:${port}/0`
  const start = (): ChildProcess => spawn('redis-server', [
    '--bind', '127.0.0.1', '--port', String(port), '--dir', root,
    '--appendonly', 'yes', '--appendfsync', 'always', '--save', '',
    '--aclfile', aclPath,
  ], { stdio: 'ignore' })
  let server = start()
  try {
    await awaitReady(port)
    await revokeSession('before-restart', 'psn_reconnect', 'libre_terminale')
    await expect(isRevoked('before-restart', 'psn_reconnect', 'libre_terminale')).resolves.toBe(true)

    await stop(server)
    const duringFailure = await Promise.race([
      isRevoked('before-restart', 'psn_reconnect', 'libre_terminale').then(
        () => 'accepted', () => 'refused',
      ),
      new Promise<string>((resolve) => setTimeout(() => resolve('timed_out'), 500)),
    ])
    expect(duringFailure).toBe('refused')

    server = start()
    await awaitReady(port)
    let recovered = false
    for (let attempt = 0; attempt < 80; attempt += 1) {
      try {
        recovered = await isRevoked('before-restart', 'psn_reconnect', 'libre_terminale')
        if (recovered) break
      } catch { /* Une reconnexion en cours refuse encore les opérations. */ }
      await new Promise((resolve) => setTimeout(resolve, 50))
    }
    expect(recovered).toBe(true)
    await revokeSession('after-restart', 'psn_reconnect', 'libre_terminale')
    await expect(isRevoked('after-restart', 'psn_reconnect', 'libre_terminale')).resolves.toBe(true)
  } finally {
    await stop(server)
    await rm(root, { recursive: true, force: true })
  }
}, 15_000)
