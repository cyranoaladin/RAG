# LOT_GO_LIVE_FINAL_CI_SCOPE_POLICY_GOVERNANCE_ADR

- **Branche** : `go-live/scope-policy-governance-adr`
- **Base** : `b0749c35` (`main`)
- **Date** : 2026-09-19
- **Nature** : lot de **décision**. Aucun code d'émission, aucun scope produit.

## Pourquoi ce lot existe

Le lot précédent visait à générer les onze scopes V2 pour faire démarrer le
staging. Il y parvenait, mais au prix de deux contournements :

1. le jeu de dimensions croisées de l'émetteur canonique était rétréci pour la
   nouvelle autorité de politique, supprimant le contrôle de `visibility` et de
   `programme_version` ;
2. trois artefacts de politique `prod_hggsp_*_v1` et `prod_hlp_terminale_v1`
   étaient écrits à la main par analogie avec des collections voisines, insérés
   dans le registre fermé, puis présentés à l'émetteur comme « déjà
   gouvernés ».

Preuve que le rétrécissement était porteur et non cosmétique — cross-check
complet rétabli, même entrées :

```
REFUS DE L'EMETTEUR: prod_dgemc_terminale_option_v2 :
  visibility du sujet 'public' ≠ visibility de la politique 'internal'
```

Ce travail a été **retiré**. Le working tree est revenu à l'identique de `main`
(735 tests contracts verts en base). Le dossier non suivi
`nexus_drive_provenance_8_authorities/` (9,4 Mo d'exports Drive) a été **déplacé
hors du dépôt**, non supprimé.

## Ce que l'analyse a établi

| Fait | Preuve |
|---|---|
| La divergence est **préexistante**, pas due au rescellement V2 | les placements de la release V1 portent déjà `public` / `EDUSCOL_CORPUS_20260808` |
| Les scopes `prod_*_v1` n'ont jamais subi ce croisement | ils ont été écrits à la main (ADR-0048, « Contexte ») |
| Les champs ont bien la **même sémantique** ailleurs | dans la famille multi-niveaux, `visibility` et `programme_version` coïncident exactement, 10/10 |
| `programme_version` a une **autorité gouvernée** dans la release V2 | `programme_registry.json` (`NEXUS_PROGRAMME_INDEX_REGISTRY_V3`) déclare le BOEN des 11 collections, **concordance 11/11** avec les scopes |
| `visibility` : la politique **restreint**, elle n'élargit pas | ADR-0045 a décidé `internal` ; la release déclare l'ouverture du matériau (`public`) |
| HGGSP ×2 et HLP terminale ne sont gouvernés **nulle part** | absents de `verified_production_profiles_20260825.json`, de `proposed_production_profile_matrix_20260823.json` et d'ADR-0045 ; `rights_evidence_registry.yml` et `corpus_zone_routing.yml` ne les mentionnent pas |

Conséquence : **aucune garde n'a besoin d'être affaiblie.** `programme_version`
était lu à la mauvaise source, et `visibility` compare deux notions distinctes
qu'il fallait nommer séparément.

## Livrables

| Fichier | Rôle |
|---|---|
| `docs/adr/ADR-0052-…-cross-check-…-production.md` | classe les 12 dimensions en 3 familles ; change l'autorité de `programme_version` ; formalise l'ordre de restriction de `visibility` ; interdit tout retrait de dimension |
| `docs/adr/ADR-0053-autorite-des-droits-hggsp-hlp.md` | déclare les 3 collections bloquantes ; définit ce qu'une décision humaine devra fournir ; interdit la fabrication par analogie |
| `docs/governance/retrieval_scope_policy_registry.yml` | registre `NEXUS_RETRIEVAL_SCOPE_POLICY_REGISTRY_V1` couvrant les **11** collections : 8 gouvernées (politique citée de sa source + digest), 3 bloquantes (champs de politique `null`) |
| `packages/contracts/tests/test_retrieval_scope_policy_registry.py` | 15 tests de preuve |

Le registre **ne peut pas inventer un droit** : pour chaque collection
gouvernée, un test compare `audiences`, `rights` et `policy_visibility` à
l'artefact packagé cité, digest épinglé à l'appui. Toute valeur divergente fait
échouer la CI.

## Couverture des preuves exigées

| # | Exigence | Test |
|---|---|---|
| 1 | aucun scope généré | `test_no_scope_is_emitted_by_this_lot` (registre = 41) |
| 2 | aucun runtime modifié | `test_lot_touches_only_governance_documents` |
| 3 | aucun compteur readiness modifié | idem (aucun chemin `services/`) |
| 4 | aucun fichier de release V2 modifié | `test_release_v2_manifest_digest_is_unchanged` |
| 5 | les 11 collections V2 listées | `test_registry_covers_every_v2_collection_exactly` |
| 6 | HGGSP/HLP : autorité explicite ou bloquantes | `test_blocked_collections_declare_no_policy_at_all`, `test_blocked_collections_have_no_packaged_scope` |
| 7 | règle `visibility` formalisée | `test_visibility_order_covers_every_contract_value`, `test_policy_visibility_never_widens_evidence_visibility` |
| 8 | règle `programme_version` formalisée | `test_programme_version_authority_is_declared_and_digested`, `test_programme_version_is_read_from_its_authority_not_from_placements` |
| 9 | contrat testable pour l'émetteur futur | `test_every_governed_entry_carries_all_emitter_inputs` |
| 10 | dossier Drive non committé | `test_drive_provenance_directory_is_absent_from_the_repository` |

## Conséquence sur la trajectoire go-live

La couverture de la release V2 est **8/11**. `validate_release_startup_configuration`
continuera donc légitimement de refuser le démarrage du staging : le blocage
n'est pas levé par ce lot, il est **requalifié**. Il ne porte plus sur un
symptôme de démarrage mais sur trois décisions humaines nommées, chacune avec
la liste de ce qu'elle doit fournir (ADR-0053 §3).

Un démarrage obtenu en dotant trois collections de droits que personne n'a
décidés vaudrait moins qu'un refus.

## Verrous de gouvernance

Aucun verrou touché. Aucun `promotion_status`, `activation_status` ou
`review_status` modifié. La release V2, son manifeste et `release-registry.json`
sont inchangés — le digest du manifeste est vérifié par test. Aucun
`current switch`, aucune écriture en base production, aucune exposition du
staging.

## Suite

Après approbation humaine et merge de ce lot :

1. si les 3 décisions HGGSP/HLP sont rendues : les porter au registre avec
   leurs sources, puis ouvrir `LOT_GO_LIVE_FINAL_CI_FIX_V2_RETRIEVAL_SCOPES_FOR_STAGING_V2` ;
2. sinon : ouvrir ce lot technique pour les **8** collections gouvernées, en
   sachant qu'il ne fera pas démarrer le staging tant que le contrat est
   incomplet — l'émetteur devra refuser les 3 sans autorité, par construction.
