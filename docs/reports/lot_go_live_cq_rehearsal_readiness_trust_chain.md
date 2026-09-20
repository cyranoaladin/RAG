# LOT_GO_LIVE_FINAL_CQ_REHEARSAL_READINESS_TRUST_CHAIN

- **Branche** : `go-live/cq-rehearsal-readiness-trust-chain`
- **Base** : `24b28d41` (#236)
- **Décision attendue** : `GO_LIVE_CQ_REHEARSAL_READINESS_TRUST_CHAIN_PR_OPEN_WITHOUT_ANCHOR`
- **ADR** : ADR-0057
- **S'appuie sur** : ADR-0036, ADR-0056

> Ce lot **n'autorise aucune exécution**. Il ne crée aucune clé, ne publie
> aucune ancre, ne signe aucun manifeste, ne contient aucun placeholder.
> Livrée telle quelle, la chaîne existe et refuse tout — ce qui est
> exactement le comportement d'une chaîne sans autorité.

## Le fait qui force ce lot

Le point d'entrée d'ingestion de release scellée appelle
`enforce_readiness_gate()`, comme Worker A. Sur le staging réel :

```
WORKER_READINESS_GATE_FAILED: NEXUS_EXPECTED_READINESS_PROTOCOL must explicitly pin V1 or V2
WORKER_READINESS_GATE_FAILED: NEXUS_READINESS_MANIFEST_PATH is not configured
```

Il n'existe, ni dans le dépôt ni sur l'hôte, aucune ancre de répétition,
aucun manifeste de répétition, aucune variable `NEXUS_READINESS_*`. Worker A
n'a donc jamais été démarrable sur ce staging non plus.

## Le piège refusé

Réutiliser `NEXUS-PRODUCTION-READINESS-V1` en mode répétition aurait demandé
d'affirmer **vingt-six faits de déploiement de production** pour une
exécution qui ne déploie rien : `environment: "production"` par littéral,
`gate_result: "pass"`, un `release_tag`, sept digests de preuves de
promotion, le digest du compose de production résolu, un run du workflow de
promotion.

Ce n'est pas une formalité pénible : c'est une fabrication de faits. Le
détail du calcul est dans ADR-0057 § « Le piège qu'on refuse ».

## Ce que le lot livre

| Fichier | Rôle |
|---|---|
| `docs/adr/ADR-0057-chaine-de-readiness-de-repetition.md` | la décision |
| `packages/contracts/src/nexus_contracts/staging_readiness.py` | le contrat `NEXUS-STAGING-READINESS-V1` |
| `services/rag-engine/src/ingestor/ingestion_profiles/staging_readiness_gate.py` | le gate, ses cinq variables, ses durcissements |
| `services/rag-engine/scripts/sign_staging_readiness_manifest_cli.py` | l'outil de signature |
| `services/rag-engine/src/ingestor/ingestion_worker/sealed_release_ingestion_cli.py` | le point d'entrée, recâblé |
| `docs/runbooks/ceremonie_cle_readiness_repetition.md` | la cérémonie humaine |
| `services/rag-engine/tests/test_staging_readiness_gate.py` | 47 épreuves |
| `services/rag-engine/tests/_source_inspection.py` | lecture du code sans sa prose |

### Ce que le manifeste déclare — et rien d'autre

| Champ | Vérifiable contre |
|---|---|
| `environment: "rehearsal"` | littéral |
| `repository`, `merge_sha` | un commit de ce dépôt (l'outil le vérifie) |
| `worker_image` | digest épinglé, tag refusé (lot CH6) |
| `allowed_release_id` + `allowed_release_manifest_sha256` | la release réellement chargée |
| `control_dsn_differs_from_product` | mesuré à l'exécution, pas cru |
| `issued_at`, `expires_at` | fenêtre ordonnée, expiration vérifiée |

**Une autorisation de répétition expire.** Sans `expires_at`, elle
deviendrait une autorisation permanente que personne n'a décidé d'accorder.

### Les durcissements

- **Aucune valeur de repli.** Les cinq variables n'ont aucun défaut.
  Absente, vide, ou faite d'espaces : même refus. Le cas des espaces est le
  plus traître — la variable « existe », passe un test de présence, et ne
  nomme rien.
- **`NEXUS_READINESS_MANIFEST_SHA256` est vérifié**, pas seulement exigé :
  les octets sont rehachés avant toute vérification de signature.
- **Aucun composant du chemin ne peut être un lien symbolique** — même
  discipline que la chaîne de production.
- **L'ancre de production est refusée nommément**, avant lecture, pour que
  l'opérateur lise un refus plutôt qu'une erreur de parsing.
- **L'autorité nomme un corpus**, pas seulement un hôte : le point d'entrée
  refuse si le manifeste autorise une autre release que celle qu'il charge.

### « rehearsal ≠ production » : trois barrières indépendantes

1. **Le protocole.** L'ancre de production porte
   `NEXUS-PRODUCTION-READINESS-V1` et échoue au parsing d'une ancre de
   répétition — même copiée et renommée.
2. **Le refus nommé** du chemin de l'ancre gouvernée.
3. **Les littéraux** `environment: "rehearsal"` sur le manifeste *et* sur
   chaque clé de l'ancre.

La première suffirait. Les trois existent parce qu'une seule garde, un jour,
se contourne par un chemin auquel personne n'avait pensé.

## Preuves

### Les dix épreuves demandées

| # | Exigence | Test |
|---|---|---|
| 1 | absence de protocole → refus | `test_1_…`, `test_1bis_…vide…`, `test_1ter_…production…` |
| 2 | absence de manifeste → refus | `test_2_…`, `test_2bis_…`, `test_2ter_…empreinte…` |
| 3 | manifeste non signé → refus | `test_3_…`, `test_3bis_…signature_alteree`, `test_3ter_…faits_modifies` |
| 4 | mauvaise ancre → refus | `test_4_…`, `test_4bis_…`, `test_4ter_…` |
| 5 | ancre production en répétition → refus | `test_5_…`, `test_5bis_…copie…`, `test_5ter_…`, `test_5quater_…` |
| 6 | reviewer / clé de fixture → refus | `test_6_…`, `test_6bis_…` (×3 identités), `test_6ter_…` |
| 7 | empreinte divergente → refus | `test_7_…`, `test_7bis_…` |
| 8 | répétition valide → acceptée | `test_8_…`, plus expiration, fenêtre, image non épinglée |
| 9 | production reste stricte | `test_9_…`, `test_9bis_…`, `test_9ter_…`, `test_9quater_…`, `test_9quinquies_…` |
| 10 | le point d'entrée exige ce gate | `test_10_…`, `test_10bis_…`, `test_10ter_…`, `test_10quater_…`, `test_10quinquies_…` |

**La production est prouvée intacte par `git diff` contre `origin/main`** :
`readiness_gate.py`, `production_readiness.py` et
`governance/trust-anchors/production-readiness-v1.json` sont byte-identiques.
Un test échoue si l'un d'eux change.

**La fixture n'est jamais une autorité** : le contrat refuse tout `key_id`
contenant `ephemeral`, `fixture`, `sample`, `dummy` ou `example`, dans
l'ancre comme dans le manifeste. Les trois identités de
`atomic_docker_v2_rehearsal_fixture.py` sont testées nommément. Un test
vérifie en outre qu'aucun module de la chaîne ne la référence.

### Sur les clés utilisées dans les tests

Les tests génèrent une paire Ed25519 **en mémoire**, à chaque exécution.
C'est nécessaire : sans signature vraie, « un manifeste valide est accepté »
ne prouverait rien. Aucune n'est écrite sur disque, aucune n'est commitée.
La frontière posée par l'ADR est nette — un test signe ce qu'il vérifie, une
fixture ne fait pas autorité sur un hôte.

### Exécution mesurée

```
packages/contracts   pytest -q                              839 passed
services/rag-engine  ruff check .                           All checks passed!
services/rag-engine  mypy src                               Success, 143 source files
services/rag-engine  pytest tests/test_staging_readiness_gate.py -q        47 passed
services/rag-engine  pytest -m "not integration"            1 failed, 3850 passed, 11 skipped
```

**Échec préexistant, antériorité prouvée** :
`test_openapi_schema_drift` échoue déjà sur `origin/main` — vérifié depuis un
worktree détaché, même diff, même octet. Ce lot ne touche ni l'API, ni le
schéma publié, ni les dépendances. Il est vert en CI, où l'installation est
propre.

### Deux ajustements de tests existants, tous deux justifiés

**`test_17` (lot CO)** affirmait que le CLI ne contient pas `PG_RAG_DSN`.
C'est devenu faux, et légitimement : le CLI le **lit** désormais, pour
refuser si le DSN de contrôle et celui du produit sont la même connexion. Le
manifeste *déclare* ce cloisonnement ; une déclaration qu'on ne peut pas
contredire ne prouve rien, donc le CLI la mesure. Le test ajouté
(`test_17bis`) vérifie que `PG_RAG_DSN` n'apparaît qu'une fois, dans la garde
de séparation, et qu'une seule connexion est ouverte — celle du plan de
contrôle.

**`test_22bis`** remplaçait `enforce_readiness_gate` par un double. Le
symbole n'existe plus dans ce module ; le test vise maintenant
`enforce_staging_readiness_gate`, et prouve la même chose.

## Ce que ce lot ne livre pas, et pourquoi

Ni clé privée, ni clé publique, ni ancre, ni manifeste signé, ni placeholder.
Une clé qu'un outil automatique génère et conserve est éphémère par nature ;
l'ancre de production le dit déjà pour elle-même : *« private key held
offline outside this repository/host »*.

La cérémonie est décrite pas à pas dans
`docs/runbooks/ceremonie_cle_readiness_repetition.md` : le propriétaire
génère la paire hors dépôt et hors hôte, transmet **uniquement** la clé
publique et un `key_id`, l'ancre est ajoutée par une PR, puis le propriétaire
signe le manifeste.

## Ordre de la suite

CQ et CH6 (#237) sont **cumulatifs** : ni l'un ni l'autre ne suffit. Après
fusion des deux et après la cérémonie — variables `NEXUS_READINESS_*` dans le
secret staging uniquement, vérification de la readiness, tirage de l'image
par digest, exécution du point d'entrée, vérification 11 / 315 / 479 / 8268
et `NEEDS_REVIEW`, preuve — et **seulement ensuite**
`LOT_GO_LIVE_FINAL_CI_LOT42_RELEASE_BATCH_ATTESTATION`.

Worker B ne tourne pas avant que l'attestation LOT42 batch soit enregistrée.
