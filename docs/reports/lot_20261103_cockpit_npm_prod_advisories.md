# Lot 2026-11-03 — fermer les avis de sécurité production du Cockpit

## Déclencheur

L'audit npm de production du 11 octobre 2026 rendait `0 vulnérabilité, exit 0`. Rejoué le **3 novembre 2026 sur les mêmes octets de lockfile** (blob Git `d930cd9db1c4d82251ee80185f1e00df462fa79f`, inchangé depuis), il rend **4 vulnérabilités de production dont 1 critique et 1 haute**. Aucune dépendance n'a bougé : ce sont des avis **publiés depuis**. C'est la raison pour laquelle un audit daté ne vaut pas pour une date ultérieure.

Base : `origin/main=99178e64a9eaa8c758a907d226f23ac2b68c4066`, arbre `cf5b5356ffc5d7ac9426366ae6bf26f128c16995`, worktree propre et détaché.

## Avis fermés

| Sévérité | Paquet | Installé | Avis | Correctif |
| --- | --- | --- | --- | --- |
| **CRITICAL** | `next` (direct) | 16.3.8 | [GHSA-2464-fhr4-w9xw](https://github.com/advisories/GHSA-2464-fhr4-w9xw) — **RCE non authentifiée** dans l'API d'optimisation d'images lorsque des SVG sont utilisés ; [GHSA-673q-mjm6-r5xr](https://github.com/advisories/GHSA-673q-mjm6-r5xr) — **RCE non authentifiée** dans les fonctions `use cache` renvoyant des tableaux typés ; [GHSA-p3m5-59mp-jv5r](https://github.com/advisories/GHSA-p3m5-59mp-jv5r) — déni de service dans l'App Router avec Server Actions | **16.4.4**, non majeur |
| **HIGH** | `zod` (direct) | <4.6.6 | [GHSA-mrhx-c7xc-m3w5](https://github.com/advisories/GHSA-mrhx-c7xc-m3w5) — épuisement mémoire sur collections contraintes surdimensionnées (CVSS 7.5) | **4.6.7** |
| MODERATE | `fast-uri` (transitif via `ajv`) | 3.1.8 | GHSA-w74x-v6f9-j3xg (CVSS 6.1), GHSA-wjr9-j795-jxcr (4.8), GHSA-xhq7-xmqj-769h (3.7), GHSA-333x-w4r6-6crp (3.7) | **3.1.9** |
| MODERATE | `ajv` | 8.20.0 | hérité de `fast-uri` | résolu par l'override |

Les deux RCE sont **non authentifiées** et portent sur la surface Next.js du Cockpit. Elles ne sont pas exploitables aujourd'hui par un élève — le Cockpit n'a aucune surface publique (`cockpit.nexusreussite.academy` ne résout pas) — mais elles le deviendraient au cutover. Elles doivent être fermées **avant** le freeze, pas après.

## Modifications

Deux lignes dans `services/cockpit/package.json` :

- `dependencies.next` : `16.3.8` → `16.4.4`. La version était **épinglée sans caret** : `npm audit fix` ne pouvait pas la corriger seul.
- `overrides.fast-uri` : `3.1.8` → `3.1.9`. L'override épinglait précisément la version devenue vulnérable — une remédiation antérieure retournée contre elle-même.

`services/cockpit/package-lock.json` : 60 insertions, 60 suppressions. Versions résolues : `next@16.4.4`, `zod@4.6.7`, `fast-uri@3.1.9`, `ajv@8.20.0`.

Aucun changement de code applicatif, de contrat, de scope ou de gouvernance. Aucune montée de version majeure.

## Vérifications exécutées au HEAD de ce lot

| Contrôle | Résultat |
| --- | --- |
| `npm ci` depuis un `node_modules` vide | 495 paquets, exit 0 |
| `npm audit --omit=dev` **avant** | 4 vulnérabilités — 1 critical, 1 high, 2 moderate ; exit **1** |
| `npm audit --omit=dev` **après** | **0 vulnérabilité, toutes sévérités ; exit 0** |
| `NPM_PROD_HIGH` / `NPM_PROD_CRITICAL` / `NPM_PROD_AUDIT_EXIT` | **0 / 0 / 0** |
| `npm run lint` (eslint) | exit 0 |
| `npm run typecheck` (`tsc --noEmit`) | exit 0 |
| `npx vitest run` | **202 tests passés**, 1 ignoré, 24 fichiers passés, 0 échec |
| `npm run contracts:check` | exit 0 — schémas et contrats générés inchangés |
| `npx next build` | exit 0 — 9 routes produites sous `next@16.4.4` |

## Ce que ce lot ne fait pas

- Il ne requalifie pas l'exception temporaire **#284** sur `braces`, **expirée le 17 octobre 2026**. `braces` est un avis de **développement**, hors du périmètre production fermé ici. Sa requalification reste due et doit faire l'objet de sa propre décision.
- L'audit complet (dev inclus) reste à **2 high et 1 critical de développement** (`next` côté dev, `vite`, `zod`) : hors périmètre production, à traiter séparément.
- Il ne déploie rien. Aucune image n'est construite, aucune cible n'est touchée.
- Il ne vaut que pour l'état du registre npm au **3 novembre 2026**. Un audit doit être rejoué au SHA figé, juste avant le freeze.

## Gate

Ce lot exige une review exact-HEAD sur son HEAD figé, CI standard verte, puis fusion par squash. Les avis fermés ici seront à revérifier au freeze final : la publication d'un nouvel avis ne demande aucune modification du dépôt pour rendre ce lot insuffisant.
