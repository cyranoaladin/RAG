# ADR-0052 — Dimensions légitimes de cross-check des scopes de retrieval production

- **Statut** : Proposé — HUMAN GATE requis sur la PR
- **Date** : 2026-09-19
- **Décideur attendu** : reviewer humain habilité, lié au HEAD exact de la PR
- **S'appuie sur** : ADR-0038, **ADR-0045**, **ADR-0048**

> Cette ADR décrit **comment un cross-check se lit**. Elle n'autorise aucun
> scope, n'approuve aucune audience, n'élargit aucun droit, ne promeut aucun
> contenu et n'émet aucun artefact. Elle ne lève aucun verrou de gouvernance.

## Contexte — pourquoi

ADR-0048 a doté le dépôt d'un émetteur canonique
(`packages/contracts/scripts/build_retrieval_scope_artifacts.py`) qui croise
les dimensions déclarées par les placements d'un subject avec celles de la
politique nommée, et qui **refuse** en cas de divergence. Il a été conçu sur la
famille multi-niveaux, où les dix dimensions croisées coïncident exactement.

Appliqué à la famille **profils production**, cet émetteur refuse les onze
collections de `production-profile-gate-2026-2027-v2`, dès la première liaison :

```
prod_dgemc_terminale_option_v2 :
  visibility du sujet 'public' ≠ visibility de la politique 'internal'
```

Deux dimensions divergent, systématiquement et sur les onze collections :

| Dimension | Placements de la release | Politique (scope `prod_*_v1`) |
|---|---|---|
| `visibility` | `public` | `internal` |
| `programme_version` | `EDUSCOL_CORPUS_20260808` | `BOEN_special_…` |

Trois faits établis conditionnent la décision.

**La divergence est préexistante, pas introduite par le rescellement V2.** Les
placements de la release V1 (`profile_gate/`) portent déjà `public` et
`EDUSCOL_CORPUS_20260808`. Les scopes `prod_*_v1` ont été **écrits à la main**
puis épinglés au registre fermé (ADR-0048, « Contexte ») : ils ne sont jamais
passés par ce croisement.

**`visibility` ne porte pas le même objet des deux côtés.** Côté release, il
qualifie l'**ouverture du matériau source** : le corpus est public. Côté scope,
ADR-0045 a décidé `visibility=internal` — une **politique d'accès au service**,
délibérément plus restrictive que l'ouverture du matériau.

**`programme_version` ne porte pas le même objet non plus.** Côté placements,
`EDUSCOL_CORPUS_20260808` est un identifiant de **corpus de provenance**. La
référence de programme officielle existe, gouvernée, ailleurs dans la release
elle-même : `programme_registry.json`, de genre
`NEXUS_PROGRAMME_INDEX_REGISTRY_V3`, déclare pour chacune des onze collections
un `programme_version` BOEN et le digest de la taxonomie qui le porte. Vérifié
sur l'intégralité des onze : **il coïncide exactement** avec le
`programme_version` des scopes. Il n'y a donc aucun conflit de programme —
seulement une lecture à la mauvaise source.

La tentation est de retirer ces deux dimensions du croisement. Ce serait un
fallback permissif : le contrat écrit de l'émetteur est « une divergence est un
REFUS, jamais un élargissement silencieux », et AGENTS.md interdit qu'un « vert »
soit obtenu en rétrécissant la garde qui le mesure.

## Décision — quoi

### 1. Trois familles de dimensions, et non une liste unique

Les douze dimensions d'autorisation se répartissent ainsi, pour **toutes** les
familles de release :

| Famille | Dimensions | Règle |
|---|---|---|
| **Curriculaires** | `collection`, `tenant`, `niveau`, `voie`, `matiere`, `statut_enseignement`, `candidat`, `school_year` | égalité stricte placements ↔ politique |
| **Politique seule** | `audiences`, `rights` | lues chez la politique ; aucune contrepartie en release |
| **Croisées par règle** | `programme_version`, `visibility` | §2 et §3 ci-dessous |

Aucune famille n'est vide, et **aucune dimension n'est retirée du contrôle**.
Retirer une dimension du croisement est désormais explicitement interdit : une
dimension se déplace vers une autre règle, jamais vers l'absence de règle.

### 2. `programme_version` — changement d'autorité, pas d'abandon

Le champ `programme_version` des **placements** est reclassé pour ce qu'il est :
un identifiant de corpus de provenance. Il est renommé, dans le registre de
politique, `corpus_provenance_id`, et **cesse** d'être comparé par égalité au
`programme_version` de la politique.

Il n'est pas pour autant ignoré. L'émetteur doit, en fail-closed :

1. exiger sa **présence** et son univocité sur tous les placements du subject ;
2. croiser le `programme_version` de la politique avec celui que déclare
   `programme_registry.json` (`NEXUS_PROGRAMME_INDEX_REGISTRY_V3`) **de la
   release traitée**, digest vérifié, pour la collection traitée ;
3. **refuser** si la collection est absente de ce registre de programme, si le
   digest ne correspond pas, ou si les deux valeurs diffèrent.

Le contrôle est donc **renforcé** : il s'exerce contre une autorité de
programme sourcée et digestée, au lieu d'un champ qui ne le portait pas.

### 3. `visibility` — un ordre de restriction, jamais une suppression

Deux notions distinctes sont nommées séparément :

- `evidence_visibility` — l'ouverture du matériau source, déclarée par les
  placements ;
- `policy_visibility` — la politique d'accès du scope servi, déclarée par la
  politique gouvernée.

L'ordre de restriction croissante retenu, sur les quatre valeurs du contrat
(`RetrievalScopeArtifactV2.evidence_subject.visibility`) est :

```
public  <  internal  <  restricted  <  private
```

Règle, en fail-closed :

- `policy_visibility` **au moins aussi restrictive** que `evidence_visibility`
  est admise — c'est le cas `public` → `internal` d'ADR-0045 ;
- `policy_visibility` **moins restrictive** que `evidence_visibility` est un
  **REFUS** de l'émetteur, sans exception et sans option de contournement ;
- une valeur hors de l'ordre déclaré est un refus ;
- un élargissement délibéré exige une ADR propre qui le nomme collection par
  collection. Aucune ADR ne l'accorde à ce jour, et celle-ci ne l'accorde pas.

### 4. Ce qu'un émetteur n'a plus le droit de faire

- restreindre le jeu de dimensions croisées selon le genre d'autorité de
  politique, ou selon toute autre condition ;
- traiter l'absence d'une dimension chez les placements comme une dispense de
  contrôle ;
- déduire une dimension d'autorisation de la release ;
- émettre pour une collection dépourvue de politique sourcée (cf. ADR-0053).

## Conséquences

- l'émetteur devra lire le registre de programme de la release, entrée
  supplémentaire nommée et digestée, dans la PR technique qui suivra ;
- le croisement passe de 10 dimensions comparées « à plat » à 8 égalités
  strictes + 2 règles explicites, soit **12 dimensions toutes sous contrôle** ;
- la famille profils production redevient émissible par l'émetteur canonique,
  **sans** qu'aucune garde ne soit affaiblie ;
- les scopes `*_v1` restent inchangés, packagés et adressables ;
- aucune release, aucun manifeste scellé, aucun compteur de readiness n'est
  modifié par cette ADR.

## Ce que cette ADR n'autorise pas

Elle n'autorise aucune émission de scope, aucune activation, aucun
`current switch`, aucune écriture en base production, aucun démarrage de
staging, et ne rend la release V2 ni promue ni promouvable. Elle ne crée de
politique pour aucune collection : les collections sans politique sourcée
restent bloquantes au titre d'ADR-0053.
