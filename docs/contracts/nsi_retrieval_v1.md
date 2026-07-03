# Contrat d'interface NSI ⇄ RAG — Retrieval v1

> **Version** : v1-draft — figée au merge de cette PR.
> **Date** : 2026-07-03.
> **Référence** : le consommateur (dépôt cyranoaladin/NSI) épingle ce fichier par
> URL + SHA de commit. Aucune copie locale — cette version fait foi.

---

## §1 — Objet et parties

| Rôle | Identité | Dépôt |
|------|----------|-------|
| **Fournisseur** | Service RAG (plan de données) | `cyranoaladin/RAG` — `services/rag-engine/` |
| **Consommateurs** | `substance_judge.py`, `rag_smoke_test.py`, UI éventuelle | `cyranoaladin/NSI` — `nsi-enseignement/scripts/` et `scripts/` |

Le consommateur interroge le fournisseur via une unique route HTTP.
Il ne connaît ni pgvector, ni le schéma interne, ni le pipeline d'ingestion :
seul ce contrat définit la surface partagée.

---

## §2 — Endpoint de recherche — POST /api/v1/search

### Requête (JSON)

```json
{
  "query": "analyse d'un programme récursif",
  "corpus": "nsi",
  "top_k": 8,
  "filters": {
    "doc_type": ["cours", "td", "tp", "evaluation"],
    "level": "terminale"
  }
}
```

| Champ | Type | Obligatoire | Contraintes | Notes |
|-------|------|-------------|-------------|-------|
| `query` | `str` | oui | `len >= 1` | Texte brut, sans préfixe e5 (cf. §5). |
| `corpus` | `str` | oui | `"nsi"` | Nom logique, résolu côté service (cf. §4). |
| `top_k` | `int` | non | `1..20`, défaut `8` | Nombre de résultats finaux demandés. Appliqué APRÈS rerank (cf. pipeline ci-dessous). |
| `filters` | `object` | non | — | Optionnel. |
| `filters.doc_type` | `str[]` | non | Sous-ensemble de l'enum §3 `document_type` | Filtre inclusif sur type de document. |
| `filters.level` | `str` | non | `"premiere"` ou `"terminale"` | Filtre par niveau. |

### Réponse (JSON)

```json
{
  "hits": [
    {
      "text": "L'analyse d'un programme récursif consiste à identifier le cas de base…",
      "score": 4.23,
      "metadata": {
        "collection": "nsi_corpus_pgv1",
        "source_type": "nsi_corpus",
        "private_data": false,
        "section_anchor": "à-savoir",
        "capacity_ids": "T-LANG-02B,T-LANG-02C",
        "path": "03_progressions/supports/terminale/T06/T06_cours_recursivite.md",
        "level": "terminale",
        "theme": "Langages et programmation",
        "notion": "récursivité",
        "sequence_id": "T06",
        "sha256": "a1b2c3d4e5f6…",
        "status": "needs_review",
        "document_type": "cours"
      }
    }
  ],
  "corpus": "nsi",
  "model": "e5-large",
  "dim": 1024
}
```

| Champ réponse | Type | Notes |
|---------------|------|-------|
| `hits` | `object[]` | Triés par `score` décroissant post-rerank. |
| `hits[].text` | `str` | Texte complet du chunk (pas un aperçu tronqué). |
| `hits[].score` | `float` | Score de pertinence. Garanties contractuelles : (a) tri décroissant — le premier hit est le plus pertinent ; (b) monotonie — un score plus élevé signifie toujours plus pertinent ; (c) type `float`. L'échelle absolue, le modèle de rerank et le seuil interne sont **non contractuels** (cf. encadré ci-dessous). |
| `hits[].metadata` | `object` | Tous les champs §3, aucun omis. |
| `corpus` | `str` | Écho du corpus demandé. |
| `model` | `str` | Identifiant du modèle d'embedding (`"e5-large"`). |
| `dim` | `int` | Dimension vecteur (`1024`). |

### Pipeline de traitement (normatif)

```
texte brut reçu
  → préfixe "query: " appliqué côté service (§5)
  → dense retrieval pgvector avec pré-filtrage structurel :
      WHERE collection = %s
        AND (niveau = %s)          -- si filters.level fourni
        AND (type_doc IN (%s,...))  -- si filters.doc_type fourni
      ORDER BY vector <=> query LIMIT pool_size
  → rerank CrossEncoder
  → seuil interne (non contractuel)
  → tri décroissant par score rerank
  → top_k premiers résultats retournés
```

**Contrainte contractuelle** : le pool de candidats dense (`pool_size`) DOIT
être ≥ `top_k` demandé dans la requête, même après application des filtres
SQL. Recommandation d'implémentation : `pool_size >= 3× top_k` pour absorber
le filtrage par seuil de rerank ; la valeur exacte est non contractuelle et
sera calibrée en LOT R2.

**Pré-filtrage structurel** : les filtres `doc_type` et `level` sont poussés
dans le `WHERE` SQL du dense retrieval (comme le filtre `collection` déjà
présent dans `retrieval_v2_endpoint.py:434`), PAS appliqués en post-traitement.
Justification : un post-filtrage sur N candidats denses vide silencieusement
les réponses quand le type filtré n'est pas dans le top dense — or
`doc_type_filter` est le chemin réel de `judge_role()`
(`substance_judge.py:305`). Les colonnes `type_doc` et `niveau` existent dans
le schéma `rag_chunks` (`schema_rag_chunks.sql` lignes 30, 18) et sont
indexées (lignes 55-56), ce qui rend le pré-filtrage SQL possible sans
modification de schéma.

> **Internals (non contractuels, sujets à calibration)**
>
> Les éléments suivants sont des détails d'implémentation du fournisseur.
> Le consommateur ne DOIT coder AUCUNE logique sur ces valeurs :
>
> - Échelle absolue des scores (actuellement scores bruts CrossEncoder,
>   valeurs typiques `[−5, +12]`)
> - Seuil interne de rerank (actuellement `+1.90`, LOT 24 FF-02b)
> - Taille du pool de candidats (actuellement `RERANK_CANDIDATES=10`)
> - Modèle de rerank (actuellement `cross-encoder/ms-marco-MiniLM-L-6-v2`)
>
> Un changement de ces valeurs = note de version (§10), PAS un bump v2,
> tant que les garanties (a)/(b)/(c) sur `score` sont préservées.

### Réponse vide

Quand aucun hit ne passe le seuil interne ou que le corpus est vide pour les
filtres demandés : HTTP 200, `{"hits": [], ...}`. Jamais une erreur HTTP.
Le consommateur (juge) traite `hits == []` comme absence de preuve
(`empty_evidence()` — `substance_judge.py:194-202`).

### Erreurs

Format uniforme : `{"error": {"code": "<CODE>", "message": "<texte>"}}`

| HTTP | Code | Cause |
|------|------|-------|
| 400 | `invalid_request` | Requête invalide (query vide, top_k hors bornes). |
| 401 | `token_missing` | Header Authorization absent ou token invalide. |
| 403 | `corpus_forbidden` | Token NSI demandant un corpus hors scope (ex. `"nexus"`). |
| 404 | `corpus_unknown` | Corpus demandé inconnu. |
| 503 | `service_degraded` | pgvector ou modèle indisponible. |

Codes stables : le consommateur route dessus. Tout nouveau code = note de version.

### Latence

**À mesurer** en LOT R2 sur CPU dédié. Placeholder honnête : aucun chiffre
tant que la mesure n'est pas faite. Le smoke NSI utilisera un timeout de 60 s
(valeur actuelle de `rag_smoke_test.py`).

---

## §3 — Contrat de métadonnées

Chaque hit DOIT porter TOUS les champs ci-dessous dans `metadata`.
Le consommateur s'appuie sur chacun d'eux — références NSI citées.

### Champs obligatoires

| Champ | Type | Exemple | Consommé par (NSI fichier:ligne) | Notes |
|-------|------|---------|----------------------------------|-------|
| `collection` | `str` | `"nsi_corpus_pgv1"` | `substance_judge.py:32` — `INTERNAL_COVERAGE_COLLECTIONS` allowlist ; `substance_judge.py:35-37` — `is_internal_collection()` | Nom logique de collection (§4). Doit figurer dans l'allowlist NSI. |
| `source_type` | `str` | `"nsi_corpus"` | `substance_judge.py:40-51` — `is_internal_hit()` Barrier B. `rag_core.py:118-120` — enum strict. | Enum STRICT : `{"nsi_corpus", "golden_example", "excluded"}`. Tout autre valeur ⇒ hit rejeté côté NSI (fail-closed). |
| `private_data` | `bool` | `false` | `rag_core.py:128-129` — guard skip. Contrat hérité : `rag_v2_cutover_STATE.md` §"PII=0". | **Bool JSON natif** (`true`/`false`). JAMAIS la string `"false"` — le fail-closed NSI rejetterait tout silencieusement. |
| `section_anchor` | `str` | `"à-savoir"` | `nsi-enseignement/scripts/substance_judge.py:297` — `accepted_evidence()` lit `metadata.section_anchor` (priorité) ou `metadata.anchor` (fallback) ; `nsi-enseignement/scripts/rag_core.py:167` — stocké comme `section_anchor`. Voir E-06/E-09 pour l'écart entre les deux copies du consommateur. | Unicode PRÉSERVÉ. Ni slugification ASCII ni double-encodage. Exemple accentué ci-dessus obligatoire. Ancre dérivée du heading Markdown via `github_slug()` (`rag_core.py:27-34`). |
| `capacity_ids` | `str` | `"T-LANG-01A,T-LANG-01B"` | `rag_core.py:158` — CSV à l'ingestion. | Format CSV figé à la frontière. Le consommateur adapte en liste si besoin. Peut être vide (`""`). |
| `path` | `str` | `"03_progressions/supports/terminale/T06/T06_cours_recursivite.md"` | `substance_judge.py:296` — `accepted_evidence()` lit `metadata.path` pour vérifier la citation dans le fichier source. | Chemin relatif depuis la racine du dépôt NSI. |
| `document_type` | `str` | `"cours"` | `substance_judge.py:174-178` — `doc_type_filter` filtre sur ce champ. `rag_smoke_test.py:109` — affiché. | Valeurs connues : `cours`, `fiche_cours`, `cours_eleve`, `trace`, `td`, `tp`, `starter_code`, `code`, `corrige`, `corrige_code`, `tests_code`, `evaluation`, `bareme`. Extensible (le consommateur filtre par inclusion). |
| `level` | `str` | `"terminale"` | `rag_core.py:135-137` — enum dérivé. | `"premiere"` ou `"terminale"`. |
| `theme` | `str` | `"Langages et programmation"` | `rag_core.py:138` — extrait du frontmatter. | Peut être vide. |
| `notion` | `str` | `"récursivité"` | `rag_core.py:139` — extrait du frontmatter. | Peut être vide. |
| `sequence_id` | `str` | `"T06"` | `rag_core.py:140-144` — extrait du frontmatter ou du chemin. | Format `[PT]\d{2}` (ex. `P04`, `T15`). Peut être vide. |
| `sha256` | `str` | `"0b1196ca988d…"` | `rag_core.py:132` — hash du fichier source. | Hash SHA-256 complet (64 caractères hex). |
| `status` | `str` | `"needs_review"` | `rag_core.py:169` — statut de gouvernance. | Valeurs : `needs_review`, `reviewed`. |

### Règle de compatibilité

- Champs **additionnels** autorisés : le consommateur les ignore.
- Champ **retiré** ou **type changé** = rupture = v2 obligatoire + période de
  double-service ou compat (§10).

---

## §4 — Nom logique de collection

**Proposition** : `nsi_corpus_pgv1`

- `nsi_corpus` : continuité sémantique avec les collections Chroma existantes
  (`nsi_corpus`, `nsi_corpus_v2` — `substance_judge.py:32`).
- `_pgv1` : backend pgvector, contrat v1. Distingue sans ambiguïté du Chroma legacy.
- Ce nom entre dans `INTERNAL_COVERAGE_COLLECTIONS` de NSI et dans son
  policy checker AST — il doit être **unique, stable**, et ne jamais entrer
  en collision avec les collections Nexus (`rag_nexus_*`).

**Résolution côté service** : le corpus logique `"nsi"` envoyé dans la requête
est résolu en nom de collection(s) pgvector par le service. Le mapping exact
(une collection unifiée `nsi_corpus_pgv1` ou un fan-out vers
`rag_nexus_nsi_premiere_specialite` + `rag_nexus_nsi_terminale_specialite`)
est un détail d'implémentation du fournisseur, transparent pour le
consommateur. Le champ `metadata.collection` retourné dans chaque hit DOIT
être `"nsi_corpus_pgv1"`.

> **DÉCISION REQUISE (lead)** : validation du nom `nsi_corpus_pgv1` avant
> ouverture du LOT R1.

---

## §5 — Embedding et parité query-time

| Aspect | Valeur |
|--------|--------|
| Modèle | `intfloat/multilingual-e5-large` (multilingual) |
| Dimension | 1024 |
| Préfixe ingestion | `"passage: "` — appliqué CÔTÉ SERVICE à l'ingestion |
| Préfixe recherche | `"query: "` — appliqué CÔTÉ SERVICE à la recherche |

**Le consommateur envoie du TEXTE BRUT** et n'embarque aucun modèle.

### Implémentation RAG actuelle

Les préfixes sont centralisés dans le package partagé `nexus-contracts` :

- `packages/contracts/src/nexus_contracts/embedding_utils.py:13-15` — `format_passage(text) → "passage: {text}"`
- `packages/contracts/src/nexus_contracts/embedding_utils.py:18-20` — `format_query(text) → "query: {text}"`

Application effective :

- **Ingestion v2** : `services/rag-engine/src/ingestor/ingest_v2.py:214` — `format_passage()` appelée avant `encode()`.
- **Retrieval v2** : `services/rag-engine/src/ingestor/retrieval_v2_endpoint.py:415-418` — `format_query()` appelée avant `encode()`.

### Justification

Le mismatch d'embedder query/index est le mode de défaillance silencieux n°1
(retrieval incohérent sans erreur visible) — leçon documentée de la série NSI
(passage nomic → e5-large). La parité est garantie par le fait que les deux
préfixes vivent dans le même module (`embedding_utils.py`) et que les deux
chemins (ingestion + retrieval) l'importent.

### Écart avec le backend de rollback

Le backend Chroma actuel de NSI (`nsi_corpus_v2`) utilise `nomic-embed-text`
(768d). La migration vers e5-large 1024d implique une ré-ingestion complète
du corpus NSI dans pgvector. Voir §9 écart E-01.

---

## §6 — Authentification et autorisation

### Schéma

| Élément | Spécification |
|---------|---------------|
| Transport | HTTPS |
| Header | `Authorization: Bearer <token>` |
| Scope | Lecture seule + corpus `"nsi"` uniquement |
| Refus cross-corpus | Token NSI + corpus `"nexus"` ⇒ HTTP 403 `corpus_forbidden` |
| Refus inverse | Token Nexus + corpus `"nsi"` ⇒ HTTP 403 `corpus_forbidden` |

### Nomenclature canonique des variables consommateur

Le fichier `.env.rag` côté consommateur est résolu par
`rag_core.resolve_env_file()` (`nsi-enseignement/scripts/rag_core.py:17-24`).
Les clés canoniques sont :

| Variable `.env.rag` | Rôle | Référence NSI |
|---------------------|------|---------------|
| `RAG_API_BASE_URL` | URL du endpoint de recherche | `.env.rag.example:8`, `substance_judge.py:165`, `rag_smoke_test.py:30,75` |
| `RAG_API_KEY` | Bearer token d'authentification | `.env.rag.example:9`, `substance_judge.py:167`, `rag_smoke_test.py:31,84` |
| `RAG_COLLECTION` | Nom de collection par défaut | `.env.rag.example:10`, `substance_judge.py:166` |
| `RAG_BACKEND` | Backend actif (`chroma` ou `nexus_rag`) | `.env.rag.example:7`, `rag_smoke_test.py:29` |
| `RAG_VECTOR_DIM` | Dimension attendue des vecteurs | `.env.rag.example:12`, `rag_smoke_test.py:33` |

**Justification** : `RAG_API_KEY` est le nom existant dans les deux dépôts
(NSI : `.env.rag.example:9`, `substance_judge.py:167` ;
RAG : `services/rag-pedago/.env.example:17`). `RAG_SERVICE_TOKEN` n'existe
dans aucun des deux dépôts (vérifié par grep exhaustif). Le contrat conserve
`RAG_API_KEY` comme nom définitif — une seule nomenclature, pas de renommage
gratuit.

### Rotation

- Le token est généré par l'administrateur du service RAG.
- Côté consommateur, il vit dans `.env.rag` sous la clé `RAG_API_KEY`.
  Jamais en dur dans le code.
- Procédure : générer un nouveau token → mettre à jour côté service →
  mettre à jour `.env.rag` côté consommateur → valider par smoke test.

> **Aucun token dans ce document ni dans aucun exemple.**

---

## §7 — Isolation multi-corpus (exigence produit)

### Garantie exigée

**STRUCTURELLE**, pas conventionnelle : aucune requête `corpus=nsi` ne DOIT
retourner de chunk d'un autre corpus (Nexus, français, maths, etc.), et
réciproquement.

### Mécanisme proposé (basé sur l'existant RAG)

Le schéma pgvector actuel utilise une **table unique `rag_chunks`** avec une
colonne `collection TEXT NOT NULL` indexée (`schema_rag_chunks.sql:17,54`).

Le endpoint `POST /search/v2` filtre structurellement par collection dans la
requête SQL (`retrieval_v2_endpoint.py:434`) :

```sql
WHERE collection = %s AND review_status IN ('reviewed', 'needs_review')
```

Le corpus logique `"nsi"` est résolu en nom(s) de collection(s) pgvector
côté service. Le filtre `WHERE collection = %s` est **paramétré** (pas
concaténé) — pas de risque d'injection SQL.

**Proposition** : le endpoint `POST /api/v1/search` NSI applique le même
filtrage structurel. Le consommateur ne peut pas contourner le filtre : il
n'a accès qu'au corpus autorisé par son token (§6).

### Renforcement optionnel (décision lead)

Alternative au filtrage par colonne : **table ou partition dédiée** pour le
corpus NSI. Avantage : isolation physique. Inconvénient : complexité opérationnelle.
L'existant (colonne + index B-tree) est suffisant si le scoping token (§6) est
correctement implémenté.

> **DÉCISION REQUISE (lead)** : validation du mécanisme d'isolation
> (colonne + scoping token) ou demande de partition physique.

### Tests d'acceptation (spécifiés ici, exécutés en LOT R2)

1. **Test positif** : requête `corpus=nsi`, query arbitraire ⇒ tous les hits
   ont `metadata.collection == "nsi_corpus_pgv1"` ; aucun hit avec un autre
   nom de collection.
2. **Test négatif** : requête `corpus=nsi`, même query ⇒ aucun chunk dont le
   `doc_id` appartient à un corpus Nexus n'est retourné (vérification croisée
   par requête directe pgvector).
3. **Test auth** : token NSI + `corpus=nexus` ⇒ HTTP 403 `corpus_forbidden`.
4. **Test inverse** : token Nexus + `corpus=nsi` ⇒ HTTP 403 `corpus_forbidden`.

---

## §8 — Santé et observabilité — GET /api/v1/health

### Réponse

```json
{
  "status": "ok",
  "corpus_counts": {
    "nsi_corpus_pgv1": 6100
  },
  "embed_model": "e5-large",
  "dim": 1024,
  "reranker": "cross-encoder/ms-marco-MiniLM-L-6-v2"
}
```

> Le compte `6100` est **illustratif**. Le compte pgvector réel sera établi
> en LOT R1 après ré-ingestion depuis les fichiers sources et réconcilié avec
> les 5992 chunks Chroma (écart attendu : chunking différent, cf. §11).

| Champ | Type | Notes |
|-------|------|-------|
| `status` | `str` | `"ok"` ou `"degraded"`. |
| `corpus_counts` | `object` | Nombre de chunks par collection accessible au token. |
| `embed_model` | `str` | Identifiant du modèle d'embedding. |
| `dim` | `int` | Dimension vecteur. |
| `reranker` | `str` | Identifiant du modèle de rerank. |

Le smoke NSI (`scripts/rag_smoke_test.py`) et le monitoring s'appuient sur
cet endpoint pour valider la connectivité et la cohérence dimensionnelle
(`RAG_VECTOR_DIM` dans `.env.rag` — `rag_smoke_test.py:33`).

---

## §9 — Écarts à résoudre

### E-01 : Métadonnées NSI absentes du schéma pgvector

**Constat** : le schéma `rag_chunks` (`scripts/schema_rag_chunks.sql`) ne
contient AUCUN des champs de métadonnées que NSI consomme. Comparaison :

| Champ NSI (§3) | Colonne `rag_chunks` | Statut |
|-----------------|---------------------|--------|
| `collection` | `collection` (ligne 17) | **Existe** mais avec nommage `rag_nexus_*`, pas `nsi_corpus_pgv1`. |
| `source_type` | — | **ABSENT**. Aucune colonne. |
| `private_data` | — | **ABSENT**. Aucune colonne. |
| `section_anchor` | — | **ABSENT**. Aucune colonne. |
| `capacity_ids` | — | **ABSENT**. Aucune colonne. |
| `path` | `source_uri` (ligne 28) | **Sémantique différente** : `source_uri` stocke une URI (URL GDrive, etc.), pas un chemin relatif depuis la racine du dépôt. |
| `document_type` | `type_doc` (ligne 30) | **Nom différent** et **enum incompatible**. 6 des 13 types NSI (`fiche_cours`, `cours_eleve`, `trace`, `starter_code`, `corrige_code`, `tests_code`) sont HORS de l'enum `TypeDoc` de nexus-contracts (`document.py:52-85`). La validation Pydantic (`chunk.py:24`) les REJETTERAIT à l'ingestion. 7 types acceptés : `cours`, `td`, `tp`, `code`, `corrige`, `evaluation`, `bareme`. Décision R1 : soit étendre `TypeDoc`, soit mapper dans l'adaptateur. |
| `level` | `niveau` (ligne 18) | **Nom différent**. Mêmes valeurs sous-jacentes. |
| `theme` | — | **ABSENT**. `notions TEXT[]` (ligne 23) couvre partiellement. |
| `notion` | `notions TEXT[]` (ligne 23) | **Type différent** : string vs array. |
| `sequence_id` | — | **ABSENT**. |
| `sha256` | `chunk_sha256` (ligne 11) | **Sémantique différente** : `chunk_sha256` = hash du chunk, NSI attend `sha256` = hash du fichier source complet. |
| `status` | `review_status` (ligne 40) | **Nom différent**. Mêmes valeurs. |

**Impact** : sans ces champs, le consommateur NSI ne peut pas fonctionner.
`is_internal_hit()` rejette tout (pas de `source_type`), `accepted_evidence()`
ne trouve ni `path` ni `anchor`, le smoke échoue.

**Résolution proposée** : LOT R1 — ajouter les colonnes manquantes au schéma
`rag_chunks` (ou créer une vue/table dédiée NSI), et les peupler à l'ingestion.
Alternativement : l'endpoint `POST /api/v1/search` peut mapper les colonnes
existantes vers les noms de champs attendus par NSI (couche d'adaptation dans
le endpoint, sans toucher au schéma).

### E-02 : Endpoint de recherche inexistant

**Constat** : le endpoint `POST /api/v1/search` spécifié dans ce contrat
N'EXISTE PAS dans le service RAG. Les endpoints existants sont :

- `POST /search` (legacy, Chroma, `api.py:2043`) — body : `{q, collection, k, include_documents, score_threshold, filters}`.
- `POST /search/v2` (pgvector, `retrieval_v2_endpoint.py:377`) — body : `{q, collection, k}`.

Ni l'un ni l'autre ne correspond au format de requête/réponse spécifié ici.

**Impact** : le consommateur NSI devra être adapté pour pointer vers le bon
endpoint et le bon format, OU le fournisseur doit créer un endpoint dédié.

**Résolution proposée** : LOT R1 — créer le endpoint `POST /api/v1/search`
comme adaptateur au-dessus du pipeline v2 existant. Ce endpoint :
(a) accepte le format de requête §2,
(b) résout `corpus=nsi` en collection(s) pgvector,
(c) exécute le pipeline v2 (dense + rerank),
(d) projette la réponse au format §2 (mapping des noms de colonnes + ajout
des métadonnées manquantes).

### E-03 : Format de réponse incompatible

**Constat** : le format de réponse actuel du `POST /search/v2` diffère du
contrat :

| Contrat §2 | SearchV2Response actuelle | Écart |
|-------------|--------------------------|-------|
| `hits[].text` | `hits[].preview` (tronqué à 200 car., `retrieval_v2_endpoint.py:472`) | Contrat exige le texte complet. |
| `hits[].score` | `hits[].rerank_score` + `hits[].dense_sim` | Nom différent. |
| `hits[].metadata` (objet plat) | Champs au niveau du hit (pas de sous-objet `metadata`) | Structure différente. |
| `corpus` | `collection` | Nom différent. |
| `model`, `dim` | Absents de la réponse | Manquants. |

**Résolution** : LOT R1 — l'endpoint adaptateur §2/E-02 gère cette projection.

### E-04 : Authentification non scopée par corpus

**Constat** : le service RAG utilise un token unique (`INGESTOR_API_TOKEN` ou
`INGEST_AUTH_TOKEN` — `retrieval_v2_endpoint.py:494`) pour tous les endpoints,
sans distinction de corpus. Le même token donne accès à tous les corpus.

**Impact** : le contrat §6 exige un scoping par corpus (token NSI ⇒ seul
corpus `nsi` accessible). Sans cela, un consommateur NSI pourrait lire les
chunks Nexus et inversement.

**Résolution proposée** : LOT R1 — implémenter un mécanisme de scoping token.
Options : (a) token dédié par corpus avec table de mapping token→corpus, ou
(b) claims JWT avec champ `corpus_scope`.

### E-05 : Embedding model mismatch avec le backend de rollback

**Constat** : le backend Chroma actuel de NSI (`nsi_corpus_v2` = 5992 chunks,
`rag_v2_cutover_STATE.md:5`) utilise `nomic-embed-text` (768d). Le pipeline
pgvector RAG utilise `intfloat/multilingual-e5-large` (1024d,
`retrieval_v2_endpoint.py:102`).

**Impact** : la migration exige une ré-ingestion depuis les **fichiers sources**
du dépôt NSI (pas un transfert des vecteurs Chroma). Le chunking e5-large
peut produire un compte différent des 5992 chunks Chroma (redécoupage,
sections vides filtrées, PII exclus) — le §11 exige la réconciliation avec
écart expliqué. Les vecteurs nomic et e5-large ne sont pas interopérables.
Le backend Chroma reste disponible pour rollback (aucune modification).

**Résolution** : LOT R1 — ingestion du corpus NSI depuis les fichiers sources
dans pgvector avec e5-large. Le backend Chroma est conservé intact comme
fallback.

### E-06 : Champ `anchor` vs `section_anchor` — BLOQUANT pour le chemin de preuve

**Constat** : deux versions du consommateur lisent des noms de champ différents :

| Fichier | Ligne | Champ lu | Comportement |
|---------|-------|----------|--------------|
| `scripts/substance_judge.py` (racine) | 267 | `metadata.get("anchor", "")` | Lit UNIQUEMENT `anchor`. |
| `nsi-enseignement/scripts/substance_judge.py` | 297 | `metadata.get("section_anchor") or metadata.get("anchor", "")` | Lit `section_anchor` en priorité, fallback `anchor`. |

Or `rag_core.extract_metadata()` stocke le champ comme `section_anchor`
(`nsi-enseignement/scripts/rag_core.py:167`).

**Impact** : **BLOQUANT pour le chemin de preuve consommateur**. Si la version
racine est exécutée, `accepted_evidence()` ne trouve JAMAIS d'ancre → veto
silencieusement vide sur 100% des preuves. C'est le mode de défaillance
silencieux n°1 de la série (pas d'erreur, pas de preuve, verdict
`needs_content` systématique). Ce n'est pas un détail cosmétique — c'est la
branche qui tue le rappel du juge.

Le contrat fixe le nom canonique à `section_anchor` (§3). Le fournisseur RAG
retournera `section_anchor` dans tous les hits.

**Résolution** : prérequis LOT N1 (dépôt NSI) — harmoniser le code
consommateur sur `section_anchor`. Ce n'est PAS un changement côté fournisseur
RAG, mais la migration ne peut pas être validée tant que le consommateur n'est
pas aligné.

### E-07 : Endpoint de santé minimal

**Constat** : le endpoint `GET /health` actuel (`api.py:1936-1938`) retourne
uniquement `{"status": "healthy"}` — sans comptes de corpus, sans modèle,
sans dimension.

**Impact** : le smoke NSI ne peut pas vérifier la cohérence dimensionnelle ni
les comptes de chunks.

**Résolution** : LOT R1 — enrichir ou créer `GET /api/v1/health` avec les
champs §8.

### E-08 : Nomenclature de collection divergente

**Constat** : le catalogue RAG (`rag_collections.yml`) déclare les collections
NSI sous les noms `rag_nexus_nsi_premiere_specialite` et
`rag_nexus_nsi_terminale_specialite` (lignes 49-66). Le contrat §4 propose
`nsi_corpus_pgv1` comme nom unique vu par le consommateur.

**Impact** : le service doit résoudre le corpus logique `"nsi"` en collections
physiques `rag_nexus_nsi_*` et retourner `nsi_corpus_pgv1` dans le champ
`metadata.collection` de chaque hit. Ce mapping est un détail d'implémentation
interne au fournisseur.

**Résolution** : LOT R1 — implémenter le mapping corpus→collection(s) dans
l'endpoint adaptateur.

### E-09 : Duplication du consommateur dans le dépôt NSI

**Constat** : le dépôt NSI contient DEUX copies divergentes des scripts
critiques dans des arborescences distinctes (`scripts/` racine et
`nsi-enseignement/scripts/`). Diff factuel :

#### substance_judge.py

| Aspect | `scripts/` (racine) | `nsi-enseignement/scripts/` |
|--------|--------------------|-----------------------------|
| Barrière A (`INTERNAL_COVERAGE_COLLECTIONS`, `is_internal_collection`) | **ABSENTE** | Présente (lignes 32, 35-37) |
| Barrière B (`is_internal_hit`) | **ABSENTE** | Présente (lignes 40-51) |
| `search_rag()` — collection | Hardcodée `"nsi_corpus"` (ligne 137) | Via `env.get("RAG_COLLECTION")` (ligne 166) |
| `search_rag()` — filtre interne | **Aucun** — tous les hits passent | `is_internal_hit()` appliqué AVANT `doc_type_filter` (ligne 172) |
| `accepted_evidence()` — ancre | `metadata.get("anchor")` UNIQUEMENT (ligne 267) | `metadata.get("section_anchor") or metadata.get("anchor")` (ligne 297) |
| Pré-vol collection | **Aucune validation** | Refuse `RAG_COLLECTION` hors allowlist (lignes 490-500) |
| ENV resolution | Hardcodée `ROOT / ".env.rag"` (ligne 24) | Via `resolve_env_file(ROOT)` (ligne 28) |
| Imports | `from check_substance_anchors import ...` (ligne 20) | `from scripts.check_substance_anchors import ...` (ligne 24) |

#### rag_smoke_test.py

| Aspect | `scripts/` (racine) | `nsi-enseignement/scripts/` |
|--------|--------------------|-----------------------------|
| Collection validation | **Aucune** | Strict : allowlist `{"nsi_corpus", "nsi_corpus_v2"}` (ligne 64) |
| Dimension validation | **Aucune** | Vérifie `RAG_VECTOR_DIM == 768` (strict) |
| Backend validation | **Aucune** | Vérifie `RAG_BACKEND == "chroma"` (strict) |
| ENV resolution | Hardcodée (ligne 24) | Via `resolve_env_file()` |
| Ancre dans metadata | Non vérifié | Vérifie `metadata.anchor or metadata.section_anchor` (ligne 54) |

#### rag_core.py

| Aspect | `scripts/` (racine) | `nsi-enseignement/scripts/` |
|--------|--------------------|-----------------------------|
| Existence | **N'EXISTE PAS** | Présent (209 lignes) — `extract_metadata()`, `resolve_env_file()`, `github_slug()` |

#### Autres fichiers en double

`check_substance_anchors.py` existe dans les deux arborescences (contenu
identique vérifié). Les 27 fichiers de policy checkers et outils RAG
avancés (dont `check_rag_collection_policy.py`, `check_rag_config.py`) sont
**uniquement** dans `nsi-enseignement/scripts/`.

**Impact** : **BLOQUANT — fragmentation de source de vérité**. Les barrières
durcies (A+B), le policy checker AST (19 cas adverses), les guards
`resolve_env_file()` et la validation stricte de collection gardent
UNIQUEMENT la copie `nsi-enseignement/scripts/`. Si la copie racine
`scripts/` est exécutée en production :
- Aucune barrière source_type → des hits tierces (rag_education, etc.)
  seraient acceptés comme preuves internes ;
- Aucune validation de collection → un `RAG_COLLECTION` erroné passerait ;
- `metadata.anchor` manquant → 100% des ancres perdues silencieusement ;
- Toute la chaîne de hardening des PRs #40-56 est contournée.

**Résolution** : **DÉCISION LEAD REQUISE** — désigner l'arbre canonique
(`nsi-enseignement/scripts/` est le candidat évident au vu du hardening) et
prévoir la suppression ou redirection du doublon en LOT N1. Tant que la
duplication persiste, aucune garantie contractuelle ne tient côté
consommateur : le contrat RAG livre les bons champs, mais si le mauvais
script les consomme, le résultat est silencieusement vide.

### Tableau récapitulatif

| Écart | Sévérité | Lot de résolution |
|-------|----------|-------------------|
| E-01 Métadonnées absentes (+ enum `type_doc` incompatible) | **Bloquant** | R1 |
| E-02 Endpoint inexistant | **Bloquant** | R1 |
| E-03 Format réponse incompatible | **Bloquant** | R1 |
| E-04 Auth non scopée | **Bloquant** | R1 |
| E-05 Embedding mismatch (ré-ingestion sources) | **Bloquant** | R1 |
| E-06 `anchor` vs `section_anchor` | **Bloquant** (chemin de preuve) | Prérequis N1 (côté NSI) |
| E-07 Health minimal | Modéré | R1 |
| E-08 Nomenclature collection | Modéré | R1 |
| E-09 Duplication consommateur NSI | **Bloquant** (source de vérité) | N1 (côté NSI, décision lead) |

---

## §10 — Versionnement et cycle de vie

- **v1** figé au merge de cette PR. Toute modification de ce fichier sur `main`
  après merge constitue une nouvelle version.
- **Changement compatible** (ajout de champ dans `metadata`, ajout de valeur
  d'enum `document_type`) : note de version en tête de fichier, pas de bump
  majeur.
- **Changement cassant** (retrait de champ, changement de type, modification
  d'endpoint, rupture des garanties (a)/(b)/(c) sur `score`) : v2 obligatoire
  + période de double-service ou de compat. Le consommateur doit pouvoir
  continuer à fonctionner avec v1 pendant la transition.
- **Recalibration interne** (changement de seuil de rerank, changement de
  modèle de rerank, changement de pool de candidats) : note de version, PAS
  un bump v2, tant que les garanties (a) tri décroissant, (b) monotonie,
  (c) type float sont préservées.
- Le consommateur épingle la version dans sa config (URL + SHA de commit).

### Conséquence pour le consommateur

Le smoke et le juge NSI ne DOIVENT appliquer AUCUN seuil absolu sur `score`.
Le score sert uniquement au tri relatif entre hits d'une même requête.
Leçon héritée : la métrique de distance change avec le modèle, le reranker
ou le seuil — coder un seuil absolu côté consommateur est un mode de
défaillance silencieux garanti lors de toute recalibration fournisseur.

---

## §11 — Critères d'acceptation du contrat

### LOT R1 — n'est PAS terminé tant que :

- [ ] Un hit réel collé ne montre pas TOUS les champs §3 aux bons types :
  - `private_data` = bool nu (pas string)
  - `section_anchor` = ancre accentuée intacte (ex. `"à-savoir"`, pas `"a-savoir"`)
  - `source_type` = valeur de l'enum strict (`"nsi_corpus"`)
  - `document_type` = valeur reconnue par le consommateur
- [ ] Dimension vecteur == 1024 prouvée (requête pgvector directe)
- [ ] Comptes réconciliés avec les 5992 Chroma (écart expliqué si différent —
  ex. chunks redécoupés, PII exclus, sections vides filtrées)
- [ ] Endpoint `POST /api/v1/search` fonctionnel avec le format §2
- [ ] Token NSI dédié créé et scopé (§6)

### LOT R2 — n'est PAS terminé tant que :

- [ ] Les 4 tests d'isolation §7 sont verts (positif, négatif, auth, inverse)
- [ ] Latence CPU réelle mesurée et inscrite en §2 (remplace "à mesurer")
- [ ] Smoke fournisseur : 5 requêtes pédagogiques réelles collées avec réponses
  complètes (dont au moins une par niveau premiere/terminale, et une testant
  un filtre `doc_type`)
- [ ] Endpoint `GET /api/v1/health` retourne les champs §8 avec comptes corrects

---

## Annexe A — Inventaire des fichiers de référence

### Dépôt NSI (consommateur)

| Fichier | Rôle | Doublon ? |
|---------|------|-----------|
| `nsi-enseignement/scripts/substance_judge.py` | Juge de substance — copie **durcie** (barrières A+B, `resolve_env_file`) | Oui — `scripts/substance_judge.py` est la copie **non durcie** (cf. E-09) |
| `nsi-enseignement/scripts/rag_core.py` | Logique partagée RAG — `extract_metadata()`, `resolve_env_file()`, `github_slug()` | Non — n'existe PAS dans `scripts/` racine |
| `nsi-enseignement/scripts/rag_smoke_test.py` | Smoke test strict (allowlist, dim, backend) | Oui — `scripts/rag_smoke_test.py` est la version sans validation strict |
| `nsi-enseignement/reports/closure2/rag_v2_cutover_STATE.md` | État prouvé Chroma v2 (5992 chunks, nomic 768d) | Non |

### Dépôt RAG (fournisseur)

| Fichier | Rôle |
|---------|------|
| `services/rag-engine/src/ingestor/retrieval_v2_endpoint.py` | Endpoint `POST /search/v2` (pipeline v2 certifié LOT 24) |
| `services/rag-engine/src/ingestor/api.py` | Endpoints legacy (`POST /search`, `GET /health`) |
| `services/rag-engine/scripts/schema_rag_chunks.sql` | Schéma pgvector `rag_chunks` |
| `services/rag-engine/configs/rag_collections.yml` | Catalogue des collections (dont NSI) |
| `packages/contracts/src/nexus_contracts/embedding_utils.py` | Préfixes e5 (`format_passage`, `format_query`) |
| `packages/contracts/src/nexus_contracts/retrieval.py` | Contrat Nexus `RetrievalRequest`/`RetrievalResponse` |
| `services/rag-engine/src/ingestor/ingest_v2.py` | Pipeline d'ingestion v2 |
