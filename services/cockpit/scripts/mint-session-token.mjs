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

  const pilotScopePath = path.resolve(__dirname, '../src/generated/pilot-retrieval-scope-v1.json')
  const pilotScope = JSON.parse(fs.readFileSync(pilotScopePath, 'utf8'))
  const finalScopesPath = path.resolve(__dirname, '../src/generated/final-retrieval-scopes-v4-v5.json')
  const finalScopes = JSON.parse(fs.readFileSync(finalScopesPath, 'utf8'))
  const matches = finalScopes.filter((scope) => {
    const target = scope.target_identity
    const profile = identity.pedagogical_profile
    return identity.tenant === target.tenant && identity.niveau === target.niveau
      && identity.school_year === scope.evidence_subject.school_year
      && profile.voie === target.voie && profile.matieres.length === 1
      && profile.matieres[0] === target.matiere
      && profile.statut_enseignement === target.statut_enseignement
      && target.candidates.includes(profile.candidat) && profile.audience === target.audience
  })
  if (matches.length > 1) throw new Error('Scope de qualification ambigu')
  if (matches.length === 0) {
    const target = pilotScope.identity
    const profile = identity.pedagogical_profile
    const allowed = new Set(pilotScope.subjects.map((subject) => subject.matiere))
    if (identity.tenant !== target.tenant || identity.niveau !== target.niveau
      || identity.school_year !== pilotScope.school_year || profile.voie !== target.voie
      || profile.statut_enseignement !== target.statut_enseignement
      || profile.audience !== target.audience || !target.candidates.includes(profile.candidat)
      || !profile.matieres.every((matiere) => allowed.has(matiere))) {
      throw new Error('Identité hors scope de qualification')
    }
  }
  const selectedScope = matches[0] || pilotScope
  const scopeDigest = crypto
    .createHash('sha256')
    .update(canonicalJson(selectedScope), 'utf8')
    .digest('hex')

  const allowedCollections = selectedScope.evidence_subject
    ? [selectedScope.evidence_subject.collection]
    : pilotScope.subjects.map((subject) => subject.collection)

  const envelope = {
    protocol_version: '1',
    iss: internalIssuer,
    aud: internalAudience,
    sub: identity.sub,
    jti: identity.jti,
    iat: now,
    exp: now + 300,
    identity,
    scope_id: selectedScope.scope_id,
    scope_digest: scopeDigest,
    allowed_collections: allowedCollections,
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
