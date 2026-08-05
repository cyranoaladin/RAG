# ADR-0026 — Contrats canoniques du moteur d'ingestion (LOT44a)

- **Statut** : Accepté
- **Date** : 2026-08-04
- **Décideur** : Alaeddine Ben Rhouma (Shark)
- **Découle de** : ADR-0001 (séparation plan de contrôle / plan de données / cockpit), ADR-0002 (contrat partagé `nexus-contracts` versionné), ADR-0004 (ingestion agentique), ADR-0023 (review BFF et durcissement runtime)
- **ADR liés** : rapport `docs/reports/lot_43_rag_engine_p1_hardening.md` (clôture LOT43, commit `ac8bc10`)

## Contexte

LOT43 a clos le durcissement P1 du moteur `rag-engine` (routes legacy, SSRF, migrations, scope serveur, timeouts) sans construire l'usine d'ingestion agentique elle-même. Une phase de conception en plusieurs tours (Phase 0 LOT44, validée avec le décideur) a produit une proposition d'architecture minimale et progressive pour cette usine, découpée en sous-lots indépendants (LOT44a → LOT44g). LOT44a est le premier : les contrats canoniques, condition préalable à tout le reste (schéma Postgres, agents, orchestrateur, MCP), puisque ADR-0002 impose `nexus-contracts` comme source de vérité unique et interdit toute redéfinition locale.

`nexus-contracts` (`packages/contracts/`) ne portait jusqu'ici que le contrat de retrieval, de review et d'identité (ADR-0002, ADR-0022, ADR-0023). Aucun modèle ne représentait un candidat de ressource, un artefact téléchargé, une décision de routage, un rapport qualité, un run d'ingestion ou une collection gouvernée. Cet ADR couvre l'ajout de ces modèles.

## Périmètre

**Dans le périmètre de LOT44a et de cet ADR :**
- huit modèles Pydantic canoniques : `CollectionProfile`, `SearchPlan`, `ResourceCandidate`, `ArtifactRecord`, `RoutingDecision`, `QualityReport`, `IngestionRun`, `CoverageSnapshot` ;
- un type de scope partagé `ResourceScope` (dix dimensions obligatoires) et une politique de publication passive `PublicationPolicy` ;
- une machine d'état pure (`ResourceState`, sans effet de bord) décrivant les transitions valides d'une ressource, dépourvue de tout état de publication ;
- l'extension du pipeline de synchronisation existant (`export_schemas.py` → JSON Schema → `generate-contracts.mjs` → TypeScript) à ces nouveaux modèles ;
- les tests contractuels correspondants.

**Explicitement hors périmètre de LOT44a (renvoyé à LOT44b et suivants) :**
- toute migration PostgreSQL (aucune table `collection_profiles`, `ingestion_runs`, `ingestion_jobs`, `workflow_events`, `resources`, etc. n'est créée par ce lot) ;
- tout worker, tout scheduler, tout agent exécutable, tout orchestrateur ;
- tout serveur MCP (différé explicitement à LOT44g, après stabilisation des fonctions déterministes) ;
- tout endpoint HTTP, côté `rag-engine` comme côté Cockpit ;
- toute modification du ledger SQLite existant (`services/rag-pedago/rag_pedago/ledger/`), qui reste strictement inchangé — c'est un système d'audit batch du controlled-import distinct par nature (SQLite mono-écrivain, sans `SKIP LOCKED` ni lease) du futur moteur PostgreSQL multi-worker de LOT44b ;
- tout mécanisme réel de publication produit ;
- toute modification des verrous de gouvernance (`pedago_interface_contract.yml`, `governance-locks.baseline`) — vérifiés inchangés.

## Décisions retenues

### 1. Scope gouverné complet, obligatoire, fail-closed

`ResourceScope` porte exactement les dix dimensions déjà gouvernées côté `rag-engine` (colonnes `rag_chunks` de LOT41, `003_profile_filtering.sql`) : `tenant`, `collection`, `niveau`, `voie`, `matiere`, `candidat`, `audience`, `visibility`, `school_year`, `programme_version`. Aucun champ n'a de valeur par défaut — une instanciation incomplète échoue à la construction, jamais silencieusement. Ce type est embarqué comme champ obligatoire (`scope: ResourceScope`, sans défaut) dans chacun des huit modèles canoniques, sans exception.

### 2. Identifiants UUID, hash réservés à la déduplication

Tous les identifiants d'exécution et clés primaires (`run_id`, `candidate_id`, `resource_id`, `artifact_id`, `decision_id`, `report_id`, `snapshot_id`, `search_plan_id`) sont typés `UUID`. Les hash déterministes SHA-256 (`dedup_key`, `sha256`) sont réservés à la déduplication, l'idempotence et le rattachement contrôlé de versions — jamais utilisés comme identifiant primaire.

### 3. `ResourceCandidate` toujours rattaché à une ressource

`resource_id` est un champ obligatoire (jamais nul) : la conception retenue crée la ressource provisoire de façon atomique dès l'acceptation du candidat (même transaction, détail d'implémentation renvoyé à LOT44b), garantissant qu'aucun candidat ne peut exister sans ressource rattachée, et donc aucune ressource orpheline.

### 4. Machine d'état sans notion de publication

`ResourceState` énumère vingt valeurs (séquence normale `DISCOVERED → ... → REVIEWED → RETRIEVAL_ELIGIBLE`, plus les états d'échec/quarantaine/doublon). **`PUBLISHED` n'existe pas dans cette énumération.** `CANDIDATE` et `STAGED` sont séparés par sept états intermédiaires obligatoires dans la séquence normale — aucune transition directe `CANDIDATE → STAGED` n'est représentable dans la table de transitions (`is_valid_resource_transition`, testé exhaustivement).

### 5. Distinction stricte `REVIEWED` / `RETRIEVAL_ELIGIBLE`

- `REVIEWED` signifie **uniquement** que la décision humaine a été validée côté `rag-engine` (`review_status = 'reviewed'`, mécanisme déjà démontré en LOT43 §43.7 via `/review/v2/decide`). Ce n'est jamais une décision prise par le moteur LOT44 lui-même.
- `RETRIEVAL_ELIGIBLE` est une **vérification déterministe et automatique**, constatée (pas décidée) une fois qu'une ressource `REVIEWED` satisfait le prédicat de scope du retrieval — identique au prédicat SQL déjà utilisé par `retrieval_pg_v2.py`/`review_v2_endpoint.py`.
- Les deux ne sont **jamais synonymes** : `REVIEWED` peut exister sans que `RETRIEVAL_ELIGIBLE` soit encore constaté (le contrôle de scope n'a pas encore tourné), et la transition `REVIEWED → RETRIEVAL_ELIGIBLE` est la seule voie normale vers l'avant depuis `REVIEWED`.
- Cette distinction est testée exhaustivement (`test_reviewed_and_retrieval_eligible_are_not_synonymous` et la suite `test_publication_policy_scope.py`).

### 6. `PublicationPolicy` conservée comme politique passive, verrouillée au type

`PublicationPolicy` (portée par `CollectionProfile.publication`) a été réexaminée spécifiquement pour cet ADR : elle **n'introduit ni état `PUBLISHED`, ni transition, ni comportement, ni endpoint** de publication. Ses deux champs sont verrouillés **au niveau du type**, pas seulement par une valeur par défaut :
- `mode: Literal["human_review"]` — aucune autre valeur n'est représentable (en particulier pas `"trusted_auto_publish"`, qui n'existe pas dans le type) ;
- `auto_publish: Literal[False]` — structurellement impossible à valider à `True` en LOT44a.

Elle est donc retenue comme **politique passive** au sens de la revue de ce lot : une déclaration d'intention inerte, sans capacité d'action, qui prépare la place pour un futur sous-système de publication produit sans en construire aucune partie. Démontré par les tests listés en section « Tests ».

### 7. Réutilisation stricte du pipeline de contrats existant

Aucun second système de contrats n'a été créé. `export_schemas.py` (Python → JSON Schema) et `generate-contracts.mjs` (JSON Schema → TypeScript, via `json-schema-to-typescript` et `ajv`) sont étendus avec les huit nouvelles entrées, exactement selon le motif déjà utilisé pour les contrats de review (ADR-0023). Les schémas JSON générés sont vérifiés bit-à-bit stables et rejoués avec `pydantic==2.13.4`, la version exacte verrouillée par `packages/contracts/pyproject.toml` (cf. rapport de validation LOT44a).

## Versionnement SemVer

Selon la règle déjà fixée par ADR-0002 :
> *mineur* : ajout rétro-compatible (champ optionnel, nouvelle valeur d'enum non requise).

Les huit nouveaux modèles, `ResourceScope`, `PublicationPolicy` et le module `resource_state` sont des **ajouts purs** : aucun modèle existant n'est modifié, aucun champ existant ne devient requis, aucune valeur d'enum existante n'est supprimée ou renommée, aucune validation existante n'est resserrée. C'est un changement strictement rétro-compatible.

**Version : `0.5.0` → `0.6.0`.**

## Découplage entre le SemVer du package et le namespace des schémas JSON

Cette décision a été explicitement examinée en revue de LOT44a et méritait d'être actée ici plutôt que de rester implicite dans une réponse de revue.

**Constat.** Le package `nexus-contracts` passe à `0.6.0` (section précédente). `CONTRACT_VERSION`, la constante utilisée par `packages/contracts/scripts/export_schemas.py` pour construire l'identifiant `$id` de chaque schéma JSON (`https://nexusreussite.academy/contracts/v{CONTRACT_VERSION}/{filename}`), **reste à `"0.5"`** et n'est **pas** modifiée par LOT44a.

**Nature de `CONTRACT_VERSION`.** Ce n'est pas un numéro de version du package : c'est le **namespace stable** des identifiants `$id` de schéma JSON — une adresse d'espace de noms, pas un compteur qui doit suivre chaque publication. Il n'existe qu'un seul endroit où cette valeur est utilisée (`export_schemas.py::schema_bytes`), et elle est reproduite telle quelle dans les quatorze schémas préexistants et les huit nouveaux schémas LOT44a.

**Découplage volontaire.** Le SemVer du package (`0.5.0` → `0.6.0`) suit la règle d'ADR-0002 (mineur = ajout rétro-compatible) à chaque changement de contrat, aussi petit soit-il. Le namespace `CONTRACT_VERSION` est délibérément plus grossier et ne suit pas ce rythme : il ne change que lorsque l'espace de noms d'adressage des schémas lui-même doit changer (par exemple une rupture d'URL, une réorganisation du service qui sert ces schémas), ce qui est un événement distinct d'un ajout de modèles.

**Raison du maintien à `0.5` pour LOT44a spécifiquement.** Faire suivre `CONTRACT_VERSION` au SemVer du package aurait changé le champ `$id` — donc le **contenu** — des quatorze fichiers de schéma déjà commités et utilisés (par `rag-engine`, le Cockpit, et tout consommateur externe qui aurait pu épingler ces URL), pour un lot qui n'ajoute que des modèles strictement nouveaux et ne modifie aucun schéma existant. Bumper `CONTRACT_VERSION` aurait donc réécrit quatorze fichiers sans nécessité fonctionnelle, uniquement pour une chaîne d'URL — au prix d'un diff bien plus large que l'ajout additif réellement livré, et d'un risque de casser un consommateur externe qui référencerait déjà `v0.5/...`. Ce lot n'a strictement rien changé, y compris de ce point de vue : les quatorze schémas préexistants restent bit-à-bit identiques (vérifié avec `pydantic==2.13.4`, la version exacte verrouillée).

**Obligation pour l'avenir.** Toute décision de faire évoluer `CONTRACT_VERSION` (que ce soit pour l'aligner sur le SemVer du package ou pour une autre raison) nécessite un **ADR dédié**, distinct de celui-ci, qui devra explicitement traiter la réécriture de tous les fichiers de schéma existants et la compatibilité des consommateurs déjà déployés qui référenceraient les URL `v0.5/...`.

**Confirmation.** Le maintien de `CONTRACT_VERSION` à `"0.5"` ne constitue **ni une migration** (aucune base de données, aucun schéma SQL n'est concerné) **ni un changement de comportement applicatif** (aucun code exécutable ne lit ni n'interprète cette constante au runtime — elle n'apparaît que dans un artefact statique généré, le champ `$id` d'un fichier JSON Schema, consommé au mieux comme identifiant documentaire).

## Conséquences

### Positives
- Les huit contrats de l'usine d'ingestion existent, testés et synchronisés Python/TypeScript, avant tout code applicatif — LOT44b (schéma Postgres) peut s'appuyer dessus sans device de type.
- Le verrouillage au type de `PublicationPolicy` rend l'invariant « auto-publication désactivée par défaut » vérifiable par le compilateur/le validateur, pas seulement par convention.
- L'absence de `PUBLISHED` dans l'énumération élimine toute ambiguïté de contrat sur la publication produit avant que ce sous-système n'existe.

### Négatives
- `ResourceCandidate` sans champ de statut propre impose que toute lecture de son état passe par `resource_id` → `resource_state` (LOT44b) ; ce couplage doit être respecté par tout code consommateur futur.
- `PublicationPolicy` reste un nom qui évoque la publication avant que le sous-système correspondant n'existe — risque de confusion en revue si cet ADR n'est pas lu ; mitigé par la documentation dans le code et ce document.

### Risques et mitigations
- *Dérive future d'un champ « publication » vers un comportement réel sans ADR dédié* → tests figeant `Literal[False]`/`Literal["human_review"]` ; toute levée nécessitera de changer le type, donc de casser la compilation/la validation, donc de passer par une revue explicite.
- *Confusion `REVIEWED`/`RETRIEVAL_ELIGIBLE`* → distinction testée exhaustivement et documentée dans le module `resource_state.py` lui-même.

## Suites

- LOT44b : schéma PostgreSQL du plan de contrôle (`ingestion_control`), primitives de concurrence (`SKIP LOCKED`, lease, CAS), rôle à privilèges minimaux, protection SQL réelle de `workflow_events` contre `UPDATE`/`DELETE`.
- LOT44g : adaptateurs MCP, différés jusqu'à stabilisation des fonctions déterministes (LOT44c/44d).
- Un ADR dédié restera nécessaire avant toute levée réelle de `auto_publish` ou toute introduction d'un état `PUBLISHED`, conformément à ADR-0002 (changement majeur) et à AGENTS.md.
