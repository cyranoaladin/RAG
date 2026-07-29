// Compatibilité transitoire avec le build Vite. `import.meta.env` est absent
// pendant le prerender Next. Seul le mode de build est lisible côté client :
// aucune adresse amont ni donnée d'authentification n'y est acceptée.
export const clientEnvironment = Object.freeze({
  mode: import.meta.env?.MODE ?? process.env.NODE_ENV ?? 'production',
})
