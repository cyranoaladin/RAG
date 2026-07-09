# LOT 26 — Cahier des charges et plan d'action Codex Spark

**Date** : 2026-07-09  
**Branche de cadrage** : `codex/cdc-fusion-rag-unifie`  
**Dépôt canonique** : `cyranoaladin/RAG`  
**Objet** : fusion contrôlée des apports `RAG`, `rag-local` et `RAG-Anything` en une plateforme RAG Nexus unique, performante, robuste, gouvernée et sans dette technique volontaire.

---

## 0. Décision d'autorité

Le dépôt `cyranoaladin/RAG` est la seule base canonique.

Les dépôts `cyranoaladin/rag-local` et `cyranoaladin/RAG-Anything` ne doivent jamais être fusionnés à plat. Ils servent uniquement de sources d'implémentations à reprendre sous contrat Nexus :

- `rag-local` : héritage production utile pour Streamlit, ingestion Drive/upload/URL, nginx, smoke, observabilité, logique de parsing existante.
- `RAG-Anything` : adaptateur multimodal optionnel pour extraction structurée de PDF, Office, images, tableaux et équations.

La cible reste l'architecture Nexus actuelle :

```text
services/rag-pedago   -> plan de contrôle, taxonomie, gouvernance, review, agents
services/rag-engine   -> plan de données, ingestion v2, pgvector, retrieval, rerank
services/cockpit      -> SaaS Next.js cible, sans accès direct à pgvector
packages/contracts    -> source unique des modèles partagés
```

---

## 1. Mission Codex Spark

Codex Spark doit transformer le cadrage de convergence en travaux atomiques, testés, réversibles et reviewables.

Codex Spark ne doit pas produire une grande PR monolithique. Il doit produire une suite de PRs ordonnées, chacune avec :

1. un périmètre unique ;
2. des tests automatisés ;
3. un rapport dans `docs/reports/` ;
4. aucune régression volontaire ;
5. aucun secret ;
6. aucune modification de gouvernance non documentée par ADR ;
7. aucun changement de production non demandé explicitement.

La règle de sortie est stricte : un lot est terminé seulement si son code, ses tests, sa documentation et ses garde-fous sont alignés.

---

## 2. Objectifs produit et techniques

### 2.1 Objectif principal

Mettre en place un RAG Nexus unifié qui :

- ingère des documents depuis upload, URL, Google Drive et agents IA ;
- impose une gouvernance `quality -> gate -> review` ;
- stocke dans pgvector dédié en 1024 dimensions ;
- utilise `intfloat/multilingual-e5-large` pour embeddings ;
- sert uniquement des chunks admissibles et revus aux élèves ;
- renvoie des citations complètes ;
- sépare les rôles admin, enseignant/reviewer, agent ingestion et élève ;
- prépare un cockpit Next.js propre, sans casser l'UI Streamlit existante ;
- permet une migration shadow/canary depuis la production actuelle `rag-ui.nexusreussite.academy`.

### 2.2 Objectifs non négociables

- Zéro écriture directe en base hors pipeline v2.
- Zéro `get_or_create_collection` dans le code v2.
- Zéro exposition élève de `review_status = needs_review`.
- Zéro mélange entre embeddings 768d legacy et 1024d Nexus.
- Zéro accès direct cockpit -> pgvector.
- Zéro dépendance métier entre services hors `packages/contracts` ou API.
- Zéro secret ou PII dans le dépôt.
- Zéro déploiement prod automatisé dans ces PRs.

---

## 3. Périmètre fonctionnel cible

### 3.1 Ingestion

Voies à supporter :

1. upload fichiers ;
2. URLs ;
3. Google Drive ;
4. agents IA d'acquisition ;
5. adaptateur multimodal optionnel.

Chaque voie doit produire un document normalisé puis appeler le même pipeline v2.

Pipeline cible :

```text
source entrante
  -> auth + rôle + provenance
  -> validation collection v2
  -> extraction/parsing
  -> normalisation texte/blocs
  -> chunking pédagogique
  -> métadonnées F-01 obligatoires
  -> embedding e5-large 1024d
  -> insertion pgvector rag_chunks
  -> review_status = needs_review
  -> review humaine
  -> review_status = reviewed
```

### 3.2 Retrieval

Le retrieval élève doit suivre :

```text
question + profil signé
  -> vérification HMAC/profil/rôle
  -> sélection collection autorisée
  -> embedding query e5-large
  -> recherche dense pgvector HNSW
  -> filtres collection/niveau/audience/rights/reviewed
  -> rerank CrossEncoder
  -> RetrievalResponse avec citations
```

Réponse minimale attendue :

```json
{
  "results": [
    {
      "chunk_id": "...",
      "doc_id": "...",
      "score": 0.0,
      "title": "...",
      "excerpt": "...",
      "citation": {
        "source_label": "...",
        "source_uri": "...",
        "rights": "...",
        "page": null
      },
      "metadata": {}
    }
  ],
  "warnings": [],
  "filters_applied": {}
}
```

### 3.3 Review

Un contenu ingéré est non publiable par défaut.

États autorisés :

- `needs_review` : créé par ingestion, visible admin/enseignant, invisible élève ;
- `reviewed` : validé humainement, visible si filtres et droits compatibles ;
- `rejected` : exclu du retrieval ;
- `quarantined` : isolé, jamais retrievable.

Le passage `needs_review -> reviewed` doit être un acte explicite d'un rôle reviewer/admin. Aucun agent ne peut l'effectuer seul.

### 3.4 Frontend et dashboard

Court terme : Streamlit reste interface admin d'ingestion. Il doit être branché sur les endpoints v2 et le catalogue `/collections/v2`.

Moyen terme : cockpit Next.js pour :

- recherche élève sourcée ;
- dashboard ingestion ;
- queue de review ;
- indicateurs qualité RAG ;
- observabilité ;
- gestion des collections ;
- gouvernance.

---

## 4. Architecture cible détaillée

### 4.1 Arborescence attendue

Codex Spark doit tendre vers l'arborescence suivante sans déplacements brutaux non nécessaires :

```text
packages/
  contracts/
    src/nexus_contracts/
      retrieval.py
      ingestion.py
      review.py
      collections.py
      profile_auth.py
      audit.py
  rag_anything_adapter/
    src/nexus_rag_anything/
      parser.py
      normalizer.py
      models.py
      settings.py

services/
  rag-engine/
    app/
      main.py
      api/
        health.py
        collections.py
        ingest_v2.py
        review_v2.py
        search_v2.py
        admin.py
      core/
        settings.py
        security.py
        governance.py
      ingestion/
        pipeline.py
        drive.py
        upload.py
        urls.py
        provenance.py
      retrieval/
        dense.py
        rerank.py
        response_mapper.py
      review/
        repository.py
        service.py
      multimodal/
        adapter.py
      observability/
        metrics.py
    legacy/
      README.md

  rag-pedago/
    review/
    query_agents/
    agents/
    taxonomy/
    configs/

  cockpit/
    app/
    components/
    lib/api/
    lib/auth/
```

Cette arborescence est une cible. Codex Spark doit migrer par étapes et utiliser `git mv` pour préserver l'historique lorsqu'il déplace des fichiers.

### 4.2 Interfaces API cibles

Endpoints v2 attendus :

```text
GET  /health
GET  /ready
GET  /collections/v2
POST /ingest/v2/upload-files
POST /ingest/v2/urls
POST /ingest/v2/drive
GET  /ingest/v2/drive/status/{task_id}
POST /ingest/v2/drive/cancel/{task_id}
GET  /review/v2/queue
POST /review/v2/approve
POST /review/v2/reject
POST /review/v2/quarantine
POST /search/v2
GET  /cache/v2/stats
POST /cache/v2/invalidate
GET  /metrics
```

Endpoints legacy à isoler :

```text
/legacy/search
/legacy/ingest
/legacy/collections
/legacy/admin/*
```

Aucun nouveau frontend ne doit appeler les endpoints legacy.

---

## 5. Sécurité et gouvernance

### 5.1 Rôles minimaux

Introduire une couche de sécurité centralisée dans `services/rag-engine/app/core/security.py` ou équivalent.

Rôles :

| Rôle | Autorisations |
|---|---|
| `student` | recherche sur contenus `reviewed` uniquement |
| `teacher` | recherche `reviewed`, consultation des collections, consultation de la queue de review sans décision |
| `reviewer` | droits `teacher` + décisions de review : approve/reject/quarantine |
| `ingest_agent` | ingestion vers `needs_review` uniquement |
| `admin` | toutes opérations v2 hors secrets |

Le rôle `teacher` est volontairement distinct de `reviewer`.
Un `teacher` peut inspecter la queue de review et préparer une validation pédagogique, mais il ne peut pas modifier `review_status`.
Seuls `admin` et `reviewer` peuvent exécuter `approve`, `reject` ou `quarantine`.

Approche acceptable en première étape : tokens séparés par variables d'environnement, sans système OAuth complet.

Variables proposées :

```text
RAG_ADMIN_TOKEN
RAG_REVIEWER_TOKEN
RAG_TEACHER_TOKEN
RAG_INGEST_AGENT_TOKEN
RAG_STUDENT_PROFILE_SECRET
```

Ne pas réutiliser un token unique pour tout.

### 5.2 HMAC profil élève

Le profil élève signé ne doit pas donner de droits admin. Il sert uniquement à filtrer niveau/audience. Le serveur doit ignorer tout `niveau`, `audience`, `role` ou `review_status` fourni par le client dans le body.

### 5.3 Gouvernance

Tout verrou `*_allowed` reste gouverné par :

```text
services/rag-pedago/configs/pedago_interface_contract.yml
scripts/governance-locks.baseline
```

Codex Spark ne doit pas passer un verrou à `true` sans :

1. ADR explicite ;
2. modification baseline ;
3. tests de garde-fou ;
4. rapport de lot.

---

## 6. Plan d'action par PRs

### PR 26.1 — Cadrage et ADR de convergence

Objectif : figer les décisions de fusion.

Travaux :

- Ajouter `docs/adr/ADR-0014-fusion-rag-local-rag-anything.md`.
- Réconcilier la documentation sur les collections v2 : 22 historiques vs catalogue courant.
- Déclarer `RAG` comme dépôt canonique.
- Déclarer `rag-local` comme legacy source-only.
- Déclarer `RAG-Anything` comme adapter multimodal, pas backend.
- Ajouter un rapport `docs/reports/lot_26_1_cadrage_fusion.md`.

Critères d'acceptation :

- ADR clair et daté.
- Aucun code runtime modifié.
- Aucun verrou changé.
- CI documentaire/gouvernance OK.

Commandes :

```bash
bash scripts/check-governance-locks.sh
bash scripts/tests/test-governance-locks.sh
```

---

### PR 26.2 — Fail-closed retrieval v2

Objectif : empêcher tout contenu non revu d'être servi côté élève.

Fichiers probables :

```text
services/rag-engine/src/ingestor/retrieval_v2_endpoint.py
services/rag-engine/tests/test_retrieval_v2_endpoint.py
services/rag-engine/tests/test_review_visibility.py
```

Travaux :

- Modifier `/search/v2` pour filtrer strictement `review_status = 'reviewed'` pour tout appel élève/public.
- Interdire `needs_review`, `rejected`, `quarantined` dans la réponse search.
- Ajouter tests unitaires :
  - un chunk `reviewed` est servi ;
  - un chunk `needs_review` n'est pas servi ;
  - un chunk `rejected` n'est pas servi ;
  - un chunk `quarantined` n'est pas servi ;
  - le cache ne réintroduit pas un chunk devenu non reviewed.
- Documenter la décision dans le rapport de lot.

Critères d'acceptation :

- Aucun endpoint élève ne renvoie `needs_review`.
- Les endpoints review/admin peuvent encore voir `needs_review`.
- Le cache est invalidé ou isolé par statut.
- Tests rouges avant correction, verts après correction.

Commandes :

```bash
cd services/rag-engine
make test
pytest -q tests/test_retrieval_v2_endpoint.py tests/test_review_visibility.py
```

---

### PR 26.3 — Sécurité v2 centralisée et rôles séparés

Objectif : remplacer la logique token unique par une couche d'autorisation explicite.

Fichiers probables :

```text
services/rag-engine/src/ingestor/security_v2.py
services/rag-engine/src/ingestor/ingest_v2_endpoint.py
services/rag-engine/src/ingestor/retrieval_v2_endpoint.py
services/rag-engine/src/ingestor/review_v2_endpoint.py
services/rag-engine/tests/test_security_v2.py
```

Travaux :

- Créer un module sécurité v2 centralisé.
- Définir rôles `admin`, `reviewer`, `teacher`, `ingest_agent`, `student`.
- Remplacer les copies locales `_enforce_security_v2` et `_enforce_security` par appels centralisés.
- Accepter temporairement des tokens par variables d'environnement.
- Refuser tout endpoint sensible si le token attendu n'est pas configuré.
- Ne jamais logger les tokens.
- Logger un hash court de token seulement si nécessaire pour provenance.

Matrice d'autorisation :

| Endpoint | admin | reviewer | teacher | ingest_agent | student |
|---|---:|---:|---:|---:|---:|
| `/search/v2` | oui | oui | oui | non | oui |
| `/ingest/v2/*` | oui | non | non | oui | non |
| `/review/v2/queue` | oui | oui | oui | non | non |
| `/review/v2/approve` | oui | oui | non | non | non |
| `/review/v2/reject` | oui | oui | non | non | non |
| `/review/v2/quarantine` | oui | oui | non | non | non |
| `/cache/v2/invalidate` | oui | oui | non | non | non |
| `/collections/v2` | oui | oui | oui | oui | oui |

Critères d'acceptation :

- Token unique legacy non utilisé pour v2, sauf compat temporaire explicitement documentée.
- Tests de refus 401/403 par rôle.
- Aucun secret dans les tests.
- Aucun token affiché dans logs.
- `teacher` peut accéder à `/review/v2/queue`.
- `teacher` ne peut pas appeler `/review/v2/approve`.
- `teacher` ne peut pas appeler `/review/v2/reject`.
- `teacher` ne peut pas appeler `/review/v2/quarantine`.
- `teacher` ne peut pas appeler `/ingest/v2/*`.

Commandes :

```bash
cd services/rag-engine
pytest -q tests/test_security_v2.py
make test
```

---

### PR 26.4 — Implémentation Drive ingestion v2

Objectif : porter la robustesse Drive de `rag-local` vers le pipeline v2 sans écrire dans Chroma.

Fichiers probables :

```text
services/rag-engine/src/ingestor/drive_v2.py
services/rag-engine/src/ingestor/ingest_v2_endpoint.py
services/rag-engine/tests/test_drive_v2.py
services/rag-engine/tests/test_ingest_v2_endpoint.py
```

Travaux :

- Remplacer le `501` actuel de `/ingest/v2/drive`.
- Créer un service Drive v2 isolé.
- Réutiliser les capacités legacy :
  - listing folder ;
  - export Google Docs en texte ;
  - export Google Sheets en CSV ou texte ;
  - export Slides en texte ;
  - téléchargement DOCX ;
  - fallback PDF texte ;
  - skip fichiers non supportés ;
  - suivi task_id ;
  - déduplication par empreinte.
- La sortie doit appeler `ingest_document(...)` v2.
- Tous les chunks Drive doivent arriver en `needs_review`.
- Les métadonnées F-01 doivent être obligatoires : `source_label`, `source_uri`, `rights`, `doc_id`, `chunk_sha256`.
- La source URI Drive doit être stable et non ambiguë : `gdrive://file/{file_id}` ou URL Drive canonique.

Critères d'acceptation :

- `/ingest/v2/drive` ne retourne plus `501` quand les credentials sont configurés.
- En absence de credentials, retour `503` clair et testé.
- Aucune écriture Chroma.
- Tous les chunks insérés sont `needs_review`.
- Collection validée par `resolve_collection_v2`.
- Tests avec mocks Drive, sans accès réseau réel.

Commandes :

```bash
cd services/rag-engine
pytest -q tests/test_drive_v2.py tests/test_ingest_v2_endpoint.py
make test
```

---

### PR 26.5 — Contrats d'ingestion, review et collections

Objectif : sortir les modèles implicites des endpoints et les placer dans `packages/contracts`.

Fichiers probables :

```text
packages/contracts/src/nexus_contracts/ingestion.py
packages/contracts/src/nexus_contracts/review.py
packages/contracts/src/nexus_contracts/collections.py
packages/contracts/tests/test_ingestion_contract.py
packages/contracts/tests/test_review_contract.py
```

Travaux :

- Ajouter modèles Pydantic partagés :
  - `IngestionSource` ;
  - `IngestionRequest` ;
  - `IngestionResult` ;
  - `ReviewStatus` ;
  - `ReviewDecision` ;
  - `CollectionDescriptor` ;
  - `CollectionListResponse`.
- Aligner endpoints v2 sur ces modèles.
- Interdire les champs extra.
- Ajouter golden tests.

Critères d'acceptation :

- Aucun modèle dupliqué dans les endpoints si un modèle contractuel existe.
- `packages/contracts` reste sans I/O métier.
- Version package incrémentée selon SemVer si nécessaire.

Commandes :

```bash
cd packages/contracts
python -m pytest -q
cd ../../services/rag-engine
make test
```

---

### PR 26.6 — API review v2 complète

Objectif : fournir le workflow humain de validation.

Fichiers probables :

```text
services/rag-engine/src/ingestor/review_v2_endpoint.py
services/rag-engine/src/ingestor/review_repository.py
services/rag-engine/tests/test_review_v2_endpoint.py
```

Travaux :

- Ajouter ou compléter :
  - `GET /review/v2/queue` ;
  - `POST /review/v2/approve` ;
  - `POST /review/v2/reject` ;
  - `POST /review/v2/quarantine`.
- Chaque décision doit stocker :
  - `review_status` ;
  - reviewer hash ou identifiant non secret ;
  - timestamp ;
  - reason ;
  - ancienne valeur ;
  - nouvelle valeur.
- Invalider le cache retrieval après toute décision.

Critères d'acceptation :

- Seul `admin` ou `reviewer` peut modifier le statut.
- Impossible d'approuver un chunk sans F-01 complet.
- Impossible d'approuver un chunk sans `rights` connu/autorisé.
- Cache invalidé.
- Tests de transitions valides et interdites.

Commandes :

```bash
cd services/rag-engine
pytest -q tests/test_review_v2_endpoint.py tests/test_security_v2.py
make test
```

---

### PR 26.7 — Migration Streamlit admin vers endpoints v2

Objectif : conserver la productivité admin sans maintenir l'ancien routage Chroma.

Fichiers probables :

```text
services/rag-engine/src/ui/app_v2.py
services/rag-engine/src/ui/api_client.py
services/rag-engine/tests/test_ui_contract.py
```

Travaux :

- Remplacer les collections hardcodées par appel `/collections/v2`.
- Remplacer les appels legacy ingestion par :
  - `/ingest/v2/upload-files` ;
  - `/ingest/v2/urls` ;
  - `/ingest/v2/drive`.
- Ajouter champs obligatoires dans UI :
  - collection ;
  - rights ;
  - source_label ;
  - matiere ;
  - niveau ;
  - voie ;
  - type_doc.
- Afficher le résultat `needs_review` au lieu de promettre une publication immédiate.
- Masquer ou signaler clairement les rubriques legacy cassées.

Critères d'acceptation :

- Aucune ingestion Streamlit v2 ne va vers Chroma.
- Les collections affichées viennent du catalogue v2.
- L'UI ne permet pas d'omettre `rights`.
- Tests contractuels du client API.

Commandes :

```bash
cd services/rag-engine
make test
```

---

### PR 26.8 — Adaptateur RAG-Anything multimodal

Objectif : intégrer les capacités multimodales sans imposer LightRAG comme backend.

Fichiers probables :

```text
packages/rag_anything_adapter/pyproject.toml
packages/rag_anything_adapter/src/nexus_rag_anything/models.py
packages/rag_anything_adapter/src/nexus_rag_anything/parser.py
packages/rag_anything_adapter/src/nexus_rag_anything/normalizer.py
services/rag-engine/src/ingestor/multimodal_adapter.py
services/rag-engine/tests/test_multimodal_adapter.py
```

Travaux :

- Créer un package adapter optionnel.
- Définir `ParsedBlock` :

```python
class ParsedBlock(BaseModel):
    text: str
    modality: Literal["text", "image", "table", "equation", "generic"]
    page: int | None = None
    caption: str | None = None
    source_ref: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
```

- Convertir la sortie RAG-Anything/MinerU/Docling en blocs Nexus.
- Ne pas utiliser les embeddings OpenAI du README RAG-Anything.
- Ne pas écrire dans LightRAG storage comme backend Nexus.
- Ne pas générer de réponse VLM en production tant que `answer_generation_allowed = false`.

Critères d'acceptation :

- Adapter désactivable si dépendances absentes.
- Tests sans télécharger de gros modèles.
- Fallback texte si multimodal indisponible.
- Aucune dépendance obligatoire lourde dans installation minimale.

Commandes :

```bash
cd packages/rag_anything_adapter
pytest -q
cd ../../services/rag-engine
pytest -q tests/test_multimodal_adapter.py
```

---

### PR 26.9 — Migration corpus legacy vers pgvector v2

Objectif : fournir des scripts sûrs de migration Chroma 768d -> pgvector 1024d.

Fichiers probables :

```text
services/rag-engine/scripts/export_legacy_chroma.py
services/rag-engine/scripts/prepare_legacy_migration.py
services/rag-engine/scripts/reembed_legacy_to_pgvector.py
services/rag-engine/tests/test_legacy_migration.py
```

Travaux :

- Exporter les chunks legacy sans modifier Chroma.
- Filtrer les chunks admissibles : `matiere`, `niveau`, `source_uri` présents.
- Mettre le reste en quarantaine.
- Résoudre `rights` par provenance, jamais par supposition opaque.
- Ré-embedder avec e5-large 1024d.
- Insérer dans `rag_chunks` avec `review_status = needs_review`.
- Produire un rapport JSON de migration.

Critères d'acceptation :

- Script idempotent.
- Dry-run obligatoire par défaut.
- Aucun accès prod requis dans les tests.
- Aucun chunk migré directement en `reviewed`.
- Rapport : total, admissibles, rejetés, raisons, collections cibles.

Commandes :

```bash
cd services/rag-engine
pytest -q tests/test_legacy_migration.py
python scripts/prepare_legacy_migration.py --dry-run --input tests/fixtures/legacy_export.jsonl
```

---

### PR 26.10 — Cockpit Next.js MVP recherche et review

Objectif : démarrer le cockpit cible sans casser Streamlit.

Fichiers probables :

```text
services/cockpit/app/
services/cockpit/components/
services/cockpit/lib/api/
services/cockpit/lib/auth/
services/cockpit/tests/
```

Travaux :

- Créer client API typé pour :
  - `/collections/v2` ;
  - `/search/v2` ;
  - `/review/v2/queue` ;
  - `/review/v2/approve` ;
  - `/review/v2/reject`.
- Créer pages minimales :
  - recherche élève ;
  - dashboard collections ;
  - queue review ;
  - détail chunk ;
  - décision review.
- Ne jamais accéder directement à pgvector.
- Prévoir auth simple par rôles côté serveur.

Critères d'acceptation :

- Cockpit consomme uniquement l'API rag-engine.
- Pas de secret côté client.
- Pas d'appel legacy.
- Pas de génération de réponse sans verrou.

Commandes à définir selon stack cockpit effective.

---

## 7. Tests globaux obligatoires

Chaque PR doit exécuter les tests de son périmètre. Les PRs de code runtime doivent aussi exécuter :

```bash
bash scripts/check-governance-locks.sh
bash scripts/tests/test-governance-locks.sh
```

Avant une PR finale de convergence :

```bash
bash scripts/ci-local.sh
```

Si des dépendances lourdes empêchent la CI locale complète, Codex Spark doit :

1. prouver que l'échec est préexistant ;
2. ajouter la preuve dans `docs/reports/lot_26_*_dettes.md` ;
3. ne jamais masquer un nouvel échec.

---

## 8. Invariants de non-régression

Codex Spark doit ajouter des tests qui échouent si :

- `/search/v2` retourne un chunk `needs_review` à un étudiant ;
- une ingestion v2 écrit dans Chroma ;
- une collection v2 est auto-créée ;
- une collection non instanciée est acceptée ;
- un chunk sans `source_uri` est approuvé ;
- un chunk sans `rights` est approuvé ;
- un endpoint review est accessible avec token ingestion ;
- un endpoint ingestion est accessible avec token élève ;
- un token `teacher` ne peut pas modifier `review_status` ;
- un token `teacher` ne peut pas ingérer ;
- un endpoint cockpit accède directement à pgvector ;
- un embedding 768d est inséré dans `rag_chunks` v2 ;
- un agent passe un contenu en `reviewed`.

---

## 9. Rollback et déploiement

Codex Spark ne doit pas déployer en production.

Les PRs doivent préparer un mode shadow/canary :

```text
legacy Chroma reste actif
pgvector v2 tourne en parallèle
Streamlit admin peut appeler v2 pour ingestion contrôlée
recherche élève bascule collection par collection
rollback nginx en une ligne conservé
```

Tout script touchant la prod doit être :

- dry-run par défaut ;
- idempotent ;
- loggé ;
- sans secret ;
- documenté dans `docs/runbooks/` ;
- validé sur fixture avant prod.

---

## 10. Définition de terminé

Un lot Codex Spark est terminé seulement si :

- le périmètre annoncé est respecté ;
- les tests ciblés passent ;
- les garde-fous gouvernance passent ;
- aucun secret n'est ajouté ;
- aucune route legacy n'est utilisée par du code nouveau ;
- les erreurs sont fail-closed ;
- le rapport de lot existe ;
- la documentation utilisateur ou développeur est mise à jour ;
- les limites restantes sont listées explicitement.

Une PR qui fonctionne mais introduit une dette implicite est à refuser.

---

## 11. Premier ordre d'exécution recommandé

Ordre strict :

1. PR 26.1 — ADR et cadrage.
2. PR 26.2 — fail-closed retrieval v2.
3. PR 26.3 — sécurité/rôles v2.
4. PR 26.6 — review v2 complète.
5. PR 26.4 — Drive ingestion v2.
6. PR 26.5 — contrats ingestion/review/collections.
7. PR 26.7 — Streamlit admin vers v2.
8. PR 26.9 — scripts migration legacy.
9. PR 26.8 — adaptateur RAG-Anything.
10. PR 26.10 — cockpit MVP.

Raison : la sécurité et la non-exposition de contenu non revu doivent précéder l'élargissement des voies d'ingestion et la migration corpus.

---

## 12. Prompt opérationnel pour Codex Spark

Codex Spark doit commencer par :

```text
Tu travailles dans cyranoaladin/RAG uniquement.
Ne modifie pas main directement.
Crée une branche par lot.
Lis AGENTS.md, README.md, docs/adr/, services/rag-engine/configs/rag_collections.yml, services/rag-engine/src/ingestor/retrieval_v2_endpoint.py, services/rag-engine/src/ingestor/ingest_v2.py, services/rag-engine/src/ingestor/ingest_v2_endpoint.py.
Implémente le lot demandé uniquement.
Ajoute les tests avant ou avec le correctif.
Ne touche pas aux verrous de gouvernance sauf instruction explicite.
Ne déploie pas en production.
Ne crée pas de fallback legacy dans le code v2.
À la fin, fournis les commandes exécutées, les résultats, les limites et le rapport docs/reports/lot_26_X_*.md.
```

---

## 13. Points de vigilance senior

- Le plus grand risque est le mélange silencieux legacy/v2.
- Le deuxième risque est de servir du contenu non revu.
- Le troisième risque est de maintenir deux contrats divergents.
- Le quatrième risque est d'intégrer RAG-Anything comme backend au lieu d'un adapter.
- Le cinquième risque est de construire le cockpit avant de verrouiller le moteur.

Tout choix qui augmente ces risques doit être rejeté ou isolé dans une ADR.
