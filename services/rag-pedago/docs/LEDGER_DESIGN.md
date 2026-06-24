# Ledger SQLite

Le ledger est le registre local des runs, documents, etats, chunks et erreurs du
pipeline RAG pedagogique. Il sert a rendre les futures operations d'ingestion
deterministes, auditables et reprenables.

## Pourquoi un ledger

Un RAG pedagogique ne doit pas reindexer aveuglement les memes documents. Le
ledger conserve les hash, les etats et les erreurs afin de savoir ce qui a ete
decouvert, parse, chunké, vectorise ou bloque. Il permet aussi de relancer un
traitement apres interruption sans dupliquer les chunks.

## Ce que le ledger fait

- initialise une base SQLite locale ;
- enregistre les migrations appliquees ;
- enregistre les runs ;
- stocke les metadonnees documentaires completes ;
- stocke les etats successifs d'un document ;
- stocke les chunks et leur unicite par document/index ;
- stocke les erreurs recoverables ou non ;
- permet de retrouver le dernier etat d'un document.

## Ce que le ledger ne fait pas

- pas d'ingestion ;
- pas de parsing PDF ;
- pas de scraping ;
- pas de vectorisation ;
- pas de connexion Qdrant ;
- pas de connexion PostgreSQL ;
- pas d'appel LLM.

## Tables

`schema_migrations` suit les migrations appliquees.

`runs` contient un lancement du pipeline ou d'une commande future, avec statut
`running`, `success`, `failed` ou `partial`.

`documents` contient les metadonnees critiques et un `metadata_json` complet du
modele Pydantic `DocumentMeta`. Le champ `is_retrievable` est derive des droits.

`document_states` contient l'historique des etats d'un document. Les etats
autorises reprennent le pipeline cible : `discovered`, `fetched`, `stored_raw`,
`parsed`, `normalized`, `classified`, `enriched`, `chunked`, `embedded_text`,
`embedded_visual`, `upserted`, `verified`, `stale`, `failed`, `quarantined`.

`chunks` contient les chunks futurs. La contrainte `UNIQUE(doc_id, chunk_index)`
interdit deux chunks differents au meme index pour un document. Un upsert propre
est possible uniquement quand le `chunk_id` est identique.

`errors` contient les erreurs rattachees a un run et eventuellement a un
document.

Depuis la migration 2, le ledger contient aussi les tables d'audit de revue :

`review_packages` enregistre les packages de revue et leurs hashes.

`review_decisions` enregistre les approbations ou rejets humains lies a un
package.

`controlled_import_attempts` enregistre chaque tentative d'import controle, y
compris les blocages avant ecriture documentaire.

`controlled_import_verifications` enregistre les controles de hash, gate,
review package, decision et ecriture ledger pour chaque tentative.

## Migrations versionnees

Les migrations sont declarees dans une liste `MIGRATIONS`. La version 1 cree le
schema minimal. La version 2 ajoute l'audit des reviews et imports controles.
`initialize_database` applique uniquement les versions absentes et enregistre
chaque version dans `schema_migrations` avec sa description. Une relance ne doit
pas ajouter de doublon.

## Cycle d'un document

Un document est d'abord insere via `upsert_document`. Les futures etapes du
pipeline ajouteront ensuite des lignes dans `document_states`. Le dernier etat
est calcule par ordre `updated_at DESC, id DESC`.

## Cycle d'un run

Un run est cree avec `create_run`, demarre en `running`, puis termine avec
`finish_run`. Un run echoue peut rester auditable et un nouveau run peut
reprendre le meme document sans le dupliquer.

## Gestion des erreurs

Les erreurs sont enregistrees avec un identifiant stable, une etape, un message
et un indicateur `recoverable`. Une erreur ne supprime pas le document. Elle
permet au run suivant de reprendre.

`finish_run` leve une erreur explicite si le run n'existe pas. Les erreurs avec
`run_id` inconnu ou `doc_id` inconnu sont bloquees par les foreign keys SQLite.

## Revalidation Pydantic

`metadata_json` est la copie complete du modele Pydantic stocke au moment de
l'ecriture. Le repository expose :

- `get_document_meta(doc_id)` ;
- `get_chunk_meta(chunk_id)`.

Ces methodes relisent le JSON puis reconstruisent `DocumentMeta` ou `ChunkMeta`.
Un JSON corrompu ou non conforme leve une erreur claire. Cette revalidation
evite de traiter un payload SQLite comme fiable sans controle.

## `created_at` et `updated_at`

`upsert_document` conserve `created_at` lors d'un update du meme `doc_id`.
`updated_at` est renouvele a chaque upsert. Cette distinction permettra de
connaitre l'apparition initiale d'un document et sa derniere actualisation
metier.

## Regles d'upsert chunk

Un chunk peut etre mis a jour si le `chunk_id` est identique. Deux chunks
differents ne peuvent pas partager le meme couple `(doc_id, chunk_index)`. Cette
regle evite les doublons silencieux lors d'une relance.

## Diagnostics

`check_integrity(db_path)` execute :

- `PRAGMA integrity_check` ;
- `PRAGMA foreign_key_check` ;
- detection des tables attendues ;
- verification de `PRAGMA foreign_keys` ;
- comptage des migrations, runs, documents, chunks, erreurs, packages de revue,
  decisions, tentatives d'import controle et verifications.

La commande `python -m rag_pedago.ledger.init_db --check`, exposee par
`make ledger-doctor`, initialise la base si besoin puis affiche ce diagnostic
minimal.

## Reprise apres echec

Le scenario teste est :

1. run 1 cree ;
2. document ajoute ;
3. etat `discovered` ;
4. erreur enregistree ;
5. run 1 marque `failed` ;
6. run 2 cree ;
7. meme document marque `parsed`.

Le dernier etat devient alors `parsed`.

## Limites volontaires

Le lot 3 reste un socle local. Il ne lance aucune ingestion, ne lit aucun PDF,
ne contacte aucun service externe et ne cree aucun point vectoriel.

Avant le lot 4, le ledger ne lit encore aucun manifest metier. Les diagnostics
verifient la base, pas la qualite pedagogique des documents.

L'audit de revue autorise une ecriture de gouvernance meme quand le gate bloque
un import. Cette ecriture ne cree pas de run document, ne cree pas de document et
ne change aucun etat d'ingestion.
