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

> **Mise à jour du 2026-09-22** : les deux premières lignes sont **levées** par
> la mesure datée décrite plus bas (« Qualification PII bornée »). La
> troisième est confirmée et précisée (« Qualification des autorités V2
> réelles »). L'état initial est conservé ici tel qu'il avait été constaté.

| Condition | État initial | Aujourd'hui |
|---|---|---|
| Identités des pages scannées (PII) | compteurs seuls ; `pages_scanned == page_count` pour 315/315, mais une égalité de cardinalités ne prouve pas l'égalité des ensembles | **établies** : 0 page sans texte sur les 315 contenus, l'égalité est adossée à un fait par page |
| Erreurs d'extraction (PII) | aucun champ ne les porte chez ce producteur — ni constatées, ni infirmées | **établies** : 0 erreur d'extraction sur 315 |
| Actualité | résumé contredisant sa liste | **confirmé et précisé** : `counts` déclare 26 pour 486 entrées, granularité par placement, 469 entrées `CURRENT` sans URL de téléchargement |

## Dette de qualité logicielle

`test_openapi_schema_drift::test_le_schema_publie_est_celui_du_runtime` échoue.
Reproduit à l'identique sur `main` en worktree propre — **un échec également
reproduit sur la base ; aucune régression supplémentaire observée dans la suite
unitaire exécutée. Intégration et CI non encore qualifiées.** Sa cause n'est pas
encore identifiée et doit l'être avant le verdict final.

## Worker B ne peut pas démarrer sur la release V2 réelle

Mesuré en exécutant le chargeur canonique sur les **fichiers exacts** de V2 :

```
load_multilevel_candidate_inventory(candidate_inventory.json)
  -> REFUS : inventory unique_artifacts count differs
```

Le refus survient sur la **première** autorité, avant même l'actualité.

Mesuré **sur les listes du fichier lui-même**, pas sur une autre source :

| Grandeur | Déclarée dans `counts` | Portée par les listes du même fichier |
|---|---|---|
| `unique_artifacts` | **486** | **319** `content_sha256` distincts |
| `placements` | **486** | 486 candidats listés |
| `physical_objects` | **486** | — |
| `multi_placement_artifacts` | **0** | ≥ 1 : 486 candidats pour 319 contenus |

Le fichier décrit donc **486 candidats sur 319 contenus** — un ensemble
légitime, et **différent** de l'ensemble publié (315 artefacts, 479
placements). Ce n'est pas l'écart candidat/publié qui fait échouer le
chargeur : c'est que `counts.unique_artifacts` déclare **486** là où les
listes du même fichier en portent **319**.

C'est la **même famille de défaut** que le `counts` de
`currentness_evidence.json` : un résumé qui ne décrit pas son propre
ensemble. Deux fichiers d'autorité de la release V2 sont concernés — et le
**319** est exactement le nombre de contenus distincts que porte aussi
`pii_evidence.json`, ce qui rattache les trois fichiers au même périmètre
d'origine.

**Conséquence opérationnelle** : la publication réelle de V2 par Worker B est bloquée tant que ces deux autorités ne sont pas réconciliées. Ce n'est pas une réserve de rédaction — c'est un refus au démarrage, mesuré.

Le parcours batch sur données de banc n'est pas affecté : il utilise des autorités de test cohérentes, explicitement nommées comme telles.

## Dérive OpenAPI — cause et traitement

Le schéma publié avait été généré par une version de Pydantic antérieure à
l'épingle courante (`pydantic==2.13.4`). Les 62 lignes d'écart se
répartissaient en deux catégories, et deux seulement :

- `additionalProperties: true` ajouté sur 6 champs libres — défaut de JSON
  Schema, sans effet observable ;
- `enum: [x]` retiré à côté de `const: x` sur 6 champs — même contrainte.

**Mesure décisive** : après normalisation de ces deux écarts, les deux
documents sont identiques. La régénération ne change donc rien de ce que les
intégrateurs observent.

Le test n'est ni supprimé ni neutralisé ; il est complété par une épreuve qui
refuse un `enum` redondant dans le document runtime — sa réapparition
signalerait un environnement de génération différent.

## Le parcours batch atteint l'index produit — mesuré

Worker B a été **réellement lancé** par son CLI, sur une base produit
pgvector isolée, avec le modèle E5 réel. Sa sortie, telle quelle :

```
MULTILEVEL_PUBLICATION_WORKER_STARTUP_AUTHORITY authority_mode=STAGING_LOCAL_GITHUB_ONLY
  production_approval=false release_manifest_sha256=228529d81ac0b352…
  profile_manifest_sha256=47c86091687fc7a4… declared_count=10
  embedding_inventory_sha256=58ad18dbb0a154c5…
MULTILEVEL_PUBLICATION_WORKER_ATTESTATION_OK current_user=ingestion_control_app
MULTILEVEL_PUBLICATION_WORKER_ITERATION job_id=16c0ff2b… status=succeeded
  artifact_id=f91fc2c247f2e7c0… placements=1 chunks=3
MULTILEVEL_PUBLICATION_WORKER_ITERATION job_id=7112e271… status=succeeded
  artifact_id=e9f0a4072d5f7223… placements=1 chunks=3
MULTILEVEL_PUBLICATION_WORKER_ITERATION job_id=976582ff… status=succeeded
  artifact_id=e9f0a4072d5f7223… placements=2 chunks=3
MULTILEVEL_PUBLICATION_WORKER_ITERATION job_id=e0250fd6… status=succeeded
  artifact_id=f91fc2c247f2e7c0… placements=2 chunks=3
```

Un code de sortie nul ne vaut pas preuve : les deux bases sont relues
**indépendamment** après coup, et le contenu est **récupéré** par le chemin
de retrieval réel — identité interne signée, scope serveur dérivé du
catalogue gouverné, store pgvector sous le rôle `retrieval`. Le texte rendu
est celui qui a été extrait des octets publiés, et il porte le type
documentaire, les droits, l'éditeur et la provenance que l'attestation a
scellés.

Le rôle `ingestion_control_app` porte le worker ; le superutilisateur ne
sert qu'à préparer et à relire les bases jetables.

## Quatre défauts réels, révélés par ce parcours

Aucun n'était visible avant de lancer le CLI : la branche scellée de
`publication_resume` n'avait jamais été exécutée.

| # | Défaut | Traitement |
|---|---|---|
| 1 | `_charger_catalogue_scelle` devinait un manifeste de transfert voisin et lisait son empreinte attendue dans `authorities.artifact_transfer_manifest_sha256` — champ que la chaîne d'autorités, **fermée**, ne comporte pas. L'invariant de format restait donc toujours vide, et **toute lecture scellée refusait** | le manifeste est transporté comme les autres autorités, par un couple chemin/empreinte (`--artifact-transfer-manifest-path/-sha256`). Une moitié de couple est refusée |
| 2 | `_verify_release_batch_attestation` dérivait les quatre faits d'attribution de `collection` et de `profile_id` : le batch publiait **le nom de sa collection en guise de type documentaire**, jusque dans `rag_chunks.type_doc`, que le retrieval lit | les faits sont lus dans leur foyer durable (migration 012). L'ingestion scellée les dérive du catalogue d'artefacts de la release — dont l'empreinte est portée par l'artefact de revue approuvé. Le type doit être une valeur canonique de `TypeDoc`, ce qui refuse précisément un nom de collection, et l'hôte de provenance un domaine que le profil autorise ; le type lui-même est confronté par le résolveur de placement au moment de publier (voir « une confrontation mal placée ») |
| 3 | La branche scellée lisait `artifact_record.extracted_text_ref` et `.mime_detected`, **absents** de `SealedReleaseArtifactRecord` : une release scellée n'a jamais été téléchargée et ne porte aucune référence de fichier | l'artefact est relu **par son empreinte**, sous la même protection que le chemin unitaire, et son digest est **re-mesuré** sur les octets lus. Le format vient de l'invariant établi par le catalogue |
| 4 | Le batch revendiquait l'URL canonique vide que son schéma lui interdit : le resolver refusait, à raison | le batch ne revendique aucune URL canonique ; sa provenance reste confrontée au catalogue scellé |

Le défaut 2 a une **conséquence opérationnelle nommée** : une release
scellée déjà ingérée ne porte aucune attribution durable. Elle devra en
recevoir une — dérivée de son propre catalogue, sans nouvelle ingestion —
avant de pouvoir publier. Ce n'est pas une régression : ce chemin ne
publiait rien auparavant.

## Le constructeur de contexte du banc

`tests/integration/_banc_multiniveaux.py` produit **ensemble** la chaîne que
Worker B exige, pour une release de banc de deux vrais PDF placés dans deux
collections.

Ce qui est **gouverné est réutilisé tel quel** : profils staging multi-niveaux
et leur manifeste, trois tables de correspondance Éduscol, registre de
programmes, catalogue de collections. Ce qui décrit le **contenu du banc** est
seul fabriqué : inventaire candidat, actualité, preuve PII, registre de droits,
catalogue d'artefacts, manifestes de sujet et de release.

Deux exigences s'appliquent à ce que le banc écrit :

- **chaque empreinte déclarée nomme des octets qui existent** dans le
  répertoire de la release — aucune valeur de remplissage ;
- **les mesures sont mesurées** : le nombre de caractères que le pré-vol
  déclare par chunk est celui que l'extracteur gouverné compte sur les
  octets réels. Une constante y rendrait le prédicat de qualité décoratif —
  le banc l'a d'ailleurs révélé en refusant, à raison.

Les autorisations de scope ne sont plus posées en base à la main : le banc
sert l'artefact sur sa forge locale, fait approuver la PR de test, et
laisse `authorize_scope_cli` relire, vérifier et écrire — au protocole
**LOT41A-V2**, le seul que le publisher accepte.

## Refus et reprises, mesurés sur le worker réel

| Propriété | Comment elle est établie |
|---|---|
| Reprise après écriture produit, avant acquittement | le même job repasse en file (bail tombé) et est repris : **rien n'est dupliqué** — artefacts, placements et chunks identiques — et les quatre jobs sont acquittés une fois chacun |
| Mauvaise release | un worker portant les autorités d'une **autre** release ne publie rien, refuse en nommant sa raison, et laisse toutes les ressources en `NEEDS_REVIEW` |
| Identité d'artefact exigée | un job batch sans `artifact_id` est refusé sans repli vers « le plus récent » ; A autorisé est utilisé même lorsque B est plus récent |
| Attribution conservée | ce que le retrieval rend porte les faits que l'attestation a scellés, pas des valeurs recomposées à l'affichage |
| Octets du magasin | un fichier portant le bon nom mais d'autres octets est refusé à la lecture, pas plus loin |
| Conflit sans écrasement | une **seconde** revue, approuvée elle aussi, n'écrase pas l'attestation déjà enregistrée : `ATTESTATION_CONFLICT`, et la première reste intacte — même nombre, même digest, même revue |

## Qualification des autorités V2 réelles — mesure

Exécution des **chargeurs canoniques** sur les fichiers exacts des deux
releases V2. Lecture seule : aucun fichier scellé n'a été modifié.

Les **granularités** de `profile_gate_v2` sont confirmées par recomptage
indépendant : **11 collections, 315 artefacts distincts, 479 placements,
8 268 identités de chunks**.

**Les ensembles sont cohérents ; ce sont les résumés qui mentent.**

| Rapprochement (profile_gate_v2) | Résultat |
|---|---|
| publiés \ inventaire candidat | **0** |
| inventaire \ publiés | 4 (l'inventaire est plus large que la release — légitime) |
| actualité Δ inventaire | **0** dans les deux sens |
| publiés \ preuve PII | **0** |

`candidate_inventory.json` (`d906663b…`) — trois résumés contredisent ses
propres listes :

| Grandeur | Déclarée | Portée par les listes |
|---|---|---|
| `unique_artifacts` | 486 | **319** |
| `physical_objects` | 486 | **319** |
| `multi_placement_artifacts` | 0 | **167** |
| `placements` | 486 | 486 ✔ |
| `target_collections` | 11 | 11 ✔ |

Les `counts` des **onze** collections, eux, concordent avec leurs listes
(0/11 en écart) : le défaut est strictement au niveau racine.

`currentness_evidence.json` (`8fc2208d…`) — trois défauts de forme, pas
seulement des comptes :

1. `counts` déclare **26** artefacts là où le fichier en porte **486** ;
2. la granularité est **par placement** (486 entrées pour 319 contenus),
   alors que le contrat en attend une par **contenu**, portant tous ses
   placements dans `placement_facts` ;
3. **469 des 486** entrées `CURRENT` ont `current_download_url: null`, que
   le contrat interdit pour une décision `CURRENT`.

**Origine.** Les producteurs courants
(`services/rag-pedago/scripts/build_production_profile_release.py`)
calculent aujourd'hui ces comptes depuis leurs propres listes et émettent
une actualité `…_V2` groupée par contenu. Les fichiers scellés sur disque
sont donc **antérieurs à cette correction**. Le remède n'est pas de
retoucher un fichier scellé — ce serait en changer l'empreinte, donc le
manifeste, donc les payloads et les attestations qui la nomment — mais de
**régénérer la release sous gouvernance**. Rien ici ne permet d'affirmer
que la régénération passerait : elle n'a pas été exécutée.

**Conséquence inchangée** : Worker B ne peut pas démarrer sur la release V2
réelle. Le refus survient sur la première autorité, avant l'actualité. Le
banc n'en dépend pas : il utilise des autorités de test nommées comme telles.

## Suites exécutées

```bash
# Acceptation batch — 15 collectés, 15 verts, 0 ignoré (132,7 s)
cd services/rag-engine && NEXUS_BATCH_CLI_ACCEPTANCE=1 \
RAG_EMBEDDING_MODEL_CACHE_DIR=<artefact E5 58ad18db…> \
PYTHONPATH=src:../../packages/contracts/src \
.venv/bin/python -m pytest tests/integration/test_batch_publication_cli_acceptance.py \
  -p no:warnings -q --junit-xml=<chemin>/acceptation_15.xml

# Suite unitaire rag-engine — 3 955 tests, 0 échec, 1 ignoré
cd services/rag-engine && PYTHONPATH=src:../../packages/contracts/src \
.venv/bin/python -m pytest tests/ -p no:warnings -q --ignore=tests/integration \
  --junit-xml=<chemin>/suite_unitaire.xml

# Contrats — 925 tests, 0 échec
.venv/bin/python -m pytest ../../packages/contracts/tests -p no:warnings -q
```

`test_openapi_schema_drift::test_le_schema_publie_est_celui_du_runtime`,
signalé rouge dans les sessions précédentes, **passe** dans cette
exécution : la dette de qualité logicielle correspondante est close.

### Dettes d'intégration, antérieures à ce lot

La suite d'intégration complète porte des rouges **qui ne viennent pas de ce
lot**. L'antériorité n'est pas argumentée : elle est **mesurée par égalité
d'ensembles**. La suite entière a été exécutée deux fois, seule, l'une après
l'autre — au commit parent `b0c87971` dans un worktree détaché, puis sur ce
lot :

| | Parent `b0c87971` | Ce lot |
|---|---|---|
| Tests collectés | 518 | 532 (les 14 de ce lot) |
| Échecs | 19 | 19 |
| Erreurs | 12 | 12 |
| Ensemble des noms rouges | **identique des deux côtés** — `diff` vide | idem |

Aucun rouge n'apparaît, aucun ne disparaît. Ils sont diagnostiqués un par un
dans `docs/reports/lot_go_live_cu_dettes.md` — trois attentes de test qui ont
vieilli (un message de refus devenu plus précis, une tête de schéma passée
de 15 à 17, un argument devenu obligatoire) et un défaut d'outillage réel
(le script de rollback place un `LOCK TABLE` hors transaction).

Une cinquième dette a été **close** par ce lot : `make typecheck` était rouge
au parent comme ici (13 constats, 6 fichiers), ce qui empêchait `make test`
de s'exécuter dans le job CI du service. Elle est levée sans toucher à
aucune logique ; `mypy src` ne rend plus aucun constat sur 147 fichiers.

Les suites que ce lot fait vivre sont vertes, y compris celles qu'il touche
sans les avoir écrites : `test_sealed_release_ingestion_pg.py` 13/13 et
`test_h2f_artifact_attribution_pg.py` 40/40.

Garde-fous de gouvernance, exécutés séparément :

```bash
bash scripts/check-governance-locks.sh   # 18 verrous confrontés au baseline, aucun écart
.venv/bin/python -m pytest -q scripts/tests/   # 538 passés, 7 ignorés
```

`scripts/ci-local.sh` **n'a pas été exécuté** : sa première action sur
`rag-engine` est `make install`, qui réinstalle `requirements.lock`
(pydantic 2.9.2) par-dessus le venv du banc (2.13.4). Ce monolithe est un
défaut **déjà mesuré et antérieur** — la commande aboutit, le graphe est
`ResolutionImpossible`, `pip check` échoue — et l'exécuter aurait détruit
l'environnement qui porte les preuves de ce lot sans rien établir de neuf.
Ses cibles vérifiables ont donc été lancées directement : contrats, suite
unitaire, lint, typecheck, verrous de gouvernance et tests de scripts.

Qualité : `ruff` vert sur `src/` et `tests/`. `mypy src` — la cible réelle
de `make typecheck` — **ne rend plus aucun constat** sur 147 fichiers, alors
qu'il en rendait 13 au commit parent.

## Qualification PII bornée — mesure datée du 2026-09-22

Les deux conditions que les preuves historiques n'établissaient pas —
**identités des pages scannées** et **erreurs d'extraction** — sont
désormais établies pour les **315 contenus publiés** de `profile_gate_v2`.

La mesure a été produite par l'outil gouverné prévu pour cela
(`services/rag-pedago/scripts/rescan_pii_corpus.py`), hors ligne, sur le
miroir local adressé par contenu. Chaque fichier est **rehaché** avant
d'être mesuré : une mesure sur d'autres octets ne dirait rien de ce
contenu. Aucune correspondance brute n'est transportée
(`raw_pii_in_output: false`).

Artefact : `docs/reports/evidence-index/pii_rescan_profile_gate_v2_315_20260922.json`
(`f449a2b8…`), ensemble mesuré `04b731e2…`.

| Ce qui est établi | Résultat |
|---|---|
| Périmètre | 315 mesurés = 315 publiés, aucun écart dans les deux sens |
| Identité des pages | `pages_scanned` mesuré == `page_count` du catalogue == déclaration historique, **315/315** |
| Pages sans texte | **0** sur l'ensemble des 315 documents — l'égalité des cardinalités est donc adossée à un fait par page, et non plus supposée |
| Erreurs d'extraction | **0** — dimension qu'aucun champ de la preuve historique ne portait |
| Texte réellement lu | `characters_scanned` **identique à l'historique pour 315/315** : l'ancienne mesure avait bien lu le même texte |

### Ce que la mesure révèle en plus

**22 des 315 contenus portent un signal** sous le scanner courant, là où la
preuve scellée les déclare tous `CLEARED` :

| Classe de signal | Contenus |
|---|---|
| `postal_address` | 12 |
| `phone_french` | 9 |
| `student_name_pattern` | 3 |
| `email_address` | 2 |
| `french_ssn` | 1 |

Ce n'est **ni une réfutation, ni une correction rétroactive** : la politique
est identique (`d09cbfd2…`, inchangée depuis le 13/08/2026) et le texte lu
est identique, mais **le scanner a changé**. La preuve scellée déclare
l'avoir été produite par `8ec8af55…` (`production-profile-gate-v1`) ; le
fichier courant hache `388e3ed4…`, modifié le 03/09/2026. Un verdict
différent rendu par un scanner différent est une **nouvelle mesure datée**,
et c'est exactement ce que cet artefact est.

**Une incohérence d'autorité s'y ajoute** : le manifeste de la release
déclare `authorities.pii_scanner_sha256 = 388e3ed4…` — le scanner
**courant** — alors que la preuve PII qu'il scelle a été produite par
`8ec8af55…`. Rien au runtime ne confronte ces deux valeurs : le worker ne
vérifie que `pii_evidence_sha256` et `pii_policy_sha256`. C'est la même
famille de défaut que les `counts` : une déclaration que rien ne confronte
à ce qu'elle décrit.

**Conséquence** : publier ces 22 contenus **sous le scanner courant**
exigerait la voie de revue humaine PII (ADR-0047) — jeu de décisions signé,
reçu, ancre et index — et non un simple report de l'ancien verdict. Aucune
admission n'est inventée ici : la mesure dit ce qu'elle a vu, à sa date.

Enfin, `pii_evidence.json` liste **486 résultats pour 319 contenus
distincts** — même granularité par placement que l'actualité — et son
`summary` compte 486/486, c'est-à-dire la longueur de sa liste et non ses
contenus.

## Complétude : 319 = 315 publiés + 4 exclus nommés

L'écart relevé plus haut — quatre contenus de l'inventaire candidat que la
release ne publie pas — se referme entièrement : la release **les nomme
elle-même**, dans `release_currentness_exclusion_registry.json`
(`NEXUS-CURRENTNESS-EXCLUSION-REGISTRY-V1`, ADR-0055, généré le
2026-09-17), avec pour chacun une raison :

| Contenu | Raison déclarée | Verdict |
|---|---|---|
| `157309db13b6` — Archive Éduscol 2024 / EAF | `ARCHIVE_DECLARED_BY_SOURCE_ADR_0055` | `BLOCKED_NOT_CURRENT_BY_SOURCE` |
| `174f273ff258` — Archive Éduscol DGEMC | idem | idem |
| `ccffe628bbd6` — Archive Éduscol SVT voie technologique | idem | idem |
| `dc58fcc42ef9` — Archive Éduscol SVT voie générale | idem | idem |

La complétude globale est donc **rapprochée et close** : 319 contenus
inventoriés = 315 publiés + 4 exclus, chacun avec sa raison. Aucun contenu
n'est perdu sans explication.

### Deux autorités de la même release se contredisent sur ces quatre-là

`currentness_evidence.json` déclare ces quatre contenus `decision: CURRENT`,
`effective_currentness: actuel`. Le registre d'exclusions, **postérieur**,
les déclare `ARCHIVE_DECLARED` et bloqués comme **non actuels à la source**.

Dans les faits la release a tranché — elle ne les publie pas — et le runtime
est protégé pour une raison indirecte : ce n'est pas l'actualité qui décide
de ce qui se publie, c'est l'**allowlist** de la release, où ces quatre ne
figurent pas. Mais **rien ne confronte les deux autorités** : un worker qui
suivrait l'actualité seule les tiendrait pour actuels. Même famille que les
`counts` — une déclaration que personne ne compare à ce qu'elle décrit.

### Leur statut PII indécis est levé

Trois des quatre portaient `PII_CLEARED_OR_NOT_SCANNED` — une disjonction
qui n'établit rien. Mesure du 2026-09-22, même outil gouverné, artefact
`docs/reports/evidence-index/pii_rescan_profile_gate_v2_exclus_4_20260922.json`
(ensemble `7679ee81…`) :

| Contenu | Déclaré | Mesuré |
|---|---|---|
| `174f273ff258`, `ccffe628bbd6`, `dc58fcc42ef9` | `PII_CLEARED_OR_NOT_SCANNED` | **aucun signal, aucune erreur d'extraction** — la disjonction est levée du bon côté |
| `157309db13b6` | `PII_CLEARED` | **un signal** `student_name_pattern` |

Le dernier cas est le même phénomène que les 22 contenus publiés : scanner
différent, verdict différent. Aucune conséquence de publication ici — ces
quatre sont exclus — mais la mesure dit ce qu'elle a vu, à sa date.

## Une confrontation mal placée, corrigée par la mesure

La dérivation d'attribution scellée confrontait d'abord `type_doc` au
**périmètre de découverte** du profil (`expected_resource_types`), par
analogie avec le chemin unitaire. La suite d'intégration de l'ingestion
scellée l'a refusée aussitôt, et la mesure sur la release réelle a donné la
raison :

| Mesure sur `profile_gate_v2` | Résultat |
|---|---|
| Placements | 479 |
| Placements dont le `type_doc` sort du périmètre de leur profil | **224** (47 %) |
| Types concernés | `autre` 66, `programme_officiel` 57, `diaporama` 52, `modalite_examen` 45, `annale` 4 |
| Périmètre déclaré par chacun des **onze** profils `v2_livraison_319` | `['ressource_officielle']` — un seul type |

Un type scellé **n'est pas une proposition de Scout**. Il est produit par la
correspondance gouvernée depuis le vocabulaire externe, et le résolveur de
placement le **redérive indépendamment** au moment de publier avant de
refuser toute divergence. Lui appliquer en plus le périmètre de découverte,
c'était appliquer à une release approuvée un critère que personne ne lui a
appliqué — et bloquer près de la moitié de ses placements.

La confrontation a donc été retirée de la dérivation, et ce qui reste y est
bien une autorisation : le type doit être une valeur canonique de `TypeDoc`
— ce qui refuse précisément le nom de collection que le batch publiait — et
l'hôte de provenance doit être un domaine que le profil autorise.

Reste une question de gouvernance, posée et non tranchée ici : onze profils
n'attendent qu'un seul type documentaire quand la release approuvée en porte
cinq. Que ce soit le profil qui soit trop étroit ou la release qui déborde,
cela se décide hors de l'attribution.

## État de la CI GitHub (PR #246)

GitHub Actions est disponible et s'exécute sur cette branche. Treize
contrôles passent, dont `real-model acceptance (E5 + reranker + pgvector)`,
`worker image integration (docker)`, `access authority (C5)`, `governance
locks guard`, `services/cockpit`, `services/rag-pedago` et les trois
paquets.

Ce qui reste rouge, et pourquoi :

| Contrôle | Cause |
|---|---|
| `trusted-human-review/head-pinned` et `Evaluate trusted human review` | **par construction** : aucune approbation humaine n'est épinglée au head exact. C'est le gate qui doit rester rouge jusqu'à la revue |
| `governance postgres` | les dettes 2 et 4 du registre. La dette 2 est close et la 4 l'est aux deux tiers ; la dernière épreuve touche des migrations **empreintées** et demande une migration de rattrapage |
| `services/rag-engine` | `make typecheck` **passe désormais** et `make test` s'exécute pour la première fois : il y révèle la dette 5 — la CI installe pydantic 2.9.2 quand le paquet de contrats exige 2.13.4 |

Aucun de ces rouges n'est introduit par ce lot : l'antériorité est prouvée
par égalité d'ensembles pour l'intégration, et par la même liste de 13
constats `mypy` au commit parent pour le typage. Les deux derniers sont
**apparus** parce que ce lot a rouvert le chemin qui y mène.

## Dossier d'exécution staging

L'ordre ci-dessous est celui des **dépendances**, pas celui du confort : chaque
étape refuse tant que la précédente n'a pas eu lieu. Rien n'y est exécuté par
ce lot — aucune écriture sur staging n'a été faite.

### 0. Préconditions

| Élément | Exigence |
|---|---|
| Environnement | `NEXUS_ENVIRONMENT=rehearsal` (ou `production`) avec manifeste de readiness signé et ancre de confiance |
| Rôles PostgreSQL | contrôle d'ingestion (`app`, `authority`, `attestor`) et base produit (`publisher`) **distincts** ; le worker refuse un DSN unique |
| Modèle | artefact E5 monté, `--embedding-inventory-sha256` égal à celui que la release déclare |
| Magasin | `<store>/<content_sha256>.pdf` pour chaque artefact ; les octets sont re-mesurés à la lecture |
| Forge | la revue approuvée doit rester lisible au head exact : elle est **relue à chaque publication**, pas une fois pour toutes |

### 1. Régénérer les deux autorités V2 incohérentes

`candidate_inventory.json` et `currentness_evidence.json` sont antérieurs à
la correction de leurs producteurs. Tant qu'ils ne sont pas régénérés,
`load_multilevel_candidate_inventory` refuse sur la **première** autorité et
Worker B ne démarre pas. La régénération change leurs empreintes, donc le
manifeste, donc les payloads scellés et les attestations qui les nomment :
c'est une **re-release gouvernée**, à instruire comme telle.

### 2. Établir l'attribution des artefacts déjà ingérés

```bash
python -m ingestor.ingestion_worker.sealed_release_ingestion_cli \
  --only-attributions \
  --release-dir <release> \
  --release-manifest-sha256 <…> --artifacts-release-sha256 <…> \
  --candidate-inventory-sha256 <…> \
  --artifact-transfer-manifest-path <…> --artifact-transfer-manifest-sha256 <…> \
  --artifact-store-dir <store> --profiles-dir <profils> \
  --owner <opérateur> --expected-role ingestion_control_app \
  --report-path <rapport>.json
```

N'ingère rien. Écrit les attributions manquantes, dérivées du catalogue de
la release. Idempotent ; une attribution divergente est un refus.

**Ses préconditions sont vérifiées sur les données de V2 elles-mêmes**
(lecture seule) : sur les 479 placements, **0** provenance hors des domaines
que son profil autorise, **0** type documentaire non canonique, et les onze
profils portent `source_authority: official`. Les 479 paires
(collection, artefact) sont distinctes : aucune ambiguïté d'attribution.
Attendu, donc : `examined=479`, `written=479`, `missing_rows=0` — la seule
inconnue restante étant que les 479 lignes de contrôle existent bien dans la
base visée.

### 3. Décider du cas PII des 22 contenus signalés

Sous le scanner courant, 22 des 315 contenus publiés portent un signal que
la preuve scellée déclare `CLEARED`. Deux voies, et deux seulement :

- publier **sous le scanner qui a produit la preuve** (`8ec8af55…`), en le
  déclarant comme tel — la release doit alors nommer ce scanner, ce que son
  manifeste ne fait pas aujourd'hui ;
- ou instruire la **revue humaine ADR-0047** (jeu de décisions signé, reçu,
  ancre, index, allowlist) pour ces 22 contenus, et publier sous le scanner
  courant.

Aucune troisième voie : reporter l'ancien verdict sous un scanner différent
serait inventer une admission.

### 4. Proposer, faire approuver, enregistrer l'attestation batch

```bash
python -m ingestor.ingestion_worker.attest_publication_cli \
  propose-release-batch-review --release-id <…> --release-dir <…> …
# → l'artefact canonique est publié sur la PR de revue, approuvé par un humain
python -m ingestor.ingestion_worker.attest_publication_cli \
  record-release-batch-attestation --release-id <…> --review-id <…> \
  --repository <…> --pull-request <n> --expected-head <sha> \
  --review-artifact-path <chemin canonique>
```

Une projection portant une condition inconnue **ou négative** refuse ici.
Une attestation déjà présente et divergente refuse aussi : pas d'écrasement.

### 5. Créer les jobs, puis lancer Worker B

Chaque job **nomme son artefact** (`artifact_id`), dérivé de l'attestation
enregistrée. Un job batch sans cette identité est refusé sans repli.

```bash
PG_RAG_DSN=<produit> python -m ingestor.ingestion_worker.multilevel_publication_resume_cli \
  --profiles-dir <profils> --artifact-store-dir <store> \
  --owner <worker> --expected-role ingestion_control_app \
  --embedding-artifact-root <E5> --embedding-inventory-sha256 <…> \
  --max-iterations <n> \
  --artifact-transfer-manifest-path <…> --artifact-transfer-manifest-sha256 <…> \
  <les autorités multi-niveaux>
```

### 6. Vérifier indépendamment

Un code de sortie nul ne suffit pas. Relire, dans les deux bases : l'état
`RETRIEVAL_ELIGIBLE` des ressources, le statut des jobs, l'artefact exact,
ses droits, son type documentaire, sa provenance, les placements par
collection et les chunks (modèle et dimension), puis **récupérer le contenu
par le chemin de retrieval** sous le rôle prévu.

Une interruption entre l'écriture produit et l'acquittement d'un job n'exige
rien de particulier : le bail tombe, le job est repris, et la reprise ne
duplique rien.

## Point de reprise — fin de session du 2026-09-22

| Élément | Valeur |
|---|---|
| Branche | `go-live/cu-batch-projection-and-pii-reconciliation` |
| Pull request | **#246** — `go-live (lot CU) : le parcours batch atteint l'index produit, et le contenu est récupéré` |
| Dernier maillon atteint | **publication produit et retrieval** — le parcours batch est complet sur le banc |
| Modifications locales | aucune |
| Environnement | aucun conteneur ni processus à conserver ; les bases du banc sont créées et détruites par les fixtures ; aucun secret monté |

Un point d'environnement à connaître : le worktree détaché qui a servi à
prouver l'antériorité des dettes (sous le répertoire de travail temporaire
de la session) **reste enregistré**. Il ne peut pas être supprimé sans
privilège : une fixture Docker y a créé
`services/rag-engine/infra/configs` appartenant à `root`. Aucun privilège
n'a été escaladé pour le retirer. `git worktree prune` nettoiera
l'enregistrement dès que le répertoire temporaire disparaîtra ; supprimer le
répertoire lui-même demande `root`. Le même répertoire appartient aussi à
`root` dans le dépôt principal, depuis le 7 août — antérieur à cette
session.

### Prérequis d'exécution du banc

```bash
export NEXUS_BATCH_CLI_ACCEPTANCE=1
export RAG_EMBEDDING_MODEL_CACHE_DIR=<artefact E5 dont SHA256SUMS vaut 58ad18db…>
```

L'artefact E5 est exigé et jamais supposé : son absence est un refus nommé,
pas un test ignoré. Docker est requis (deux instances PostgreSQL jetables :
contrôle d'ingestion et produit).

### Travaux suivants, par ordre de dépendance

1. **Attribution des artefacts scellés déjà ingérés.** Les lignes acquises
   ne portent pas les quatre faits d'attribution ; ils doivent leur être
   établis depuis le catalogue de leur propre release, sans nouvelle
   ingestion. C'est la condition d'une publication réelle de V2.
2. **Régénération gouvernée des deux autorités V2** (inventaire candidat et
   actualité), avec la liaison d'autorité applicable : leurs listes sont
   déjà cohérentes, leurs résumés et la granularité de l'actualité ne le
   sont pas.
3. **Revue humaine PII (ADR-0047)** pour les 22 contenus que le scanner
   courant signale, si la publication doit avoir lieu sous ce scanner. La
   qualification bornée elle-même est **faite** (mesure du 2026-09-22) ;
   ce qui reste est une décision humaine, qui ne s'invente pas.
4. **Complétude globale** rapprochée de l'inventaire approuvé.

Aucune écriture sur staging ou production n'a eu lieu dans cette session.
Les 479 placements acquis de V2, leurs identifiants, leurs runs et leurs
événements historiques sont intacts : rien n'a été ingéré, réécrit ni
supprimé hors des bases jetables du banc.
