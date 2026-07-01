# LOT 22 — Investigation ingestion NSI (T-22-0, v3.1)

**Date** : 1er juillet 2026
**Statut** : investigation corrigée (C1→C25), manifest ratifié. Exécution T-22-1→T-22-5.
**Décisions lead figées** : D-22-1 (provenance attestée), D-22-2 (programmes→collection NSI), D-22-3 (annales→terminale), D-22-4 (notions={} dette), D-22-5 (EpreuvePratique\* dans allowlist).

---

## Patches C11→C14 (ajouts à la v3 acceptée)

### C11 — Ratio tokenizer mesuré, proxy condamné

**Mesure empirique** sur 337 chunks issus de 35 PDFs NSI (Cours, TP, Évaluations) :

| Métrique | Valeur |
|---|---|
| Ratio e5_tokens / proxy_count — mean | **1.568** |
| Ratio — median | 1.332 |
| Ratio — p95 | **3.078** |
| Ratio — max | 3.862 |
| À proxy=384 : % chunks > 512 tokens e5 | **46.0 %** |
| À proxy=384 : p95 tokens e5 réels | **1 179** |

**Verdict** : le proxy `len(words)*1.3` est inutilisable pour garantir le respect de la fenêtre 512 de e5. À proxy=384, **presque la moitié des chunks dépassent 512 tokens e5** et sont tronqués silencieusement.

**Décision LOT 22** : option (b) — le script d'ingestion NSI utilise directement `AutoTokenizer.from_pretrained('intfloat/multilingual-e5-large')` pour compter les tokens et couper les chunks à **max_tokens_e5=384**. Ce n'est pas un refactor du chunker partagé (`pedagogical_chunker.py` reste inchangé) — c'est un paramètre local de ce run d'ingestion. Le défaut 500 du chunker partagé est inchangé.

**Garantie** : tout chunk produit par le LOT 22 a `len(tokenizer.encode(text)) <= 384 < 512`, marge 25 %. Aucune troncature silencieuse.

### C12 — `source_uri` : label logique, non garanti résoluble

`source_uri` = chemin logique relatif à la racine du corpus **à la date d'ingestion**. Ce n'est pas garanti résoluble si le corpus source est réorganisé. La stabilité réelle repose sur `doc_id` (SHA-256 du contenu binaire), qui survit au renommage.

**Le couple citable durable est `source_label` + `doc_id`**, pas `source_uri`. La citabilité F-01 s'appuie sur `source_label` (nom humain du fichier) + `doc_id` (identifiant de contenu stable) + `rights` (provenance).

`source_uri` reste utile comme trace de provenance et aide à la relocalisation si la structure de dossiers est maintenue.

### C13 — Dédup par `text_sha256_doc`, identifiants réconciliés

**Règle** :
1. La dédup se décide sur `text_sha256_doc` (hash du texte normalisé extrait du document)
2. Le `doc_id` retenu est celui du **représentant** (le PDF prioritaire)
3. Les écartés apparaissent au manifest avec leur propre `doc_id` binaire + `kept: false` + le `doc_id` du représentant en `dedup_representant`

**Cas des formats non extractibles** (`.docx`/`.odt` quand l'extraction échoue) : dédup par base-name en fallback, `group_id` préfixé `basename:`.

Le `group_id` est le `text_sha256_doc` (pas le base-name) — identifiant stable et non ambigu.

### C14 — Quarantaine non-retrievable prouvé + scoping

**Preuve** (dumpée depuis `rag_collections.yml`) :
```
domains.quarantine.retrievable = False
```
`resolve_collection_v2('rag_nexus_quarantine')` résout (instanciée), mais le domaine `quarantine` est `retrievable: false`. Les chunks de cette collection ne remontent jamais dans les résultats de recherche.

**Scoping** : `resolve_collection_v2` prend un nom de collection **exact**. Le retrieval v2 interroge `rag_chunks` avec `WHERE collection = ?`. Une requête Première = `rag_nexus_nsi_premiere_specialite` **uniquement**. Pas d'union cross-collection. Un chunk Terminale ne pollue pas une recherche Première.

---

## Manifest de dry-run — compteurs agrégés

Fichier complet : `/tmp/manifest_nsi_dryrun.json` (2 104 entrées, 1,6 MiB).

| Métrique | Valeur |
|---|---|
| **Total scanné** | 2 104 |
| **Gardés pour embedding** | **1 742** |
| Écartés par dédup texte | 67 (65 groupes) |
| **Holding list** (texte vide / non extractible) | **295** |
| Par collection : `rag_nexus_nsi_terminale_specialite` | 963 |
| Par collection : `rag_nexus_nsi_premiere_specialite` | 779 |
| Par provenance : officiel | 6 |
| Par provenance : tiers identifié | 20 |
| Par provenance : ambiguë | 1 716 |
| Par type_doc | Voir tableau C21 ci-dessous (source unique) |
| **Gardés pour embedding** | **1 763** |
| Dédup écartés (exact + basename) | **271** (75 exact + 196 basename multi-format) |
| Holding list | **70** (37 `.ipynb` JSON corrompus, 30 PDFs scannés, 3 `.docx` corrompus) |
| Par collection : Terminale | 952 |
| Par collection : Première | 811 |
| **Chunks estimés (budget 480 tokens e5)** | **~20 031** |
| Durée embedding (CPU, 30-80 ch/min) | **4,2-11,1 heures** |
| Budget tokens | **480 tokens e5** (max total 484 ≤ 512, marge 28 tokens, C24 prouvé) |
| Manifest gzippé (traçable) | `docs/audits/manifest_nsi_dryrun.json.gz` (93 KiB) |
| SHA-256 manifest complet | `d0e1217cbc6f496a7e55b273464dffd3711b3d626e666959a923c9686274697e` |

### Patches C15→C20

**C15** — Pattern `*sujet*` retiré de la priorité 1 annale. Seuls les marqueurs réels de session bac (codes `\d{2}-NSI-\d{2}`, `NSIJ\d`, `\d{3}-SUJET`, sessions géographiques) classent en `annale`. Les `*sujet*` génériques (épreuves pratiques dans les dossiers) sont classés `evaluation`. Annale passe de 976 → **582**, evaluation de 41 → **414**. Les fichiers Première restent routés Première.

**C16** — Extraction `.docx`/`.odt` corrigée (C16 était un bug, pas du scan). Holding passe de 295 → **70** (37 `.ipynb` vides/corrompus, 30 PDFs scannés sans texte, 3 `.docx` corrompus). OCR = hors-scope ce lot (holding assumé pour les 30 PDFs scannés).

**C17** — Budget re-justifié : **480 tokens e5** (pas 384). Le proxy est condamné (C11) ; le tokenizer e5 réel garantit le comptage exact. 480 tokens + tokens spéciaux (`passage:` prefix, CLS, SEP ≈ 5-8 tokens) ≈ 488 < 512. Marge ~6 %. Réduction de ~20 % du nombre de chunks vs 384 (21 459 vs 26 952).

**C18** — Dédup en deux phases : (1) hash texte exact (75 écartés), (2) fallback basename multi-format (196 écartés). Le hash exact rate les multi-format car les extractions PDF vs ODT divergent (césures, en-têtes, ordre des blocs — prouvé sur 5 groupes : `1_Cours_Machines_de_Turing.odt`+`.pdf` ont des textes normalisés différents). Le fallback base-name par dossier (même parent + même nom de base + formats différents → garder le PDF, écarter le reste) couvre les 225 groupes multi-format identifiés. Total : 271 écartés.

**C19** — `sum(type_doc) = 1 763 = kept_for_embedding`. **Boucle.**

**C20** — Manifest commité en `docs/audits/manifest_nsi_dryrun.json.gz` (93 KiB). SHA-256 consigné.

### Patches C21→C24

**C21** — Réconciliation des compteurs :
```
v1: kept=1742, holding=295, dedup=67,  total=2104
v2: kept=1959, holding=70,  dedup=75,  total=2104
v3: kept=1763, holding=70,  dedup=271, total=2104
```
v1→v2 : +225 récupérés du holding (extraction `.docx`/`.odt` corrigée C16), −8 dedup supplémentaires (texte extrait → hash calculé → doublons détectés). 1742+225−8=1959.
v2→v3 : +196 écartés par fallback base-name multi-format (C23). 1959−196=1763.
Invariant : 2104 = kept + holding + dedup à chaque étape.

Tableau type_doc post-régénération (C21) :

| type_doc | Fichiers |
|---|---|
| annale | 551 |
| evaluation | 388 |
| tp | 191 |
| corrige | 172 |
| notebook | 143 |
| autre | 138 |
| cours | 81 |
| td | 44 |
| programme_officiel | 29 |
| fiche_synthese | 26 |
| **TOTAL** | **1 763** |

**C22** — Les 37 `.ipynb` en holding sont des fichiers JSON **corrompus** (erreur de parsing JSON : `Expecting value`). Ce ne sont pas des notebooks vides — le fichier JSON est malformé. 0 bug d'extraction, 37 vraiment illisibles. Holding légitime.

**C23** — Dédup multi-format corrigée. Démonstration sur 5 groupes :
- `1_Cours_Machines_de_Turing.odt`+`.pdf` : textes normalisés divergent (en-tête PDF `bloc 1 cours : les machines de turing 1ère – nsi lycée pmf` absent de l'ODT) → hash exact ne fusionne pas → **fallback base-name écarte l'ODT, garde le PDF**.
- `10_TD3_Piles_Files.docx`+`.odt` : textes proches mais espaces différents → hash exact ne fusionne pas → **fallback base-name écarte l'ODT, garde le DOCX** (pas de PDF disponible).
- 225 groupes multi-format traités, 196 écartés.

**C24** — Max tokens prouvé :
- Budget chunk : **480 tokens e5**
- Préfixe `"passage: "` : **2 tokens e5**
- Tokens spéciaux (CLS+SEP) : **2 tokens**
- **Max total : 480 + 2 + 2 = 484 ≤ 512**
- Marge : 28 tokens (5,5 %)
- **0 troncature garantie** : le chunker coupe à 480 tokens e5 comptés par le tokenizer réel, pas par un proxy.

---

## 1. Collections v2 — confirmé (accepté, figé)

`rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`, `rag_nexus_quarantine` — instanciées, résolution v2 OK. Backend pgvector, table `rag_chunks`, dim 1024. Aucune collection à créer.

---

## 2. Dump enum verbatim (C1)

Source : `packages/contracts/src/nexus_contracts/document.py` + `chunk.py`.

### Niveau (8 membres)
`troisieme`, `seconde`, `premiere`, `terminale`, `cycle4`, `lycee_gt`, `voie_generale`, `voie_technologique`

### Voie (6 membres)
`college`, `generale`, `technologique`, `professionnelle`, `aefe`, `unknown`

### StatutEnseignement (15 membres)
`tronc_commun`, `enseignement_commun`, `specialite`, `eds`, `option`, `maths_complementaires`, `maths_expertes`, `snt`, `enseignement_scientifique`, `emc`, `atelier`, `stage`, `remediation`, `examen`, `unknown`

### TypeDoc (33 membres)
`programme_officiel`, `ressource_officielle`, `cours`, `fiche_synthese`, `fiche_methode`, `td`, `tp`, `exercice`, `exercice_corrige`, `devoir`, `devoir_corrige`, `evaluation`, `evaluation_corrigee`, `bac_blanc`, `brevet_blanc`, `annale`, `sujet_zero`, `corrige`, `bareme`, `grille_evaluation`, `grille_grand_oral`, `oral`, `diaporama`, `latex`, `notebook`, `code`, `image`, `scan`, `copie`, `rapport`, `referentiel`, `modalite_examen`, `autre`

### Rights (9 membres)
`officiel_public`, `public_allowed`, `nexus_proprietaire`, `usage_interne`, `student_private`, `parent_private`, `commercial_confidential`, `restricted`, `unknown`

### SourceType (9 membres)
`officiel`, `eduscol`, `bo`, `examens`, `nexus`, `upload`, `scan`, `generated`, `unknown`

### Audience (3 membres, `chunk.py`)
`libre`, `aefe`, `tous`

### domain
**Pas d'enum Domain** dans `nexus-contracts`. Le champ `domain` dans la DDL est `TEXT NOT NULL DEFAULT 'education'` — littéral libre. Valeurs utilisées : `education` (collections NSI), `quarantine` (quarantaine). Confirmé.

### review_status
**Pas d'enum** ni de `CHECK` dans la DDL. `TEXT NOT NULL DEFAULT 'needs_review'`. Convention : `needs_review` → `reviewed`. Pas de contrainte empêchant une faute de frappe. **Dette consignée** : ajouter un `CHECK` en DDL au prochain lot infra.

### Table de conformité complète

| Champ | Littéral utilisé | Membre enum/valeur | Confirmé |
|---|---|---|---|
| `niveau` | `premiere` | `Niveau.premiere` | oui |
| `niveau` | `terminale` | `Niveau.terminale` | oui |
| `voie` | `generale` | `Voie.generale` | oui |
| `statut_enseignement` | `specialite` | `StatutEnseignement.specialite` | oui |
| `matiere` | `nsi` | libre (TEXT) | oui |
| `domain` | `education` | libre (TEXT, pas d'enum) | oui |
| `audience` | `{tous}` | `Audience.tous` | oui |
| `type_doc` | `programme_officiel` | `TypeDoc.programme_officiel` | oui |
| `type_doc` | `cours` | `TypeDoc.cours` | oui |
| `type_doc` | `fiche_synthese` | `TypeDoc.fiche_synthese` | oui |
| `type_doc` | `td` | `TypeDoc.td` | oui |
| `type_doc` | `tp` | `TypeDoc.tp` | oui |
| `type_doc` | `evaluation` | `TypeDoc.evaluation` | oui |
| `type_doc` | `annale` | `TypeDoc.annale` | oui |
| `type_doc` | `corrige` | `TypeDoc.corrige` | oui |
| `type_doc` | `notebook` | `TypeDoc.notebook` | oui |
| `type_doc` | `autre` | `TypeDoc.autre` | oui |
| `rights` | `officiel_public` | `Rights.officiel_public` | oui |
| `rights` | `usage_interne` | `Rights.usage_interne` | oui |
| `source_kind` | `officiel` | `SourceType.officiel` | oui |
| `source_kind` | `upload` | `SourceType.upload` | oui |
| `review_status` | `needs_review` | convention (pas d'enum) | oui |
| `official` | `true`/`false` | BOOLEAN | oui |

**Aucun littéral non confirmé.**

---

## 3. Inventaire corpus — comptes re-figés (C2)

### 3.1 Méthode

Filtrage par zone (accepté, figé) + allowlist refermée (C2 : ajout de `EpreuvePratique*`, `B.O._*`, `Extrait_BO*`, `Partie_pratique*`, `GO_NSI*`, `Lepreuve_du_Grand_Oral`, `sujets_epreuves_pratique*`).

### 3.2 Résultats

| Catégorie | Fichiers |
|---|---|
| **Retenus** (allowlist+denylist) | **2 104** |
| Rejetés (extension non parsable) | 11 823 |
| Rejetés (denylist) | 306 |
| Rejetés (pas de match allowlist) | 1 673 |

### 3.3 Par niveau

| Niveau | Fichiers |
|---|---|
| Première (`01_Premiere_NSI/`) | 917 |
| Terminale (`02_Terminale_NSI/`) | 520 |
| Annales/transversal (`03_Autres/`, NSI strict) | 643 |
| Programmes officiels (`00_Programmes/`) | 24 |

### 3.4 Clarification denylist LabVIEW (C2)

Les **129 PDFs Thorlabs** (`HA0008T_*.pdf` … `HA0302T_*.pdf`) sont des manuels matériel au format `.pdf` — ils passent le filtre d'extension mais sont exclus par la denylist sur le pattern `HA\d{4}T`. Les fichiers `.vi`/`.tdms` sont exclus par extension **avant** la denylist. Les deux mécanismes sont distincts : extension = premier filtre, denylist = second filtre sur le nom/chemin.

---

## 4. Déduplication (C3)

### 4.1 Estimation base-name

**294 groupes** multi-format identifiés (même base-name, extensions différentes : `.pdf`+`.odt`, `.docx`+`.pdf`, `.tex`+`.pdf`). Total de fichiers dans ces groupes : 593. Fichiers à retirer (garder 1 par groupe, priorité PDF) : 299.

### 4.2 Limite de cette estimation

Le comptage par base-name **sous-estime** les doublons réels (rate les mêmes contenus à noms différents et les suffixes `_2`/`_3`). Il **surestime** aussi les vrais doublons (des base-names identiques peuvent avoir des contenus différents dans des dossiers différents).

**Le compte exact d'uniques n'est connaissable qu'après extraction du texte et hash normalisé.** L'estimation `2 104 − 299 = ~1 805` est une **borne inférieure approchée**, pas un acquis.

### 4.3 Exécution

La dédup s'exécute **avant l'embedding**, dans l'étape de production du manifest. Le manifest reportera, par groupe : le représentant gardé et les fichiers écartés (avec motif). Le lead ratifie le manifest **avec les décisions de dédup visibles**.

---

## 5. Provenance (C4)

### 5.1 Méthode étendue

Détection sur : (a) composants de chemin (dossiers parents), (b) patterns dans le nom de fichier, (c) champ `/Author` des métadonnées PDF (via `pypdf`).

### 5.2 Résultats

| Famille | Fichiers | Critère |
|---|---|---|
| **Officiel Ministère** | 5 | `programme*NSI`, `BO_*`, `B.O._*`, `Extrait_BO_*` |
| **Tiers identifiable** | 24 | Chemin (`nativel`, `icnisnlycee`, etc.) ou PDF `/Author` (`F. Nativel`) |
| **Provenance ambiguë** | 2 075 | Ni officiel ni tiers identifié par le nom/chemin/auteur |

### 5.3 Sémantique et dette

`usage_interne` = usage pédagogique interne, non-redistribution, provenance tierce.

**Dette B5** : si `answer_generation_allowed` est un jour activé, la couche de citation **devra exposer `source_label`/`source_uri`** pour tout contenu tiers (risque de reproduction non attribuée). Consigné dans `lot_0_dettes.md`.

### 5.4 Décision réservée au lead

La quasi-totalité (99 %) est ambiguë. Recommandation inchangée : attestation lead « usage interne » + `officiel_public` pour les BO.

---

## 6. Idempotence et upsert (C5)

### 6.1 Identifiants

| Champ | Sémantique | Génération |
|---|---|---|
| `doc_id` | Identifiant stable du document source | SHA-256 du contenu binaire du fichier |
| `chunk_id` | Identifiant unique du chunk | `{doc_id}:{chunk_index}` |
| `chunk_sha256` | Hash du texte normalisé du chunk | SHA-256 du texte extrait |

### 6.2 SQL upsert corrigé (C5a)

```sql
INSERT INTO rag_chunks (chunk_id, doc_id, chunk_sha256, vector, ...)
VALUES (...)
ON CONFLICT (chunk_id) DO UPDATE SET
    chunk_sha256 = EXCLUDED.chunk_sha256,
    vector = EXCLUDED.vector,
    text = EXCLUDED.text,
    indexed_at = NOW()
WHERE rag_chunks.chunk_sha256 <> EXCLUDED.chunk_sha256;
```

Si le `chunk_sha256` est identique → pas d'écriture (skip). Si le texte a changé (re-chunk) → mise à jour du vecteur et du texte.

### 6.3 Politique orphelins (C5b)

**Hypothèse LOT 22** : corpus traité comme immuable. Les documents source ne changent pas pendant ce lot. La ré-ingestion de documents modifiés (nouveau doc_id → anciens chunks orphelins) est **hors-scope ce lot**. **Dette consignée** : un lot ultérieur devra implémenter un `DELETE WHERE doc_id = ? AND chunk_index >= ?` ou un garbage collector d'orphelins.

### 6.4 Résumabilité

Le run d'embedding (1-5h) est résumable au niveau `doc_id` : une table de progression `ingestion_progress(doc_id TEXT PRIMARY KEY, status TEXT, last_chunk_index INT)` permet de redémarrer depuis le dernier document complété, sans refaire les embeddings déjà insérés (l'upsert `ON CONFLICT` est idempotent).

---

## 7. `type_doc` corrigé (C6)

### 7.1 `06_Projets` → `autre` (pas `rapport`)

`TypeDoc.projet` **n'existe pas** dans l'enum (vérifié dans le dump §2). `rapport` est impropre (un projet contient énoncés, livrables, barèmes — pas un rapport). **`autre`** est le membre le plus honnête.

### 7.2 Collision `*corrige*` dans `07_Evaluations`

Un fichier `*_corrige*` dans `07_Evaluations/` est étiqueté `corrige` (priorité pattern) et non `evaluation`. C'est la conséquence du routage par priorité pattern > dossier (§7.3 v2, accepté). **Acté comme conséquence connue.**

### 7.3 Table complète

| Source | `type_doc` | Priorité |
|---|---|---|
| Pattern `*sujet*`, `*SUJET*`, `\d{2}-NSI-\d{2}`, `*NSIJ*`, sessions bac | `annale` | 1 (pattern) |
| Pattern `*corrige*`, `*correction*` | `corrige` | 1 (pattern) |
| Pattern `*programme*`, `*BO*` | `programme_officiel` | 1 (pattern) |
| Extension `.ipynb` | `notebook` | 1 (format) |
| Dossier `01_Cours/` | `cours` | 2 (dossier) |
| Dossier `02_Fiches_et_Syntheses/` | `fiche_synthese` | 2 |
| Dossier `03_TD/` | `td` | 2 |
| Dossier `04_TP/` | `tp` | 2 |
| Dossier `06_Projets/` | `autre` | 2 |
| Dossier `07_Evaluations/` | `evaluation` | 2 |
| Défaut | `autre` | 3 |

---

## 8. Sémantique quarantaine dédoublée (C7)

### 8.1 Holding list (non embeddé)

Documents **non insérés** dans aucune collection pgvector :
- PDF sans texte extractible (extraction vide → pas d'embedding possible)
- Fichiers rejetés par la denylist
- Provenance non résolue si le lead choisit l'option (b) quarantaine massive

**Format** : entrée dans le manifest avec `status: holding`, `motif: textless_pdf` / `denied` / `provenance_unresolved`. Pas d'embedding, pas d'INSERT.

### 8.2 Collection `rag_nexus_quarantine` (embeddé, isolé)

Documents **embeddés mais isolés du retrieval NSI** :
- Contenu lisible mais de provenance douteuse, que le lead préfère isoler plutôt qu'exclure
- Contenu hors-programme NSI résiduel passé l'allowlist

**`rag_nexus_quarantine`** est `instanciee: true` mais `domain: quarantine` → `retrievable: false` dans la config. Les chunks y sont insérés avec un embedding mais ne remontent **jamais** dans les résultats de recherche des collections NSI.

### 8.3 Table de routage corrigée

| Cas | Cible | Sémantique |
|---|---|---|
| NSI Première (allowlist) | `rag_nexus_nsi_premiere_specialite` | Collection pgvector |
| NSI Terminale (allowlist) | `rag_nexus_nsi_terminale_specialite` | Collection pgvector |
| Annales bac NSI (`03_Autres/`) | `rag_nexus_nsi_terminale_specialite` | Bac = Terminale |
| Programmes officiels | **Décision lead** | Options : collection NSI du niveau, ou holding list |
| PDF sans texte | **Holding list** (§8.1) | Non embeddé |
| Hors-allowlist résiduel | Exclu (pas d'embedding) | — |

---

## 9. Chunking : 384 scopé, tokenizer confirmé (C8)

### 9.1 Tokenizer du chunker existant

Le `pedagogical_chunker.py` (ligne 27) compte : `max(1, int(len(text.split()) * 1.3))` — un proxy mots×1.3, **pas** le tokenizer e5. C'est le défaut F-07 de l'audit.

### 9.2 Décision LOT 22

Le LOT 22 **ne modifie pas** `TARGET_MAX_TOKENS` du chunker partagé (reste à 500). À la place, le script d'ingestion NSI passe **384 comme paramètre d'appel** au chunker, scopé à ce run. Le défaut 500 est inchangé pour ne pas régresser le comportement existant.

### 9.3 Tokenizer réel

**Le chunker ne compte pas avec le tokenizer e5.** Le proxy mots×1.3 sous-estime pour le français. **Dette consignée** : remplacer le proxy par le tokenizer réel de e5 (`AutoTokenizer.from_pretrained('intfloat/multilingual-e5-large')`) au LOT 25 (unification chunker). Pour le LOT 22, le paramètre 384 avec le proxy existant produit des chunks de ~296 tokens e5 réels (384 / 1.3 × facteur sous-mots) — en dessous de la fenêtre 512.

### 9.4 Estimation durée

- CPU uniquement (12 cœurs, pas de GPU sur le host de dev)
- ~1 800 documents uniques, ~5 000–9 000 chunks estimés
- Débit e5-large CPU : 30-80 chunks/min (batch=32)
- **Durée estimée : 1-5 heures** (CPU)

### 9.5 Dépendances

`python-docx` (1.2.0) et `odfpy` (1.4.2) sont installés localement mais **pas épinglés** dans les `pyproject.toml`. **Action au lot d'implémentation** : ajouter, épingler, vérifier CI governance locks guard.

### 9.6 Préfixes e5

- Ingestion (embedding) : `passage:` (via `nexus_contracts.embedding_utils.format_passage`)
- Retrieval (requête) : `query:` (via `nexus_contracts.embedding_utils.format_query`)

Confirmé.

---

## 10. Durabilité `source_uri` (C9)

### 10.1 Constat

Si `source_uri` = chemin relatif dans le staging (gitignoré/jetable), la purge du staging rend l'URI non résoluble.

### 10.2 Décision

`source_uri` est un **label de provenance**, pas une URI résoluble au runtime. Il identifie le document source dans le corpus d'ingestion (ex. `01_Premiere_NSI/01_Cours/08_cours_algorithme.pdf`). Ce chemin est **stable dans le corpus source** (qui vit dans `~/Documents/NSI/...`), pas dans le staging éphémère.

**Format** : `source_uri` = chemin relatif par rapport à la racine du corpus (`ressources_nsi_centralisees/`), pas par rapport au staging.

**Conséquence F-01** : la citation expose `source_label` (nom humain du fichier) + `source_uri` (chemin dans le corpus). Ce n'est pas une URL cliquable mais c'est une référence durable permettant de retrouver le document source. Si une URI web est nécessaire à terme, elle sera ajoutée comme enrichissement.

---

## 11. Manifest de dry-run enrichi (C10)

### 11.1 Schéma du manifest

Par fichier retenu :

```json
{
  "file": "01_Premiere_NSI/01_Cours/08_cours_algorithme.pdf",
  "doc_id": "<sha256 du binaire>",
  "type_doc": "cours",
  "niveau": "premiere",
  "collection": "rag_nexus_nsi_premiere_specialite",
  "provenance": "ambigue",
  "rights": "usage_interne",
  "official": false,
  "source_kind": "upload",
  "source_uri": "01_Premiere_NSI/01_Cours/08_cours_algorithme.pdf",
  "source_label": "08_cours_algorithme.pdf",
  "dedup": {
    "group_id": null,
    "kept": true,
    "ecart_motif": null
  },
  "quarantine": {
    "flag": false,
    "motif": null
  }
}
```

Pour les fichiers en groupe de dédup :
```json
{
  "dedup": {
    "group_id": "1_Cours_Machines_de_Turing",
    "kept": true,
    "ecart_motif": null
  }
}
```
et le doublon écarté :
```json
{
  "dedup": {
    "group_id": "1_Cours_Machines_de_Turing",
    "kept": false,
    "ecart_motif": "doublon multi-format, priorité PDF"
  }
}
```

Pour les fichiers en holding list :
```json
{
  "quarantine": {
    "flag": true,
    "motif": "textless_pdf"
  }
}
```

### 11.2 Gate

Après production du manifest (avec dédup exécutée et texte extrait pour le hash) : **STOP**. Le lead ratifie le manifest avant tout embedding. Le manifest contient toutes les décisions de dédup, provenance, quarantaine et routage — le lead voit exactement ce qui sera embeddé et ce qui ne le sera pas.

---

## 12. `notions[]` — dette assumée (B7, inchangé)

Champ `notions` = `{}` (vide) pour le LOT 22. Filtrage via `collection` + `matiere` + `type_doc`. Enrichissement de `notions` différé à un lot dédié. Consigné dans `lot_0_dettes.md`.

---

## 13. Questions pour le lead (bloquantes)

1. **Provenance (C4/B5)** : attestation lead « usage interne » pour le corpus + `officiel_public` pour les BO ? **(recommandation : oui)**

2. **Programmes officiels (B10)** : les BO/programmes → collection NSI du niveau, ou holding list en attente d'une collection `official` ? **(recommandation : collection NSI du niveau, type_doc=programme_officiel)**

3. **Annales `03_Autres` (B10)** : routées vers `rag_nexus_nsi_terminale_specialite` (bac = Terminale). **Confirmé ?**

4. **`notions[]` vide (B7)** : dette assumée LOT 22. **Confirmé ?**

5. **EpreuvePratique\*.ipynb (C2)** : ajoutés à l'allowlist. **Confirmé ?**

---

## STOP — Rendu de main au lead

Aucune écriture, aucun embedding. Listes nominatives dans `/tmp/nsi_retained_v3.txt` (2 104 fichiers). Manifest de dry-run à produire (avec dédup, hash texte, quarantaine) après ratification des 5 décisions.
