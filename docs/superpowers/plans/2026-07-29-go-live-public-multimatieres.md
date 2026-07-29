# Go-live public multi-matières Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Livrer Nexus/ARIA sur le serveur actuel avec SSO Nexus, 59 collections substantiellement couvertes, retrieval canonique, réponses OpenRouter citées et exploitation vérifiée.

**Architecture:** Le cockpit Next.js authentifie l'utilisateur par le SSO Nexus et appelle uniquement `rag-engine` via les contrats générés depuis `packages/contracts`. `rag-pedago` prépare et signe les paquets après `quality → gate → panel`, puis un publisher `rag-engine` les vérifie avant écriture dans l'index pgvector servi.

La présente PR documentaire constitue le LOT 33 ; l'exécution commence au
LOT 34 et se termine au LOT 40.

**Tech Stack:** Python 3.11, Pydantic, FastAPI, PostgreSQL/pgvector, Redis, Next.js/React/TypeScript, Auth.js/JWT, OpenRouter HTTP API, Docker Compose, Nginx, pytest, Vitest, Playwright, ruff, mypy, ESLint.

---

## Protocole d'exécution

- Chaque chunk est un lot indépendant : nouvelle branche, nouvelle PR et
  `docs/reports/lot_<n>_*.md`.
- Chaque tâche suit RED → GREEN → refactor → validations ciblées → commit.
- `bash scripts/ci-local.sh` doit être vert avant chaque PR.
- Aucun verrou de production n'est levé avant le Chunk 6.
- Les échecs préexistants ne sont plus tolérés implicitement : ils doivent
  être corrigés ou prouvés et bloquer la release.
- Les modifications du site principal nécessaires au SSO sont une dépendance
  externe au dépôt RAG ; le contrat et le simulateur sont développés ici,
  mais le go-live reste bloqué tant que le bridge réel n'est pas déployé.

## Cartographie des fichiers cibles

| Responsabilité | Fichiers |
|---|---|
| Contrats Python | `packages/contracts/src/nexus_contracts/{chat,identity,publication}.py` |
| Schémas générés | `packages/contracts/schema/*.json`, `services/cockpit/src/generated/contracts.ts` |
| Cockpit | `services/cockpit/src/app/**`, `services/cockpit/src/server/**` |
| Retrieval/chat | `services/rag-engine/src/ingestor/{retrieval_service,chat_endpoint}.py` |
| Génération | `services/rag-engine/src/ingestor/generation/*.py` |
| Staging/publication | `services/rag-pedago/rag_pedago/publication/**`, `services/rag-engine/src/ingestor/publication_endpoint.py` |
| Gouvernance runtime | `services/rag-pedago/scripts/export_runtime_governance.py`, `services/rag-engine/src/ingestor/runtime_governance.py` |
| Couverture | `services/rag-pedago/configs/substantive_coverage.yml`, `services/rag-pedago/scripts/substantive_coverage_gate.py` |
| Production | `services/rag-engine/infra/docker-compose.nexus-prod.yml`, `services/rag-engine/infra/nginx/*.conf.template` |

## Chunk 1: LOT 34 — baseline reproductible et CI sincère

### Task 1: Rendre la CI strictement fail-closed

**Files:**
- Create: `scripts/lib/ci-common.sh`
- Modify: `scripts/ci-local.sh`
- Modify: `scripts/tests/test-ci-local-failsafe.sh`

- [ ] **Step 1: écrire les tests shell en échec**

Ajouter des tests comportementaux qui sourcent `ci-common.sh` : un faux
Python 3.10 fait échouer `require_python_311`, un faux Python 3.11 passe et
une commande factice retournant 7 est propagée par `run_checked`. Conserver
aussi l'assertion d'absence de tolérance :

```bash
! grep -q 'pre-existing failure(s) — acceptable' scripts/ci-local.sh
```

- [ ] **Step 2: exécuter le test et constater l'échec**

Run: `bash scripts/tests/test-ci-local-failsafe.sh`

Expected: FAIL car `ci-common.sh` et les fonctions n'existent pas.

- [ ] **Step 3: supprimer la tolérance et imposer Python 3.11**

Créer les deux fonctions isolables, faire retourner à `run_pedago` le vrai
code de `make test` et appeler `require_python_311` au démarrage. Le target
cockpit appartient à la Task 4.

- [ ] **Step 4: valider les garde-fous**

Run: `bash scripts/tests/test-ci-local-failsafe.sh`

Expected: PASS.

- [ ] **Step 5: committer**

```bash
git add scripts/lib/ci-common.sh scripts/ci-local.sh scripts/tests/test-ci-local-failsafe.sh
git commit -m "ci: rends la validation locale strictement bloquante"
```

### Task 2: Faire compiler le cockpit depuis Git seul

**Files:**
- Modify: `.gitignore`
- Add: `services/cockpit/src/data/collections.json`
- Add: `services/cockpit/src/data/sources.json`
- Create: `scripts/tests/test-cockpit-clean-build.sh`

- [ ] **Step 1: écrire le test d'archive propre**

Le script crée un répertoire temporaire, extrait l'arbre Git donné par
`COCKPIT_BUILD_TREE` (défaut `HEAD`), exécute `npm ci` puis `npm run build`,
et nettoie par `trap`.

- [ ] **Step 2: prouver l'échec initial**

Run: `bash scripts/tests/test-cockpit-clean-build.sh`

Expected: FAIL avec `Cannot find module '@/data/collections.json'`.

- [ ] **Step 3: versionner les données de référence**

Conserver les JSON sous `src/data/`, restreindre `.gitignore` aux répertoires
runtime réellement générés, puis exécuter :

```bash
git add .gitignore scripts/tests/test-cockpit-clean-build.sh
git add -f services/cockpit/src/data/collections.json services/cockpit/src/data/sources.json
```

- [ ] **Step 4: valider l'archive**

Run: `COCKPIT_BUILD_TREE="$(git write-tree)" bash scripts/tests/test-cockpit-clean-build.sh`

Expected: PASS.

- [ ] **Step 5: committer**

```bash
git add .gitignore services/cockpit scripts/tests/test-cockpit-clean-build.sh
git commit -m "cockpit: rends le build reproductible depuis Git"
```

### Task 3: Fermer lint, tests et vulnérabilités cockpit

**Files:**
- Modify: `services/cockpit/package.json`
- Modify: `services/cockpit/package-lock.json`
- Modify: `services/cockpit/eslint.config.js`
- Modify: `services/cockpit/src/components/ui/sidebar.tsx`
- Modify: `services/cockpit/src/lib/api.ts`
- Create: `services/cockpit/src/lib/api.test.ts`
- Create: `services/cockpit/vitest.config.ts`

- [ ] **Step 1: ajouter un test qui interdit le fallback de production**

```ts
it('échoue explicitement quand l’API production est indisponible', async () => {
  vi.stubEnv('MODE', 'production')
  await expect(search('graphes', 'terminale', 'eleve')).rejects.toThrow(
    'RAG_API_UNAVAILABLE',
  )
})
```

- [ ] **Step 2: exécuter séparément lint, test et audit**

Run:

```bash
npm run lint
npm test
npm audit --omit=dev
```

Expected: codes non nuls distincts ; 8 erreurs lint, script test absent et
2 vulnérabilités élevées.

- [ ] **Step 3: appliquer le minimum sûr**

Configurer l'exception Fast Refresh uniquement pour les composants UI
générés, remplacer `Math.random()` par une largeur déterministe issue de
`useId`, ajouter Vitest, retirer les mocks en production et mettre à jour les
dépendances vers les versions corrigées. `sidebar.tsx` ne reçoit aucune
nouvelle responsabilité : seule l'expression de largeur est remplacée.

- [ ] **Step 4: valider**

Run: `npm run lint && npm test -- --run && npm run build && npm audit --omit=dev`

Expected: PASS et `0 high`, `0 critical`.

- [ ] **Step 5: committer**

```bash
git add services/cockpit
git commit -m "cockpit: ferme les écarts qualité de la baseline"
```

### Task 4: Ajouter le cockpit aux deux CI

**Files:**
- Create: `.nvmrc`
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/ci-local.sh`
- Modify: `scripts/tests/test-ci-local-failsafe.sh`
- Create: `docs/reports/lot_34_baseline_ci.md`

- [ ] **Step 1: écrire l'assertion de workflow**

Ajouter deux blocs d'assertions bornés : l'un extrait `run_cockpit()` dans
`ci-local.sh`, l'autre le job YAML `cockpit`. Chacun doit contenir `npm ci`,
`npm run lint`, `npm test -- --run`, `npm run build` et
`npm audit --omit=dev`. Ajouter `.nvmrc` avec `22.12.0`.

- [ ] **Step 2: constater l'échec**

Run: `bash scripts/tests/test-ci-local-failsafe.sh`

Expected: FAIL sur l'absence du target local et du job GitHub.

- [ ] **Step 3: ajouter le job `cockpit` et le target local**

Utiliser Node `22.12.0` via `actions/setup-node`, cache npm et `npm ci`.

- [ ] **Step 4: exécuter la CI complète et consigner les nombres**

Run: `bash scripts/ci-local.sh`

Expected: tous les targets PASS, sans clause d'exception.

Renseigner `lot_34_baseline_ci.md` avec SHA, versions Python/Node/npm,
commandes, nombres de tests, preuve du build depuis l'arbre Git, résultat
`npm audit` et résumé de chaque target CI.

- [ ] **Step 5: committer**

```bash
git add .nvmrc .github/workflows/ci.yml scripts docs/reports/lot_34_baseline_ci.md
git commit -m "ci: contrôle le cockpit dans chaque pipeline"
```

## Chunk 2: LOT 35 — contrats canoniques, Next.js et SSO Nexus

### Task 5: Versionner les contrats conversation et identité

**Files:**
- Create: `docs/adr/ADR-0021-contrat-conversationnel-nexus.md`
- Create: `docs/adr/ADR-0022-sso-nexus-aria.md`
- Create: `packages/contracts/src/nexus_contracts/chat.py`
- Create: `packages/contracts/src/nexus_contracts/identity.py`
- Modify: `packages/contracts/src/nexus_contracts/__init__.py`
- Modify: `packages/contracts/pyproject.toml`
- Create: `packages/contracts/tests/test_chat_contract.py`
- Create: `packages/contracts/tests/test_identity_contract.py`
- Create: `packages/contracts/tests/fixtures/chat_request_v1.json`
- Create: `packages/contracts/tests/fixtures/chat_response_v1.json`
- Create: `packages/contracts/tests/fixtures/chat_stream_events_v1.json`
- Create: `packages/contracts/tests/fixtures/chat_stream_events_invalid_v1.json`
- Create: `packages/contracts/tests/fixtures/internal_identity_v1.json`
- Create: `scripts/tests/test-adr-metadata.sh`

- [ ] **Step 1: écrire les tests de schéma**

```python
def test_chat_response_requires_grounded_citations() -> None:
    with pytest.raises(ValidationError):
        ChatResponse(answer="...", citations=[], refused=False)
```

Tester `ChatRequest` avec profil, message, conversation bornée et options ;
`ChatResponse` avec citations, avertissements, filtres appliqués et métadonnées
d'audit non sensibles ; `InternalIdentity` avec sujet pseudonyme, audience,
issuer, expiration, `jti`, tenant, niveau, profil pédagogique et rôle parmi
les cinq rôles autorisés. Tester `ChatStreamEvent` (`accepted`, `heartbeat`,
`validated`, `answer_delta`, `done`, `error`) et la machine d'état :
`accepted → heartbeat* → validated → answer_delta* → done`, ou `error`
terminal. Interdire delta avant validation, terminal multiple, événement
après terminal et flux sans terminal. `done` transporte le `ChatResponse`
canonique final. Valider fixtures valides/invalides et round-trip sans perte.
ADR-0021 documente SSE, tamponnage, validation avant émission et ordre.

- [ ] **Step 2: constater RED**

Run: `pytest packages/contracts/tests/test_chat_contract.py packages/contracts/tests/test_identity_contract.py -q`

Expected: FAIL sur imports inexistants.

- [ ] **Step 3: implémenter les modèles `extra="forbid"`**

Un `ChatResponse` non refusé exige au moins une citation ; un refus exige un
code de refus et ne prétend pas fournir une réponse factuelle. Tous les
modèles utilisent `extra="forbid"`. Monter `nexus-contracts` en `0.3.0`.

- [ ] **Step 4: valider puis refactorer contrats et ADR**

Run: `python -m pytest packages/contracts/tests -q && bash scripts/tests/test-adr-metadata.sh`

Expected: PASS ; ADR numérotés, statut `accepté`, contexte, décision et
conséquences présents. Extraire tout validateur partagé plutôt que dupliquer
les règles entre modèles.

- [ ] **Step 5: committer**

```bash
git add packages/contracts docs/adr/ADR-0021* docs/adr/ADR-0022* scripts/tests/test-adr-metadata.sh
git commit -m "contracts: publie les contrats conversation et identité"
```

### Task 6: Générer JSON Schema et TypeScript

**Files:**
- Create: `packages/contracts/scripts/export_schemas.py`
- Create: `packages/contracts/schema/{retrieval-request,retrieval-response,chat-request,chat-response,chat-stream-event,internal-identity}.json`
- Create: `packages/contracts/tests/test_schema_export.py`
- Create: `services/cockpit/scripts/generate-contracts.mjs`
- Create: `services/cockpit/src/generated/contracts.ts`
- Create: `services/cockpit/src/generated/validators.ts`
- Create: `services/cockpit/src/generated/contracts.test-d.ts`
- Create: `services/cockpit/src/generated/validators.test.ts`
- Modify: `services/cockpit/package.json`
- Modify: `services/cockpit/package-lock.json`

- [ ] **Step 1: tester la reproductibilité**

Exporter deux fois dans deux dossiers temporaires et comparer récursivement
les octets ; vérifier les six JSON attendus et leurs `$id` versionnés.

- [ ] **Step 2: constater l'absence du générateur**

Run: `pytest packages/contracts/tests/test_schema_export.py -q`

Expected: FAIL sur module absent.

- [ ] **Step 3: implémenter l'export trié et la génération TypeScript**

Le script TypeScript consomme uniquement les JSON Schema versionnés. Il
génère aussi des validateurs runtime Ajv. Les tests construisent les six
types valides, chaque variante de stream, une séquence valide et font rejeter
champs supplémentaires et séquences invalides.

- [ ] **Step 4: vérifier et refactorer la génération**

Run:

```bash
npm run contracts:check
npm test -- --run src/generated/validators.test.ts
npm run typecheck
if rg "interface (Retrieval|Chat|InternalIdentity)" services/cockpit/src --glob '!generated/contracts.ts'; then exit 1; fi
```

Expected: génération sans diff et aucune occurrence hors fichier généré ;
canonicalisation et écriture de fichiers restent dans deux fonctions
distinctes.

- [ ] **Step 5: committer**

```bash
git add packages/contracts services/cockpit
git commit -m "contracts: génère le client TypeScript canonique"
```

### Task 7: Ajouter le shell Next.js sans casser le cockpit Vite

**Files:**
- Create: `services/cockpit/next.config.ts`
- Create: `services/cockpit/src/app/layout.tsx`
- Create: `services/cockpit/src/app/page.tsx`
- Create: `services/cockpit/src/app/globals.css`
- Modify: `services/cockpit/package.json`
- Modify: `services/cockpit/package-lock.json`
- Create: `services/cockpit/src/app/page.test.tsx`

- [ ] **Step 1: écrire le test de rendu sans accès API direct**

Le test rend la page avec une session simulée et vérifie qu'aucun token ou
URL interne n'apparaît.

- [ ] **Step 2: constater RED**

Run: `npm test -- --run src/app/page.test.tsx`

Expected: FAIL, arborescence Next inexistante.

- [ ] **Step 3: migrer avec `git mv` et installer Next**

Ajouter Next sans changer encore le script `build` Vite : `page.tsx` enveloppe
le `Home` existant et `globals.css` importe temporairement `../index.css`.
Installer Next, mais conserver tous les fichiers Vite jusqu'à la Task 7b.

- [ ] **Step 4: valider et refactorer**

Run: `npm run lint && npm test -- --run && npm run build`

Expected: PASS du cockpit Vite existant et tests du shell Next ;
`layout.tsx` reste sans logique métier.

- [ ] **Step 5: committer**

```bash
git add -A services/cockpit
git commit -m "cockpit: prépare le shell Next.js"
```

### Task 7b: Migrer tous les consommateurs vers les types générés

**Files:**
- Create: `services/cockpit/src/types/ui.ts`
- Create: `services/cockpit/src/lib/bff-client.ts`
- Modify: `services/cockpit/tsconfig.json`
- Modify: `services/cockpit/eslint.config.js`
- Move: `services/cockpit/src/pages/Home.tsx` → `services/cockpit/src/app/HomeClient.tsx`
- Modify: `services/cockpit/src/app/page.tsx`
- Move: `services/cockpit/src/index.css` → `services/cockpit/src/app/globals.css`
- Modify: `services/cockpit/src/sections/CollectionsSection.tsx`
- Modify: `services/cockpit/src/sections/GovernanceSection.tsx`
- Modify: `services/cockpit/src/sections/IngestionSection.tsx`
- Modify: `services/cockpit/src/sections/OverviewSection.tsx`
- Modify: `services/cockpit/src/sections/ReviewSection.tsx`
- Modify: `services/cockpit/src/sections/SearchSection.tsx`
- Modify: `services/cockpit/package.json`
- Modify: `services/cockpit/package-lock.json`
- Delete: `services/cockpit/index.html`
- Delete: `services/cockpit/vite.config.ts`
- Delete: `services/cockpit/tsconfig.app.json`
- Delete: `services/cockpit/tsconfig.node.json`
- Delete: `services/cockpit/src/main.tsx`
- Delete: `services/cockpit/src/App.tsx`
- Delete: `services/cockpit/src/App.css`
- Delete: `services/cockpit/src/lib/api.ts`
- Delete: `services/cockpit/src/types/rag.ts`
- Create: `services/cockpit/src/lib/bff-client.test.ts`

- [ ] **Step 1: écrire le test d'interdiction des appels directs**

Le test échoue si un composant appelle `fetch` vers une base externe ou
importe les anciens modules ; les réponses sont validées par
`generated/validators.ts`.

- [ ] **Step 2: constater RED**

Run: `npm test -- --run src/lib/bff-client.test.ts`

Expected: FAIL sur les imports et appels legacy actuels.

- [ ] **Step 3: séparer UI locale et contrats partagés**

Déplacer seulement labels/états de présentation vers `types/ui.ts`, utiliser
les contrats générés pour les données partagées, router tous les appels par
les chemins BFF relatifs, basculer les scripts sur Next et supprimer les
résidus Vite. Supprimer le wrapper CSS temporaire avant `git mv` de
`index.css`; déplacer `Home.tsx` vers `HomeClient.tsx` avec `git mv` et garder
`page.tsx` comme composant serveur fin.

- [ ] **Step 4: valider et refactorer**

Run: `npm test -- --run && npm run typecheck && npm run build`

Expected: PASS ; aucun import de `lib/api` ou `types/rag`.

- [ ] **Step 5: committer**

```bash
git add -A services/cockpit
git commit -m "cockpit: consomme uniquement les contrats générés"
```

### Task 8a: Vérifier le SSO et émettre l'identité interne

**Files:**
- Create: `services/cockpit/src/auth.ts`
- Create: `services/cockpit/src/app/api/auth/[...nextauth]/route.ts`
- Create: `services/cockpit/src/server/sso-verifier.ts`
- Create: `services/cockpit/src/server/internal-token.ts`
- Create: `services/cockpit/src/server/replay-store.ts`
- Create: `services/cockpit/src/server/revocation-store.ts`
- Create: `services/cockpit/src/server/session-rotation.ts`
- Create: `services/cockpit/src/server/sso-verifier.test.ts`
- Modify: `services/cockpit/package.json`
- Modify: `services/cockpit/package-lock.json`
- Create: `services/cockpit/.env.example`

- [ ] **Step 1: tester toutes les frontières d'identité**

Tester signature, `iss`, `aud`, `exp`, `jti`, rejeu, révocation en Redis,
rotation de session, rôle, tenant, niveau, profil pédagogique et
pseudonymisation ; deux tenants ne peuvent partager une session.

- [ ] **Step 2: constater RED**

Run: `npm test -- --run src/server/sso-verifier.test.ts`

Expected: FAIL sur modules absents.

- [ ] **Step 3: séparer vérification, anti-rejeu et émission**

Auth.js reçoit le jeton du bridge Nexus, `sso-verifier` le vérifie,
`replay-store` consomme le `jti` dans Redis et `internal-token` émet un jeton
court sans email. `revocation-store` bloque les sessions révoquées et
`session-rotation` remplace l'identifiant selon une période fixée. Configurer
cookies `Secure`, `HttpOnly`, `SameSite=Lax` et CSRF Auth.js.

- [ ] **Step 4: valider et refactorer**

Run: `npm test -- --run src/server/sso-verifier.test.ts && npm run typecheck`

Expected: PASS ; aucun fichier serveur manuel ne dépasse 250 lignes.

- [ ] **Step 5: committer**

```bash
git add services/cockpit
git commit -m "cockpit: vérifie l’identité SSO Nexus"
```

### Task 8b: Raccorder le BFF et l'interface

**Files:**
- Create: `services/cockpit/src/server/rag-client.ts`
- Create: `services/cockpit/src/server/sse-parser.ts`
- Create: `services/cockpit/src/server/sse-parser.test.ts`
- Create: `services/cockpit/src/app/api/chat/route.ts`
- Create: `services/cockpit/src/app/api/chat/route.test.ts`
- Create: `services/cockpit/src/app/api/health/route.ts`
- Create: `services/cockpit/src/components/chat/ChatClient.tsx`
- Create: `services/cockpit/src/components/chat/ChatClient.test.tsx`
- Modify: `services/cockpit/src/app/page.tsx`

- [ ] **Step 1: tester proxy et consommateur UI**

Une session absente donne 401, une session valide appelle seulement
`RAG_ENGINE_INTERNAL_URL`, deux identités restent isolées et l'UI n'utilise
que `/api/chat`. Le parser teste fragmentation arbitraire, événement inconnu,
ordre invalide, interruption, annulation et contre-pression.

- [ ] **Step 2: constater RED**

Run: `npm test -- --run src/server/sse-parser.test.ts src/app/api/chat/route.test.ts src/components/chat/ChatClient.test.tsx`

Expected: FAIL sur modules absents.

- [ ] **Step 3: implémenter le vérificateur et le proxy**

Le BFF consomme l'identité déjà vérifiée, transmet le jeton interne et valide
chaque événement avec `generated/validators.ts` et la machine d'état avant de
le relayer en conservant `text/event-stream`. Aucun `answer_delta` n'est
relayé avant `validated`. `rag-client` ne gère que transport, validation SSE,
timeout et erreurs ; l'UI ne connaît aucune URL interne.

- [ ] **Step 4: valider, refactorer et contrôler les secrets**

Run:

```bash
npm test -- --run
npm run build
if rg "OPENROUTER_API_KEY|RAG_.*TOKEN|RAG_ENGINE_INTERNAL_URL" services/cockpit/.next/static; then exit 1; fi
```

Expected: tests/build PASS, aucune occurrence et `rag-client.ts` limité au
transport/validation runtime.

- [ ] **Step 5: committer**

```bash
git add services/cockpit
git commit -m "cockpit: raccorde le SSO Nexus au BFF"
```

### Task 8c: Clore le lot contrats/SSO

**Files:**
- Create: `docs/reports/lot_35_contracts_sso.md`
- Create: `services/cockpit/playwright.config.ts`
- Create: `services/cockpit/e2e/sso.spec.ts`
- Modify: `services/cockpit/package.json`
- Modify: `services/cockpit/package-lock.json`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: ajouter contrats générés et build Next à la CI**

Le job cockpit exécute `contracts:check`, typecheck, lint, tests, build et
l'E2E SSO. Ajouter le script `test:e2e:sso` qui cible explicitement
`e2e/sso.spec.ts`.

- [ ] **Step 2: exécuter la CI locale complète**

Run: `bash scripts/ci-local.sh`

Expected: tous les targets PASS.

- [ ] **Step 3: vérifier le bridge réel en environnement de validation**

Run: `npm run test:e2e:sso`

Expected: session Nexus créée, révocation propagée et isolation tenant PASS.

- [ ] **Step 4: consigner versions, tests et dépendance externe**

Le rapport référence les ADR, la version `0.3.0`, les golden fixtures, les
résultats CI et l'URL de preuve du bridge sans exposer de token.

- [ ] **Step 5: committer**

```bash
git add .github/workflows/ci.yml services/cockpit docs/reports/lot_35_contracts_sso.md
git commit -m "docs: consigne la convergence contrats et SSO"
```

## Chunk 3: LOT 36 — staging, panel signé et publication gouvernée

### Task 9: Définir le paquet de publication signé

**Files:**
- Create: `docs/adr/ADR-0023-publication-signee-pgvector.md`
- Create: `packages/contracts/src/nexus_contracts/staging.py`
- Create: `packages/contracts/src/nexus_contracts/publication.py`
- Create: `packages/contracts/src/nexus_contracts/governance.py`
- Create: `packages/contracts/tests/test_publication.py`
- Create: `packages/contracts/tests/test_governance_snapshot.py`
- Create: `packages/contracts/tests/fixtures/publication_package_v1.json`
- Create: `packages/contracts/tests/fixtures/governance_snapshot_production_v1.json`
- Create: `packages/contracts/tests/fixtures/governance_snapshot_validation_v1.json`
- Create: `packages/contracts/schema/staging-package.json`
- Create: `packages/contracts/schema/publication-package.json`
- Create: `packages/contracts/schema/governance-snapshot.json`
- Modify: `packages/contracts/scripts/export_schemas.py`
- Modify: `packages/contracts/tests/test_schema_export.py`
- Modify: `packages/contracts/src/nexus_contracts/__init__.py`
- Modify: `packages/contracts/pyproject.toml`
- Modify: `services/cockpit/src/generated/contracts.ts`
- Modify: `services/cockpit/src/generated/validators.ts`
- Modify: `services/cockpit/src/generated/contracts.test-d.ts`
- Modify: `services/cockpit/src/generated/validators.test.ts`
- Modify: `services/cockpit/scripts/generate-contracts.mjs`

- [ ] **Step 1: tester canonicalisation et altération**

Tester les champs obligatoires du staging : identifiant stable, empreintes
binaire/texte/chunks, provenance/date, source déclarée, preuve de droits,
collection cible et versions des extracteurs, chunkers et modèles. Tester
aussi versions de règles, trois verdicts nommés, décision, `key_id` et
signature du paquet. La fixture de gouvernance couvre version, émission,
expiration, `environment` (`production|validation`), digest d'autorisation
obligatoire uniquement en validation, verrous, `key_id` et signature.
Le digest est exactement 64 hex minuscules ; il est interdit en production.
Mutation d'`environment` ou du digest après signature invalide Ed25519.
Le test d'export prouve que le générateur TypeScript auto-découvre chaque
JSON Schema sans liste manuelle oubliable.

- [ ] **Step 2: constater RED**

Run: `pytest packages/contracts/tests/test_publication.py packages/contracts/tests/test_governance_snapshot.py -q`

Expected: FAIL sur contrats publication et gouvernance absents.

- [ ] **Step 3: implémenter manifestes et signatures Ed25519**

Canonicaliser les octets, signer Ed25519, charger la clé privée depuis un
secret obligatoire et vérifier par `key_id` dans un trousseau public
rotatable. La clé absente bloque. Monter `nexus-contracts` en `0.4.0` et
régénérer JSON Schema/TypeScript.

- [ ] **Step 4: valider**

Run:

```bash
pytest packages/contracts/tests -q
npm --prefix services/cockpit run contracts:check
npm --prefix services/cockpit test -- --run src/generated/validators.test.ts
npm --prefix services/cockpit run typecheck
```

Expected: PASS, y compris altération manifest/chunk/verdict.

- [ ] **Step 5: committer**

```bash
git add packages/contracts services/cockpit/scripts/generate-contracts.mjs services/cockpit/src/generated docs/adr/ADR-0023*
git commit -m "contracts: définit le paquet de publication signé"
```

### Task 10: Remplacer l'écriture pré-revue par un staging

**Files:**
- Create: `services/rag-pedago/rag_pedago/publication/staging_store.py`
- Create: `services/rag-pedago/tests/unit/test_staging_store.py`
- Create: `services/rag-engine/src/ingestor/staging_gateway.py`
- Create: `services/rag-engine/tests/test_staging_service.py`
- Create: `scripts/check-pgvector-writers.sh`
- Create: `scripts/tests/test-pgvector-writers.sh`
- Modify: `services/rag-engine/src/ingestor/ingest_v2_endpoint.py`
- Modify: `services/rag-engine/src/ingestor/ingest_v2.py`
- Modify: `services/rag-engine/src/ingestor/api.py`
- Modify: `services/rag-engine/src/ingestor/admin_api.py`
- Modify: `services/rag-engine/src/ingestor/tasks.py`
- Modify: `services/rag-engine/src/ingestor/database.py`
- Modify: `services/rag-engine/tests/test_ingest_v2.py`
- Modify: `services/rag-engine/tests/test_ingestion_embedding_path_audit_contract.py`

- [ ] **Step 1: écrire le test d'interdiction pgvector**

Faire échouer si upload, URL, Drive ou toute route legacy appelle pgvector.
Le script statique autorise les écritures `rag_chunks` uniquement dans le
futur `publication_repository.py`.

- [ ] **Step 2: constater l'appel DB actuel**

Run: `pytest services/rag-engine/tests/test_staging_service.py -q`

Expected: FAIL et inventaire exhaustif de tous les writers actuels.

- [ ] **Step 3: établir le handoff contractuel vers le staging contrôlé**

Le volume `NEXUS_STAGING_ROOT` contient uniquement des `StagingPackage`
canoniques. `staging_gateway` dépose par écriture temporaire, `fsync` et
renommage atomique ; `staging_store` de `rag-pedago` en est le lecteur
autoritatif. Désactiver ou rediriger tous les writers legacy. Aucun chemin
machine absolu.

- [ ] **Step 4: valider**

Run:

```bash
pytest services/rag-pedago/tests/unit/test_staging_store.py -q
pytest services/rag-engine/tests/test_staging_service.py services/rag-engine/tests/test_ingest_v2.py -q
bash scripts/tests/test-pgvector-writers.sh
```

Expected: PASS, zéro connexion pgvector et aucun writer hors allowlist.

- [ ] **Step 5: committer**

```bash
git add services/rag-pedago services/rag-engine scripts
git commit -m "ingestion: impose le staging avant pgvector"
```

### Task 11: Durcir URL et implémenter Drive dans le même staging

**Files:**
- Create: `services/rag-engine/src/ingestor/remote_fetch.py`
- Create: `services/rag-engine/src/ingestor/drive_source.py`
- Create: `services/rag-engine/tests/test_remote_fetch.py`
- Create: `services/rag-engine/tests/test_drive_source.py`
- Modify: `services/rag-engine/src/ingestor/ingest_v2_endpoint.py`

- [ ] **Step 1: écrire la matrice SSRF et Drive**

Tester DNS privé, IPv6, redirect public→privé, redirect chain, dépassement de
taille, MIME interdit, Drive sans droits, pagination Drive, export Google
Docs et Drive valide. Les trois voies doivent produire le même
`StagingPackage`, ne jamais appeler pgvector et ne jamais journaliser les
credentials.

- [ ] **Step 2: constater les échecs**

Run: `pytest services/rag-engine/tests/test_remote_fetch.py services/rag-engine/tests/test_drive_source.py -q`

Expected: FAIL, notamment route Drive 501.

- [ ] **Step 3: implémenter résolution/revalidation et adaptateur Drive**

Injecter résolveur et client HTTP pour tests déterministes ; revalider DNS et
règles de source après chaque redirection, streamer avec limite dure, sans
charger 50 MiB avant contrôle. L'adaptateur Drive applique les mêmes
contrôles MIME/taille/droits et charge ses credentials depuis un secret.

- [ ] **Step 4: valider**

Run: `pytest services/rag-engine/tests/test_remote_fetch.py services/rag-engine/tests/test_drive_source.py -q`

Expected: PASS.

- [ ] **Step 5: committer**

```bash
git add services/rag-engine/src/ingestor services/rag-engine/tests
git commit -m "rag-engine: sécurise les sources URL et Drive"
```

### Task 12: Raccorder quality, gate et panel unanime

**Files:**
- Create: `services/rag-pedago/rag_pedago/publication/package_builder.py`
- Create: `services/rag-pedago/tests/unit/test_publication_package_builder.py`
- Modify: `services/rag-pedago/agents/review_panel.py`
- Modify: `services/rag-pedago/agents/reviewers.py`
- Modify: `services/rag-pedago/configs/review_policy.yml`
- Modify: `services/rag-pedago/rag_pedago/imports/quality.py`
- Modify: `services/rag-pedago/rag_pedago/imports/gate.py`
- Modify: `services/rag-pedago/tests/unit/test_review_panel.py`

- [ ] **Step 1: tester exhaustivité, unanimité et quarantaine**

Tester tous les documents/chunks, experts exacts `rights`, `subject`,
`quality`, lisibilité/extraction, artefacts, cohérence taxonomique,
substance, droits/provenance, déduplication, secrets/PII, instructions
injectées, panel 2/3, reviewer en erreur, gate échoué et paquet positif 3/3.

- [ ] **Step 2: constater RED**

Run: `pytest services/rag-pedago/tests/unit/test_publication_package_builder.py services/rag-pedago/tests/unit/test_review_panel.py -q`

Expected: FAIL car le panel actuel ne produit pas le paquet Ed25519 complet.

- [ ] **Step 3: chaîner staging → quality → gate → panel → paquet**

Le builder refuse tout sous-ensemble, lie les rapports exhaustifs et ne signe
que `approved` unanime. Tout autre état reste en quarantaine hors pgvector.

- [ ] **Step 4: valider et refactorer**

Run: `pytest services/rag-pedago/tests/unit/test_publication_package_builder.py services/rag-pedago/tests/unit/test_review_panel.py -q`

Expected: PASS ; aucune écriture pgvector dans `rag-pedago`.

- [ ] **Step 5: committer**

```bash
git add services/rag-pedago
git commit -m "rag-pedago: signe les paquets approuvés à l’unanimité"
```

### Task 12b: Vérifier et publier transactionnellement

**Files:**
- Create: `services/rag-engine/src/ingestor/publication_repository.py`
- Create: `services/rag-engine/src/ingestor/publication_endpoint.py`
- Create: `services/rag-engine/tests/test_publication_endpoint.py`
- Create: `services/rag-engine/tests/integration/test_publication_pgvector.py`
- Modify: `services/rag-engine/src/ingestor/api.py`
- Delete: `services/rag-engine/src/ingestor/review_v2_endpoint.py`
- Delete: `services/rag-engine/tests/test_review_v2.py`

- [ ] **Step 1: tester les refus**

Refuser signature altérée, collection non instanciée et republication
incohérente. Tester succès, idempotence, concurrence, rollback DB et absence
de ligne partielle. Asserter que le publisher ne crée jamais les statuts
`needs_review` ou `reviewed`.

- [ ] **Step 2: constater RED**

Run: `pytest services/rag-engine/tests/test_publication_endpoint.py -q`

Expected: FAIL sur modules absents.

- [ ] **Step 3: construire puis vérifier avant transaction pgvector**

L'endpoint ne fait que sécurité/wiring. Le repository vérifie tout le paquet
avant d'ouvrir la transaction et écrit uniquement `published` avec
clé d'idempotence.

- [ ] **Step 4: vérifier la disparition du bypass humain**

Run:

```bash
pytest services/rag-engine/tests/test_publication_endpoint.py -q
pytest services/rag-engine/tests/integration/test_publication_pgvector.py -q
if rg "/review/v2/decide|human review" services/rag-engine/src; then exit 1; fi
bash scripts/tests/test-pgvector-writers.sh
```

Expected: PASS.

- [ ] **Step 5: committer**

```bash
git add -A services/rag-engine
git commit -m "rag-engine: publie uniquement les paquets approuvés"
```

### Task 13: Appliquer les verrous au runtime

**Files:**
- Create: `services/rag-pedago/scripts/export_runtime_governance.py`
- Create: `services/rag-pedago/tests/unit/test_runtime_governance_export.py`
- Modify: `docs/adr/ADR-0023-publication-signee-pgvector.md`
- Create: `services/rag-engine/src/ingestor/runtime_governance.py`
- Create: `services/rag-engine/tests/test_runtime_governance.py`
- Modify: `services/rag-engine/src/ingestor/api.py`
- Modify: `services/rag-engine/infra/.env.ci`

- [ ] **Step 1: tester snapshot absent, expiré et verrou fermé**

Snapshot absent/expiré/signature altérée donne 503 ; verrou fermé donne 403 ;
snapshot valide autorise. Un test parcourt toutes les routes montées et exige
une politique explicite. Un snapshot validation sans digest d'autorisation ou
présenté à un runtime production est refusé fail-closed. Tester digest
malformé, inconnu et divergent de l'artefact pointé par
`RAG_VALIDATION_AUTHORIZATION`.

- [ ] **Step 2: constater RED**

Run: `pytest services/rag-engine/tests/test_runtime_governance.py -q`

Expected: FAIL, middleware absent.

- [ ] **Step 3: exporter un snapshot signé et le vérifier fail-closed**

Consommer le `GovernanceSnapshot` défini à la Task 9, exporté et signé par le
control plane, distribué à
`RAG_GOVERNANCE_SNAPSHOT=/run/governance/runtime.json` et vérifié par trousseau
public rotatable. Exiger que `RAG_ENV` concorde avec l'environnement signé et,
en validation, comparer le digest signé à l'autorisation configurée. Mapper
explicitement chaque route à ses verrous requis ; `api.py` ne contient que le
wiring.

- [ ] **Step 4: valider**

Run:

```bash
pytest packages/contracts/tests/test_governance_snapshot.py -q
pytest services/rag-pedago/tests/unit/test_runtime_governance_export.py services/rag-engine/tests/test_runtime_governance.py -q
```

Expected: PASS.

- [ ] **Step 5: committer**

```bash
git add packages/contracts services/rag-pedago services/rag-engine docs/adr/ADR-0023-publication-signee-pgvector.md
git commit -m "rag-engine: applique la gouvernance au runtime"
```

### Task 13b: Clore le lot de publication

**Files:**
- Create: `docs/reports/lot_36_publication_gouvernee.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/ci-local.sh`

- [ ] **Step 1: ajouter les tests PostgreSQL et writers à la CI**

Le job engine démarre pgvector et exécute les intégrations sans skip.
`ci-local.sh` exécute aussi le garde writers et l'intégration contre son stack
PostgreSQL de test.

- [ ] **Step 2: exécuter les validations ciblées**

Run: `bash scripts/tests/test-pgvector-writers.sh && pytest services/rag-engine/tests/integration/test_publication_pgvector.py -q`

Expected: PASS.

- [ ] **Step 3: exécuter la CI complète**

Run: `bash scripts/ci-local.sh`

Expected: tous les targets PASS.

- [ ] **Step 4: consigner les preuves**

Le rapport lie contrat `0.4.0`, clés de test, handoff staging, matrice des
writers, tests SSRF/Drive, panel 3/3, rollback et CI.

- [ ] **Step 5: committer**

```bash
git add .github/workflows/ci.yml scripts/ci-local.sh docs/reports/lot_36_publication_gouvernee.md
git commit -m "docs: consigne la publication gouvernée"
```

## Chunk 4: LOT 37 — retrieval canonique et chat OpenRouter

### Task 14: Remplacer `/search/v2` par le contrat canonique

**Files:**
- Create: `services/rag-engine/src/ingestor/retrieval_service.py`
- Create: `services/rag-engine/src/ingestor/retrieval_endpoint.py`
- Create: `services/rag-engine/scripts/run_golden_queries.py`
- Create: `services/rag-engine/tests/test_golden_runner.py`
- Create: `services/rag-engine/tests/fixtures/golden_pg_seed.sql`
- Create: `services/rag-engine/configs/retrieval_quality.yml`
- Modify: `services/rag-engine/tests/golden_queries_lot24.json`
- Create: `services/rag-engine/tests/test_retrieval_endpoint.py`
- Modify: `services/rag-engine/src/ingestor/api.py`
- Modify: `services/rag-engine/src/ui/app_v2.py`
- Modify: `services/rag-engine/tests/test_catalogue_business_alignment.py`
- Modify: `services/rag-engine/tests/test_catalogue_v2_auth.py`
- Modify: `services/rag-engine/tests/test_embedding_model_artifact_contract.py`
- Modify: `services/rag-engine/tests/test_ingestion_embedding_path_audit_contract.py`
- Modify: `services/rag-engine/tests/test_prod_compose_config_mount.py`
- Move: `services/rag-engine/tests/test_retrieval_v2_endpoint.py` → `services/rag-engine/tests/test_retrieval_endpoint_legacy_migration.py`
- Modify: `services/rag-engine/tests/test_review_visibility.py`
- Modify: `services/rag-engine/tests/test_ui_app_v2_admin.py`
- Modify: `services/rag-engine/tests/test_ui_business_alignment.py`
- Modify: `services/rag-engine/tests/test_ui_runtime_dependency_lock.py`
- Delete: `services/rag-engine/src/ingestor/retrieval_v2_endpoint.py`

- [ ] **Step 1: tester profil, routing et réponse canonique**

Envoyer un `RetrievalRequest`, vérifier filtres imposés et
`RetrievalResponse` exact ; ajouter un test où le client tente d'élargir le
niveau. Ajouter un inventaire `rg` qui échoue sur toute référence runtime
résiduelle à `/search/v2` ou `retrieval_v2_endpoint`. Le golden runner utilise
un seed PostgreSQL déterministe, une identité fixe, des chunks/citations
oracles et échoue sur corpus vide, skip ou résultat incomplet.

- [ ] **Step 2: constater RED**

Run: `pytest services/rag-engine/tests/test_retrieval_endpoint.py -q`

Expected: FAIL, endpoint absent.

- [ ] **Step 3: implémenter service et endpoint fins**

L'endpoint valide le contrat et délègue ; le service résout la collection
depuis le profil et le catalogue, jamais depuis un filtre client arbitraire.
Migrer tous les consommateurs/tests listés et conserver une réponse 410
documentée pour l'ancienne route pendant une seule version.

- [ ] **Step 4: valider contrat et golden queries existantes**

Run:

```bash
pytest services/rag-engine/tests/test_retrieval_endpoint.py services/rag-engine/tests/test_retrieval_contract_adapter.py -q
pytest services/rag-engine/tests/test_golden_runner.py -q
pytest services/rag-engine/tests -q
python services/rag-engine/scripts/run_golden_queries.py services/rag-engine/tests/golden_queries_lot24.json --quality services/rag-engine/configs/retrieval_quality.yml
```

Expected: PASS et inventaire legacy vide hors test explicite 410.

- [ ] **Step 5: committer**

```bash
git add -A services/rag-engine
git commit -m "rag-engine: expose le retrieval Nexus canonique"
```

### Task 15: Implémenter le retrieval hybride et le cache sûr

**Files:**
- Move: `services/rag-engine/src/ingestor/hybrid_search.py` → `services/rag-engine/src/ingestor/hybrid_retrieval.py`
- Move: `services/rag-engine/tests/test_hybrid_search.py` → `services/rag-engine/tests/test_hybrid_retrieval_legacy.py`
- Create: `services/rag-engine/src/ingestor/retrieval_cache.py`
- Modify: `services/rag-engine/src/ingestor/retrieval_service.py`
- Modify: `services/rag-engine/pyproject.toml`
- Modify: `services/rag-engine/Makefile`
- Create: `services/rag-engine/infra/postgres/migrations/002_hybrid_fts.sql`
- Create: `services/rag-engine/tests/test_hybrid_retrieval.py`
- Create: `services/rag-engine/tests/integration/test_hybrid_fts_migration.py`
- Create: `services/rag-engine/tests/integration/test_hybrid_retrieval_pgvector.py`

- [ ] **Step 1: écrire les tests dense, lexical et fusion**

Le test réel insère des chunks publiés/quarantinés et prouve que seuls les
publiés ressortent. Tester retrait, quarantaine, droits modifiés, version de
publication et isolation tenant/profil dans le cache.

- [ ] **Step 2: constater RED**

Run: `pytest services/rag-engine/tests/test_hybrid_retrieval.py -q`

Expected: FAIL sur module absent.

- [ ] **Step 3: implémenter recherche vectorielle + FTS et fusion déterministe**

Préserver l'historique avec `git mv`, adapter l'implémentation dense/sparse/RRF
existante, raccorder `retrieval_service` et indexer FTS via migration
idempotente. Adapter pyproject, Makefile et tests ; un `rg` final interdit les
imports `hybrid_search`.

- [ ] **Step 4: valider unité et PostgreSQL réel**

Run: `pytest services/rag-engine/tests/test_hybrid_retrieval.py services/rag-engine/tests/integration/test_hybrid_fts_migration.py services/rag-engine/tests/integration/test_hybrid_retrieval_pgvector.py -q`

Expected: PASS sans skip lorsque le service CI PostgreSQL est présent.

- [ ] **Step 5: committer**

```bash
git add services/rag-engine
git commit -m "rag-engine: combine retrieval dense et lexical"
```

### Task 16: Ajouter evidence gate et client OpenRouter

**Files:**
- Create: `docs/adr/ADR-0024-generation-openrouter-gouvernee.md`
- Create: `services/rag-engine/src/ingestor/generation/evidence_gate.py`
- Create: `services/rag-engine/src/ingestor/generation/openrouter_client.py`
- Create: `services/rag-engine/src/ingestor/generation/model_policy.py`
- Create: `services/rag-engine/src/ingestor/generation/prompt_policy.py`
- Create: `services/rag-engine/src/ingestor/generation/quota.py`
- Create: `services/rag-engine/tests/test_evidence_gate.py`
- Create: `services/rag-engine/tests/test_openrouter_client.py`
- Create: `services/rag-engine/tests/fixtures/openrouter_model_evaluation.json`
- Create: `services/rag-engine/configs/openrouter_models.yml`
- Create: `services/rag-engine/configs/prompts/chat_v1.yml`

- [ ] **Step 1: tester preuves insuffisantes et résilience**

Tester zéro preuve, scores faibles, diversité insuffisante, contradiction,
profil incohérent, droits absents, citation inexploitable, timeout, 429, 5xx,
retries/backoff bornés, transitions du circuit breaker, budget/quota,
concurrence, réponse malformée et modèle hors allowlist/non évalué. Ajouter
un chemin nominal où un modèle dont la preuve d'évaluation est signée renvoie
une réponse structurée valide.

- [ ] **Step 2: constater RED**

Run: `pytest services/rag-engine/tests/test_evidence_gate.py services/rag-engine/tests/test_openrouter_client.py -q`

Expected: FAIL sur imports absents.

- [ ] **Step 3: implémenter policy, timeout et circuit breaker bornés**

N'envoyer à OpenRouter ni email, ni identifiant, ni historique non borné.
Versionner prompt et paramètres, minimiser les extraits, imposer budget,
quota et sémaphore de concurrence. Aucun fallback hors allowlist et aucun
modèle sans référence vers son rapport d'évaluation.

- [ ] **Step 4: valider**

Run: `pytest services/rag-engine/tests/test_evidence_gate.py services/rag-engine/tests/test_openrouter_client.py -q`

Expected: PASS.

- [ ] **Step 5: committer**

```bash
git add services/rag-engine docs/adr/ADR-0024-generation-openrouter-gouvernee.md
git commit -m "rag-engine: gouverne les appels OpenRouter"
```

### Task 17: Exposer le chat cité et valider les affirmations

**Files:**
- Create: `services/rag-engine/src/ingestor/generation/citation_validator.py`
- Create: `services/rag-engine/src/ingestor/generation/conversation_store.py`
- Create: `services/rag-engine/src/ingestor/generation/chat_stream.py`
- Create: `services/rag-engine/src/ingestor/internal_identity.py`
- Create: `services/rag-engine/src/ingestor/chat_service.py`
- Create: `services/rag-engine/src/ingestor/chat_endpoint.py`
- Create: `services/rag-engine/tests/test_chat_endpoint.py`
- Modify: `services/rag-engine/src/ingestor/api.py`

- [ ] **Step 1: écrire les tests de citation et refus**

Refuser une citation inconnue, un identifiant dupliqué, une réponse factuelle
sans citation et une sortie non conforme au JSON Schema. Tester identité
interne invalide, isolation utilisateur/tenant, historique borné et résumé
isolé, OpenRouter indisponible, streaming interrompu et refus fail-closed.
Ajouter le nominal complet identité valide→retrieval publié→gate
accepté→modèle évalué→`ChatResponse` citée.

- [ ] **Step 2: constater RED**

Run: `pytest services/rag-engine/tests/test_chat_endpoint.py -q`

Expected: FAIL sur endpoint absent.

- [ ] **Step 3: orchestrer identité → retrieval → gate → OpenRouter → validation**

Vérifier le jeton interne puis orchestrer le flux. Retourner toujours
`ChatResponse`, y compris pour les refus et indisponibilités prévues par le
contrat. `chat_stream` émet des événements SSE canoniques : il tamponne et
valide la réponse complète, puis seulement émet `answer_delta` et `done`.
Ne persister que l'état conversationnel pseudonymisé et borné.

- [ ] **Step 4: valider**

Run: `pytest services/rag-engine/tests/test_chat_endpoint.py -q`

Expected: PASS, aucun appel OpenRouter lorsque le gate refuse.

- [ ] **Step 5: committer**

```bash
git add services/rag-engine
git commit -m "rag-engine: génère des réponses strictement citées"
```

### Task 17b: Clore le lot retrieval et génération

**Files:**
- Create: `docs/reports/lot_37_retrieval_openrouter.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/ci-local.sh`

- [ ] **Step 1: ajouter PostgreSQL et golden queries aux CI**

Les deux CI exécutent migrations FTS, intégration hybride, golden queries et
tests chat sans skip.

- [ ] **Step 2: exécuter les validations ciblées**

Run: `pytest services/rag-engine/tests/integration/test_hybrid_fts_migration.py services/rag-engine/tests/integration/test_hybrid_retrieval_pgvector.py -q`

Expected: PASS.

- [ ] **Step 3: exécuter la CI complète**

Run: `bash scripts/ci-local.sh`

Expected: tous les targets PASS.

- [ ] **Step 4: consigner et refactorer**

Le rapport lie ADR, allowlist, prompt, résultats golden, cache, pannes,
isolation et CI. Aucun module manuel de génération ne dépasse 250 lignes.

- [ ] **Step 5: committer**

```bash
git add .github/workflows/ci.yml scripts/ci-local.sh docs/reports/lot_37_retrieval_openrouter.md
git commit -m "docs: consigne le retrieval et la génération gouvernés"
```

## Chunk 5: LOT 38 — substance et validation exhaustive des 59 collections

### Task 18: Construire la matrice de substance exhaustive

**Files:**
- Create: `services/rag-pedago/configs/substantive_coverage.yml`
- Create: `services/rag-pedago/configs/evaluation_thresholds.yml`
- Create: `services/rag-pedago/scripts/substantive_coverage_gate.py`
- Create: `services/rag-pedago/tests/unit/test_substantive_coverage_gate.py`
- Create: `docs/reports/lot_38_coverage_inventory.json`

- [ ] **Step 1: tester les faux verts**

Créer des fixtures pour référence générique, notion sans contenu, ressource
sans droits, collection non instanciée, paquet absent, chunk non publié,
golden query absente et évaluation manquante.

- [ ] **Step 2: constater RED**

Run: `pytest services/rag-pedago/tests/unit/test_substantive_coverage_gate.py -q`

Expected: FAIL sur script absent.

- [ ] **Step 3: calculer la chaîne de preuve par notion**

Le gate possède trois phases. `substance` exige
taxonomie→ressource→chunk staging→golden. `prepublication` ajoute
taxonomie→ressource→chunk staging→panel→paquet→golden. `final` ajoute
collection instanciée→chunk `published`→résultats d'évaluation. Les seuils
sont par collection, sans moyenne masquante : 100 % des notions substantielles,
au moins une requête positive par notion, trois négatives et trois confusions
par collection, recall@8 ≥ 0,95, citations valides = 100 %, fuite de profil =
0, affirmations non ancrées = 0 et refus insuffisants = 100 %.

- [ ] **Step 4: générer la baseline rouge honnête**

Run: `python services/rag-pedago/scripts/substantive_coverage_gate.py --phase prepublication --report docs/reports/lot_38_coverage_inventory.json`

Expected: exit non nul et inventaire exhaustif des écarts actuels.

- [ ] **Step 5: committer**

```bash
git add services/rag-pedago docs/reports/lot_38_coverage_inventory.json
git commit -m "rag-pedago: mesure la substance des 59 collections"
```

### Task 19: Qualifier les sources restantes

**Files:**
- Modify: `services/rag-pedago/configs/eduscol_sources.yml`
- Generate (runtime, ignored): `services/rag-pedago/data/ledger/source_validation.jsonl`
- Generate (runtime, ignored): `services/rag-pedago/data/reports/source_validation_latest.md`
- Modify: `docs/validation/source_validation_evidence.json`
- Create: `docs/reports/lot_38_sources_multimatieres.md`

- [ ] **Step 1: exécuter l'audit sans mutation**

Run: `cd services/rag-pedago && python -m agents.source_validator --plan`

Expected: liste complète des sources `to_verify` et preuves manquantes.

- [ ] **Step 2: vérifier chaque source contre son contenu réel**

Archiver empreinte, statut HTTP, portée pédagogique, droits et collections
réellement couvertes. Ne jamais promouvoir une simple page générique.

- [ ] **Step 3: recalculer les verdicts signés**

Run: `cd services/rag-pedago && python -m agents.source_validator --run`

Expected: seules les sources démontrées deviennent candidates.

- [ ] **Step 4: appliquer les verdicts puis régénérer la preuve**

Promouvoir dans `eduscol_sources.yml` uniquement les
`verified_candidate` signés, puis exécuter :

```bash
cd services/rag-pedago
python scripts/export_source_validation_evidence.py
python scripts/export_source_validation_evidence.py --check
```

Expected: PASS sans signature fabriquée.

- [ ] **Step 5: committer**

```bash
git add services/rag-pedago docs/validation docs/reports/lot_38_sources_multimatieres.md
git commit -m "rag-pedago: qualifie les sources multi-matières"
```

### Task 20: Constituer les corpus par collection

**Files:**
- Create/Modify: `corpus/catalogue/$collection_slug/manifest.yml` pour chaque slug du worklist
- Create/Modify: `corpus/catalogue/$collection_slug/resources/**`
- Create: `services/rag-pedago/tests/golden_queries/$collection_slug.json`
- Modify: `services/rag-pedago/agents/review_panel.py`
- Modify: `services/rag-pedago/tests/unit/test_review_panel.py`
- Create: `services/rag-pedago/scripts/stage_collection.py`
- Create: `services/rag-pedago/tests/unit/test_stage_collection.py`
- Create: `docs/reports/lot_38_collection_worklist.json`
- Modify: `docs/reports/lot_38_coverage_inventory.json`

- [ ] **Step 1: écrire les tests du worklist, stager et filtre panel**

Générer `lot_38_collection_worklist.json` avec les 59 slugs exacts, statut et
prochaine action. Tester que `stage_collection.py` produit un
`StagingPackage` canonique et que `review_panel --collection` n'examine que
ce paquet.

Run: `pytest services/rag-pedago/tests/unit/test_stage_collection.py services/rag-pedago/tests/unit/test_review_panel.py -q`

Expected: FAIL avant implémentation du stager et du filtre.

- [ ] **Step 2: implémenter les outils et traiter une collection**

Implémenter le worklist, le stager et le filtre jusqu'aux tests GREEN. Pour
chaque `$collection_slug`, ajouter les ressources qui enseignent chaque
notion, leur manifeste de droits et les golden queries positives, négatives
et de confusion.

Run: `pytest services/rag-pedago/tests/unit/test_stage_collection.py services/rag-pedago/tests/unit/test_review_panel.py -q`

Expected: PASS.

Committer les outils avant les 59 commits de contenu :

```bash
git add services/rag-pedago/scripts/stage_collection.py services/rag-pedago/tests/unit/test_stage_collection.py services/rag-pedago/agents/review_panel.py services/rag-pedago/tests/unit/test_review_panel.py docs/reports/lot_38_collection_worklist.json
git commit -m "rag-pedago: pilote le staging collection par collection"
```

- [ ] **Step 3: déposer en staging puis exécuter le gate substance**

Run:

```bash
python services/rag-pedago/scripts/stage_collection.py --collection "$collection_slug"
python services/rag-pedago/scripts/substantive_coverage_gate.py --phase substance --collection "$collection_slug" --report docs/reports/lot_38_coverage_inventory.json
```

Expected: `SUBSTANCE PASS` uniquement pour la collection effectivement
complète ; le paquet n'est pas encore exigé.

- [ ] **Step 4: exécuter panel, prepublication et commit**

Run: `cd services/rag-pedago && python -m agents.review_panel --run --collection "$collection_slug"`

Expected: approbation unanime 3/3. Une quarantaine arrête la collection et le
lot ; elle ne permet ni commit de complétude ni passage à la suivante.

Run: `python services/rag-pedago/scripts/substantive_coverage_gate.py --phase prepublication --collection "$collection_slug" --report docs/reports/lot_38_coverage_inventory.json`

Expected: `PREPUBLICATION PASS` après approbation 3/3 et paquet signé.

```bash
git add "corpus/catalogue/$collection_slug" "services/rag-pedago/tests/golden_queries/$collection_slug.json" docs/reports/lot_38_collection_worklist.json docs/reports/lot_38_coverage_inventory.json
git commit -m "corpus: couvre $collection_slug substantiellement"
```

- [ ] **Step 5: répéter avec reprise jusqu'à 59/59**

Run: `python services/rag-pedago/scripts/substantive_coverage_gate.py --phase prepublication --all`

Expected: `59/59 PREPUBLICATION PASS`, aucune référence générique comptée.

### Task 21: Publier et évaluer les 59 collections

**Files:**
- Create: `docs/adr/ADR-0025-instanciation-59-collections.md`
- Create: `services/rag-pedago/configs/validation_transition_authorization.yml`
- Modify: `services/rag-pedago/scripts/export_runtime_governance.py`
- Modify: `services/rag-pedago/tests/unit/test_runtime_governance_export.py`
- Modify: `services/rag-engine/configs/rag_collections.yml`
- Modify: `services/rag-engine/src/ingestor/runtime_governance.py`
- Create: `services/rag-engine/scripts/publish_approved_packages.py`
- Create: `services/rag-engine/scripts/evaluate_all_collections.py`
- Create: `services/rag-engine/tests/test_publish_approved_packages.py`
- Create: `services/rag-engine/tests/test_evaluate_all_collections.py`
- Create: `services/rag-engine/tests/test_validation_governance.py`
- Create: `services/rag-engine/tests/integration/test_all_collections.py`
- Generate (runtime, ignored): `services/rag-engine/infra/runtime/governance/validation.json`
- Create: `docs/reports/lot_38_retrieval_generation_evidence.json`

- [ ] **Step 1: tester le mode dry-run**

Le test publisher vérifie qu'un paquet manquant/invalide ou une collection
non prête bloquent le batch entier avant transaction. Le test évaluateur
vérifie les 59 collections, tous les profils et le refus d'un résultat
incomplet. Le test gouvernance refuse un snapshot validation sans
autorisation signée et refuse toute utilisation de cette autorisation avec
`environment=production`.

Run:

```bash
pytest services/rag-engine/tests/test_publish_approved_packages.py services/rag-engine/tests/test_evaluate_all_collections.py services/rag-engine/tests/test_validation_governance.py -q
pytest services/rag-pedago/tests/unit/test_runtime_governance_export.py -q
```

Expected: FAIL sur publisher absent, évaluateur absent et export
validation/autorisation non implémenté.

- [ ] **Step 2: implémenter instanciation, publisher et évaluateur**

Après `59/59 PREPUBLICATION PASS`, accepter ADR-0025 et passer les 59
collections à `instanciee: true`. Implémenter dry-run exhaustif, reprise
idempotente, refus de batch partiel et évaluateur exhaustif produisant le
schéma de preuve attendu par le gate final. ADR-0025 autorise explicitement
un snapshot signé `environment=validation`, sans modifier les verrous de
production. L'exporteur lie le digest de cette autorisation au snapshot ; le
vérificateur refuse digest absent/invalide et toute réutilisation avec
`environment=production`.

- [ ] **Step 3: valider dry-run puis publier en validation**

Run:

```bash
pytest services/rag-engine/tests/test_publish_approved_packages.py -q
pytest services/rag-engine/tests/test_evaluate_all_collections.py -q
pytest services/rag-engine/tests/test_validation_governance.py -q
pytest services/rag-pedago/tests/unit/test_runtime_governance_export.py -q
cd services/rag-pedago
python scripts/export_runtime_governance.py --environment validation --authorization configs/validation_transition_authorization.yml --output ../rag-engine/infra/runtime/governance/validation.json
cd ../..
python services/rag-engine/scripts/publish_approved_packages.py --all --dry-run
RAG_GOVERNANCE_SNAPSHOT=services/rag-engine/infra/runtime/governance/validation.json python services/rag-engine/scripts/publish_approved_packages.py --all --execute
```

Expected: tests/dry-run PASS puis 59 collections publiées. Le snapshot signé
porte `environment=validation` et ne modifie aucun verrou canonique de
production.

- [ ] **Step 4: évaluer puis exécuter le gate final**

Run:

```bash
python services/rag-engine/scripts/evaluate_all_collections.py --thresholds services/rag-pedago/configs/evaluation_thresholds.yml --output docs/reports/lot_38_retrieval_generation_evidence.json
pytest services/rag-engine/tests/integration/test_all_collections.py -q
python services/rag-pedago/scripts/substantive_coverage_gate.py --phase final --all --evaluations docs/reports/lot_38_retrieval_generation_evidence.json
```

Expected: `59/59 FINAL PASS`, chaque seuil atteint par collection, aucun skip.

- [ ] **Step 5: committer les scripts et preuves**

```bash
git add services/rag-pedago/configs/validation_transition_authorization.yml services/rag-pedago/scripts/export_runtime_governance.py services/rag-pedago/tests/unit/test_runtime_governance_export.py services/rag-engine docs/adr/ADR-0025-instanciation-59-collections.md docs/reports/lot_38_retrieval_generation_evidence.json
git commit -m "rag-engine: prouve le retrieval des 59 collections"
```

### Task 21b: Clore le lot corpus

**Files:**
- Create: `docs/reports/lot_38_corpus_final.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/ci-local.sh`

- [ ] **Step 1: ajouter le gate final aux CI**

Les CI savent charger les preuves versionnées et échouent si le statut final
n'est plus `59/59`.

- [ ] **Step 2: exécuter la CI complète**

Run: `bash scripts/ci-local.sh`

Expected: tous les targets PASS.

- [ ] **Step 3: revérifier les preuves sans mutation**

Run: `python services/rag-pedago/scripts/substantive_coverage_gate.py --phase final --all --check`

Expected: `59/59 FINAL PASS`.

- [ ] **Step 4: consigner le lot**

Le rapport référence worklist, sources, paquets, empreintes publiées,
évaluations par collection, gate final et résultats CI.

- [ ] **Step 5: committer**

```bash
git add .github/workflows/ci.yml scripts/ci-local.sh docs/reports/lot_38_corpus_final.md
git commit -m "docs: consigne la couverture finale des 59 collections"
```

## Chunk 6: LOT 39 — production, exploitation et décision de go-live

### Task 22: Unifier et durcir le Compose de production

**Files:**
- Create: `services/rag-engine/infra/docker-compose.nexus-prod.yml`
- Create: `services/rag-engine/infra/.env.nexus.example`
- Modify: `services/rag-engine/infra/Dockerfile.ingestor-v2`
- Create: `services/cockpit/Dockerfile`
- Create: `services/rag-engine/infra/nginx/aria.conf.template`
- Create: `services/rag-engine/infra/nginx/rag-api-internal.conf.template`
- Create: `services/rag-engine/infra/fluent-bit.conf`
- Create: `services/rag-engine/infra/README.md`
- Create: `services/rag-engine/tests/test_nexus_prod_compose.py`
- Create: `services/rag-engine/tests/test_nexus_nginx.py`

- [ ] **Step 1: écrire les assertions de durcissement**

Tester images par digest, utilisateurs non-root, `read_only`,
`cap_drop: ALL`, ports DB/Redis/API non publics, health/readiness distincts,
migrations avant readiness, worker unique pour les modèles, limites mémoire,
secrets obligatoires, logs structurés et Nginx CSP/CORS/en-têtes fermés.

- [ ] **Step 2: constater RED**

Run: `pytest services/rag-engine/tests/test_nexus_prod_compose.py services/rag-engine/tests/test_nexus_nginx.py -q`

Expected: FAIL, Compose cible absent.

- [ ] **Step 3: créer le Compose unique**

Inclure cockpit, engine, pgvector, Redis, migrations, supervision et collecte
Fluent Bit pseudonymisée ; retirer Streamlit et Ollama du chemin J1
génératif OpenRouter. Marquer les anciens Compose comme legacy non
déployables dans `infra/README.md`.

- [ ] **Step 4: valider sans afficher les secrets**

Run: `docker compose --env-file services/rag-engine/infra/.env.ci -f services/rag-engine/infra/docker-compose.nexus-prod.yml config -q`

Puis: `pytest services/rag-engine/tests/test_nexus_prod_compose.py services/rag-engine/tests/test_nexus_nginx.py -q`

Expected: config exit 0 et tests PASS. Refactorer les probes et ancres
Compose partagées plutôt que les dupliquer.

- [ ] **Step 5: committer**

```bash
git add services/rag-engine/infra services/rag-engine/tests services/cockpit/Dockerfile
git commit -m "infra: unifie le déploiement Nexus RAG"
```

### Task 23: Rendre sauvegarde, restauration et rollback exécutables

**Files:**
- Create: `services/rag-engine/infra/scripts/backup-nexus.sh`
- Create: `services/rag-engine/infra/scripts/restore-nexus.sh`
- Create: `services/rag-engine/infra/scripts/rollback-nexus.sh`
- Create: `services/rag-engine/infra/tests/test-disaster-recovery.sh`
- Create: `docs/reports/lot_39_disaster_recovery_evidence.json`
- Modify: `docs/runbooks/go_live.md`

- [ ] **Step 1: écrire le test de restauration isolée**

Créer une base de test, sauvegarder, chiffrer, copier vers un stockage de test
hors hôte, altérer, restaurer et comparer les empreintes des publications et
migrations. Vérifier permissions `0600`, archive illisible sans clé et refus
d'une cible non nommée.

- [ ] **Step 2: constater l'échec**

Run: `bash services/rag-engine/infra/tests/test-disaster-recovery.sh`

Expected: FAIL, scripts absents.

- [ ] **Step 3: implémenter pg_dump/restore et rollback applicatif**

Chiffrer avant transfert hors hôte, vérifier l'archive avant restauration et
refuser toute cible non explicitement nommée. Le rollback coupe
UI/génération sans modifier verrous, paquets signés ou chunks publiés.

- [ ] **Step 4: exécuter l'exercice**

Run: `bash services/rag-engine/infra/tests/test-disaster-recovery.sh`

Expected: PASS avec RPO/RTO mesurés dans
`lot_39_disaster_recovery_evidence.json` et invariants rollback intacts.
Refactorer validation de cible et chiffrement en fonctions shell séparées.

- [ ] **Step 5: committer**

```bash
git add services/rag-engine/infra docs/runbooks/go_live.md docs/reports/lot_39_disaster_recovery_evidence.json
git commit -m "infra: éprouve sauvegarde restauration et rollback"
```

### Task 24: Superviser et tester trois conversations simultanées

**Files:**
- Modify: `services/rag-engine/infra/prometheus/prometheus.yml`
- Create: `services/rag-engine/infra/prometheus/rules/platform.rules.yml`
- Create: `services/rag-engine/infra/prometheus/rules/openrouter.rules.yml`
- Create: `services/rag-engine/infra/prometheus/rules/backup.rules.yml`
- Create: `services/rag-engine/configs/slo.yml`
- Create: `scripts/load/chat_concurrency.py`
- Create: `services/cockpit/e2e/public-chat.spec.ts`
- Modify: `services/cockpit/package.json`
- Modify: `services/cockpit/package-lock.json`
- Create: `services/rag-engine/infra/tests/test-alerts.sh`
- Create: `docs/reports/lot_39_capacity_evidence.json`

- [ ] **Step 1: écrire le scénario de charge**

Trois sessions distinctes exécutent authentification, chargement du profil,
retrieval, génération streamée, validation des citations, logs et métriques ;
une quatrième vérifie la contre-pression. `slo.yml` fixe avant exécution :
0 erreur, p95 retrieval ≤ 2 s, premier token ≤ 5 s, réponse ≤ 30 s, attente
queue ≤ 2 s et mémoire ≤ 85 %. Simuler aussi une panne OpenRouter.

- [ ] **Step 2: écrire les alertes testables**

Alertes séparées sur erreurs, p95, queue, pool DB, circuit OpenRouter, espace
disque et fraîcheur des sauvegardes. `test-alerts.sh` exécute `promtool check`
et des règles synthétiques firing/not-firing. Ajouter le script npm
`test:e2e` ciblant Playwright.

- [ ] **Step 3: exécuter sur le stack de validation**

Run: `python scripts/load/chat_concurrency.py --users 3 --report docs/reports/lot_39_capacity_evidence.json`

Expected: trois flux réussis, aucune fuite de session, tous les seuils
préfixés atteints, quatrième flux borné et panne OpenRouter fail-closed.

- [ ] **Step 4: exécuter l'E2E authentifié**

Run: `npm --prefix services/cockpit run test:e2e -- e2e/public-chat.spec.ts && bash services/rag-engine/infra/tests/test-alerts.sh`

Expected: connexion Nexus, question, réponse citée et refus hors preuve PASS.
Refactorer le générateur de charge pour séparer session, scénario et mesures ;
aucun fichier manuel ne dépasse 250 lignes.

- [ ] **Step 5: committer**

```bash
git add services/rag-engine services/cockpit/e2e services/cockpit/package.json services/cockpit/package-lock.json scripts docs/reports/lot_39_capacity_evidence.json
git commit -m "infra: prouve la capacité conversationnelle J1"
```

### Task 25: Fermer sécurité, conformité et dépendances

**Files:**
- Create: `scripts/security/release_security_gate.sh`
- Create: `scripts/security/check_dependencies.sh`
- Create: `scripts/security/check_images.sh`
- Create: `scripts/security/check_runtime_controls.sh`
- Create: `scripts/release/release_readiness_gate.py`
- Create: `scripts/release/release_evidence.schema.json`
- Create: `scripts/tests/test-release-security-gate.sh`
- Create: `scripts/tests/test-release-readiness-gate.sh`
- Create: `docs/compliance/minors_privacy_approval.md`
- Create: `docs/reports/lot_39_release_evidence.json`
- Create: `docs/reports/lot_39_security_privacy.md`
- Modify: `docs/checklists/production_go_live_checklist.md`
- Modify: `.github/workflows/ci.yml`
- Modify: `scripts/ci-local.sh`

- [ ] **Step 1: agréger les scans bloquants**

Garder `release_security_gate.sh` comme orchestrateur. Couvrir secrets, npm,
Python, images, SBOM, permissions, PII, RBAC/IDOR, XSS/CSP/CORS, injection et
exfiltration documentaire, rate limiting, quotas, isolation tenant et refus
fail-closed. Les tests des gates injectent vulnérabilité, preuve manquante,
JSON invalide et checklist incomplète et exigent un code non nul. Ajouter ces
tests aux deux CI.

- [ ] **Step 2: exécuter le gate**

Run: `bash scripts/security/release_security_gate.sh`

Expected: exit non nul tant qu'une vulnérabilité élevée/critique subsiste.

- [ ] **Step 3: corriger chaque résultat à la source**

Ne pas ajouter d'ignore sans justification, expiration, propriétaire et ADR
de risque explicitement accepté. Faire renseigner l'approbation
confidentialité/mineurs avec approbateur, date, périmètre et SHA des textes.

- [ ] **Step 4: vérifier**

Run:

```bash
bash scripts/tests/test-release-security-gate.sh
bash scripts/tests/test-release-readiness-gate.sh
bash scripts/security/release_security_gate.sh
python scripts/release/release_readiness_gate.py --mode pre-authorization --evidence docs/reports/lot_39_release_evidence.json --checklist docs/checklists/production_go_live_checklist.md
```

Expected: PASS, `15/16` barrières avec liens de preuve ; seule l'autorisation
de transition reste en attente. Checklist sans case vide et approbation
conformité présente. Refactorer chaque famille de scan dans le sous-script
responsable.

- [ ] **Step 5: committer**

```bash
git add .github/workflows/ci.yml scripts services/cockpit/package.json services/cockpit/package-lock.json docs/compliance docs/reports/lot_39_security_privacy.md docs/reports/lot_39_release_evidence.json docs/checklists/production_go_live_checklist.md
git commit -m "security: ferme les barrières de release"
```

### Task 26a: Implémenter les scripts de release fail-closed

**Files:**
- Create: `services/rag-engine/infra/scripts/switch-aria-public.sh`
- Create: `services/rag-engine/infra/scripts/monitor-soak.sh`
- Create: `services/rag-engine/infra/scripts/deploy-release.sh`
- Create: `services/rag-engine/infra/tests/test-release-scripts.sh`
- Create: `scripts/release/build-release-images.sh`
- Create: `services/cockpit/e2e/production.spec.ts`
- Modify: `services/cockpit/package.json`
- Modify: `services/cockpit/package-lock.json`

- [ ] **Step 1: écrire les tests dry-run et rollback**

Tester variable `NEXUS_RELEASE_ROOT` absente, dry-run, idempotence, digest
incohérent, E2E en échec, soak inférieur à 24 h, alerte SLO et rollback sans
mutation des verrous.

- [ ] **Step 2: constater RED**

Run: `bash services/rag-engine/infra/tests/test-release-scripts.sh`

Expected: FAIL, scripts absents.

- [ ] **Step 3: implémenter build, switch, soak et orchestrateur**

Chaque script a une responsabilité. `deploy-release.sh` utilise
`set -euo pipefail`, exige `NEXUS_RELEASE_ROOT`, vérifie SHA/digests et arme
un `trap` de rollback avant tout changement.

- [ ] **Step 4: valider et refactorer**

Run: `bash services/rag-engine/infra/tests/test-release-scripts.sh && npm --prefix services/cockpit run test:e2e:production -- --list`

Expected: PASS ; scripts idempotents, scénario Playwright découvrable et
aucune logique de gouvernance dans les scripts d'exploitation.

- [ ] **Step 5: committer**

```bash
git add services/rag-engine/infra services/cockpit scripts/release
git commit -m "infra: automatise une release fail-closed"
```

### Task 26b: Préparer et faire accepter l'artefact de release

**Files:**
- Create: `docs/adr/ADR-0026-activation-publique-aria.md`
- Modify: `services/rag-pedago/configs/transition_authorization.yml`
- Modify: `services/rag-pedago/configs/pedago_interface_contract.yml`
- Modify: `scripts/governance-locks.baseline`
- Create: `docs/reports/lot_39_release_authorization.md`

- [ ] **Step 1: lancer la checklist automatisée sans lever les verrous**

Run:

```bash
bash scripts/ci-local.sh
bash scripts/security/release_security_gate.sh
python services/rag-pedago/scripts/substantive_coverage_gate.py --phase final --all --check
python scripts/release/release_readiness_gate.py --mode pre-authorization --evidence docs/reports/lot_39_release_evidence.json --checklist docs/checklists/production_go_live_checklist.md
```

Expected: tous PASS avant modification des verrous.

- [ ] **Step 2: faire accepter ADR et autorisation**

Rédiger ADR-0026 en statut `accepté`, référencer la décision utilisateur et
toutes les preuves des
chunks 1–6 et ajouter l'autorisation. Toute preuve absente interdit de
poursuivre.

- [ ] **Step 3: activer seulement les clés explicitement autorisées**

Activer `ui_runtime_allowed`, `real_documents_allowed`,
`curated_ingestion_allowed` et `answer_generation_allowed` avec références
ADR sur les lignes ajoutées. Le mode `final` du readiness gate dérive
dynamiquement la barrière 15 du statut ADR, de l'autorisation et des quatre
verrous concordants ; il ne modifie pas l'evidence JSON.

- [ ] **Step 4: committer et faire accepter la PR**

```bash
git add docs/adr/ADR-0026* services/rag-pedago/configs scripts/governance-locks.baseline docs/reports/lot_39_release_authorization.md
git commit -m "governance: autorise le go-live public ARIA"
```

Pousser la branche, obtenir CI/revue vertes et merger par PR. L'acceptation
de l'ADR est matérialisée par ce merge. Sur un checkout propre du SHA mergé :

```bash
python scripts/release/release_readiness_gate.py --mode final --evidence docs/reports/lot_39_release_evidence.json --checklist docs/checklists/production_go_live_checklist.md
release_manifest="${NEXUS_RELEASE_ROOT:?NEXUS_RELEASE_ROOT requis}/candidate/manifest.json"
bash scripts/release/build-release-images.sh --registry ghcr.io/cyranoaladin --sha "$(git rev-parse HEAD)" --output "$release_manifest"
```

Expected: `16/16 PASS`, images poussées par digest et manifeste signé liant
SHA, digests et Compose. Aucun déploiement public avant cette étape.

- [ ] **Step 5: déployer avec orchestrateur fail-closed**

Run:

```bash
bash services/rag-engine/infra/scripts/deploy-release.sh \
  --manifest "${NEXUS_RELEASE_ROOT:?NEXUS_RELEASE_ROOT requis}/candidate/manifest.json" \
  --env services/rag-engine/infra/.env.nexus \
  --soak 24h
```

Expected: digests identiques au registre, health/readiness verts, E2E PASS,
24 h sans violation SLO, puis ouverture Nginx. `deploy-release.sh` utilise
`set -euo pipefail` et un `trap` qui désactive l'accès public et exécute
`rollback-nexus.sh` au premier échec, sans modifier verrous ou preuves. Les
logs et le manifeste sont conservés sous le release id hors dépôt.

## Chunk 7: LOT 40 — preuve post-déploiement

### Task 27a: Vérifier la release de production en lecture seule

**Files:**
- Create: `scripts/release/verify_production_release.py`
- Create: `scripts/release/export_production_slo.py`
- Create: `scripts/tests/test_verify_production_release.py`
- Create: `scripts/tests/test_export_production_slo.py`

- [ ] **Step 1: ouvrir la branche LOT 40 et écrire les tests**

Créer la branche depuis le SHA déployé avant toute modification. Tester URL
autre que `https://nexusreussite.academy`, identité de test absente, mode
différent de `0600`, symlink, propriétaire différent, signature invalide,
digest registre différent, SHA déployé différent, collection manquante et
fenêtre SLO incomplète.

- [ ] **Step 2: constater RED**

Run: `pytest scripts/tests/test_verify_production_release.py scripts/tests/test_export_production_slo.py -q`

Expected: FAIL sur scripts absents.

- [ ] **Step 3: implémenter les vérificateurs read-only**

Exiger `PRODUCTION_BASE_URL=https://nexusreussite.academy`,
`NEXUS_RELEASE_ROOT`, `NEXUS_RELEASE_PUBLIC_KEY` et
`NEXUS_PROD_TEST_IDENTITY_FILE`. Ce fichier secret contient uniquement des
identités pseudonymes/profils autorisés ; il doit être régulier, non symlink,
appartenir au processus et être `0600`. Ni contenu ni chemin local ne sont
journalisés ou versionnés. Vérifier signature,
SHA/digests du manifeste contre registre et conteneurs, puis interroger les 59
collections avec profils/citations/fuites. Exporter Prometheus sur les
fenêtres datées soak et post-ouverture, sans conversation ni PII.

- [ ] **Step 4: valider et refactorer**

Run: `pytest scripts/tests/test_verify_production_release.py scripts/tests/test_export_production_slo.py -q`

Expected: PASS ; vérification manifeste et export SLO restent dans deux
modules séparés.

- [ ] **Step 5: committer les vérificateurs**

```bash
git add scripts/release/verify_production_release.py scripts/release/export_production_slo.py scripts/tests/test_verify_production_release.py scripts/tests/test_export_production_slo.py
git commit -m "ops: vérifie la release de production"
```

Expected: commit limité aux outils read-only et à leurs tests.

### Task 27b: Versionner le rapport final d'exploitation

**Files:**
- Create: `docs/reports/lot_40_go_live_exploitation.md`
- Create: `docs/validation/production_release_evidence.json`
- Create: `docs/validation/production_slo_evidence.json`
- Create: `docs/validation/production_release_manifest.sha256`

- [ ] **Step 1: exécuter les preuves production**

Run:

```bash
export PRODUCTION_BASE_URL=https://nexusreussite.academy
python scripts/release/verify_production_release.py --manifest "${NEXUS_RELEASE_ROOT:?}/candidate/manifest.json" --public-key "${NEXUS_RELEASE_PUBLIC_KEY:?}" --identity-file "${NEXUS_PROD_TEST_IDENTITY_FILE:?}" --output docs/validation/production_release_evidence.json
python scripts/release/export_production_slo.py --from "$SOAK_STARTED_AT" --to "$POST_OPEN_ENDED_AT" --output docs/validation/production_slo_evidence.json
sha256sum "${NEXUS_RELEASE_ROOT:?}/candidate/manifest.json" | awk '{print $1 \"  manifest.json\"}' > docs/validation/production_release_manifest.sha256
PRODUCTION_BASE_URL=https://nexusreussite.academy NEXUS_PROD_TEST_IDENTITY_FILE="${NEXUS_PROD_TEST_IDENTITY_FILE:?}" npm --prefix services/cockpit run test:e2e:production
```

Expected: signature valide, SHA/digests concordants, `59/59 PRODUCTION PASS`,
aucune fuite, SLO/alertes conformes sur les deux fenêtres et E2E PASS.

- [ ] **Step 2: rédiger le rapport final**

Consigner heures, SHA, digests, hash du manifeste, résultats E2E, SLO,
rollback disponible, incidents éventuels, `59/59` et décision d'exploitation.

- [ ] **Step 3: exécuter la CI puis finaliser le rapport**

Run: `bash scripts/ci-local.sh`

Expected: CI PASS ; consigner ensuite la commande, le SHA et son résultat
dans le rapport.

- [ ] **Step 4: vérifier les artefacts**

Run:

```bash
python scripts/release/verify_production_release.py \
  --check-output docs/validation/production_release_evidence.json \
  --check-slo docs/validation/production_slo_evidence.json \
  --check-manifest-hash docs/validation/production_release_manifest.sha256
git add docs/reports/lot_40_go_live_exploitation.md docs/validation/production_release_evidence.json docs/validation/production_slo_evidence.json docs/validation/production_release_manifest.sha256
git diff --cached --check
```

Expected: PASS sans accès mutatif ; liens croisés SHA, manifest hash, fenêtres
SLO et `59/59` cohérents ; diff indexé propre.

- [ ] **Step 5: committer et ouvrir la PR documentaire**

```bash
git commit -m "docs: consigne la preuve finale du go-live"
```

Expected: worktree propre et PR LOT 40 documentaire.
