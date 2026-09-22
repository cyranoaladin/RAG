# ADR-0059 — Publier un instantané officiel sans le déclarer vérifié

- **Statut** : Proposé — HUMAN GATE requis sur la PR
- **Date** : 2026-09-22
- **Décideur attendu** : reviewer humain habilité, lié au HEAD exact de la PR
- **S'appuie sur** : ADR-0047 (décisions PII par contenu), ADR-0050 (identité
  de release), **ADR-0055** (politique d'actualité), ADR-0056 (revue de
  publication LOT42 d'une release scellée)
- **Contrat** : `nexus-contracts` 0.19.0 → **0.20.0** (additif)

> Cette ADR **ne publie rien**, n'active aucune release et ne lève aucun
> verrou. Elle rend exprimable, dans le runtime, une disposition que la
> gouvernance a déjà adoptée — et interdit qu'on la contrefasse.

## Le fait qui force la décision

ADR-0055 a adopté la politique `NEXUS-RAG-CURRENTNESS-POLICY-V1`. Elle dit,
en tête de fichier :

> `OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE` n'est pas `VERIFIED_CURRENT`, et
> ces deux valeurs ne doivent jamais se confondre dans une release.

La release candidate `production-profile-gate-2026-2027-v2` les confond,
mesuré sur ses propres fichiers :

| Fichier de la release | Ce qu'il déclare |
|---|---|
| `servability_matrix_v1.json` (autorité de sélection) | les **315** contenus publiés : `OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE`, **aucun** `VERIFIED_CURRENT` |
| `currentness_network_audit.json` | `CURRENTNESS_UNVERIFIED_SOURCE_UNREACHABLE`, `verified: 0` sur 486 |
| `currentness_evidence.json` (livré à côté de l'audit) | 486 × `decision: CURRENT`, `byte_identity: true`, *« Official Eduscol URL downloaded read-only and byte-matched »* |

L'actualité contredit l'audit livré avec elle. Ce n'est pas une nuance : la
preuve affirme une vérification réseau que l'audit dit ne pas avoir eue lieu.

Le producteur courant ne commet plus cette faute : quand l'audit est
`UNVERIFIED`, il écrit `REVIEW_REQUIRED`. Mais le runtime n'a que deux mots
— `CURRENT` (identité d'octets prouvée) et `REVIEW_REQUIRED` (non publiable).
Une actualité honnête rend donc la release **entièrement impubliable**, alors
que la gouvernance a décidé que ces contenus étaient servables.

Le runtime n'implémente pas la politique que la gouvernance a adoptée. Les
deux sorties possibles aujourd'hui sont toutes deux fausses :

- **déclarer `CURRENT`** : la contrefaçon que l'ADR-0055 interdit ;
- **déclarer `REVIEW_REQUIRED`** : bloquer ce que la gouvernance a autorisé,
  et réduire la livraison à zéro sans décision qui le fonde.

## Décision

### 1. La preuve d'actualité parle le vocabulaire de la politique

Nouveau type `MULTILEVEL_ARTIFACT_CURRENTNESS_V3`. Chaque contenu y porte une
`currentness_disposition` parmi les quatre de l'ADR-0055, et aucune autre :

| Disposition | Publiable | Faits exigés, et seuls admis |
|---|---|---|
| `VERIFIED_CURRENT` | oui | URL de téléchargement officielle, `current_download_sha256 == content_sha256`, `byte_identity: true`, et un audit réseau frère qui **ne se déclare pas** `UNVERIFIED` |
| `OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE` | oui | URL de provenance officielle de l'artefact (celle du catalogue scellé), statut de source non archivé, les quatre conditions de repli de la politique **toutes** vraies ; `byte_identity`, URL et empreinte de téléchargement **absents** |
| `NOT_CURRENT_DECLARED_BY_SOURCE` | non | aucun fait positif |
| `UNKNOWN` | non | aucun fait positif |

Le chargeur refuse, sans repli :

- un instantané qui porte un fait de vérification (`byte_identity`, URL ou
  empreinte de téléchargement) — c'est la contrefaçon, sous une autre forme ;
- un `VERIFIED_CURRENT` livré avec un audit qui se déclare non vérifié —
  c'est exactement le défaut de V2 ;
- une preuve qui ne nomme pas l'empreinte de la politique et de la matrice
  de servabilité dont ses dispositions dérivent.

`MULTILEVEL_ARTIFACT_CURRENTNESS_V1` et `V2` restent lus à l'identique :
`CURRENT` y vaut `VERIFIED_CURRENT`, `REVIEW_REQUIRED` y vaut `UNKNOWN`.
Aucune release existante ne change de sens.

### 2. Le produit enregistre ce qui a été prouvé, pas davantage

`rag_artifact_placements.currentness` admet une valeur de plus,
`official_snapshot` (migration produit `005`). Un instantané est publié
avec `currentness = 'official_snapshot'`, jamais `'current'`. `'current'`
reste réservé à l'identité d'octets prouvée.

Le retrieval sert les deux. C'est la décision de servabilité de l'ADR-0055,
qui n'est pas rouverte ici : la politique autorise la servabilité d'un
instantané institutionnel versionné, et le gate de servabilité l'a composée.
Ce qui change, c'est que la ligne servie **dit ce qu'elle est**.

### 3. La revue batch approuve ce qu'elle voit

`ReleaseBatchPlacementEvidence.currentness` admet `"official_snapshot"` en
plus de `"current"`. La revue humaine d'une release porte donc la
disposition réelle de ses placements, et une approbation donnée sur
`"current"` ne vaut pas pour une release d'instantanés.

### 4. La projection PII admet la détection revue, et elle seule

La projection batch n'admettait que `CLEARED`. Elle admet désormais
`DETECTED_REVIEWED_ACCEPTED` **uniquement** si l'entrée nomme le
`decision_set_id` et le `review_bundle_sha256` de la décision humaine, selon
l'ADR-0047. La vérification de l'ensemble scellé et de son reçu reste celle
du chargeur de preuve existant ; la projection ne la duplique pas. Une
admission n'efface jamais la détection : la valeur projetée reste
`DETECTED_REVIEWED_ACCEPTED`.

### 5. Un successeur adopte les artefacts acquis, sans les réécrire

Mesuré : les 479 placements de V2 déjà acquis en staging sont liés à V2 par
le `release_id` de leur payload, et **toute** la chaîne — rattrapage
d'attribution, faits de l'attestation batch, projection, Worker B — les
sélectionne par ce `release_id`. Aucun mécanisme ne permet à une release
successeur de les couvrir. Il reste deux gestes, tous deux refusés : réécrire
les payloads acquis (une réécriture silencieuse de faits historiques), ou
réingérer les mêmes octets sous la nouvelle identité (une réingestion de
convenance, bloquée d'ailleurs par l'unicité `(collection, dedup_key)`).

Décision : une table d'**adoption**, en ajout seul (migration de contrôle
`018`). Une ligne y dit qu'un placement acquis sous le prédécesseur est
couvert par le successeur, et nomme les preuves du successeur qui le fondent
— manifeste, inventaire, actualité, PII — ainsi que l'actualité du
placement dans le vocabulaire du produit. L'adoption exige l'égalité exacte,
placement par placement, de tout ce qui n'est pas une autorité corrigée :
collection, contenu, identifiants de placement, type documentaire,
provenance, nombre de chunks, autorisation de scope. Un écart est un refus,
jamais une adoption partielle.

Les lignes acquises ne sont ni modifiées ni supprimées. Les faits de
l'attestation batch d'un successeur se lisent dans ses adoptions ; ceux d'un
prédécesseur, inchangés, dans les payloads.

## Ce que cette ADR ne fait pas

- Elle ne transforme **aucun** `REVIEW_REQUIRED` en instantané : la
  disposition vient de la matrice de servabilité, produite par la politique
  adoptée. Le producteur ne la décide pas.
- Elle ne réintroduit pas les contenus archivés : `NOT_CURRENT_DECLARED_BY_SOURCE`
  n'est pas publiable, et le registre d'exclusion ADR-0055 reste l'autorité
  des quatre contenus qu'il écarte.
- Elle ne modifie pas V2 en place. Une release honnête est un **successeur**,
  avec une identité neuve (ADR-0050), et ses propres revues.
- Elle n'affiche rien à l'utilisateur. Que le cockpit signale ou non un
  instantané est une décision produit distincte, que le produit peut
  désormais prendre puisque la donnée existe.

## Conséquences

- Les 315 contenus que la gouvernance a déclarés servables deviennent
  publiables **sans** qu'une vérification réseau leur soit attribuée.
- Une release existante publiée en `'current'` ne peut pas être requalifiée
  en silence : la migration `005` est additive et ne réécrit aucune ligne.
- La migration produit `005` doit être appliquée avant toute publication
  d'un instantané ; sans elle, l'écriture est refusée par la contrainte.

## Annexe — format `MULTILEVEL_ARTIFACT_CURRENTNESS_V3`

Clés de document (exactes) : celles de V2, plus trois liaisons.

```text
evidence_kind                      "MULTILEVEL_ARTIFACT_CURRENTNESS_V3"
school_year, candidate_inventory_sha256, corpus_manifest_sha256,
sealed_catalog_sha256, placement_catalog_sha256, catalog_delta_sha256,
effective_catalog_authority_sha256, currentness_audit_sha256,
decision_basis                     (inchangées depuis V2)
currentness_policy_id              "NEXUS-RAG-CURRENTNESS-POLICY-V1"
currentness_policy_sha256          empreinte des octets de la politique appliquée
servability_matrix_sha256          empreinte des octets de la matrice dont les dispositions dérivent
counts                             {unique_artifacts, evaluated, VERIFIED_CURRENT,
                                    OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE,
                                    NOT_CURRENT_DECLARED_BY_SOURCE, UNKNOWN}
partition                          {VERIFIED_CURRENT: [...], OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE: [...],
                                    NOT_CURRENT_DECLARED_BY_SOURCE: [...], UNKNOWN: [...]}
artifacts                          une entrée par CONTENU (jamais par placement)
```

Clés d'une entrée (exactes) :

```text
content_sha256, exact_path, collections, placement_facts,
current_for_school_year            (inchangées depuis V2)
currentness_disposition            l'une des quatre dispositions
source_status                      statut de source de la matrice, verbatim
provenance_url                     URL de provenance institutionnelle
fallback_conditions                {OFFICIAL_INSTITUTIONAL_PROVENANCE, CONTENT_SHA_PROVENANCE_MATCH,
                                    SOURCE_STATUS_NOT_EXPLICIT_ARCHIVE, NO_KNOWN_SUPERSEDING_CONFLICT}
                                    → booléens, ou null hors instantané
effective_currentness, current_source_listing_url, current_download_url,
current_download_sha256, byte_identity
                                   faits de vérification réseau : exigés pour VERIFIED_CURRENT,
                                   null pour toute autre disposition
reason_codes, drive_modified_time  (inchangées depuis V2)
```

Règles du chargeur, par disposition :

| Disposition | Exige | Refuse |
|---|---|---|
| `VERIFIED_CURRENT` | règles V2 de `CURRENT` ; `effective_currentness = "actuel"` | un audit frère `currentness_status = CURRENTNESS_UNVERIFIED_SOURCE_UNREACHABLE` |
| `OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE` | `provenance_url` en `https` sur `eduscol.education.gouv.fr` ou `www.education.gouv.fr` — la provenance de l'artefact, page de listing ou URL de fichier officielle, celle que le catalogue scellé enregistre ; les quatre conditions présentes et `true` ; `source_status` non vide | tout fait de vérification non null ; un `source_status` contenant `ARCHIVE` |
| `NOT_CURRENT_DECLARED_BY_SOURCE` | `source_status` contenant `ARCHIVE` | tout fait de vérification ; toute condition de repli |
| `UNKNOWN` | — | tout fait de vérification ; toute condition de repli |

Correspondance avec le produit : `VERIFIED_CURRENT` → `current`,
`OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE` → `official_snapshot`. Les deux
autres ne sont jamais publiées. L'URL de source d'un placement publié est
l'URL de téléchargement pour `VERIFIED_CURRENT`, l'URL de provenance pour un
instantané : on ne cite pas un téléchargement qui n'a pas eu lieu.
