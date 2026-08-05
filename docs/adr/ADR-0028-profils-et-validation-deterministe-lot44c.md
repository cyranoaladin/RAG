# ADR-0028 — Profils canoniques et validation déterministe (LOT44c)

- **Statut** : Accepté
- **Date** : 2026-08-04
- **Décideur** : Alaeddine Ben Rhouma (Shark)
- **Découle de** : ADR-0001 (séparation plan de contrôle / plan de données / cockpit), ADR-0002 (contrat partagé `nexus-contracts` versionné), ADR-0026 (contrats canoniques d'ingestion, LOT44a), ADR-0027 (plan de contrôle PostgreSQL `ingestion_control`, LOT44b), ADR-0013 (convergence dual-engine — catalogue `rag_collections.yml`)
- **Chronologie réelle de ce document** : créé après la première passe d'implémentation de LOT44c (`registry.py`, `validation.py`, `events.py` et leurs tests existaient déjà), pour documenter les décisions déjà prises dans le code — jamais lu comme une entrée pré-existante avant ce code. Amendé une première fois lors d'une revue de clôture adversariale (identité de profil, empreinte, matrice de production, contrat d'interface LOT44d/LOT44e, dettes LOT44b). Amendé une seconde fois ici (détection de dérive cross-run, manifest de production, dette E2E `/ingest/v2`) après qu'une revue suivante a démontré que l'empreinte seule ne constituait pas une détection de dérive.

## Contexte

LOT44a a livré `CollectionProfile` (profil déclaratif complet d'une collection gouvernée) comme l'un des huit contrats canoniques, sans aucun mécanisme de chargement, de sélection ou de validation. LOT44b a construit le schéma PostgreSQL et les primitives de concurrence du plan de contrôle, sans persister ni valider aucun profil. LOT44c devait construire : le chargement déterministe des profils, leur sélection explicite, un moteur de validation déterministe scope/profil, et la persistance éventuelle des résultats — sans construire de moteur de stages, de scheduler, ni aucun comportement d'ingestion réel.

## Ce qu'est un « profil » dans ce lot

`CollectionProfile` (LOT44a, `nexus_contracts.ingestion`, **non modifié**) est l'unique et seul concept de profil de ce lot — vérifié en lisant ADR-0026 et le module lui-même avant tout code. Ce n'est ni un profil de source, ni un profil de traitement séparé : c'est le « profil déclaratif complet d'une collection gouvernée » déjà défini (scope, cadence de recherche, domaines autorisés, seuils qualité, politique de publication verrouillée). LOT44c ne crée donc **aucun nouveau contrat de profil** — seulement un registre, une sélection et un moteur de validation qui le consomment.

## Décision 1 — Identité d'un profil : `(scope.collection, profile_version)`, jamais un UUID inventé

`CollectionProfile` ne porte aucun champ `profile_id`/UUID — seulement `profile_version: str`. Ce n'est pas un oubli de LOT44a : `IngestionRun`, `SearchPlan` et `RoutingDecision` référencent déjà un profil exclusivement par `scope` + `profile_version` (jamais par un identifiant séparé), et LOT44b a délibérément laissé `ingestion_runs.profile_version` comme colonne texte libre sans table `collection_profiles` ni FK (ADR-0026 : « aucune table `collection_profiles`... n'est créée »).

**Décision** : l'identité d'un profil dans ce lot est la paire `(scope.collection, profile_version)` — deux types déjà canoniques (`CollectionName`, `str` contraint `min_length=1`), jamais un hash utilisé comme identifiant primaire, jamais un UUID ajouté artificiellement à `CollectionProfile` (qui resterait un contrat gelé).

### Réponses explicites aux neuf questions d'identité (revue de clôture)

1. **Existe-t-il un `profile_id` canonique ?** Non — vérifié par lecture directe de `CollectionProfile.model_fields` (`packages/contracts/src/nexus_contracts/ingestion.py:88-126`) : aucun champ de ce nom, aucun UUID.
2. **`(collection, profile_version)` est-il l'identifiant primaire autorisé ?** Oui, par déduction du seul motif déjà utilisé dans les contrats LOT44a existants (`IngestionRun.profile_version`, `SearchPlan.profile_version`, `RoutingDecision.profile_version` — aucun ne porte de `profile_id` séparé) : c'est une extension conforme, pas une invention.
3. **Est-il unique et stable ?** Unique : `load_profile_registry()` (`registry.py`) rejette toute paire dupliquée entre deux fichiers (`ProfileRegistryLoadError`, testé par `test_duplicate_collection_and_version_across_files_is_rejected` — y compris avec un contenu strictement identique dans les deux fichiers, prouvant que le rejet porte sur l'identité, pas sur une divergence de contenu accidentelle). Stable : oui pour `collection` (type `CollectionName`, motif `^[a-z0-9_]+$` déjà contraint par LOT44a) ; **non garanti pour `profile_version` avant cette clôture** — cf. point 4.
4. **La version possède-t-elle un format contrôlé ?** Le contrat LOT44a (`profile_version: str = Field(min_length=1)`) n'impose **aucun** format au-delà de la non-vacuité — une chaîne composée uniquement d'espaces, de sauts de ligne, ou de longueur arbitraire passait. **Lacune réelle corrigée pendant cette clôture** : `registry.py::PROFILE_VERSION_PATTERN` (`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`) est une contrainte **additionnelle, appliquée uniquement au chargement du registre LOT44c**, sans modifier le contrat gelé — testée (`TestProfileVersionFormat`, 4 tests : espace interne, chaîne uniquement blanche, longueur excessive, formes conventionnelles acceptées).
5. **Deux fichiers YAML différents peuvent-ils produire le même profil ?** Oui si leur contenu est identique — toléré et testé (`test_duplicate_collection_and_version_across_files_is_rejected` utilise deux fichiers de contenu identique) : le rejet porte sur la clé, jamais sur la comparaison de contenu, par choix fail-closed (une identité dupliquée est toujours une erreur de configuration à corriger, que le contenu diverge ou non).
6. **Deux profils différents peuvent-ils produire la même identité ?** Non — même mécanisme de rejet que le point précédent, la clé est vérifiée avant toute comparaison de contenu.
7. **L'empreinte du contenu est-elle distincte de l'identité ?** **Lacune réelle corrigée pendant cette clôture** : avant cette passe, aucune empreinte n'existait — seule l'identité `(collection, profile_version)` était calculée, aucune fonction ne résumait le contenu. Ajout de `registry.py::profile_fingerprint()` (SHA-256 déterministe, sérialisation canonique `json.dumps(model_dump(mode="json"), sort_keys=True)`), propagée dans `ValidationResult.profile_fingerprint` et persistée par `record_validation_result`. Testé : déterminisme (même contenu → même empreinte), indépendance de l'ordre des clés YAML, divergence pour deux contenus différents.
8. **Une modification d'un profil déjà utilisé est-elle impossible ou détectée ?** **Ni l'un ni l'autre avant cette clôture, et seulement partiellement après** : rien n'empêche techniquement d'éditer un fichier YAML déjà référencé (aucun verrou de fichier, aucun registre de versions publiées côté LOT44c) — prouvé explicitement par `test_editing_a_profile_file_in_place_changes_its_fingerprint`, qui démontre qu'une édition change l'empreinte mais n'est bloquée par rien au chargement. Ce que cette clôture ajoute est une **primitive habilitante** de détection a posteriori : deux résultats de validation persistés pour la même identité mais avec une empreinte différente prouvent qu'une modification a eu lieu entre les deux. **Aucune comparaison automatique de ce type n'est effectuée par LOT44c** — c'est un gate explicite laissé à un futur lot (cf. section « Gates obligatoires avant production »).
9. **Le profil chargé peut-il être relié sans ambiguïté à un résultat de validation ultérieur ?** Oui : `ValidationResult` porte `collection`, `profile_version` et `profile_fingerprint` ; `record_validation_result` persiste les trois dans `payload` (JSONB, `workflow_events`).

Un profil déjà référencé n'est donc jamais modifié **silencieusement en un sens comportemental fort** (la dérive reste détectable a posteriori via l'empreinte persistée) mais reste **techniquement modifiable sans blocage immédiat** au chargement — reformulé ici par honnêteté : la version initiale de ce lot affirmait à tort une garantie plus forte que celle réellement implémentée avant cette clôture.

## Décision 2 — Profils déclaratifs, aucune persistance PostgreSQL

`CollectionProfile` reste une **déclaration statique**, jamais persistée en base — ni par LOT44b (constat explicite d'ADR-0026/ADR-0027), ni par ce lot. Le repository possède déjà un motif directement analogue : `services/rag-engine/configs/rag_collections.yml` + `services/rag-engine/src/ingestor/collection_config.py` (ADR-0013), un catalogue YAML avec résolveur Python, variable d'environnement de override, erreurs typées explicites (`CollectionUnknownError`, `CollectionNotInstanciatedError`), aucune correspondance floue.

**Décision** : LOT44c reproduit ce motif pour `CollectionProfile`, sous un nom distinct pour éviter toute confusion avec le catalogue de collections existant (qui gouverne le routage physique pgvector/Chroma, un concept différent) :
- `services/rag-engine/src/ingestor/ingestion_profiles/registry.py` — chargeur YAML, répertoire résolu par `RAG_ENGINE_INGESTION_PROFILES_DIR` ou `configs/ingestion_profiles/` par défaut ;
- aucune table `collection_profiles`, aucune migration ajoutée ;
- **aucun fichier de profil de production n'est livré par ce lot** (cf. section « Hors périmètre »).

Un répertoire absent produit un registre vide (pas une erreur — aucun profil n'est encore déclaré, c'est l'état attendu de ce lot). Un fichier structurellement invalide (ne valide pas `CollectionProfile`) fait échouer le chargement entier plutôt que de retourner un registre partiel. Deux fichiers déclarant la même clé `(collection, profile_version)` sont rejetés explicitement au chargement (fail-closed, jamais « le dernier fichier gagne »).

## Décision 3 — Sélection : `(collection, profile_version)` toujours explicites, jamais de version implicite

Aucune règle canonique de « dernière version » ou de « profil par défaut » n'existe dans LOT44a ou LOT44b. Plutôt que d'en inventer une (risque explicitement signalé par la consigne de ce lot), `select_profile()` exige les deux paramètres — `collection` et `profile_version` — sans valeur par défaut : un appel omettant l'un des deux est une erreur Python (`TypeError`), jamais une inférence silencieuse. Un profil inconnu (`ProfileUnknownError`) et un profil désactivé (`enabled=False`, `ProfileDisabledError`) sont deux rejets explicites et distincts.

## Décision 4 — Moteur de validation : structurel (scope vs profil), pas de statut inventé hors nécessité

Le moteur (`ingestion_profiles/validation.py`) est une fonction pure : reçoit un scope brut (`Mapping[str, object]`), un registre, et une paire `(collection, profile_version)` ; ne fait ni réseau, ni I/O, ni horloge. Il :
1. sélectionne le profil (`profile_unknown`/`profile_disabled` si rejeté) ;
2. construit `ResourceScope.model_validate(raw_scope)` — toute erreur Pydantic (champ manquant, valeur vide, valeur d'enum inconnue) devient `incomplete_input` avec une liste structurée de `ValidationIssue(code, path, message)`, jamais seulement un texte libre ;
3. compare les dix dimensions du scope construit à `profile.scope`, dans l'ordre canonique de déclaration (`SCOPE_DIMENSIONS`) — toute divergence produit `failed` avec un `ValidationIssue` par dimension divergente (`SCOPE_DIMENSION_MISMATCH`) ;
4. sinon `passed`.

Aucun réseau, aucune horloge, aucun état global mutable, testé déterministe par appels répétés à entrée identique.

**Statuts retenus** : `passed`, `failed`, `profile_unknown`, `profile_disabled`, `incomplete_input`, `technical_error`. **`review_required`** (concept existant : `ResourceState.NEEDS_REVIEW`) est **volontairement absent** de cette liste : cette comparaison structurelle n'a aucune zone grise — soit le scope correspond exactement au profil, soit non — l'ajouter sans cas d'usage réel aurait été inventer un statut sans nécessité, ce que la consigne de ce lot demande explicitement d'éviter. **`profile_invalid`** est également absent comme statut produit par le moteur : la validité structurelle d'un profil est garantie **au chargement du registre** (`ProfileRegistryLoadError`, fail-closed), donc un profil atteignant le moteur de validation est par construction déjà valide — un `CollectionProfile` structurellement invalide ne peut jamais y parvenir.

`technical_error` encapsule toute exception inattendue à la frontière publique (`validate_scope_against_profile`) — la fonction ne laisse jamais fuir d'exception non gérée.

Vérifié explicitement (`test_lot44c_validation_engine.py::TestNoPublishedNoStateConflict`) : aucun de ces six statuts ne collisionne avec les vingt valeurs de `ResourceState`, `PUBLISHED` absent.

## Décision 5 — Persistance éventuelle : réutilisation de `workflow_events`, aucune nouvelle migration

Les résultats de validation sont rattachables à `run_id`/`resource_id` (colonnes déjà présentes sur `ingestion_control.workflow_events`, LOT44b, migration 003, **non modifiée**). `candidate_id`/`artifact_id` — quand l'appelant les fournit — sont portés dans le `payload` JSONB, jamais ajoutés comme colonne (la migration 003 est gelée). `event_type = 'profile_validation'` : une valeur libre parmi d'autres, la colonne ne porte aucune contrainte `CHECK` sur son contenu.

**Aucune migration n'est créée** par ce lot : `workflow_events` porte déjà tout ce qui est nécessaire (`run_id`, `job_id` nullable, `resource_id` nullable, `event_type`, `payload` JSONB, `actor`, `idempotency_key` nullable avec unicité partielle). `record_validation_result()` (`ingestion_profiles/events.py`) :
- ne renseigne jamais `job_id` (reste `NULL`, cohérent avec ADR-0027 : aucun producteur automatique en dehors d'un futur contrat `IngestionJob`) ;
- ne renseigne jamais `from_state`/`to_state` (cet événement n'est pas une transition de `resource_state` — aucun appel à `cas_transition` n'est effectué par ce lot, aucune transition automatique n'est déclenchée) ;
- ne fournit `idempotency_key` que si l'appelant le demande explicitement (même convention que `cas_transition`, LOT44b) — **contrat B, jamais appelé « idempotence » sans précision** (cf. sous-section dédiée ci-dessous) ;
- rejette explicitement (`PayloadTooLargeError`) tout payload dont la sérialisation JSON dépasse `MAX_PAYLOAD_BYTES` (256 Kio) — un plafond réel et testé, jamais seulement un nombre de champs supposé petit ;
- ne committe jamais la transaction (responsabilité de l'appelant, même convention que les quatre primitives LOT44b).

### Contrat exact de `idempotency_key` : détection de doublon (contrat B), pas une idempotence complète (contrat A)

Une revue de clôture a objecté à juste titre que présenter `UniqueViolation` comme « l'idempotence » sans préciser le contrat était trompeur. Choix explicite et définitif : **contrat B — détection de doublon, la répétition échoue**, jamais **contrat A — la répétition renvoie le résultat déjà enregistré**. `record_validation_result` ne relit jamais la ligne existante en cas de conflit ; elle laisse `UniqueViolation` remonter à l'appelant.

L'index unique partiel réutilisé (LOT44b, migration 003, non modifié) porte sur la colonne `idempotency_key` **seule** — jamais sur une combinaison avec `run_id`/`resource_id`. Cinq scénarios prouvés (PostgreSQL réel, `TestDuplicateDetectionKeyContractB`) :

| Scénario | Comportement | Test |
|---|---|---|
| Même clé + même payload | Échec (`UniqueViolation`) | `test_same_key_same_payload_fails_on_repeat` |
| Même clé + payload différent | Échec identique — le contenu n'est jamais comparé | `test_same_key_different_payload_fails_identically` |
| Aucune clé | Jamais de conflit, un nouvel événement à chaque appel | `test_no_key_never_conflicts` |
| Même clé, `run_id` différent | Échec — l'unicité ne porte pas sur `(idempotency_key, run_id)` | `test_same_key_different_run_id_still_fails` |
| Même clé, `resource_id` différent | Échec — l'unicité ne porte pas sur `(idempotency_key, resource_id)` | `test_same_key_different_resource_id_still_fails` |

**Réserve technique conservée** : ce contrat B ne protège qu'à la reprise stricte (même clé) ; il n'offre aucune garantie de reprise idempotente au sens fort (retourner le résultat déjà connu). Si un futur appelant a besoin du contrat A, cela nécessitera une primitive dédiée (par ex. `SELECT ... WHERE idempotency_key = %s` avant insertion, ou `INSERT ... ON CONFLICT DO NOTHING RETURNING`), hors périmètre de ce lot.

**Contrat exact du payload** (`event_contract_version = "1"`, porté dans le payload lui-même — `workflow_events` reste générique, aucun schéma SQL dédié) :
```json
{
  "kind": "profile_validation",
  "event_contract_version": "1",
  "status": "passed | failed | profile_unknown | profile_disabled | incomplete_input | technical_error",
  "collection": "<str>",
  "profile_version": "<str>",
  "profile_fingerprint": "<sha256 hex ou null>",
  "issues": [{"code": "<str>", "path": "<str>", "message": "<str>"}],
  "candidate_id": "<uuid str, présent uniquement si fourni>",
  "artifact_id": "<uuid str, présent uniquement si fourni>"
}
```
Champs **obligatoires** (toujours présents, testé — `test_payload_contract_mandatory_fields_always_present_optional_fields_absent`) : `kind`, `event_contract_version`, `status`, `collection`, `profile_version`, `profile_fingerprint` (valeur `null` possible, clé toujours présente), `issues` (liste vide possible, clé toujours présente). Champs **optionnels** (absents de l'objet, pas seulement `null`, quand non fournis) : `candidate_id`, `artifact_id`. `run_id`/`resource_id`/`actor`/`occurred_at`/`idempotency_key` sont portés par les colonnes SQL de `workflow_events`, pas par le payload (`occurred_at = now()`, horodatage serveur PostgreSQL — jamais fourni par l'appelant, jamais falsifiable côté client ; `actor` = provenance, chaîne libre fournie par l'appelant).

**Taille maximale** : `MAX_PAYLOAD_BYTES = 262 144` (256 Kio), vérifiée par sérialisation JSON avant toute tentative d'`INSERT` — testé avec un payload artificiellement surdimensionné (`test_oversized_payload_is_rejected_before_insertion`, `PayloadTooLargeError`) et un payload ordinaire (`test_ordinary_payload_is_well_within_the_limit`). Ce n'est pas une estimation théorique du nombre de champs : c'est une vérification réelle de la taille sérialisée, appliquée à chaque appel.

**Sérialisation réellement canonique** — corrigée pendant cette clôture (la version précédente utilisait `json.dumps(payload)` sans paramètres explicites : déterministe par accident de l'ordre d'insertion du `dict`, mais pas canonique au sens strict). `events.py::canonical_json_bytes()` fixe explicitement :
- `sort_keys=True` — ordre des clés indépendant de l'ordre de construction du payload ;
- `ensure_ascii=True` — tout caractère non-ASCII échappé, taille indépendante de la locale ;
- `separators=(",", ":")` — aucun espace superflu, taille minimale réelle ;
- `allow_nan=False` — `NaN`/`Infinity` rejetés explicitement (`ValueError`) plutôt que sérialisés en JSON non standard.

Testé (`TestCanonicalJsonBytes`, 6 tests) : indépendance de l'ordre des clés, absence d'espaces superflus, échappement non-ASCII, rejet de `NaN`/`Infinity`, déterminisme entre appels répétés.

**Distinction taille mesurée / représentation JSONB stockée** : `canonical_json_bytes()` mesure la taille du flux JSON textuel envoyé à PostgreSQL ; `psycopg.types.json.Jsonb` délègue ensuite à PostgreSQL la normalisation binaire JSONB effective à l'écriture (réordonnancement/compaction interne par PostgreSQL lui-même). La taille mesurée côté application est une approximation sûre pour ce type de contenu majoritairement scalaire — pas une garantie bit-à-bit de la taille de la ligne stockée en base.

**Réserve non fermée, avec responsable explicite** : cette limite n'est appliquée que par `record_validation_result` — aucune contrainte SQL équivalente n'existe sur `workflow_events` (migration 003, gelée). Un futur code insérant directement dans la table par SQL brut contournerait la limite. **Lot responsable** : non assigné à ce jour, à traiter par le même lot que la dette « bootstrap sans fingerprint colonne-par-colonne » (durcissement du schéma `ingestion_control`) si un besoin réel de défense en profondeur au niveau SQL est démontré. **Condition d'acceptation** : une contrainte `CHECK (pg_column_size(payload) <= <limite>)` sur `workflow_events`, ou un trigger équivalent. **Test d'acceptation** : une tentative d'`INSERT` SQL brut avec un payload surdimensionné doit échouer au niveau de la base, pas seulement au niveau applicatif. **Gate de production** : ne bloque pas la production tant que `record_validation_result` reste le seul chemin d'écriture réel (aucun autre code n'écrit sur `event_type = 'profile_validation'`) — devient bloquant si un futur lot introduit un second chemin d'écriture sans réutiliser cette fonction.

Testé avec de vraies connexions PostgreSQL indépendantes (conteneur Docker jetable, mêmes scripts `bootstrap_ingestion_control_schema.sh`/`provision_ingestion_control_roles.sh` que LOT44b, **non modifiés**) : insertion réussie avec le rôle `ingestion_control_app`, non-commit vérifié par un test de rollback, `UPDATE` rejeté par `InsufficientPrivilege` (append-only réel, hérité de LOT44b), violation de clé étrangère sur un `run_id` inexistant.

**Contrat exact du payload** (`event_contract_version = "1"`, porté dans le payload lui-même — `workflow_events` reste générique, aucun schéma SQL dédié) :
```json
{
  "kind": "profile_validation",
  "event_contract_version": "1",
  "status": "passed | failed | profile_unknown | profile_disabled | incomplete_input | technical_error",
  "collection": "<str>",
  "profile_version": "<str>",
  "profile_fingerprint": "<sha256 hex ou null>",
  "issues": [{"code": "<str>", "path": "<str>", "message": "<str>"}],
  "candidate_id": "<uuid str, si fourni>",
  "artifact_id": "<uuid str, si fourni>"
}
```
`run_id`/`resource_id`/`actor`/`occurred_at`/`idempotency_key` sont portés par les colonnes SQL de `workflow_events`, pas par le payload (`occurred_at = now()`, horodatage serveur PostgreSQL — jamais fourni par l'appelant, jamais falsifiable côté client ; `actor` = provenance, chaîne libre fournie par l'appelant).

## Décision 6 — Détection de dérive cross-run : primitive de comparaison réelle, pas seulement une empreinte

Une revue de clôture a objecté à juste titre qu'« une simple primitive de calcul SHA-256 ne constitue pas une détection de dérive ». Correction apportée : `ingestion_profiles/events.py::detect_profile_drift()` — lecture seule (`SELECT`), aucune écriture, aucune primitive de concurrence LOT44b requise — interroge le dernier `profile_fingerprint` persisté pour une identité `(collection, profile_version)` donnée et le compare à l'empreinte courante. Trois issues distinctes et testées (PostgreSQL réel) :
- **aucun historique** (`has_history=False`) : première validation connue pour cette identité, jamais traitée comme une dérive ;
- **empreinte identique** : `drift_detected=False` ;
- **empreinte différente** : `drift_detected=True` — le contenu a changé sous la même identité, ce qui contredit la convention « toute nouvelle définition porte une nouvelle version ».

Cette fonction **constate**, elle ne bloque ni n'alerte elle-même — la réaction (log, alerte, rejet) reste à la charge d'un futur appelant (LOT44d+), cohérent avec le principe de ce lot : une primitive contrôlée, jamais un comportement autonome.

### Ordre déterministe : `ORDER BY occurred_at DESC, event_id DESC`

Une seconde revue de clôture a exigé un tie-breaker immuable, faute de quoi la dette ne pouvait être déclarée fermée. Ajouté : `event_id` (UUID `gen_random_uuid()` à l'insertion, jamais `NULL`) comme second critère de tri. Précision exacte de ce que cela garantit et de ce que cela ne garantit pas :
- **Garanti** : la requête devient **reproductible** — deux appels successifs sur les mêmes données renvoient toujours la même ligne (prouvé, `test_same_transaction_inserts_share_occurred_at_but_query_is_reproducible`, deux appels comparés par égalité stricte du résultat).
- **Non garanti** : `event_id` n'est pas corrélé à l'ordre d'écriture réel — quand deux événements partagent strictement le même `occurred_at` (PostgreSQL `now()` = début de transaction, constant pour toute la transaction), le départage par `event_id` ne restaure aucun ordre chronologique véritable entre les deux. C'est un tie-breaker **immuable et déterministe**, pas un tie-breaker **chronologiquement significatif**. Seule une colonne de séquence sur `workflow_events` (migration 003 gelée, hors périmètre LOT44c) résoudrait la seconde moitié du problème.
- **Événement courant exclu explicitement** : `exclude_event_id` (nouveau paramètre) permet à un appelant d'exclure l'événement qu'il vient d'insérer lui-même. Sans ce paramètre, appeler `detect_profile_drift` *après* `record_validation_result` pour la même identité comparerait l'empreinte à elle-même et renverrait toujours `drift_detected=False` de façon triviale — prouvé (`test_exclude_event_id_prevents_comparing_the_current_event_to_itself`, qui démontre le piège puis sa correction). Convention recommandée : appeler `detect_profile_drift` **avant** `record_validation_result`.
- **Événements sans empreinte** (`profile_unknown`/`profile_disabled`/`technical_error`) : exclus par construction (`WHERE payload->>'profile_fingerprint' IS NOT NULL`), la comparaison remonte au dernier événement qui en portait réellement une — prouvé (`test_events_without_fingerprint_are_skipped_by_drift_check`).
- **Écritures concurrentes** : deux `record_validation_result` concurrents sans clé de doublon partagée créent deux lignes indépendantes (`INSERT` nativement sûr sous concurrence PostgreSQL) ; l'isolation de transaction standard s'applique — une transaction non commitée reste invisible aux lectures concurrentes.

**Coût de requête** : filtrage sur des champs JSONB non indexés (`payload->>'collection'`, `payload->>'profile_version'`) — un scan séquentiel de `workflow_events` à chaque appel. Acceptable au volume actuel (zéro donnée de production, cf. matrice ci-dessous) ; un index fonctionnel dédié serait à évaluer par un futur lot si le volume d'événements le justifie — pas ajouté ici pour éviter une migration non justifiée par un besoin réel mesuré.

**Statut de la dette** : la requête est désormais déterministe et reproductible (tie-breaker immuable, testé). La composante « ordre chronologique réel en cas d'égalité stricte de timestamp » reste ouverte — non fermable sans modifier un schéma gelé — et n'est **pas** présentée comme close.

## Décision 7 — Manifest de profils de production : mécanisme livré, aucun profil livré

Le registre (`load_profile_registry`) accepte silencieusement tout fichier présent dans son répertoire — utile pour le développement, insuffisant pour garantir qu'un déploiement de production charge *exactement* l'ensemble voulu de profils, avec le contenu exact attendu. `ingestion_profiles/manifest.py::verify_profile_manifest()` ferme ce mécanisme technique, sans fabriquer aucun profil réel :
- déclaration explicite (YAML, `manifest_version`, `provenance`, `generated_at`, `profiles: [{collection, profile_version, fingerprint}, ...]`), versionnée dans le dépôt ;
- **`manifest_version`** : seule la valeur `SUPPORTED_MANIFEST_VERSION` (`"1"`) est acceptée — un format non reconnu est rejeté explicitement, jamais interprété de façon optimiste ;
- **`provenance`**/**`generated_at`** : obligatoires et non vides — traçabilité de l'origine et de la date du manifest, un manifest anonyme ou non daté est refusé ;
- **`fingerprint` par entrée** (corrigé pendant cette passe — absent de la version initiale) : chaque entrée déclare l'empreinte SHA-256 exacte attendue du profil ; `verify_profile_manifest` la compare à `profile_fingerprint()` du profil réellement chargé et échoue explicitement (`ProfileManifestError`, message « Fingerprint mismatch ») en cas de divergence — ferme la dette « détection de dérive » au niveau du manifest lui-même, pas seulement via `detect_profile_drift` (comparaison cross-run, Décision 6) ;
- égalité d'ensembles **stricte** entre les identités déclarées par le manifest et celles réellement chargées par le registre — un profil manquant **ou** un profil surnuméraire fait échouer la vérification ;
- manifest absent, vide, malformé, ou contenant une entrée dupliquée/incomplète/à empreinte malformée (format non 64 caractères hexadécimaux) : échec explicite, jamais une approximation ;
- `manifest_fingerprint()` : empreinte SHA-256 déterministe du manifest lui-même (sérialisation canonique, indépendante de l'ordre des clés) ;
- aucun chemin de manifest par défaut (`manifest_path` est un paramètre positionnel obligatoire, testé) ; aucune sélection « la version la plus récente convient » (testé : un manifest déclarant `v1` alors que seul `v2` est chargé échoue, jamais une tolérance implicite).

Testé par 34 tests (`test_lot44c_profile_manifest.py`), incluant un scénario réaliste de dérive (`test_profile_edited_after_manifest_written_is_caught` : manifest écrit, profil modifié ensuite sans mise à jour du manifest, dérive détectée au chargement suivant).

## Décision 8 — Gate de démarrage : mécanisme complet, non câblé au processus de production réel

`ingestion_profiles/startup_gate.py::enforce_production_manifest_gate()` combine `load_profile_registry` et `verify_profile_manifest` en un seul appel bloquant, **sans aucun paramètre de contournement** (signature limitée à `profiles_dir`/`manifest_path`, testé) :
- échoue explicitement (exception non interceptée, jamais une valeur de repli) si : le manifest est absent, un profil déclaré est absent du registre, le registre est vide (le manifest ne pouvant jamais être vide, un répertoire de profils vide échoue nécessairement), une empreinte a dérivé, une version est inconnue, ou un fichier profil est structurellement invalide (propagation de `ProfileRegistryLoadError` sans interception) ;
- ne renvoie un `StartupGateResult` que dans le cas strictement cohérent, démontré par une paire de tests positif/négatif sur le même répertoire (`test_startup_authorized_only_with_consistent_manifest`).

**Point d'entrée CLI autonome** (`python -m ingestor.ingestion_profiles.startup_gate <profiles_dir> <manifest_path>`) — code de sortie non nul en cas d'échec, testé à la fois via appel direct de `_main()` (3 tests) et via une invocation réelle en sous-processus (démonstration manuelle, profils/manifest de test placés hors dépôt, jamais commités) : `STARTUP_GATE_FAILED`/exit 1 sur manifest vide, `STARTUP_GATE_PASSED`/exit 0 sur manifest cohérent avec un profil de test valide.

**Réserve explicite et assumée, non fermée par ce lot** : ce mécanisme **n'est câblé dans aucun processus réellement déployé en production**. Le processus de production réel de `rag-engine` est l'application FastAPI **`src/ingestor/api.py`** (objet `app`, servie par `uvicorn api:app`, cf. `infra/Dockerfile.ingestor-v2` et le service `ingestor` de `infra/docker-compose.v2.yml`, LOT43) — **correction apportée ici** : une rédaction précédente de cette section désignait à tort `src/ingestor/app_v2.py`, un chemin qui n'existe pas dans le dépôt (vérifié par recherche directe) ; `src/ui/app_v2.py` est un tableau de bord Streamlit distinct qui consomme l'API, pas le moteur de production lui-même. Ajouter l'appel à `enforce_production_manifest_gate()` dans `api.py` nécessiterait de modifier un fichier d'un lot antérieur, explicitement exclu de cette passe (« ne modifie aucun lot antérieur »). Le point d'entrée CLI livré ici est directement utilisable comme étape de pré-démarrage ou de healthcheck dans un pipeline de déploiement (ex. `CMD`/`ENTRYPOINT` Docker, étape CI/CD) sans toucher à aucun fichier LOT43/44a/44b, mais son câblage effectif dans `api.py` reste une décision et une action de LOT44e (ou d'un mandat explicite pour toucher LOT43). Tant que ce câblage n'existe pas, **`enforce_production_manifest_gate` reste une primitive complète et testée, mais pas une gate active en production** — cohérent avec `PRODUCTION_BLOCKED_NO_PRODUCTION_PROFILES`.

**Défaut mineur connu, non bloquant** : l'invocation `python -m ingestor.ingestion_profiles.startup_gate` émet un `RuntimeWarning` Python bénin (le paquet `ingestion_profiles/__init__.py` importe déjà `startup_gate` avant que `runpy` ne l'exécute comme `__main__`) — n'affecte ni le code de sortie ni le comportement, simple bruit sur stderr.

## États et transitions

Ce lot ne crée aucune seconde machine d'état, ne modifie ni n'étend `ResourceState` (LOT44a), ne déclenche aucune transition. `PUBLISHED` reste absent — vérifié par recherche exhaustive et par test dédié. `REVIEWED` et `RETRIEVAL_ELIGIBLE` restent des états `ResourceState` distincts, jamais confondus avec un statut `ValidationResult` (deux types disjoints, vérifié par test).

## Matrice — profils de production

| Élément | État | Preuve | Bloquant production |
|---|---|---|---|
| Schéma de profil | Présent | `CollectionProfile`, `packages/contracts/src/nexus_contracts/ingestion.py:88-126` (LOT44a, gelé) | Non |
| Registre (chargeur + sélection) | Présent | `services/rag-engine/src/ingestor/ingestion_profiles/registry.py` | Non |
| Profils réellement fournis | **Absents** | `services/rag-engine/configs/ingestion_profiles/` n'existe pas dans le dépôt ; aucun fichier YAML livré par ce lot (décision de gouvernance, pas une limite technique) | **Oui** |
| Validation du registre au chargement | Présente pour la structure et le format d'identité | `TestLoadProfileRegistry`, `TestProfileVersionFormat` (`test_lot44c_profile_registry.py`) | Non pour ce qui est couvert ; ne couvre jamais la substance pédagogique d'un profil (domaines réellement pertinents, seuils réellement justifiés) — hors portée d'un contrôle automatique |
| Manifest de production (liste versionnée des profils actifs attendus, empreinte par profil, provenance, date) | **Mécanisme complet présent (empreinte incluse), aucun manifest réel livré** | `ingestion_profiles/manifest.py::verify_profile_manifest`, `manifest_fingerprint` — testés (`test_lot44c_profile_manifest.py`, 34 tests, dont vérification d'empreinte par entrée) ; aucun fichier manifest réel dans le dépôt | **Oui** — le mécanisme existe et vérifie désormais l'empreinte, mais aucun manifest réel n'a de raison d'exister sans profils réels |
| Empreinte des profils + comparaison cross-run | Primitive **et** comparaison réelle présentes, à deux niveaux | `registry.py::profile_fingerprint` (calcul), `manifest.py::verify_profile_manifest` (comparaison manifest ↔ profil chargé, locale, sans DB), `events.py::detect_profile_drift` (comparaison contre l'historique persisté, PostgreSQL réel, 6 tests) | Non pour les primitives elles-mêmes |
| Contrôle de compatibilité au démarrage d'un processus | **Mécanisme complet présent, non câblé au processus de production réel** | `startup_gate.py::enforce_production_manifest_gate` (aucun paramètre de contournement, testé) + point d'entrée CLI autonome (`python -m ingestor.ingestion_profiles.startup_gate`, testé par appel direct et par sous-processus réel) | **Oui** — le câblage dans le processus FastAPI réel (LOT43) est hors périmètre de cette passe (« ne modifie aucun lot antérieur ») ; revient à LOT44e ou à un mandat explicite |

**Conséquence explicite** : `PRODUCTION_BLOCKED_NO_PRODUCTION_PROFILES`. Cette absence n'est masquée par aucun profil de démonstration, aucun profil par défaut, aucun fallback — vérifié : zéro fichier sous `configs/ingestion_profiles/` dans ce lot.

## Isolation et scope — formulation sans ambiguïté

Le système **n'est pas multi-tenant** au sens plein du terme. `tenant` est un champ **contractuel** (dimension de `ResourceScope`, obligatoire, fail-closed à la construction) mais **opérationnellement limité à une seule valeur par déploiement** — limitation héritée d'ADR-0027 (elle-même héritée de LOT43 §43.4, `NEXUS_DEFAULT_TENANT`), ni levée ni renforcée par LOT44c.

- `UNIQUE(collection, dedup_key)` (LOT44b, migration 001) **peut** provoquer une collision entre deux tenants différents si l'hypothèse « une valeur par dimension par déploiement » est violée — documenté et testé dès LOT44b (`test_dedup_key_collision_across_different_scope_is_documented_not_fixed`), non modifié ici.
- L'hypothèse de déploiement qui rend cette contrainte acceptable : un seul tenant actif à la fois par instance déployée — jamais deux tenants simultanément servis par la même base `ingestion_control`.
- **Aucune protection applicative n'empêche un mélange de tenants** si cette hypothèse de déploiement est violée par erreur opérationnelle (ex. deux équipes pointant vers la même base avec des valeurs `tenant` différentes) — ni en LOT44b, ni en LOT44c.
- Comportement en cas de tenant incohérent avec un profil sélectionné : **fail-closed**, vérifié explicitement pendant cette clôture (`test_tenant_mismatch_is_rejected_like_any_other_dimension`) — `tenant` est comparé exactement comme les neuf autres dimensions, sans traitement spécial, sans bypass.

Cette architecture ne doit **jamais** être présentée comme une isolation multi-tenant complète. C'est une limitation à un seul tenant actif par déploiement, avec un champ contractuel prêt pour une future extension, mais sans aucune barrière technique multi-tenant réelle.

## Contrat d'interface pour LOT44d et LOT44e

Sans implémenter ni stages, ni scheduler, ni workers, ce lot documente l'interface que ces lots futurs doivent respecter :

**Chaîne complète visée (non implémentée au-delà de LOT44c)** :
`création run → création job → claim PostgreSQL (LOT44b::claim_resource) → récupération ressource → sélection explicite du profil (LOT44c::select_profile) → validation (LOT44c::validate_scope_against_profile) → persistance du résultat (LOT44c::record_validation_result) → décision de retry (LOT44b::record_retry) ou de revue → cas_transition (LOT44b) → suite`

- **Entrée minimale du moteur** : `raw_scope: Mapping[str, object]`, `registry: ProfileRegistry` (déjà chargé par l'appelant — LOT44c ne décide jamais quand recharger), `collection: str`, `profile_version: str` — tous obligatoires, aucune valeur implicite.
- **Objet de sortie** : `ValidationResult(status, issues, collection, profile_version, profile_fingerprint)` — immuable (`frozen=True`), sérialisable en JSON via les champs de `record_validation_result`.
- **Statuts de sortie** : `passed | failed | profile_unknown | profile_disabled | incomplete_input | technical_error` (`ValidationStatus`, `validation.py`).
- **Codes d'erreur stables** : `PROFILE_UNKNOWN`, `PROFILE_DISABLED`, `SCOPE_FIELD_MISSING`, `SCOPE_FIELD_EMPTY`, `SCOPE_FIELD_INVALID`, `SCOPE_DIMENSION_MISMATCH`, `VALIDATION_ENGINE_ERROR` — portés par `ValidationIssue.code`, jamais seulement par un texte libre.
- **Comportement retryable** : `technical_error` est le seul statut qu'un futur appelant devrait raisonnablement retenter (erreur inattendue, potentiellement transitoire) ; `incomplete_input`/`failed`/`profile_unknown`/`profile_disabled` sont des rejets **définitifs** pour l'entrée fournie — retenter avec la même entrée produit toujours le même résultat (déterminisme prouvé par `TestDeterminism`).
- **Comportement non-retryable** : tous les statuts sauf `technical_error`, ci-dessus.
- **Rattachement au run/à la ressource** : `record_validation_result(run_id, resource_id=None, candidate_id=None, artifact_id=None, ...)` — `run_id` obligatoire (FK réelle vers `ingestion_runs`), le reste optionnel selon le niveau de granularité de l'appelant.
- **Profil et version utilisés** : toujours portés par `result.collection`/`result.profile_version`/`result.profile_fingerprint`, jamais à reconstruire séparément par l'appelant.
- **Événement écrit** : `ingestion_control.workflow_events`, `event_type = 'profile_validation'` (constante `PROFILE_VALIDATION_EVENT_TYPE`), `from_state`/`to_state` toujours `NULL`.
- **État `ResourceState` éventuellement observé** : **aucun** — LOT44c ne lit ni n'écrit jamais `resources.resource_state`. Un futur appelant qui souhaite faire progresser une ressource après un `passed` doit appeler `cas_transition` (LOT44b) **séparément et explicitement**, jamais automatiquement depuis ce moteur.
- **Absence de transition implicite** : garanti par construction — `record_validation_result` n'appelle jamais `cas_transition`, ne renseigne jamais `job_id` (reste `NULL`), vérifié par test (`TestIdentifiersAreUuidWhereExpectedByEvents::test_record_validation_result_never_accepts_job_id`).
- **Comportement lorsqu'aucun profil de production n'est disponible** : `load_profile_registry()` retourne un registre vide (pas une erreur) ; tout appel à `select_profile`/`validate_scope_against_profile` avec une collection non déclarée retourne `profile_unknown` — un futur worker (LOT44e) doit traiter ce statut comme un blocage **métier**, pas une erreur technique à retenter.

**Requête de lecture déterministe pour un futur worker (LOT44e)** — « quel est le dernier résultat de validation pour une ressource » :
```sql
SELECT payload FROM ingestion_control.workflow_events
WHERE resource_id = %s AND event_type = 'profile_validation'
ORDER BY occurred_at DESC, event_id DESC
LIMIT 1
```
Le second critère (`event_id DESC`) rend cette requête reproductible en cas d'égalité de `occurred_at` (même raisonnement que `detect_profile_drift`, cf. Décision 6) — sans lui, deux exécutions de la même requête sur les mêmes données ne sont pas garanties de renvoyer la même ligne. Cette requête est déjà servie efficacement par l'index partiel existant `idx_ingestion_control_workflow_events_resource_id` (LOT44b, migration 003, non modifiée) — aucun nouvel index n'est nécessaire pour ce cas d'usage.

**Interface pour LOT44f (Cockpit, lecture seule)** : le Cockpit ne parle jamais directement à PostgreSQL (AGENTS.md, règle cross-service). LOT44f devra exposer un endpoint `rag-engine` en lecture seule qui interroge `workflow_events` selon le même motif que ci-dessus — **cet endpoint n'existe pas et ne doit pas être créé par LOT44c**.

**Nature exacte de `workflow_events`** : c'est un **journal d'audit append-only** (aucune ligne n'est jamais mise à jour ni supprimée, `UPDATE`/`DELETE` révoqués pour le rôle runtime) — **jamais** une projection opérationnelle séparée (aucune table matérialisée « dernier statut par ressource » n'existe ni n'est prévue par ce lot). Il reste néanmoins **directement requêtable comme source pour une décision opérationnelle** via la requête ci-dessus (`ORDER BY occurred_at DESC, event_id DESC LIMIT 1`), rendue efficace par l'index déjà en place — sans qu'aucune projection/vue matérialisée ne soit nécessaire au volume actuel. Si un futur lot juge la lecture par scan trop coûteuse au volume réel de production, une projection dédiée resterait un choix d'architecture séparé, hors périmètre LOT44c.

**Contrat de répétition (contrat B — détection de doublon)** : une validation répétée crée un **nouvel événement** à chaque appel (jamais un remplacement, jamais un rejet silencieux) sauf si l'appelant fournit une `idempotency_key` explicite, auquel cas une répétition **échoue toujours** (`UniqueViolation`) — y compris à payload identique, y compris pour un `run_id`/`resource_id` différent (cf. sous-section dédiée, Décision 5). Ce n'est jamais une idempotence au sens fort (contrat A) — prouvé par la matrice à cinq scénarios (`TestDuplicateDetectionKeyContractB`).

**Réserve prouvée et non corrigée** (schéma LOT44b figé) : rien n'empêche d'appeler `record_validation_result(run_id=A, resource_id=<ressource appartenant en réalité à un run B>)` — `workflow_events` porte deux FK indépendantes (`run_id`, `resource_id`) sans contrainte composite vérifiant leur cohérence mutuelle. Prouvé par `test_inconsistent_run_and_resource_pairing_is_not_rejected_by_the_schema`. Non modifiable sans toucher la migration 003 (gelée) — signalé ici comme réserve, pas corrigé silencieusement.

## Dettes héritées de LOT44b — traitées comme prérequis de production

| Dette | Risque concret | Lot de clôture | Condition d'acceptation | Test qui prouvera la résolution | Bloque la production |
|---|---|---|---|---|---|
| Bootstrap PostgreSQL sans fingerprint colonne-par-colonne (`bootstrap_ingestion_control_schema.sh`, cf. ADR-0027) | Dérive silencieuse du schéma `ingestion_control` en production (colonne/contrainte/index modifiés hors migration, non détectée) | **Non assigné à ce jour** — recommandé avant toute première mise en production réelle, quel que soit le lot fonctionnel en cours à ce moment | Le bootstrap revalide colonnes/contraintes/index un par un après application, au même niveau de rigueur que `pgvector_migration_state.sh` | Un test qui mute une colonne/contrainte hors migration et prouve que le bootstrap suivant échoue explicitement | **Oui** — avant toute mise en production |
| `job_id` sans table `jobs` ni contrainte FK (`workflow_events.job_id`, ADR-0027) | Aucune intégrité référentielle sur l'identifiant de tentative d'exécution métier ; un futur worker pourrait écrire des `job_id` incohérents ou dupliqués sans qu'aucune contrainte ne le détecte | **LOT44e** (scheduler et workers CLI — premier producteur réel de `job_id`, cf. ADR-0027 « Suites ») | Table `ingestion_control.jobs` (ou équivalent) + FK réelle depuis `workflow_events.job_id`, avec un ADR dédié | Test de violation de FK sur un `job_id` inconnu, une fois la table créée | **Oui, si LOT44e livre un producteur de `job_id` sans cette table** — pas bloquant pour LOT44c/LOT44d qui n'en produisent aucun |
| Incohérence `run_id`/`resource_id` non bloquée par le schéma (`workflow_events`, deux FK indépendantes, aucune contrainte composite) | Un appelant peut journaliser un événement associant une ressource à un run auquel elle n'appartient pas réellement, sans erreur SQL — traçabilité faussée sans le savoir | **Non assigné** — nécessite de modifier la migration 003 (gelée) ; à traiter par un lot dédié au durcissement du schéma `ingestion_control`, pas par LOT44c/LOT44d | Contrainte composite (`FOREIGN KEY (run_id, resource_id) REFERENCES ...` ou vérification applicative systématique) empêchant la pose d'une paire incohérente | Test qui insère une paire `run_id`/`resource_id` incohérente et prouve un rejet (actuellement : prouvé accepté, `test_inconsistent_run_and_resource_pairing_is_not_rejected_by_the_schema`) | **Oui** — avant toute mise en production s'appuyant sur cette traçabilité pour des décisions automatisées |
| Limitation multi-tenant : une seule valeur par dimension de scope par déploiement (ADR-0027, réaffirmée LOT44c) | `UNIQUE(collection, dedup_key)` peut collisionner entre deux tenants si l'hypothèse de déploiement à tenant unique est violée ; aucune barrière technique ne l'empêche | **Hors périmètre explicite** tant qu'aucun besoin réel de multi-tenant n'est démontré — nécessiterait un ADR dédié avant toute généralisation (ADR-0027, réaffirmé) | Un ADR dédié actant un vrai modèle multi-tenant, avec élargissement de la contrainte aux dix dimensions de scope | Test de collision inter-tenant après élargissement de la contrainte | **Non**, tant que le déploiement reste à tenant unique (hypothèse actuelle, non un vrai risque en l'état) |
| Absence de parcours end-to-end reliant `/ingest/v2` (endpoint HTTP réel, LOT43, `src/ingestor/ingest_v2_endpoint.py`) au plan de contrôle PostgreSQL `ingestion_control` (LOT44b/44c) | Le plan de contrôle PostgreSQL existe en parallèle de l'endpoint d'ingestion réellement exposé, sans aucun lien — vérifié par recherche exhaustive : zéro référence à `ingestion_control`/`ingestion_profiles` dans `ingest_v2.py`/`ingest_v2_endpoint.py`. Une ingestion réelle via `/ingest/v2` aujourd'hui ne passe par aucune primitive LOT44b/44c | **LOT44e** (scheduler et workers CLI) au plus tôt, potentiellement un lot dédié de câblage E2E | Un test d'intégration démontrant qu'une requête `/ingest/v2` réelle produit un `run`/`resource` dans `ingestion_control`, sélectionne un profil, et journalise un résultat de validation | Test end-to-end HTTP → `ingestion_control`, actuellement inexistant | **Oui** — c'est la condition même de l'objectif global du projet (« workflow d'ingestion automatisée complet »), non atteinte par LOT44a-c pris isolément |

Aucune de ces cinq réserves n'est traitée comme une simple remarque : chacune porte un lot de clôture (assigné ou explicitement non assigné), une condition d'acceptation vérifiable et un test qui prouvera sa résolution — une réserve sans ces trois éléments serait une dette non maîtrisée, ce que ce tableau évite.

## Hors périmètre de LOT44c

- Aucun fichier de profil de production n'est livré : la définition du contenu réel d'un profil (domaines autorisés, cadence, seuils qualité) est une décision pédagogique/gouvernance, hors du périmètre infrastructure de ce lot.
- Aucun déclenchement automatique de transition (`cas_transition`) depuis un résultat de validation — un futur appelant explicite (LOT44d, stages déterministes) en décidera.
- Aucune généralisation multi-tenant : la limitation « une valeur par dimension par déploiement » (ADR-0027) n'est ni levée ni contournée.
- Aucun worker, scheduler, agent, orchestrateur, serveur MCP, endpoint HTTP, route Cockpit, pipeline Planner/Scout/Fetcher, connexion externe, écriture dans `rag_chunks`, logique de retrieval, publication ou auto-publication.

## Conséquences

### Positives
- Aucune nouvelle migration, aucun nouveau rôle, aucun nouveau privilège — surface de risque minimale.
- Réutilisation exacte d'un motif déjà éprouvé (`collection_config.py`) plutôt qu'un nouveau mécanisme de configuration.
- `CollectionProfile`/`ResourceScope`/`ResourceState` (LOT44a) et `workflow_events` (LOT44b) restent strictement inchangés.

### Négatives
- Aucun profil réel n'existe encore : LOT44c reste une primitive sans donnée de production, comme LOT44b avant lui — `PRODUCTION_BLOCKED_NO_PRODUCTION_PROFILES` (cf. matrice ci-dessus).
- `review_required` et `profile_invalid`, bien que représentables dans le vocabulaire de la consigne, ne sont pas des statuts produits par ce moteur — à réévaluer si un futur lot introduit un cas d'usage réel.
- Le système n'est pas multi-tenant : `UNIQUE(collection, dedup_key)` peut collisionner entre deux tenants si l'hypothèse de déploiement à tenant unique est violée (hérité de LOT44b, non modifié).
- Aucune contrainte composite ne garantit qu'un `resource_id` transmis à `record_validation_result` appartient réellement au `run_id` fourni (schéma LOT44b figé).
- Aucun parcours end-to-end ne relie l'endpoint HTTP réel `/ingest/v2` (LOT43) au plan de contrôle PostgreSQL — l'objectif global du projet (workflow d'ingestion automatisée complet) n'est pas atteint par LOT44a-c pris isolément.
- `detect_profile_drift` a un critère de départage non garanti entre deux événements partageant exactement le même `occurred_at` (transaction unique sans commit intermédiaire) — non corrigible sans migration sur un schéma gelé, sans impact dans l'usage réel (chaque validation committée séparément), prouvé par test.

### Risques et mitigations
- *Confusion entre le registre de profils LOT44c et le catalogue `rag_collections.yml` (ADR-0013)* → noms de modules et de répertoires délibérément distincts (`ingestion_profiles/` vs `collection_config.py`), documenté ici explicitement.
- *Tentation future de faire produire `job_id` ou une transition automatique par ce moteur* → bloqué par absence de paramètre `job_id` dans `record_validation_result()` et absence d'appel à `cas_transition`, vérifié par test.
- *Version de profil non bornée en format, risque d'identité instable* → corrigé pendant cette clôture (`PROFILE_VERSION_PATTERN`).
- *Modification silencieuse d'un profil non détectable* → `detect_profile_drift` compare réellement contre l'historique persisté (pas seulement une empreinte isolée), testé avec de vraies connexions PostgreSQL ; reste un mécanisme à invoquer explicitement (aucun processus ne l'appelle automatiquement dans ce lot).
- *Déploiement de profils de production incohérent avec l'intention (fichier oublié/ajouté par erreur)* → `verify_profile_manifest` ferme ce mécanisme (égalité d'ensembles stricte), à invoquer par un futur processus de démarrage.

## Suites

- LOT44d : stages déterministes — premier consommateur légitime d'un résultat de validation pour déclencher une transition explicite via `cas_transition`.
- LOT44e : scheduler et workers CLI — premier producteur réel de `job_id` (doit fermer la dette « `job_id` sans table `jobs` », cf. tableau ci-dessus), premier appelant de `verify_profile_manifest`/`detect_profile_drift` à son démarrage, premier consommateur de la requête de lecture documentée ici, et lot responsable du câblage E2E `/ingest/v2` → `ingestion_control`.
- LOT44f : Cockpit en lecture seule — doit exposer un endpoint `rag-engine` dédié pour lire `workflow_events` (jamais un accès direct Postgres depuis le Cockpit).
- Un ADR dédié reste nécessaire avant toute persistance PostgreSQL de `CollectionProfile` lui-même (table `collection_profiles`), si un futur lot en démontre le besoin réel.
- Un ADR dédié reste nécessaire avant toute réintroduction d'un état ou statut `PUBLISHED` (déjà acté par ADR-0026/ADR-0027).
- Avant toute mise en production réelle : fermer la dette du bootstrap sans fingerprint colonne-par-colonne (lot non assigné, cf. tableau), livrer un manifest de profils de production réel, câbler le parcours E2E `/ingest/v2` → `ingestion_control`, et invoquer `detect_profile_drift` depuis un processus réel avant chaque utilisation d'un profil.
