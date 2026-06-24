# Import de repertoire de manifests JSONL

Le lot 5 ajoute un import controle d'un repertoire local contenant des manifests
JSONL. L'import reste non recursif et ne lit jamais les documents pointes par
`source_uri`.

## Objectif

Importer ou pre-valider plusieurs manifests dans un meme lot de travail, avec un
rapport global, des compteurs consolides et une detection de doublons avant les
futurs lots d'ingestion controlee.

## Manifest unique vs repertoire

L'import d'un manifest unique cree un run pour un fichier JSONL. L'import de
repertoire liste les fichiers `.jsonl` directement presents dans le dossier,
calcule les compteurs globaux, detecte les doublons puis lance un run par
manifest en mode reel.

Les run ids reels sont deterministes quand `batch_id` est fourni :

```text
batch-<batch_id>-001
batch-<batch_id>-002
...
```

Si un run id existe deja, l'import reel echoue explicitement au lieu d'ecraser.

## Dry-run

Avec `--dry-run`, le systeme :

- lit les manifests ;
- valide les lignes avec `DocumentMeta` ;
- detecte les doublons ;
- evalue la politique qualite ;
- ecrit un rapport Markdown ;
- ne cree pas de base SQLite si elle n'existe pas ;
- ne cree aucun run, document, etat ou erreur.

Si la politique qualite bloque le lot, le statut devient `dry_run_blocked`.

## Doublons detectes

Le rapport signale :

- `duplicate_doc_ids` : meme `doc_id` dans plusieurs lignes ;
- `duplicate_doc_id_exact` : meme `doc_id` avec payload identique ;
- `duplicate_doc_id_conflicts` : meme `doc_id` avec hash ou payload different ;
- `duplicate_source_uris` : meme `source_uri` avec plusieurs `doc_id` ;
- `duplicate_sha256` : meme hash avec plusieurs `doc_id`.

Ces doublons ne lisent pas les documents sources. Ils sont calcules uniquement
sur les metadonnees des manifests.

## Statuts

Mode reel :

- `success`
- `partial`
- `failed`
- `quality_blocked`

Mode dry-run :

- `dry_run_success`
- `dry_run_warning`
- `dry_run_partial`
- `dry_run_failed`
- `dry_run_blocked`

Un dossier vide ou sans `.jsonl` leve une erreur claire.

## Politique qualite

Le rapport contient une section `Quality policy` et une table `Quality issues`.
Par defaut, les lignes invalides, conflits de `doc_id`, doublons de
`source_uri`, champs pedagogiques critiques manquants et epreuves d'examen
manquantes bloquent l'import reel. Les droits inconnus et doublons de hash sont
des warnings par defaut.

Le CLI expose :

```bash
--strict
--allow-unknown-rights
```

`--strict` rend les droits inconnus bloquants. `--allow-unknown-rights` les
repasse explicitement en warning.

## Rapport global

Le rapport contient :

- `batch_id` ;
- chemin du dossier ;
- nombre de manifests ;
- lignes lues ;
- documents valides et invalides ;
- documents retrievables et non retrievables ;
- doublons detectes ;
- runs crees en mode reel ;
- decision qualite et issues ;
- notes de garantie.

## Garanties et limites

- Aucun `source_uri` n'est ouvert.
- Aucun appel reseau n'est fait.
- Aucun PDF n'est parse.
- Aucun OCR n'est lance.
- Aucun service Qdrant ou PostgreSQL n'est contacte.
- L'import n'est pas recursif.
- Pas encore de mode dry-run pour manifest unique via CLI.
