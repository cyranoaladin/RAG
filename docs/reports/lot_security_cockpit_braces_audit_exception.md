# Décision — exception d'audit TEMPORAIRE du cockpit pour l'avis `braces` (GHSA-vfj7-8cjw-p6xm)

**Statut : temporaire et révocable. Échéance : 2026-10-17T23:59:59Z. Aucune extension automatique.**

## Problème

Depuis le 2026-10-03, `npm audit` échoue dans `services/cockpit` pour **toute** PR, ce qui bloque le check requis `services/cockpit`
et donc toute fusion sur `main`, alors que le code n'a pas changé (les 180 tests et le build passent).

## L'avis exact

| | |
|---|---|
| GHSA | `GHSA-vfj7-8cjw-p6xm` (npm : source 1240992) |
| CVE | `CVE-2026-93687` |
| paquet racine | `braces`, plage vulnérable `<= 3.0.3` |
| sévérité | high (déni de service par épuisement de pile sur des motifs profondément imbriqués) |
| version corrigée | **aucune** (`first_patched_version: null` ; dernière version npm : 3.0.3) |

Les sept vulnérabilités hautes remontent **toutes, exclusivement**, à cet avis : `braces`, `chokidar`, `micromatch`, `fast-glob`,
`tailwindcss`, `tailwindcss-animate` et `@next/eslint-plugin-next`. Il n'y en a aucune autre, de quelque sévérité que ce soit.

## Exposition démontrée (relue sur `main` = `0e62d339`)

- `npm audit --omit=dev` : **0 vulnérabilité** (plus strict que `--audit-level=high`, et conservé tel quel).
- `braces` n'est pas dans l'arbre de production : l'entrée du lockfile porte `dev: true`, aucune des 225 entrées de production ne l'atteint,
  et `npm ls braces --omit=dev` ne trouve rien. Il n'apparaît que sous `tailwindcss`, une dépendance de développement.
- Les entrées des sept paquets sont toutes `dev: true` dans le lockfile.

## Décision

- **A (migrer vers Tailwind v4) — différée.** C'est la correction réelle, mais c'est une migration front non triviale ; elle n'a pas sa place sur le chemin critique du go-live HGGSP.
- **C (fusion par un administrateur malgré le check requis) — refusée.** Aucun contournement du ruleset.
- **B (exception d'audit) — acceptable, temporairement**, parce qu'elle est **plus étroite que le problème** : elle n'accepte l'échec de `npm audit` que si
  l'ensemble des vulnérabilités est exactement celui décrit ci-dessus, et refuse tout le reste.

## Ce que fait la politique (`scripts/ci/cockpit_audit_policy.py`)

Le contrôle lit réellement le JSON de `npm audit --json` et le lockfile. Il ne retourne `PASS_WITH_EXACT_TEMPORARY_EXCEPTION` que si **toutes** les conditions sont réunies :

1. l'audit de production est propre (0 vulnérabilité, toutes sévérités) ;
2. l'avis exact est présent sur `braces` (source, nom, URL, plage `<=3.0.3`, sévérité high) ;
3. chaque vulnérabilité remonte exclusivement à cet avis et est de sévérité high ; aucune critique ;
4. la population est exactement celle des sept paquets connus : un paquet de plus qui dépendrait de `braces` est un refus, même avec la même racine ;
5. aucun correctif n'est disponible (`fixAvailable` à `true`, ou nommant `braces`) ;
6. `braces` et les sept paquets sont `dev: true` dans le lockfile, et présents ;
7. la date est antérieure à l'échéance.

Il refuse sinon, avec la raison. Il refuse aussi si l'audit complet devient propre (l'exception est obsolète : la supprimer). Un JSON malformé est refusé.

## Ce qui est volontairement interdit

`npm audit || true`, `continue-on-error`, `--audit-level=critical` ou `moderate`, `--omit=dev` comme seul audit, désactivation de l'audit, liste blanche générale de sévérité ou de paquet,
masquage de la sortie (la sortie lisible de `npm audit` est toujours imprimée), downgrade forcé de Next, Tailwind ou ESLint. La CI, la CI locale et leur méta-test de topologie
(`scripts/tests/test-ci-local-failsafe.sh`) exigent la nouvelle commande, dans le même ordre, avec échec injecté vérifié.

## Sortie, avant le 2026-10-17

Choisir entre : une mise à jour amont devenue disponible (la politique devient rouge d'elle-même et exige la suppression de l'exception), ou la migration Tailwind v4 correctement qualifiée,
puis **supprimer la politique** et rétablir `npm audit`. Après l'échéance, la CI est rouge tant que l'exception existe.

## Qualification

- `scripts/tests/test_cockpit_audit_policy.py` : 40 tests hermétiques. PASS : l'avis seul, en développement, avant l'échéance (et à la seconde exacte de l'échéance).
  FAIL : braces en production ; autre HIGH ; CRITICAL ; avis absent mais audit rouge ; autre avis ou plage sur `braces` ; date après l'échéance ; JSON malformé ;
  audit de production rouge ; population élargie ou réduite ; sévérité différente à racine identique ; compteur critique ; correctif disponible ; audit propre ;
  lockfile incomplet. Onze mutations volontaires de la politique font chacune échouer au moins un test.
- Sur les données réelles de `main` : `COCKPIT_AUDIT_POLICY=PASS_WITH_EXACT_TEMPORARY_EXCEPTION`, et refus après l'échéance.
- `test-ci-local-failsafe.sh` : 51 passed ; `test-ci-local-topology.sh` : vert.
