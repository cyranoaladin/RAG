# Lot DI — activation épinglée et garde produit avant Worker B

## Périmètre et décision

Branche dédiée issue exactement de `fb8a7cc8e85448115a64de8ff5325d639ef9ee70`.
Ce lot déplace avec `git mv` la proposition DI vers son chemin d'autorisation
actif, sans exécuter l'autorisation. La revue batch #262 reste ouverte, à son
HEAD `079461659b60f8a8ce9458145a199599ad822bbc` ; ce lot ne la modifie,
ferme ni fusionne. Aucune connexion SSH, écriture en base réelle ou exécution
de Worker B n'a été effectuée.

L'autorisation demeure **inopérante jusqu'à la fusion de cette PR sur main** :
`verifier_operation_di` exige que l'autorisation, le plan, l'identité et la
preuve de provenance existent à l'identique sur `origin/main`. Une approbation
au HEAD exact par le relecteur gouverné est requise avant cette fusion.

## Provenance de l'image DI

Le run `production-image-provenance.yml` n° `36321957702`, tentative 1,
`workflow_dispatch` sur `main`, a conclu `success` au commit source
`fb8a7cc8e85448115a64de8ff5325d639ef9ee70`, arbre
`13971825e149fbe287bce93605f7ccbb182e7c06`. L'inventaire téléchargé
`NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1` est l'artefact
`nexus-deployment-image-inventory` n° `10932683454` ; l'API GitHub annonce
pour son ZIP `sha256:91fa5c0b3d57eb25b0db7a79969366756f3b09728584c8af68cae97923639696`.
L'entrée `multilevel-worker-b-production` donne exactement :

`ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:8980977c6eda1fe2f7545cd9e2cedee4655a6afbd5abea45765780af067175e6`

Le Dockerfile a l'empreinte
`feeceb7813ad2cfb38e984ceef12cf51088c7054d13045ff03ab30eba57c60de`.
Le vérificateur lie l'autorisation au digest, au commit, à l'arbre, au run,
à l'inventaire et à la preuve locale épinglée par SHA-256. Il refuse les
divergences et continue de contrôler que le commit de build est sur
`origin/main` et contient les marqueurs du correctif DI.

## Finding P1 : concordance du produit au pré-vol

Avant Worker B, la précondition vérifie la base et le rôle `rag_reader`, puis
lit tous les placements, artefacts et `chunk_id` de la base produit
dédiée, dans une transaction en lecture seule. Elle dérive les placements
attendus des attestations actives dont le job est `succeeded`, avec leurs
`placement_id` et `source_placement_id` tirés des sujets scellés de V4.
L'ensemble d'artefacts attendu
vient de ces placements ; les identités de chunks par artefact viennent du
registre de la release V4, dont l'empreinte est vérifiée contre son manifeste
scellé. Le moindre placement, artefact ou chunk supplémentaire ou manquant
est un refus. Tout placement HGGSP est refusé explicitement.

La garde dérive le produit attendu à chaque pré-vol : après un arrêt code 75,
une nouvelle publication déjà réussie augmente le produit attendu et la
relance reste possible. Les comptes d'incident 72/76/1532 ne servent pas de
seuil fixe. La revue #262 et les jobs HGGSP conservent leurs gardes existantes.

## Qualification locale

- `scripts/qualification/tests` avec les dépendances du service : 798 tests
  passés, 4 ignorés.
- Parcours DI sur PostgreSQL jetable, avec les rôles opérationnels : 1 test
  passé. Le banc crée et supprime ses conteneurs locaux ; aucune base réelle
  n'est visée.
- Tests unitaires ciblés de l'image/Worker B : 53 passés.
- `ruff check` ciblé et `bash -n` : verts.
- `mypy` sur `staging_v4_partial_recovery.py` : vert. Une erreur préexistante
  à la ligne 307 de `check_staging_authorization.py` est reproduite au commit
  parent exact ; aucun nouveau diagnostic mypy n'est introduit.
- Vérification locale des six cibles DI canoniques : six refus avant fusion,
  car l'autorisation, le plan et la preuve ne sont pas sur `origin/main`.

La CI GitHub de cette PR sera relevée après son ouverture. La signature
locale de readiness et toute opération de reprise restent hors de ce lot.
