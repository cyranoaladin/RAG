import { NextResponse } from 'next/server'

import { fetchEngine } from '../_engine'

export async function GET() {
  try {
    const upstream = await fetchEngine('/health')
    return NextResponse.json(
      { status: upstream.status >= 200 && upstream.status < 300 ? 'ok' : 'unavailable' },
      { status: upstream.status >= 200 && upstream.status < 300 ? 200 : 503 },
    )
  } catch {
    return NextResponse.json({ status: 'unavailable' }, { status: 503 })
  }
}
