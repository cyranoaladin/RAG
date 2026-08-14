# LOT — Index de preuves et registre de disposition terminale (PII / droits / actualité)

## Verdict

Un index de preuves et un registre de disposition terminale ont été
construits pour les **2582 contenus uniques** (`content_sha256`) du corpus
scellé local (`~/Téléchargements/NEXUS_RAG_GDRIVE_READY`,
`SEALED_MANIFEST_SHA256=d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e`).
**Couverture de disposition terminale : 100 %** au niveau contenu ET au
niveau placement — chaque ligne porte une valeur `FINAL_DISPOSITION`
décidée, jamais un placeholder.

**Ce rapport corrige une première version de ce lot**, qui contenait deux
défauts réels identifiés par relecture humaine :

1. **Confusion entrée-de-manifeste / contenu unique.** La version précédente
   affichait `total_unique_content_sha256=2583` — en réalité une ligne
   parasite s'était glissée dans le calcul : le fichier manifeste
   lui-même (`00_ADMIN/SHA256SUMS.txt`) avait été haché et traité comme
   un « contenu » de plus, alors que le manifeste ne se liste jamais
   lui-même (0 occurrence de `SHA256SUMS` dans ses propres lignes,
   vérifié). Une fois cette ligne retirée : **2582 contenus uniques**
   parmi les 2583 entrées de manifeste, avec exactement 1 groupe de
   doublon (un même contenu à deux emplacements). Deux registres
   distincts remplacent l'unique fichier conflaté précédent — voir
   §Artefacts.
2. **Conclusion PII incomplète — une campagne H2F antérieure avait été
   ignorée.** La version précédente concluait `INGEST_ELIGIBLE=0` parce
   que les 64 contenus de la zone `10_ACTUEL_CONFIRME/` (la seule qui
   route vers `INGEST`) n'avaient aucune preuve PII dans le scan
   `h2b_exhaustive_pii_scan_20260813.jsonl` (2411 entrées). Cette
   preuve H2F existe réellement — voir §Correction PII ci-dessous —,
   et sa découverte change la conclusion : **63 contenus sont
   aujourd'hui réellement éligibles à `INGEST`** selon les quatre portes
   de `corpus_zone_routing.yml` (droits, PII, actualité, format), et 1
   est en `QUARANTINE` (PII détecté : adresse postale).

Aucune ingestion, aucune écriture pgvector, aucune mutation live n'a été
effectuée dans ce lot — travail de reconciliation pure, lecture seule
(y compris le nouveau scan/relecture d'evidence : lecture seule des octets
scellés).

## Correction 1 — deux registres, jamais un seul conflaté

- **CONTENT_LEDGER** (`content_ledger_20260814.jsonl`, 2582 lignes) — une
  ligne par `content_sha256` unique : `PII`, `CURRENTNESS`, `RIGHTS`,
  `EXTRACTABILITY`, `ROUTING_BASELINE`, `FINAL_DISPOSITION`,
  `REASON_CODES`, `EVIDENCE_SOURCES`, `PLACEMENT_COUNT`,
  `PLACEMENT_PATHS`.
- **PLACEMENT_LEDGER** (`placement_ledger_20260814.jsonl`, 2583 lignes) —
  une ligne par entrée de manifeste (= par emplacement physique) :
  `content_sha256`, `path`, `ROUTING_ZONE` (calculé directement depuis
  `corpus_zone_routing.yml`, retranscription complète et vérifiée du
  moteur de règles préfixe-de-chemin / sous-zone, premier match gagne),
  `CONTENT_FINAL_DISPOSITION` (référence vers la disposition du contenu).
- Le seul cas de placements divergents (`education-a-la-vie-affective-
  et-relationnelle...pdf`, présent sous `00_INDEX_PROVENANCE/` ET sous
  `01_EDUSCOL_OFFICIEL/COLLEGE/CYCLE_4_TRANSVERSAL/`) apparaît deux fois
  dans `PLACEMENT_LEDGER` (chacune avec sa propre `ROUTING_ZONE`), mais
  une seule fois dans `CONTENT_LEDGER`, résolu fail-closed à
  `REVIEW_REQUIRED` au niveau contenu — jamais l'une des deux zones
  choisie arbitrairement.

```
PHYSICAL_FILES=2584
MANIFEST_ENTRIES=2583
UNIQUE_CONTENT_SHA256=2582
DUPLICATE_CONTENT_GROUPS=1
PLACEMENT_ROWS=2583
```

## Correction 2 — la campagne PII H2F retrouvée par contenu, pas par nom

Recherche exhaustive dans `~/Documents/NEXUS_RAG_H2_EVIDENCE/` (81
entrées + les deux sous-répertoires `h2f_4d09148976e7/` et
`h2f_b4f8870d4b9e/`, listés intégralement). Le fichier
`h2f_4d09148976e7/pii_evidence_exit_validation.txt` cite
`PII_EVIDENCE_SHA256=76e6ba3cd5b1c116c8647b611eb3fdeb2aba6b8c7fdfbad9e71048354956f311`
avec `PII_SCAN_REQUIRED=64` / `PII_SCANNED=64` / `PII_CLEARED=63` /
`PII_QUARANTINED=1` — un compte qui coïncide exactement avec les 64
contenus de la zone `INGEST`. Un `sha256sum` de **tous** les fichiers du
trove a permis de retrouver le fichier exact portant ce digest :
`h2b_pii_evidence_20260808.json` (pas dans les sous-répertoires — à la
racine du trove, daté du 2026-08-08, jamais ouvert par la version
précédente de ce lot).

Vérifications avant usage (jamais un digest ni un nom de fichier pris au
mot) :

```
$ sha256sum h2b_pii_evidence_20260808.json
76e6ba3cd5b1c116c8647b611eb3fdeb2aba6b8c7fdfbad9e71048354956f311  ✓ correspond

corpus_manifest_sha256 dans le fichier = d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e  ✓ correspond au manifeste scellé canonique
evidence_kind = "REAL_CORPUS_PII_SCAN"
scan_scope = "INITIAL_PRODUCTION_ELIGIBLE_PDFS"
required_pdf_path_count = 64
unique_pdf_content = 64
scanner_version = "pii_scanner_h2b_v2"  (remote_pii_scan.py, scan_remote_corpus)

set(64 content_sha256 du fichier) == set(64 content_sha256 de la zone INGEST)  → True (égalité stricte)
set(64) ∩ set(2411 du scan du 2026-08-13)  → ∅ (0 recouvrement — couverture réellement complémentaire, jamais un doublon de snapshot)
```

Statuts des 64 (tous avec `error_code: null`, donc extraction réussie
pour les 64 — `pages_scanned`/`characters_scanned` renseignés) :

```
CLEARED           : 63
QUARANTINED_PII   : 1   (signal postal_address, page 1)
```

**Union PII (2411-scan + H2F-64), recalculée depuis les fichiers réels,
jamais recopiée de mémoire** :

```
PII_PDF_UNION_COVERAGE=2475
PII_PDF_UNION_DUPLICATES=0
CLEARED                          : 2286
QUARANTINED_PII                  : 146
REVIEW_REQUIRED_EXTRACTION_FAILED: 43
```

(L'opérateur humain se souvenait d'une partition `2284 CLEARED + 146
QUARANTINED + 45 REVIEW_REQUIRED = 2475` — le total et `QUARANTINED`
coïncident exactement, confirmant qu'il s'agit bien de la même preuve
retrouvée ; la répartition exacte CLEARED/REVIEW_REQUIRED calculée ici
[2286/43] diffère légèrement du souvenir [2284/45] — les totaux réels
des fichiers font foi, jamais un compte reconstitué de mémoire.)

## Correction 2bis — les 107 contenus non-PDF

`2582 - 2475 = 107` contenus sans preuve PII dans l'union — tous
non-PDF, vérifié (`.ggb` ×37, `.tsv` ×29, `.yaml` ×18, `.json` ×9,
`.md`/`.txt` ×4 chacun, `.zip` ×3, `.sha256` ×2, `.csv` ×1). Aucun n'est
dans la zone `INGEST` (routing : `EXCLUDE` ×51 placements, `REVIEW_
REQUIRED` ×19, `UNSUPPORTED` ×37).

Le contrat/scanner réel (`remote_pii_scan.py::scan_remote_corpus`) filtre
strictement `object_path.lower().endswith(".pdf")` **avant** toute
tentative de scan — le non-PDF n'entre jamais dans son périmètre. La
politique committée (`pii_gate_policy.yml`, section `full_content_scan`)
est elle-même explicitement scopée PDF (`pdf_text_extraction`,
`estimated_scope.total_pdfs`). Aucun état `NOT_APPLICABLE` n'existe dans
ce contrat — en inventer un aurait violé l'instruction explicite de ne
jamais introduire de vocabulaire que le contrat réel ne définit pas.
Ces 107 lignes portent donc `PII=OUT_OF_SCANNER_SCOPE_NON_PDF`,
accompagné du code `PII_GATE_PDF_ONLY_BY_POLICY_NON_PDF_CONTENT` — une
frontière de politique réelle et documentée, jamais un angle mort
silencieux. Impact sur l'éligibilité : nul (aucun des 107 ne route vers
`INGEST`).

## Registre — répartition finale corrigée (2582 contenus uniques)

```
REVIEW_REQUIRED : 2408
UNSUPPORTED     :   37
EXCLUDE         :   53
ARCHIVE_ONLY    :   19
QUARANTINE      :    2   (1 conflit de statut zone + 1 PII détecté dans la zone INGEST)
INGEST          :   63
─────────────────────────
TOTAL           : 2582
```

`RELEASE_ELIGIBLE_ARTIFACTS=63` — au sens des quatre portes déjà
codifiées dans `corpus_zone_routing.yml` (droits, PII, actualité,
format) uniquement. **Ceci ne constitue pas une autorisation de
publication** : la chaîne d'autorisation/attribution complète (ADR-0032,
liaison de revue, portée PR #98 — déjà jugée insuffisante et non
étendue par cette mission) reste un layer séparé, non recalculé ici.

Le zéro précédent (`INGEST_ELIGIBLE=0`) provenait uniquement de l'omission
de la preuve H2F ci-dessus — abandonné, comme demandé, puisqu'il ne
reflétait pas les faits une fois cette preuve retrouvée.

## Ce qui n'a pas changé depuis la version précédente

- Les valeurs `RIGHTS`/`CURRENTNESS` pour les ~2518 contenus hors zone
  `INGEST` (déjà calculées depuis `rights_evidence_registry.yml` et les
  fichiers `*_currentness_evidence*.yml`, sources committées et revues)
  sont réutilisées telles quelles — ces sources et cette logique
  n'étaient pas mises en cause par les deux défauts corrigés ici.
- Le conflit `currentness` documenté entre `wave0_currentness_evidence_v1`
  et `_v2` (2 contenus, valeurs `effective_currentness` identiques,
  provenance différente) reste flagué, non arbitré par « le plus
  récent ».
- `h2b_coverage_report.py` reste non exécutable de bout en bout contre le
  corpus réel (deux défauts déjà documentés dans la version précédente de
  ce rapport : chemins de configuration inexistants dans
  `_produce-h2-evidence.yml`, schéma incompatible dans
  `corpus_catalog_compiler.py`) — non corrigés par ce lot (hors
  périmètre ; lots séparés).

## Artefacts produits

- `docs/reports/evidence-index/evidence_index_20260814.json` — 11 sources
  de preuve distinctes (10 précédentes + `h2b_pii_evidence_20260808.json`
  nouvellement localisé et vérifié).
- `docs/reports/evidence-index/content_ledger_20260814.jsonl` — 2582
  lignes, une par `content_sha256` unique.
- `docs/reports/evidence-index/placement_ledger_20260814.jsonl` — 2583
  lignes, une par entrée de manifeste/emplacement physique.
- `docs/reports/evidence-index/summary_20260814.json` — compteurs bruts
  recalculés.
- **Supprimé** : `terminal_disposition_ledger_20260814.jsonl` (l'ancien
  fichier unique conflaté — entièrement remplacé par les deux registres
  ci-dessus, jamais conservé en parallèle pour éviter toute ambiguïté sur
  la source de vérité).

Aucun de ces fichiers n'est signé ni ne constitue une autorisation —
lecture seule, reconciliation de preuves existantes plus une preuve
retrouvée, jamais une décision de gouvernance nouvelle.

## Booléens finaux

```
PHYSICAL_FILES=2584
MANIFEST_ENTRIES=2583
UNIQUE_CONTENT_SHA256=2582
DUPLICATE_CONTENT_GROUPS=1
PLACEMENT_ROWS=2583
PII_PDF_UNION_COVERAGE=2475
PII_PDF_UNION_DUPLICATES=0
CONTENT_TERMINAL_DISPOSITION_COVERAGE=100.0%
PLACEMENT_TERMINAL_DISPOSITION_COVERAGE=100.0%
UNACCOUNTED_CONTENT=0
UNACCOUNTED_PLACEMENTS=0
RELEASE_ELIGIBLE_ARTIFACTS=63
CURRENT_LEDGER_PRELIMINARY=false
H2_COVERAGE_REPORT_PRODUCIBLE_END_TO_END=false
FULL_CORPUS_AUTHORITY_FILE_EXISTS=false
GOOGLE_DRIVE_ELIGIBLE_CONTENT_INGESTED=false
PRODUCTION_VECTOR_INDEX_COMPLETE=false
GO_LIVE_READY=false
LIVE_MUTATIONS_ALLOWED=false
```
