# ADR-0029 — Stages déterministes de l'usine d'ingestion agentique (LOT44d)

- **Statut** : Accepté
- **Date** : 2026-08-04
- **Décideur** : Alaeddine Ben Rhouma (Shark)
- **Découle de** : ADR-0026 (contrats canoniques d'ingestion, LOT44a), ADR-0027 (plan de contrôle PostgreSQL `ingestion_control`, LOT44b), ADR-0028 (profils et validation déterministe, LOT44c — en particulier sa section « Contrat d'interface pour LOT44d et LOT44e »)
- **Chronologie réelle de ce document** : rédigé après l'implémentation (huit modules `ingestion_agents/*.py`, un module de dépendances, un module de transitions, treize fichiers de tests, tous vérifiés verts avant rédaction) — documente des décisions déjà prises dans le code, jamais lu comme une entrée pré-existante avant ce code.

## Contexte

LOT44a a livré les contrats canoniques (`SearchPlan`, `ResourceCandidate`, `ArtifactRecord`, `RoutingDecision`, `QualityReport`, `CoverageSnapshot`) et la machine d'état `ResourceState`/`NORMAL_SEQUENCE`. LOT44b a livré le plan de contrôle PostgreSQL et ses quatre primitives (`claim_resource`, `cas_transition`, `record_retry`, `reap_expired_leases`). LOT44c a livré le chargement/sélection/validation déterministe de profil et documenté explicitement, dans sa section « Contrat d'interface pour LOT44d et LOT44e », la chaîne visée par LOT44d : `claim PostgreSQL → sélection de profil → validation → persistance du résultat → décision de retry/revue → cas_transition → suite`, en désignant LOT44d comme « le premier consommateur légitime d'un résultat de validation pour déclencher une transition explicite via `cas_transition` ».

LOT44d construit les huit stages eux-mêmes — Planner, Scout, Fetcher, Extractor, Classifier, RightsAgent, QualityAgent, CoverageAgent — comme des interfaces déterministes, testables sur fixtures, raccordables aux contrats existants, mais **non câblées à aucun processus de production réel**.

## Décision 1 — Un cœur pur par stage, une couche d'exécution injectée

Chaque stage est scindé en deux fonctions :
- `*_core` : fonction pure — aucune E/S réseau, aucun PostgreSQL, aucune horloge implicite (tout timestamp est un paramètre explicite). Entrée et sortie exclusivement en contrats `nexus_contracts.ingestion` typés (ou en petits objets de résultat locaux, ex. `ConformityResult`).
- `run_*` : couche d'exécution — reçoit ses dépendances d'E/S par injection explicite (`ingestion_agents.dependencies` : `DestinationValidator`, `SafeFetcher`, `ArtifactStore`, `ArtifactReader`), avec une implémentation réelle par défaut quand elle existe (`ssrf_guard.validate_destination`/`safe_fetch`, LOT43 D-7) et aucun défaut quand elle n'existe pas dans ce dépôt (`ArtifactStore`/`ArtifactReader` — LOT44d ne contient aucun client de stockage réel, en créer un serait une infrastructure de production hors périmètre).

Chaque cœur est testé sur fixtures, sans réseau ni PostgreSQL ; chaque couche d'exécution est testée avec des doublures explicites (jamais la vraie garde SSRF ni un vrai PostgreSQL dans les tests unitaires).

## Décision 2 — Toute transition passe par `apply_resource_transition`, jamais une écriture directe

`ingestion_agents/transitions.py::apply_resource_transition` enchaîne explicitement `is_valid_resource_transition` (LOT44a, contrôle structurel pur) puis `cas_transition` (LOT44b, écriture CAS réelle) — aucun stage n'appelle `cas_transition` directement, aucun stage n'écrit `resources.resource_state` par un autre chemin. `job_id` n'est **jamais un paramètre** de cette fonction : transmis en dur à `None` à `cas_transition` — structurellement impossible à renseigner depuis LOT44d, conformément à ADR-0028 qui assigne la production réelle de `job_id` (et la table `jobs` associée) à LOT44e.

Mapping stage → transition, conforme à `NORMAL_SEQUENCE` (aucun saut) :

| Stage | Transition portée |
|---|---|
| Scout | `DISCOVERED → CANDIDATE` |
| Fetcher | `CANDIDATE → FETCHED` puis `FETCHED → STORED` (deux CAS distincts) |
| Extractor | `STORED → EXTRACTED` |
| Classifier | `EXTRACTED → CLASSIFIED` |
| RightsAgent | `CLASSIFIED → RIGHTS_CHECKED` |
| QualityAgent | `RIGHTS_CHECKED → QUALITY_CHECKED` (unique transition persistée par ce stage) |
| Planner | aucune (amont, avant `DISCOVERED`) |
| CoverageAgent | aucune (aval, hors machine d'état) |

## Décision 3 — `RoutingDecision` calculée par QualityAgent, jamais persistée ni activée

`QualityAgent` calcule une `RoutingDecision` déterministe (`decide_routing_core`, priorité doublon > PII > motif de rejet > acceptation) immédiatement après avoir produit `QualityReport`. **La transition `QUALITY_CHECKED → ROUTED` n'est jamais appliquée par ce lot** : `run_quality_agent` n'appelle `apply_resource_transition` qu'une seule fois (pour `RIGHTS_CHECKED → QUALITY_CHECKED`) ; la `RoutingDecision` est retournée comme une valeur pure à l'appelant, jamais écrite dans `workflow_events`, jamais utilisée pour transitionner. Prouvé par test (`test_lot44d_quality_agent.py::TestRunQualityAgentNeverActivatesRouted`, unitaire) et par le test d'intégration PostgreSQL réel (`test_lot44d_chain_wiring.py`, qui vérifie `COUNT(*) FROM workflow_events WHERE to_state = 'ROUTED'` égal à zéro après un passage complet de la chaîne, y compris pour une `RoutingDecision` de type `DUPLICATE`).

Ce choix résout une ambiguïté relevée lors de la cartographie initiale de ce lot (aucun des huit stages nommés ne porte nativement `RoutingDecision`) sans introduire de neuvième composant hors périmètre : `QualityAgent` en porte le calcul, un lot ultérieur décidera explicitement s'il active la transition correspondante.

## Décision 4 — Tension de contrat documentée : `ArtifactRecord.rights_status` à l'étape `FETCHED`/`STORED`

`ArtifactRecord.rights_status: Rights` est un champ obligatoire du contrat LOT44a (frozen, non modifié), mais `Fetcher` (qui construit `ArtifactRecord`) s'exécute avant `RightsAgent` (qui détermine réellement les droits). `Fetcher` fixe donc `rights_status = Rights.unknown` à la construction — une valeur honnête (les droits ne sont, de fait, pas encore vérifiés), jamais une valeur optimiste. La détermination réelle par `RightsAgent` (`assess_rights_core`) est retournée comme une valeur séparée à l'appelant, jamais réinjectée dans l'`ArtifactRecord` déjà construit (le contrat ne porte pas de mutation) — c'est `QualityReport.rights_status` (calculé par `QualityAgent` à partir de la sortie de `RightsAgent`) qui porte la valeur définitive.

## Décision 5 — Heuristiques de qualité explicitement placeholders

`QualityAgent::build_quality_report_core` calcule `extraction_quality`, `readability`, `structure_score`, `topic_coverage`, `relevance_score`, `metadata_quality` par des heuristiques déterministes volontairement simples (longueur de texte bornée, nombre de phrases, fraction de sujets attendus effectivement trouvés, fraction de champs de métadonnées optionnels renseignés). **Ce ne sont pas des mesures de qualité pédagogique validées** — chaque fonction porte un avertissement explicite en docstring. `topic_coverage`/`relevance_score` mesurent une substance réelle (fraction de sujets *distincts* effectivement trouvés dans le texte, jamais la simple présence d'une référence générique), conformément à la clause « Qualité des métriques » d'AGENTS.md ; `extraction_quality`/`readability`/`structure_score` restent des placeholders assumés comme tels, à remplacer par un futur lot avant toute décision de production réelle.

## Décision 6 — Garde SSRF partagée pour Planner/Scout/Fetcher

Les trois stages qui manipulent une URL externe passent exclusivement par `ingestor.ssrf_guard.validate_destination`/`safe_fetch` (LOT43, D-7), injectées via `ingestion_agents.dependencies` avec l'implémentation réelle en valeur par défaut. `Planner` valide chaque `profile.seed_urls` avant de construire un `SearchPlan` (échec explicite, propagation de `SSRFValidationError`, jamais un retrait silencieux de l'URL fautive) ; `Scout` valide `source_url` avant de construire un `ResourceCandidate` ; `Fetcher` télécharge exclusivement via `safe_fetch` (revalidation à chaque redirection, taille bornée). Aucun `httpx`/`requests` direct sur une URL externe n'existe dans `ingestion_agents/`.

## Décision 7 — Aucun fallback, aucun contournement du gate LOT44c

Aucun stage ne sélectionne un profil par défaut, ne devine une « dernière version », ni ne contourne `select_profile`/`validate_scope_against_profile`/`enforce_production_manifest_gate` (LOT44c, non modifiés). Le test d'intégration réel charge le registre LOT44c depuis un répertoire temporaire (fixture `tmp_path`) et appelle réellement `validate_scope_against_profile` avant d'exécuter la chaîne — la validation LOT44c n'est jamais court-circuitée.

## Périmètre couvert

- Huit modules (`planner.py`, `scout.py`, `fetcher.py`, `extractor.py`, `classifier.py`, `rights_agent.py`, `quality_agent.py`, `coverage_agent.py`), un module de dépendances injectables (`dependencies.py`), un module de transitions (`transitions.py`).
- 49 tests unitaires sur fixtures (aucun réseau, aucun PostgreSQL réel) répartis sur huit fichiers `tests/test_lot44d_*.py` + `tests/test_lot44d_transitions.py`.
- 1 test d'intégration PostgreSQL réel (`tests/integration/test_lot44d_chain_wiring.py`) : chaîne complète Scout → Fetcher → Extractor → Classifier → RightsAgent → QualityAgent sur conteneur Docker jetable, prouvant le câblage réel aux primitives LOT44b et au moteur de validation LOT44c.

## Hors périmètre de LOT44d (réserves explicites, non traitées ici)

- Aucun scheduler, aucune boucle autonome, aucun worker CLI — LOT44d livre des fonctions appelables, jamais un processus qui tourne (réservé à LOT44e, ADR-0028).
- Aucune création de run/job/table `jobs` — `job_id` reste `NULL` sur tous les événements écrits par ce lot, prouvé par le test d'intégration.
- Aucun câblage à `/ingest/v2`, à un scheduler/worker, ni au gate `startup_gate.py` dans `api.py` — ces trois raccordements restent hors périmètre (LOT44e ou un mandat explicite pour toucher LOT43).
- Aucune activation de la transition `QUALITY_CHECKED → ROUTED` — décision calculée mais non appliquée (Décision 3).
- Aucun profil, manifest ou fingerprint de production créé — le registre LOT44c reste chargé exclusivement depuis des répertoires temporaires dans les tests de ce lot.
- Aucun modèle réel d'extraction (PDF/OCR), de classification de contenu, ou de détection PII — placeholders explicitement documentés (Décisions 4-5), à remplacer par un futur lot.
- Aucune table `ingestion_control.jobs`, aucune contrainte composite `run_id`/`resource_id` — dettes héritées de LOT44b/44c (ADR-0028), non rouvertes ni aggravées par ce lot.

## Verdicts LOT44c — republiés inchangés (non rouverts par ce lot)

```
LOT44C_BLOCKED_MISSING_APPROVED_PRODUCTION_PROFILE_MATRIX
LOT44C_BLOCKED
PRODUCTION_BLOCKED_NO_PRODUCTION_PROFILES
GATE_NOT_CONNECTED_TO_PRODUCTION_ENTRYPOINT
NOT_READY_FOR_PRODUCTION
```

La production reste strictement bloquée. LOT44d ne lève, ne contourne, ni ne rediscute aucun de ces verdicts.

## Conséquences

### Positives
- Aucune migration, aucun nouveau rôle PostgreSQL, aucune modification des schémas LOT44b/44c — surface de risque minimale.
- Chaque stage testable isolément, sans dépendance à un environnement réel — cœurs purs, dépendances injectées.
- Chaîne bout-en-bout prouvée sur PostgreSQL réel (conteneur jetable), pas seulement affirmée.

### Négatives
- Aucun des huit stages n'est raccordé à un processus réellement invocable en production — un futur lot (LOT44e) doit construire le scheduler/worker qui les appelle réellement.
- Les heuristiques de qualité/classification/droits restent des placeholders déterministes, pas des modèles validés — documenté explicitement, pas corrigé par ce lot.
- La tension de contrat sur `ArtifactRecord.rights_status` (Décision 4) reste un défaut de conception hérité de LOT44a (contrat gelé), contourné proprement mais non résolu structurellement.
