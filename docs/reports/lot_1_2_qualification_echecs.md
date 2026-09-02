# LOT 1.2 — Qualification exhaustive des échecs de suites (pré-gel du 2026-09-02)

*Suites canoniques exécutées dans des environnements PROPRES construits depuis les
locks de la branche (`pypdf 6.14.2`, `nexus-contracts 0.15.0` chargé depuis le commit
candidat), lint et mypy verts dans les deux services. État de départ : 40 échecs (6
`rag-pedago`, 34 `rag-engine`). État d'arrivée : 4 + 7, tous d'une même famille
structurelle, rendus ci-dessous comme événement B.*

## 1. Causes racines trouvées

| # | Cause | Preuve | Effet |
|---|---|---|---|
| C1 | Ma branche partait de `ffc1bae` (lignée Claude/Codex) ; `lot1c` avait entre-temps fait entrer et rescellé la release des onze. Le répertoire de release était un état mixte. | `git merge-base` = `ffc1bae` ; 6 commits lot1c absents | fusion `85736c0` : 3 conflits (inventaire modèle), résolus côté LOT 1.2 |
| C2 | Le manifeste de profils de la livraison 319 vit SOUS `configs/ingestion_profiles/` (chemin lié par `authority_bindings.json`) ; le registre le validait « comme profil ». | erreur de collecte `test_h2c_placement_readiness` sur lot1c ET sur ma branche | toute la suite moteur était interrompue à la collecte |
| C3 | `src/ingestor/requirements.txt` (inclus par `requirements-dev.txt`) épinglait encore `pypdf==4.2.0` : un environnement propre retombait à 4.2.0 malgré le lock. | env propre initial : `pypdf 4.2.0` | non-reproductibilité réelle (texte différent sur 319/320 PDF) |
| C4 | Les épreuves d'activation du catalogue épinglaient le plan ADR-0041 (Quatrième, vague 0, huit collections) ; aucune release scellée ne l'a jamais porté. | catalogue instancié = 11 = registre = base | 9 épreuves « ancienne politique » |
| C5 | Les épreuves de release épinglaient la lignée A (26 contenus, 18 profils, manifeste `ingestion_manifest.yml`). | release scellée : 11 sujets, 486 placements, 319 contenus | 8 épreuves « ancienne topologie » |
| C6 | **La release scellée des onze (V1, lignée B) est REFUSÉE par le lecteur du moteur** : `artifact is duplicated across subjects` (168 contenus bi-placés répétés par sujet — représentation Option B). | `load_release_expectation` et `load_release_registry_file` sur `release-registry.json` (`c9a844d4…`) | le registre monté en production est celui-là : seconde cause, structurelle, du 503 depuis le 30/08 |
| C7 | **Le rescellement lot1c de `document_type_mapping_sha256` (→ `ce5e51b7…`, mapping à 4 types) ne couvre pas la release** : l'inventaire scellé utilise 8 types externes, 5 absents de ce mapping (`annales-sujets-corriges`, `autre`, `evaluation-examen`, `guide`, `programme-limitatif`). Le mapping de la branche 319 (`3518fe87…`, 9 types) les couvre tous. La release servie du 29/08 liait `330c3362…`, un contenu jamais commité. | mesure sur `candidate_inventory.json` | binding faux ; test « chaque autorité liée » rouge |
| C8 | La projection de scopes de retrieval (`release_scope_placement_20260825`, 30 artefacts de scope du contrat, pilote maths terminale) est celle de la lignée A ; ses entrées ont été remplacées sous le même nom par la lignée B. Une reprojection depuis la lignée B refuse : la matrice cite des profils `v2_corpus_complet` absents du dépôt. | `produce_release_scope_placement_from_git` → `INVALID_GIT_TREE_ENTRY` | 3 épreuves de projection/scopes |
| C9 | Douze gardes `git status` des audits unitaires regardaient tout le dépôt ; une sonde transitoire écrite par un test moteur les faisait rougir en parallèle. | reproduit ; témoin durable ajouté | interférence de suites |

## 2. Table des 40 échecs de départ

Catégories : **DR** défaut réel · **FO** fixture historique obsolète · **EC** expected count obsolète · **AT** ancienne topologie de release · **EN** environnement · **AP** test dépendant d'une ancienne politique · **INV** test réellement invalide · **STRUCT** impossibilité structurelle (événement B).

| Test | Message | Cause | Cat. | Propriété protégée | Correctif | État |
|---|---|---|---|---|---|---|
| `test_h2c_placement_readiness` ×24 | `assert () == ('03f268…',)` puis erreur de collecte | C2 puis C4 (collection pilote philosophie non instanciée) | AP | logique de readiness H2C (allowlist exacte, dérives, autorité) — module hors de tout chemin d'exécution | manifeste reconnu par nature ; collection pilote instanciée dans une copie du catalogue POUR L'ÉPREUVE | vert (38) |
| `test_rag_collections_config` ×4 | `instanciee` attendu `True` | C4 | AP | catalogue = release servie | restatées : instancié == registre ∪ quarantaine ; décidées = dormantes tant que non servies | vert |
| `test_wave0_canonical_activation::only_the_two_wave0…` | `set() == {troisieme…}` | C4 | AP | idem | restatée | vert |
| `test_multilevel_scope_registry::complete_registry_aligns_with_adr_0041…` | `assert False is True` | C4 | AP | alignement registre de scopes / catalogue | flag suit la release servie | vert |
| `test_multilevel_scope_registry::startup_accepts_explicit_nonempty_release_subset…` | `release manifest collection set mismatch` puis `artifact is duplicated across subjects` | C4 puis **C6** | STRUCT | démarrage avec une release explicite | restatée sur la release des onze → refusée par le lecteur | **rouge (B)** |
| `test_multilevel_verified_placement::mappings_are_closed_and_exact` | mapping ≠ attendu | **C7** | DR | mapping fermé et exact, égal à celui que la release lie | épinglé à l'empreinte liée → révèle le binding faux | **rouge (B)** |
| `test_production_multilevel_profile_manifest::…twenty_six_placements` | runtime pypdf, puis `inventory unique_artifacts count differs` / `artifact is duplicated…` | C3 puis **C6** (inventaire compte 486 « artefacts uniques » pour 319) | STRUCT | les autorités de production réelles se résolvent | pypdf réglé ; le reste exige une release V2 | **rouge (B)** |
| `test_retrieval_scope_v2::mounted_catalogue_aligns_every_instantiated_pilot_subject` | maths terminale non instanciée | **C8** | STRUCT | scope pilote aligné sur le catalogue | reprojection lignée B requise | **rouge (B)** |
| `test_wave0_worker_runtime_cli::rejects_pii_policy_drift` | verrou runtime pypdf | EN (venv partagé 4.2.0) | EN | dérive de politique PII | épreuve isolée du runtime | vert |
| `test_build_production_profile_release::release_scope_inputs…` | `486 == 26` | C5 | EC | entrées de portée couvrent exactement la release | restatée sur la release scellée (486 lignes = placements, 319 uniques) | vert |
| `…::every_authority_is_named_path_bound_and_digest_checked` | `authority bindings fields are not exact` puis `digest differs for document_type_mapping` | ancien binding sans `runtime`, puis **C7** | DR | chaque autorité liée par chemin et empreinte | fusion lot1c (bindings avec `runtime`) ; reste C7 | **rouge (B)** |
| `…::any_authority_binding_mutation_is_refused` | idem | ancien binding | FO | mutation d'une liaison refusée | fusion lot1c | vert |
| `…::v2_producer_pii_scans_unique_contents_once` | double sans `pii_detected` | FO | FO | un scan par contenu | double honnête | vert |
| `test_production_profile_gate::new_profile_collections_are_declared_but_dormant_before_cutover` | `True is False` | C5 (bascule faite pour les servies) | AT | collections décidées déclarées, instanciées si servies | restatée | vert |
| `…::production_manifest_matches_all_eighteen_profiles_exactly` | 18 profils / manifeste lignée A | C5 | AT | manifeste = profils exactement | onze profils `v2_livraison_319`, manifeste lié | vert |
| `test_production_release_scope_placement::current_head_has_no_drift_in_any_producer_input_blob` | set éligible `a2d7bb…` ≠ `fe97b3…` | **C8** | STRUCT | reproductibilité de la projection | reprojection lignée B requise | **rouge (B)** |
| `test_release_scope_placement_git::p24_profile_match_is_accepted_by_current_release_registry` | philo hors release | **C8** | STRUCT | acceptation d'un profil par le registre courant | idem | **rouge (B)** |
| `test_recompute_final_release_set::versioned_ledger_recomputes…` | doublons dans le set éligible | **C6** (sortie lignée B écrite par placement) + comptabilité lignée A (72/26/46) | STRUCT | comptabilité terminale reproductible | la production V2 écrit le set comme ensemble ; comptabilité à refonder sur le ledger successeur | **rouge (B)** |
| `unit/test_cleanup_dry_run…`, `…decision_draft…` | `?? test_zz_docker_policy_probe.py` | C9 | EN | le script ne touche ni index ni arbre du service | gardes bornées (12), témoin durable | vert |
| lignée A 26/18 : `registered_release…`, `aggregate_covers_exactly_26…`, `preflight_proves…` (apparus à la fusion) | `11 == 18`, `486 == 26` | C5 | EC/AT | release scellée exacte, populations nommées | restatées (11 sujets, 486 placements par sujet, 319 uniques, +1 visé) | vert |
| 4 `test_release_readiness::runtime_*`/`real_release_registry_*` (apparus dans l'environnement propre sur la release des onze) | `artifact is duplicated across subjects` | **C6** | STRUCT | le registre réel se charge au démarrage | release V2 requise | **rouge (B)** |

Aucun test supprimé, aucun `skip`/`xfail`, aucune assertion alignée sur un état
pour faire vert : chaque restatement nomme la propriété conservée.

## 3. Ce qui reste rouge et pourquoi c'est un événement B

Les 11 échecs restants (7 moteur, 4 pedago) ont trois causes structurelles qui ne
relèvent pas d'un correctif de test :

1. **C6 — la release scellée des onze n'est pas chargeable par le moteur.** Elle
   duplique les 168 contenus bi-placés par sujet ; le lecteur (Option A) la refuse.
   C'est aussi une cause du 503 du service depuis le 30/08 (registre `c9a844d4…`
   monté). Seule une production V2 (Option A) la remplace — production dont le
   périmètre PII dépend des décisions humaines (ordre imposé : contrat → décisions →
   worker → production).
2. **C7 — le rescellement lot1c du mapping des types de document est faux** ; le bon
   contenu est `3518fe87…` (9 types, présent dans l'arbre). Le corriger est un
   rescellement d'attestation (outil `reseal_release_authorities.py`, ordre réel), à
   autoriser.
3. **C8 — la projection de scopes de retrieval et ses 30 artefacts sont de la lignée A**
   (pilote, wave 0, 18 collections). Une reprojection lignée B exige de fixer la
   provenance des profils dans la matrice (`v2_corpus_complet` → `v2_livraison_319`) et
   de décider le sort des scopes non servis (pilote maths terminale, entrées 3e/2de).

Hors suites : le `sys.path` interservice du producteur est mesuré (5 imports directs,
54 modules transitifs via `ingestion_profiles/__init__`, 7 modules réellement
nécessaires ≈ 3 300 lignes, ~130 sites d'import) ; un package neutre
`nexus-release-chain` est la seule voie conforme à AGENTS.md. Non fait dans ce lot.
