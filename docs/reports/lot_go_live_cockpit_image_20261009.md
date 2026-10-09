# Lot go-live — image autonome du Cockpit (9 octobre 2026)

## Résultat et périmètre

Ce lot prépare une image Docker **locale et non publiée** du Cockpit Next.js. Le
Dockerfile installe les dépendances du `package-lock.json` avec `npm ci`, exécute
les tests, le lint, le contrôle TypeScript et le contrôle du contrat JavaScript,
puis construit un bundle `standalone` quand le SHA de build conteneur est fourni.
Le build local conserve `next start` ; le conteneur final sert ce bundle avec
l'utilisateur non privilégié `node`, sans dépôt monté. La base Node 22.22.0
`bookworm-slim` est épinglée par digest ; le contexte Docker est réduit aux
sources Cockpit et aux artefacts de contrat nécessaires au `main` actuel.
Les artefacts V4/V5 de répétition ne sont pas copiés dans cette image. Le
successeur de scopes publics du BFF devra être intégré et revalidé avant un
build de release ; PR #294 est encore ouverte au moment de ce lot.

Le `SOURCE_COMMIT_SHA` doit être un SHA Git hexadécimal de 40 caractères. Il
devient l'ID de build Next.js et le label OCI `org.opencontainers.image.revision`.
Ce lien est vérifié pendant le build. Le producteur d'image final doit encore
fournir un SHA de `main` **figé** et vérifier la correspondance du contexte
source ; ce lot ne prétend pas établir une provenance de release.

Base du travail : `origin/main=14cb787310d1ffda1e8c6f215cfb1435e80573fb`,
arbre `2b1ae0edb923b0ca91291a3dab08fe1e4129ed6d`, worktree propre avant
modification. La branche a ensuite intégré par merge normal le `main`
`49f6d2dc8e57125d0b7fb9638e36842420678b97` (arbre
`fb18ab69be7f4f091b94bd3cd793b9d140cb8aac`), après fusion des PR
#305 et #306. Aucune mutation staging ou production ; aucune image poussée.

## Validation exécutée

- TDD : quatre tests nouveaux ont échoué sur l'état initial, puis sont passés
  après implémentation. La correction du démarrage local a également suivi un
  cycle rouge/vert. Suite Cockpit finale : **185/185 tests** ; lint et
  TypeScript : succès.
- Contrat Python + JavaScript : `npm run contracts:check` avec un venv isolé
  contenant `nexus-contracts[dev]` ; build Next.js local : succès.
- `docker buildx build --load --platform linux/amd64` : succès depuis le vrai
  contexte du dépôt. Un `SOURCE_COMMIT_SHA=main` a été refusé après `npm ci`
  et la copie du contexte, avant les tests et la construction Next.js.
- Après l'intégration de #306, le test `next.container-config.test.ts`, renommé,
  était absent de l'allowlist Docker. Une assertion de régression a d'abord
  échoué, puis a réussi après l'ajout de son chemin exact. Le journal d'un
  **nouveau build Docker** affiche explicitement
  `next.container-config.test.ts (3 tests)`, puis `23` fichiers et `185` tests
  réussis dans l'étape builder. Le build et son smoke ont été rejoués après
  cette correction : UID 1000, `/` HTTP 200, `/api/health` HTTP 503 attendu,
  `.next/BUILD_ID` égal au SHA sentinelle, zéro mount.
- Sur cette branche intégrée : suite Cockpit `185/185`, lint, typecheck,
  `contracts:check` et build Next.js réussis. Le contrôle Python du contrat a
  utilisé une installation **non éditable** dans un venv isolé. `npm run start`
  répond HTTP 200 après ce build local. Depuis `packages/contracts`, le
  `Dockerfile` ne copie que les schémas et artefacts figés ; le contrôle
  Pydantic canonique `export_schemas.py --check` est bloquant dans le contexte
  CI requis `packages/contracts` avant la fusion et le build de release.
- `npm audit --omit=dev --json` : exit 0, zéro vulnérabilité de production,
  dont zéro high et critical. `npm audit --json` : exit 1, sept high de
  développement seulement ; la politique exacte temporaire #284 accepte
  uniquement `braces` / GHSA-vfj7-8cjw-p6xm jusqu'au 17 octobre 2026.
- Conteneur local éphémère en lecture seule : `/` répond HTTP 200 ; utilisateur
  effectif UID 1000 ; aucun dépôt présent dans l'image. `/api/health` répond
  HTTP 503 `unavailable`, attendu en l'absence de moteur RAG et de sa
  configuration dans cet essai isolé. Le conteneur et son image ont été
  supprimés après l'essai.

La répétition locale finale a exécuté
`docker buildx build --progress=plain --load --platform linux/amd64 --build-arg SOURCE_COMMIT_SHA=0000000000000000000000000000000000000000 -f services/cockpit/Dockerfile -t nexus-pr307-local:final-validation .`.
Le SHA de build était une **sentinelle synthétique**, car le worktree contenait
les changements non committés. L'image locale testée avait l'ID
`sha256:90717fa1dd6edda6c08a282be3111fd16799c8751662ba607af832c27b04af22`.
Cet ID **n'est ni un digest de registre ni `COCKPIT_IMAGE_DIGEST` final** ;
l'image a été supprimée après le smoke.

## Intégration de release restant à faire

La chaîne canonique actuelle, `.github/workflows/production-image-provenance.yml`
et `services/rag-engine/scripts/deployment_image_inventory.py`, produit et
vérifie `NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1` pour **exactement trois services** :
`ingestor` et les deux workers. Le Compose de release
`services/rag-engine/infra/docker-compose.production-release.yml` et le
signataire de readiness sont liés au même ensemble. Ils restent inchangés pour
préserver la vérification des inventaires historiques V4/V5.

Une release publique avec Cockpit exige un lot ultérieur **explicitement
opt-in** : construire et pousser l'image Cockpit depuis le `FINAL_SHA` figé,
étendre la provenance et le Compose avec un inventaire successeur vérifié sans
affaiblir V1, obtenir son digest de registre et lier ce digest à la signature de
readiness. Il faudra alors exercer l'E2E étudiant avec le vrai moteur, la
visibilité et les droits gouvernés. Aujourd'hui :

```text
COCKPIT_IMAGE_DIGEST_FINAL=absent
STUDENT_E2E_PASS=false
GO_LIVE_READY=false
RAG_PRODUCTION_DEPLOYED=false
```
