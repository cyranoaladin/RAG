# Lot — Republication gouvernée du catalogue candidat vers INGEST

## 1. Constat traité

Deux rapports de lot antérieurs documentaient le même constat structurel :

> `docs/reports/lot_fix_h2_evidence_workflow.md` §6 : « Il manque, dans ce
> dépôt, une étape automatisée réelle de « republication gouvernée » qui
> consommerait un catalogue candidat + une autorité vérifiée pour produire
> un catalogue où `disposition="INGEST"` — cette étape n'existe pas
> encore. »

> `docs/reports/lot_h2_authority_promotion.md` §« Portée » :
> `GOVERNED_REPUBLISH_STEP_EXISTS=false` — la promotion introduite par ce
> lot (Finding C) reste purement en mémoire, pour la durée d'un rapport de
> couverture ; aucun catalogue réel n'est jamais réécrit.

Ce lot construit cette étape manquante.

## 2. Investigation préalable (lecture seule)

Avant tout code, une investigation exhaustive a tracé :

- `expected_catalog_digest` sur `CorpusCampaignV1` (`corpus_campaign.py:142`)
  était un champ **totalement mort** : jamais produit, jamais vérifié, par
  quoi que ce soit. Seuls deux fixtures de test lui donnaient une valeur
  factice.
- `ScopeAuthorizationArtifactV2` (`nexus_contracts.authority_artifacts`)
  possédait déjà exactement la forme nécessaire (`allowed_content_sha256`,
  chemin canonique gouverné, intégration complète avec la liaison de revue
  scellée ADR-0035) — et `h2b_coverage_report.py` la consommait **déjà**
  intégralement (`_authority_structural_validation`,
  `_authority_semantic_validation`, `_load_authority_evidence`,
  `_promote_authority_cleared_candidates`), avec les trois couches de
  vérification ADR-0035 (structurelle, sémantique, liaison de revue) déjà
  câblées à de vrais fichiers via CLI.
- Le vrai manque n'était donc **pas** un nouveau schéma d'autorisation
  (le plan initialement validé avec l'opérateur en proposait un nouveau —
  corrigé au fil de l'implémentation, voir §7) mais uniquement la
  **matérialisation sur disque** du résultat déjà validé.

## 3. Ce qui a été construit

### 3.1 Refactor préalable (comportement inchangé)

`services/rag-pedago/rag_pedago/imports/h2b_coverage_report.py` : extraction
de la fonction publique `ingest_candidate_facts(physical_objects)`
(empreintes + catégories de droits du périmètre `base_disposition ==
"INGEST"`), auparavant dupliquée en ligne dans `generate_coverage_report`.
Comportement-préservant, vérifié par les 143 tests existants de la suite
H2 avant/après le refactor, sans aucune régression.

### 3.2 Nouveau module

`services/rag-pedago/rag_pedago/governance/catalog_republish.py` —
`republish_catalog(...)` :

1. Refuse tout `campaign.environment != "production"` (même discipline que
   `report_to_h2_coverage_evidence` : une clé de répétition ne peut jamais
   matérialiser ce qui sera réellement consommé).
2. Charge l'autorité (`--authority`) et sa liaison de revue scellée
   (`--authority-review-binding`) via `_load_authority_evidence` —
   **réutilisée, jamais dupliquée** — qui applique les trois couches
   ADR-0035 en mode `production` strict (ancre et registre de révocation
   toujours lus au chemin gouverné, jamais en argument).
3. Vérifie `authority.authorization_id == campaign.authorization_id` (la
   campagne approuvée doit nommer *cette* autorisation, pas une autre).
4. Vérifie `catalog["manifest_sha256"] == campaign.expected_manifest_sha256`.
5. Applique `_promote_authority_cleared_candidates` — réutilisée,
   fonction introduite par le lot précédent — sur une copie profonde des
   objets physiques.
6. Sérialise le catalogue promu (mêmes réglages canoniques que
   `corpus_catalog_compiler.py --output` : clés triées, indentation 2,
   UTF-8, LF final) et **exige** que son digest égale exactement
   `campaign.expected_catalog_digest` — donnant à ce champ, mort jusqu'ici,
   son premier producteur et son premier vérificateur réels.
7. Écrit `catalog.json` et `catalog.digest.json` sous
   `governance/corpus-campaigns/<campaign_id>/` (chemins déjà nommés par
   `CorpusCampaignV1.canonical_dir()`/`catalog_digest_path()`).
8. **Idempotence sans écrasement** : si `catalog.digest.json` existe déjà
   avec un `catalog_sha256` différent, refus explicite — jamais de
   réécriture silencieuse d'un artefact gouverné déjà publié (même
   philosophie que `corpus_publication.py` pour le registre OCI). Si le
   digest existant est identique, no-op idempotent (`already_published`).

### 3.3 CLI

`rag-pedago-governance republish-catalog` (`governance/cli.py`), quatrième
sous-commande, même discipline que `h2-evidence` : tous les arguments sont
requis, aucun n'est optionnel (vérifié par un test structurel dédié).

## 4. Ce qui n'a délibérément pas changé

- `corpus_catalog_compiler.py` : jamais touché — précédent explicite du lot
  d'autorité (`lot_h2_authority_promotion.md`).
- `packages/contracts` : jamais touché — `ScopeAuthorizationArtifactV2`
  existant s'est révélé suffisant.
- `services/rag-engine` : jamais touché.
- Aucune écriture pgvector, directe ou indirecte — ce lot matérialise un
  fichier catalogue gouverné, il ne touche à aucune base de données.
- Aucun contenu réel d'autorisation pour les 63 objets `RELEASE_ELIGIBLE`
  n'est créé ici — c'est une décision de gouvernance de contenu distincte
  (Section 10 de la directive du 2026-08-15), pas un artefact d'ingénierie.

## 5. Écart avec le plan initialement confirmé (amélioration, pas dérive)

Le plan présenté et confirmé avant codage proposait un **nouveau** schéma
`governance/authorizations/<id>.json` (`NEXUS-CATALOG-AUTHORIZATION-V1`).
L'investigation qui a suivi a montré que `ScopeAuthorizationArtifactV2`
couvrait déjà exactement ce besoin, avec en prime son intégration complète
à la liaison de revue scellée ADR-0035. Le construire quand même aurait dupliqué
une infrastructure existante — écart signalé ici explicitement plutôt que
laissé implicite : strictement moins de code nouveau, strictement plus de
réutilisation, que ce qui avait été confirmé.

## 6. Tests

- `services/rag-pedago/tests/test_catalog_republish.py` — 9 tests, corpus
  réel minimal fidèle aux fixtures de `test_h2b_coverage_report.py` (même
  ancre gouvernée de test, même autorité LOT41A-V2, même liaison de revue
  signée Ed25519). Couvre : promotion + matérialisation nominale, refus
  rehearsal, refus `authorization_id` divergent, refus manifeste divergent,
  refus digest divergent de `expected_catalog_digest`, idempotence, refus
  d'écrasement silencieux sur digest existant divergent, autorité absente,
  liaison de revue absente.
- `services/rag-pedago/tests/test_governance_cli_and_workflow.py` — mis à
  jour (3→4 sous-commandes) + nouveau test structurel « aucun argument
  optionnel » pour `republish-catalog`.
- Mutation-testing manuel sur les 5 branches de sécurité (refus rehearsal,
  refus authorization_id, refus manifest, refus digest, refus
  d'écrasement) : chaque garde désactivée fait échouer son test dédié pour
  la bonne raison, restaurée, suite verte à nouveau.
- Suite complète `rag-pedago` : 2505/2505 verts (deux échecs observés lors
  d'un premier passage se sont révélés être un artefact de course avec mes
  propres éditions concurrentes d'un fichier suivi pendant l'exécution —
  reproduits comme faux positifs, confirmés verts en isolation sans
  édition concurrente : `test_cleanup_dry_run_does_not_modify_git_status_
  staging_or_ledger`, `test_cleanup_review_does_not_modify_git_status_
  staging_or_ledger`, aucun rapport avec ce lot).
- `ruff check` et `mypy` : propres sur tous les fichiers touchés/ajoutés.

## 7. Booléens finaux

```
GOVERNED_REPUBLISH_STEP_EXISTS=true
GOVERNED_REPUBLISH_STEP_TESTED=true
GOVERNED_REPUBLISH_MUTATION_TESTED=true
EXPECTED_CATALOG_DIGEST_HAS_A_PRODUCER=true
EXPECTED_CATALOG_DIGEST_HAS_A_VERIFIER=true
CORPUS_CATALOG_COMPILER_UNTOUCHED=true
CONTRACTS_PACKAGE_UNTOUCHED=true
RAG_ENGINE_UNTOUCHED=true
REAL_AUTHORIZATION_CONTENT_FOR_THE_63_CREATED=false   # décision de gouvernance distincte, hors périmètre
```

## 8. Prochaine étape

Ce lot ferme le blocker technique. La prochaine étape (hors périmètre de
ce lot, per Section 10 de la directive du 2026-08-15) est la construction
du contenu réel d'autorisation — un `ScopeAuthorizationArtifactV2` +
liaison de revue scellée réels, couvrant exactement les 63 SHA-256
`RELEASE_ELIGIBLE`, avec la revue humaine que cela implique — puis un
premier `campaign.json` réel pointant dessus.
