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
| 2 | `_verify_release_batch_attestation` dérivait les quatre faits d'attribution de `collection` et de `profile_id` : le batch publiait **le nom de sa collection en guise de type documentaire**, jusque dans `rag_chunks.type_doc`, que le retrieval lit | les faits sont lus dans leur foyer durable (migration 012). L'ingestion scellée les dérive du catalogue d'artefacts de la release — dont l'empreinte est portée par l'artefact de revue approuvé — et les confronte au périmètre du profil |
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
# Acceptation batch — 13 collectés, 13 verts, 0 ignoré (112,9 s)
cd services/rag-engine && NEXUS_BATCH_CLI_ACCEPTANCE=1 \
RAG_EMBEDDING_MODEL_CACHE_DIR=<artefact E5 58ad18db…> \
PYTHONPATH=src:../../packages/contracts/src \
.venv/bin/python -m pytest tests/integration/test_batch_publication_cli_acceptance.py \
  -p no:warnings -q --junit-xml=<chemin>/acceptation_13.xml

# Suite unitaire rag-engine — 3 949 tests, 0 échec, 1 ignoré (108,5 s)
cd services/rag-engine && PYTHONPATH=src:../../packages/contracts/src \
.venv/bin/python -m pytest tests/ -p no:warnings -q --ignore=tests/integration \
  --junit-xml=<chemin>/suite_unitaire.xml

# Contrats — 925 tests, 0 échec
.venv/bin/python -m pytest ../../packages/contracts/tests -p no:warnings -q
```

`test_openapi_schema_drift::test_le_schema_publie_est_celui_du_runtime`,
signalé rouge dans les sessions précédentes, **passe** dans cette
exécution : la dette de qualité logicielle correspondante est close.

Qualité : `ruff` vert sur `src/` et `tests/`. `mypy` sur les sept sources
touchées ne rend que des constats **préexistants** (lignes non modifiées) ;
les deux constats introduits ont été corrigés.

## Point de reprise — fin de session du 2026-09-22

| Élément | Valeur |
|---|---|
| Branche | `go-live/cu-batch-projection-and-pii-reconciliation` |
| Dernier maillon atteint | **publication produit et retrieval** — le parcours batch est complet sur le banc |
| Modifications locales | aucune hors ce rapport |
| Environnement | aucun conteneur ni processus à conserver ; les bases du banc sont créées et détruites par les fixtures ; aucun secret monté |

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
3. **Qualification PII bornée** : les preuves historiques établissent les
   compteurs, pas les identités de pages scannées ni les erreurs
   d'extraction. Une mesure actuelle portera sa date réelle.
4. **Complétude globale** rapprochée de l'inventaire approuvé.

Aucune écriture sur staging ou production n'a eu lieu dans cette session.
Les 479 placements acquis de V2, leurs identifiants, leurs runs et leurs
événements historiques sont intacts : rien n'a été ingéré, réécrit ni
supprimé hors des bases jetables du banc.
