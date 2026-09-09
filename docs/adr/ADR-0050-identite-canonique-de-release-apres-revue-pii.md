# ADR-0050 — Identité canonique de release après revue PII : V1 reste immuable, aucune release ne se rescelle en place

- Statut : Proposé. Devient Accepté par une review humaine `APPROVED` du
  Code Owner selon ADR-0025, sur le HEAD exact de la PR qui le porte, avec
  le challenge `NEXUS-TRUSTED-REVIEW-V1` sur une ligne autonome.
- Périmètre : gouvernance de l'identité de release RAG (`release_id`) après
  la revue humaine PII scellée par ADR-0047 ; ne crée, ne produit, ne
  rescelle, ne promeut et ne matérialise aucune release. Document de
  décision uniquement.
- S'appuie sur : ADR-0025 (autorité de revue humaine GitHub), ADR-0035
  (liaison de revue scellée), ADR-0047 (décisions humaines de revue PII, par
  contenu), le rapport de qualification post-merge R1G (issue #155,
  commentaire du 2026-09-09).

## Contexte

La release actuellement inscrite dans `release-registry.json` sous
`release_id=production-profile-gate-2026-2027-v1` porte 319 contenus
uniques, 486 placements, 8324 chunks uniques (12403 references
placement-ponderees), 11 collections. Sa chaine de digests est reelle et
verifiee ; elle n'a cependant jamais ete materialisee sur la PostgreSQL de
production `korrigo`.

Cette release scelle `profile_gate/pii_evidence.json` sous la politique
`pii_gate_policy_h2b_v5` avec ses 486 bindings declares `CLEARED /
pii_detected=false`. Une mesure ulterieure correctement instrumentee (le
scanner et la revue humaine scellee par ADR-0047) a retrouve des signaux PII
reels sur 23 contenus uniques appartenant a ces memes 319 : la preuve PII
scellee par cette release est donc factuellement erronee pour ces 23
entrees, meme si sa chaine de digests reste intacte et verifiable en tant
que telle.

ADR-0047 est effectivement Accepte : son texte devient Accepte par une
review `APPROVED` du Code Owner selon ADR-0025, sur le HEAD exact de la PR
qui le porte, avec le challenge `NEXUS-TRUSTED-REVIEW-V1`. La PR #142 (qui
porte ADR-0047 et la politique de page PDF ADR-0046) a recu exactement
cela sur son HEAD final `a33c5c33434bdee9f2ad597d67827ddef29cc99f` :
`reviewer=abenrhouma`, `state=APPROVED`, `commit_id=a33c5c33434bdee9f2ad597d67827ddef29cc99f`,
challenge `NEXUS-TRUSTED-REVIEW-V1` present. Le meme constat vaut pour
ADR-0046 (politique de page PDF), porte par la meme PR, sur le meme HEAD,
avec la meme review. Le fait que le texte de ces deux fichiers dise encore
lexicalement « Proposé » est une dette documentaire distincte de leur statut
de gouvernance effectif ; cette ADR ne la corrige pas.

Les 23 decisions humaines existent reellement : `governance/pii-review-decisions/pii-review-2026-09-03-final.json`
(`decision_set_id=pii-review-2026-09-03-final`,
sha256=`2b1974259b1ac4a2a21766b71f3ed586df22722cb969f07bdb3fb0bdaafda469`),
23 decisions, 23 `APPROVED`, 0 `REJECTED`. Comparees par `content_sha256`
aux 319 contenus de la V1 historique : les 23 contenus revus appartiennent
tous a cette V1 (`DECISIONS_OUTSIDE_V1=0`) ; les 319 contenus de V1 comptent
23 detections, et les 23 ont une decision humaine (`V1_DETECTED_WITH_HUMAN_DECISION=23`,
`V1_DETECTED_WITHOUT_HUMAN_DECISION=0`). La PR #143 qui porte cet ensemble a
recu une approbation humaine valide sur son HEAD final. Ces decisions
constituent donc une autorite gouvernee reutilisable pour toute future
release qui contiendrait exactement les memes `content_sha256` sous les
memes instruments lies (politique, scanner, foyer de pages, paquet de
revue).

Une candidate posterieure a projete cette revue humaine sur un corpus plus
large : 320 contenus, 488 placements, 8421 chunks uniques, 11 collections.
Son rapport de production lui donne pourtant `FINAL_RELEASE_ID=production-profile-gate-2026-2027-v1`,
alors qu'elle est semantiquement differente de la V1 reelle. Il n'existe pas
aujourd'hui deux entrees conflictuelles dans `release-registry.json` — celui-ci
ne contient qu'une seule entree pour cet identifiant, celle de la V1 reelle
319/486/8324. Il s'agit d'une collision nominale et documentaire (le meme
libelle employe dans deux documents pour designer deux chaines scellees
differentes), pas d'une collision active du registre. Cette candidate est
elle-meme emise `PROMOTION_STATUS=NOT_PROMOTABLE` / `ACTIVATION_STATUS=NO_PRODUCTION_ACTIVATION`
et porte encore des gates d'integration ouverts.

## Décision

### 1. La V1 historique est un enregistrement immuable, jamais rescellee en place

```text
V1_STATUS=IMMUTABLE_HISTORICAL_RECORD
V1_IN_PLACE_RESEAL=FORBIDDEN
```

`production-profile-gate-2026-2027-v1` (319/486/8324/12403, 11 collections)
reste figee telle qu'elle a ete scellee. Toute modification de son corpus,
de ses placements, de ses chunks, de sa chaine PII, de son type de release,
de ses autorites ou de son digest qui changerait sa semantique exige une
nouvelle identite de release, jamais une ecriture sur l'identite existante.
Cette decision ne revoque ni ne detruit V1 : elle reste la preuve exacte de
ce qui a ete reellement scelle a l'epoque, y compris de sa preuve PII
aujourd'hui reconnue erronee pour 23 entrees. Cette preuve historique n'est
pas corrigee in situ.

### 2. Aucune materialisation retroactive de la V1 historique en production

```text
RETROACTIVE_V1_PRODUCTION_MATERIALIZATION=FORBIDDEN
```

ADR-0047 decide explicitement l'admission PII « sans grandfathering des
contenus servis » : le fait qu'un contenu ait deja figure dans une ancienne
release ne dispense pas une future materialisation des exigences actuelles.
Cette regle s'applique en particulier a une materialisation nouvelle,
aujourd'hui, d'une V1 qui n'a jamais existe sur `korrigo` : on ne cree pas en
2026 un nouvel etat PostgreSQL en le presentant comme la materialisation de
l'ancienne V1 alors que l'autorite contemporaine (ADR-0047, effectivement
Acceptee) a demontre qu'une partie de sa preuve d'admissibilite PII est
factuellement erronee pour 23 des 319 contenus concernes.

### 3. La candidate 320/488/8421 ne peut pas reutiliser l'identite de V1

```text
REUSE_OF_V1_RELEASE_ID_FOR_320_CORPUS=FORBIDDEN
CURRENT_320_CANDIDATE_PRODUCTION_AUTHORITY=NO
```

La candidate post-revue (320 contenus, 488 placements, 8421 chunks uniques,
11 collections, revue PII humaine correctement projetee) est semantiquement
distincte de la V1 reelle : elle ne peut pas porter
`production-profile-gate-2026-2027-v1` comme identite finale, quel que soit
le document qui l'affirme. Elle est en outre emise `NOT_PROMOTABLE` /
`NO_PRODUCTION_ACTIVATION` et porte encore des gates d'integration ouverts
(§5) : elle ne constitue pas aujourd'hui une autorite de production et ne
peut pas etre utilisee directement pour C05a. Elle est un intrant candidat
pour la prochaine release, pas cette release elle-meme.

### 4. Une nouvelle identite de release canonique est requise

```text
NEW_CANONICAL_RELEASE_ID_REQUIRED=YES
HISTORICAL_V1_REMAINS_IMMUTABLE=YES
CURRENT_320_CANDIDATE_REUSES_V1_ID=FORBIDDEN
NEW_RELEASE_ID=TBD_BY_GOVERNED_SEALING
```

La prochaine release de production doit porter une identite distincte de
`production-profile-gate-2026-2027-v1` et de toute identite deja utilisee
(y compris la candidate `production-profile-gate-2026-2027-v2-candidate-candidate-v2-20260904T084521Z`
deja presente dans `rehearsal_v2/`). Cette ADR ne decide pas automatiquement
que cet identifiant sera `production-profile-gate-2026-2027-v2` : aucune
regle de nommage existante dans ce depot n'impose precisement ce format pour
une release de ce type. Le choix exact de `NEW_RELEASE_ID` reste `TBD_BY_GOVERNED_SEALING`
(a determiner au moment du scellement gouverne), sous les contraintes
suivantes :

- different de toute identite existante (V1, les identites de
  `rehearsal_v2/`, et de toute identite deja documentee) ;
- stable et deterministe une fois publie ;
- jamais reutilise pour une autre chaine scellee ;
- lie a son propre digest (aggregate, artefacts, placements, chunks,
  autorites) ;
- une identite semantique ne peut designer qu'une seule chaine scellee (§6).

### 5. Gates a fermer avant tout scellement/promotion de la nouvelle release

```text
NEW_PRODUCTION_PROMOTION_BEFORE_REQUIRED_GATES_PASS=FORBIDDEN
```

Ce depot distingue deja la production d'une candidate (`build_production_profile_release.py`,
`promotion_status`) de sa promotion en production (`activation_status`,
gates de go-live) : c'est donc la promotion en production de la future
release, pas sa seule production en tant que candidate, que cette ADR
interdit avant fermeture des blockers ci-dessous, prouves depuis l'etat
courant du depot au commit `f6fe504e61b56836cf251f2efd53409e5cc91217` (non
re-executes dans cette PR, seulement verifies presents) :

- `services/rag-engine/tests/integration/test_h2c_governed_rehearsal.py:142`
  — `pytest.skip("répétition réelle H2-C non demandée", allow_module_level=True)` ;
- `services/rag-engine/tests/integration/test_multilevel_real_ingestion.py:185`
  — `pytest.skip("multilevel real ingestion not requested", allow_module_level=True)` ;
- `services/rag-engine/tests/integration/test_multilevel_worker_cli_e2e.py:102`
  — `pytest.skip("multilevel subprocess CLI acceptance not requested", allow_module_level=True)` ;
- la fraicheur de la candidate (`CURRENTNESS_FRESHNESS=UNVERIFIED_SOURCE_UNREACHABLE`,
  `verified_at=null`), explicitement non fermee pour `GO_LIVE_READY` par le
  rapport qui l'a produite.

### 6. Regle durable : un `release_id` publie ne designe jamais deux chaines differentes

```text
RELEASE_ID_IMMUTABLE_AFTER_PUBLICATION=YES
SAME_RELEASE_ID_DIFFERENT_SEMANTIC_CHAIN=FORBIDDEN
```

Un `release_id` publie ne peut jamais designer deux corpus, deux ensembles
de placements, deux ensembles de chunks ou deux chaines d'autorite
semantiquement differents. Un rescellement semantiquement significatif
produit toujours une nouvelle identite ; aucune modification silencieuse
d'une release existante n'est admissible. Cette regle ferme la classe de
defaut qui a permis la confusion documentaire du §Contexte : elle s'ajoute,
sans les remplacer, aux garanties deja fournies par le code (`ingestor.release_readiness`
resout l'identite par la chaine de digests, jamais par le seul libelle) et
par `release-registry.json` (unicite de `release_id` a l'interieur d'un
meme registre).

### 7. Ce qui peut etre reutilise sans reecriture pour la future release

Lorsque leurs liaisons concordent avec la future release (memes `content_sha256`,
meme politique, meme scanner, meme foyer de pages, meme paquet de revue) :

- les 23 decisions humaines PII et leur reçu, l'ancre de confiance
  associee ;
- les octets sources des PDF inchanges et leurs identites `content_sha256` ;
- les profils d'ingestion existants et valides ;
- les artefacts d'embedding/reranker si leur autorite reste valide ;
- l'exporteur R1G qualifie ;
- le contrat `ResourceRegistryBootstrap`.

```text
R1_QUALIFIED_EXPORTER_REUSABLE=YES
```
(qualification actuelle : `f6fe504e61b56836cf251f2efd53409e5cc91217`)
```text
RESOURCE_REGISTRY_BOOTSTRAP_CONTRACT_REUSABLE=YES
```

Aucune decision PII n'est reecrite ni reemise par cette ADR ou par la future
release : les 23 decisions scellees restent celles qui font autorite pour
les `content_sha256` qu'elles couvrent.

### 8. Impact consommateur (C05a / Nexus), documente sans rebasculer maintenant

```text
C05A_HISTORICAL_V1_BASELINE=SUPERSEDED_FOR_FUTURE_EXECUTION
RAG_ISSUE_155_REBASE_REQUIRED=YES
NEXUS_C05A_REBASE_REQUIRED=YES
REBASE_BEFORE_NEW_RELEASE_EXISTS=NO
```

L'issue RAG #155 et la chaine consommateur Nexus C05a sont aujourd'hui
epinglees sur les cardinalites de la V1 historique. Cette ADR ne modifie pas
l'issue #155 et ne modifie aucun contrat ou depot Nexus : l'impact
consommateur est seulement documente ici. Le rebaseline explicite de #155 et
de C05a n'intervient qu'apres l'existence reelle de la nouvelle release
canonique — on ne rebascule jamais un consommateur sur une release
hypothetique.

## Conséquences

- Aucune release n'est creee, produite, rescellee, promue ou materialisee
  par cette ADR : `NEW_RELEASE_CREATED=NO`, `NEW_RELEASE_SEALED=NO`,
  `RELEASE_REGISTRY_CHANGED=NO`, `PROFILE_GATE_RELEASE_CHANGED=NO`.
- La collision nominale documentaire entre l'identite de V1 et celle de la
  candidate 320/488/8421 reste, pour l'instant, un fait documente et non
  corrige ailleurs que par cette decision ; sa correction dans les rapports
  historiques n'est pas faite par cette ADR.
- La collision de numerotation preexistante autour d'« ADR-0046 » (deux
  documents distincts portant ce numero) n'est pas corrigee par cette ADR.
- Toute future PR qui scelle la nouvelle release devra citer cette ADR et
  satisfaire integralement §4 a §6 avant toute promotion en production.

## Preuves

- Registre de release courant : `services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json`
  (une seule entree pour `production-profile-gate-2026-2027-v1`).
- Preuve PII V1 : `services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate/pii_evidence.json`.
- Decisions PII humaines : `governance/pii-review-decisions/pii-review-2026-09-03-final.json`
  et son reçu `governance/pii-review-bindings/pii-review-2026-09-03-final.json`.
- Rapport de qualification post-merge R1G : commentaire du 2026-09-09 sur
  l'issue #155.
- Rapport de la candidate post-revue : `docs/reports/lot_1_2_candidate_v2.md`.
