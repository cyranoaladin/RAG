# H2-B — clôture corpus et go-live gouverné

## Statut et objectif

Cette spécification traduit l’autorisation explicite de Nexus Réussite du
8 août 2026. Elle est validée par cette autorisation et ne constitue ni un avis
juridique externe, ni une levée de gate technique. Le flux reste fail-closed :
une phase suivante ne démarre que lorsque toutes les preuves obligatoires de la
phase courante sont vertes.

L’objectif est de remplacer les affirmations H2-B synthétiques par une chaîne
reproductible fondée sur le corpus Drive scellé, puis d’exécuter successivement
l’audit H2 indépendant, le merge, P1, P2, P3 et P4. La production n’est jamais
une cible implicite : elle ne devient accessible qu’après H2, la CI de `main`,
la sauvegarde, le rollback et la répétition complète.

## Données réelles déjà réconciliées

La source canonique est
`gdrive_ert:NEXUS_RAG/NEXUS_RAG_GDRIVE_READY`, en lecture seule. Les premières
mesures réelles donnent :

- 2 584 objets distants ;
- 2 583 entrées dans `00_ADMIN/SHA256SUMS.txt` ;
- SHA-256 du manifest
  `d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e` ;
- 2 451 PDF Eduscol uniques et 2 956 placements ;
- 433 artefacts Eduscol multi-placement, avec 505 placements supplémentaires ;
- 2 476 PDF dans tout le corpus et 37 fichiers GeoGebra ;
- le manifest lui-même est le 2 584e objet physique et reçoit `EXCLUDE` avec
  `MANIFEST_SELF_OBJECT` sans modifier le sceau.

## Modèle canonique

Le catalogue distingue trois identités qui ne doivent plus être confondues :

1. L’objet physique est un chemin réel du corpus. Chacun des 2 584 objets reçoit
   exactement une disposition primaire.
2. L’identité de contenu est le SHA-256. Elle porte l’extraction, le scan PII,
   le chunking et l’embedding, exécutés une seule fois pour des octets identiques.
3. Le placement pédagogique porte scope, niveau, matière, type, année et statut.
   Un contenu Eduscol peut avoir N placements, tous conservés.

Cette distinction est obligatoire car le manifest contient un même SHA à deux
chemins physiques, l’un dans la provenance exclue et l’autre dans le corpus
pédagogique. La disposition reste donc attachée à l’objet physique ; la
déduplication de calcul reste attachée au SHA ; le filtrage de retrieval reste
attaché aux placements.

Le compilateur `corpus_catalog_compiler` devient l’entrée canonique et utilise
les types de `artifact_placement_model`. Le rapport de couverture et le golden
consomment le même catalogue réel. Le moteur RAG reçoit les placements sous
forme de métadonnées gouvernées, sans importer le code du plan de contrôle.

## Ordre fail-closed des gates

`INGEST` n’est possible que si droits, PII, currentness, format, provenance,
SHA, autorité et attribution passent tous. Un échec impose une disposition
bloquante à l’objet concerné. Les exclusions structurelles, formats non pris en
charge, archives, conflits, extractions impossibles et droits particuliers ne
sont jamais transformés en `INGEST` pour atteindre un quota.

Les droits Eduscol génériques sont enregistrés comme
`HUMAN_ORGANIZATIONAL_RIGHTS_APPROVAL` de Nexus Réussite sur le manifest
scellé. Une restriction propre à un document peut encore le placer en
`REVIEW_REQUIRED`. Les deux documents DEPP restent `REVIEW_REQUIRED`. Les
contenus Nexus sont liés à leur ensemble exact de 39 SHA par un digest de set,
sans signature fabriquée.

## Scan PII et exceptions documentaires

Les 2 476 PDF physiques sont couverts. Le téléchargement est séquentiel dans un
scratch borné sous `/tmp`, le SHA attendu est vérifié avant extraction, puis le
scratch du lot est nettoyé. Deux chemins partageant les mêmes octets réutilisent
la même preuve de scan. L’extraction est native avec `pypdf`; aucun OCR de masse
n’est autorisé. Une extraction impossible reste bloquante.

Avant le corpus réel, des canaris synthétiques prouvent que ni valeurs PII ni
contexte brut n’entrent dans la sortie ou les logs. La preuve externe ne contient
que SHA, statuts, classes de signaux, compteurs, versions et digests de politique.
Elle est scellée sous `$HOME/Documents/NEXUS_RAG_H2_EVIDENCE/`.

Le texte déjà extrait est aussi soumis, sur tout le périmètre Eduscol, à des
détecteurs conservateurs de restriction documentaire explicite. Un signal
particulier bloque le seul artefact concerné et n’ouvre aucun avis juridique
automatique.

## Autorité, mutations et retrieval

Les preuves LOT41A/LOT42 existantes sont exécutées avec PostgreSQL/pgvector
éphémère. Le test positif lie les octets réels au SHA déclaré ; les variantes
octets, SHA, manifest, revue, autorisation, échéance, révocation et scope doivent
échouer fermées.

La matrice de mutation est un harness temporaire réel. Pour chacun des douze
guards, il conserve les octets originaux, neutralise exactement le guard, exige
que le test ciblé passe de vert à rouge pour la raison attendue, restaure les
octets dans un `finally`, puis exige le retour au vert et le hash original.

Le retrieval éphémère utilise au moins un SHA Eduscol réel multi-placement. Un
seul jeu de chunks est inséré ; plusieurs placements autorisés y pointent. Les
tests couvrent collège, seconde, première, terminale et STMG, plusieurs matières,
l’isolation de niveau/matière, l’attribution, le SHA et la citation.

## Phases opérationnelles

Après CI locale et sécurité vertes, un reviewer réellement séparé reçoit le
SHA, les preuves externes et les commandes reproductibles, mais pas le verdict
du rapport d’implémentation comme source d’autorité. Tout constat bloquant est
remédié et réaudité. La PR devient ready uniquement à ce stade ; la review
GitHub de confiance et tous les checks du head exact restent obligatoires.

Le merge suit la méthode protégée du dépôt, sans force. `main` est ensuite
revérifiée. P1 découvre la topologie réelle et les secrets requis sans les
afficher. Avant toute écriture, l’état mutable est sauvegardé et la restauration
est testée. P2 rejoue build, migration éventuelle, ingestion, retrieval,
redémarrage et rollback hors trafic. P3 utilise le plus petit canary prévu par
les runbooks. P4 seul peut activer le wiring live LOT42 et ingérer tous les
objets `INGEST` — aucun autre statut.

L’absence d’accès à une infrastructure réellement identifiée, une sauvegarde
incomplète, une CI rouge, une fuite PII, un scope leak, une autorité invalide ou
un canary rouge arrête la progression au gate concerné ; l’autorisation générale
ne transforme jamais cet arrêt en succès.

## Preuves finales

Le rapport de lot en français contient les mesures réelles, le sceau PII,
l’audit indépendant, les SHA Git et image, la sauvegarde, le rollback, les
résultats P1–P4, le manifest d’ingestion non sensible et les invariants
post-go-live. Aucune donnée pédagogique brute, PII ou secret n’est incluse.
