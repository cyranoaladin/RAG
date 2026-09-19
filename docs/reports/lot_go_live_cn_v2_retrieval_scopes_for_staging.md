# LOT_GO_LIVE_FINAL_CI_FIX_V2_RETRIEVAL_SCOPES_FOR_STAGING_V2

- **Branche** : `go-live/fix-v2-retrieval-scopes-for-staging-v2`
- **Base** : `0868d4b5` (`main`, après merge de #229 / lot CM)
- **Date** : 2026-09-19
- **Nature** : lot **technique**. Premier des trois à modifier du runtime.

## Objet

Émettre les onze scopes de retrieval de `production-profile-gate-2026-2027-v2`
par l'émetteur canonique, en appliquant les règles d'ADR-0052 et l'autorité
d'ADR-0053, et faire démarrer le staging **parce que le contrat est complet**.

## La contre-épreuve, d'abord

Le démarrage est accepté en rehearsal. Pour que cela veuille dire quelque
chose, il faut montrer que la garde n'a pas été réduite. En retirant les onze
scopes du registre — l'état exact d'avant ce lot — le refus d'origine revient :

```
--- AVEC les 11 scopes ---   ACCEPTE
--- SANS les 11 scopes ---   REFUS: scope source SHA differs from subject release
```

C'est le test `test_removing_the_eleven_scopes_restores_the_original_refusal`.
Un test qui passerait dans les deux cas ne prouverait rien.

## Ce que le lot ajoute à l'émetteur, et pourquoi ce ne sont pas des assouplissements

Le lot écarté sous `SECURITY_STOP` retirait `visibility` et `programme_version`
du croisement. Ici les deux restent contrôlés, par une autorité corrigée.

| Règle (ADR-0052) | Mise en œuvre | Ce qui la prouve porteuse |
|---|---|---|
| §1 — huit dimensions curriculaires, égalité stricte | `_require_curricular_dimensions_match_subject` | `test_curricular_divergence_is_refused` |
| §2 — `programme_version` lu chez `NEXUS_PROGRAMME_INDEX_REGISTRY_V3` | `_require_programme_version_matches_authority` | `test_programme_version_diverging_from_its_authority_is_refused`, `test_corpus_provenance_is_never_used_as_a_programme_reference` |
| §3 — `policy_visibility` ne peut pas élargir | `_require_visibility_is_not_widened` | 3 cas d'élargissement refusés, 3 de restriction admis, 3 valeurs inconnues refusées |
| §3 bis — anti-circularité | `_require_evidence_visibility_matches_placements` | `test_evidence_visibility_must_match_the_placements` |
| ADR-0053 — pas d'autorité, pas de scope | refus fail-closed | `test_collection_absent_from_the_registry_is_refused`, `test_entry_without_policy_is_refused` |

**Anti-circularité.** `_require_visibility_is_not_widened` compare deux valeurs
du registre. Si personne ne vérifiait que `evidence_visibility` est bien celle
que les placements déclarent, il suffirait d'y écrire une valeur plus
restrictive pour faire passer n'importe quelle politique. Le croisement contre
la release ferme cette porte.

**Lecteur dédié, non élargi.** La release profils production porte ses
placements à la racine du subject, là où la release multi-niveaux les imbrique
sous `artifacts`. Plutôt que d'assouplir le lecteur historique — ce que faisait
le lot écarté — un lecteur distinct et STRICT a été ajouté :
`load_profile_subject_release` exige que chaque dimension soit présente et
univoque sur tous les placements. Le chemin multi-niveaux est inchangé, et
`test_legacy_multilevel_reader_still_requires_nested_placements` le vérifie.

## Les onze scopes

| Collection | scope_id | Politique |
|---|---|---|
| dgemc terminale option | `prod_dgemc_terminale_option_v2` | reconduite (ADR-0045) |
| hlp première spécialité | `prod_hlp_premiere_specialite_v2` | reconduite |
| nsi première / terminale | `prod_nsi_*_v2` | reconduite |
| ses première / terminale | `prod_ses_*_v2` | reconduite |
| svt première / terminale | `prod_svt_*_v2` | reconduite |
| **hggsp première** | `prod_hggsp_premiere_specialite_v1` | **décision humaine (ADR-0053, lot CM)** |
| **hggsp terminale** | `prod_hggsp_terminale_specialite_v1` | **décision humaine** |
| **hlp terminale** | `prod_hlp_terminale_specialite_v1` | **décision humaine** |

**Pourquoi trois `_v1` et non `_v2`.** Ces collections n'avaient aucun scope
packagé. Les nommer `_v2` laisserait croire à un prédécesseur qui n'existe pas.
ADR-0045 veut un nouvel identifiant par version de subject ; une collection
sans histoire commence à `_v1`.

**Recoupement notable.** Les huit scopes reconduits rendent des digests
**identiques** à ceux que produisait le lot écarté (`8ebb28a0…` pour dgemc,
`2c4f72b4…` pour hlp première, `41c2ef4c…` pour nsi première…). La politique
reconduite est donc bien la même ; ce qui a changé, c'est que le chemin qui y
mène est gouverné et que toutes les gardes sont actives.

## Entrées nommées et digérées

| Entrée | sha256 |
|---|---|
| release V2 (manifeste) | `e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864` |
| registre de politique | `54212d964d49c6f871de6606754b259561b0d4baac20a46118cfba4910295b68` |
| autorité de nommage | `1a31c6f93fc403e940541c1a8f9c85b1c82963b83ebf7c4be307d5c79574c37d` |

L'autorité de programme est nommée **par le registre lui-même**, digest
vérifié à l'exécution.

## Extension du registre : `target_identity`

`RetrievalScopeArtifactV2.target_identity` porte `audience` et `candidates`,
que `validate_envelope` utilise pour le **contrôle d'accès** :

```python
if profile.candidat not in expected.candidates:
if profile.audience != expected.audience:
```

Le registre ne les portait pas. Les onze entrées les déclarent désormais :

- pour les **8** reconduites, `target_audience` et `target_candidates` sont
  **restitués** du scope source et vérifiés contre lui — toute divergence est
  un refus d'émission (`test_governed_target_identity_diverging_is_refused`) ;
- pour les **3** décidées, `libre` / `[libre]` sont une **extension explicite
  de la décision CM**, approuvée au titre d'ADR-0053. Elles ne sont pas
  dérivées d'un motif observé : elles sont écrites, commentées et relues.

## Invariants, vérifiés et non affirmés

| Invariant | Preuve |
|---|---|
| aucun scope `*_v1` préexistant modifié | `test_no_preexisting_scope_artifact_is_modified` : sous `artifacts/`, seuls les ajouts (`A`) sont admis |
| aucune release modifiée | `test_no_release_file_is_ever_modified` ; digest du manifeste V2 vérifié |
| les 11 `source_sha256` = release V2 | `test_every_emitted_scope_binds_the_exact_release_subject` |
| un scope par couple `(collection, subject_sha256)` | `test_every_registry_collection_is_now_packaged_exactly_once` |
| émission déterministe | `test_emission_is_deterministic`, `test_reproduction_matches_the_packaged_bytes` |
| production refuse toujours la release non promue | `test_production_still_refuses_the_unpromoted_release_despite_the_scopes` |
| aucun `current_switch`, aucune écriture DB prod | `test_safety_invariants` (inchangé) |

Registre fermé : **41 → 52** scopes. Paquet `nexus-contracts` : **0.17.0 →
0.18.0**, lock de schémas régénéré.

## Qualité

- `packages/contracts` : **792 tests verts** (756 avant le lot, +36).
- `services/rag-engine` : `test_rehearsal_runtime_guard.py` **11 verts**, plus
  les suites de scopes (`test_retrieval_scope_v2`, `test_multilevel_scope_registry`,
  `test_rag_query_external_client`, `test_release_readiness`,
  `test_staging_external_acceptance`) — toutes vertes.
- `ruff` propre ; `export_schemas.py --check` vert.

> Réserve de transparence : faute de venv `rag-engine` installable en local
> (conflit `pydantic` connu), ces suites ont été exécutées via `PYTHONPATH=src`
> avec le Python système. `test_production_multilevel_profile_manifest.py` y
> échoue sur `pypdf 6.16.1 ≠ 6.14.2 déclaré` — un artefact de cet
> environnement, sans rapport avec le lot, que la CI ne reproduit pas
> puisqu'elle épingle la version. La CI GitHub fait foi.

## Ce que ce lot ne fait pas

Aucune release, aucun manifeste, aucun `release-registry.json` modifié. Aucun
`promotion_status`, `activation_status` ou `review_status` déplacé : la release
V2 reste `NOT_PROMOTABLE`, et la production continue de la refuser. Aucun
`current switch`, aucune écriture en base production, aucun déploiement
production, aucune exposition du staging.

**Aucune action d'infrastructure n'est effectuée par ce lot.** Le rebuild de
l'image staging, le redémarrage de `nexus-staging-ingestor-1` et la reprise du
lot CI staging viennent après le merge, sur feu vert explicite, et hors PR.

## Suite

Après approbation et merge :

1. rebuild de l'image staging avec `nexus-contracts` 0.18.0 ;
2. `NEXUS_ENVIRONMENT=rehearsal`, port loopback 18003,
   `PGVECTOR_CONTAINER=nexus-staging-pgvector-1` conservés ;
3. redémarrage de `nexus-staging-ingestor-1` ;
4. reprise du lot CI staging au point d'arrêt ;
5. preuve `STAGING_EXTERNE` **seulement** si healthcheck, retrieval et cockpit
   passent réellement.
