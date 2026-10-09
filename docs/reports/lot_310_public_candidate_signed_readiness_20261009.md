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

## Dépendance restante

Le Compose public résolu du lot 309 doit être branché au signer et au wrapper
pour que le chemin `--public-candidate` puisse aboutir. À cette base, le
Compose historique ne contient pas Cockpit : le refus du candidat public est
attendu. Aucun verdict `GO_LIVE_READY` ni digest final n'est produit ici.
