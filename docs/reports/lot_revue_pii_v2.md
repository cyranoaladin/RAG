# Revue PII de la campagne V2 — préparation des 149 paquets

> Aucune matière brute : `content_sha256`, `drive_file_id`, classes de motif,
> comptes, numéros de page, identifiants de preuve.

## 1. Le préparateur ne ré-extrait plus (§ 6)

Le préparateur lisait le PDF et en tirait son propre texte. Il re-décidait donc
du sens d'une page, et pouvait présenter au reviewer un texte que ni le scanner
PII ni le découpage n'avaient vu. C'est exactement le chemin par lequel
l'extraction partielle V1 a traversé toute la chaîne.

La règle est désormais : **sortie canonique du traitement V2 → entrée de revue**.

## 2. `NEXUS-CANONICAL-REVIEW-INPUT-V1` (§ 7)

Le texte de revue n'est pas produit, il est **retrouvé**. L'exporteur rejoue
l'extraction gouvernée puis confronte, avant d'écrire quoi que ce soit :

- la provenance de **chaque page** (voie, empreinte du texte natif, verdict de
  politique, empreinte de la page canonique, identité du runtime OCR) ;
- l'empreinte du **texte canonique** du document ;

à ce que la base du run porte réellement. Toute divergence est un refus.

```
CANONICAL_REVIEW_INPUT_SCHEMA=NEXUS-CANONICAL-REVIEW-INPUT-V1
CANONICAL_REVIEW_INPUT_CONTENTS=149
CANONICAL_REVIEW_INPUT_CONTENT_SET_SHA256=45afb75aec3bd0f07a6f46aeafec367bf41617eb51739e90359ff3a43ecde389
CANONICAL_REVIEW_INPUT_MANIFEST_SHA256=4af05532b718f2834583c30477671c26b3cd48efcf085ef7200b1ff59836f1ac
```

Le runtime OCR est **exigé identique** à celui du run (`require_runtime`) : un
autre moteur rendrait un autre texte sur les pages océrisées, et l'export
échouerait plus loin sur une divergence dont l'origine serait perdue.

La matière sort hors dépôt, `0700`/`0600`.

## 3. Ce que l'export a attrapé, et que je n'aurais pas vu

Le premier passage a **refusé** : `page 11 : le texte de l'entrée canonique ne
correspond pas à son empreinte déclarée`.

Cause : je relisais les pages en mode texte, où Python traduit `\r\n` et `\r`
en `\n`. Le texte canonique du corpus gouverné contient de **vrais retours
chariot** — les traduire aurait présenté au reviewer un texte différent de
celui qui a été scanné. Corrigé en lecture et écriture d'**octets**, et scellé
par une épreuve dont la page porte un `\r\n`.

C'est la garde d'empreinte qui l'a trouvé sur un document réel, pas une
relecture du code.

## 4. Les paquets (§ 8, § 10)

Un paquet porte le **PDF source exact** — le reviewer doit pouvoir confronter
le finding au document — mais **aucun finding n'est recalculé depuis une
nouvelle extraction**. Les correspondances sont localisées dans le texte
canonique, et leur agrégat est confronté au registre PII du run : si le nombre
de correspondances, les classes ou les pages divergent, ce n'est pas le paquet
qui est faux, c'est que le scanner ou la politique ont bougé sous une lignée
qui prétend ne pas avoir bougé. Refus.

Chaque finding nomme la provenance de sa page :

```
page_number  extraction_path  page_policy_verdict
canonical_page_text_sha256    ocr_runtime_identity_sha256
```

```
FINDINGS_TOTAL=479
FINDINGS_BY_EXTRACTION_PATH = {NATIVE_TEXT: 478, OCR_FALLBACK: 1}
DOCS_WITH_OCR_SOURCED_FINDING=1
```

Ce **1** est la détection que V1 ne pouvait pas voir : elle se situe sur une
page que V1 comptait vide. C'est le `V1_CLEARED → V2_DETECTED = 1` de la
matrice de transition, matérialisé.

## 5. Ensembles et égalités (§ 9, § 12)

```
PII_REVIEW_BUNDLES=149          PII_REVIEW_INDEX_CONTENTS=149
MISSING_BUNDLES=0               EXTRA_BUNDLES=0
DUPLICATE_CONTENT_SHA=0

V2_PII_DETECTED_SHA_SET   = 45afb75aec3bd0f07a6f46aeafec367bf41617eb51739e90359ff3a43ecde389
PII_REVIEW_INDEX_SHA_SET  = 45afb75aec3bd0f07a6f46aeafec367bf41617eb51739e90359ff3a43ecde389
PII_REVIEW_BUNDLE_SHA_SET = 45afb75aec3bd0f07a6f46aeafec367bf41617eb51739e90359ff3a43ecde389
SET_EQUALITY=true

BUNDLE_TEXT_DIVERGENCES=0
PII_TEXT_DIVERGENCES=0
CHUNKING_TEXT_DIVERGENCES=0
```

`CHUNKING_TEXT_DIVERGENCES=0` s'appuie sur le rejeu du run V2 : extraction et
découpage rejoués sur les 2473 documents ont redonné à la fois la même
empreinte de texte canonique et les mêmes identités de chunk
(`CANONICAL_TEXT_MISMATCH=0`, `CHUNK_SET_MISMATCH=0`). Le texte qui redonne les
mêmes chunks est celui dont l'empreinte a été soumise au scanner.

Vérificateur de paquets : `{"intact": true, "ecarts": []}`.

## 6. Sécurité (§ 13)

```
RAW_PII_IN_GIT=0        RAW_PII_IN_INDEX=0        RAW_PII_IN_PUBLIC_LOGS=0
BUNDLE_FILE_MODES=[0o600]
OUTPUT_ROOT_INSIDE_REPOSITORY=false
```

L'index versionné ne porte que des empreintes, des classes, des comptes, des
pages et la provenance d'extraction — jamais `match_text` ni `context`.

Le miroir adressé par contenu de la campagne V2 est construit en **copies
indépendantes** : le précédent miroir, fait par liens physiques, rendait le
corpus scellé mutable par une seconde voie et avait fait refuser la campagne.

## 7. Protocole inchangé (§ 14)

L'index reste un `NEXUS-PII-REVIEW-INDEX-V1` avec ses clés existantes
(`bundles`, `counts.scanned`, `counts.bundles`, `raw_pii_in_output`,
`index_sha256_excluded`). Un premier jet les avait renommées : le vérificateur
et la projection de release auraient cessé de le lire, sous un numéro de
protocole inchangé.

Les décisions passeront par `NEXUS-PII-REVIEW-DECISIONS-V1`, sans protocole
nouveau.

## 8. Les 9 non évaluables n'entrent pas dans cette revue (§ 11)

`PII_DETECTED=149` et `PII_NOT_ASSESSABLE=9` sont deux populations distinctes.
Une décision humaine PII ne peut pas transformer une absence de mesure en
absence de PII. Les 9 portent un blocage technique, consigné dans
`docs/reports/evidence-index/not_assessable_remediation_v2_20260907.json` :

```
disposition   = GOVERNED_NOT_SERVABLE
blocker_codes = ["PII_NOT_ASSESSABLE", "SOURCE_EXTRACTION_INCOMPLETE"]
chunks=0  embeddings=0  servable=false
remediation_status = PENDING_ALTERNATE_SOURCE_LOOKUP
```

La recherche d'une source alternative gouvernée (§ 3) exige un accès Drive que
cette session n'a pas : le registre porte les `drive_file_id` nécessaires, la
remédiation reste ouverte et ne bloque pas le reste du pipeline.

## 9. Comptabilité du plan de données (§ 18)

```
DRIVE_DISCOVERED=2580     CONTROL_PLANE=50
DATA_PLANE_TOTAL=2530     PDF=2473     NON_PDF=57
NON_PDF_ACCOUNTED=57      NON_PDF_UNACCOUNTED=0
DATA_PLANE_ACCOUNTED=2530 DRIVE_UNACCOUNTED=0
```

Dispositions non-PDF : 37 `INTERACTIVE_RESOURCE_SERVABLE`,
19 `DIAGNOSTIC_QUESTION_BANK_NON_INDEXABLE`,
1 `OPERATIONAL_DOCUMENTATION_NON_INDEXABLE`.

## 10. Demande de revue humaine

```
HUMAN_ACTION_REQUIRED
REASON=NEW_PII_REVIEW

REVIEW_CONTENTS=149
REVIEW_FINDINGS=479
REVIEW_INDEX_SHA256=30dee679baee95b2db39306515ecfaec1e566e6a055776d812df1960de687758
REVIEW_BUNDLE_SET_SHA256=4798f2ed0fc2e96aa944847d77406909c9b73764e08ae0337d76c2152d2aae6b
REVIEW_CONTENT_SET_SHA256=45afb75aec3bd0f07a6f46aeafec367bf41617eb51739e90359ff3a43ecde389
PROCESSING_RUN_ID=8bbaa039cfd4e99b69a6f4a72fe23f5fe9bb07e6f242f564380fd35a91e68611
EXTRACTION_POLICY_ID=NEXUS-DRIVE-PDF-EXTRACTION-V2
```

Aucune décision PII antérieure n'est étendue à ces empreintes : les 149 sont
des SHA nouveaux pour la revue, et 148 d'entre eux seulement coïncident avec
des contenus déjà détectés sous V1 — sous un **texte différent** pour ceux qui
ont changé.
