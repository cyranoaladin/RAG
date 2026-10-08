# Lot 20261008 — avis npm courants du Cockpit

## Périmètre et base

Exécution le 2026-10-08 UTC sur un worktree propre créé après `git fetch origin main`, sans utiliser le checkout CU divergent. Base : `origin/main` `ee35544bce5af74d6186ea0ef61f6902a2258ffe`, arbre `e7f13396a17676ceba5550d039b50a6a2160838f`. Le correctif npm touche `services/cockpit/package.json` et son lockfile ; le lot intègre aussi les tests d'actualité PII de la PR #288 afin de rétablir les jobs CI du producteur et du moteur, ainsi que les trois rapports de ce lot. Aucune donnée de staging ou de production n'a été écrite. L'antériorité des échecs CI est consignée dans `lot_20261008_cockpit_npm_security_dettes.md`.

Les mesures npm ont été refaites contre le registre courant. Avant correction, `npm audit --omit=dev --json` sortait avec code 1 et trois vulnérabilités **high** : `sharp` `<0.35.5` (GHSA-wq5f-xc86-pv6w), `source-map-js` `<1.2.2` (GHSA-68fv-2mgg-jv7q) et `next` par dépendance de `sharp`. L'audit complet sortait avec code 1 : neuf **high** et trois **moderate**. Les trois moderate étaient `postcss-selector-parser` `<7.1.6` (GHSA-rj75-hqrm-r3gf), `postcss-nested` par dépendance du parser et `tailwindcss-animate` par sa dépendance pair à Tailwind. Dans le lockfile, `tailwindcss` dépend directement de `postcss-nested` et de `postcss-selector-parser`. L'audit de base réexécuté depuis `ee35544b` confirme neuf high : six nœuds liés à `braces` côté développement plus trois nœuds de production. Après correction, `tailwindcss-animate` est classé high par la chaîne `braces`, d'où les sept high de développement restants ; les comptes avant/après ne s'additionnent pas par nom stable.

## Correction minimale

- L'override `sharp` de `next` passe de `0.35.4` à `0.35.5`, avec ses binaires et `libvips` associés dans le lockfile.
- `source-map-js` passe de `1.2.1` à `1.2.2` par régénération du lockfile (`npm update source-map-js --package-lock-only`).
- L'override `postcss-selector-parser` vaut `7.1.6`, version corrigée de la chaîne de développement Tailwind 3. C'est une **montée majeure 6 → 7 de cette dépendance transitive**, sans montée majeure du framework ni changement du code applicatif. Le build et les tests ont été rejoués ; un parcours BFF → API réel reste à qualifier avec la release finale.

Lockfile final : SHA-256 `8d6bc2bdcffa03e83e4a168eebd62f4a95ac344d883014465cfc7ee5d1fbbc2f`.

L'exception temporaire #284 n'a pas été modifiée ni élargie. L'audit complet conserve exclusivement les sept vulnérabilités **high** de développement provenant de `braces` GHSA-vfj7-8cjw-p6xm, exactement le périmètre déjà borné par `scripts/ci/cockpit_audit_policy.py`, qui expire le 2026-10-17 à 23:59:59 UTC.

## Qualification temporelle PII intégrée

Le contenu du commit `fb8cf474a91c71d08e11636a252b26d4c13cf020` de la PR #288 est repris par cherry-pick sous `7ffe1e3c5cdabc0a4517c62cef2d1f3feb5aca09`. Il corrige cinq tests qui demandaient encore une décision positive au reçu du 3 septembre, expiré le 3 octobre. Les tests positifs courants utilisent le reçu scellé du 22 septembre lié aux releases V4/V5, valable jusqu'au 23 octobre ; les tests historiques sont rejoués dans leur fenêtre de validité et le refus actuel du vieux reçu est vérifié explicitement. Aucun reçu, décision scellée, vérificateur d'autorité ou horloge n'est modifié. Le [rapport de cette qualification](lot_go_live_pii_currentness_20261008.md) détaille les empreintes, la population et les conditions de renouvellement.

## Preuves rejouées

| Contrôle | Résultat |
| --- | --- |
| `npm ci --no-audit --no-fund` depuis le lockfile régénéré | PASS, 495 paquets installés |
| `npm audit --omit=dev --json` | Code 0 ; info=0, low=0, moderate=0, high=0, critical=0 |
| `npm audit --json` | Code 1 ; exactement sept high de développement liés à `braces`, 0 autre avis |
| `python3 ../../scripts/ci/cockpit_audit_policy.py` | `PASS_WITH_EXACT_TEMPORARY_EXCEPTION` ; politique inchangée |
| `npm run lint`, `npm run typecheck`, `npm run contracts:check` | PASS |
| `npm test -- --run` | 21 fichiers, 180 tests PASS |
| `python3 -m pytest -q scripts/tests/test_cockpit_audit_policy.py` | 40 tests PASS |
| `python3 scripts/tests/test-cockpit-snapshot-coherence.py` | 7 tests PASS |
| `npm run build` | PASS, Next.js 16.3.8 |
| `COCKPIT_BUILD_TREE=d0888b9970e8da435fdec6f2e1bd5d9358b74765 bash scripts/tests/test-cockpit-clean-build.sh` | PASS depuis l'arbre Git indexé ; sources 21/21, catalogue 62/62, build Next.js PASS |
| Smoke HTTP local du build | `/` = 200 ; `/api/health` = 503 sans moteur configuré, conformément au refus attendu |
| `git diff --cached --check` | PASS |
| Tests PII `rag-pedago` ciblés | 91 PASS après intégration de #288 |
| Tests PII `rag-engine` ciblés | 84 PASS après intégration de #288 |
| Ruff des deux fichiers de tests PII | PASS |

Le test d'intégration `services/rag-engine/tests/integration/test_cockpit_e2e_retrieval.py` n'a **pas** été exécuté : les variables et artefacts de corpus, preuves PII et modèles nécessaires ne sont pas présents dans ce worktree ; de plus son champ de preuve `MAIN_SHA_EXPECTED` est figé sur `7769b72259d8e51749de07ab9a2dbc0a6e86ef28`. Les tests HTTP du BFF et de ses routes font partie des 180 tests réussis, mais ne remplacent pas un E2E réel au SHA final. Celui-ci reste un prérequis de qualification go-live et doit être rejoué contre le staging final par le chantier d'intégration.

## Verdict et limite

`NPM_PROD_HIGH=0`, `NPM_PROD_CRITICAL=0`, `NPM_PROD_AUDIT_EXIT=0` **sur ce lockfile**, sous réserve de fusion de la PR et d'un nouveau `npm ci` sur le SHA final. La politique d'audit complet passe sans modification, mais son exception `braces` reste temporaire et doit être retirée après correctif amont ou migration qualifiée, au plus tard à son échéance. La CI complète du HEAD réunissant les deux corrections constitue le verdict final de la PR. Cette preuve ne démontre ni le chemin étudiant public, ni la qualification staging, ni la readiness globale de production.
