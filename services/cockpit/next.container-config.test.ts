import { afterEach, describe, expect, it, vi } from 'vitest'

const SOURCE_SHA = 'a'.repeat(40)

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

describe('construction de l’image Cockpit', () => {
  it('conserve le démarrage Next.js local sans sortie standalone', async () => {
    vi.stubEnv('NEXUS_COCKPIT_BUILD_SHA', '')
    vi.resetModules()

    const { default: config } = await import('./next.config')

    expect(config.output).toBeUndefined()
  })

  it('produit un bundle autonome lié au SHA source exact', async () => {
    vi.stubEnv('NEXUS_COCKPIT_BUILD_SHA', SOURCE_SHA)
    vi.resetModules()

    const { default: config } = await import('./next.config')

    expect(config.output).toBe('standalone')
    expect(await config.generateBuildId?.()).toBe(SOURCE_SHA)
  })

  it('refuse un SHA de build malformé', async () => {
    vi.stubEnv('NEXUS_COCKPIT_BUILD_SHA', 'main')
    vi.resetModules()

    await expect(import('./next.config')).rejects.toThrow('NEXUS_COCKPIT_BUILD_SHA invalide')
  })
})
