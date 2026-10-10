import { spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import { canonicalScopeJson } from '@/server/public-scope'

const script = fileURLToPath(new URL('../../scripts/mint-session-token.mjs', import.meta.url))

function mintWithRights(rights: string) {
  const sandbox = mkdtempSync(join(process.cwd(), '.nexus-public-scope-'))
  try {
    mkdirSync(join(sandbox, 'scripts'))
    mkdirSync(join(sandbox, 'src', 'generated'), { recursive: true })
    const copiedScript = join(sandbox, 'scripts', 'mint-session-token.mjs')
    copyFileSync(script, copiedScript)
    const scopes = Array.from({ length: 11 }, (_, index) => {
      const matiere = `matiere${index}`
      return {
        artifact_version: '3',
        scope_id: `prod_${matiere}_terminale_specialite_v4`,
        status: 'eligible_for_promotion',
        source_sha256: String(index).padStart(64, 'a'),
        target_policy: {
          tenant: 'libre_terminale', niveau: 'terminale', voie: 'generale',
          matiere, statut_enseignement: 'specialite', audiences: ['libre'],
          candidates: ['libre'], roles: ['student'],
        },
        evidence_subject: {
          collection: `rag_nexus_${matiere}_terminale_specialite`,
          tenant: 'libre_terminale', niveau: 'terminale', voie: 'generale',
          matiere, statut_enseignement: 'specialite', candidat: 'libre',
          audiences: ['libre'], visibility: 'public', rights: [rights],
          school_year: '2026-2027', programme_version: 'BOEN_2026',
        },
      }
    })
    writeFileSync(join(sandbox, 'src', 'generated', 'public-retrieval-scopes-v3.json'), JSON.stringify(scopes))
    const digest = createHash('sha256').update(canonicalScopeJson(scopes)).digest('hex')
    return spawnSync(process.execPath, [copiedScript], {
      input: JSON.stringify({
        nextauth_secret: 'test-nextauth-secret-long-enough',
        internal_token_secret: 'test-internal-secret-long-enough',
        sso_issuer: 'nexus-issuer', sso_audience: 'nexus-cockpit',
        internal_token_issuer: 'cockpit-internal', internal_token_audience: 'rag-engine',
        tenant: 'libre_terminale', niveau: 'terminale', matieres: ['matiere0'],
        role: 'student', candidat: 'libre',
      }),
      encoding: 'utf8',
      env: {
        ...process.env,
        NEXUS_COCKPIT_SCOPE_MODE: 'public_v3',
        NEXUS_COCKPIT_PUBLIC_SCOPE_INDEX_SHA256: digest,
      },
    })
  } finally {
    rmSync(sandbox, { recursive: true, force: true })
  }
}

describe('jeton de qualification BFF', () => {
  it('signe un dérivé public_allowed sous un scope étudiant exact', () => {
    const run = mintWithRights('public_allowed')
    expect(run.status).toBe(0)
    expect(JSON.parse(run.stdout).internal_access_token).toMatch(/^eyJ/)
  })

  it('refuse le droit historique officiel_public pour les dérivés publics', () => {
    const run = mintWithRights('officiel_public')
    expect(run.status).not.toBe(0)
    expect(run.stdout).toBe('')
  })

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
