# Lot go-live — image autonome du Cockpit (9 octobre 2026)

## Résultat et périmètre

Ce lot prépare une image Docker **locale et non publiée** du Cockpit Next.js. Le
Dockerfile installe les dépendances du `package-lock.json` avec `npm ci`, exécute
les tests, le lint, le contrôle TypeScript et le contrôle du contrat JavaScript,
puis construit un bundle `standalone`. Le conteneur final sert ce bundle avec
l'utilisateur non privilégié `node`, sans dépôt monté. La base Node 22.22.0
`bookworm-slim` est épinglée par digest ; le contexte Docker est réduit aux
sources Cockpit et aux artefacts de contrat nécessaires.

Le `SOURCE_COMMIT_SHA` doit être un SHA Git hexadécimal de 40 caractères. Il
devient l'ID de build Next.js et le label OCI `org.opencontainers.image.revision`.
Ce lien est vérifié pendant le build. Le producteur d'image final doit encore
fournir un SHA de `main` **figé** et vérifier la correspondance du contexte
source ; ce lot ne prétend pas établir une provenance de release.

Base du travail : `origin/main=14cb787310d1ffda1e8c6f215cfb1435e80573fb`,
arbre `2b1ae0edb923b0ca91291a3dab08fe1e4129ed6d`, worktree propre avant
modification. Aucune mutation staging ou production ; aucune image poussée.

## Validation exécutée

- TDD : quatre tests nouveaux ont échoué sur l'état initial, puis sont passés
  après implémentation. Suite Cockpit finale : **184/184 tests** ; lint et
  TypeScript : succès.
- Contrat Python + JavaScript : `npm run contracts:check` avec un venv isolé
  contenant `nexus-contracts[dev]` ; build Next.js local : succès.
- `docker buildx build --load --platform linux/amd64` : succès depuis le vrai
  contexte du dépôt. Un `SOURCE_COMMIT_SHA=main` a été refusé avant le build.
- Conteneur local éphémère en lecture seule : `/` répond HTTP 200 ; utilisateur
  effectif UID 1000 ; aucun dépôt présent dans l'image. `/api/health` répond
  HTTP 503 `unavailable`, attendu en l'absence de moteur RAG et de sa
  configuration dans cet essai isolé. Le conteneur et son image ont été
  supprimés après l'essai.

La répétition locale a utilisé le SHA **sentinelle synthétique**
`0000000000000000000000000000000000000000`, parce que le worktree contenait
les changements non committés. Son image locale avait l'ID
`sha256:f4df7ebbf841dc28c18676bde92bae2a98f13dbb56c642a5482be60b7ac1c424`.
Cet ID **n'est ni un digest de registre ni `COCKPIT_IMAGE_DIGEST` final**.

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
