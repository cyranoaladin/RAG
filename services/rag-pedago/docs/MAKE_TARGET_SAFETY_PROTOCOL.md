# Protocole de sécurité des cibles Makefile

## 1. Objectif

Classer les cibles Makefile selon leur sûreté opérationnelle afin d’éviter toute confusion entre diagnostic, gouvernance non destructive, workflows metadata-only, runtime, réseau, ingestion, backup et composants futurs non prêts.

## 2. Principes

- Une cible non classée est un risque.
- Une cible sensible ne doit pas être lancée hors lot dédié.
- Les cibles SAFE_* peuvent être utilisées pour diagnostic, tests ou revue non destructive.
- Les cibles RESTRICTED_* nécessitent une instruction explicite.
- Les cibles FUTURE_NOT_READY ne doivent pas être utilisées tant que le composant correspondant n’est pas implémenté.
- `rag-local` reste read-only.

## 3. Catégories

- SAFE_DIAGNOSTIC : diagnostics locaux sans action produit, réseau, ingestion, runtime ou nettoyage réel.
- SAFE_METADATA_ONLY : contrôles metadata-only déjà bornés par les protocoles et fixtures synthétiques.
- SAFE_CLEANUP_REVIEW : dry-run, revue et brouillon de décision cleanup sans suppression, déplacement ni archive.
- SAFE_TESTING : tests et contrôles statiques locaux sans action produit.
- RESTRICTED_METADATA_IMPORT : commandes qui écrivent ou vérifient des artefacts de ledger, manifest, gate, review ou import metadata-only et nécessitent un lot dédié.
- RESTRICTED_RUNTIME : commandes qui démarrent ou surveillent un runtime applicatif.
- RESTRICTED_NETWORK : commandes pouvant impliquer installation, scraping ou accès réseau.
- RESTRICTED_DESTRUCTIVE_OR_BACKUP : commandes qui modifient des fichiers ou créent des sauvegardes.
- FUTURE_NOT_READY : commandes liées à des composants non implémentés ou non validés.
- UNKNOWN : catégorie de quarantaine pour toute cible non classée.

## 4. Cibles autorisées par défaut

SAFE_DIAGNOSTIC :

- `doctor`
- `project-doctor`
- `make-target-safety-audit`

SAFE_METADATA_ONLY :

- `metadata-preflight`
- `pilot-template-check`
- `pilot-compile-check`
- `pilot-rehearsal`
- `real-draft-guard-check`
- `human-unlock-check`
- `real-draft-unlock-gate-check`
- `pilot-corpus-scope-audit`
- `retrieval-metadata-eval-audit`
- `pedago-interface-contract-audit`
- `source-admission-policy-audit`
- `human-source-review-audit`
- `controlled-readiness-audit`
- `transition-authorization-audit`
- `metadata-governance-chain-audit`
- `metadata-review-handoff-audit`

SAFE_CLEANUP_REVIEW :

- `cleanup-dry-run`
- `cleanup-review`
- `cleanup-decision-draft`

SAFE_TESTING :

- `test`
- `lint`
- `typecheck`

## 5. Cibles interdites hors lot dédié

RESTRICTED_METADATA_IMPORT :

- `ledger-init`
- `ledger-doctor`
- `manifest-import-fixture`
- `manifest-dir-dry-run`
- `manifest-dir-import-fixture`
- `manifest-readiness`
- `manifest-coverage`
- `manifest-gate`
- `manifest-readiness-clean`
- `manifest-coverage-clean`
- `manifest-gate-clean`
- `manifest-controlled-import-clean`
- `manifest-controlled-import-problem`
- `review-package-clean-audited`

RESTRICTED_RUNTIME :

- `watch`
- `api`

RESTRICTED_NETWORK :

- `install`
- `scrape-official`

RESTRICTED_DESTRUCTIVE_OR_BACKUP :

- `format`
- `backup`

FUTURE_NOT_READY :

- `init`
- `ingest`
- `ingest-official`
- `ingest-internal`
- `verify`
- `eval-retrieval`

## 6. Conditions avant d’utiliser une cible restreinte

- lot dédié ;
- intention explicite ;
- validations avant/après ;
- pas de document réel sauf validation ;
- pas de réseau sauf validation ;
- pas de Qdrant sauf validation ;
- rollback documenté ;
- revue humaine.

## 7. Conditions avant de déclarer une cible SAFE

- tests ;
- non-destruction ;
- absence réseau ;
- absence écriture risquée ;
- documentation ;
- compatibilité metadata-only si applicable.

## 8. Cohérence Makefile / .PHONY / configuration

Un audit vert exige :

- toute cible réelle appelable doit être dans `.PHONY` ;
- toute cible `.PHONY` doit avoir une règle réelle ;
- toute cible Makefile doit être classée ;
- aucune cible classée ne doit être absente du Makefile ;
- aucune cible ne doit rester dans `UNKNOWN` ;
- aucune cible sensible ne doit être SAFE_*.

## 9. Validation stricte de la configuration

Un audit vert exige :

- aucune catégorie YAML inconnue ;
- aucune cible classée plusieurs fois ;
- aucune valeur de catégorie mal formée ;
- aucune entrée non-string ;
- aucune cible dans `UNKNOWN` ;
- aucune erreur de configuration masquée par un traceback.

## 10. Motifs sensibles dans les noms de cibles

Même si une cible n’est pas dans la liste explicite des cibles sensibles, son nom peut indiquer un risque opérationnel.

Une cible classée SAFE_* doit être refusée si son nom contient un motif sensible comme :

- ingest ;
- scrape ;
- api ;
- watch ;
- backup ;
- deploy ;
- prod ;
- docker ;
- qdrant ;
- embed ;
- embedding ;
- upsert ;
- migrate ;
- sync ;
- upload ;
- download ;
- seed ;
- reset.

Les seules exceptions SAFE autorisées sont les cibles explicitement reconnues comme non destructives et déjà testées :

- cleanup-dry-run ;
- cleanup-review ;
- cleanup-decision-draft ;
- make-target-safety-audit.
