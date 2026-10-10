import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const script = fileURLToPath(new URL('../../scripts/mint-session-token.mjs', import.meta.url))

describe('jeton de qualification BFF', () => {
  it('refuse le mode public sans index final embarqué et scellé', () => {
    const run = spawnSync(process.execPath, [script], {
      input: JSON.stringify({
        nextauth_secret: 'test-nextauth-secret-long-enough',
        internal_token_secret: 'test-internal-secret-long-enough',
        sso_issuer: 'nexus-issuer', sso_audience: 'nexus-cockpit',
        internal_token_issuer: 'cockpit-internal', internal_token_audience: 'rag-engine',
        tenant: 'libre_terminale', niveau: 'terminale', matieres: ['nsi'],
        role: 'student', candidat: 'libre',
      }),
      encoding: 'utf8',
      env: {
        ...process.env,
        NEXUS_COCKPIT_SCOPE_MODE: 'public_v3',
        NEXUS_COCKPIT_PUBLIC_SCOPE_INDEX_SHA256: 'a'.repeat(64),
      },
    })
    expect(run.status).not.toBe(0)
    expect(run.stdout).toBe('')
  })
})
