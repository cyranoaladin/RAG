# P0-L1A — cohérence release / catalogue

## Verdict

`RELEASE_CATALOGUE_COHERENCE = FAIL — 7 collections sur 18`

Les deux sources **ne sont pas** mutuellement satisfaisables en l'état. Elles le
redeviennent en retirant de la release les 7 collections non instanciées, sans
toucher au catalogue ni à un verrou de gouvernance.

Aucune modification n'est appliquée à la PR #134 par ce lot : il produit la
preuve demandée avant toute régénération ou signature.

## Pourquoi c'est P0 et non P1

La cartographie classait cet écart en P1. Le lot P0-L2 a changé sa nature :
`validate_configured_release_database()` conditionne désormais le **démarrage**
du moteur. Les deux règles suivantes se contredisent alors directement.

| Source | Ce qu'elle impose |
| --- | --- |
| Registre de release | avant tout trafic, le moteur exige en base les artefacts, placements et chunks de **chaque** collection nommée |
| Catalogue (`instanciee`) | `resolve_collection_v2` refuse fail-closed toute collection non instanciée, sur `/search/v2`, `/chat` et `/collections/v2` |

Une collection nommée par la release mais non instanciée est donc
auto-contradictoire : **sa publication est exigée pour démarrer, et son
interrogation est refusée ensuite**. Le coût n'est pas théorique — c'est de
l'ingestion gouvernée réelle (droits, PII, currentness, revue) dont le résultat
ne sera jamais interrogeable.

## Tableau exhaustif des 18 collections de release

| collection | in_catalogue | instanciee | in_release_registry | expected_artifacts | expected_placements | expected_chunks | ingestible_by_current_policy | verdict |
| --- | :-: | :-: | :-: | --: | --: | --: | :-: | --- |
| `rag_nexus_dgemc_terminale_option` | oui | **false** | oui | 1 | 1 | 44 | non | **P0** |
| `rag_nexus_francais_premiere_tc` | oui | true | oui | 1 | 1 | 38 | oui | COHERENT |
| `rag_nexus_francais_quatrieme_tc` | oui | true | oui | 1 | 1 | 20 | oui | COHERENT |
| `rag_nexus_francais_seconde_tc` | oui | true | oui | 2 | 2 | 44 | oui | COHERENT |
| `rag_nexus_hlp_premiere_specialite` | oui | **false** | oui | 4 | 4 | 56 | non | **P0** |
| `rag_nexus_maths_premiere_gen_specialite` | oui | true | oui | 1 | 1 | 38 | oui | COHERENT |
| `rag_nexus_maths_quatrieme_tc` | oui | true | oui | 1 | 1 | 21 | oui | COHERENT |
| `rag_nexus_maths_seconde_tc` | oui | true | oui | 1 | 1 | 44 | oui | COHERENT |
| `rag_nexus_maths_terminale_gen_specialite` | oui | true | oui | 1 | 1 | 55 | oui | COHERENT |
| `rag_nexus_nsi_premiere_specialite` | oui | true | oui | 1 | 1 | 19 | oui | COHERENT |
| `rag_nexus_nsi_terminale_specialite` | oui | true | oui | 1 | 1 | 18 | oui | COHERENT |
| `rag_nexus_pc_premiere_specialite` | oui | **false** | oui | 1 | 1 | 39 | non | **P0** |
| `rag_nexus_pc_terminale_specialite` | oui | true | oui | 1 | 1 | 56 | oui | COHERENT |
| `rag_nexus_philo_terminale_tc` | oui | true | oui | 5 | 5 | 75 | oui | COHERENT |
| `rag_nexus_ses_premiere_specialite` | oui | **false** | oui | 1 | 1 | 16 | non | **P0** |
| `rag_nexus_ses_terminale_specialite` | oui | **false** | oui | 1 | 1 | 18 | non | **P0** |
| `rag_nexus_svt_premiere_specialite` | oui | **false** | oui | 1 | 1 | 57 | non | **P0** |
| `rag_nexus_svt_terminale_specialite` | oui | **false** | oui | 1 | 1 | 72 | non | **P0** |

`P0` = `P0_RELEASE_NAMES_A_NON_INSTANCIATED_COLLECTION`.

Les 18 collections sont présentes au catalogue et disposent chacune d'un profil
d'ingestion production activé, en correspondance exacte 1:1. **Le seul écart est
le drapeau `instanciee`** — aucune collection n'est absente du catalogue, aucune
n'est sans profil, aucun profil n'est en double.

## Totaux

| | collections | artefacts | placements | chunks |
| --- | --: | --: | --: | --: |
| Release déclarée | 18 | 26 | 26 | 730 |
| Sous-ensemble cohérent | 11 | 16 | 16 | 428 |
| **Travail non servable si conservé** | **7** | **10** | **10** | **302** |

Le manifest annonce exactement `{artifacts: 26, placements: 26, chunks: 730}`,
identique à la somme des 18 sujets : la porte de démarrage est donc
arithmétiquement satisfaisable, mais 302 chunks n'auraient aucun consommateur.

## Preuve de satisfaisabilité

Un candidat réduit aux 11 collections cohérentes a été construit hors dépôt et
soumis à la validation de démarrage réelle :

```
A) release courante   (18 collections) : validate_release_startup_configuration = OK
B) release candidate  (11 collections) : validate_release_startup_configuration = OK
```

Les deux passent : retirer les 7 ne casse aucun invariant de démarrage. Le
candidat conserve 11 collections instanciées, ce qui satisfait l'exigence
d'intersection non vide entre collections de release et scopes V2 instanciés.

Digests du candidat (indicatifs, non versionnés — le producteur canonique
refera le calcul en P0-L1C) :

| Artefact | SHA-256 |
| --- | --- |
| manifest candidat | `81b4e971c2c8d75546566ff1dacf8842c677d167891a4bf10b1ce353805b90b4` |
| registre candidat | `f5282c1d03b52a3a6b00200072a43e7f99dd5c578026d12855b9bcbda20f1a4f` |

## Décision

**Retirer les 7 collections non instanciées de la release**, conformément aux
invariants existants et à la préférence opérateur.

L'alternative — passer les 7 à `instanciee: true` — est écartée : le catalogue
documente explicitement que ces collections attendent leur vague de revue
(LOT 28 / ADR-0040 pour HLP, blocs disciplinaires pour les autres). Les activer
pour satisfaire un registre reviendrait à déclarer 7 collections interrogeables
sans la revue que `instanciee` a précisément pour rôle de porter — c'est-à-dire
à affaiblir un verrou pour satisfaire une porte, exactement ce que la discipline
du projet interdit.

Retirer ne détruit rien : les 7 collections restent déclarées au catalogue, leurs
profils d'ingestion production restent versionnés, et leurs artefacts restent
éligibles. Elles rejoindront une release ultérieure le jour où leur vague de
revue les instanciera.

## Conséquences pour P0-L1C

Le retrait touche des artefacts scellés et invalide la chaîne d'autorisation :

- `release-registry.json` : 18 → 11 collections, nouveau `expected_manifest_sha256` ;
- `production-profile-gate.release.json` : 18 → 11 sujets, `expected_counts`
  26/26/730 → 16/16/428 ;
- `RAG_RELEASE_REGISTRY_SHA256` et les ancres `PRODUCTION_*` correspondantes ;
- PR #134 : 18 → 11 `ScopeAuthorizationArtifactV2`, union de 26 → 16 contenus,
  donc nouveau digest d'union (l'actuel `fe97b341…` couvre 26 contenus) ;
- HEAD de la PR #134, donc CI et `trusted-human-review/head-pinned` à rejouer ;
- bundle de review-bindings à régénérer intégralement.

Aucun binding ni bundle lié à l'ancien HEAD ne doit être réutilisé.

## Garde-fou

`services/rag-pedago/scripts/release_catalogue_coherence_audit.py` reproduit ce
tableau et, avec `--check`, sort en code 1 tant qu'une collection de release
n'est pas instanciée. Il n'est pas encore câblé en CI : il le sera avec la
correction de P0-L1C, pour que le garde-fou et l'état correct arrivent ensemble
plutôt qu'un rouge délibéré sur `main`.

## Vérifications

- `release_catalogue_coherence_audit.py --check` : exit 1, `FAIL (7 collections)` ;
- `tests/test_release_catalogue_coherence_audit.py` : `7 passed` ;
- ruff : PASS ;
- preuve machine : `docs/reports/evidence/release_catalogue_coherence_20260826.json`.

## Dépendances restantes

- P0-L1B — le préflight de signature accepte encore une ancre tournée ;
- P0-L1C — régénération release + PR #134 + bundle, après P0-L1A et P0-L1B ;
- P0-L2B — démarrage de l'API, bloqué tant que la release n'est pas publiée.
