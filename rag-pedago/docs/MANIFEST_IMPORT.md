# Import de manifest JSONL

Le lot 4 introduit un import controle de manifests JSONL locaux vers le ledger
SQLite. Il ne fait aucune ingestion de documents et ne lit pas les fichiers
pointes par `source_uri`.

## Objectif

Permettre de declarer des documents candidats via des metadonnees validees,
puis de les enregistrer comme `discovered` dans le ledger. Cette etape prepare
un futur import controle sans telechargement, scraping ou parsing.

## Format JSONL

Chaque ligne non vide du fichier JSONL doit etre un objet JSON compatible avec
`DocumentMeta`. Les champs critiques sont notamment :

- `doc_id`
- `source_uri`
- `source_type`
- `sha256`
- `discovered_at`
- `rights`
- `visibility`
- `matiere`
- `type_doc`

Une ligne invalide est rejetee individuellement et enregistree dans `errors`.
Elle n'interrompt pas les autres lignes.

Le hash SHA-256 du fichier manifest est calcule sur les octets du JSONL avant
l'import. Il est expose dans `ImportReport.manifest_sha256`, dans la sortie CLI
et dans le rapport Markdown.

## Ce qui est valide

- JSON syntaxiquement valide ;
- validation Pydantic `DocumentMeta` ;
- droits et visibilite ;
- hash SHA-256 au format attendu ;
- dimensions pedagogiques quand elles sont fournies ;
- retrievability derivee de `rights`.

## Ce qui n'est pas fait

- aucune ouverture du fichier source ;
- aucun telechargement ;
- aucun scraping ;
- aucun parsing PDF ;
- aucune vectorisation ;
- aucun appel reseau ;
- aucun LLM.

## Idempotence

`upsert_document` evite les doublons par `doc_id`. Importer deux fois le meme
manifest cree deux runs et deux etats `discovered`, mais un seul document dans
la table `documents`.

Un `run_id` fourni doit etre unique. Si le run existe deja, l'import leve
`run_id already exists: ...` avant toute ecriture documentaire du second import.
Il n'y a pas de mode `--replace` pour l'instant.

## Droits

Un document `rights=unknown` est stocke pour audit mais `is_retrievable=0`.
Les futurs lots devront continuer a bloquer ces documents au retrieval.

## Erreurs

Chaque ligne invalide cree une entree `errors` avec l'etape
`manifest_import`. Le run est termine en :

- `success` si aucune erreur ;
- `partial` si au moins un document valide et au moins une erreur ;
- `failed` si aucun document valide.

Les erreurs sont normalisees avec :

- `line_number` ;
- `error_type` (`json_decode` ou `validation_error`) ;
- `message` ;
- `doc_id` si detecte ;
- `raw_excerpt` court.

## Rapport genere

Chaque import ecrit un rapport Markdown dans `data/reports/` avec :

- run id ;
- manifest path ;
- manifest sha256 ;
- statut ;
- lignes lues ;
- documents valides et invalides ;
- documents retrievables et non retrievables ;
- documents valides detailles ;
- documents non retrievables avec raison ;
- erreurs par ligne ;
- notes de garantie indiquant qu'aucun `source_uri` n'a ete ouvert et qu'aucun
  appel reseau n'a ete fait.

## Garanties

L'import lit uniquement le fichier JSONL fourni. Il ne lit jamais les fichiers
pointes par `source_uri`, meme si ce sont des URI `file://`. Les tests verifient
egalement que le module d'import ne depend pas de `requests`, `httpx`,
`urllib.request` ou `urlopen`.

## Limites avant lot 5

Le lot 4.5 ne valide pas encore les doublons de `source_uri` entre manifests, ne
scanne pas un dossier de manifests et ne produit pas encore de tableau qualite
global. Ces points peuvent etre traites au lot 5.

## Exemple

```bash
python -m rag_pedago.imports.import_manifest data/fixtures/manifests/sample_documents.jsonl --run-id import-sample-001
```
