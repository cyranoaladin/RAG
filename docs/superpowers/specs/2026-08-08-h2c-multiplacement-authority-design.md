# H2-C — Plan de données multi-placement et autorités LOT41A/LOT42

Date : 2026-08-08  
Branche d'implémentation : `track-a/lot-h2b-corpus-production-readiness`  
État : conception autorisée par l'instruction Nexus Réussite H2-C

## Objectif et limites

H2-C doit rendre possible la publication gouvernée d'un contenu extrait et
vectorisé une seule fois, associé à plusieurs placements pédagogiques. Le lot
reste strictement préproduction : toutes les migrations, publications et
recherches sont exécutées sur PostgreSQL/pgvector jetable. Aucun endpoint
d'écriture public n'est ajouté et aucun système de production n'est ciblé.

## Décisions structurantes

### Modèle normalisé additif

La migration produit `004_artifact_placements.sql` ajoute :

- `public.rag_artifacts`, dont `artifact_id` est l'identité stable liée au
  contenu et `content_sha256` est unique ;
- `public.rag_artifact_placements`, qui porte chaque scope de retrieval
  autorisé et sa provenance ;
- `public.rag_chunks.artifact_id`, nullable pour préserver toutes les lignes
  historiques.

Pour le corpus H2 gouverné, `artifact_id` est la valeur SHA-256 canonique du
contenu. La base impose sa forme hexadécimale et son égalité à
`content_sha256`. Les chunks gouvernés utilisent le même `doc_id` et un index
unique partiel `(artifact_id, chunk_index)`. Une modification de chemin ou de
placement ne change donc jamais l'identité ; une modification des octets la
change toujours.

Les colonnes scalarisées historiques de `rag_chunks` sont conservées. Elles
restent autoritatives uniquement lorsque `artifact_id IS NULL`. Pour un chunk
gouverné, elles ne sont qu'une projection de compatibilité déterministe du
premier placement trié ; le retrieval ne leur accorde aucune autorité.

### Placements et scopes transversaux

Une ligne de placement représente un scope de retrieval exact, complet et
résolu. Un placement source transversal peut produire plusieurs placements
de publication exacts, mais seulement lorsqu'une règle déterministe appuyée
par les métadonnées source le prouve. La relation conserve séparément
`source_placement_id`, `source_scope`, le chemin et le statut source afin de
ne jamais faire passer une projection résolue pour la donnée originale.

Tout placement `non-classe` ou sans collection/taxonomie sûre reste
`REVIEW_REQUIRED` et n'est pas inséré dans la table produit. Il n'existe aucun
niveau par défaut et aucun routage de secours.

### Publication gouvernée

Le publisher est une fonction Python interne, jamais un routeur HTTP. Son
entrée exige :

- les octets du contenu et leur SHA-256 canonique ;
- les métadonnées d'artefact ;
- au moins un placement exact ;
- pour chaque placement, une `VerifiedAttestation` LOT42 active couvrant
  exactement le scope, le contenu, le profil et le manifest concernés.

Le publisher vérifie de nouveau toutes les liaisons avant écriture. Une seule
transaction insère ou vérifie l'artefact, insère les placements, extrait et
segmente le contenu une fois, calcule les embeddings une fois, puis insère les
chunks une fois. Un retry compare les lignes existantes et ne ré-extrait ni ne
ré-encode. L'ajout d'un placement valide ne touche pas aux chunks. Toute
divergence d'une ligne déjà présente ou toute erreur annule la transaction.

Le rôle PostgreSQL publisher reçoit seulement `SELECT` et `INSERT` sur les
trois tables produit. Il ne reçoit ni `UPDATE`, ni `DELETE`, ni droit sur les
tables étrangères au publisher. Le rôle retrieval reçoit `SELECT` sur les
trois tables ; le rôle review conserve uniquement son droit historique de
mettre à jour `rag_chunks.review_status` et ne peut écrire ni artefact ni
placement.

### Retrieval 1:N sans doublon

Le prédicat SQL devient une disjonction stricte :

- `artifact_id IS NULL` : prédicat scalarisé historique inchangé ;
- `artifact_id IS NOT NULL` : `EXISTS` sur un placement produit actif,
  courant et exactement égal au scope serveur signé.

Le sous-select `EXISTS` empêche une multiplication de lignes lorsqu'au moins
deux placements correspondent. Les canaux dense et lexical, RRF, rerank et MMR
continuent à dédupliquer et classer par `chunk_id`. Les résultats gouvernés
transportent dans `RetrievalResult.metadata` l'`artifact_id`, le
`content_sha256` et les identifiants/provenances des placements correspondants.
Le contrat public n'est pas modifié : `metadata` est déjà la surface canonique
extensible.

### Migration et rollback

La migration 004 est additive : aucune ligne existante n'est réécrite et
aucun vecteur n'est recalculé. Le rollback refuse de supprimer le modèle si un
chunk gouverné, un artefact ou un placement existe encore ; sur une base de
rehearsal revenue à l'état historique, il supprime uniquement les ajouts 004.
Les tests exécutent 003 -> 004 -> rollback 004 -> 004 et comparent la forme
exacte du schéma et les lignes legacy à chaque étape.

### Portée de l'autorisation LOT41A réelle

`ScopeAuthorizationArtifact` ne couvre qu'un `ResourceScope` exact. Il serait
mensonger de l'utiliser comme autorisation globale des 63 candidats PII-clear.
La première autorisation réelle est donc limitée à
`rag_nexus_philo_terminale_tc`, scope `terminale/philosophie/tronc_commun`,
justifié par cinq artefacts actuels PII-clear dont les métadonnées réelles
portent toutes `lycee/terminal/philosophie`.

Le SHA PII-quarantiné
`b81201b857c67e4e928a079cfe9d5b9b402537d0101bfccc730465631d5e8376`
appartient aux scopes français/HLP et n'est pas dans cette autorisation. Une
exclusion par URL serait trop large : la même URL Eduscol porte de nombreux
autres artefacts. La séparation par scope est la représentation exacte et
fail-closed.

Le profil philosophie réel et son manifest borné sont versionnés sur la
branche H2 avant de générer l'artefact LOT41A canonique. Le manifest attribue
la décision organisationnelle à Nexus Réussite, conformément à l'instruction
humaine explicite, sans fabriquer de signature. La PR LOT41A dédiée reste
ouverte pendant la durée du grant. Seule une review `APPROVED` de
`abenrhouma`, sur son head exact, permet l'enregistrement de l'autorisation.

### LOT42

Le mécanisme existant `verify_publication_attestation` reste l'unique ancre de
la transition `REVIEWED -> RETRIEVAL_ELIGIBLE`. H2-C câble la suite
`ROUTED -> STAGED -> NEEDS_REVIEW -> REVIEWED`, puis appelle exclusivement
`attempt_retrieval_eligible_transition`. La génération et l'enregistrement
des artefacts LOT42 continuent à provenir de vrais `workflow_events` durables.

Une rehearsal peut utiliser une base et des PR de staging. Elle est enregistrée
comme rehearsal, jamais comme attestation de publication production. Les
attestations production seront générées à P4 depuis les événements production
réels et nécessiteront leur revue humaine distincte.

## Preuves réelles et fermeture fail-closed

Le contrôle multi-placement utilise le SHA réel
`371d0c82ed1f47614ee9cbfdaa86cfb4add1f239a84882d9731fbd125105925d`,
reconfirmé à sept placements source. Les placements source sans collection
production sûre restent en review. La rehearsal peut résoudre des placements
de staging explicites pour démontrer l'unicité artefact/chunks et l'isolation
de scope ; elle ne les transforme pas en placements production éligibles.

Le compilateur final compte séparément les blocages PII, autorité, placement
et collection. Un artefact n'est `INGEST` que s'il conserve au moins un
placement retrieval exact, une collection instanciée, une autorisation réelle
et toutes les autres preuves H2. Les invariants de sécurité restent à zéro
pour tout `INGEST`.

## Alternatives rejetées

- Dupliquer les chunks et vecteurs par collection : viole directement
  l'identité par contenu et crée des résultats dupliqués.
- Porter une liste de placements JSON/array dans chaque chunk : répète les
  métadonnées, complique l'intégrité référentielle et rend l'évolution d'un
  placement proportionnelle au nombre de chunks.
- Autoriser globalement les 63 candidats dans un seul LOT41A : le contrat ne
  porte qu'un scope exact et le ferait mentir sur la portée et la PII.
- Déduire un niveau depuis le seul titre ou la seule matière : non déterministe
  et contraire au fail-closed.

