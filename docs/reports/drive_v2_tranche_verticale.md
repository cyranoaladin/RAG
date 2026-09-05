# Tranche verticale Drive v2 — d'un PDF réel au staging gouverné

Branche `glr/drive-v2`. Ce rapport consigne ce que la tranche a réellement
traversé, les compteurs mesurés, les mutations prouvées, et **ce qui reste
bloqué** — la dernière section est la plus importante.

## Ce que la tranche traverse

```
Google Drive API
  → GoogleDriveTransport        (drive_transport.py)   le seul code qui parle au réseau
  → DriveSourceAdapter          (drive_source.py)      énumération, raccourcis, empreinte
  → acquire_corpus              (corpus_acquisition.py) FOYER MÉTIER : matérialise + REHACHE
  → require_scoped_reconciled   (corpus_acquisition.py) recoupement sur le périmètre demandé
  → classify_from_hints         (drive_slice.py)       classification depuis le chemin gouverné
  → extract_pdf_pages           (drive_extraction.py)  runtime pypdf canonique (6.14.2)
  → make_chunks                 (drive_slice.py)       un chunk par page, identité = (artefact, rang, texte)
  → PostgresStagingStore        (drive_staging_pg.py)  staging du plan de contrôle, `needs_review`
```

L'adaptateur ne fournit que la frontière source. `acquire_corpus` reste le
foyer : c'est son rehachage intégral qui fait passer d'un contenu déclaré à
un contenu prouvé, et le découpage lit les octets **écrits par
l'acquisition**, jamais ceux rendus par le téléchargement.

## Le PDF Drive réellement traité

| | |
|---|---|
| Chemin | `01_EDUSCOL_OFFICIEL/LYCEE/TERMINALE/MATHEMATIQUES/01_PROGRAMMES_OFFICIELS/2026/programme-de-l-enseignement-de-specialite-de-mathematiques-de-la-classe-terminale-de-la-voie-generale--9c99a32bb3.pdf` |
| `drive_file_id` | `1j-xF9bKsyu-oX_czky-Jsyh_iBEwOmy_` |
| `size` | 511 499 octets |
| `modified_time` | `2026-08-05T01:53:07.337Z` |
| `content_sha256` = `artifact_id` | `9c99a32bb3e5f14d8906783f86a9a0fd86a99543b032a20fe388841d024ed4a5` |
| Digest **déclaré** par `00_ADMIN/SHA256SUMS.txt` | identique — recoupement de périmètre OK |
| Classification produite | zone `01_EDUSCOL_OFFICIEL`, cycle `lycee`, niveau `terminale`, matière `mathematiques`, nature `programmes_officiels`, millésime `2026`, `servable = true` |
| Chunks stagés | 14, tous `needs_review` |

Interrogation du staging (`matiere=mathematiques`, motif `suites`) : 6 chunks,
dont le chunk de rang 7 (page 8) « En classe de première, l'étude des suites
est abordée sous un angle essentiellement algébrique… ». Le contenu servi est
bien le programme officiel, pas un artefact d'extraction.

## Preuve 1 — bout en bout sur la racine réelle

Découverte **complète** de `NEXUS_RAG_GDRIVE_READY`
(`1OEwXePZors4rlCHv_4nwuPjqtIdM2naX`) par l'adaptateur lui-même : 1 288
dossiers énumérés, ~9 min par passage. Exclusions gouvernées relevées et
**nommées**, jamais comptées comme erreurs :

```
EXCLUSION EXCLUDED_BY_GOVERNED_SOURCE_CLASS NEXUS_RAG_GDRIVE_READY/00_INDEX_PROVENANCE/ARCHIVES_SOURCES_NON_INGESTABLES
EXCLUSION EXCLUDED_BY_GOVERNED_SOURCE_CLASS NEXUS_RAG_GDRIVE_READY/00_INDEX_PROVENANCE/OUTILS_NEXUS_NON_INGESTABLES
```

## Preuve 2 — idempotence

Même instantané Drive, deux exécutions complètes, même base de staging :

| compteur | passage 1 | passage 2 |
|---|---|---|
| `NEW_ARTIFACTS` | 1 | **0** |
| `DUPLICATE_ARTIFACTS` | 0 | 1 |
| `NEW_CHUNKS` | 14 | **0** |
| `DUPLICATE_CHUNKS` | 0 | **14** |
| `NEW_PROVENANCES` | 1 | 0 |
| `ACQUIRED_BYTES` | 1 099 550 | 1 099 550 |
| `MANIFEST_SHA256` | `fcc9bd4e…8272` | `fcc9bd4e…8272` |

`NEW_ARTIFACTS_SECOND_RUN = 0` et `DUPLICATE_CHUNKS_SECOND_RUN = 14` (aucun
chunk nouveau). Après les deux passages, la base contient 1 artefact,
1 provenance, 14 chunks. Les mêmes octets donnent le même `artifact_id`
parce que l'identité **est** l'empreinte : le schéma l'impose
(`CHECK (artifact_id = content_sha256)`), il ne fait pas confiance à un
identifiant fourni.

## Preuve 3 — raccourcis

Une occurrence logique n'est pas un artefact physique. Le raccourci est
résolu vers sa cible ; sa taille et sa date sont lues à la cible (le
raccourci ne les porte pas). Deux occurrences du même contenu donnent **un**
artefact, **deux** provenances, **un seul** téléchargement — vérifié sur le
journal du transport, pas sur un compteur interne
(`test_une_occurrence_supplementaire_ne_retelecharge_pas_les_memes_octets`).
Un raccourci vers un dossier déjà planifié n'est pas redescendu, et un cycle
`racine → dossier → raccourci vers la racine` se referme sans boucler.

## Preuve 4 — pagination réelle, contre l'API vivante

Aucun dossier de la racine ne dépasse 200 enfants : la pagination ne se
serait jamais déclenchée avec la taille de page par défaut, et un test
« vert » l'aurait laissé croire. La taille de page est donc réglable
(`NEXUS_GDRIVE_PAGE_SIZE`), et la preuve a été faite sur le plus gros
dossier réel (96 objets) avec `page_size=10`, en appelant Drive :

```
PAGES_REELLES=10
OBJETS=96
TAILLES_DE_PAGE=[10, 10, 10, 10, 10, 10, 10, 10, 10, 6]
JETONS_DISTINCTS=10
PANNE=panne réseau simulée au milieu d'une pagination réelle
AVANT_PANNE=40 APRES_REPRISE=56 TOTAL=96
DOUBLONS=0
IDENTIQUE_A_UNE_PASSE_UNIQUE=True
DECOUVERTE_REPRODUCTIBLE=True
```

La panne survient à la 5ᵉ page ; l'état de découverte n'ayant pas avancé sur
la page échouée, la reprise repart exactement là et rend les 56 objets
restants : ni perte, ni doublon, inventaire identique à une passe unique.
Jeton rejoué et réponse partielle sont couverts en test unitaire (voir
mutations).

## Mutations prouvées

17 gardes, chacune cassée puis restaurée, test ciblé rouge puis vert
(harnais reproductible, `mutations.py`) :

1. champs obligatoires d'une entrée Drive → **ROUGE**
2. taille déclarée obligatoire → **ROUGE**
3. cache d'octets (pas de retéléchargement) → **ROUGE**
4. taille annoncée vs octets arrivés → **ROUGE**
5. jeton de page rejoué → **ROUGE**
6. dossiers déjà visités → **ROUGE (boucle infinie, arrêtée à 20 s)**
7. sous-arbres non ingestibles nommés → **ROUGE**
8. objet acquis hors du périmètre demandé → **ROUGE**
9. objet demandé jamais déclaré par le producteur → **ROUGE**
10. périmètre vide refusé → **ROUGE**
11. rang de chunk = rang de page → **ROUGE**
12. staging jamais marqué relu → **ROUGE**
13. chemin de classification ambigu → **ROUGE**
14. périmètre absent de la source → **ROUGE**
15. portée Drive en lecture seule → **ROUGE**
16. identifiants jamais devinés → **ROUGE**
17. réponse Drive sans liste `files` → **ROUGE**

La garde 16 a d'abord révélé un **test trop lâche** : il acceptait aussi bien
« la variable n'est pas définie » que « ce fichier n'existe pas », donc un
repli sur `~/creds.json` passait inaperçu. Le test a été resserré sur le
message exact avant que la garde soit déclarée prouvée.

## Qualité

Depuis `services/rag-pedago` :

- `ruff check .` — **All checks passed**
- `mypy schema pipeline retrieval services rag_pedago scrapers agents` — **103 fichiers, aucune erreur**
- `pytest -q` — **3180 passés, 4 ignorés** (dont 78 nouveaux)

Note d'environnement : lancé depuis le worktree avec le venv du checkout
principal, 4 modules de test échouent à la collecte parce que l'installation
éditable de `nexus-contracts` pointe vers l'autre branche. Avec
`PYTHONPATH` sur les paquets du worktree, la suite est intégralement verte.
Ce n'est pas une dette du lot.

## ESCALADE — ce qui n'a pas été fait, et pourquoi

**Le 501 de `services/rag-engine/src/ingestor/ingest_v2_endpoint.py` est
laissé en place.** Il ne doit pas tomber ici, pour deux raisons distinctes :

1. **Règle cross-service.** `acquire_corpus` — le foyer métier imposé — vit
   dans `rag-pedago` (plan de contrôle) ; l'endpoint vit dans `rag-engine`
   (plan de données). Câbler l'un sur l'autre exigerait un import direct
   entre services, ce qu'AGENTS.md interdit. La tranche a donc été menée
   **entièrement dans le plan de contrôle**, jusqu'à un staging qui lui
   appartient.

2. **Le verrou de revue.** Le chemin qui rend un chunk *servable* dans
   `rag-engine` est `publish_governed_artifact`, et il exige une attestation
   LOT42-V2 liée au contenu, une ressource en `RETRIEVAL_ELIGIBLE` et une
   autorisation de scope — c'est-à-dire `quality → gate → review` avec un
   humain dedans. L'autre chemin disponible (`ingest_document`) écrit dans
   `rag_chunks` en `needs_review`, invisible du retrieval. Faire tomber le
   501 sur ce second chemin donnerait une ingestion Drive « qui marche » et
   ne servirait rien : l'apparence du résultat sans le résultat.

Ce qu'il faut décider avant d'aller plus loin :

- **Qui porte la frontière Drive ?** Si c'est `rag-pedago`, alors le passage
  vers `rag-engine` doit se faire par contrat ou par API, pas par import —
  et ce contrat n'existe pas encore. S'il faut que ce soit `rag-engine`,
  alors `acquire_corpus` doit y être déplacé ou promu en paquet partagé
  (`packages/`), ce qui est une décision d'architecture, donc un ADR.
- **Le staging de tranche est-il celui du plan de contrôle
  (`drive_staging.*`, introduit ici) ou une file vers le plan de données ?**
  Tant que ce n'est pas tranché, rien de ce qui sort de cette tranche ne peut
  franchir la revue.

Aucune de ces deux décisions n'a été prise de ma propre initiative.
