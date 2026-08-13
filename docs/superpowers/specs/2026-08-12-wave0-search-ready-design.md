# Wave 0 — Search-Ready avec modèles et HTTP réels

## Statut et objectif

Conception approuvée par l'instruction Nexus Réussite du 12 août 2026.
Le vertical slice d'ingestion au HEAD
`386f2825882a4287e2ea831f966996b23ba5ca72` reste l'autorité de départ.
Cette passe transforme les deux PDF Wave 0 déjà gouvernés en corpus réellement
interrogeable, sans reconstruire currentness, PII, droits, placement ni Phase B.

Le succès exige des chunks PDF page-aware, des vecteurs E5 et un reranker réels,
un scope signé qui distingue la cible élève Seconde de la preuve curriculaire 3e,
et vingt recherches HTTP réelles pertinentes et isolées.

## Chunking gouverné

Le publisher conserve les octets source jusqu'au chunking. Quand les octets sont
un PDF, il réutilise `extract_pdf_pages(raw_bytes)` et produit des
`PublicationChunk(text, page_start, page_end)` ordonnés. Une page textuelle est
la frontière normale : elle produit un ou plusieurs chunks, tous liés au même
numéro de page. Une page vide ne produit rien ; toute page non vide doit être
couverte.

Le provider d'embedding fournit le tokenizer et sa limite effective. Le splitter
assemble paragraphes puis phrases sous un budget de passage d'environ 300–450
tokens, compté après `format_passage`. Une unité trop longue est coupée par
tokens, puis décodée sans chunk vide. Une vérification finale interdit tout
passage dépassant la limite effective du modèle. Le Markdown structuré conserve
le chemin heading-aware existant ; le texte simple utilise le même splitter
borné sans métadonnée de page.

Le publisher persiste `page_start` et `page_end` dans `rag_chunks`. La citation
HTTP utilise `page_start`. Les chunks de PDF n'ont jamais de page nulle.

## Provenance des embeddings

Le callable nu n'est plus l'autorité. Un `EmbeddingProvider` expose au minimum
`model_id`, `dimension`, l'identité d'artefact vérifiée, l'inventaire, la limite
de séquence, le comptage de tokens et l'encodage normalisé. Le provider canonique
ne peut être construit qu'à partir de `verify_embedding_artifact`,
`load_embedding_model` et `validate_runtime_embedding_contract`. Le publisher
écrit `provider.model_id`, vérifie cardinalité, dimension, valeurs finies et
norme non nulle.

Le provider déterministe reste réservé aux tests avec
`model_id=debug/deterministic-1024`. Il ne peut pas revendiquer le modèle E5.
L'acceptance utilise une base PostgreSQL/pgvector neuve ; aucune ligne issue du
provider déterministe n'y existe.

Les artefacts E5 et reranker sont matérialisés hors Git, sans symlink, avec
`manifest.json` et `SHA256SUMS` déterministe. Les digests d'inventaire externes
ancrent les verifiers existants. Aucun téléchargement n'est permis sur le chemin
de requête.

## Contrat de retrieval et portée signée

`RetrievalRequest` reçoit un `curriculum_scope` explicite. Le profil élève décrit
la cible (`seconde`) ; le scope curriculum décrit la preuve (`troisieme`,
`college`, matière, `tronc_commun`). `to_payload_filters` prend les dimensions
pédagogiques du scope curriculum quand il existe.

Le scope historique V1 Terminale reste lisible sans changement. Un scope signé
V2 contient deux blocs : `target_identity` et `evidence_subject`. Les deux
artefacts Wave 0 sont étroits et indépendamment révocables :

- `entree_seconde_maths_v1` autorise uniquement
  `rag_nexus_maths_troisieme_tc` ;
- `entree_seconde_francais_v1` autorise uniquement
  `rag_nexus_francais_troisieme_tc`.

Un registre versionné sélectionne exactement l'artefact nommé par `scope_id`
après vérification HS256. Il refuse l'identifiant inconnu, le digest divergent,
la collection hors allowlist, la cible divergente et le curriculum divergent.
Le client ne choisit jamais une collection physique : le serveur la résout par
intersection entre curriculum demandé et `evidence_subject` signé.

Les validations serveur sont séparées : cible élève contre `target_identity`,
puis curriculum contre `evidence_subject` et `ServerRetrievalScope`. Les
dimensions SQL — tenant, niveau, voie, matière, statut, candidat, audiences,
année, programme, droits, visibilité et review — viennent de l'artefact de
preuve signé. Le rôle `teacher` est utilisé pour lire les placements `internal`;
le rôle `student` reste refusé.

## Activation staging et API réelle

Un catalogue staging dérivé du canonique active exactement les deux collections
Wave 0. Le canonique conserve `instanciee: false`. L'API est lancée par uvicorn
sur localhost avec les DSN canoniques, les deux artefacts modèles vérifiés, le
catalogue staging, le BFF token et l'identité signée. Le lifespan effectue les
readiness réelles ; aucune sonde n'est monkeypatchée.

La matrice HTTP couvre les erreurs 401/403, l'isolation de `/collections/v2`,
puis dix requêtes sémantiques par matière. Chaque cas valide le concept attendu,
l'artefact, la collection, le statut reviewed, la page et le chemin source.
Zéro résultat ou résultat de l'autre matière est un échec.

## E2E et limites

L'E2E principal repart d'une base propre et utilise le vrai
`verify_scope_authorization`, `LocalGitHub`, LOT41A-V2, LOT42-V2, Worker A et
Worker B. Aucune insertion produit ou publication manuelle ne remplace ce
chemin. Les deux PDF sont réingérés avec le provider E5 réel.

Le client `scripts/rag_query.py` utilise les mêmes scopes, ne lit ses secrets
que depuis l'environnement, valide `RetrievalResponse` et n'imprime jamais de
token. Le full Wave 0, les modèles alternatifs, PR #96 et l'intégration d'un
autre dépôt restent hors périmètre.
