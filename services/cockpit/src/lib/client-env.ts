// Compatibilité transitoire avec le build Vite. `import.meta.env` est absent
// pendant le prerender Next : l'accès optionnel évite tout fallback vers une
// variable NEXT_PUBLIC_*, en particulier pour le jeton de profil historique.
export const clientEnvironment = Object.freeze({
  mode: import.meta.env?.MODE ?? process.env.NODE_ENV ?? 'production',
  apiBase: import.meta.env?.VITE_RAG_API_BASE,
  profileToken: import.meta.env?.VITE_RAG_PROFILE_TOKEN,
})
