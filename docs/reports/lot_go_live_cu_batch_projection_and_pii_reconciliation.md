# Lot CU — lecture batch, réconciliation PII, projection

**Branche** : `go-live/cu-batch-projection-and-pii-reconciliation`
**Base** : `main` = `57754133`

## Rectification traçable — l'origine des doublons PII n'est pas établie

> Le message du commit `aa58b4ef` présente une explication comme démontrée :
> « `pdf_entries` émet une entrée par couple (contenu, chemin) du manifeste,
> puis `source_by_sha` écrase la distinction de chemin ». **Cette explication
> est retirée.** L'historique partagé n'est pas réécrit ; la rectification est
> consignée ici et fait autorité sur le message de commit.

Ce qui a été vérifié après coup :

| Producteur | Comportement mesuré |
|---|---|
| `pii_scan_reconciliation.py:198` | émet **une entrée par contenu** (`for content_sha256 in sorted(pdf_counts)`), relation aux chemins conservée dans `physical_object_count` |
| `pii_review_projection.py:250` | **refuse** un contenu vu deux fois, itère un `corpus_order` dédupliqué |

Le refus de doublon date de `7ae20224` (2026-09-05) ; le commit qui scelle le
fichier est `6fdecb51` (2026-09-18) — treize jours plus tard. Aucune version
courante de ces chemins ne peut produire 486 entrées pour 319 contenus.

Le fichier porte `scanner_version: production-profile-gate-v1`, ce qui le
rattache au constructeur de release ; mais `git log` date l'entrée d'un fichier
dans le dépôt, **pas sa production**. L'hypothèse d'une production antérieure au
correctif est plausible et non démontrée.

**Conclusion retenue : origine non établie.** Aucun « correctif producteur »
n'est attribué à un producteur non identifié. Cette recherche historique ne
bloque ni le correctif de lecture ni les garanties futures, qui sont traitées
séparément (§ *Unicité des futures preuves*).

## Références figées des preuves

Mesurées le 2026-09-21, sur `main` = `57754133`.

| Fichier | sha256 brut | Déclaré par la release |
|---|---|---|
| `production-profile-gate.release.json` | `e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864` | — (autorité racine) |
| `artifacts.release.json` | `42c71df3c3ddbab83f71ea20bc6624237608bb77f064db3018f9d15f63eabeb0` | `artifact_registry.sha256` |
| `candidate_inventory.json` | `d906663b91b7bfac9dab0c05e4374cdb61b2eef8556ad2e86ceee3d529ab8123` | `authorities.candidate_inventory_sha256` |
| `pii_evidence.json` | `ffb136d332f8a33bd46a8bd3bcad31711f39b7d6a3f22fc50eb57e5d9e0478e4` | `authorities.pii_evidence_sha256` |
| `preflight_evidence.json` | `809c756ebb9aec74adee747b1ad48f5b94eb44896838e27f2e1886026e21b69d` | `authorities.preflight_evidence_sha256` |
| `currentness_evidence.json` | `8fc2208d08c1703bd8a04c7884ef587598ecc692d9e683262ed022219922df1e` | `authorities.currentness_evidence_sha256` |
| `rights_evidence_registry.yml` | `e3c9a157f1f78171c0052750fa08b7726b99ea4dd348728f1b90db07f93ef1ff` | `authorities.rights_registry_sha256` |

Tous sous `services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2/release-1b9eba0c0eb0ab13/profile_gate/`,
sauf le registre de droits (`services/rag-pedago/configs/`).

### Cardinalités, par fichier et mesurées indépendamment

| Grandeur | `pii_evidence` | `currentness_evidence` | `artifacts.release` | base staging |
|---|---|---|---|---|
| Entrées brutes | **486** | **486** | 315 | 479 lignes |
| SHA de contenu distincts | **319** | *non mesuré séparément* | **315** | **315** |
| Placements | — | — | — | **479** |
| Contenus appartenant à V2 | 315 | 315 | 315 | 315 |

Le 486 de `currentness_evidence` a été compté sur **ce fichier**, jamais repris
de `pii_evidence`.

### Dépendance entre pré-vol et release — pas deux validations indépendantes

La release et le pré-vol portent des `(chunk_id, chunk_sha256)` identiques pour
315/315 et le même `page_count` pour 315/315. **Ce n'est pas une double
validation** : `build_production_profile_release.py` consomme le pré-vol pour
construire la release. La concordance établit une **liaison** — la release n'a
pas dérivé de son pré-vol — et non deux mesures indépendantes du même fait.

## Réconciliation des répétitions PII

Le chargeur canonique refusait les 167 répétitions. Le refus est **restreint à
ce qu'il garde** — une contradiction de verdicts — et non supprimé :

- comparaison de l'entrée **entière**, convention du dépôt (UTF-8, `sort_keys`,
  séparateurs compacts) : un champ inconnu du code ne disparaît pas avant la
  comparaison, et les types ne sont pas aplatis ;
- **équivalence structurelle**, pas identité des octets — l'empreinte du fichier
  brut reste vérifiée en amont, séparément ;
- noms de propriétés répétés refusés (`object_pairs_hook`), y compris dans les
  objets imbriqués ; `NaN`/`Infinity` refusés (`parse_constant`) ;
- les octets vérifiés sont **ceux qui sont analysés** — une seule lecture ;
- divergence détectée sur tout le fichier chargé, avant toute sélection ;
- le représentant logique subit les contrôles habituels ;
- multiplicité brute conservée dans `_occurrences`.

Exécuté sur la preuve réelle : 486 occurrences, 319 contenus, multiplicités
`{1: 152, 2: 167}`, 315/315 des contenus publiés `CLEARED`, zéro refus, aucune
autorité de revue requise (aucun `DETECTED_REVIEWED_ACCEPTED`).

## Actualité — `counts` est un résumé dérivé, et il est faux

`load_multilevel_currentness` confronte `counts` à la liste `artifacts`, champ
par champ (`multilevel_evidence.py:679-700`). Exécuté :

```
REFUS  artifacts        déclaré=26  attendu=486
REFUS  evaluated        déclaré=26  attendu=486
REFUS  current          déclaré=26  attendu=486
ok     review_required  déclaré=0  == 0
ok     unevaluated      déclaré=0  == 0
```

Les décisions métier sont intactes : 486/486 `CURRENT`, zéro en revue, zéro non
évalué. Le consommateur canonique complet n'a pas encore été exercé de bout en
bout ; le relevé ci-dessus porte sur les seuls contrôles de compteurs.

## Représentation batch

`SealedReleaseArtifactRecord` — discriminée par
`pipeline_kind: Literal["sealed_release_pipeline"]`. `original_url`,
`final_url`, `domain` et `collected_at` sont **absents du modèle**, et le modèle
est strict : les fournir est une erreur, pas un extra ignoré. `ArtifactRecord`
n'est pas touché ; ses quatre champs restent obligatoires.

Construit depuis les **479 payloads historiques réels** : 479/479, zéro échec,
provenance concordante avec l'autorité scellée relue indépendamment pour 479/479.

Cet essai a été mené dans l'image épinglée **avec les contrats de la branche
superposés par `PYTHONPATH`**. C'est une expérimentation de compatibilité, pas
une qualification de l'image gouvernée — l'image `431264a0…` ne contient pas ce
code.

## Conditions non établies

| Condition | État |
|---|---|
| Identités des pages scannées (PII) | compteurs seuls ; `pages_scanned == page_count` pour 315/315, mais une égalité de cardinalités ne prouve pas l'égalité des ensembles |
| Erreurs d'extraction (PII) | aucun champ ne les porte chez ce producteur — ni constatées, ni infirmées |
| Actualité | résumé contredisant sa liste |

## Dette de qualité logicielle

`test_openapi_schema_drift::test_le_schema_publie_est_celui_du_runtime` échoue.
Reproduit à l'identique sur `main` en worktree propre — **un échec également
reproduit sur la base ; aucune régression supplémentaire observée dans la suite
unitaire exécutée. Intégration et CI non encore qualifiées.** Sa cause n'est pas
encore identifiée et doit l'être avant le verdict final.
