# Protocole de preflight global metadata-only

## 1. Objectif

Le preflight global agrège les garde-fous metadata-only déjà versionnés afin de
produire un verdict de gouvernance avant tout futur brouillon réel minimal. Il
ne crée aucun brouillon réel et ne donne pas le droit de lire, parser, ingérer
ou indexer un document.

## 2. Périmètre

Le preflight global vérifie uniquement la gouvernance metadata-only. Il ne
valide pas le contenu pédagogique et n’autorise pas l’ingestion documentaire.

## 3. Entrées synthétiques vérifiées

- template manifest incomplet ;
- brouillon rempli synthétique ;
- rehearsal metadata-only ;
- real draft guard synthétique ;
- human unlock synthétique ;
- gate combiné synthétique.

## 4. Conditions de réussite

Le preflight est réussi seulement si :

- template-check retourne `needs_completion` ;
- compile-check retourne `ready` ;
- rehearsal retourne tous les statuts attendus ;
- real-draft-guard retourne `ready_for_human_locked_metadata_validation` ;
- human-unlock retourne `approved_for_metadata_only_next_step` ;
- real-draft-unlock-gate retourne `approved_for_real_metadata_draft_preparation` ;
- aucun document réel n’est présent ;
- aucun PDF/DOCX/PPTX/XLSX n’est présent ;
- aucun `data/staging` n’est créé ;
- le ledger permanent n’est pas modifié ;
- aucun `source_uri` n’est ouvert ;
- aucun réseau, scraping, Docker, Qdrant, embedding, ingestion n’est utilisé.

## 5. Conditions de refus

Refuser si :

- un garde-fou échoue ;
- un statut est inattendu ;
- un fichier réel apparaît ;
- `data/staging` apparaît ;
- le ledger permanent est modifié ;
- un chemin vers `rag-local` ou `rag-ui` apparaît ;
- un secret est détecté ;
- un document réel ou un PDF est détecté.

## 6. Limites

Le preflight ne signifie pas que le contenu pédagogique est bon. Il signifie
seulement que la chaîne de gouvernance metadata-only est prête pour une
prochaine revue humaine.
