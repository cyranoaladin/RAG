# Protocole d’autorisation humaine — brouillon réel metadata-only

## 1. Objectif

L’autorisation humaine ne donne pas le droit de parser, copier, ingérer ou
indexer un document. Elle autorise seulement un futur lot metadata-only
strictement borné, limité à la préparation manuelle de métadonnées sous
contraintes.

## 2. Ce que l’autorisation peut permettre

Uniquement :

- préparer 1 à 2 lignes de métadonnées ;
- vérifier droits, visibilité, provenance ;
- vérifier la cohérence AEFE Tunisie ;
- vérifier le statut candidat ;
- vérifier que le SHA-256 a été calculé hors pipeline ;
- lancer les validateurs metadata-only.

## 3. Ce que l’autorisation ne permet pas

Interdictions explicites :

- copier un PDF dans le dépôt ;
- ouvrir un PDF ;
- parser un PDF ;
- OCR ;
- embedding ;
- Qdrant ;
- scraping ;
- ingestion documentaire réelle ;
- `data/staging` ;
- écriture dans ledger permanent ;
- usage de fichiers du RAG historique ;
- `source_uri` vers `rag-local` ;
- `source_uri` vers `rag-ui` ;
- `source_uri` vers secret ou credential ;
- droits `unknown` ;
- donnée personnelle élève.

## 4. Format du fichier d’autorisation

Format JSON minimal :

```json
{
  "schema_version": "1.0",
  "decision": "approved",
  "scope": "real_minimal_metadata_only_draft",
  "batch_id": "A_REMPLIR",
  "reviewer_name": "A_REMPLIR",
  "reviewer_role": "A_REMPLIR",
  "reviewed_at": "A_REMPLIR_ISO8601",
  "max_items": 2,
  "allowed_subject": "mathematiques",
  "allowed_level": "terminale",
  "allowed_track": "generale",
  "allowed_teaching": "specialite",
  "allowed_zone": "aefe_tunisie",
  "allowed_candidate_status": "scolarise",
  "rights_checked": true,
  "sha256_checked_outside_pipeline": true,
  "no_personal_data": true,
  "no_real_document_copied": true,
  "no_source_uri_opening_allowed": true,
  "no_parsing_allowed": true,
  "no_embedding_allowed": true,
  "no_qdrant_allowed": true,
  "no_scraping_allowed": true,
  "no_data_staging_allowed": true,
  "no_permanent_ledger_write_allowed": true,
  "human_notes": "A_REMPLIR"
}
```

## 5. Conditions de validité

Une autorisation est invalide si :

- `decision != approved` ;
- `scope != real_minimal_metadata_only_draft` ;
- `max_items > 2` ;
- droits non vérifiés ;
- SHA-256 non vérifié hors pipeline ;
- `no_personal_data != true` ;
- `no_real_document_copied != true` ;
- `no_source_uri_opening_allowed != true` ;
- `no_parsing_allowed != true` ;
- `no_embedding_allowed != true` ;
- `no_qdrant_allowed != true` ;
- `no_scraping_allowed != true` ;
- `no_data_staging_allowed != true` ;
- `no_permanent_ledger_write_allowed != true` ;
- zone différente de `aefe_tunisie` ;
- candidat différent de `scolarise` ;
- matière différente de `mathematiques` ;
- niveau différent de `terminale` ;
- enseignement différent de `specialite`.

## 6. Critères d’arrêt immédiat

Arrêter si :

- le fichier d’autorisation est absent ;
- le fichier contient un placeholder `A_REMPLIR` ;
- le fichier mentionne un chemin `rag-local` ou `rag-ui` ;
- le fichier mentionne un secret ;
- le fichier autorise parsing, ingestion, scraping, Qdrant ou embedding ;
- le fichier autorise plus de 2 items ;
- un doute humain subsiste.

## 7. Limites

L’autorisation humaine ne valide pas le contenu pédagogique. Elle valide
seulement que le prochain lot metadata-only peut être préparé sous contraintes.

