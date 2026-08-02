# ADR-0024 — Runtime v2 lecture et revue fail-closed

- Statut : Accepté
- Date : 2026-08-02
- Périmètre : image et stack d'exécution `rag-engine` v2
- S'appuie sur : ADR-0001, ADR-0010, ADR-0011, ADR-0013, ADR-0022 et
  ADR-0023

## Contexte

Le runtime v2 charge actuellement le monolithe historique `api:app`. Le même
processus expose donc retrieval PostgreSQL, review, ingestion directe
PostgreSQL, ingestion ChromaDB et administration legacy. Les routes v2
d'ingestion acceptent des métadonnées contrôlées par l'appelant, omettent le
scope complet utilisé par le retrieval et écrivent avant toute preuve
autoritaire de la chaîne `quality → gate → review`.

Le dépôt ne possède pas encore l'autorité externe LOT41A ni les attestations de
publication LOT42. Ajouter des champs à la requête ou au token de rôle ne peut
pas remplacer ces preuves.

## Décision

Le runtime Nexus v2 devient un runtime de **lecture et revue** uniquement. Son
application dédiée monte les routes de retrieval et de review authentifiées,
ainsi que des sondes minimales. Elle ne monte aucune route d'ingestion,
d'administration ou de stockage legacy.

L'image v2 est construite par allowlist de modules. Elle ne contient ni le
monolithe ChromaDB, ni client de source distante, ni parseur de document, ni
Celery. Le Compose v2 ne démarre aucun worker : **aucun writer** de contenu
n'est autorisé dans ce plan de données.

Le reverse proxy applique la même frontière par allowlist. `/ingest` et tous
ses descendants sont fermés avant proxy ; une route inconnue n'est jamais
transmise au moteur.

Une base PostgreSQL neuve applique successivement le bootstrap 001/002 et la
migration canonique `003_profile_filtering`. La readiness vérifie le schéma 003
et bloque le moteur si un volume existant n'a pas été migré par le runner
transactionnel sauvegardé.

Une future publication v2 devra recevoir du plan de contrôle une remise liée au
digest du contenu, au tenant, à la collection, aux dimensions de profil et à
des attestations indépendantes `quality → gate → review`. Son authenticité, son
autorité et sa révocation relèvent de LOT41A et LOT42. Aucune variable
d'environnement ne peut réactiver l'ancien writer.

## Conséquences

- Les défauts d'upload non borné et de SSRF disparaissent de la surface v2 : le
  runtime n'accepte plus de fichier ni d'URL.
- Une ligne incomplète ne peut plus être créée par le stack v2.
- Le retrieval et la review conservent leurs scopes signés et leurs rôles SQL à
  privilèges minimaux.
- Le code et les stacks `legacy` restent identifiés comme historique isolé ;
  ils ne constituent ni le runtime Nexus v2 ni une alternative de go-live.
- Le verdict global reste `GO_LIVE: NO_GO` jusqu'aux autorités LOT41A/LOT42, à
  la revue substantielle du corpus et aux preuves opérationnelles externes.

## Alternatives rejetées

Enrichir le payload avec les cinq champs de profil est rejeté : l'appelant
resterait sa propre autorité et le write contournerait toujours la gouvernance.
Durcir uniquement les redirections URL est rejeté pour la même raison. Monter
les routes legacy derrière un autre token dans la même image est rejeté : deux
autorités de stockage resteraient déployables dans le même plan de données.

## Retour arrière

Le retour arrière sûr est l'arrêt du runtime v2. Remettre `api:app`, le worker
ou un proxy d'ingestion rouvrirait la frontière non gouvernée et n'est pas une
option de production. La décision ne supprime ni ne transforme de données ; le
rollback SQL 003 existant reste réservé à une procédure opérateur sauvegardée
et à une base sans données enrichies.
