# Résolution de la PR 76 — conception

## Contexte

La branche `lot-34-baseline-ci` a été créée sur `lot-33-go-live-architecture`.
Les lots 31 et 35 ont ensuite été intégrés dans `main`. Le cockpit a alors été
migré vers Next.js/BFF, ce qui entre en conflit avec les améliorations CI et de
catalogue du lot 34.

## Décision

Fusionner `origin/main` dans `lot-34-baseline-ci` sans réécrire les commits
publiés. Conserver l'architecture BFF de `main` pour tous les fichiers de
runtime cockpit et reporter les apports du lot 34 uniquement lorsqu'ils restent
compatibles : CI, snapshots de catalogue, tests de cohérence et garde-fous de
build.

## Règles de résolution

- `src/lib/api.ts` reste supprimé : le cockpit public passe par
  `src/lib/bff-client.ts` et les routes `src/app/api`.
- Les composants et tests de recherche partent de la version `main`, puis
  intègrent seulement les assertions de non-démo et de cohérence compatibles.
- Les dépendances et le lockfile sont régénérés depuis le `package.json`
  résolu, sans réintroduire les dépendances incompatibles avec Next.js.
- Les scripts CI du lot 34 restent fail-closed ; ils doivent viser les scripts
  réellement présents dans le cockpit Next.js.

## Validation

Les tests de cohérence des snapshots et de fail-safe CI sont exécutés avant et
après résolution. Le cockpit passe ensuite contrats, lint, tests et build. La
PR n'est poussée qu'après une fusion sans marqueur de conflit et une CI ciblée
verte.
