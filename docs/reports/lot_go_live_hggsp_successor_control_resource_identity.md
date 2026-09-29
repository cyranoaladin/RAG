# Lot préalable HGGSP — identités de contrôle du successeur

Base de conception : `2bc65c9386aafb80d66ce25096b50c75eeeb5412`.
Ce lot ajoute une primitive runtime et une migration de contrôle. Il ne donne
aucune autorisation staging ; la PR d'activation #270 reste distincte et draft.

## Invariant de coexistence

`publication_attestations` conserve son index unique sur `resource_id` pour
les attestations actives. Les colonnes `resource_id` et `artifact_id` de
`sealed_release_adoptions` conservent leur sens historique : elles désignent
la ressource et l'artefact **acquis par le prédécesseur**. La migration 020
ajoute `successor_resource_id` et `successor_artifact_id` pour les seules
adoptions `SEALED-RELEASE-ADOPTION-V2`. Les V1 restent sans valeur dans ces
colonnes. Les deux couples artefact/ressource sont contrôlés par des clés
étrangères composites. Aucun PDF, chunk ou embedding n'est recopié : V5
possède une nouvelle ligne de métadonnées d'artefact qui nomme le même SHA,
la même taille, les mêmes types MIME et les mêmes URL gouvernées.

## Dérivation déterministe

Le document d'identité est du JSON UTF-8 canonique (`sort_keys=True`,
séparateurs `,` et `:`, `ensure_ascii=False`) portant exactement
`version=SEALED-RELEASE-ADOPTION-V2`, `release_id`, `placement_id`,
`content_sha256` et `collection`.

- Ressource V5 : UUIDv5 dans `NAMESPACE_URL`, à partir de
  `nexus:successor-control:resource:v2` suivi d'un octet NUL et du document.
- Artefact de contrôle V5 : UUIDv5 dans `NAMESPACE_URL`, avec le domaine
  `nexus:successor-control:artifact:v2` et le même document.
- `dedup_key` V5 : `successor-control-v2:` suivi du SHA-256 hexadécimal de
  `nexus:successor-control:dedup-key:v2`, octet NUL, puis document.
- Run de contrôle V5 : UUIDv5 dans `NAMESPACE_URL`, à partir de
  `nexus:successor-control:run:v2`, octet NUL, puis du JSON canonique de
  `release_id` et `collection`.

Le digest d'adoption V2 reprend celui de V1 avec sa version V2 et **les quatre
UUID de contrôle** : ressource/artefact V4 et ressource/artefact V5. Les golden
vectors et les mutations d'un UUID figurent dans
`services/rag-engine/tests/test_sealed_release_adoption.py`.

## Écriture gouvernée

Le CLI `adopt-predecessor-release --adoption-version
SEALED-RELEASE-ADOPTION-V2` vérifie la release scellée, apparie exactement
les placements, puis utilise le rôle dédié `ingestion_control_adopter` dans
une transaction sérialisable. Ce rôle peut lire et **insérer** uniquement les
faits de contrôle nécessaires ; il ne peut pas modifier les lignes V4, créer
des jobs ou attester. Une divergence d'identité ou de métadonnées refuse la
transaction entière. La reprise V1 conserve l'option par défaut et le rôle
attestor historique.

La liaison des autorités et la proposition de revue batch restent des étapes
gouvernées distinctes : elles produisent les projections V5 après l'adoption.
La revue humaine batch reste obligatoire avant l'enregistrement des
attestations V5. L'outil d'enqueue et le claim release-bound continuent ensuite
de sélectionner les seules attestations et jobs V5.

La tête du schéma passe de 019 à 020. Le runner canonique relit maintenant le
registre **après** avoir acquis son verrou transactionnel et saute le DDL si
une autre invocation a déjà inscrit la même version. Deux bootstraps
concurrents terminent donc sans rejouer les contraintes déclaratives de 020.
Le rollback officiel 020 refuse toute adoption V2 et toute valeur des deux
nouvelles colonnes avant de retirer les colonnes, FKs et index. Les migrations
018 et 019 restent inchangées.

## Qualification locale

- PostgreSQL jetable : ancien modèle V1 → `ATTESTATION_CONFLICT` ; nouveau
  modèle V2 → 74 ressources et 74 artefacts de contrôle distincts, 74
  attestations V4 toujours actives, 74 attestations V5 actives, 74 jobs V5.
  Snapshots de toutes les colonnes V4 ressource, artefact, attestation et job
  identiques avant/après adoption, enqueue et claim V5. Rejeu : zéro nouvelle
  ressource, artefact, adoption, attestation ou job. Une erreur forcée sur la
  74e adoption annule l'ensemble.
- PostgreSQL jetable : installation depuis 000, upgrade 018→020, contrôle de
  propriété artefact/ressource, replay, rollback 020 avant V2 et refus du
  rollback après V2. La suite ciblée 020 compte 8 tests réussis ; les deux
  contre-épreuves historiques de rollback et de bootstrap concurrent ont
  été adaptées à la tête 020 et passent.
- Suite unitaire `rag-engine` : verte avec `PYTHONPATH` pointant vers ce
  worktree ; `mypy` : 149 fichiers sans erreur ; Ruff, `bash -n`, verrous de
  gouvernance, unicité d'autorité et hygiène dépôt : verts.
- `scripts/qualification/tests` : 803 réussis, 4 ignorés. `scripts/tests`
  hors tests de disponibilité go-live : 457 réussis, 17 ignorés. Quatre tests
  go-live échouent dans l'environnement local car `disk_policy_ok` exige
  40 Gio libres et la machine n'en a que 25 Gio ; le code de cette politique
  et ses tests sont inchangés par ce lot. Le run `scripts/ci-local.sh` a été
  interrompu pendant le téléchargement d'une dépendance CUDA de 423 Mo ;
  les cibles contracts (1012 tests), pdf-page-policy (23 tests) et import
  release-chain avaient réussi avant cette interruption. La CI GitHub de la
  PR reste la qualification intégrale à consulter avant toute fusion.

## Frontière du lot

La publication produit des placements HGGSP V5 exige encore une décision
distincte. Les 74 placements HGGSP des manifestes V4 et V5 ont la même
identité de contenu et de scope. `rag_artifact_placements` impose actuellement
une identité unique pour ce couple et le publisher refuse une autorité ou une
attestation différente sur la ligne V4. Cette PR ne change ni le schéma
produit, ni les 405 placements V4, ni #270 ou #262. Elle ne constitue donc
pas à elle seule une autorisation de lancer le Worker V5.

Après fusion éventuelle de ce lot : attendre la CI post-fusion, puis lancer
`production-image-provenance` sur le nouveau `main` avant toute reprise de
#270. Aucun build ni opération serveur ne fait partie de cette PR.
