import { execFileSync } from 'node:child_process'
import type { NextConfig } from 'next'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const cockpitRoot = path.dirname(fileURLToPath(import.meta.url))

function sourceSha(): string | null {
  const pinned = process.env.NEXUS_COCKPIT_BUILD_SHA?.trim()
  if (pinned) {
    if (!/^[0-9a-f]{40}$/.test(pinned)) throw new Error('NEXUS_COCKPIT_BUILD_SHA invalide')
    return pinned
  }
  try {
    const head = execFileSync('git', ['rev-parse', 'HEAD'], {
      cwd: path.resolve(cockpitRoot, '../..'),
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
      timeout: 5_000,
    }).trim()
    return /^[0-9a-f]{40}$/.test(head) ? head : null
  } catch {
    return null
  }
}

const buildSha = sourceSha()
const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  ...(buildSha === null ? {} : { generateBuildId: async () => buildSha }),
  turbopack: {
    root: cockpitRoot,
  },
}

export default nextConfig
