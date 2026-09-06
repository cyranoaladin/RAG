# Incident d'extraction partielle — requalification de la campagne `239103dc…`

> Aucune matière brute ici : uniquement des `content_sha256`, des numéros de
> page, des classes de verdict et des compteurs.

## 1. Le défaut

`extraction_gouvernee` (V1) décidait de l'océrisation au niveau du
**document** : elle n'y recourait que si AUCUNE page ne rendait de texte. Un
document qui portait une couche textuelle **et** des pages muettes non
ignorables — page-image, tracé vectoriel, opérateurs de texte non décodables —
voyait ces pages rendues comme du texte vide.

Conséquences en chaîne, toutes silencieuses :

- le scanner PII lisait du **vide** là où la page affiche du contenu ;
- le découpage n'en produisait **aucun chunk** ;
- `canonical_text_sha256` scellait un texte **amputé** ;
- rien, dans aucun compteur, ne distinguait ce cas d'une page réellement blanche.

Découvert par le refus du préparateur de paquets de revue PII sur
`PAGE_TEXTE_NON_DECODABLE:pages 2` — c'est-à-dire par un garde-fou, pas par un
contrôle de la campagne.

## 2. Requalification des verdicts V1

```
PROCESSING_RUN_239103DC_COMPLETED=PASS
PROCESSING_RUN_239103DC_RECONCILED=PASS
PROCESSING_RUN_239103DC_DRIFT=0
FINAL_PDF_CANONICAL_EXTRACTION=NOT_PROVEN
FINAL_PII_CLEARANCE=INVALIDATED
FULL_GDRIVE_PDF_PROCESSING=NOT_FINAL
V1_DISPOSITION=SUPERSEDED_FOR_FINAL_SERVING__KEPT_AS_DIFFERENTIAL_BASELINE
```

Le run V1 reste **exact sur ce qu'il mesure** : il prouve fidèlement ce que
l'algorithme V1 a produit. Ce qui est invalidé, c'est l'usage qu'on voulait en
faire — déclarer le corpus lu, donc publiable. Un scanner qui n'a pas lu une
page ne l'a pas déclarée saine.

La base V1 est **conservée intacte** (`drive_staging.artifacts` = 2473,
`chunks` = 23874, `provenances` = 2473). Aucun `UPDATE` n'y est appliqué : elle
sert de référence différentielle.

## 3. Audit exhaustif des pages muettes — les 2473 PDF, sans échantillon

Politique auditée : `NEXUS-PDF-PAGE-POLICY-V1`, extraction native seule
(aucun OCR : on mesure la population, on ne la corrige pas).

```
PDF_TOTAL=2473
PAGE_TOTAL=26736
DOCS_WITH_NATIVE_EMPTY_PAGE=44
NATIVE_EMPTY_PAGES_TOTAL=141
IGNORABLE_EMPTY_PAGES=54
NON_IGNORABLE_EMPTY_PAGES=87
DOCS_WITH_NON_IGNORABLE_EMPTY_PAGE=28
PAGE_IMAGE_NON_LISIBLE=72
PAGE_TEXTE_NON_DECODABLE=5
PAGE_TRACE_VECTORIEL=10
PAGE_INSPECTION_FAILED=0
AFFECTED_PREVIOUSLY_PII_CLEARED=26
AFFECTED_PREVIOUSLY_PII_DETECTED=2
AFFECTED_CONTENT_SET_SHA256=84ca339bbfe1851c0d78e151d5ef030ffcead81f17b6a8da7a798eaad64040eb
```

`72 + 5 + 10 = 87` et `87 + 54 = 141` : la partition est exacte.

### 3.1 Le périmètre réellement perdu n'est pas 28, mais 25

V1 océrisait correctement les documents **entièrement** muets. Sur les 28
documents portant au moins une page non ignorable, 3 étaient dans ce cas et ont
donc bien été océrisés. Les **25 autres sont mixtes** : c'est là que des pages
ont été perdues.

```
DOCS_FULLY_SILENT_ALREADY_OCRED_BY_V1=3
DOCS_MIXED_PAGES_LOST_BY_V1=25
PAGES_LOST_BY_V1=61
LOST_CONTENT_SET_SHA256=6e1317595c949b66f4d2c2d2a1cafd6c17837148e450ec5f6c1e31c061ac8616
LOST_PREVIOUSLY_PII_CLEARED=23
LOST_PREVIOUSLY_PII_DETECTED=2
```

Ne pas faire cette distinction aurait surestimé l'incident et, surtout, aurait
laissé croire que V1 n'océrisait jamais — ce qui aurait masqué la vraie règle
fautive (« décider au niveau du document »).

## 4. Correction à la racine — `NEXUS-DRIVE-PDF-EXTRACTION-V2`

La décision passe au niveau de la **page**. Composition :

```
EXTRACTION_POLICY_ID   = NEXUS-DRIVE-PDF-EXTRACTION-V2
PAGE_COMPOSITION_RULE  = NATIVE_TEXT_KEPT__OCR_FILLS_ONLY_NON_IGNORABLE_EMPTY
OCR_FALLBACK_POLICY    = NON_IGNORABLE_EMPTY_PAGES_ONLY
```

L'identité de la politique lie : extracteur natif + version `pypdf` canonique,
identifiant **et empreinte du module** de la politique de page, identifiant de
normalisation textuelle, politique de repli OCR, identité du runtime OCR, règle
de composition. Une politique dont le code change sans changer d'identifiant
rendrait deux corpus incomparables sous la même étiquette.

### 4.1 Voies d'extraction, par page

| Voie | Sens |
|---|---|
| `NATIVE_TEXT` | la page rend du texte ; il n'est **jamais** remplacé |
| `STRUCTURAL_EMPTY` | muette et ignorable — une page de séparation n'enseigne rien |
| `OCR_FALLBACK` | muette, non ignorable, OCR concluant |
| `NOT_ASSESSABLE` | muette, non ignorable, **OCR sans résultat** |

`NOT_ASSESSABLE` **bloque la publication** du document. L'OCR qui ne rend rien
n'est pas une page vide : c'est une page dont personne ne sait ce qu'elle
porte. La compter vide ferait dire au scanner PII qu'il l'a lue.

Sans runtime OCR disponible alors qu'une page l'exige, l'extraction **refuse**
(`TextLayerAbsente`) — elle ne rend pas un document amputé.

### 4.2 Provenance persistée, par page

`number`, `extraction_path`, `native_text_sha256`, `page_policy_verdict`,
`canonical_page_text_sha256`, `ocr_runtime_identity_sha256`.

`native_text_sha256` est conservé même quand la page est océrisée : c'est le
témoin qui permet de rejouer la décision. `canonical_page_text_sha256` est
l'empreinte du texte **retenu** — celui que le scanner PII lit et que le
découpage utilise ; les deux doivent citer la même.

### 4.3 Océrisation bornée aux pages nécessaires

`ocr_pdf_pages` accepte désormais `pages=`. Un document de 155 pages dont une
seule est illisible était océrisé en entier — 155 fois le coût du besoin. Une
sélection **vide** est un refus, pas une absence de sélection : les confondre
ferait océriser le document entier en croyant obéir.

## 5. Matrice de mutation — les épreuves tuent-elles vraiment le défaut ?

Une épreuve verte qui ne détecte pas la régression ne protège rien. Chaque
mutant a été appliqué au code V2, les épreuves relancées, puis le code restauré.

| Mutant | Effet | Résultat |
|---|---|---|
| M1 | décision au niveau du **document** (le défaut de V1) | **11 échecs** / 3 |
| M2 | OCR muet compté comme page vide | **1 échec** / 13 |
| M3′ | l'OCR prime sur le texte natif | **5 échecs** / 9 |
| M4 | panne d'inspection avalée | **13 échecs** / 1 |
| M5 | absence de runtime OCR silencieuse | **1 échec** / 13 |
| M6 | océrisation du document entier | **9 échecs** / 5 |

Un premier M3 (« OCR écrase le texte natif ») avait **survécu** : la mutation
était nulle, une page qui rend du texte n'entrant jamais dans l'ensemble
océrisé. Le mutant réel exige d'altérer **la sélection et la composition** —
M3′ ci-dessus. Le noter plutôt que de le taire : un mutant survivant mal
construit se lit comme une couverture qu'on n'a pas.

## 6. Différentiel exhaustif V1 → V2 — les 2473 documents

Confronté aux empreintes que la base V1 a **réellement enregistrées**
(`drive_staging.artifacts`), non à une ré-exécution de V1 : rejouer V1
prouverait que mon code V1 est stable, pas que le corpus servi correspond.

```
PDF_TOTAL=2473
V1_ARTIFACTS_IN_DB=2473
ABSENT_FROM_V1_DB=0
EXPECTED_CHANGED_DOCUMENTS=25
CHANGED_DOCUMENTS=24
UNCHANGED_DOCUMENTS=2449
UNEXPECTED_CHANGED_DOCUMENTS=0
EXPECTED_BUT_UNCHANGED=1
EXTRACTION_ERRORS=0
```

`UNEXPECTED_CHANGED_DOCUMENTS=0` : V2 ne touche à aucun document que l'audit
n'avait pas désigné. C'est ce qui autorise à requalifier le corpus plutôt qu'à
le redécouvrir.

`EXPECTED_BUT_UNCHANGED=1` — `a009392fc284f5cf…` : sa seule page refusée
(page 15, `PAGE_IMAGE_NON_LISIBLE`) reste illisible **après** OCR. Son texte
canonique ne change donc pas, mais sa **disposition** change : le document
passe de « PII claire » à non évaluable, donc non publiable.

### 6.1 Partition exacte des 87 pages non ignorables

```
PAGES_OCR_FALLBACK_V2=72
PAGES_NOT_ASSESSABLE_V2=15
DOCS_NOT_ASSESSABLE_V2=9
```

`72 + 15 = 87` : chaque page que la politique refuse d'ignorer est désormais
soit récupérée, soit **nommée comme non lue**. Aucune n'est plus comptée vide.

Les 9 documents non évaluables **bloquent leur propre publication**. Ce n'est
pas un échec de la campagne : c'est la première fois que ces pages sont
comptées pour ce qu'elles sont.

## 7. Rejeu OCR page par page — déterminisme

Si océriser deux fois la même page sous le même runtime rendait deux textes,
`canonical_page_text_sha256` ne prouverait rien. Mesuré sur **toutes** les
pages océrisées, pas un échantillon :

```
OCR_RUNTIME_IDENTITY=4090ff0754b32f2e4eca110f3e5378d3a02562e898a1f5aeaee7931696a04af2
PAGE_OCR_REPLAYED=87
PAGE_OCR_HASH_MATCH=87
PAGE_OCR_HASH_MISMATCH=0
```

## 8. Campagne V2 — `8bbaa039…`

PostgreSQL **neuf** (`nexus-drive-staging-v2`, image confrontée au digest
épinglé). Aucun `UPDATE` de la base V1, qui reste intacte.

```
FULL_DRIVE_RUN_ID=8bbaa039cfd4e99b69a6f4a72fe23f5fe9bb07e6f242f564380fd35a91e68611
CODE_COMMIT=6b6de0fa5fe9dd1c4e2ed60b3c7367f88b18735c   CODE_DIRTY=False
EXTRACTION_POLICY_ID=NEXUS-DRIVE-PDF-EXTRACTION-V2
MANIFEST_REVERIFIED=b14bad4bf358e0d86838d7daddc49d32bd61d9b9a5175649040afb9164d3eaf5
OCR_RUNTIME_IDENTITY=4090ff0754b32f2e4eca110f3e5378d3a02562e898a1f5aeaee7931696a04af2
OCR_CAPABILITY_SHA256=9095568785b27fd96edc4c9f127a8ef4bdf8a321f40f604355dd4ff635a84fe6
POSTGRES_IMAGE_MATCH=True   POSTGRES_SERVER_VERSION=16.14
PGVECTOR_EXTENSION_VERSION=ABSENTE
```

### 8.1 Partition des documents

```
DRIVE_PDF_DISTINCT_ARTIFACTS=2473
DRIVE_PDF_CLEARED_AND_STAGED=2315
DRIVE_PDF_QUARANTINED_PII=149
DRIVE_PDF_NOT_ASSESSABLE=9
DRIVE_PDF_UNCLASSIFIABLE=0
DRIVE_PDF_PROCESSING_ERRORS=0
DRIVE_PDF_UNACCOUNTED=0
PII_ATTEMPTED=2464   PII_CLEARED=2315   PII_DETECTED=149
PII_NOT_ASSESSABLE=9   PII_UNACCOUNTED=0
```

`2315 + 149 + 9 = 2473`. `PII_ATTEMPTED = 2473 − 9` : les 9 documents non
évaluables ne sont pas soumis au scanner — un « aucune PII » obtenu sur une
page que personne n'a lue ne parlerait que du silence de l'instrument.

L'écart avec V1 est exactement celui attendu : `PII_CLEARED` passe de 2324 à
2315, les 9 documents non évaluables sortant du seau « clair ». Les 149
détections restent 149.

### 8.2 Partition des pages

```
PAGES_TOTAL=26736
PAGES_NATIVE_TEXT=26595
PAGES_STRUCTURAL_EMPTY=54
PAGES_OCR_FALLBACK=72
PAGES_NOT_ASSESSABLE=15
```

`26595 + 54 + 72 + 15 = 26736` — identique au `PAGE_TOTAL` de l'audit §3.

### 8.3 Réconciliation en base

```
ARTIFACTS_TOTAL=2473          PROVENANCES_TOTAL=2473
CHUNKS_TOTAL=23744            PAGE_PROVENANCES_TOTAL=26736
ARTIFACTS_WITHOUT_PAGE_PROVENANCE=0
ARTIFACTS_WITHOUT_CHUNKS=158            (149 quarantaine + 9 non évaluables)
NOT_ASSESSABLE_DOCS_WITH_CHUNKS=0
OCR_PAGES_WITHOUT_RUNTIME_IDENTITY=0    DISTINCT_OCR_RUNTIMES=1
DUPLICATE_ARTIFACT_IDENTITIES=0         DUPLICATE_CHUNK_IDENTITIES=0
PII_CANONICAL_TEXT_SHA_MISMATCH=0
NOT_ASSESSABLE_CANONICAL_TEXT_SHA_MISMATCH=0
```

### 8.4 Reproductibilité depuis le corpus scellé

Extraction et découpage rejoués sur les 2473 documents, confrontés à ce que la
base porte :

```
CANONICAL_TEXT_REPRODUCED=2473    CANONICAL_TEXT_MISMATCH=0
PAGE_PROVENANCE_REPRODUCED=2473   PAGE_PROVENANCE_MISMATCH=0
CHUNK_SET_REPRODUCED=2473         CHUNK_SET_MISMATCH=0
```

C'est aussi la preuve d'identité PII ↔ découpage : le texte réextrait qui
redonne les mêmes chunks est celui dont l'empreinte a été soumise au scanner.

### 8.5 Un lien physique dans le corpus scellé

La campagne a d'abord **refusé** de démarrer : `generate_sealed_manifest` a
détecté 149 fichiers à `nlink=2`. La préparation des paquets de revue PII avait
créé un miroir adressé par contenu par liens physiques — les mêmes octets
atteignables par deux chemins rendent le corpus scellé mutable par une seconde
voie.

Corrigé **à la cause**, pas à la garde : le miroir a été détaché (copies
indépendantes, `0600`), `MIROIR_DETACHE=149`, `DIVERGENCES=0`, corpus revenu à
`nlink=1` partout.

## 9. Ce qui reste dû avant toute revue humaine PII

- **préparateur de paquets** : lui faire consommer le texte canonique de la
  base V2 au lieu de re-décider du sens d'une page, et prouver
  `bundle_canonical_text_sha256 == DB_canonical_text_sha256` sur les 149 ;
- **disposition des 9 documents non évaluables** — aucun ne peut être servi ;
  la décision (réparer la source, accepter la perte, exclure) revient au
  commanditaire.

Les 149 paquets de revue PII préparés sous V1 ne sont **pas** soumis : ils
porteraient un texte amputé.

## 10. Preuves scellées (hors dépôt, `0600`, adressées par contenu)

| Preuve | sha256 |
|---|---|
| audit exhaustif des pages muettes | `0bb06d26fe9388da14e23ef60ebc55ce3e66b05348a2559fa1e6eb3107a067d7` |
| partition mixtes / entièrement muets | `4d4ea07240c77891252d1a48d71e058f4fefca9c20fb72430f3d9f083f32aca4` |
| différentiel V1→V2 | `2aa3badf893545f5f90ca4274f9a3d85f5a7effee7d099871132a9c8e55db7fe` |
| provenance de page V2 (2473 documents) | `ed0d2d37a1e98d0b4e1f50e3c1668cd48c7b6ac2d06203c082b3f1d69b74f389` |
| rejeu OCR par page | `0cee17e179c6e66246087dbacc3fbfd61a1d6dea33fbe29307fd8211cd81247a` |
| rapport de campagne V2 | `10b685b9cb84ae3b57b297fa6df049f992dbbb5b409daa7d3b4d0e2a97ba2168` |
| reproductibilité V2 | `383c3e3ac1f7d274932bd71e537cc7157f0459aac04f11536bed4fddbe1e9472` |
| réconciliation base V2 | `91529db2d81a4f009bbeb73ddb491833437e3f8d9861cd632c700c41fb6f82aa` |
