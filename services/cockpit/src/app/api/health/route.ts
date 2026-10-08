import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { NextResponse } from 'next/server'

import { fetchEngine } from '../_engine'

export async function GET() {
  const buildId = await readFile(path.resolve(process.cwd(), '.next/BUILD_ID'), 'utf8').catch(() => '')
  const build_sha = /^[0-9a-f]{40}$/.test(buildId.trim()) ? buildId.trim() : null
  try {
    const upstream = await fetchEngine('/health')
    return NextResponse.json(
      { status: upstream.status >= 200 && upstream.status < 300 ? 'ok' : 'unavailable', build_sha },
      { status: upstream.status >= 200 && upstream.status < 300 ? 200 : 503 },
    )
  } catch {
    return NextResponse.json({ status: 'unavailable', build_sha }, { status: 503 })
  }
}
