# Nexus RAG pédagogique — état du projet et dossier d'audit

Nexus est une plateforme RAG pédagogique pour les candidats libres et les
élèves AEFE. Elle sépare le contrôle des sources et des droits, la publication
des contenus, la recherche dans pgvector et le Cockpit. La chaîne visée est
`source → qualité → gate → revue humaine → release scellée → attestation →
job → publication → retrieval filtré`. La génération de réponses reste
verrouillée.

**Instantané audité : 28 septembre 2026, `main` au commit de base
`5203c737aa41dd2994504e671819b7a1f024d5f1`.** Ce SHA précède le commit
qui portera cette mise à jour du README. Il est une borne de reproductibilité,
pas une affirmation que `main` restera à ce commit. Les
chiffres de release proviennent des artefacts versionnés ; l'état des PR et de
la CI a été relu sur GitHub ; les chiffres du staging DI proviennent des
journaux locaux de l'opérateur, qui ne sont pas versionnés. Aucun accès serveur
ou base n'a été effectué pour rédiger cet instantané. Un audit opérationnel
ultérieur doit relire le serveur, la base dédiée et les preuves signées avant
toute mutation.

Les règles de contribution sont dans [AGENTS.md](AGENTS.md), les décisions
dans [docs/adr](docs/adr), les rapports dans [docs/reports](docs/reports), et
les procédures dans [docs/runbooks](docs/runbooks). Le
[rapport de ce lot documentaire](docs/reports/lot_20260928_readme_audit.md)
trace la méthode et les contrôles. Les sections numérotées
plus bas conservent le détail des fondations historiques ; **la présente
section fait autorité pour l'état au SHA indiqué**.

## Sommaire de l'état audité

- [Verdict et frontière des preuves](#verdict-et-frontière-des-preuves)
- [Architecture et composants](#architecture-et-composants-au-sha-audité)
- [Gouvernance et sécurité](#gouvernance-et-sécurité-au-sha-audité)
- [V4, reprise DI et revue #262](#v4-reprise-di-et-revue-262)
- [Complément HGGSP, option B](#complément-hggsp-option-b)
- [Ce qui reste à faire](#ce-qui-reste-à-faire-avant-le-complément-hggsp)
- [Qualifications et reproduction](#qualifications-et-reproduction-de-laudit)
- [Référence historique](#sommaire-historique)

## Verdict et frontière des preuves

| Sujet | État vérifié au 28 septembre 2026 | Preuve / limite |
|---|---|---|
| Code de référence | `main` = `5203c737aa41dd2994504e671819b7a1f024d5f1` ; les PR [#266](https://github.com/cyranoaladin/RAG/pull/266) et [#267](https://github.com/cyranoaladin/RAG/pull/267) sont fusionnées. | Git et API GitHub, contrôle ponctuel. |
| CI du `main` audité | [CI — Nexus RAG Platform](https://github.com/cyranoaladin/RAG/actions/runs/36407773355) et [Corpus CAS reproducibility (C1)](https://github.com/cyranoaladin/RAG/actions/runs/36407773249) : `success` sur ce SHA. | Exécutions GitHub du 28 septembre 2026, à reconsulter pour un autre SHA. |
| Staging V4 hors HGGSP | Reprise DI clôturée : 9 collections, 263 artefacts, 405 placements, 5 678 chunks, zéro placement HGGSP. | Journaux opérateur locaux et contrôle de clôture, détaillés ci-dessous ; ce dépôt ne contient pas leur transcript complet. |
| Successeur HGGSP | Release complémentaire construite : 2 collections, 52 artefacts, 74 placements, 2 590 chunks. | Manifeste, registre mixte, preuve de build et diff machine versionnés. |
| Autorisation HGGSP | `PROPOSED_INACTIVE` ; aucune image, readiness ni autorité de scopes successeurs activée. | [Proposition](docs/reports/go_live/authorizations/proposed/staging_hggsp_complementary_authorization.json). |
| Revue V4 [#262](https://github.com/cyranoaladin/RAG/pull/262) | `OPEN`, non draft, `APPROVED`, non fusionnée ; HEAD `079461659b60f8a8ce9458145a199599ad822bbc`. | API GitHub relue le 28 septembre 2026 ; son état doit être revérifié avant toute opération. |
| Production publique | **`GO_LIVE: NO_GO`** ; aucun current switch ni déploiement du complément ne découle des fusions #266/#267. | [Runbook go-live](docs/runbooks/go_live.md) et statuts `NO_PRODUCTION_ACTIVATION` des manifests. |

Il faut distinguer trois catégories de faits : **scellé dans Git** (fichiers et
SHA recalculables), **mesuré hors dépôt** (journaux DI locaux conservés par
l'opérateur) et **état live** (PR et CI, susceptible de changer). Le fichier
[go_live_readiness_state.json](docs/reports/go_live/go_live_readiness_state.json)
se déclare lui-même non courant (`snapshot_is_operational_current=false`,
`evaluated_head=470c4b991a4234428d3f1960881d45e9bebf3dfa`) ; il ne
prouve pas une readiness de production au SHA de cet audit. Une CI verte
valide le code et les gardes testées ; elle
ne vaut ni attestation de droits, ni vérification de la base actuelle, ni
autorisation de bascule publique.

## Architecture et composants au SHA audité

| Composant | Responsabilité et frontière | Entrée d'audit |
|---|---|---|
| [`services/rag-pedago`](services/rag-pedago) | Plan de contrôle : référentiels, taxonomies, acquisition, qualité, PII, droits, actualité, releases, revue et attestations. | [Rapport successeur HGGSP](docs/reports/lot_go_live_hggsp_complementary_successor.md) |
| [`services/rag-engine`](services/rag-engine) | Plan de données : PostgreSQL/pgvector, placements d'artefacts, Worker B, retrieval hybride et API v2. Le runtime HTTP `api_v2:app` est limité à la lecture/revue. | [Compose v2](services/rag-engine/infra/docker-compose.v2.yml), [runbook](docs/runbooks/go_live.md) |
| [`services/cockpit`](services/cockpit) | Application Next.js et BFF Auth.js : session humaine, scope dérivé côté serveur, identité interne signée. Aucun accès direct aux documents bruts ou à pgvector. | [Package Cockpit](services/cockpit/package.json) |
| [`packages/contracts`](packages/contracts) | `nexus-contracts` **v0.21.0**, schémas Pydantic partagés et contrat de retrieval ; Python ≥ 3.11. | [pyproject](packages/contracts/pyproject.toml) |
| [`packages/release-chain`](packages/release-chain) | `nexus-release-chain` v0.1.0 : chargeurs et validations canoniques des releases et de la readiness, dont le registre mixte par collection. La pile PDF est optionnelle pour le cœur. | [pyproject](packages/release-chain/pyproject.toml), [ADR-0062](docs/adr/ADR-0062-coexistence-par-collection-v4-et-successeur-hggsp.md) |
| [`packages/pdf-page-policy`](packages/pdf-page-policy) et [`packages/pdf-ocr`](packages/pdf-ocr) | Politique de pages PDF v1.0.0 et OCR v0.1.0 sous contrôle de la chaîne de contenu. | Leurs `pyproject.toml` et tests. |
| [`corpus`](corpus) | Référentiels source et cadrage pédagogique ; la présence d'un document ne prouve pas son admission au retrieval. | [Référentiel candidat libre](corpus/REFERENTIEL_CANDIDAT_LIBRE.md) |

Le flux de recherche part du Cockpit BFF, passe par le contrat partagé et
l'API `rag-engine`, puis applique les scopes de profil et les droits aux
placements publiés. `chunk.collection` indique l'ancre physique d'ingestion ;
pour un artefact gouverné, `rag_artifact_placements` définit dans quelles
collections il est atteignable. Un artefact peut donc être servi dans plusieurs
collections sans duplication physique. La [sonde indépendante](scripts/go_live/staging_retrieval_probe.py)
utilise cette autorité de placement depuis la correction [#265](https://github.com/cyranoaladin/RAG/pull/265),
avec contrôles de collection, profil, visibilité, année, version de programme,
statut actif, actualité, revue et droits.

Le [Compose v2](services/rag-engine/infra/docker-compose.v2.yml) lie le
registre de release et les inventaires de modèles à des SHA fournis par le
déploiement. Le [Compose de promotion](services/rag-engine/infra/docker-compose.production-release.yml)
exige des images par digest provenant de l'inventaire de provenance. Leur
présence dans le dépôt ne signifie pas que le complément HGGSP est déployé.
Le [runbook go-live](docs/runbooks/go_live.md) exige le head du schéma produit
`005_official_snapshot_currentness` (avec `rag_chunks`, `rag_artifacts` et
`rag_artifact_placements`) et la chaîne de migrations `ingestion_control`
jusqu'à `013` pour une cible qualifiée ; les anciennes indications `003`
des lots pilotes ne sont pas suffisantes.
Le modèle d'embedding scellé est `intfloat/multilingual-e5-large` en 1 024
dimensions ; le reranker est `cross-encoder/ms-marco-MiniLM-L-6-v2`.

## Gouvernance et sécurité au SHA audité

- Toute écriture de contenu suit `quality → gate → review`, puis des
  attestations et jobs liés à la release. Ni le Cockpit ni un agent de requête
  ne publie directement dans pgvector. Le contrat interservices est versionné
  dans `packages/contracts` ; voir [AGENTS.md](AGENTS.md) et
  [ADR-0001](docs/adr/ADR-0001-separation-controle-donnees-cockpit.md).
- Les verrous de [pedago_interface_contract.yml](services/rag-pedago/configs/pedago_interface_contract.yml)
  incluent `answer_generation_allowed: false`. Le
  [garde CI](scripts/check-governance-locks.sh) les compare à la baseline ;
  une évolution d'autorité exige l'ADR et la revue prévues par le dépôt.
- Les manifests de release lient les mappings, inventaires, modèles, preuves
  PII, droits, actualité, profils et catalogue par empreinte. La correction
  [#267](https://github.com/cyranoaladin/RAG/pull/267) ajoute le contrôle des
  octets des preuves V4 recopiées, dont les liaisons d'autorité, les
  inventaires de modèles et les descripteurs de catalogue. Une copie altérée
  doit être refusée avant la construction du complément.
- Les scopes de retrieval sont dérivés et approuvés par une autorité r4 ; les
  nouveaux scopes HGGSP doivent être propres au successeur. Les anciens
  scopes et jobs HGGSP V4 ne sont pas adoptés par simple renommage.
- L'API v2 sert la lecture/revue avec identité signée issue du BFF et rôles
  PostgreSQL séparés à privilèges minimaux. Le serveur de production, les
  secrets, les certificats et la base historique `ragdb` restent hors du
  périmètre de cet audit documentaire.

## V4, reprise DI et revue #262

La release source `production-profile-gate-2026-2027-v4` est immuable. Son
[manifeste](services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v4/release-024f8625ebfeb7ce/profile_gate/production-profile-gate.release.json)
a pour SHA-256
`bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be`.
Il décrit historiquement **11 collections, 315 artefacts uniques, 479
placements et 8 268 chunks** ; son statut est `rehearsal`, `PRE_REVIEW`,
`NOT_PROMOTABLE`, `NO_PRODUCTION_ACTIVATION`. Le mapping de sujets V4
[`eduscol_profile_gate_subjects.yml`](services/rag-engine/configs/mappings/eduscol_profile_gate_subjects.yml)
est inchangé, SHA-256
`85a8efa17a9b04659800363ea3386208b46874ca673bdcb0889c6270bfc9c71c`.
Il ne gouverne pas `hggsp`, raison du refus des 74 jobs HGGSP dans la première
publication. [Le rapport DI](docs/reports/lot_go_live_di_partial_v4_worker_recovery.md)
analyse l'incident, le cas « pin sans produit », le 403 GitHub et la reprise
idempotente. La cause exacte du 403 initial n'est pas prouvée
rétrospectivement ; la limitation primaire est une hypothèse étayée, pas un
fait établi.

La [reprise partielle DI](docs/runbooks/staging_v4_partial_recovery_DI_EXECUTION_PLAN.md)
a été autorisée par la [PR #264](https://github.com/cyranoaladin/RAG/pull/264),
après provenance du Worker B par le run GitHub Actions
[`36321957702`](https://github.com/cyranoaladin/RAG/actions/runs/36321957702),
tentative 1, protocole `NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1`. L'image exacte
était
`ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:8980977c6eda1fe2f7545cd9e2cedee4655a6afbd5abea45765780af067175e6`,
construite depuis `fb8a7cc8e85448115a64de8ff5325d639ef9ee70` (arbre
`13971825e149fbe287bce93605f7ccbb182e7c06`). Le Dockerfile avait le
SHA-256 `feeceb7813ad2cfb38e984ceef12cf51088c7054d13045ff03ab30eba57c60de`.
L'artefact d'inventaire `nexus-deployment-image-inventory` a l'ID
`10932683454` et son ZIP le SHA-256
`91fa5c0b3d57eb25b0db7a79969366756f3b09728584c8af68cae97923639696`.
La
[preuve d'image](docs/reports/evidence/staging_worker_image_provenance_di.json)
et l'[autorisation DI](docs/reports/go_live/authorizations/staging_v4_partial_recovery_authorization.json)
épinglent cette identité. La reprise réclamait seulement les neuf
collections non HGGSP et conservait l'empreinte des 74 jobs exclus :
`fef6d99df13b08c3ea02f79f29be94fa5f8d12a639ef7af85989bfcdaba6af31`.

Les **journaux locaux opérateur, non versionnés**, relus pour ce README,
rapportent : les cinq étapes DI (`partial_readiness_install`,
`partial_preflight`, `partial_worker_b_publication`,
`partial_independent_verification`, `partial_closure_check`) terminées ;
Worker B : **329 `succeeded`, 1 `retried`** après HTTP 502, **0
`lease_lost`, 0 rate limit, 0 `dead_letter`**. La vérification produit donne
`PLACEMENTS=9 263 405`, `CHUNKS=5678`, `HGGSP=0` et
`SONDE_RETRIEVAL_V4` réussie (`chunks=8584`, `manques=4`,
`rappel_a_1=8572`, `rappel_a_5=8573`, `refus_egalite=7` ; ce compteur de
sonde ne remplace pas les 5 678 chunks du produit). Le contrôle final émet
`DI_PARTIAL_PUBLICATION_COMPLETE published=405 excluded_pending=74`
avec l'empreinte ci-dessus et `review_closure=NOT_SAFE`. Les comparaisons de
baseline du journal émettent `RAGDB_INCHANGEE`. Les SHA-256 des journaux
locaux `partial-closure.out`, `verification.txt` et de la sortie Worker B sont
respectivement `4f532af1aa8e1332e18a4ed7653ad77337f0950cabf7d0e1c986095057ef494d`,
`b11fcb3eead2358585e6a798c808a53b33658750d95a02cac8935aaf1a18d28a`
et `175c89d9d250a918e5e9fd4ba6ad271e2becd3e679075468f051523c1cc6a78f`.
Ces SHA permettent de reconnaître une copie des preuves, mais les fichiers
locaux doivent encore être fournis à un auditeur indépendant : le README
n'est pas une attestation live de la base.

La revue [#262](https://github.com/cyranoaladin/RAG/pull/262) est restée
ouverte, approuvée et non fusionnée au HEAD exact
`079461659b60f8a8ce9458145a199599ad822bbc` lors du contrôle GitHub.
Le check `trusted-human-review/head-pinned` est `success` sur cette revue ;
la liste GitHub conserve aussi un ancien job `Evaluate trusted human review`
en échec, qui ne doit pas être présenté comme un succès de toute l'histoire
des checks.
Elle continue de gouverner la revue V4 ; les 74 anciens jobs HGGSP doivent
rester intacts jusqu'à publication et vérification du successeur. Le contrôle
de clôture V4 ne peut pas être présenté comme sûr sur les 405 seules.

## Complément HGGSP, option B

L'arbitrage humain du 28 septembre 2026 retient un **complément par
collection**, et non une V5 qui réadopterait les 405 placements V4. La
[décision ADR-0062](docs/adr/ADR-0062-coexistence-par-collection-v4-et-successeur-hggsp.md)
et le [registre mixte v2](services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json)
attribuent explicitement chaque collection servie à une release. Le registre
porte le SHA-256
`59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6`.
Le chargeur valide les manifests complets et refuse collection étrangère,
doublon, collision d'artefact ou divergence de modèle ; la version 1 du
registre conserve sa sémantique.

| Propriétaire dans le registre mixte | Collection | Placements |
|---|---|---:|
| V4 | `rag_nexus_dgemc_terminale_option` | 12 |
| V4 | `rag_nexus_hlp_premiere_specialite` | 115 |
| V4 | `rag_nexus_hlp_terminale_specialite` | 89 |
| V4 | `rag_nexus_nsi_premiere_specialite` | 29 |
| V4 | `rag_nexus_nsi_terminale_specialite` | 47 |
| V4 | `rag_nexus_ses_premiere_specialite` | 30 |
| V4 | `rag_nexus_ses_terminale_specialite` | 28 |
| V4 | `rag_nexus_svt_premiere_specialite` | 19 |
| V4 | `rag_nexus_svt_terminale_specialite` | 36 |
| **Sous-total V4 servi** | **9 collections, 263 artefacts, 5 678 chunks** | **405** |
| Successeur | `rag_nexus_hggsp_premiere_specialite` | 39 |
| Successeur | `rag_nexus_hggsp_terminale_specialite` | 35 |
| **Sous-total HGGSP** | **2 collections, 52 artefacts, 2 590 chunks** | **74** |
| **Union logique visée** | **11 collections, 315 artefacts, 8 268 chunks** | **479** |

Le successeur s'appelle exactement
`production-profile-gate-2026-2027-v5-hggsp`. Son
[manifeste](services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_hggsp_v5/release-b34b11e678bf9559/profile_gate/production-profile-gate.release.json)
porte le SHA-256
`8286388002071e31a4d80d357feb19d802292c862055e6749d9371fc15441daf`.
Le mapping additif
[`eduscol_profile_gate_subjects_hggsp.yml`](services/rag-engine/configs/mappings/eduscol_profile_gate_subjects_hggsp.yml)
porte le SHA-256
`b909c1fb0a8b874b2bbe53cdb1973d5eadce97823c987f4e2b75fefd0d48bb6a`
et ajoute `hggsp: hggsp` au mapping V4 sans le modifier. Le motif de
changement d'autorité cite le commit
`fb8a7cc8e85448115a64de8ff5325d639ef9ee70` qui porte ce mapping.
Mappings de niveau et type de document et modèles E5/reranker sont conservés.

La [preuve de build](docs/reports/evidence/hggsp_v5_complementary_build_proof.json)
et le [diff machine](docs/reports/evidence/profile_gate_v4_to_hggsp_v5_diff.json)
établissent : 52 PDF sur 52 présents avec SHA-256 conforme ; 52 résultats PII
`CLEARED`, zéro détection, avec chaîne de revue source V4 signée préservée ;
deux builds identiques octet pour octet sur 19 fichiers ; 28 fichiers V4
byte-identical à la base ; **zéro intersection** entre les 52 artefacts
HGGSP et les 263 déjà publiés ; aucun des 405 placements V4 servis n'est
inclus dans le complément. Le nombre de 2 590 chunks est recalculé depuis les
autorités scellées et confronté au produit, et non accepté comme constante.
La correction #267 épingle et vérifie aussi les octets des preuves sources
auxiliaires avant la projection.
Le miroir des PDF est **hors dépôt** ; la preuve scelle l'ensemble de contenus
par `content_set_sha256=b76b84b03b8b47e936555f0bb1135b4e0580d702a8f11d353285c928c215619f`.
La preuve PII source V4 porte le SHA-256
`33e3fbfb943ffded360d2db254061edebe8ccff9e08b7509ebcdf4cd305ca700`.
Un auditeur qui veut reconstruire la release doit disposer du même miroir et
revérifier les 52 SHA individuels ; le dépôt seul permet de contrôler les
manifests et les preuves scellées, pas de recréer les PDF absents.

Le produit reste `rehearsal`, `PRE_REVIEW`, `NOT_PROMOTABLE` et
`NO_PRODUCTION_ACTIVATION`. La
[proposition d'autorisation HGGSP](docs/reports/go_live/authorizations/proposed/staging_hggsp_complementary_authorization.json)
est `PROPOSED_INACTIVE` : image Worker B, image retrieval, readiness signée et
autorité des scopes successeurs restent à produire et à lier. Le registre
mixte est un artefact candidat ; sa présence dans Git n'installe aucun
runtime. L'ADR-0062 conserve encore un libellé initial « Proposé » : ses
conditions de revue/fusion ont été remplies par #266/#267, mais ce libellé
documentaire n'a pas été actualisé dans ce lot README.

## Ce qui reste à faire avant le complément HGGSP

Le [plan opérateur HGGSP](docs/runbooks/staging_hggsp_complementary_SUCCESSOR_PLAN.md)
est le chemin gouverné. Chaque étape dépend d'une autorité vérifiée au HEAD
exact ; ce tableau décrit des **travaux à venir**, pas une permission de les
exécuter à partir du README.

1. Construire hors hôte et épingler par digest les nouvelles images Worker B
   et retrieval depuis le `main` fusionné, avec inventaires de provenance.
   Le nouveau chargeur du registre mixte rend les anciennes images
   insuffisantes comme preuve de ces octets.
2. Ouvrir une PR d'activation HGGSP distincte qui lie manifeste, registre,
   images, SHA, opérateur et prévol. Obtenir la revue humaine fiable au HEAD
   exact puis fusionner cette PR avant toute mutation de staging. La
   proposition actuelle sous `proposed/` reste inactive.
3. Produire une readiness **successeur** signée et deux autorisations r4 de
   scopes HGGSP propres à cette lignée ; les relire et les enregistrer par le
   mécanisme canonique. Préserver la readiness V4.
4. Lier/acquérir les 74 placements sous la nouvelle release, établir la
   proposition de revue batch, attendre sa décision humaine distincte,
   enregistrer 74 attestations et créer 74 **nouveaux** jobs. Vérifier à
   chaque prévol les 405 placements V4 et l'empreinte inchangée des 74 anciens
   jobs HGGSP V4.
5. Publier uniquement les deux collections HGGSP avec Worker B borné par
   l'image, la readiness et la liste positive ; un arrêt sûr `75` exige un
   nouveau prévol et une reprise opérateur. Vérifier indépendamment les deux
   scopes HGGSP, les neuf scopes V4, le produit 2/52/74/2 590 et l'union
   11/315/479/8 268, ainsi que la base historique.
6. Après succès de cette vérification, préparer **une autre** autorisation et
   revue pour annuler/invalider canoniquement les 74 anciens jobs et
   attestations HGGSP V4. Décider séparément du traitement de #262, du
   contrôle de fermeture V4, d'une éventuelle promotion de release et du
   déploiement public. Aucun SQL manuel ni current switch n'est autorisé
   par ce plan.

## Qualifications et reproduction de l'audit

Le [rapport HGGSP](docs/reports/lot_go_live_hggsp_complementary_successor.md)
consigne les qualifications du lot #266/#267 : 174 tests producteur/PII/
lignée, 201 tests readiness et gouvernance de sujets, 111 tests retrieval,
44 tests de chaîne C1 (2 ignorés), 22 tests wrapper/orchestrateur, ainsi que
`ruff`, `mypy` ciblé, syntaxe Bash, hygiène, verrous, unicité des autorités,
chargeurs canoniques et reproductibilité. Ces résultats sont des preuves de
lot, **pas** une nouvelle exécution de toutes les suites pour ce README.
La CI GitHub du `main` audité est verte pour les deux workflows indiqués en
tête. La [CI locale](scripts/ci-local.sh) couvre contrats, politiques PDF,
release-chain, services, Cockpit, hygiène, gouvernance, revue humaine fiable
et qualification C1 ; elle renvoie un échec si une cible échoue. Python ≥ 3.11
et Node ≥ 22.22 sont requis. Les cibles `rag-engine` utilisant PostgreSQL
jetable/Docker ne doivent pas être confondues avec une simple lecture du
dépôt.

Pour reproduire **sans serveur ni base**, depuis la racine d'un checkout du
SHA audité :

```bash
git rev-parse HEAD
git status --short
sha256sum \
  services/rag-engine/configs/mappings/eduscol_profile_gate_subjects.yml \
  services/rag-engine/configs/mappings/eduscol_profile_gate_subjects_hggsp.yml \
  services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json \
  services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v4/release-024f8625ebfeb7ce/profile_gate/production-profile-gate.release.json \
  services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_hggsp_v5/release-b34b11e678bf9559/profile_gate/production-profile-gate.release.json
bash scripts/check-governance-locks.sh
bash scripts/check-authority-uniqueness.sh
```

Les cinq SHA attendus, dans cet ordre, sont :
`85a8efa17a9b04659800363ea3386208b46874ca673bdcb0889c6270bfc9c71c`,
`b909c1fb0a8b874b2bbe53cdb1973d5eadce97823c987f4e2b75fefd0d48bb6a`,
`59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6`,
`bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be`,
`8286388002071e31a4d80d357feb19d802292c862055e6749d9371fc15441daf`.
Le calcul suivant lit **en lecture seule** le registre, les sujets et les
artefacts scellés, sans solliciter le moteur ni une base :

```bash
python3 - <<'PY'
import json
from pathlib import Path

registry = Path('services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v4-hggsp-complementary.json')
owners = []
for owner in json.loads(registry.read_text())['releases']:
    base = (registry.parent / owner['manifest_path']).parent
    manifest = json.loads((base / 'production-profile-gate.release.json').read_text())
    placements = [p for subject in manifest['subjects']
                  if subject['collection'] in owner['collections']
                  for p in json.loads((base / subject['path']).read_text())['placements']]
    ids = {p['artifact_id'] for p in placements}
    artifacts = json.loads((base / 'artifacts.release.json').read_text())['artifacts']
    chunks = sum(len(a['chunks']) for a in artifacts if a['artifact_id'] in ids)
    owners.append((owner['release_id'], ids, {p['placement_id'] for p in placements}))
    print(owner['release_id'], len(owner['collections']), len(ids), len(placements), chunks)
assert not (owners[0][1] & owners[1][1])
assert not (owners[0][2] & owners[1][2])
PY
```

La sortie attendue est `production-profile-gate-2026-2027-v4 9 263 405
5678`, puis `production-profile-gate-2026-2027-v5-hggsp 2 52 74 2590`.
Ce calcul de lecture contrôle les cardinalités et la disjonction ; les
chargeurs canoniques et les validations d'autorité testent en plus les SHA,
identités, mappings et statuts.
Pour l'état live, relire [#262](https://github.com/cyranoaladin/RAG/pull/262)
et les workflows du nouveau SHA ; pour l'état du produit, obtenir les
journaux DI aux SHA ci-dessus et une mesure indépendante autorisée de la base
dédiée. **Ne pas transformer un état versionné en constat live.**

## Sommaire historique

Les sections 1 à 20 ci-dessous détaillent les fondations et l'inventaire
historique. Plusieurs mesures y sont datées des premiers lots, notamment
LOT20/LOT41U ; elles ne remplacent pas l'état audité ci-dessus. Les anciens
comptages de fichiers, dettes, chemins pilotes et descriptions de production
ne doivent pas être utilisés comme preuves de la cible DI ou du complément
HGGSP. La procédure courante de qualification de production reste
[docs/runbooks/go_live.md](docs/runbooks/go_live.md).

## Sommaire

- [1. Resume executif](#1-resume-executif)
- [2. Logique metier](#2-logique-metier)
- [3. Etat historique du projet (lots initiaux)](#3-etat-historique-du-projet-lots-initiaux)
- [4. Architecture generale](#4-architecture-generale)
- [5. Arborescence commentee](#5-arborescence-commentee)
- [6. Contrat partage `nexus-contracts`](#6-contrat-partage-nexus-contracts)
- [7. Service `rag-pedago`](#7-service-rag-pedago)
- [8. Service `rag-engine`](#8-service-rag-engine)
- [9. Service `cockpit`](#9-service-cockpit)
- [10. Donnees, corpus et artefacts](#10-donnees-corpus-et-artefacts)
- [11. Flux de bout en bout](#11-flux-de-bout-en-bout)
- [12. Gouvernance et verrous](#12-gouvernance-et-verrous)
- [13. API, authentification et filtrage](#13-api-authentification-et-filtrage)
- [14. Qualite, CI et commandes](#14-qualite-ci-et-commandes)
- [15. Installation et execution locale](#15-installation-et-execution-locale)
- [16. Securite, conformite et limites](#16-securite-conformite-et-limites)
- [17. Production inventoriee (LOT 20)](#17-production-inventoriee-lot-20)
- [18. ADR et historique des lots](#18-adr-et-historique-des-lots)
- [19. Dettes et points d'attention](#19-dettes-et-points-dattention)
- [20. Lecture rapide pour auditeur](#20-lecture-rapide-pour-auditeur)

## 1. Resume executif

Le projet construit une plateforme RAG pedagogique francaise, centree sur deux publics :

- candidats libres au baccalaureat general, principalement Premiere et Terminale ;
- eleves scolarises dans le reseau AEFE, de la Troisieme a la Terminale.

La decision fondatrice est la separation stricte entre trois plans :

- `services/rag-pedago/` : plan de controle. Il porte la taxonomie, les profils, le referentiel officiel, les gates qualite, la revue humaine, le ledger et les agents d'acquisition ou de requete.
- `services/rag-engine/` : plan de donnees. Il porte pgvector, l'indexation, le retrieval et l'API HTTP de recherche en lecture seule.
- `services/cockpit/` : SaaS Next.js et BFF authentifié. Il ne doit jamais acceder directement a pgvector ni aux documents bruts.

La couture entre les plans est `packages/contracts/`, package Python `nexus-contracts`. Il contient les modeles Pydantic qui definissent les profils, documents, chunks, requetes de retrieval, citations, filtres et jetons de profil signes.

Les lots 0 à 22 ont établi les fondations historiques suivantes :

- monorepo en place ;
- contrat partagé `nexus-contracts` v0.2.0 **à cette étape historique**
  (v0.21.0 au SHA audité) ;
- taxonomies pedagogiques multi-niveaux ;
- acquisition gouvernee depuis des sources whitelistes ;
- chunks pilotes Terminale ;
- embeddings pilotes `intfloat/multilingual-e5-large` en 1024 dimensions ;
- manifeste de revue `quality -> gate -> review` ;
- indexation pgvector pilote dans `rag_chunks_pilote` ;
- API `/search` en lecture seule, filtree par profil signe HMAC ;
- agents de requete `context_only`, sans generation de reponse.

Les lots suivants ont livré le Cockpit Next.js, son BFF, l'identité interne
signée, le retrieval hybride et la revue scopée. LOT41U isole leur runtime
lecture/revue dans `api_v2:app`. La generation de reponse reste explicitement
interdite (`answer_generation_allowed: false`).

Lot 19 aligne la documentation entre la production historique et le chemin Nexus gouverne. Lot 20 inventorie la production `rag-ui.nexusreussite.academy` (17 912 vecteurs ChromaDB 768 dim, 6 collections, 3 rubriques UI cassees, code prod divergent du depot). Lot 21 pose l'infrastructure de convergence : ADR-0013 (e5-large 1024 dim + pgvector dedie), catalogue de 22 collections `rag_nexus_*` avec flags d'instanciation, invariant anti-auto-creation, table `rag_chunks` citations-ready (F-01). Lot 22a isole le moteur legacy (config separee `rag_collections_legacy.yml`) du code neuf (resolveur v2 etanche).

L'inventaire LOT20 observait une production historique Streamlit/ingestor en
768 dimensions. Son état live actuel n'est pas déduit du dépôt et cette surface
ne doit jamais être confondue avec le runtime Nexus v2 gouverné.

## 2. Logique metier

### 2.1 Probleme traite

Le produit cible doit aider des eleves ou candidats libres a trouver des ressources pedagogiques fiables, pertinentes pour leur niveau et leur statut, citees, et compatibles avec leurs droits d'acces. Le systeme ne cherche pas seulement a faire de la recherche semantique : il doit prouver que chaque ressource est admissible, correctement etiquetee, et servie au bon profil.

Les exigences metier principales sont :

- retrouver des passages pedagogiques par niveau, matiere, notion et besoin ;
- distinguer le contenu disciplinaire commun du contenu specifique candidat libre ou AEFE ;
- citer chaque ressource avec une source et des droits ;
- refuser la generation ou l'exposition quand la source ou les droits ne sont pas etablis ;
- tracer les decisions d'admission et de revue ;
- empecher un client ou un agent d'elargir lui-meme son perimetre de recherche.

### 2.2 Publics et profils

Le domaine metier encode plusieurs dimensions :

| Dimension | Exemples | Role |
|---|---|---|
| Niveau | `troisieme`, `seconde`, `premiere`, `terminale` | Frontiere principale de retrieval pilote. |
| Voie | `college`, `generale`, `technologique`, `professionnelle`, `aefe`, `unknown` | Contexte de scolarite. |
| Candidat | `scolarise`, `individuel`, `libre`, `cned_reglemente`, `cned_libre`, `aefe`, `both` | Determine notamment l'audience. |
| Status detail | `aefe`, `candidat_libre`, `cned_libre`, `systeme_tunisien`, etc. | Sert aux warnings et a la derivation d'audience. |
| Audience | `libre`, `aefe`, `tous` | Filtre obligatoire de contenu. |
| Matiere | `mathematiques`, `nsi`, `philosophie`, etc. | Axe pedagogique. |
| Statut enseignement | `tronc_commun`, `specialite`, `examen`, etc. | Precision du programme ou de l'epreuve. |

Dans `StudentProfile`, l'audience est derivee ainsi :

- `libre` si le statut detaille est candidat libre ou si le candidat est individuel/libre/CNED libre ;
- `aefe` si le statut detaille est AEFE ;
- `aefe` par defaut pour les autres cas scolarises.

Cette derivation est volontairement conservatrice mais une dette existe pour les cas ambigus hors AEFE.

### 2.3 Corpus pedagogique cible

Le corpus source racine contient des fiches de cadrage en francais :

- `corpus/REFERENTIEL_CANDIDAT_LIBRE.md` ;
- `corpus/Tronc_commun/*.md` ;
- `corpus/Specialites/*.md`.

Ces fichiers donnent le contexte produit et les fiches matiere, mais le contenu de cours exploitable par retrieval est progressivement acquis, nettoye, decoupe, embedde et indexe via `rag-pedago` puis `rag-engine`.

Les sources admises doivent etre :

- officielles ou libres ;
- compatibles avec les droits declares ;
- conformes robots.txt quand elles viennent du web ;
- passees par quality, gate et revue avant indexation.

## 3. Etat historique du projet (lots initiaux)

### 3.1 Snapshot historique de lecture du dépôt

Ces mesures proviennent des lots initiaux et ne valent pas readback du head
courant ni preuve de couverture substantielle :

| Element | Valeur |
|---|---:|
| Fichiers corpus Markdown racine | 14 |
| Fichiers YAML de taxonomie | 26 |
| Taxonomies avec themes pedagogiques | 19 |
| Notions principales | 246 |
| Subnotions | 174 |
| Identifiants notion/subnotion totaux | 420 |
| Fichiers ADR racine | 13 |
| Rapports de lots racine | 47 |
| Chunks pilotes versionnes | 124 |
| Embeddings pilotes versionnes | 124 |
| Chunks approuves dans `review_manifest.json` | 124 |
| Rejets dans `review_manifest.json` | 0 |
| Tests `rag-pedago` | 67 fichiers |
| Tests `rag-engine` | 32 fichiers |
| Tests `packages/contracts` | 2 fichiers |

Repartition taxonomique actuelle :

| Niveau | Identifiants |
|---|---:|
| Troisieme | 49 |
| Seconde | 48 |
| Premiere | 149 |
| Terminale | 174 |

| Matiere / domaine | Identifiants |
|---|---:|
| Mathematiques | 139 |
| Histoire-geographie | 72 |
| NSI | 62 |
| Francais | 35 |
| Philosophie | 26 |
| Physique-chimie | 22 |
| SES | 19 |
| SVT | 17 |
| Orientation candidat libre | 11 |
| Grand oral | 10 |
| SNT | 7 |

### 3.2 Ce qui fonctionne deja

- Validation des modeles metier Pydantic.
- Taxonomies multi-niveaux et validation automatique.
- Fetch gouverne de sources web whitelistes, en GET uniquement, avec robots.txt et rate limit.
- Nettoyage HTML MediaWiki, anti-navigation, controle de substance.
- Parsing de certains programmes officiels PDF en staging.
- Construction de correspondances taxonomie <-> BO.
- Chunking gouverne en artefacts JSONL.
- Embeddings gouvernes avec convention e5 (`passage:` pour chunks, `query:` pour requetes).
- Manifeste de revue qui approuve uniquement les `(chunk_id, chunk_sha256)` valides.
- Indexation pgvector pilote gatee par le contrat de gouvernance `rag-pedago`.
- API FastAPI `/search` lecture seule, filtree par niveau/audience depuis un profil signe.
- Agents de requete qui assemblent un contexte structure sans generer de reponse.
- Cockpit Next.js avec BFF, sessions Auth.js, identité interne signée et routes
  de retrieval/revue scopées.
- Runtime v2 PostgreSQL lecture/revue sans writer ni surface legacy.
- CI locale racine avec contrats, services, garde-fous de gouvernance et validation taxonomie.

### 3.3 Ce qui n'était pas encore livré lors des lots initiaux

- Activation go-live du Cockpit et du moteur, encore bloquée par les preuves
  d'autorité, de corpus et d'exploitation.
- Generation de reponse eleve (`answer_generation_allowed: false`).
- Interface de ressources curees.
- Ingestion generale de vrais documents proprietaires.
- Migration du corpus prod vers le moteur gouverne (9 199 chunks admissibles sur 17 912, cf. LOT 20).
- Deploiement production coherent de l'ensemble Nexus trois plans.
- Ingestion NSI gouvernée de bout en bout (LOT 22, alors en cours ; la
  publication V4/DI ultérieure figure dans l'état audité en tête).

## 4. Architecture generale

### 4.1 Vue d'ensemble

```text
                              profil eleve / intent
                                       |
                                       v
                         +---------------------------+
                         | cockpit SaaS + BFF        |
                         | Next.js, UI par profil    |
                         | pas d'acces direct DB     |
                         +-------------+-------------+
                                       |
                         contrat logique de retrieval
                                       |
                                       v
                         +---------------------------+
                         | rag-engine                |
                         | API /search lecture seule |
                         | pgvector, retrieval       |
                         +-------------+-------------+
                                       ^
                        index pilote  |  embeddings approuves
                                       |
                         +-------------+-------------+
                         | rag-pedago                |
                         | taxonomie, acquisition,   |
                         | gates, review, ledger,    |
                         | query agents context_only |
                         +---------------------------+
```

### 4.2 Frontieres de responsabilite

| Domaine | Proprietaire | Details |
|---|---|---|
| Taxonomie pedagogique | `rag-pedago` | Niveaux, matieres, themes, notions, competences. |
| Referentiel officiel | `rag-pedago` | Sources officielles, examens, statuts candidats, contextes. |
| Admission de sources | `rag-pedago` | Whitelist, droits, robots, revue humaine. |
| Acquisition agentique | `rag-pedago` | Agents orchestrateur/niveau/matiere, depot en staging. |
| Chunking pilote | `rag-pedago` | Artefacts JSONL + sidecars metadata. |
| Embeddings pilotes | `rag-pedago` | `multilingual-e5-large`, 1024d, artefacts locaux. |
| Manifeste de revue | `rag-pedago` | Preuve d'admission par chunk id + sha. |
| Indexation pgvector | `rag-engine` | Lit les artefacts pedago et ecrit dans pgvector. |
| Retrieval HTTP pilote | `rag-engine` | `/search`, lecture seule, filtres serveur. |
| Agents de requete | `rag-pedago` | Signent le profil et assemblent un contexte via l'API. |
| UI SaaS | `cockpit` | Application Next.js et BFF présents au SHA audité. |
| Contrat inter-service | `packages/contracts` | Source unique des modeles partages. |

### 4.3 Invariant majeur : pas de raccourci cross-service

- Le cockpit ne lit jamais pgvector directement.
- Un service n'importe pas le code d'un autre service comme dependance metier.
- La communication se fait par API ou par contrat partage.
- Les verrous de gouvernance vivent dans `services/rag-pedago/configs/pedago_interface_contract.yml`.
- `rag-engine` lit ces verrous pour bloquer l'indexation ou le runtime si l'autorisation n'est pas presente.

## 5. Arborescence commentee

```text
.
|-- AGENTS.md
|-- CLAUDE.md
|-- README.md
|-- corpus/
|-- docs/
|   |-- ROADMAP.md
|   |-- BACKLOG.md
|   |-- adr/
|   `-- reports/
|-- packages/
|   `-- contracts/
|-- scripts/
|-- services/
|   |-- cockpit/
|   |-- rag-engine/
|   `-- rag-pedago/
`-- requirements.lock
```

### 5.1 Racine

| Chemin | Role |
|---|---|
| `AGENTS.md` | Instructions canoniques pour agents de codage. Ne pas le reecrire sans demande explicite. |
| `CLAUDE.md` | Relais vers `AGENTS.md`. |
| `docs/ROADMAP.md` | Phases et lots prevus. Certaines decisions anciennes sont revisees par les ADR plus recents. |
| `docs/BACKLOG.md` | Dettes et ecarts connus. |
| `docs/adr/` | Decisions d'architecture acceptees. |
| `docs/reports/` | Rapports de lots, preuves de CI, preuves d'execution et dettes. |
| `scripts/ci-local.sh` | CI locale racine. |
| `scripts/check-governance-locks.sh` | Garde-fou strict des verrous. |
| `scripts/governance-locks.baseline` | Etat autorise des verrous. |

### 5.2 `corpus/`

`corpus/` contient les fiches source produit et pedagogiques en Markdown. Elles decrivent les programmes, epreuves, coefficients, specificites candidat libre et notes d'indexation RAG.

Sous-dossiers :

- `Tronc_commun/` : EMC, enseignement scientifique, EPS, francais EAF, histoire-geographie, langues vivantes, philosophie.
- `Specialites/` : HGGSP, mathematiques, NSI, physique-chimie, SES, SVT.
- `REFERENTIEL_CANDIDAT_LIBRE.md` : cadrage central du parcours candidat libre.

### 5.3 `packages/contracts/`

Package Python partage `nexus-contracts`, source de verite des schemas d'echange. Il n'a pas d'I/O metier et ne depend pas des services.

### 5.4 `services/rag-pedago/`

Plan de controle : schemas pedagogiques, referentiel officiel, taxonomies, acquisition, gates, review, ledger, chunks, embeddings et agents de requete.

### 5.5 `services/rag-engine/`

Plan de donnees : pgvector, scripts d'indexation pilote, API `/search`, moteur historique Chroma/Ollama/Streamlit et tests.

### 5.6 `services/cockpit/`

SaaS Next.js avec Auth.js, BFF authentifié, scope pilote dérivé côté serveur,
identité interne signée et routes search/chat/collections/review.

## 6. Contrat partage `nexus-contracts`

### 6.1 Statut

`packages/contracts/pyproject.toml` declare :

- nom : `nexus-contracts` ;
- version : `0.2.0` ;
- Python : `>=3.11` ;
- dependance runtime : `pydantic==2.13.4`.

Le package est installe en editable par les `Makefile` de `rag-pedago` et `rag-engine`.

### 6.2 Modules principaux

| Module | Contenu |
|---|---|
| `document.py` | Enums et modeles `DocumentMeta`, `ChunkMeta`, droits, niveaux, voies, types de documents. |
| `chunk.py` | `Audience` et `ChunkMetadata`, sidecar minimal des chunks pour filtrage. |
| `student_profile.py` | `StudentProfile`, derivation `audience`, warnings de coherence. |
| `retrieval.py` | `RetrievalRequest`, `RetrievalNeed`, `RetrievalOptions`, `RetrievalResult`, `RetrievalResponse`, `Citation`. |
| `profile_auth.py` | Signature et verification HMAC de profils niveau/audience. |
| `embedding_utils.py` | Prefixes e5 : `format_passage`, `format_query`. |

### 6.3 Modele de retrieval logique

Le contrat logique complet est :

```text
RetrievalRequest
  student_profile: StudentProfile
  need: RetrievalNeed
  retrieval: RetrievalOptions

RetrievalResponse
  results: list[RetrievalResult]
  warnings: list[str]
  filters_applied: dict
```

`RetrievalRequest.to_payload_filters()` derive les filtres :

- `niveau`
- `voie`
- `matiere`
- `statut_enseignement`
- `candidat`
- `audience`

L'endpoint pilote actuel de `rag-engine` (`POST /search`) est plus minimal : le body contient `query` et `top_k`, tandis que `niveau` et `audience` viennent d'un jeton HMAC signe.

### 6.4 Citations et droits

Une `Citation` porte :

- `source_label`
- `source_uri`
- `rights`
- `page` optionnelle

Les droits sont modelises par `Rights` et `RIGHTS_ALLOWED_CONTEXTS`. Un document dont les droits sont inconnus n'est pas considere retrievable.

### 6.5 Jetons de profil signes

`profile_auth.py` est un module pur, sans FastAPI ni psycopg. Format :

```text
base64url({"niveau":"terminale","audience":"libre"}).hmac_sha256_hex
```

Contraintes :

- niveaux valides : `troisieme`, `seconde`, `premiere`, `terminale` ;
- audiences valides : `libre`, `aefe`, `tous` ;
- signature calculee sur le payload base64url ;
- verification par comparaison constante `hmac.compare_digest`.

## 7. Service `rag-pedago`

### 7.1 Role

`rag-pedago` est le plan de controle. Il determine ce qui peut entrer dans le systeme, comment les contenus sont etiquetes, quelles notions ils couvrent, quand ils sont prets, et quels verrous permettent de passer d'une etape a l'autre.

### 7.2 Sous-systemes

| Chemin | Role |
|---|---|
| `schema/` | Modeles pedagogiques locaux et re-exports du contrat partage. |
| `taxonomy/` | Taxonomies YAML par niveau/matiere/statut. |
| `data/reference/` | Referentiels officiels : niveaux, examens, statuts, sources, options, specialites. |
| `rag_pedago/reference/` | Chargement et resolution du referentiel officiel. |
| `rag_pedago/imports/` | Manifests, qualite, readiness, coverage, gate, review, import controle. |
| `rag_pedago/ledger/` | Ledger SQLite, migrations, repository, diagnostics. |
| `scrapers/` | Fetch gouverne, parsing programmes, acquisition par taxonomie. |
| `agents/` | Agents d'acquisition : orchestrateur, niveau, matiere. |
| `query_agents/` | Agents de requete : orchestrateur, niveau, matiere, appels API. |
| `scripts/` | Audits, chunking, embeddings, manifests, validation taxonomie. |
| `configs/` | Politiques et verrous. |
| `tests/` | Tests unitaires et contrats projet. |

### 7.3 Taxonomie

Les taxonomies suivent le schema `TaxonomySpec` :

- `id`
- `matiere`
- `niveau`
- `voie`
- `statut_enseignement`
- `programme_version`
- `themes`
- `competences`

Chaque theme contient des notions, et chaque notion peut porter des subnotions. Les fichiers `common/` et `exams/` servent de listes communes et specifications d'examens ; les taxonomies disciplinaires portent les themes exploitables.

### 7.4 Acquisition gouvernee

L'acquisition web est volontairement contrainte :

- domaines whitelistes ;
- respect robots.txt ;
- GET uniquement ;
- pas de JavaScript ;
- pas d'authentification ;
- limite de debit ;
- user-agent identifiable ;
- taille de reponse bornee.

Domaines actuellement whitelistes dans `scrapers/fetch.py` :

- `eduscol.education.gouv.fr`
- `education.gouv.fr`
- `www.education.gouv.fr`
- `cache.media.eduscol.education.gouv.fr`
- `cache.media.education.gouv.fr`
- `fr.wikiversity.org`
- `fr.wikipedia.org`

Les pages HTML sont nettoyees avec BeautifulSoup. Le code retire scripts, styles, navigation, infobox, references, sections terminales, footer et marqueurs residuels. La qualite controle la longueur, la presence de francais et les traces de navigation.

### 7.5 Agents d'acquisition

Architecture ADR-0005 :

```text
OrchestratorAgent
  -> LevelAgent
      -> SubjectAgent
          -> fetch_notion()
          -> staging JSON
```

Un `SubjectAgent` :

- charge une taxonomie ;
- charge si disponible une correspondance BO ;
- priorise les notions non trouvees ou partiellement trouvees ;
- appelle `fetch_notion()` ;
- nettoie les fichiers stale pour la notion ;
- ecrit un fichier staging canonique `{matiere}_{notion_id}.json`.

Ces agents proposent et deposent en staging. Ils ne doivent pas ecrire directement dans le corpus final ni pgvector.

Point d'attention : `OrchestratorAgent.check_ingestion_blocked()` verifie historiquement que `ingestion_allowed` est faux, alors que le contrat courant l'a leve a `true` pour l'indexation pilote pgvector. Ce comportement peut bloquer l'orchestrateur d'acquisition tel quel et doit etre traite dans un lot dedie si on reprend ce chemin.

### 7.6 Chunking

`scripts/build_chunks.py` :

- verifie `chunking_allowed` ;
- lit `data/staging/agents/` ;
- produit `data/chunks/{niveau}/{matiere}_{notion}.jsonl` ;
- produit un sidecar `data/chunks/{niveau}/{matiere}_{notion}.meta.json`.

Parametres :

- cible : environ 750 tokens ;
- overlap : environ 12 % ;
- decoupe sur paragraphes et phrases ;
- identifiants deterministes `chunk_id = {niveau}_{matiere}_{notion}#{index}` ;
- hash SHA-256 par chunk ;
- sidecar compatible `ChunkMetadata`.

### 7.7 Embeddings

`scripts/build_embeddings.py` :

- verifie `embeddings_allowed` ;
- lit les chunks ;
- charge `intfloat/multilingual-e5-large` ;
- produit des vecteurs normalises L2 en 1024 dimensions ;
- applique `format_passage()` ;
- ecrit `data/embeddings/{niveau}/{matiere}_{notion}.jsonl`.

Idempotence :

- reutilisation seulement si `chunk_sha256`, `MODEL_NAME`, `MODEL_DIM` et `input_format` correspondent.

### 7.8 Manifeste de revue

`scripts/build_review_manifest.py` :

- parcourt les embeddings ;
- valide dimension 1024 ;
- rejette NaN/Inf ;
- verifie metadonnees minimales ;
- produit `data/embeddings/review_manifest.json`.

`rag-engine` n'indexe que les chunks presents dans ce manifeste avec le bon SHA.

### 7.9 Agents de requete

Les agents de requete sont separes de l'acquisition :

```text
query_orchestrator()
  -> signe le profil HMAC
  -> query_level()
      -> query_subject()
          -> POST rag-engine /search
          -> assemble_context()
```

Ils renvoient un contexte structure :

- `mode: context_only`
- `passages`
- `profile_niveau`
- `profile_audience`
- `count`
- metadonnees de gouvernance

Ils ne generent pas de prose tant que `answer_generation_allowed` reste faux.

## 8. Service `rag-engine`

### 8.1 Role

`rag-engine` est le plan de donnees. Il porte deux realites :

1. un moteur historique `rag-local` avec ChromaDB, Ollama, ingestor FastAPI, UI Streamlit, Google Drive, uploads, observabilite ;
2. le chemin Nexus recent, centre sur pgvector et une API pilote `/search` en lecture seule filtree par profil signe.

Un auditeur doit distinguer ces deux surfaces. Les README internes de `rag-engine` contiennent encore des references historiques a `rag-local`, ChromaDB et `nomic-embed-text`; le chemin Nexus actuel pour le pilote pedagogique est documente par les ADR 0010-0012, les scripts `index_pgvector.py` et `retrieval_api.py`, et le schema `rag_chunks_pilote`.

### 8.2 Pgvector historique et pilote

`infra/postgres/init.sql` cree :

- `rag_documents` : documents historiques multi-tenant ;
- `rag_chunks` : chunks historiques, embeddings `vector(768)`, full-text francais ;
- `rag_chunks_pilote` : table Nexus pilote, embeddings `vector(1024)` ;
- `rag_api_keys` : cles API historiques ;
- `rag_eval_runs` : metriques d'evaluation.

La table pilote est isolee :

```sql
rag_chunks_pilote (
  chunk_id text primary key,
  doc_id text not null,
  vector vector(1024),
  niveau text not null,
  voie text not null default 'generale',
  audience text[] not null default '{"tous"}',
  matiere text not null,
  notions text[] not null default '{}',
  text text,
  model text
)
```

Cette separation evite la collision avec `rag_chunks` historique en 768 dimensions.

### 8.3 Indexation pilote

`scripts/index_pgvector.py` :

- resout la racine workspace ;
- lit le contrat `services/rag-pedago/configs/pedago_interface_contract.yml` ;
- refuse si `ingestion_allowed` est faux ;
- lit `services/rag-pedago/data/embeddings/` ;
- lit `review_manifest.json` ;
- rejette tout chunk absent du manifeste ou avec SHA divergent ;
- valide dimension, niveau, matiere et longueur de vecteur ;
- upsert dans `rag_chunks_pilote`.

Par defaut :

- DSN : `postgresql://nexus:nexus@localhost:${PGVECTOR_PORT:-5433}/nexus_rag` ;
- dimension : 1024 ;
- modele de demo : `intfloat/multilingual-e5-large`.

### 8.4 API de retrieval lecture seule

`scripts/retrieval_api.py` expose :

- `GET /health`
- `POST /search`

L'application :

- verifie `server_start_allowed` et `runtime_api_allowed` au demarrage ;
- charge `PROFILE_SECRET` depuis l'environnement ;
- verifie le jeton `Authorization: Bearer <token>` ;
- encode la requete avec `format_query()` ;
- cherche dans `rag_chunks_pilote` ;
- impose `WHERE niveau = %s AND (%s = ANY(audience) OR 'tous' = ANY(audience))`.

Le body de `/search` ne contient que :

```json
{
  "query": "derivee d'une fonction",
  "top_k": 5
}
```

Il n'y a pas de route d'ecriture, pas d'ingestion, pas d'emission HTTP de jeton.

### 8.5 Emission de jetons

`scripts/issue_profile_token.py` est un CLI d'administration :

```bash
PROFILE_SECRET=... python scripts/issue_profile_token.py terminale libre
```

Il importe `sign_profile()` depuis `nexus_contracts.profile_auth`.

### 8.6 Moteur historique

Le dossier `src/ingestor/` conserve des composants importants :

- `api.py` : ingestor FastAPI historique avec `/ingest`, `/search`, `/rag/query`, `/metrics`, uploads, Google Drive, Chroma ;
- `database.py` : client async pgvector historique ;
- `hybrid_search.py` : dense + BM25 + RRF + reranker CrossEncoder ;
- `embedding_service.py` : embeddings Ollama avec cache Redis ;
- `pedagogical_chunker.py` : chunker markdown structure-aware ;
- `tasks.py` : ingestion asynchrone Celery.

Ce code est teste et reutilisable, mais il ne constitue pas encore l'API Nexus filtree par profil signe. La surface Nexus pilote est `scripts/retrieval_api.py`.

### 8.7 Catalogue de collections v2 (ADR-0013, LOT 21/22a)

Le catalogue cible est versionne dans `services/rag-engine/configs/rag_collections.yml` (v2). Convention de nommage : `rag_nexus_{matiere}_{niveau}_{statut}`, avec 5 exceptions nommees (grand oral, examens, candidats libres, quarantaine).

22 collections au catalogue taxonomique. Chaque collection porte un flag `instanciee: true|false`. Seules les collections instanciees sont creees et exposees (invariant M-04) :

| Collections instanciees | Statut |
|---|---|
| `rag_nexus_nsi_premiere_specialite` | instanciee |
| `rag_nexus_nsi_terminale_specialite` | instanciee |
| `rag_nexus_quarantine` | instanciee |

Les 19 autres (maths, francais, HG, PC, SVT, SES, philo, SNT, grand oral, examens, candidats libres) restent au catalogue comme perimetre cible, non instanciees tant que du contenu gouverne n'existe pas pour elles.

**Invariant anti-auto-creation** : `resolve_collection_v2()` leve `CollectionUnknownError` si la collection n'est pas dans le catalogue, et `CollectionNotInstanciatedError` si elle est dans le catalogue mais pas instanciee. Pas de `get_or_create_collection`.

### 8.8 Separation legacy / v2 (LOT 22a)

Deux mondes etanches, aucune cross-contamination :

| | Monde v2 (code neuf) | Monde legacy (api.py historique) |
|---|---|---|
| Config | `rag_collections.yml` (v2) | `rag_collections_legacy.yml` (v1) |
| Resolveur | `resolve_collection_v2()` | `resolve_collection()` |
| Collections | 22 du catalogue taxonomique | 6 silos Chroma (education, official, exams, owned, web3, quarantine) |
| Routing | Pas de routing implicite | `routing.sections` |
| Backend | pgvector dedie (instance separee) | ChromaDB prod |

Le code legacy (`api.py`, `retrieval_contract_adapter.py`) lit `rag_collections_legacy.yml`. Le code neuf lit `rag_collections.yml`. Aucun alias, aucun fallback entre les deux.

### 8.9 Table cible `rag_chunks` (LOT 21)

La table cible `rag_chunks` (pas `rag_chunks_pilote`) est citations-ready (F-01) :

```sql
rag_chunks (
  chunk_id text PRIMARY KEY,
  doc_id text NOT NULL,        -- distinct de chunk_id
  chunk_sha256 text NOT NULL,
  vector vector(1024),
  collection text NOT NULL,    -- rag_nexus_{matiere}_{niveau}_{statut}
  niveau text NOT NULL,
  voie text NOT NULL,
  audience text[] NOT NULL,
  matiere text NOT NULL,
  source_label text NOT NULL,  -- Citation.source_label
  source_uri text NOT NULL,    -- Citation.source_uri
  rights text NOT NULL,        -- Citation.rights (par provenance, A-4)
  type_doc text NOT NULL,      -- ChunkMetadata.type_doc
  official boolean NOT NULL,
  text text,
  review_status text NOT NULL DEFAULT 'needs_review',
  ...
)
```

Index : HNSW cosine + 6 B-tree/GIN (collection, niveau, matiere, audience, rights, review_status).

### 8.10 Infrastructure pgvector dedie (LOT 21)

`services/rag-engine/infra/docker-compose.pgvector-rag.yml` : instance separee de `nexus_prod` (A-1), schema auto-applique a l'init, mot de passe obligatoire (pas de defaut), encodage UTF-8 / collation C.

### 8.11 Moteur historique legacy

Le mapping legacy est conserve dans `legacy_collection_mapping.yml` :

| Legacy Chroma | Cible legacy |
|---|---|
| `rag_education` | `rag_nexus_education` |
| `rag_francais_premiere` | `rag_nexus_education` |
| `rag_maths_premiere` | `rag_nexus_education` |
| `rag_web3` | `rag_nexus_web3` |
| `rag_divers` | `rag_nexus_quarantine` |

Les tests du moteur legacy sont marques `@pytest.mark.legacy_engine` et tournent sur `rag_collections_legacy.yml`. Ils restent en CI tant que `api.py` sert la prod (D-LEGACY-CI).

## 9. Service `cockpit`

`services/cockpit/` contient un SaaS Next.js App Router :

- authentification ;
- resolution `StudentProfile` ;
- routage vers un cockpit par niveau/profil ;
- agents UI d'accompagnement ;
- Q/R sourcees, revision, exercices, correction ;
- consommation du retrieval via `rag-engine`.

Statut actuel : BFF de retrieval/revue livré et testé, sans accès direct à
pgvector. L'ouverture publique reste bloquée par le verdict global NO_GO.

## 10. Donnees, corpus et artefacts

### 10.1 Donnees racine

`corpus/` est la matiere premiere pedagogique et produit. Ces documents sont rediges en francais et contiennent des notes RAG d'indexation. Ils ne sont pas automatiquement synonymes de chunks retrievables : l'entree dans le moteur passe par les pipelines gouvernes.

### 10.2 Donnees `rag-pedago`

| Chemin | Role |
|---|---|
| `data/reference/` | Referentiel officiel structure. |
| `data/programmes/` | Registre programmes, correspondances BO. |
| `data/staging/` | Contenus candidats acquis ou programmes telecharges. |
| `data/chunks/` | Chunks pilotes et sidecars. |
| `data/embeddings/` | Vecteurs et manifeste de revue. |
| `data/ledger/rag_pedago.sqlite` | Ledger local. |
| `data/reports/` | Rapports runtime et historiques codex. |

### 10.3 Artefacts pilotes actuels

Le pilote indexe des notions Terminale :

- mathematiques : continuite, convexite, derivation, limites, suites ;
- NSI : arbres, files, graphes, listes, piles ;
- philosophie : droit, etat, justice, liberte ;
- grand oral : expression orale, transversalite.

Total actuel : 16 fichiers notionnels, 124 chunks, 124 embeddings, 124 approuves.

### 10.4 Donnees `rag-engine`

`rag-engine` peut utiliser :

- volumes Docker historiques Chroma/Ollama ;
- PostgreSQL pgvector ;
- table historique `rag_documents`/`rag_chunks` ;
- table pilote `rag_chunks_pilote`.

La table pilote est alimentee depuis les artefacts `rag-pedago`, pas par l'API HTTP.

## 11. Flux de bout en bout

### 11.1 Acquisition pedagogique

```text
TaxonomySpec
  -> plan d'acquisition
  -> sources candidates
  -> governed_fetch()
  -> extraction HTML/PDF
  -> quality_check()
  -> staging JSON
```

Garanties :

- fetch web uniquement si `network_allowed` et `data_staging_allowed` ont ete leves dans le perimetre ADR ;
- source whitelist ;
- robots.txt respecte ;
- contenu depose en staging, pas directement dans pgvector.

### 11.2 Chunking et embeddings

```text
staging JSON
  -> build_chunks.py
  -> data/chunks/*.jsonl + *.meta.json
  -> build_embeddings.py
  -> data/embeddings/*.jsonl
  -> build_review_manifest.py
  -> review_manifest.json
```

Garanties :

- chaque etape verifie son verrou ;
- chunks et embeddings sont versionnables ;
- le modele et la dimension font partie de l'idempotence ;
- le manifeste est la preuve d'approbation.

### 11.3 Indexation

```text
review_manifest.json + embeddings
  -> rag-engine/scripts/index_pgvector.py
  -> check_ingestion_allowed()
  -> rag_chunks_pilote
```

Garanties :

- `rag-engine` lit le contrat de `rag-pedago` ;
- un chunk absent du manifeste n'est pas indexe ;
- un SHA divergent est rejete ;
- upsert idempotent par `chunk_id`.

### 11.4 Retrieval

```text
PROFILE_SECRET
  -> issue_profile_token.py ou query_orchestrator()
  -> Authorization: Bearer <token>
  -> POST /search {"query": "...", "top_k": n}
  -> filtre SQL niveau + audience
  -> passages
```

Garanties :

- le client ne fournit pas niveau/audience dans le body ;
- le profil est verifie cote serveur ;
- un jeton forge ou modifie est rejete ;
- le contenu `audience = tous` est accessible aux audiences autorisees ;
- le contenu exclusif `aefe` n'est pas visible par `libre`.

### 11.5 Agents de requete

```text
question + profil amont
  -> query_orchestrator()
  -> token HMAC
  -> query_level()
  -> query_subject()
  -> API /search
  -> contexte structure
```

Garanties :

- l'agent ne s'auto-attribue pas un profil ;
- l'agent ne reimplemente pas le filtrage ;
- l'agent ne genere pas de reponse tant que le verrou est ferme.

## 12. Gouvernance et verrous

### 12.1 Source de verite

Le contrat runtime de reference est :

```text
services/rag-pedago/configs/pedago_interface_contract.yml
```

Le garde-fou racine compare ce fichier a :

```text
scripts/governance-locks.baseline
```

Commande :

```bash
bash scripts/check-governance-locks.sh
```

Etat mesure : `OK: all governance locks match baseline (18 keys verified).`

### 12.2 Etat actuel des verrous principaux

| Verrou | Valeur | Sens actuel |
|---|---:|---|
| `runtime_api_allowed` | true | API retrieval lecture seule autorisee. |
| `server_start_allowed` | true | Demarrage serveur retrieval autorise. |
| `ui_runtime_allowed` | false | Pas d'UI runtime autorisee par ce contrat. |
| `real_documents_allowed` | false | Pas d'acces general aux documents reels. |
| `pdf_allowed` | true | Parsing programmes officiels en staging autorise. |
| `ingestion_allowed` | true | Indexation pgvector pilote autorisee, scope strict ADR-0008. |
| `parsing_allowed` | true | Parsing gouverne autorise. |
| `chunking_allowed` | true | Chunking gouverne autorise. |
| `embeddings_allowed` | true | Embeddings gouvernes autorises. |
| `qdrant_allowed` | false | Qdrant abandonne, ne pas reutiliser. |
| `network_allowed` | true | Fetch reseau scope ADR-0004. |
| `answer_generation_allowed` | false | Aucune generation de reponse. |
| `data_staging_allowed` | true | Depot de contenu candidat avant revue autorise. |
| `curated_ingestion_allowed` | false | Canal ressources curees pose mais ferme. |

### 12.3 Lecture des differents fichiers de config

Tous les YAML de `configs/` n'ont pas le meme role :

- `pedago_interface_contract.yml` : contrat runtime courant.
- `transition_authorization.yml` : protocole de transition et cas d'autorisation.
- `source_admission_policy.yml` : politique d'admission de sources, tres conservative.
- `metadata_governance_chain.yml` : chaine metadata historique.
- `retrieval_metadata_eval.yml` : evaluation metadata-only historique.

Il ne faut pas conclure qu'un verrou est globalement ferme parce qu'il est faux dans une politique specifique. Le garde-fou racine verifie `pedago_interface_contract.yml` contre la baseline.

### 12.4 Regle d'evolution

Toute activation de verrou sensible doit :

- etre volontaire ;
- etre referencee par ADR ;
- modifier la baseline et le contrat dans la meme PR ;
- conserver des tests de garde-fou.

## 13. API, authentification et filtrage

### 13.1 Endpoint Nexus pilote

Demarrage :

```bash
cd services/rag-engine
PROFILE_SECRET=... python scripts/retrieval_api.py
```

Endpoint :

```text
GET  /health
POST /search
```

Exemple :

```bash
TOKEN="$(PROFILE_SECRET=... python scripts/issue_profile_token.py terminale libre)"

curl -sS http://localhost:8100/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"derivee d une fonction","top_k":3}'
```

Reponse :

```json
{
  "results": [
    {
      "chunk_id": "...",
      "doc_id": "...",
      "niveau": "terminale",
      "matiere": "mathematiques",
      "notions": ["derivation"],
      "similarity": 0.8897,
      "preview": "..."
    }
  ],
  "profile_niveau": "terminale",
  "profile_audience": "libre",
  "count": 1
}
```

### 13.2 Proprietes de securite

#### Runtime v2 gouverné — BFF et identité signée

Les endpoints v2 de `rag-engine` appliquent les règles suivantes :

- `/search/v2` reste `reviewed-only` ;
- la queue et la décision de revue exigent le credential machine du Cockpit BFF,
  une enveloppe d'identité valide et un rôle humain autorisé ;
- les collections et le tenant sont dérivés de l'identité signée ;
- aucune route d'ingestion, d'administration legacy, de statistiques ou
  d'évaluation n'appartient à `api_v2:app` ;
- le proxy ne transmet qu'une allowlist de neuf chemins exacts.

Les seules autorités runtime sont le credential BFF, la clé de signature
interne et les paramètres d'issuer/audience. Les DSN PostgreSQL sont séparés :
lecture stricte pour le retrieval, droits minimaux de revue pour la décision.
Il n'existe aucun fallback vers le propriétaire ou le DSN de migration.

#### Endpoints legacy / v1 — profil, niveau, audience, HMAC

- Le client ne choisit pas son niveau dans le body.
- Toute tentative d'ajouter `niveau` ou `audience` au body est ignoree par schema.
- Le serveur derive les filtres depuis le jeton.
- Un mauvais secret produit `401 invalid signature`.
- Un payload modifie apres signature produit `401 invalid signature`.
- L'absence de token echoue.
- L'absence de table pilote renvoie `503 retrieval index not ready`.

### 13.3 Limites actuelles de l'API pilote

- Elle ne renvoie pas encore le modele `RetrievalResponse` complet avec `Citation` formelle.
- Elle expose des previews de texte, pas une reponse pedagogique.
- Elle charge le modele `multilingual-e5-large` au demarrage.
- Elle cible `rag_chunks_pilote`, pas le moteur historique hybride complet.

## 14. Qualite, CI et commandes

### 14.1 Standards

- Python >= 3.11.
- Qualite : ruff, mypy, pytest.
- Documentation et contenu pedagogique en francais.
- Aucun secret ni PII eleve.
- Aucun chemin absolu machine-local dans le code versionne.

### 14.2 CI locale racine

Commande :

```bash
bash scripts/ci-local.sh
```

La CI locale execute :

1. import du package `packages/contracts` ;
2. `rag-pedago` install, lint, typecheck, test ;
3. `rag-engine` install, lint, typecheck, test ;
4. garde-fou gouvernance ;
5. validation taxonomie ;
6. tests du garde-fou ;
7. tests failsafe de la CI.

Le script CI courant renvoie un code non nul si une cible échoue. Cette
description de ses cibles date des premiers lots ; les packages PDF et
release-chain, le Cockpit, la revue humaine fiable, l'hygiène et C1 sont
également couverts au SHA audité (voir l'état en tête et le script réel).

### 14.3 Commandes par service

Contrats :

```bash
cd packages/contracts
python -m venv .venv
. .venv/bin/activate
pip install -e .[dev]
pytest -q
```

`rag-pedago` :

```bash
cd services/rag-pedago
make install
make lint
make typecheck
make test
python scripts/validate_taxonomy.py
```

`rag-engine` :

```bash
cd services/rag-engine
make install
make lint
make typecheck
make test
make smoke
```

Gouvernance :

```bash
bash scripts/check-governance-locks.sh
bash scripts/tests/test-governance-locks.sh
```

## 15. Installation et execution locale

### 15.1 Installation minimale

Depuis la racine :

```bash
cd services/rag-pedago
make install

cd ../rag-engine
make install
```

Les deux `Makefile` installent `packages/contracts` en editable avant le service.

### 15.2 Construction des artefacts pilotes

Depuis `services/rag-pedago` :

```bash
python scripts/build_chunks.py
python scripts/build_embeddings.py
python scripts/build_review_manifest.py
```

Preconditions :

- `chunking_allowed: true`
- `embeddings_allowed: true`
- modele HuggingFace accessible/localement cache ;
- staging deja present.

### 15.3 Pgvector pilote

Depuis `services/rag-engine` :

```bash
docker compose -f infra/docker-compose.pgvector.yml up -d
python scripts/index_pgvector.py
```

Variables utiles :

| Variable | Defaut | Role |
|---|---|---|
| `PGVECTOR_PORT` | `5433` | Port local de PostgreSQL pgvector. |
| `PG_DSN` | derive de `PGVECTOR_PORT` | DSN psycopg pour indexation/API. |
| `PROFILE_SECRET` | aucun | Secret HMAC pour API `/search`. |
| `RETRIEVAL_API_URL` | `http://localhost:8100` | URL consommee par les query agents. |

### 15.4 API et query agents

Terminal 1 :

```bash
cd services/rag-engine
PROFILE_SECRET=dev-secret python scripts/retrieval_api.py
```

Terminal 2 :

```bash
cd services/rag-pedago
PROFILE_SECRET=dev-secret python - <<'PY'
from query_agents.query_orchestrator import query_orchestrator

print(query_orchestrator(
    question="derivee d une fonction",
    niveau="terminale",
    audience="libre",
    matiere="mathematiques",
    top_k=3,
))
PY
```

## 16. Securite, conformite et limites

### 16.1 Principes appliques

- Secrets par environnement uniquement.
- Pas de secret commite.
- Pas de PII eleve dans le corpus.
- Pas d'acces direct cockpit -> pgvector.
- Pas de generation sans source.
- Pas de generation tant que `answer_generation_allowed` est faux.
- Fetch web whitelist + robots + rate limit.
- Aucun agent n'ecrit directement dans pgvector.
- Indexation seulement apres manifeste de revue.

### 16.2 Donnees et RGPD

Le projet reduit l'exposition RGPD par separation :

- profils et logique eleve cote cockpit/futur auth ;
- contenus pedagogiques et gouvernance cote `rag-pedago` ;
- index vectoriel cote `rag-engine` ;
- pas de documents bruts exposes au cockpit.

Le profil signe actuel ne porte que `niveau` et `audience`. Il ne transporte pas d'identifiant eleve.

### 16.3 Limites de conformité actuelles

- La session/RBAC du Cockpit est livrée, mais son déploiement réel, ses secrets
  et sa révocation doivent encore être prouvés sur l'environnement cible.
- Les ressources curees enseignant ne sont pas alimentees.
- Les documents reels proprietaires restent bloques.
- Les tests d'integration pgvector du chemin pilote doivent etre industrialises.

## 17. Production inventoriee (LOT 20)

Le LOT 20 a inventorie la production `rag-ui.nexusreussite.academy` en lecture seule. Livrables dans `docs/audits/`.

### 17.1 Topologie prod

5 conteneurs Docker Compose (ingestor FastAPI, UI Streamlit, ChromaDB 1.1.1, Ollama 0.3.13, autoheal), reverse proxy nginx avec TLS Let's Encrypt.

### 17.2 Corpus prod

| Collection | Vecteurs | Dim (mesuree) | Modele |
|---|---:|---|---|
| `rag_education` | 7 181 | 768 | nomic-embed-text |
| `rag_francais_premiere` | 5 948 | 768 | nomic-embed-text |
| `nsi_corpus` | 4 716 | 768 | nomic-embed-text |
| `rag_math_correction` | 67 | 768 | nomic-embed-text |
| **Total** | **17 912** | **768** | |

Incompatibilite avec le pilote gouverne : 768 dim (prod) vs 1024 dim (e5-large). Re-embedding complet requis.

### 17.3 Admissibilite

Critere : `matiere` ET `niveau` ET `source_uri` (URL) presents. Scan exhaustif :

| Collection | Admissibles | % |
|---|---:|---|
| `rag_education` | 3 366 | 46 % |
| `rag_francais_premiere` | 5 833 | 98 % |
| `nsi_corpus` | 0 | 0 % (pas de source_uri) |
| **Total** | **9 199** | **51 %** |

`rights` = 0 % sur tout le corpus. Resolution par provenance (A-4), jamais par classification.

### 17.4 Ecarts prod ↔ depot

- Code ingestor divergent (91 501 o vs 90 357 o)
- `COLLECTION_MAP` et fallback differents
- `maths_premiere_fallback` a 3 filtres (non-fonctionnel par construction)
- 3 rubriques UI cassees (Maths 1ère, Web3, Divers)
- `nsi_corpus` 100 % non revu, routable via API

### 17.5 Strategie de migration (ADR-0013)

Plan historique LOT20 : shadow puis canary (D-4), rollback nginx en une ligne,
instanciation initiale NSI + quarantaine et sauvegarde préalable. Cette stratégie
ne constitue plus le runbook canonique LOT41U.

Baseline de parite : `docs/audits/baseline_retrieval_prod.json` (16 requetes, 4 sections, sans texte non droite).

## 18. ADR et historique des lots

### 17.1 ADR racine

| ADR | Decision |
|---|---|
| ADR-0001 | Separation plan de controle / plan de donnees / cockpit. |
| ADR-0002 | Contrat partage `nexus-contracts`, versionne SemVer. |
| ADR-0003 | Tenants par niveau et `audience` en metadonnee filtrable. |
| ADR-0004 | Ingestion agentique sous gouvernance. |
| ADR-0005 | Architecture multi-agents d'acquisition. |
| ADR-0006 | Chunking gouverne. |
| ADR-0007 | Embeddings gouvernes, modele e5, 1024 dimensions. |
| ADR-0008 | Indexation pgvector gouvernee. |
| ADR-0009 | Canal ressources curees pose mais ferme. |
| ADR-0010 | Gouvernance cross-service, verrous `rag-pedago` lus par `rag-engine`. |
| ADR-0011 | API retrieval lecture seule. |
| ADR-0012 | Agents de requete context-only branches sur l'API filtree. |
| ADR-0013 | Convergence dual-engine : e5-large 1024 + pgvector dedie, shadow+canary, cockpit differe, catalogue 22 collections. |

### 17.2 Lots structurants

| Lot | Resultat |
|---|---|
| 0 | Monorepo, extraction `nexus-contracts`, CI racine. |
| 1.0 | Contrat v0.2.0, audience, `ChunkMetadata`. |
| 7-8 | Taxonomie BO pilote puis taxonomie complete 420 identifiants. |
| 9 | Recuperation programmes officiels et correspondances BO. |
| 10 | Agents d'acquisition. |
| 11 | Recherche reelle par table notion -> article. |
| 12 | Chunking gouverne, 124 chunks conformes. |
| 13 | Embeddings e5 1024d, prefixes et idempotence. |
| 14 | pgvector pilote, filtrage niveau/audience. |
| 15 | Referentiel exhaustif voie generale, canal ressources curees. |
| 16 | Migration retrieval/indexation vers `rag-engine`. |
| 17 | API `/search` lecture seule, HMAC, table pilote isolee. |
| 18 | Agents de requete `context_only` branches sur l'API filtree. |
| 19 | Alignement documentaire prod historique / Nexus gouverne. |
| 20 | Inventaire prod read-only : 17 912 vecteurs 768 dim, 6 collections, ADR convergence decision-ready. Rotation token, 3 bugs prod decouverts. |
| 21 | Infrastructure convergence : ADR-0013, `rag_collections.yml` v2, table `rag_chunks` citations-ready, pgvector dedie, invariant anti-auto-creation. |
| 22a | Suppression schema dual Chroma/v2, separation etanche legacy/v2, 12 tests legacy isoles sur config dediee. |

## 19. Dettes et points d'attention

### 19.1 Dettes connues documentees

| Dette | Impact | Ref |
|---|---|---|
| `DETTE-16-ITEST-RETRIEVAL` | Pas de test d'integration `index_pgvector.py` contre pgvector Docker. | LOT 23 cible |
| Mapping audience ambigu | Statuts hors cible derivent vers `aefe` par defaut. | — |
| Notion articles partiel | `data/sources/notion_articles.yml` couvre une partie des notions, pas les 420. | — |
| Sources examen incompletes | Sujets examen moins couverts que STEM. | — |
| Divergence outils | Versions ruff/mypy differentes entre services. | — |
| `api.py` moteur legacy (2215 lignes) | Monolithe Chroma/Ollama en sursis, a decommissionner post-LOT 25. | A-02, lot_0_dettes.md |
| 10 erreurs d'import preexistantes | Tests legacy avec deps lourdes (chromadb, langchain, etc.), preexistantes commit `31020f8`. | lot_0_dettes.md |
| Taxonomie incomplete | Options hors maths, ens. scientifique, EMC manquent dans taxonomy/. Enums du contrat prets. | O-03 |
| `nsi_corpus` non revu en prod | 100 % des 4 716 chunks NSI ont `status: needs_review`, routables via API directe (pas via UI). | I-06 |
| 3 rubriques UI prod cassees | Maths 1ère (fallback non-fonctionnel), Web3 (collection vide), Divers (collection vide). | L-02, A-L03 |
| Migration corpus prod | 9 199 chunks admissibles (51 %), rights=0 %, re-embedding 768→1024 requis. | LOT 20, ADR-0013 |
| `rag_francais_premiere` etiquetage | `niveau=Sixième` (suspect, source unique), niveau reel a verifier. | J-06 |

### 19.2 Ecarts de documentation interne

Quelques documents internes sont historiques :

- `services/rag-engine/README.md`, `README-PROD.md`, `SPEC.md` parlent de `rag-local`, ChromaDB et Ollama parce qu'ils documentent la prod historique ; ils portent des avertissements Lot 19 pour eviter la confusion avec Nexus.
- `services/rag-pedago/README.md` decrit encore un etat metadata-only plus strict que l'etat courant.
- `docs/ROADMAP.md` mentionne une nomenclature initiale de tenants `{population}_{niveau}`.

L'etat courant du code et des ADR recents est :

- tenant pilote = niveau (`terminale`, `premiere`, etc.) ;
- audience = metadonnee filtrable (`libre`, `aefe`, `tous`) ;
- pgvector pilote = `rag_chunks_pilote` en 1024 dimensions ;
- collections cible = `rag_nexus_*` avec mapping legacy explicite ;
- API runtime lecture seule autorisee ;
- generation de reponse interdite.

### 19.3 Point sensible : conventions de tenant

`AGENTS.md` conserve la convention `{population}_{niveau}` comme nomenclature. ADR-0003 et le code courant revisent ce choix vers un tenant par niveau et un filtre `audience`. Tant que cette divergence n'est pas clarifiee par un lot documentaire ou ADR de consolidation, un contributeur doit suivre l'etat du code et des ADR pour le moteur pilote, et signaler toute modification de nomenclature dans un rapport de lot.

### 19.4 Point sensible : baseline de gouvernance

`scripts/governance-locks.baseline` est l'autorite testee par CI. Il contient 18 entrees verifiees par le script, dont plusieurs lignes `answer_without_source_allowed: false`. Ne pas "nettoyer" ces lignes sans lot dedie, car le garde-fou compare l'etat attendu ligne par ligne.

## 20. Lecture rapide pour auditeur

Pour auditer **l'état au SHA de base indiqué en tête** :

1. Vérifier le SHA de la base, l'absence de modifications locales, les deux
   fusions #266/#267 et la CI de ce SHA. L'état GitHub est temporel : le
   relire, ne pas le déduire du texte de ce README.
2. Recalculer les cinq SHA du bloc « Qualifications et reproduction » et
   charger les manifests V4, HGGSP et le registre mixte par les chargeurs
   canoniques de `packages/release-chain`. Vérifier les listes de collections,
   les 405 et 74 placements, les 263 et 52 artefacts, leur disjonction et
   les 5 678 et 2 590 chunks issus des registres scellés.
3. Contrôler le [diff machine](docs/reports/evidence/profile_gate_v4_to_hggsp_v5_diff.json),
   la [preuve de build](docs/reports/evidence/hggsp_v5_complementary_build_proof.json),
   le mapping HGGSP et le motif citant le commit de l'autorité. Pour une
   reconstruction complète, demander le miroir des 52 PDF hors dépôt et
   vérifier chaque SHA ; le `content_set_sha256` ne le remplace pas.
4. Relire les journaux DI locaux identifiés par SHA plus haut en suivant le
   [plan DI](docs/runbooks/staging_v4_partial_recovery_DI_EXECUTION_PLAN.md),
   puis mesurer de nouveau la base dédiée par
   la procédure opérateur approuvée. Vérifier aussi le maintien de #262
   ouverte au même HEAD et des 74 anciens jobs HGGSP inchangés.
5. Constater la proposition HGGSP `PROPOSED_INACTIVE`, les statuts
   `NOT_PROMOTABLE`/`NO_PRODUCTION_ACTIVATION`, le verdict
   `GO_LIVE: NO_GO` et les autorités absentes avant d'envisager une suite.
   Le [plan opérateur HGGSP](docs/runbooks/staging_hggsp_complementary_SUCCESSOR_PLAN.md)
   décrit les étapes futures ; il n'est pas une autorisation en lui-même.

La question d'audit est : **quelles preuves établissent que chaque passage a
été admis, publié et servi dans le périmètre autorisé, pour un commit et un
état de base précis ?** Les preuves versionnées et les preuves d'exploitation
doivent être lues ensemble avant toute décision de production.
