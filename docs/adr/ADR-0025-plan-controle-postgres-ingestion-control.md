# ADR-0025 — Plan de contrôle PostgreSQL `ingestion_control` (LOT44b, décision D1)

- **Statut** : Accepté
- **Date** : 2026-08-04
- **Décideur** : Alaeddine Ben Rhouma (Shark)
- **Découle de** : ADR-0001 (séparation plan de contrôle / plan de données / cockpit), ADR-0002 (contrat partagé `nexus-contracts` versionné), ADR-0024 (contrats canoniques d'ingestion, LOT44a)
- **ADR liés** : rapport de conception LOT44 (Phase 0, conversation), rapports de clôture LOT44a/LOT44b (revue directe)

## Contexte

LOT44a a livré les contrats canoniques Python/TypeScript de l'usine d'ingestion (`CollectionProfile`, `SearchPlan`, `ResourceCandidate`, `ArtifactRecord`, `RoutingDecision`, `QualityReport`, `IngestionRun`, `CoverageSnapshot`, `ResourceScope`, `ResourceState`) sans aucune persistance ni comportement. LOT44b devait construire le schéma PostgreSQL de ces contrats et les primitives atomiques de concurrence (claim, transition CAS, retry/backoff, lease reaper) nécessaires à un futur moteur multi-worker (LOT44c+), sans construire ce moteur lui-même.

La décision D1 (« même instance PostgreSQL/pgvector, schéma logique dédié `ingestion_control` ») avait été formulée à plusieurs reprises dans la conversation de conception, mais jamais actée dans un ADR dédié. Cet ADR corrige ce manque et documente précisément les choix effectués et vérifiés lors de la revue de clôture de LOT44b — y compris deux corrections apportées pendant cette revue (suppression d'un privilège excessif, séparation stricte de deux identifiants qu'une première rédaction avait laissés ambigus).

## Décision D1 — Instance et schéma

- **Même instance PostgreSQL/pgvector** que le reste du projet (celle qui héberge `public.rag_chunks`) — pas d'instance Postgres supplémentaire à opérer.
- **Schéma logique dédié `ingestion_control`**, jamais mélangé à `public`. Vérifié explicitement : recherche exhaustive de `rag_chunks` dans tout le code et les migrations LOT44b — les deux seules occurrences trouvées sont des commentaires de documentation affirmant la séparation, aucune jointure, aucune référence de clé étrangère, aucune requête ne traverse les deux schémas.
- **Aucune table de contrôle dans `rag_chunks`** : les cinq tables du plan de contrôle (`ingestion_runs`, `resources`, `resource_candidates`, `artifacts`, `workflow_events`) et le registre (`schema_migrations`) vivent exclusivement dans `ingestion_control`.

## Rôles et privilèges

Deux rôles, jamais confondus, provisionnés par `infra/scripts/provision_ingestion_control_roles.sh` :

| Rôle | Usage | Privilèges exacts |
|---|---|---|
| `ingestion_control_migrator` | Exécute uniquement `bootstrap_ingestion_control_schema.sh` (DDL des migrations) | `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS`, propriétaire (`OWNER`) du schéma `ingestion_control` — la propriété d'un schéma suffit intrinsèquement à y créer des objets (`CREATE TABLE`/`INDEX`/`CONSTRAINT`), aucun privilège de gestion des rôles n'est nécessaire |
| `ingestion_control_app` | Seul rôle utilisé par les quatre primitives Python | `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS`, `USAGE` sur le schéma, `SELECT/INSERT/UPDATE` sur `ingestion_runs`/`resources`/`resource_candidates`/`artifacts`, **`SELECT/INSERT` seul** sur `workflow_events` (`UPDATE`/`DELETE`/`TRUNCATE` explicitement révoqués), aucun privilège sur `public` |

### `CREATEROLE` — retiré, décision explicite

Une première rédaction du script accordait `CREATEROLE` au rôle de migration « au cas où ». Une revue de clôture a vérifié directement le script : **la création des deux rôles eux-mêmes est faite par la connexion administrative externe (`$PGUSER`, superutilisateur du conteneur ou équivalent CREATEROLE), jamais par le rôle de migration**. Ce dernier n'exerce jamais `CREATEROLE` nulle part dans ce lot — il n'a besoin que d'être propriétaire du schéma. `CREATEROLE` a donc été retiré (`NOCREATEROLE`) : c'était un privilège excessif accordé sans justification, corrigé pendant la revue plutôt que documenté comme nécessaire à tort.

Vérifié par un test réel de privilèges effectifs (`test_migrator_role_has_no_createrole_privilege`, cf. section Tests) : interroge directement `pg_roles.rolcreaterole` après provisionnement.

### Append-only réel

La protection de `workflow_events` contre `UPDATE`/`DELETE` est un privilège SQL réel (`REVOKE`), pas une convention applicative — vérifiée par test réel (`InsufficientPrivilege` levée par PostgreSQL lui-même lors d'une tentative de `UPDATE`/`DELETE` avec le rôle runtime).

## Séparation stricte des identités

Une première rédaction de la documentation (pas du code exécutable) suggérait que `job_id` puisse être renseigné à partir de `lease_token`. Une revue de clôture a corrigé ce point : les cinq identités suivantes restent **conceptuellement et effectivement distinctes**, jamais l'une substituée à l'autre :

- `run_id` (UUID) : identifie l'exécution (`ingestion_runs`).
- `job_id` (UUID, nullable, sans contrainte de clé étrangère) : identifiant libre d'une éventuelle tentative d'exécution métier — **reste `NULL` par défaut**, jamais rempli automatiquement par `claim_resource` ni par `cas_transition`. LOT44a ne définit aucun contrat `IngestionJob` ; LOT44b ne crée aucune table `jobs` (aucun concept non justifié). `job_id` n'a donc, dans ce lot, aucun producteur automatique — il existe dans le schéma pour qu'un futur LOT44c+ puisse l'alimenter sans migration supplémentaire.
- `resource_id` (UUID) : identifie la ressource (`resources`).
- `lease_token` (UUID) : identifiant **secret** de possession temporaire d'un bail de concurrence, généré neuf à chaque réclamation réussie par `claim_resource`, jamais réutilisé comme `job_id`.
- `claimed_by` (texte libre) : identité du détenteur du bail (nom de process/worker), distincte du token lui-même.

Vérifié par un test dédié (`test_job_id_and_lease_token_remain_distinct_identities`) qui construit un événement avec un `job_id` explicitement différent du `lease_token` de la réclamation en cours, et un second test qui confirme qu'une transition sans `job_id` explicite laisse la colonne `NULL` (jamais substituée).

## Absence de comportement applicatif

LOT44b crée exclusivement : le schéma, ses contraintes/index, et quatre fonctions Python transactionnelles (claim, CAS, retry/backoff, lease reaper). Vérifié par recherche exhaustive (grep) dans tous les fichiers créés :

- aucun `APIRouter`/`@app.get`/`@app.post`/route Next.js ;
- aucune tâche Celery, aucun `while True`, aucune boucle de scheduler ;
- aucune classe « Agent »/« Orchestrator »/serveur MCP ;
- aucune connexion réseau sortante (pas de `httpx`/`requests`) ;
- aucune écriture dans `rag_chunks` (zéro référence hors commentaires de documentation) ;
- aucune requête de retrieval, aucune notion de publication produit, aucun chemin vers `auto_publish=True`.

Le lease reaper (`reap_expired_leases`) reste une primitive contrôlée, appelée une fois par invocation : elle ne boucle jamais, ne dort jamais et ne décide jamais de sa propre cadence — un futur scheduler (hors périmètre LOT44b) décidera quand l'appeler.

## Scope : déploiement limité à une valeur par dimension

Les dix dimensions de `ResourceScope` (`tenant`, `collection`, `niveau`, `voie`, `matiere`, `candidat`, `audience`, `visibility`, `school_year`, `programme_version`) sont persistées **directement, en colonnes `NOT NULL` + `CHECK`**, sur `ingestion_runs` et `resources` — jamais nullables, jamais omissibles silencieusement. `resource_candidates`, `artifacts` et `workflow_events` ne portent pas le scope directement : ils y accèdent uniquement par clé étrangère (`resource_id`/`run_id`) vers les deux tables qui le portent.

Le **déploiement actuel** reste limité à une seule valeur par dimension de scope à la fois (héritage direct de la limitation déjà actée en LOT43 §43.4 : `NEXUS_DEFAULT_TENANT`/`NEXUS_DEFAULT_CANDIDAT`/etc., une valeur globale par déploiement, pas par requête). Ce n'est **pas** un vrai système multi-tenant.

### Portée de `UNIQUE (collection, dedup_key)`

La contrainte de déduplication d'identité porte sur `(collection, dedup_key)` uniquement — pas sur les dix dimensions de scope. Ce choix est **délibéré et directement lié à la limitation ci-dessus**, pas un oubli :

- `dedup_key = sha256(collection || url_canonique)` intègre déjà `collection` dans son calcul ; la colonne `collection` de la contrainte est donc redondante avec le hash lui-même, mais retenue explicitement pour la lisibilité de la contrainte SQL.
- Sous la limitation actuelle (une seule valeur par dimension pour tout le déploiement), deux ressources de même `collection`+`dedup_key` ont **nécessairement** les mêmes `tenant`/`candidat`/`school_year`/`programme_version`/`visibility`/`audience` — il ne peut structurellement pas y avoir de collision silencieuse entre deux scopes différents **tant que cette limitation tient**.
- **Risque documenté, non corrigé ici** : si un futur lot faisait varier ces valeurs par défaut *entre deux runs* (sans les faire encore varier *par requête*, ce qui resterait hors du périmètre multi-tenant), une collision `(collection, dedup_key)` entre deux runs aux scopes différents ferait que `INSERT ... ON CONFLICT DO NOTHING` conserverait silencieusement le scope du **premier** run et ignorerait celui du second. Ce risque est **volontairement non traité par un élargissement de la contrainte** aux dix dimensions : le faire créerait de facto un système multi-tenant sans ADR dédié, ce qui est explicitement exclu de ce lot. Un tel élargissement, s'il devient nécessaire, exige son propre ADR.
- Vérifié par un test dédié (`test_dedup_key_collision_across_different_scope_is_documented_not_fixed`) qui démontre exactement ce comportement (deux insertions avec même `collection`/`dedup_key` mais `tenant` différent → la seconde est silencieusement absorbée, scope du premier conservé) — un test de **documentation du comportement actuel**, pas une régression : il échouerait si un futur lot élargissait la contrainte sans ADR, ce qui est le signal recherché.

## Machine d'état — réutilisation stricte de LOT44a

Aucune seconde machine d'état n'est créée. Les `CHECK` SQL de `resources.resource_state` et de `workflow_events.from_state`/`to_state` énumèrent exactement les vingt valeurs de `nexus_contracts.resource_state.ResourceState`, vérifié par comparaison directe programmatique (vingt valeurs identiques, `PUBLISHED` absent des deux côtés). `CANDIDATE` et `STAGED` restent séparées de sept états intermédiaires obligatoires dans la séquence normale, aucune transition directe entre les deux n'est représentable — ni en Python (`is_valid_resource_transition`), ni en SQL (`resources_state_valid` ne contraint que les valeurs individuelles, la validité des *transitions* reste entièrement portée par `cas_transition`, seul point d'écriture de `resource_state`).

`claim_resource` borne désormais explicitement les états réclamables à `CLAIMABLE_STATES` (la séquence normale hors `RETRIEVAL_ELIGIBLE`) — un appelant ne peut plus réclamer arbitrairement un état terminal ou interdit (`ValueError` immédiate). Correction apportée pendant la revue de clôture : la première rédaction laissait `eligible_states` sans aucune borne.

## Retry et backoff : déterminisme sans jitter, décision propre à ce lot

`compute_backoff_seconds` est **volontairement déterministe, sans jitter** — décision propre à LOT44b, distincte de la recommandation par défaut « jitter ±20 % » actée lors de la phase de conception de LOT44 (qui restait une recommandation générale pour un futur ordonnanceur, pas une exigence de cette primitive précise). La consigne explicite de ce lot demandait un « backoff déterministe » pour la primitive de calcul elle-même : une composante aléatoire romprait la testabilité déterministe de cette fonction pure. Le jitter, s'il est souhaité, reste **applicable par un futur appelant** (LOT44c+ ou un lot dédié à l'ordonnancement) par-dessus la valeur retournée ici — cette primitive n'a pas à en décider.

## Explicitement hors périmètre de LOT44b

- Tout worker, scheduler, agent exécutable, orchestrateur, serveur MCP, endpoint HTTP, route Cockpit.
- Le pipeline Planner/Scout/Fetcher et toute connexion à une source externe.
- Toute écriture dans `rag_chunks`, toute logique de retrieval.
- Toute notion de publication produit ou d'auto-publication.
- Toute modification du ledger SQLite (`services/rag-pedago/rag_pedago/ledger/`), toujours strictement inchangé — système d'audit batch distinct par nature (SQLite mono-écrivain) du moteur PostgreSQL multi-worker de ce lot.
- Tout élargissement de `UNIQUE(collection, dedup_key)` vers un vrai modèle multi-tenant.
- Toute réintroduction d'un état ou d'un champ de publication (`PUBLISHED`).

## Bootstrap — différence assumée avec `pgvector_migration_state.sh`

`infra/scripts/bootstrap_ingestion_control_schema.sh` réutilise le **principe** de l'outil `rag_chunks` (registre versionné, checksum par migration, verrou `pg_advisory_xact_lock`, revalidation après application) mais **pas son code** : `pgvector_migration_state.sh` encode en dur, pour chaque version, le fingerprint exhaustif du catalogue Postgres de `rag_chunks` (colonnes, contraintes, index un par un — plus de 1000 lignes), spécifique à cette table et non généralisable sans duplication massive pour un schéma différent. Le bootstrap `ingestion_control` vérifie l'absence de dérive de checksum (`MIGRATION_CHECKSUM_MISMATCH`) et la présence des cinq tables attendues après application, mais ne revalide pas colonne par colonne. **Différence jugée acceptable** : le risque couvert par le fingerprint exhaustif (dérive silencieuse d'un schéma déjà en production, modifié hors migration) est structurellement moins critique ici, puisque `ingestion_control` ne contient encore aucune donnée de production réelle (LOT44b ne construit aucun appelant) — à réévaluer si LOT44c+ constate un besoin réel de cette rigueur supplémentaire.

## Conséquences

### Positives
- Rôles à moindre privilège réellement vérifiés (pas seulement déclarés) — `CREATEROLE` retiré après un examen direct, append-only réel testé.
- Aucune ambiguïté durable entre `job_id` et `lease_token` : documentation et code alignés après revue.
- Le risque de collision `(collection, dedup_key)` inter-scope est documenté et testé plutôt que silencieusement ignoré.

### Négatives
- Le bootstrap `ingestion_control` offre une garantie de non-dérive de schéma moins forte que l'outil `rag_chunks` — accepté comme proportionné, pas comme équivalent.
- `job_id` sans producteur dans ce lot signifie que `workflow_events.job_id` restera `NULL` pour tout événement produit avant LOT44c+ — attendu, pas un défaut.

### Risques et mitigations
- *Collision `(collection, dedup_key)` inter-scope future* → documentée ci-dessus, testée, bloquée par nécessité d'un ADR dédié avant tout élargissement.
- *Dérive silencieuse du schéma hors migration* → couverte partiellement (checksum du registre), pas par fingerprint exhaustif — réserve assumée.

## Suites

- LOT44c+ : agents/stages déterministes consommant ces primitives, premier producteur réel de `job_id`.
- Un ADR dédié reste nécessaire avant tout élargissement de `UNIQUE(collection, dedup_key)` vers les dix dimensions de scope, et avant toute déclaration de vrai multi-tenant.
- Un ADR dédié reste nécessaire avant toute réintroduction d'un état `PUBLISHED` ou d'un comportement de publication (déjà acté par ADR-0024).
