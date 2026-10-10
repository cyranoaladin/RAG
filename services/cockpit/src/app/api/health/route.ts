import { NextResponse } from 'next/server'

import { configuredPublicScopes, publicScopeIndexDigest } from '@/server/public-scope'

import { fetchEngine } from '../_engine'

export async function GET() {
  try {
    const mode = process.env.NEXUS_COCKPIT_SCOPE_MODE?.trim() || 'pilot'
    if (mode !== 'pilot' && mode !== 'public_v3') {
      return NextResponse.json({ status: 'unavailable' }, { status: 503 })
    }
    let publicIndexDigest: string | null = null
    if (mode === 'public_v3') {
      configuredPublicScopes()
      publicIndexDigest = publicScopeIndexDigest()
    }
    const buildSha = process.env.NEXUS_COCKPIT_BUILD_SHA?.trim()
    if ((mode === 'public_v3' && !buildSha) || (buildSha && !/^[0-9a-f]{40}$/.test(buildSha))) {
      return NextResponse.json({ status: 'unavailable' }, { status: 503 })
    }
    const upstream = await fetchEngine('/health')
    return NextResponse.json(
      {
        status: upstream.status >= 200 && upstream.status < 300 ? 'ok' : 'unavailable',
        ...(buildSha ? { build_sha: buildSha } : {}),
        ...(publicIndexDigest ? { public_scope_index_sha256: publicIndexDigest } : {}),
      },
      { status: upstream.status >= 200 && upstream.status < 300 ? 200 : 503 },
    )
  } catch {
    return NextResponse.json({ status: 'unavailable' }, { status: 503 })
  }
}
