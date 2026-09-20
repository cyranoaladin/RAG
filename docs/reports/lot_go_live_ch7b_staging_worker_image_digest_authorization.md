# LOT_GO_LIVE_FINAL_CH7B_STAGING_WORKER_IMAGE_DIGEST_AUTHORIZATION

- **Branche** : `go-live/ch7b-staging-worker-image-digest-authorization`
- **Base** : `f66a04cb` (#240, garde d'identité d'image)
- **Décision attendue** : `GO_LIVE_CH7B_STAGING_WORKER_IMAGE_DIGEST_AUTHORIZATION_PR_OPEN`
- **Amende** : `docs/reports/go_live/authorizations/staging_ssh_authorization.json` (CH2, CH3, CH4, CH6 → **CH7B**)

> Ce lot **autorise** ; il n'exécute rien. Aucun conteneur n'a été démarré sur
> `nexus-prod`, aucune image n'y a été construite, le point d'entrée n'a pas
> tourné, et le manifeste signé `7bcf8129…` n'a été ni modifié, ni réinstallé,
> ni réutilisé.

## L'ordre a été respecté

La garde d'identité d'image (CH7A, #240) est fusionnée **d'abord**. L'image
n'a été construite qu'ensuite, depuis le `main` qui la porte. Elle contient
donc ce que ce lot affirme — ce qui n'aurait pas été le cas dans l'ordre
inverse.

## Ce que CH7B change, et rien d'autre

| Champ | Avant (CH6) | Après (CH7B) |
|---|---|---|
| `image_digest` | `sha256:2ce7533d…` | **`sha256:1fb70485…`** |
| `source_commit_sha` | `24b28d41` | **`f66a04cb`** |
| `build_workflow_run_id` | 35524322769 | **35535013039** |
| `supersedes_image_digest` | — | `sha256:2ce7533d…` |
| `runtime_image_binding_guard` | — | `NEXUS_ACTUAL_WORKER_IMAGE` |

**L'image API n'est pas touchée** : elle garde son digest `sha256:d0134f49…`
et sa ligne `contracts_version: 0.18.0`. Les deux images cohabitent, chacune
pour ce qu'elle sait faire.

### Pourquoi l'image de CH6 ne peut plus être autorisée

Elle a été construite au commit `24b28d41`, avant les lots CQ, CR et CH7A.
Elle ne porte ni `staging_readiness_gate.py`, ni la garde d'identité, et son
point d'entrée appelle `enforce_readiness_gate()` — la chaîne de
**production**, qui n'existe pas en staging :

```
ModuleNotFoundError: No module named 'ingestor.ingestion_profiles.staging_readiness_gate'
```

Le validateur refuse désormais **nommément** un retour à ce digest, au lieu
de le laisser passer inaperçu, et exige que l'amendement nomme le digest
qu'il remplace.

## L'image autorisée

```
ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:1fb70485f94a539c83142a372b24fa657daea398524173c5cdb5a3d2a9c38efb
```

| Fait | Valeur |
|---|---|
| Workflow | `.github/workflows/production-image-provenance.yml` |
| Run / tentative | `35535013039` / 1 |
| Ref | `refs/heads/main` |
| Commit source | `f66a04cb364191c53eb56c9a9e1208e9e386ae16` |
| Arbre source | `b173a5a9e5f8465cf5dbaaada8d222d376f68990` |
| Dockerfile | `Dockerfile.multilevel-worker-production`, `feeceb78…` |
| Construite le | 2026-09-20T20:21:00Z |
| Construite sur `nexus-prod` | **non** |
| Tag `latest` publié | **non** — seul `sha-f66a04cb…` existe |

## Les quinze vérifications, mesurées hors `nexus-prod`

Tirage **par digest**, puis exécutions `--network none` sur le poste de
travail.

| # | Vérification | Résultat |
|---|---|---|
| 1 | tirable par digest | OK — aucun tag `latest` publié |
| 2 | digest exact | `1fb70485…`, identique à l'inventaire |
| 3 | provenance gouvernée | workflow, run `35535013039`, `refs/heads/main`, commit `f66a04cb` |
| 4 | `nexus-contracts` | **0.19.0** |
| 5 | `ingestion_agents` | présent et importable |
| 6 | `sealed_release_ingestion_cli` | présent et importable |
| 7 | `staging_readiness_gate.py` | **présent** |
| 8 | appelle `enforce_staging_readiness_gate` | oui ; `enforce_readiness_gate` : non |
| 9 | garde `NEXUS_ACTUAL_WORKER_IMAGE` | présente |
| 10 | refus si la variable est absente | **refusé** |
| 11 | refus si elle diffère du `worker_image` signé | **refusé** (ancien digest CH6, tag seul, autre dépôt) |
| 12 | aucun secret | 0 variable porteuse, 0 fichier |
| 13 | ni clé, ni graine, ni manifeste signé embarqué | 0 ; ancre non embarquée non plus |
| 14 | aucun accès production | base produit interdite, 0 lecture, 0 écriture |
| 15 | Worker B non autorisé | interdit nommément |

Les points 10 et 11 ne sont pas lus dans le code : ils ont été **exécutés
dans l'image**. Quatre refus et une acceptation :

```
variable absente     : refuse (NEXUS_ACTUAL_WORKER_IMAGE is not configured…)
ancien digest CH6    : refuse (the running image is …2ce7533d…)
tag seul             : refuse (…carries no digest…)
autre depot          : refuse (the running image is docker.io/ailleurs/…)
image exacte         : accepte
```

**Sur `private_key_hex`.** La recherche de secrets a trouvé cette chaîne dans
`issue_review_binding_cli.py:372`. C'est un **nom de paramètre** à un site
d'appel, pas une valeur — et le code applicatif de l'image ne contient
**aucune** littérale hexadécimale de 64 caractères. Je le signale plutôt que
de l'écarter en silence : une recherche de secrets qui trouve quelque chose
doit dire ce que c'est.

## La déclaration d'autorisation

> « L'approbation de cette PR par abenrhouma vaut autorisation d'utiliser,
> pour le staging cloisonné uniquement, l'image worker digest-pinned
> construite par le workflow gouverné `production-image-provenance.yml`
> depuis main `f66a04cb364191c53eb56c9a9e1208e9e386ae16`. Cette autorisation
> ne permet ni build sur `nexus-prod`, ni tag non épinglé, ni Worker B, ni
> écriture DB production, ni current switch, ni exposition publique. »

Elle est **vérifiée**, pas seulement écrite : le validateur refuse
l'autorisation si l'une de ses huit mentions disparaît, et huit épreuves le
prouvent une par une.

## Preuves

Les **quinze épreuves demandées** sont dans
`scripts/qualification/tests/test_staging_worker_image_digest_ch7b.py`, plus
les épreuves CH6 repointées vers la preuve en vigueur. La preuve de CH6 reste
versionnée comme trace de ce qui avait été autorisé — remplacer un digest
n'efface pas l'historique.

```
pytest scripts/qualification/tests -q    325 passed, 2 skipped
  (rejoué dans un venv propre, sans psycopg, comme le job de CI)
ruff check                               All checks passed!
governance locks                         18/18 conformes
```

## Ce qui reste, et qui est à vous

L'autorisation n'est effective qu'une fois fusionnée. Ensuite, le manifeste
actuel **`7bcf8129…` est obsolète** : il nomme `merge_sha 3abcec67` et
l'image `2ce7533d…`. La garde de CH7A refuserait l'exécution.

Vous en signerez un nouveau avec `merge_sha` = le commit de fusion de CH7B,
`worker_image` = `sha256:1fb70485…`, même release V2, même `key_id`.
