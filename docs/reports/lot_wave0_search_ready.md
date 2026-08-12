# Lot Wave 0 — retrieval search-ready

## Résultat

Le lot part du HEAD
`386f2825882a4287e2ea831f966996b23ba5ca72` et transforme les deux pilotes
Wave 0 déjà gouvernés en un retrieval réellement interrogeable. La PR #95
reste Draft ; aucun verrou de production ni aucune approbation humaine n'est
modifié.

Le même E2E PostgreSQL/pgvector jetable exécute :

1. le vrai `verify_scope_authorization` avec `LocalGitHub` et LOT41A-V2 ;
2. Worker A jusqu'à `NEEDS_REVIEW` ;
3. LOT42-V2 puis Worker B ;
4. la publication avec le provider E5 vérifié ;
5. un vrai processus uvicorn et vingt appels HTTP à `/search/v2`.

Aucun appel manuel au publisher ni stub d'autorisation ne remplace ce chemin.
Le test HTTP est exécutable isolément : sur une base vide, sa fixture déroule
explicitement les deux publications gouvernées avant le démarrage de l'API.

## Chunking PDF

Le publisher conserve les octets PDF jusqu'à `extract_pdf_pages()` et ne passe
plus par un second extracteur aplati. Chaque chunk PDF appartient à une seule
page ; `page_start` et `page_end` sont persistés et toutes les pages textuelles
sont couvertes.

- Mathématiques : 11 pages, 19 chunks, couverture 100 %, tokens E5
  min/médiane/max = 18/350/384.
- Français : 8 pages, 17 chunks, couverture 100 %, tokens E5
  min/médiane/max = 17/353/378.
- chunks vides : 0 ; chunks au-delà de la limite modèle 512 : 0 ; pages nulles :
  0 ; chunks traversant plusieurs pages : 0.

Le Markdown structuré conserve ses chunks heading-aware historiques lorsqu'ils
tiennent dans la limite modèle. Seuls les chunks réellement trop longs sont
subdivisés ; le texte simple reste borné.

## Modèles réels et provenance

Les poids restent hors Git, matérialisés sans symlink, avec `manifest.json` et
`SHA256SUMS`. Les ancres externes vérifiées sont :

- `intfloat/multilingual-e5-large`, dimension 1024, révision
  `3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3`, inventaire
  `e2c7384ba36096b3f3bdfff4973f728596104aff0f1d38f1b6463e60765fe22a` ;
- `cross-encoder/ms-marco-MiniLM-L-6-v2`, révision
  `c5ee24cb16019beea0893ab7796b1df96625c6b8`, inventaire
  `bdcedc4d7cfe647b9aaa5a7546822dfee7826ebb3c64472bf89eae7592e08fe1`.

Le provider E5 n'est accepté que si son type exact provient du factory ayant
exécuté `verify_embedding_artifact`, `load_embedding_model` et
`validate_runtime_embedding_contract`. Un provider structurel ou une
sous-classe hostile ne peut pas revendiquer l'identité canonique. La base
d'acceptance contient 36 vecteurs 1024 dimensions, tous étiquetés avec le
modèle E5 canonique : zéro fake, zéro null et zéro mauvaise dimension.

Le reranker est vérifié et préchargé par le lifespan ; la recherche utilise le
singleton réel du modèle canonique. Le seuil historique `+1.90` reste inchangé.
L'acceptance matérielle est exécutée sur CPU (`CUDA_VISIBLE_DEVICES=''`) parce
que le GPU 4 Go partagé était saturé ; ni le modèle ni son contrat ne changent.

## Cible élève et preuve curriculaire

`nexus-contracts` passe en version `0.10.0`, avec ADR-0038 et schémas générés.
Le profil cible reste `seconde`, tandis que `RetrievalCurriculumScope` porte la
preuve `troisieme`, voie `college`, matière et `tronc_commun`.

Le registre signé contient, sans wildcard :

- `entree_seconde_maths_v1` →
  `rag_nexus_maths_troisieme_tc` ;
- `entree_seconde_francais_v1` →
  `rag_nexus_francais_troisieme_tc` ;
- l'artefact Terminale V1 historique inchangé.

Le runtime vérifie séparément la cible élève et les dimensions de preuve SQL.
Un scope inconnu, un digest divergent, une matière croisée, une cible Terminale
ou un curriculum Seconde sont refusés. Le rôle signé `teacher` lit la visibilité
`internal` ; le rôle `student` reste refusé.

L'overlay staging active uniquement les deux collections Wave 0. Le catalogue
canonique conserve leurs flags `instanciee: false`, et aucune autre collection
n'est activée par l'overlay.

## HTTP et pertinence

L'acceptance lance `api_v2:app` dans un vrai sous-processus uvicorn sur socket
localhost. Le lifespan vérifie BFF, registre d'identités, catalogue, alignement
des scopes, schéma PostgreSQL `004_artifact_placements`, artefacts modèles et
préchargement local-only.

La matrice HTTP couvre BFF absent/invalide, identité absente, signature invalide,
expiration, scope inconnu, digest divergent, curriculum/cible divergents,
matière croisée et rôle sans accès à `internal`. `/collections/v2` retourne
exactement la collection signée de chaque scope.

Le dataset d'acceptance contient dix questions naturelles par matière. Chaque
top hit doit être non vide, reviewed, lié au SHA et au chemin scellés, citer la
page attendue et contenir au moins un concept attendu. Résultat :

- Mathématiques : 10/10 ; zéro résultat nul, mauvais artefact ou citation
  manquante ;
- Français : 10/10 ; zéro résultat nul, mauvais artefact ou citation manquante ;
- fuites inter-collections : 0 ; fuites de scope : 0.

Le client `scripts/rag_query.py` signe une identité courte avec le mécanisme
HS256 canonique, dérive cible et curriculum depuis le scope versionné, ne prend
aucune collection physique en argument et n'imprime aucun secret.

## Vérifications exécutées

- E2E matériel complet : 5 tests passés ;
- E2E HTTP matériel ciblé et autonome : 1 test passé ;
- contrats : 202 tests passés ;
- cockpit : 178 tests passés, typecheck et génération de contrats verts ;
- rag-engine hors intégration : suite complète verte ;
- gouvernance PostgreSQL réelle : verte ;
- intégration hybride PostgreSQL/HTTP : `LOT40_HYBRID_INTEGRATION=PASS` ;
- Ruff et mypy rag-engine : verts ;
- vérification des deux artefacts modèles : verte, zéro symlink ;
- CI locale finale : 16 cibles passées, 0 échec.

La CI de branche et son HEAD exact sont consignés dans le rapport final de la
mission après le push. Le check de revue humaine peut rester rouge tant que la
PR #95 demeure Draft.
