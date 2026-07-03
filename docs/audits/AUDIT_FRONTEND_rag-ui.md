# Audit frontend — rag-ui.nexusreussite.academy

**Date** : 2 juillet 2026
**Méthode** : lecture seule (SSH + inspection conteneurs + code UI).
**Contexte** : le RAG NSI est clos (16 892 chunks, patron réutilisable). Cet audit prépare la phase multi-matières.

---

## AU-01 — État réel de la plateforme

### Conteneurs actifs (inchangés depuis LOT 20)

| Conteneur | Image | Status |
|---|---|---|
| compose-ui-1 | compose-ui (Streamlit `app_v2.py`) | Up 2 days (healthy) |
| compose-ingestor-1 | compose-ingestor (FastAPI) | Up 2 days (healthy) |
| compose-chroma-1 | chromadb/chroma:1.1.1 | Up 3 days (healthy) |
| compose-ollama-1 | ollama/ollama:0.3.13 | Up 4 days (healthy) |
| compose-autoheal-1 | willfarrell/autoheal | Up 4 days (healthy) |
| nexus-postgres-db | pgvector/pgvector:pg15 | Up 6 weeks (healthy) |

### Frontend servi

**Streamlit `app_v2.py`**, identique au LOT 20. Aucune modification déployée depuis.

### Connexion UI ↔ moteur

L'UI parle à l'**ancien moteur** (ingestor → ChromaDB 768 dim, nomic-embed-text). Elle **ne parle PAS** au moteur gouverné (pgvector dédié 1024 dim, instance locale port 5436). Les deux mondes sont totalement déconnectés :

| | UI prod (Streamlit) | Moteur gouverné (LOT 22-25a) |
|---|---|---|
| Backend vectoriel | ChromaDB 768 dim | pgvector 1024 dim |
| Embedding | nomic-embed-text (Ollama) | e5-large (sentence-transformers) |
| Collections | 8 (rag_education, nsi_corpus, etc.) | 3 instanciées (rag_nexus_nsi_*, quarantine) |
| Auth | Token Bearer partagé | resolve_collection_v2 + gate fail-closed |
| Rerank | Non | CrossEncoder MiniLM-L-6 + seuil +1.90 |

### Delta vs LOT 20

- Collections ChromaDB : 8 (était 6 au LOT 20, `nsi_corpus_v2` et `rag_divers` apparues depuis)
- Rotation du token : effectuée (LOT 20)
- 3 rubriques UI cassées (Maths 1ère, Web3, Divers) : **toujours cassées** (A-L03-REQUALIFIE, non masquées)
- Code ingestor prod **toujours divergent** du dépôt (91 501 o vs 90 357 o, I-05)

---

## AU-02 — Capacités d'ingestion existantes du frontend

### L'UI a DÉJÀ 3 voies d'ingestion fonctionnelles

Le `app_v2.py` expose des **dashboards d'ingestion complets** par rubrique :

| Voie | Implémentée ? | Fonctions |
|---|---|---|
| **Upload fichiers** | **OUI** | `st.file_uploader` multi-fichiers → `/ingest/upload-files` |
| **URLs** | **OUI** | Saisie d'URLs → `/ingest/urls` + vérification doublons |
| **Google Drive** | **OUI** | Saisie folder ID → `/ingest/drive` + suivi progression async |

Chaque rubrique (Éducation, Maths 1ère, Divers, Web3) a ses propres **3 onglets** (Upload, URLs, Drive) avec métadonnées pré-remplies (section, collection, matière, niveau).

### API ingestor — endpoints d'ingestion

| Endpoint | Méthode | Fonction |
|---|---|---|
| `/ingest/upload-files` | POST | Upload fichiers + ingestion |
| `/ingest/urls` | POST | Ingestion par URLs |
| `/ingest/drive` | POST | Ingestion Google Drive (async) |
| `/ingest/drive/status/{task_id}` | GET | Suivi progression Drive |
| `/ingest/drive/cancel/{task_id}` | POST | Annulation Drive |
| `/ingest/check-duplicates` | POST | Vérification doublons |
| `/ingest` | POST | Ingestion texte brut |
| `/admin/documents` | GET/POST | CRUD documents |
| `/admin/reindex` | POST | Réindexation |

### Ce qui manque pour les 3 voies visées

| Besoin | État |
|---|---|
| 3 voies d'ingestion (Drive, upload, URLs) | **DÉJÀ IMPLÉMENTÉES** dans l'UI actuelle |
| Routage vers les collections v2 (rag_nexus_*) | **ABSENT** — l'UI route vers ChromaDB legacy |
| Gate F-01 (rights/source_label/doc_id) | **ABSENT** côté ingestor legacy |
| review_status = needs_review | **ABSENT** — l'ingestor legacy n'a pas ce champ |
| Sélection niveau/matière multi-matières | **PARTIEL** — rubriques hardcodées (Éducation, Maths, Web3), pas dynamiques |
| API pour agents IA | **OUVERTE** — tout endpoint d'ingestion est appelable avec le token Bearer, aucun contrôle de provenance |

---

## AU-03 — Taxonomie et arborescence des collections

### Catalogue actuel (22 entrées v2)

12 matières × 4 niveaux (3e→Tle), mais pas toutes les combinaisons :

| Matière | 3e | 2de | 1re | Tle | Total |
|---|---|---|---|---|---|
| Maths | ✓ tc | ✓ tc | ✓ tc | ✓ spé | 4 |
| Histoire-Géo | ✓ tc | ✓ tc | ✓ tc | ✓ tc | 4 |
| NSI | — | — | ✓ spé | ✓ spé | 2 |
| Français | ✓ tc | — | ✓ tc | — | 2 |
| Physique-Chimie | — | — | ✓ spé | — | 1 |
| SVT | — | — | ✓ spé | — | 1 |
| SES | — | — | ✓ spé | — | 1 |
| Philosophie | — | — | — | ✓ tc | 1 |
| SNT | — | ✓ tc | — | — | 1 |
| Grand Oral | — | — | — | ✓ ex | 1 |
| Examens | — | — | ✓ ex | ✓ ex | 2 |
| Candidats libres | — | — | — | ✓ rem | 1 |
| **+ Quarantaine** | | | | | 1 |
| **Total** | | | | | **22** |

### Trous de couverture

| Dimension manquante | Impact |
|---|---|
| **Maths spécialité Première** | Pas de collection (seul tronc commun). Maths spé 1re = programme distinct |
| **Français Seconde/Terminale** | Seconde TC absent, Terminale (Grand Oral littéraire) absent |
| **PC/SVT/SES Terminale** | Spécialités Terminale non couvertes |
| **Options** (maths complémentaires, maths expertes, DGEMC, arts) | Pas de collection. Enums StatutEnseignement prêts (O-03 LOT 21) |
| **Enseignement scientifique** (1re/Tle TC) | Enum `enseignement_scientifique` existe, pas de collection |
| **EMC** | Enum `emc` existe, pas de collection |
| **Langues vivantes** | Absentes de la taxonomie |

---

## AU-04 — Écart par voie d'ingestion

### Voie Drive

| Aspect | État actuel | Écart |
|---|---|---|
| Intégration Drive | **OUI** — `gdrive-sa.json` (service account), API listing + fetch |
| Auth GDrive | Service account Nexus (credentials en `/srv/nexusreussite/rag-ui/creds/`) |
| Routage | → ChromaDB legacy (`rag_education`, etc.) | **→ doit router vers les collections v2** |
| F-01 (provenance/rights) | **ABSENT** — pas de `rights`, `source_uri` = URL Drive brute |
| review_status | **ABSENT** — contenu servi immédiatement |

### Voie dépôt direct (upload)

| Aspect | État actuel | Écart |
|---|---|---|
| Upload fichiers | **OUI** — `st.file_uploader` multi-fichiers, multi-format |
| Stockage | Fichiers uploadés dans `/data/uploads/` (bind mount) |
| Parsing | PDF, DOCX, multimodal (images si MULTIMODAL_ENABLED=true) |
| Routage | → ChromaDB legacy | **→ doit router vers v2** |
| F-01 | **ABSENT** |
| review_status | **ABSENT** |

### Voie agents IA

| Aspect | État actuel | Écart |
|---|---|---|
| API accessible | **OUI** — tout endpoint d'ingestion avec le token Bearer |
| Contrôle de provenance | **AUCUN** — un agent qui a le token peut ingérer n'importe quoi |
| D-AGENT-JUSQU-A-NEEDS-REVIEW | **NON IMPLÉMENTÉ** — contenu servi immédiatement |
| F-01 (rights par provenance) | **ABSENT** — pas de classification automatique |

### Contrainte de gouvernance commune aux 3 voies

Quel que soit la voie, l'invariant D-AGENT-JUSQU-A-NEEDS-REVIEW exige :
1. Le contenu ingéré arrive avec `review_status = needs_review`
2. `rights` et `source_uri` sont renseignés (F-01)
3. Le passage à `reviewed` est un acte humain (enseignant)
4. Le routage vers la collection v2 est contrôlé (resolve_collection_v2)

---

## AU-05 — Dettes et risques de sécurité

### Dettes frontend

| Dette | Sévérité | Commentaire |
|---|---|---|
| 3 rubriques cassées (Maths 1ère, Web3, Divers) | Basse | Documentées, non masquées (A-L03) |
| Code ingestor divergent du dépôt | Moyenne | 91 501 o vs 90 357 o (I-05) |
| Pas de routage v2 | **Haute** | L'UI ne parle qu'à ChromaDB legacy |
| Pas de review_status | **Haute** | Tout contenu ingéré est servable immédiatement |
| Pas de F-01 | **Haute** | Pas de rights/source_label obligatoires |

### Risques de sécurité

| Risque | Sévérité | Détail |
|---|---|---|
| Token Bearer = accès complet | Moyenne | Un seul token donne accès à l'ingestion, la recherche, l'admin |
| Pas de contrôle de provenance sur l'ingestion | **Haute** | N'importe quel contenu peut être ingéré via les 3 voies |
| `/metrics` public | Basse | Informations d'infrastructure exposées |
| INGESTOR_IP_ALLOWLIST vide | Moyenne | API accessible depuis localhost sans restriction |

### Qui peut ingérer aujourd'hui ?

Quiconque possède le token Bearer peut ingérer via l'UI ou l'API. Pas de distinction de rôle, pas de provenance vérifiée, pas de review_status. **C'est le bug I-06 (contenu non revu servi) industrialisé.**

---

## Recommandation — Streamlit vs cockpit Next.js

### Option A — Garder et améliorer Streamlit

| Pour | Contre |
|---|---|
| Les 3 voies d'ingestion sont DÉJÀ implémentées | Code monolithique (app_v2.py, divergent du dépôt) |
| L'UI est fonctionnelle et familière au lead | Pas d'auth par profil (un seul token) |
| Coût d'amélioration modéré : ajouter routage v2 + F-01 + review_status | Architecture non alignée avec ADR-0001 (cockpit = cible) |
| Quick-win pour la phase multi-matières | Streamlit a des limites sur les workflows complexes (multi-étapes, validation humaine) |

### Option B — Cockpit Next.js

| Pour | Contre |
|---|---|
| Aligné avec l'architecture cible (ADR-0001) | Le cockpit est un placeholder vide — tout à construire |
| Auth par profil (HMAC, rôles enseignant/admin/élève) | Effort élevé (~4-6 lots) pour reproduire les fonctionnalités existantes |
| Workflow de validation humaine (enseignant) natif | Les 3 voies d'ingestion à ré-implémenter |
| Multi-matières/multi-niveaux dynamiques | Retarde la mise en service multi-matières |

### Recommandation : **Option A — améliorer Streamlit, PUIS migrer**

**Justification** :
1. Les 3 voies d'ingestion **existent déjà** dans Streamlit — les recoder from scratch dans Next.js retarderait la phase multi-matières de plusieurs lots.
2. L'effort pour ajouter routage v2 + F-01 + review_status à l'ingestor existant est **modéré** (le pipeline d'écriture pgvector v2 existe, il faut le brancher).
3. Le cockpit Next.js se construit **en parallèle** comme interface élève/enseignant (recherche + validation), pendant que Streamlit sert d'interface admin/ingestion.
4. La migration Streamlit → cockpit se fait **par fonctionnalité** (d'abord la recherche côté cockpit, puis l'ingestion), pas d'un coup.

**Le bloqueur n'est pas le frontend — c'est l'ingestor** : quel que soit le frontend, il faut modifier l'ingestor pour router vers pgvector v2 avec F-01/review_status. C'est le même travail pour les deux options.
