# ADR-0038 — Séparation cible élève et preuve curriculaire dans le retrieval V2

- **Statut** : Proposé — **non Accepté**. L'acceptation reste soumise à la
  revue humaine du HEAD exact de la PR #95.
- **Date** : 2026-08-12
- **Périmètre** : contrat de retrieval, artefacts de scope signés et catalogue
  staging Wave 0.
- **S'appuie sur** : ADR-0002, ADR-0003, ADR-0022, ADR-0023.

## Contexte

Le diagnostic d'entrée en Seconde s'adresse à un élève de niveau `seconde`,
mais utilise comme preuve les attendus officiels de `troisieme`. Le contrat
historique dérivait les filtres de preuve du seul `StudentProfile`; forcer le
profil élève à `troisieme` aurait donc falsifié la cible pédagogique.

Le runtime ne chargeait en outre qu'un artefact de scope Terminale global. Il
ne pouvait pas sélectionner deux scopes Wave 0 étroits et révocables
indépendamment sans remplacer cette autorité historique.

## Décision

`nexus-contracts` passe de `0.9.0` à `0.10.0` et ajoute :

- `RetrievalCurriculumScope`, optionnel pour préserver le DTO V1 ;
- `RetrievalScopeArtifactV2`, qui sépare `target_identity` de
  `evidence_subject` ;
- un registre fermé contenant l'artefact Terminale V1 inchangé et les scopes
  `entree_seconde_maths_v1` et `entree_seconde_francais_v1`.

Lorsqu'un curriculum scope est présent, `niveau`, `voie`, `matiere` et
`statut_enseignement` viennent de cette portée. `candidat` et `audience`
restent des dimensions du profil cible. Le serveur V2 exige le curriculum
scope pour un artefact V2 et vérifie séparément :

1. le profil cible contre `target_identity` ;
2. la portée demandée contre `evidence_subject` ;
3. toutes les dimensions SQL contre la collection signée.

Le protocole HS256 et `InternalIdentityEnvelope.protocol_version="1"` restent
inchangés. Le `scope_id` signé sélectionne exactement un artefact ; aucune
wildcard ni valeur par défaut n'est autorisée. Un scope inconnu, un digest
divergent ou une collection différente produit un refus 403.

## Staging Wave 0

Le catalogue canonique conserve ses flags d'instanciation. Un overlay
`RAG_COLLECTIONS_STAGING_OVERLAY_V1` active uniquement les collections Maths
et Français de Troisième. Le runtime refuse tout overlay qui ajoute un champ,
vise une collection absente ou tente de modifier autre chose qu'un booléen
`false → true` explicitement nommé.

Les deux collections portent la voie canonique `college`, cohérente avec les
placements gouvernés et les prédicats PostgreSQL. L'acceptance HTTP utilise un
rôle `teacher`, car les placements Wave 0 ont la visibilité `internal`. Le
rôle `student` demeure limité à `public`.

## Conséquences

- Le scope Terminale V1 et son digest restent identiques.
- Les consommateurs doivent régénérer les schémas et types publiés.
- Un client V2 ne peut pas fournir de collection physique autoritative.
- Un nouveau scope exige un artefact nommé et un digest versionné ; modifier
  un artefact existant est interdit.
- L'activation globale des collections Wave 0 reste une décision de release
  ultérieure, distincte de cet overlay staging.
