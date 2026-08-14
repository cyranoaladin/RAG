# LOT — Index de preuves et registre de disposition terminale (PII / droits / actualité)

## Verdict

Un index de preuves et un registre de disposition terminale ont été
construits pour les **2583 contenus uniques** (`content_sha256`) du corpus
scellé local (`~/Téléchargements/NEXUS_RAG_GDRIVE_READY`, 2584 fichiers
physiques, `SEALED_MANIFEST_SHA256=d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e`).
**Couverture de disposition terminale : 100 %** — chaque ligne porte une
valeur `FINAL_DISPOSITION` décidée, jamais un placeholder.

**Constat le plus important : zéro objet n'est aujourd'hui éligible à
`INGEST`.** Les 64 objets de la seule zone qui y mène
(`01_EDUSCOL_OFFICIEL/.../10_ACTUEL_CONFIRME/`) ont tous les 64 été
recalés en `REVIEW_REQUIRED`, non pour une raison de contenu mais parce
qu'**aucun des 64 ne possède la moindre preuve PII** dans le scan le plus
récent et le plus large trouvé (`h2b_exhaustive_pii_scan_20260813.jsonl`,
2411/2583 contenus couverts). Le gate PII (`pii_gate_policy.yml`,
`scan_incomplete → BLOCK`) est bloquant par construction : en son absence,
aucun objet ne peut légitimement passer en `INGEST`, quel que soit son
contenu réel.

Aucune ingestion, aucune écriture pgvector, aucune mutation live n'a été
effectuée dans ce lot — travail de reconciliation pure, lecture seule.

## Méthodologie

1. **Identité du corpus** : le manifeste scellé réel existe toujours —
   contrairement à une hypothèse antérieure de cette mission ("gone from
   `/tmp`"), seule une COPIE dans `/tmp` a disparu ; l'original vit dans
   le corpus lui-même à `00_ADMIN/SHA256SUMS.txt` (2583 lignes,
   `sha256sum` de ce fichier = `d7e5caa5...`, confirmé). Utilisé
   directement comme source d'identité.
2. **Disposition de base** : les règles de
   `services/rag-pedago/configs/corpus_zone_routing.yml`
   (`corpus_zone_routing_h2b_v1`, source committée, revue, scope pinné
   sur le manifeste scellé) ont été retranscrites et appliquées aux 2584
   chemins physiques réels. Vérification croisée : les totaux obtenus
   (`INGEST=64, REVIEW_REQUIRED=2408, QUARANTINE=1, ARCHIVE_ONLY=19,
   EXCLUDE=55, UNSUPPORTED=37`, somme=2584) reproduisent quasi exactement
   les `expected_totals` déclarés par le fichier lui-même
   (`REVIEW_REQUIRED=2395` attendu vs `2408` obtenu — écart de 13,
   cohérent avec le fait que le fichier documente un total légèrement
   différent pour `EXCLUDE`/`REVIEW_REQUIRED` dans son bloc
   `expected_totals` que dans ses règles `sub_zone_routing` détaillées ;
   les règles détaillées, plus précises, ont été retenues comme source de
   vérité plutôt que le bloc résumé).
3. **Droits** : `rights_evidence_registry.yml` (`_v3`, committé, scope
   pinné) — clearance au niveau zone (5 zones).
4. **PII** : `h2b_exhaustive_pii_scan_20260813.jsonl` (trove
   `~/Documents/NEXUS_RAG_H2_EVIDENCE/`), le scan le plus récent et le
   plus large trouvé — 2411/2583 contenus couverts, statuts `CLEARED`
   (2223), `QUARANTINED_PII` (145), `REVIEW_REQUIRED_EXTRACTION_FAILED`
   (43).
5. **Actualité par contenu** : `wave0_currentness_evidence.yml`/`_v2.yml`
   (2 contenus chacun) et `multilevel_currentness_evidence.yml` (150
   contenus) — utilisés comme surcharge par `content_sha256` là où ils
   couvrent un objet, au-dessus de l'heuristique de zone.
6. **Aucun choix « le plus récent gagne »** : deux surcharges d'actualité
   ont été trouvées en désaccord de source (wave0 v1 vs v2, 2 contenus) —
   documentées, pas arbitrées silencieusement (voir `EVIDENCE_CONFLICT`
   ci-dessous ; dans ce cas précis les deux sources s'accordaient déjà sur
   la valeur `effective_currentness=actuel`, seule leur provenance
   diffère, donc aucun contenu n'a été mal classé par ce conflit — mais il
   est loggé comme tel par principe).
7. **Tentative de production réelle via `h2b_coverage_report.py`** —
   voir §Blocages ci-dessous : non exécutable de bout en bout.

## Registre — répartition finale (2583 lignes)

```
REVIEW_REQUIRED : 2472
UNSUPPORTED     :   37
EXCLUDE         :   54
ARCHIVE_ONLY    :   19
QUARANTINE      :    1
INGEST          :    0
─────────────────────────
TOTAL           : 2583
```

- **EVIDENCE_CONFLICT (multi-placement divergent)** : 1 — un même contenu
  (`education-a-la-vie-affective-et-relationnelle...pdf`) existe à deux
  chemins physiques dont les règles de zone divergent (`EXCLUDE` sous
  `00_INDEX_PROVENANCE/`, `REVIEW_REQUIRED` sous
  `01_EDUSCOL_OFFICIEL/.../CYCLE_4_TRANSVERSAL/`). Résolu fail-closed vers
  `REVIEW_REQUIRED`, jamais choisi arbitrairement.
- **TO_VERIFY (zone INGEST sans preuve PII)** : 64 — voir constat
  principal ci-dessus.
- **Écart de couverture PII** : 172 contenus uniques sur 2583 (6,6 %)
  n'ont aucune preuve PII dans le trove entier (au-delà des 64 déjà
  comptés ci-dessus, car cet écart touche aussi des contenus déjà
  `REVIEW_REQUIRED`/`ARCHIVE_ONLY` pour d'autres raisons).

## Blocages — `h2b_coverage_report.py` non exécutable de bout en bout

Deux défauts réels, indépendants, empêchent une exécution complète du
véritable producteur de preuve H2 contre le corpus réel :

1. **`.github/workflows/_produce-h2-evidence.yml` référence des fichiers
   qui n'ont jamais existé** dans ce dépôt :
   `services/rag-pedago/configs/rights_registry.yml` (réel :
   `rights_evidence_registry.yml`), `pii_policy.yml` (réel :
   `pii_gate_policy.yml`), `golden_controls.yml` (réel :
   `golden_corpus_h2b.yml`), ainsi que `governance/authorizations/`,
   `governance/review-bindings/`, `governance/revocations/`,
   `governance/corpus-campaigns/` (aucun de ces répertoires n'existe ;
   seul `governance/trust-anchors/` existe). `git log` confirme que le
   workflow et les fichiers réels (différemment nommés) ont été introduits
   dans le **même commit** (`2182339`, PR #95) — jamais un renommage
   after-the-fact, le workflow est cassé depuis son introduction.
   `gh run list --workflow="_produce-h2-evidence.yml"` : **0 exécution,
   jamais**. Non corrigé dans ce lot (lecture seule, hors périmètre —
   corriger exigerait de concevoir l'appareil de campagne/autorisation
   manquant, une décision de gouvernance distincte).
2. **`corpus_catalog_compiler.py` attend un schéma de placement
   incompatible avec le vrai `00_ADMIN/eduscol_affectations.tsv` du
   corpus scellé.** Colonnes réellement présentes : `sha256,
   canonical_destination, source_relative, level, subject, doc_type,
   year, is_primary, size`. Colonnes exigées par
   `_load_eduscol_placements()` : `annee, chemin_par_niveau,
   chemin_par_scope, chemin_technique_existant, famille,
   matiere_ou_rubrique, niveau, objet_source, scope, statut, titre,
   type_document, url_source`. Exécution réelle tentée, échec confirmé :

   ```
   $ python3 -m rag_pedago.imports.corpus_catalog_compiler \
       --sealed-manifest .../00_ADMIN/SHA256SUMS.txt \
       --placement-catalog .../00_ADMIN/eduscol_affectations.tsv \
       --config configs/corpus_zone_routing.yml \
       --output /tmp/catalog.json
   ValueError: placement catalog missing required columns: annee,
   chemin_par_niveau, chemin_par_scope, chemin_technique_existant,
   famille, matiere_ou_rubrique, niveau, objet_source, scope, statut,
   titre, type_document, url_source
   ```

   Sans catalogue compilé, `h2b_coverage_report.py --catalog` ne peut pas
   être fourni avec un fichier réel issu du corpus réel.
3. Même en contournant (2), aucun fichier d'autorité (`--authority`)
   couvrant l'ensemble des 2582/2583 contenus n'existe — seules des
   autorisations historiques et partielles (PR #98) existent, déjà
   explicitement jugées insuffisantes par cette mission. `--authority`
   est optionnel dans la CLI, donc un rapport partiel (routing/rights/PII
   seuls, sans `h2_coverage_gate_pass`) resterait possible une fois (2)
   résolu — non tenté faute de catalogue valide.

## Limites connues de ce registre

- Les 55 fichiers restants du trove `~/Documents/NEXUS_RAG_H2_EVIDENCE/`
  n'ont pas été ouverts individuellement (voir
  `docs/reports/evidence-index/evidence_index_20260814.json`, dernière
  entrée) — classés par nom/taille/date comme scans PII antérieurs
  superseded ou snapshots CI par commit, jamais comme preuve de
  disposition de corpus. Limite explicite, pas un angle mort silencieux.
- `rights_evidence_registry.yml` documente un mécanisme d'exception
  par document pour `01_EDUSCOL_OFFICIEL/`
  (`document_specific_exception_status: THIRD_PARTY_REVIEW_REQUIRED`)
  dont aucune liste concrète par `content_sha256` n'a été trouvée dans le
  trove — non modélisé par ligne dans ce registre, flag global uniquement.
- `pii_gate_policy.yml` (config committée) affirme encore
  `scan_complete: false`, contredit par l'existence réelle du scan du
  2026-08-13 — la config committée n'a pas été mise à jour pour refléter
  ce scan réel ; ce lot ne corrige pas la config (hors périmètre), le
  signale seulement.

## Artefacts produits

- `docs/reports/evidence-index/evidence_index_20260814.json` — index des
  10 sources de preuve distinctes consultées (producteur, version,
  date, scope, digest scellé si applicable, superseded_by, fiabilité).
- `docs/reports/evidence-index/terminal_disposition_ledger_20260814.jsonl`
  — 2583 lignes, une par `content_sha256` unique : `PII`, `CURRENTNESS`,
  `RIGHTS`, `EXTRACTABILITY`, `ROUTING_BASELINE`, `FINAL_DISPOSITION`,
  `REASON_CODES`, `EVIDENCE_SOURCES`.
- `docs/reports/evidence-index/summary_20260814.json` — compteurs bruts.

Aucun de ces trois fichiers n'est commité par ce lot (fichiers non suivis
laissés pour revue).

## Booléens finaux

```
TERMINAL_DISPOSITION_COVERAGE=100%
EVIDENCE_INDEX_BUILT=true
H2_COVERAGE_REPORT_PRODUCIBLE_END_TO_END=false
FULL_CORPUS_AUTHORITY_FILE_EXISTS=false
CORPUS_CATALOG_COMPILER_SCHEMA_COMPATIBLE_WITH_REAL_TSV=false
H2_EVIDENCE_WORKFLOW_RUNNABLE=false
PII_SCAN_COVERAGE=2411/2583 (93.4%)
PII_SCAN_COVERAGE_OF_INGEST_ZONE=0/64 (0%)
INGEST_ELIGIBLE_TODAY=0
GOOGLE_DRIVE_ELIGIBLE_CONTENT_INGESTED=false
PRODUCTION_VECTOR_INDEX_COMPLETE=false
GO_LIVE_READY=false
LIVE_MUTATIONS_ALLOWED=false
```
