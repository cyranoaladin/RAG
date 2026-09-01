# LOT 1.2 — Plan d'implémentation release V2 et pages vides

**Statut :** actif après décision Option A du 31 août 2026.

**Objectif :** produire sans activation une release V2 à 320 artefacts
globaux, 488 placements et 11 sujets, avec chunks uniques et partition
exhaustive des pages.

**Discipline :** TDD strict RED → GREEN → refactor ; `--qui-atteste` avant
chaque fichier modifié ; aucun commit sur l'état mixte ; `audit.md` après
chaque changement d'état ; comparaison des suites par noms ; aucun écrit en
base de production.

**Design :**
`docs/superpowers/specs/2026-08-31-lot-1-2-partition-pages-vides-design.md`.

## Phase 0 — Bases et DAG

- [x] Relever worktree, branche, HEAD et état Git.
- [x] Capturer les noms avant patch : 2 835 `rag-pedago`, 3 066
  `rag-engine` hors intégration.
- [x] Exécuter `--qui-atteste` sur les documents de conception.
- [x] Choisir le DAG : `artifacts.release.json` est une feuille scellée,
  chaque sujet V2 la référence et l'agrégat V2 scelle registre + sujets.
- [x] Réviser design, plan et `audit.md` sans réécrire l'historique.

## Phase A — Topologie normalisée

### A1. RED lecteur V2

Fichiers :

- `services/rag-engine/tests/test_release_readiness.py`
- `services/rag-engine/src/ingestor/release_readiness.py`

Étapes :

1. Exécuter `--qui-atteste` sur le test et le lecteur.
2. Ajouter une fixture V2 : registre global frère, agrégat qui le scelle,
   sujets avec placements/références et même digest de registre.
3. Écrire les tests RED : un artefact/un placement ; un artefact/deux sujets ;
   double définition artefact ; double définition chunk ; référence absente ;
   artefact orphelin ; doublon dans un sujet ; sujet portant un chunk interdit ;
   compteurs explicites ; compatibilité V1 et duplication V1 toujours refusée.
4. Ajouter les sabotages non rescellés : artefact global, chunk, placement,
   retrait de référence ; vérifier l'échec au bon parent.
5. Exécuter les tests et consigner les échecs attendus dans `audit.md`.

### A2. GREEN lecteur V2

1. Ajouter les trois kinds V2 et la branche explicite du parser.
2. Introduire `ExpectedPlacement`; limiter `ExpectedArtifact` aux faits
   intrinsèques et chunks ; conserver le parseur V1 historique.
3. Valider liens du registre, références, orphelins, unicités, compteurs et
   digests.
4. Adapter la réconciliation globale et par collection : les artefacts sont
   sélectionnés par leurs placements, et les chunks gouvernés par
   `artifact_id`, jamais par `rag_chunks.collection` en V2.
5. Adapter `multilevel_verified_placement` et les bindings de subject SHA du
   retrieval aux kinds V1/V2.
6. Exécuter les tests ciblés jusqu'au GREEN ; consigner le diff réel.

### A3. RED/GREEN producteur V2

Fichiers :

- `services/rag-pedago/tests/test_build_production_profile_release.py`
- `services/rag-pedago/scripts/build_production_profile_release.py`

Étapes :

1. Exécuter `--qui-atteste` sur les deux fichiers.
2. RED : demander une définition globale unique pour deux lignes de placement,
   un registre frère, deux sujets sans chunks, compteurs explicites et kinds V2.
3. GREEN : construire une fois PII/préflight/définition par SHA ; vérifier que
   toutes les lignes du même SHA ont des faits intrinsèques identiques ; ne
   jamais prendre la « première ligne » comme vérité non vérifiée.
4. Construire les placements par collection et conserver l'unicité
   `(collection, SHA)`.
5. Faire passer D-31 sur la fixture V2 sans retirer les refus V1.
6. Saboter une copie jetable et vérifier la chaîne
   registre → sujets → agrégat → release-registry.

### A4. Consommateurs et non-régression A

1. Ajouter les tests RED/GREEN des consommateurs directement incompatibles.
2. Vérifier `load_multilevel_release_eligibility` sur deux placements du même
   artefact.
3. Vérifier le binding de chaque collection au SHA de son sujet V2.
4. Exécuter les tests readiness, registry, placement et producteur ciblés.
5. Revue indépendante de conformité de la Phase A.

## Phase B — Autorité unique et partition des pages

### B1. RED foyer unique du prédicat PDF

Fichiers prévus :

- nouveau package technique neutre `packages/pdf-page-policy/` ;
- scanner PII et tests ;
- extracteur `rag-engine` et tests ;
- Makefiles/images qui doivent installer le foyer partagé.

Étapes :

1. Exécuter `--qui-atteste` sur chaque fichier existant avant modification.
2. RED : les deux services utilisent le même verdict canonique sur les mêmes
   fixtures et témoins ; erreurs fail-closed ; document entièrement vide refusé.
3. GREEN : déplacer seulement le parcours structurel et ses codes canoniques
   dans le foyer neutre ; PII et extracteur l'appellent.
4. Enregistrer l'empreinte de cette politique dans les preuves nouvelles sans
   réinterpréter rétrospectivement `pii_scanner_sha256`.

### B2. RED/GREEN dérivation PII et préflight

1. RED : `PIIScanResult` expose les pages dérivées ; `_pii_evidence` les
   inclut dans le core scellé ; le préflight consomme cette preuve exacte.
2. Couvrir pages initiale, médiane, finale et multiples ; image/ambiguïté ne
   produit jamais une liste admissible.
3. RED : page non vide dont le chunk est retiré reste refusée ; chevauchement,
   trou, hors bornes, doublon, ordre, `bool` et document vide sont refusés.
4. GREEN minimal : valider canonicalité, disjonction et union exacte.
5. Propager `ignored_empty_pages` uniquement dans la définition globale V2 ;
   conserver `page_coverage_digest` sur les pages couvertes par chunks.

### B3. RED/GREEN lecteur des pages et citations

1. Ajouter la matrice pages au parser V2 et la compatibilité V1 approuvée.
2. Sabotage non rescellé puis mensonge entièrement rescellé : échec digest puis
   échec sémantique.
3. Caractériser `[page 1 texte, page 2 vide, page 3 texte]` et exiger la page
   physique 3 sur le premier chunk suivant.
4. Exécuter les tests ciblés des deux services et consigner RED/GREEN.

## Phase C — Vérification complète

1. Lint et typecheck concernés.
2. Suite complète `rag-pedago`; comparer les noms avec la base 2 835.
3. Suite complète `rag-engine` hors intégration; comparer les noms avec la
   base 3 066.
4. Contrats, readiness, attestations et tests transversaux concernés.
5. Aucun skip, suppression de garde ou réécriture d'une preuve historique.
6. Revue indépendante de conformité puis de qualité.
7. Consigner commandes, statuts, nombres exacts et diff dans `audit.md`.

## Phase D — Témoins et production fraîche

1. Remesurer `8848f073…` avec le prédicat unique ; ne figer la page 54
   qu'après preuve. Exécuter PII et extracteur sur les mêmes octets.
2. Reconfirmer que `3bc5ff23…` reste refusé comme document image/ambigu.
3. Relever branche, HEAD, index/worktree, overrides, entrées et digests,
   runtimes pypdf, modèles, inventaires et référence 319/486.
4. Créer une cible externe fraîche non servie et lancer depuis le worktree
   exact. Ne jamais suivre l'instruction d'activation.
5. Laisser toutes les portes, dont D-31, atteindre leur état terminal.

## Phase E — Gate de sortie

Exiger simultanément :

- `unique_artifacts = 320`, `placements = 488`, `subjects = 11` ;
- `unique_chunks` mesuré, aucun doublon de définition ;
- zéro référence ou artefact orphelin ;
- tous les artefacts V2 portent `ignored_empty_pages` ;
- zéro page inexpliquée, chevauchement ou hors bornes ;
- mapping complet SHA → pages ignorées et statistiques globales ;
- citations physiques vérifiées autour de chaque page ignorée ;
- sabotage artefact/chunk/page/placement/référence détecté ;
- D-31 et `load_release_expectation` PASS ;
- PII active, aucune divergence du prédicat partagé ;
- 319 artefacts et leurs chunks inchangés ; 486 placements inchangés ;
- seul artefact ajouté : `8848f073…` ; seuls placements ajoutés : ses deux
  placements NSI ; seul delta chunks : ses chunks ; `3bc5ff23…` absent ;
- comparaison DB read-only rouge uniquement sur ce delta, jamais faux
  `ready=True`.

Après succès : mettre `audit.md` à jour et présenter le checkpoint. Ne pas
commencer l'étape 3 du LOT 1.2.
