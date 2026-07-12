# Nexus RAG Pedagogique

Plateforme RAG pedagogique multi-services pour Nexus Reussite. Le depot combine un plan de controle pedagogique, un moteur de retrieval, un futur cockpit SaaS et un contrat partage. Il sert a construire une chaine auditable de bout en bout : sources pedagogiques gouvernees -> taxonomies -> chunks -> embeddings -> index pgvector -> retrieval filtre -> contexte exploitable par des agents, sans generation de reponse tant que la gouvernance ne l'autorise pas.

Ce README est le point d'entree racine pour un auditeur. Les regles imperatives pour les agents restent dans `AGENTS.md`. Les decisions structurantes sont dans `docs/adr/`. Les rapports de lots sont dans `docs/reports/`.

Note securite v2 LOT 26.3 : les tokens de roles doivent etre uniques entre roles distincts. `RAG_REVIEWER_TOKEN` et `REVIEWER_API_TOKEN` peuvent partager une valeur pour le role reviewer. `INGESTOR_API_TOKEN` et `INGEST_AUTH_TOKEN` restent des alias de compatibilite ingest_agent v2, mais `RAG_INGEST_AGENT_TOKEN` devrait rester distinct des tokens d'ingestion legacy. Les routes legacy `/admin/*` utilisent exclusivement `LEGACY_ADMIN_API_TOKEN`, qui doit etre distinct de `RAG_ADMIN_TOKEN`, `INGESTOR_API_TOKEN` et `INGEST_AUTH_TOKEN`. Une collision entre roles v2 distincts, par exemple `RAG_ADMIN_TOKEN` identique a `RAG_STUDENT_TOKEN`, bloque `security_v2` en fail-closed `503`. Les variables de securite, dont `LEGACY_ADMIN_API_TOKEN` et `INGESTOR_TRUSTED_PROXY_CIDRS`, sont transmises au conteneur `ingestor` par les compose prod, par defaut et v2 (`make v2-up`). Une configuration trusted-proxy explicitement non vide sans aucun CIDR valide bloque l'allowlist en fail-closed `503`. Depuis un peer non trusted, `X-Forwarded-For` et `X-Real-IP` sont ignores. Depuis un peer trusted, `X-Real-IP` reste ignore cote application tant qu'un template proxy versionne ne prouve pas sa reecriture stricte ; `X-Forwarded-For` est analyse de droite a gauche, jamais en premiere position naive. Ne pas utiliser `proxy_add_x_forwarded_for` sans strategie anti-spoof cote application ou sans reecriture stricte du header par le proxy.

## Sommaire

- [1. Resume executif](#1-resume-executif)
- [2. Logique metier](#2-logique-metier)
- [3. Etat actuel du projet](#3-etat-actuel-du-projet)
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
- `services/cockpit/` : futur SaaS Next.js. Il ne doit jamais acceder directement a pgvector ni aux documents bruts.

La couture entre les plans est `packages/contracts/`, package Python `nexus-contracts`. Il contient les modeles Pydantic qui definissent les profils, documents, chunks, requetes de retrieval, citations, filtres et jetons de profil signes.

L'etat courant correspond aux lots 0 a 18 :

- monorepo en place ;
- contrat partage `nexus-contracts` v0.2.0 ;
- taxonomies pedagogiques multi-niveaux ;
- acquisition gouvernee depuis des sources whitelistes ;
- chunks pilotes Terminale ;
- embeddings pilotes `intfloat/multilingual-e5-large` en 1024 dimensions ;
- manifeste de revue `quality -> gate -> review` ;
- indexation pgvector pilote dans `rag_chunks_pilote` ;
- API `/search` en lecture seule, filtree par profil signe HMAC ;
- agents de requete `context_only`, sans generation de reponse.

Le cockpit applicatif reste un placeholder (cible : post-LOT 25). La generation de reponse reste explicitement interdite (`answer_generation_allowed: false`).

Lot 19 aligne la documentation entre la production historique et le chemin Nexus gouverne. Lot 20 inventorie la production `rag-ui.nexusreussite.academy` (17 912 vecteurs ChromaDB 768 dim, 6 collections, 3 rubriques UI cassees, code prod divergent du depot). Lot 21 pose l'infrastructure de convergence : ADR-0013 (e5-large 1024 dim + pgvector dedie), catalogue de 22 collections `rag_nexus_*` avec flags d'instanciation, invariant anti-auto-creation, table `rag_chunks` citations-ready (F-01). Lot 22a isole le moteur legacy (config separee `rag_collections_legacy.yml`) du code neuf (resolveur v2 etanche).

La production publique sert encore l'UI historique Streamlit/ingestor (ChromaDB, nomic-embed-text 768 dim, Ollama). Elle ne doit pas etre confondue avec le pilote Nexus pgvector/HMAC 1024 dim.

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

## 3. Etat actuel du projet

### 3.1 Chiffres de lecture du depot

Etat mesure localement :

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
- CI locale racine avec contrats, services, garde-fous de gouvernance et validation taxonomie.

### 3.3 Ce qui n'est pas encore livre

- Cockpit SaaS Next.js operationnel (differe post-LOT 25, D-M03).
- Generation de reponse eleve (`answer_generation_allowed: false`).
- Interface de ressources curees.
- Ingestion generale de vrais documents proprietaires.
- Migration du corpus prod vers le moteur gouverne (9 199 chunks admissibles sur 17 912, cf. LOT 20).
- Deploiement production coherent de l'ensemble Nexus trois plans.
- Ingestion NSI gouvernee de bout en bout (LOT 22, en cours).

## 4. Architecture generale

### 4.1 Vue d'ensemble

```text
                              profil eleve / intent
                                       |
                                       v
                         +---------------------------+
                         | cockpit (futur SaaS)      |
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
| UI SaaS | `cockpit` | Placeholder ; futur Next.js. |
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

Placeholder du futur SaaS Next.js. Le code applicatif n'est pas encore introduit.

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

`services/cockpit/` contient seulement :

- `README.md`
- `AGENTS.md`

Le cockpit cible est un SaaS Next.js App Router :

- authentification ;
- resolution `StudentProfile` ;
- routage vers un cockpit par niveau/profil ;
- agents UI d'accompagnement ;
- Q/R sourcees, revision, exercices, correction ;
- consommation du retrieval via `rag-engine`.

Statut actuel : placeholder. Le code applicatif est prevu au Lot 3 Cockpit MVP. Aucun acces direct a pgvector ne doit etre ajoute.

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

#### Endpoints v2 — tokens de rôles statiques

Les endpoints v2 de `rag-engine` appliquent les règles suivantes :

- `/search/v2` reste `reviewed-only` pour tous les rôles autorisés.
- `/review/v2/queue` est accessible à `admin`, `reviewer` et `teacher`.
- `/review/v2/decide` est réservé à `admin` et `reviewer`.
- `/ingest/v2` est réservé à `admin` et `ingest_agent`.

Les variables de tokens v2 sont transmises sans valeur versionnée :

- `RAG_ADMIN_TOKEN`
- `RAG_REVIEWER_TOKEN`
- `REVIEWER_API_TOKEN`
- `RAG_TEACHER_TOKEN`
- `RAG_INGEST_AGENT_TOKEN`
- `INGESTOR_API_TOKEN`
- `INGEST_AUTH_TOKEN`
- `RAG_STUDENT_TOKEN`

`REVIEWER_API_TOKEN` reste un alias du rôle reviewer. `INGESTOR_API_TOKEN` et
`INGEST_AUTH_TOKEN` sont des alias de compatibilité ingest_agent v2, mais
`RAG_INGEST_AGENT_TOKEN` devrait rester distinct des tokens d'ingestion legacy.
Une même valeur configurée pour des rôles v2 distincts est une collision interdite
et bloque l'authentification en fail-closed. Les routes legacy `/admin/*` utilisent
exclusivement `LEGACY_ADMIN_API_TOKEN`, distinct des tokens v2 et d'ingestion.
L'allowlist d'ingestion utilise `INGESTOR_IP_ALLOWLIST` ; les
headers `X-Forwarded-For` ne sont acceptés que depuis les réseaux déclarés dans
`INGESTOR_TRUSTED_PROXY_CIDRS`, sans fallback vers l'adresse du proxy trusted.

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

La CI tolere au plus un echec preexistant documente dans `rag-pedago` selon `docs/BACKLOG.md`.

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

- Le cockpit reel n'existe pas encore, donc la gestion session/RBAC n'est pas livree.
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

Shadow puis canary (D-4), rollback nginx en une ligne. Cockpit differe post-LOT 25. Instanciation initiale : NSI + quarantaine. Prealables : backup ChromaDB frais, docker save des images, verification acces GDrive, gel du corpus.

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

Pour comprendre le projet en moins d'une heure :

1. Lire ce README.
2. Lire `AGENTS.md` pour les invariants de contribution.
3. Lire ADR-0001, ADR-0003, ADR-0010, ADR-0011, ADR-0012.
4. Verifier les verrous :

   ```bash
   bash scripts/check-governance-locks.sh
   ```

5. Inspecter le contrat :

   ```bash
   sed -n '1,240p' packages/contracts/src/nexus_contracts/retrieval.py
   sed -n '1,220p' packages/contracts/src/nexus_contracts/profile_auth.py
   ```

6. Inspecter le chemin runtime pilote :

   ```bash
   sed -n '1,260p' services/rag-engine/scripts/retrieval_api.py
   sed -n '1,260p' services/rag-engine/scripts/index_pgvector.py
   ```

7. Inspecter les agents de requete :

   ```bash
   sed -n '1,220p' services/rag-pedago/query_agents/query_orchestrator.py
   sed -n '1,220p' services/rag-pedago/query_agents/query_subject_agent.py
   ```

8. Inspecter les artefacts pilotes :

   ```bash
   find services/rag-pedago/data/chunks -name '*.jsonl' -print0 | xargs -0 wc -l
   find services/rag-pedago/data/embeddings -name '*.jsonl' -print0 | xargs -0 wc -l
   python -m json.tool services/rag-pedago/data/embeddings/review_manifest.json | head -80
   ```

La question d'audit centrale n'est pas seulement "le retrieval repond-il ?", mais "peut-on prouver que chaque passage a ete admis, filtre et servi dans le bon perimetre ?". C'est l'objectif de l'architecture actuelle.
