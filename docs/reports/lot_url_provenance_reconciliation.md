# Réconciliation de provenance d'URL — 8 autorités Drive

> `content_sha256`, URL institutionnelles publiques, comptes. Aucune matière.

## 1. Réception des autorités

```
PROVENANCE_FILES_EXPECTED=8   PROVENANCE_FILES_RECEIVED=8
PROVENANCE_FILES_HASH_MISMATCH=0
```

Les huit fichiers ont été confrontés à leur taille **et** à leur empreinte
annoncées. Le bundle porte en outre son propre `SHA256SUMS.txt` et un
`manifest.json` cohérents. Copie scellée hors dépôt, `0700`/`0600`.

## 2. Le CSV n'est pas séparé par des virgules

`catalogue-complet.csv` est séparé par `;` et porte une marque d'ordre d'octets.
Croire l'extension aurait produit une seule colonne portant toute la ligne, puis
un refus « aucune colonne d'URL » parfaitement trompeur. L'importeur déduit le
séparateur de l'extension puis le **confirme sur l'en-tête**, et lit en
`utf-8-sig`.

```
CATALOGUE_CSV_ROWS=2956   CATALOGUE_TSV_ROWS=2956
CATALOGUE_CSV_TSV_SEMANTIC_DIFF=0
```

L'égalité est **sémantique** : enregistrements normalisés et comparés, pas
seulement comptés.

## 3. Faits mesurés — tous reproduits

```
CATALOGUE_ROWS=2956                      CATALOGUE_DISTINCT_CONTENT_SHA=2451
CATALOGUE_ROWS_WITH_URL=2956             CATALOGUE_DISTINCT_URLS=111
CATALOGUE_DISTINCT_CONTENT_URL_PAIRS=2542
CONTENTS_WITH_MULTIPLE_URLS=54

CORPUS_SHA_ROWS=2603                     CORPUS_SHA_DISTINCT=2603
CATALOGUE_SHA_IN_CORPUS=2451             CATALOGUE_SHA_NOT_IN_CORPUS=0
CORPUS_SHA_NOT_IN_CATALOGUE=152          (corpus technique)

statut : a-verifier=2585  actuel=225  transition-ou-actuel=101  archive=45
CONTENTS_WITH_MULTIPLE_CATALOGUE_STATUSES=21
```

## 4. Égalité d'ensembles avec le handoff — prouvée, pas déduite

```
HANDOFF_INSTITUTIONAL=2451               CATALOGUE_DISTINCT=2451
MISSING_FROM_CATALOGUE=0                 EXTRA_IN_CATALOGUE=0
HANDOFF_INSTITUTIONAL_SHA_SET_EQUAL=true

HANDOFF_INSTITUTIONAL_SET_SHA256=baa2a8501ccbf94b0d46cbe5cc4b843c44fabeb95b91543980fb14b81f9c030a
CATALOGUE_DISTINCT_SET_SHA256   =baa2a8501ccbf94b0d46cbe5cc4b843c44fabeb95b91543980fb14b81f9c030a
```

La **même empreinte d'ensemble** des deux côtés : ce n'est pas une coïncidence
de comptes.

## 5. Résultat de la réconciliation

```
URL_RELATIONS_TOTAL=2530
URL_PROVENANCE_FOUND=2451   URL_NO_EVIDENCE=79
URL_AMBIGUOUS=0             URL_NOT_APPLICABLE=0        URL_ERRORS=0
URL_RELATIONS_ACCOUNTED=2530                            URL_UNACCOUNTED=0

INSTITUTIONAL_CONTENTS=2451
INSTITUTIONAL_PROVENANCE_FOUND=2451   INSTITUTIONAL_NO_EVIDENCE=0
INSTITUTIONAL_AMBIGUOUS=0             INSTITUTIONAL_ERRORS=0

FULL_DISTINCT_URLS=111                FULL_ARTIFACT_URL_RELATIONS=2542
NEEDS_URL_EVIDENCE_BUT_NON_INDEXABLE=20   TRUE_NOT_APPLICABLE=0
MULTI_STATUS_CONTENT_SHA=21

URL_PROVENANCE_ACCOUNTING=PASS
URL_CURRENTNESS_VERIFICATION=NOT_STARTED
```

Les 79 sans preuve sont exactement le hors-catalogue : 38 diagnostics,
37 ressources interactives, 3 compléments, 1 documentation d'exploitation.

## 6. Un critère d'ambiguïté que j'ai dû corriger

La première passe rendait `URL_AMBIGUOUS=4`. Ces quatre n'étaient pas
ambigus : trois documents de technologie référencés à la fois par
`eduscol.education.gouv.fr/5745` et par `sti.eduscol.education.fr`, et un
document d'histoire des arts référencé par la page de programme **et** par une
page thématique. Quatre provenances doubles parfaitement légitimes.

Mon critère — « même scope + même `objet_source`, deux URL » — était faux :
`objet_source` est dérivé de l'empreinte, donc « même scope, même objet » ne
veut dire que « même contenu ». La règle revenait à interdire la
multi-provenance que la consigne venait d'admettre.

Le critère corrigé nomme une preuve **inattribuable** : une jointure par
chemin qui ramène des lignes portant une **autre** empreinte. Le chemin a alors
désigné un autre document, et rien ne dit laquelle de ces lignes parle du
nôtre. Sur les autorités réelles, ce cas n'existe pas — d'où `URL_AMBIGUOUS=0`.

## 7. Un contenu, 1..N provenances

Le modèle « une URL par artefact » est abandonné. Chaque relation porte ses
preuves, chacune avec :

```
row_content_sha256   url_source   scope   objet_source
catalogue_status     evidence_file   evidence_row
```

54 contenus portent plusieurs URL. Deux dénominateurs, jamais confondus :
**111 URL distinctes** et **2542 relations contenu×URL**. Une page
institutionnelle partagée par cent documents est une URL et cent relations.

## 8. Les statuts ne sont pas écrasés

`drive_slice.STATUTS_SOURCE` porte le **vocabulaire** canonique. Aucune
configuration versionnée ne définit la **sémantique de service** par statut.

```
a-verifier            2585  → A_VERIFIER             serving=UNDEFINED_PENDING_AUTHORITY
actuel                 225  → ACTUEL_CONFIRME        serving=UNDEFINED_PENDING_AUTHORITY
transition-ou-actuel   101  → TRANSITION_OU_ACTUEL   serving=UNDEFINED_PENDING_AUTHORITY
archive                 45  → ARCHIVE_CATALOGUE      serving=UNDEFINED_PENDING_AUTHORITY
UNMAPPED_RAW_STATUSES=[]
```

`a-verifier` n'est pas rendu servable : « à vérifier » est une absence de
vérification, pas une vérification positive. `transition-ou-actuel` n'est pas
tranché : la source elle-même ne l'a pas fait, et le faire ici serait inventer
le mapping.

Les 21 contenus multi-statuts sont conservés dans un ledger sanitisé
(`content_sha256`, `status_set[]`, `source_relation_ids[]`,
`url_evidence_ids[]`). Un même contenu appartenant à plusieurs relations de
provenance peut légitimement porter plusieurs statuts ; le service se décide au
niveau de la **relation**, jamais par précédence sur le contenu.

## 9. `NON_INDEXABLE` n'est plus `NOT_APPLICABLE`

Le raccourci de la passe à vide sortait 20 objets de la comptabilité sans
qu'aucune autorité métier l'ait décidé. Un objet non indexable peut exiger
provenance, droits et actualité.

```
NEEDS_URL_EVIDENCE_BUT_NON_INDEXABLE=20   TRUE_NOT_APPLICABLE=0
```

Aucun `NOT_APPLICABLE` n'est prononcé faute d'autorité métier qui déclare une
classe sans URL pertinente.

## 10. Provenance ≠ actualité

Le catalogue prouve qu'un SHA **était** lié à une URL. Il ne prouve pas que
cette URL est actuelle en septembre 2026. Aucune disposition ne vaut
`VERIFIED_CURRENT`, et la constante n'existe pas dans le code — une épreuve le
vérifie.

La campagne d'actualité viendra ensuite, et sur **111 URL distinctes**, pas sur
2542 relations : des centaines de documents partagent la même page.

## 11. Preuves

| Artefact | sha256 |
|---|---|
| `handoff/url_provenance_reconciliation.json` | `9b6fd4c65e2a84b501c15c2ec139b9e986293e73cc8293dd0f49b1c697baf892` |
| `handoff/catalogue_status_normalisation.json` | `2633b402453194dee82bb946a33d1685efa8c1526afb8ee2df9445692eb3493c` |
| `handoff/multi_status_content_ledger.json` | `53ed35c591f274818027532423f3f53449d3acdf80527db8a39e0f6701e91593` |
