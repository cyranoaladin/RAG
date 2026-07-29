Cockpit Next.js 16 (App Router), React 19 et Tailwind CSS 3.

Structure :

- `src/app/` : routes, layout et frontière serveur/client ;
- `src/components/ui/` : composants du design system ;
- `src/sections/` : sections du cockpit ;
- `src/generated/` : types et validateurs issus de `nexus-contracts` ;
- `src/lib/bff-client.ts` : unique frontière réseau du navigateur ;
- `src/types/ui.ts` : types strictement locaux à la présentation.

Commandes : `npm run dev`, `npm test -- --run`, `npm run typecheck`,
`npm run lint` et `npm run build`.
