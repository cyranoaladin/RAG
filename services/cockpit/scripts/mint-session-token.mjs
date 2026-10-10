import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { SignJWT } from 'jose'
import { encode } from 'next-auth/jwt'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

function canonicalJson(value) {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value)
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(',')}]`
  }
  const entries = Object.entries(value)
    .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
    .map(([key, entry]) => `${JSON.stringify(key)}:${canonicalJson(entry)}`)
  return `{${entries.join(',')}}`
}

function sha256(value) {
  return crypto.createHash('sha256').update(canonicalJson(value), 'utf8').digest('hex')
}

function selectedScope(identity) {
  const mode = (process.env.NEXUS_COCKPIT_SCOPE_MODE || 'pilot').trim()
  if (mode === 'pilot') {
    const pilotPath = path.resolve(__dirname, '../src/generated/pilot-retrieval-scope-v1.json')
    const pilot = JSON.parse(fs.readFileSync(pilotPath, 'utf8'))
    if (
      identity.tenant !== pilot.identity.tenant ||
      identity.niveau !== pilot.identity.niveau ||
      identity.school_year !== pilot.school_year ||
      identity.pedagogical_profile.voie !== pilot.identity.voie ||
      identity.pedagogical_profile.statut_enseignement !== pilot.identity.statut_enseignement ||
      identity.pedagogical_profile.audience !== pilot.identity.audience ||
      !pilot.identity.candidates.includes(identity.pedagogical_profile.candidat) ||
      !identity.pedagogical_profile.matieres.every((matiere) =>
        pilot.subjects.some((subject) => subject.matiere === matiere))
    ) throw new Error('Identité de qualification hors scope pilote')
    return {
      scope_id: pilot.scope_id,
      scope_digest: sha256(pilot),
      allowed_collections: pilot.subjects.map((subject) => subject.collection),
    }
  }
  if (mode !== 'public_v3') throw new Error('Mode de scope Cockpit invalide')

  const indexPath = path.resolve(__dirname, '../src/generated/public-retrieval-scopes-v3.json')
  const index = JSON.parse(fs.readFileSync(indexPath, 'utf8'))
  const expected = (process.env.NEXUS_COCKPIT_PUBLIC_SCOPE_INDEX_SHA256 || '').trim()
  if (
    !Array.isArray(index) || index.length !== 11 ||
    !/^[0-9a-f]{64}$/.test(expected) || sha256(index) !== expected
  ) throw new Error('Index public final absent ou non scellé')

  const ids = new Set()
  const collections = new Set()
  const matches = []
  for (const scope of index) {
    const policy = scope?.target_policy
    const subject = scope?.evidence_subject
    if (
      scope?.artifact_version !== '3' ||
      scope.status !== 'eligible_for_promotion' ||
      !/^prod_[a-z0-9_]+_v[0-9]+$/.test(scope.scope_id) ||
      !/^[0-9a-f]{64}$/.test(scope.source_sha256) ||
      subject?.visibility !== 'public' ||
      !Array.isArray(subject.rights) || subject.rights.length !== 1 ||
      subject.rights[0] !== 'public_allowed' ||
      !Array.isArray(policy?.roles) || !policy.roles.includes('student') ||
      typeof subject.collection !== 'string' ||
      policy.tenant !== subject.tenant || policy.niveau !== subject.niveau ||
      policy.voie !== subject.voie || policy.matiere !== subject.matiere ||
      policy.statut_enseignement !== subject.statut_enseignement ||
      !Array.isArray(policy.audiences) ||
      !Array.isArray(subject.audiences) ||
      !policy.audiences.every((audience) =>
        subject.audiences.includes(audience) || subject.audiences.includes('tous')) ||
      ids.has(scope.scope_id) || collections.has(subject.collection)
    ) throw new Error('Scope public V3 invalide ou ambigu')
    ids.add(scope.scope_id)
    collections.add(subject.collection)
    const profile = identity.pedagogical_profile
    if (
      identity.tenant === policy.tenant && identity.niveau === policy.niveau &&
      identity.school_year === subject.school_year && policy.roles.includes(identity.role) &&
      profile.voie === policy.voie && profile.statut_enseignement === policy.statut_enseignement &&
      profile.matieres.length === 1 && profile.matieres[0] === policy.matiere &&
      policy.audiences.includes(profile.audience) && policy.candidates.includes(profile.candidat)
    ) matches.push(scope)
  }
  if (matches.length !== 1) throw new Error('Identité de qualification hors scope public final')
  const scope = matches[0]
  return {
    scope_id: scope.scope_id,
    scope_digest: sha256(scope),
    allowed_collections: [scope.evidence_subject.collection],
  }
}

async function main() {
  const inputRaw = fs.readFileSync(0, 'utf8')
  const params = JSON.parse(inputRaw)

  const ssoIssuer = params.sso_issuer || 'nexus-sso'
  const ssoAudience = params.sso_audience || 'nexus-cockpit'
  const internalIssuer = params.internal_token_issuer || 'cockpit-internal'
  const internalAudience = params.internal_token_audience || 'rag-engine'
  const internalSecret = new TextEncoder().encode(params.internal_token_secret)
  const nextauthSecret = params.nextauth_secret

  const now = Math.floor(Date.now() / 1000)
  const sub = params.sub || 'psn_1234567890abcdef'
  const jti = params.jti || `jti-${crypto.randomBytes(8).toString('hex')}`
  const tenant = params.tenant || 'libre_terminale'
  const niveau = params.niveau || 'terminale'
  const matieres = params.matieres || ['maths', 'nsi']
  const role = params.role || 'teacher'
  const candidat = params.candidat || 'libre'

  const identity = {
    iss: ssoIssuer,
    aud: ssoAudience,
    sub,
    jti,
    tenant,
    niveau,
    role,
    school_year: '2026-2027',
    exp: now + 600,
    pedagogical_profile: {
      voie: 'generale',
      matieres,
      statut_enseignement: 'specialite',
      candidat,
      audience: 'libre',
    },
  }

  const scope = selectedScope(identity)

  const envelope = {
    protocol_version: '1',
    iss: internalIssuer,
    aud: internalAudience,
    sub: identity.sub,
    jti: identity.jti,
    iat: now,
    exp: now + 300,
    identity,
    scope_id: scope.scope_id,
    scope_digest: scope.scope_digest,
    allowed_collections: scope.allowed_collections,
  }

  const internalAccessToken = await new SignJWT(envelope)
    .setProtectedHeader({ alg: 'HS256', typ: 'JWT' })
    .sign(internalSecret)

  const sessionToken = await encode({
    token: { sub: identity.sub, internalAccessToken },
    secret: nextauthSecret,
  })

  process.stdout.write(
    JSON.stringify({
      session_token: sessionToken,
      internal_access_token: internalAccessToken,
    }),
  )
}

main().catch((err) => {
  console.error(err)
  process.exit(1)
})
