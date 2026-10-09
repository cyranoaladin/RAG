# Lot 310 — liaison de provenance publique à la readiness signée

## Base et périmètre

- Date : 2026-10-09.
- Base de travail : `origin/main` `6441bf306bfd3b5b58ae7bbceff6119e48cdfd8a`, arbre `298545df8410a10376629cbc0920245ae3575be6`.
- Travail isolé en worktree propre, venv Python 3.12 neuf ; `nexus-contracts`
  installé sans mode éditable depuis ce checkout.
- Aucun accès en écriture à staging/production ; aucune clé opérateur utilisée,
  aucune image construite/poussée et aucune signature émise.

## Résultat technique

Le contrat `nexus-contracts` 0.23.0 ajoute à la readiness V2 trois champs
optionnels indivisibles : digest SHA-256 des octets JSON canoniques de
l'inventaire public, identifiant et tentative du run de provenance. Leur
présence impose exactement les quatre images applicatives, dont Cockpit, leurs
dépôts canoniques et une référence worker identique. Leur absence conserve les
octets et signatures historiques V2. Le protocole V1 reste inchangé.

Le signer opt-in `--public-candidate` dérive la carte d'images et le digest
uniquement de l'artefact V2 validé par le vérificateur canonique du lot 308.
Le checker du bundle confronte le manifeste signé à l'inventaire vérifié puis
aux octets matérialisés avant mutation. Le signer exige exactement les cinq
services publics (`pgvector`, `ingestor`, `prometheus`, `session-redis`,
`cockpit`), compare les deux images exécutées (`ingestor`, `cockpit`) et garde
les quatre images dans la readiness signée. Un writer ou worker actif est
refusé. Les chemins historiques à trois services restent le défaut.

## Vérification locale

Les tests couvrent la signature et le parsing canonique, les champs partiels,
l'absence du Cockpit, les workers divergents, les dépôts erronés, les run et
tentatives différents, les octets d'artefact non canoniques, et la
compatibilité V1/V2. Les nouveaux tests ont échoué avant implémentation puis
sont passés.

- 2026-10-09 17:36 UTC : `pytest -q` sur le contrat readiness, l'export de
  schémas, l'inventaire d'images, le signer, le wrapper atomique et le gate
  runtime V2 : **316 passed**.
- `ruff check` sur les dix fichiers Python touchés : **0 erreur**.
- `git diff --check` : **0 erreur**.
- `mypy` ciblé sur les quatre modules de production : **30 erreurs** sur ce
  commit et **30 erreurs identiques** sur `origin/main` de départ, après
  normalisation des numéros de ligne. Elles concernent le typage historique
  de `V2ReleaseMaterial` et deux contrôles du wrapper ; aucune nouvelle
  erreur de typage n'a été introduite. Ce contrôle n'est pas déclaré vert.

## Raccord local avec le lot 309

Le raccord a été préparé dans un worktree d'intégration isolé depuis le HEAD
`737ea9d252cce5d8542870a3223f3a3397a1fc5b` de #309, suivi du commit
local initial de ce lot. Ce n'est pas encore la base fusionnée sur `main` ;
le rebase et les vérifications seront rejoués après la fusion de #309.

- `--public-candidate` du signer résout exclusivement
  `docker-compose.v2.yml` avec `docker-compose.public-blue-green.yml` depuis
  les objets Git du commit attesté. La voie V1 conserve ses trois fichiers.
- Le vérificateur prend l'inventaire V2 canonique des quatre images, impose
  exactement les cinq services publics et confronte seulement les deux images
  exécutées (`ingestor`, `cockpit`) au Compose. Le wrapper matérialise ces
  deux sources et les octets de l'inventaire, puis relit le Compose effectif
  avant de rendre un plan. Un manifeste V2 historique sans digest public est
  refusé dans le plan public et avant écriture du bundle.
- Le bundle public porte explicitement son mode et sa liste exacte de deux
  fichiers ; l'exécution est toujours refusée. Aucun `pull`, `up` ou accès
  à la production n'a été lancé. Le préflight public du lot 309 reste la
  preuve de topologie, de matériaux et de secrets host-local ; ce lot lie
  la signature, la provenance et le bundle.

### Rehearsal local

- 2026-10-09 : `pytest -q` sur le contrat readiness et les six suites
  `rag-engine` ciblées (inventaire, vérificateur, signer, wrapper,
  préflight public, plan signé) : **406 passed** après les négatifs finaux.
  `ruff check` sur les cinq fichiers Python modifiés et `git diff --check` :
  **0 erreur**. Aucun test n'a interrogé staging ou production.
- Tests unitaires et intégration synthétique : signature V2, provenance V2
  canonique à quatre images, bundle et relecture à deux fichiers, plan-only,
  refus `execute=True`, ancien V2, divergence du Compose effectif et du mode
  de bundle. Les chemins V1 restent couverts par leurs tests existants.
- `docker compose config` réel (Compose 5.6.0) depuis les objets Git du commit
  d'intégration `d4bba88ad22e6a87ce767f8ee04352a576c4ac52`, avec variables
  et matériaux fictifs isolés : cinq services exacts, aucun `build` pour
  l'API ou le Cockpit. Aucun conteneur n'a été démarré.
- Les tests du préflight public #309 contre le Compose réel sont passés dans
  la suite ciblée. Les preuves ci-dessus ne décrivent ni le staging final,
  ni la cible production, ni une signature opérateur.

La qualification finale devra être rejouée sur le SHA fusionné de `main` et
sur l'inventaire V2 réellement publié pour ce SHA. Aucun verdict
`GO_LIVE_READY` ni digest final n'est produit ici.
