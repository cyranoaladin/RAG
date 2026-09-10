# NEXUS-C1-ADR0050-SEMANTIC-AUDIT-V1

Audit du vocabulaire de #153 sous ADR-0050 (`2e0b8fc`, *governance: require a new
canonical release identity after PII review*). Document de gouvernance : aucun code métier.

## Six états à ne plus confondre

| état | définition | vaut pour la V1 aujourd'hui |
|---|---|---|
| `REGISTERED_RELEASE` | inscrite dans `release-registry.json`, chaîne de digests vérifiable | **oui** |
| `SELECTED_RELEASE` | celle que la configuration de déploiement désigne, ou le registre canonique par défaut | oui, quand rien d'autre n'est configuré |
| `PROMOTABLE_RELEASE` | admissible à la promotion, tous gates fermés | **non** — ADR-0050 §5 |
| `MATERIALIZED_RELEASE` | réellement écrite dans la PostgreSQL de production `korrigo` | **non** — jamais matérialisée |
| `SERVED_RELEASE` | servie aux appelants depuis cette matérialisation | **non** |
| `HISTORICAL_RELEASE` | enregistrement immuable de ce qui a été scellé | **oui** — ADR-0050 §1 |

`C1` prouve une propriété de reproductibilité sur `SELECTED_RELEASE`. Il ne prouve rien sur
`MATERIALIZED_RELEASE` ni sur `PROMOTABLE_RELEASE`.

```text
C1_REPRODUCIBILITY_AUTHORITY=SELECTED_RELEASE_REGISTRY_CHAIN
C1_PRODUCTION_MATERIALIZATION_AUTHORITY=false
C1_PRODUCTION_PROMOTION_AUTHORITY=false
```

## Décisions normatives d'ADR-0050, reprises sans les adoucir

```text
V1_STATUS=IMMUTABLE_HISTORICAL_RECORD
V1_IN_PLACE_RESEAL=FORBIDDEN
RETROACTIVE_V1_PRODUCTION_MATERIALIZATION=FORBIDDEN
REUSE_OF_V1_RELEASE_ID_FOR_320_CORPUS=FORBIDDEN
CURRENT_320_CANDIDATE_PRODUCTION_AUTHORITY=NO
NEW_CANONICAL_RELEASE_ID_REQUIRED=YES
NEW_RELEASE_ID=TBD_BY_GOVERNED_SEALING
NEW_PRODUCTION_PROMOTION_BEFORE_REQUIRED_GATES_PASS=FORBIDDEN
RELEASE_ID_IMMUTABLE_AFTER_PUBLICATION=YES
SAME_RELEASE_ID_DIFFERENT_SEMANTIC_CHAIN=FORBIDDEN
```

## Audit ligne à ligne

| path | ligne | phrase | état revendiqué | état réel sous ADR-0050 | statut |
|---|---|---|---|---|---|
| *corps de la PR #153* (distant) | — | « les contenus que la lignée `…-v1` promeut et **sert aujourd'hui** » | SERVED | REGISTERED, jamais MATERIALIZED | **FACTUALLY_STALE** |
| `docs/reports/lot_c1_promoted_coverage.md` | 13 | « un corpus qui n'est plus celui qu'on sert » | SERVED | SELECTED | **FACTUALLY_STALE** — corrigé |
| `docs/reports/lot_c1_promoted_coverage.md` | 30 | « les contenus servis aujourd'hui » | SERVED | SELECTED | **FACTUALLY_STALE** — corrigé |
| `docs/reports/lot_c1_promoted_coverage.md` | 11 | « l'ensemble que la lignée **promeut aujourd'hui** » | ambigu | SELECTED | AMBIGUOUS — encadré normatif ajouté |
| `docs/reports/lot_c1_promoted_coverage.md` | 315 | « GeoGebra s'il est servi comme artefact » | conditionnel | — | CORRECT |
| `scripts/qualification/compute_promoted_content_set.py` | 1 | « la lignée ACTIVE promeut aujourd'hui » | ambigu | SELECTED | AMBIGUOUS |
| `scripts/qualification/compute_promoted_content_set.py` | 4 | « ce que la lignée courante sert » | SERVED | SELECTED | **FACTUALLY_STALE** |
| `scripts/qualification/verify_corpus_cas.py` | 171 | « contenu(s) promu(s) et servable(s) aujourd'hui » | ambigu | SELECTED | AMBIGUOUS |
| `scripts/qualification/verify_corpus_cas.py` | 248 | idem, texte d'aide `--promoted-content-set` | ambigu | SELECTED | AMBIGUOUS |
| `scripts/qualification/tests/test_verify_corpus_cas_promoted_coverage.py` | 6 | « promu aujourd'hui : refus » | ambigu | SELECTED | AMBIGUOUS |
| `scripts/qualification/tests/test_compute_promoted_content_set.py` | 31 | « contre un registre déployé » | nom de mode | — | CORRECT |
| `scripts/qualification/tests/test_compute_promoted_content_set.py` | 747 | « changer ce script change le corpus servi » | SERVED | SELECTED | AMBIGUOUS |

```text
C1_FACTUALLY_STALE_DOCUMENTATION_OCCURRENCES=3   (2 corrigées ici, 1 dans le corps de PR distant)
C1_AMBIGUOUS_DOCUMENTATION_OCCURRENCES=6
C1_CORRECT_OCCURRENCES=2
```

Aucune occurrence n'affirme que la V1 est matérialisée sur `korrigo` : la recherche de
`korrigo`, « en production », « matérialisée en production », « déployée en production » sur toute
la surface #153 ne rend rien.

## Ce qui n'est PAS corrigé ici, et pourquoi

Les six occurrences `AMBIGUOUS` et la `FACTUALLY_STALE` de
`compute_promoted_content_set.py:4` vivent dans des fichiers de code : docstrings, messages
d'erreur et textes d'aide. Deux d'entre eux sont des chaînes que des épreuves peuvent affirmer.
Ce lot est un lot de gouvernance documentaire ; les toucher serait modifier du code. Formulations
proposées, à décider par le propriétaire de C1 :

- « la lignée ACTIVE promeut aujourd'hui » → « la release SÉLECTIONNÉE désigne » ;
- « ce que la lignée courante sert » → « ce que la release sélectionnée désigne » ;
- « promu(s) et servable(s) aujourd'hui » → « désigné(s) par la release sélectionnée ».

## Le code n'a pas besoin de changer

```text
ADR0050_CODE_CHANGE_REQUIRED=false
```
`compute_promoted_content_set`, `release_readiness`, le vérificateur C1, l'autorité de sélection du
P2 et l'implémentation unifiée de F ne dépendent que de l'autorité de registre, de la release
sélectionnée, des empreintes et de l'ensemble de contenus. Aucun ne code en dur d'identité de
release.

```text
HARDCODED_V1_RELEASE_ID_IN_RUNTIME_LOGIC=0
```
Mesuré sur les six fichiers de ces cinq surfaces : zéro occurrence. Les 18 occurrences de
`production-profile-gate-2026-2027-v1` dans le dépôt se répartissent en 16 fixtures ou épreuves
historiques, un commentaire de `r1_operator_flow.py` qui explique l'origine d'une empreinte, et
une constante de module dans `services/rag-pedago/scripts/build_production_profile_release.py:59`.

**Constat à porter au lot « nouvelle release », pas ici :** ce producteur écrit
`RELEASE_ID = "production-profile-gate-2026-2027-v1"` en dur. Une future release construite par ce
script porterait donc l'identité que l'ADR-0050 §3 et §4 interdisent de réutiliser. Ce fichier est
hors des cinq surfaces auditées et hors du périmètre de #153.

## Preuve d'agnosticisme d'identité

Le dépôt porte déjà quatre identités distinctes, dont trois exercées de bout en bout par la
matrice de parité à 39 cas : `production-profile-gate-2026-2027-v1`,
`wave0-exact-grade-troisieme-2026-2027-v1`, `multilevel-2026-2027-v1` et
`production-profile-gate-2026-2027-v2-rehearsal`.

Preuve supplémentaire avec une identité **inédite**, absente de tout le dépôt : la release Wave 0
recopiée avec `release_id=nexus-identity-agnostic-probe-20260909`, structure intacte, chaîne de
digests recalculée.

```text
NEW_RELEASE_ID_RUNTIME_SELECTION_SUPPORTED=true
   mécanisme LEGACY_MANIFEST, identité résolue = nexus-identity-agnostic-probe-20260909, 2 contenus
NEW_RELEASE_ID_C1_SUPPORTED=true
   RELEASE_REGISTRY_SOURCE=DEPLOYMENT_MANIFESTS, RELEASE_AUTHORITY_MECHANISM=LEGACY_MANIFEST
   PROMOTED_CONTENT_SET_COUNT=2
   PROMOTED_CONTENT_SET_SHA256=34b0b5934b344eb32cb1c623bf90bb8fb0865d7aedf9d0e1f4bc91d05e5cc3c0
```
Les deux côtés acceptent l'identité inédite sans branche spéciale, et rendent le même ensemble de
contenus — la même empreinte que le cas `wave0_legacy_pair` de la matrice.

## Ce que C1 ne dit pas

`C1_PASS` ne vaut ni `PRODUCTION_PROMOTION_AUTHORIZED`, ni
`RELEASE_IS_CURRENTLY_MATERIALIZED_IN_PRODUCTION`. La candidate 320/488/8421 reste un intrant :
`CURRENT_320_CANDIDATE_PRODUCTION_AUTHORITY=NO`. Elle n'est branchée ni dans `current`, ni en
production, ni dans le store C1, ni dans C05a.
