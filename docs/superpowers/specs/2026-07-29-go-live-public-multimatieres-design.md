# Go-live public multi-matières — conception validée

> Statut : validé par le commanditaire le 29 juillet 2026.
>
> Portée : architecture cible et barrières de lancement. Ce document ne vaut
> pas autorisation de lever un verrou de gouvernance ; chaque transition reste
> soumise à `transition_authorization.yml` et à l'ADR requis.

## 1. Objectif

Mettre Nexus/ARIA en production sur `nexusreussite.academy` avec :

- une ouverture publique réservée aux comptes Nexus authentifiés ;
- les 59 collections annoncées, de la Troisième à la Terminale, voies
  générale et technologique, candidats libres et AEFE ;
- un corpus substantiel et validé dans chaque collection avant l'ouverture ;
- un retrieval hybride filtré côté serveur, avec sources et citations ;
- des réponses conversationnelles générées via OpenRouter ;
- une garantie initiale de trois conversations simultanées ;
- une exploitation sur le serveur Nexus actuel, derrière Nginx.

Le lancement est atomique : aucune ouverture partielle par matière n'est
présentée comme le go-live demandé. Une collection non conforme bloque
l'ouverture globale.

## 2. Principes non négociables

Les invariants d'`AGENTS.md` restent prioritaires :

1. Le cockpit ne communique qu'avec `rag-engine` au travers de contrats
   versionnés.
2. `packages/contracts` est la seule source de vérité des schémas partagés.
3. Aucun contenu ne rejoint l'index pgvector servi avant
   `quality → gate → review`.
4. Aucun verrou `*_allowed` n'est activé par effet de bord.
5. Aucun service n'importe directement le code d'un autre service.
6. Aucun secret, token, profil élève ou PII n'est versionné ou journalisé.
7. Aucun état « vert » n'est déclaré sur un échantillon quand la promesse
   couvre 59 collections.

Le but « sans dette technique » signifie pour J1 :

- aucune dette connue qui compromet la sécurité, la gouvernance, le contrat,
  la couverture, l'exploitabilité ou la reprise ;
- aucune vulnérabilité critique ou élevée connue dans les dépendances
  déployées ;
- aucun test requis ignoré, neutralisé ou remplacé par un mock ;
- tout risque résiduel non éliminable est documenté comme risque
  d'exploitation avec propriétaire, mitigation et critère d'acceptation, et
  non comme dette silencieuse.

## 3. État initial audité

La base Python et les garde-fous existants constituent un socle utile, mais
ne suffisent pas au go-live. Les blocages observés sont notamment :

- le cockpit ne compile pas depuis une archive Git propre, car
  `src/data/collections.json` et `src/data/sources.json` sont ignorés ;
- aucun job CI ne valide le cockpit, qui ne possède pas de suite de tests ;
- le lint cockpit échoue et l'audit de production remonte deux
  vulnérabilités élevées ;
- le cockpit Vite définit localement le contrat de retrieval, appelle une API
  legacy, n'a pas de BFF et retombe silencieusement sur des données de démo ;
- les routes v2 ne consomment pas le contrat canonique de retrieval ;
- l'ingestion v2 écrit des lignes `needs_review` dans pgvector avant la revue
  gouvernée ;
- une route de revue humaine peut promouvoir directement ces lignes ;
- les verrous de gouvernance ne protègent pas effectivement toutes les routes
  v2 montées ;
- Drive v2 n'est pas implémenté ;
- la documentation, les ADR et les interfaces présentent des états
  contradictoires ;
- seules les collections pilotes disposent aujourd'hui d'une substance
  indexée démontrée ;
- les fichiers Compose, les images, les permissions de secrets et le chemin
  de déploiement ne forment pas encore une unité de production reproductible.

Une CI verte dans l'état initial ne constitue donc pas une preuve de
production readiness.

## 4. Architecture cible

```text
Navigateur authentifié
        |
        v
Cockpit Next.js + BFF Auth.js
        |
        | contrat Nexus + jeton interne court
        v
rag-engine
   |           \
   |            \ requête générative minimisée
   v             v
pgvector       OpenRouter
contenu publié

rag-pedago
   |
   v
staging hors pgvector
   |
   v
quality → gate → panel unanime d'agents
   |
   v
paquet de publication signé
   |
   v
publisher rag-engine → pgvector
```

### 4.1 Plan de contrôle — `rag-pedago`

`rag-pedago` gouverne :

- les sources autorisées et leurs preuves ;
- la taxonomie et la matrice de couverture ;
- les contrôles de qualité sur l'intégralité du périmètre ;
- les décisions du panel d'agents experts ;
- les manifestes, empreintes et signatures de publication ;
- les rapports de conformité et les blocages.

Il ne possède aucun accès d'écriture direct à pgvector.

### 4.2 Plan de données — `rag-engine`

`rag-engine` est le seul service exposant :

- le retrieval canonique ;
- l'orchestration conversationnelle ;
- la publication contrôlée de paquets déjà approuvés ;
- la lecture du catalogue publiable ;
- les métriques techniques nécessaires à l'exploitation.

Il applique côté serveur tous les filtres de profil, tenant, matière, niveau,
voie, droits et statut de publication. Le navigateur ne peut jamais élargir
ces filtres.

### 4.3 Cockpit — Next.js

Le cockpit Vite transitoire est remplacé par une application Next.js :

- intégrée à l'identité Nexus ;
- sans accès direct à pgvector, aux documents bruts ou à OpenRouter ;
- sans secret ni token statique dans les bundles ;
- sans données de démonstration en mode production ;
- consommant un client TypeScript généré depuis le contrat canonique.

Le BFF authentifie la session, récupère le profil autoritatif et échange la
session Nexus contre un jeton interne de très courte durée destiné à
`rag-engine`.

## 5. Identité, session et autorisations

Le compte Nexus existant est l'identité unique. L'intégration cible est un
échange SSO serveur-à-serveur compatible Auth.js ; elle évite de partager un
secret de session durable entre applications.

Le jeton interne contient uniquement :

- un identifiant pseudonyme stable ;
- le rôle autorisé ;
- le tenant ;
- le niveau et le profil pédagogique validés ;
- une audience, une expiration courte et un identifiant anti-rejeu.

Les rôles minimaux sont `student`, `teacher`, `admin`, `ingest_agent` et
`review_agent`. Toute décision privilégiée est auditée. Les sessions sont
sécurisées par cookies `Secure`, `HttpOnly`, `SameSite`, protection CSRF,
rotation et révocation.

Les conversations sont isolées par utilisateur et tenant. Les identifiants,
emails et autres PII ne sont jamais transmis à OpenRouter.

## 6. Contrats

`packages/contracts` publie les modèles canoniques :

- `RetrievalRequest` et `RetrievalResponse` ;
- `ChatRequest` et `ChatResponse` ;
- citations, avertissements, refus, filtres appliqués et métadonnées
  d'audit non sensibles ;
- événements de publication signée.

Toute évolution :

1. reçoit une version SemVer ;
2. est justifiée par un ADR ;
3. génère un JSON Schema/OpenAPI déterministe ;
4. génère le client TypeScript du cockpit ;
5. possède des tests de compatibilité et des golden fixtures.

Les modèles Pydantic locaux concurrents et les interfaces TypeScript écrites
à la main sont supprimés après migration de leurs consommateurs.

## 7. Chaîne d'ingestion et de publication

### 7.1 Staging

Upload, URL et Drive déposent les documents dans un staging hors de l'index
servi. Chaque dépôt reçoit :

- un identifiant stable ;
- l'empreinte du binaire et du texte extrait ;
- la provenance et la date ;
- la source déclarée et la preuve de droits ;
- la collection cible ;
- la version des extracteurs, chunkers et modèles.

Les fetchs URL résolvent le DNS, bloquent toutes les adresses privées et de
métadonnées, revalident chaque redirection, limitent taille et type MIME et
appliquent les règles de source. Drive suit les mêmes garanties.

### 7.2 Quality, gate et review

Les contrôles portent sur tous les documents et chunks :

- intégrité, extraction, lisibilité et absence d'artefacts ;
- cohérence matière, niveau, voie, taxonomie et collection ;
- substance pédagogique ;
- droits et provenance ;
- déduplication ;
- absence de secrets et de PII ;
- résistance aux instructions injectées dans les sources.

Le panel `rights_expert`, `subject_expert`, `quality_expert` doit être unanime.
Tout doute, échec ou divergence mène à la quarantaine.

### 7.3 Publication

Le panel produit un paquet signé liant :

- le manifeste ;
- les empreintes des contenus ;
- la version des règles ;
- les trois verdicts ;
- la collection et les métadonnées ;
- la décision finale.

Le publisher de `rag-engine` vérifie ce paquet avant toute écriture. Il écrit
directement un statut publiable ; il n'existe plus de promotion manuelle
`needs_review → reviewed` dans l'index servi.

## 8. Preuve de couverture des 59 collections

Une matrice machine-readable relie :

`collection → taxonomie → notion → ressources substantielles → chunks publiés
→ golden queries → résultats d'évaluation`.

Pour chaque collection, le gate exige :

- 100 % des notions obligatoires reliées à au moins une ressource qui enseigne
  réellement la notion ;
- une source vérifiée et des droits démontrés pour chaque ressource ;
- un paquet de publication valide ;
- des chunks publiés et interrogeables ;
- des requêtes positives, négatives et de confusion inter-niveaux ;
- des citations exactes ;
- aucun résultat hors profil ou hors collection.

Une référence générique à une page Eduscol ne prouve pas la substance. Le
contrôle est exhaustif, jamais échantillonné.

## 9. Retrieval et génération

### 9.1 Retrieval

Le pipeline cible conserve l'embedding gouverné et le reranking, mais passe
par le contrat commun. Il retourne uniquement des chunks publiés et autorisés.
Le cache ne peut pas contourner un retrait, une quarantaine ou un changement
de droits.

### 9.2 Evidence gate

Avant génération, `rag-engine` vérifie :

- le nombre minimal de preuves ;
- la pertinence et la diversité des résultats ;
- la cohérence avec le profil élève ;
- les droits ;
- la présence de citations exploitables.

Si les preuves sont insuffisantes ou contradictoires, le système refuse de
produire une réponse factuelle et explique la limite.

### 9.3 OpenRouter

L'adaptateur OpenRouter est serveur uniquement. Il impose :

- une liste fermée de modèles ayant passé les évaluations ;
- une version de prompt et des paramètres traçables ;
- des timeouts, retries bornés et un circuit breaker ;
- aucun fallback vers un modèle non homologué ;
- la minimisation des extraits transmis ;
- l'absence de PII ;
- un budget et des quotas par utilisateur ;
- une limite stricte de concurrence.

La sortie structurée cite les identifiants de preuves. Un validateur
post-génération rejette les citations inexistantes et toute réponse qui ne
respecte pas le contrat. La conversation est bornée et résumée sans mélanger
les utilisateurs.

## 10. Sécurité applicative

Les barrières couvrent au minimum :

- authentification, expiration, révocation et anti-rejeu ;
- RBAC, isolation tenant et prévention IDOR ;
- CSRF, XSS, CSP, CORS fermé et en-têtes Nginx ;
- SSRF et redirections sur les ingestions distantes ;
- injection de prompt et exfiltration par les documents ;
- validation MIME, taille, archive et contenu ;
- rate limiting, quotas et limites de concurrence ;
- secrets, journaux, sauvegardes et dépendances ;
- refus fail-closed lors d'une erreur de gouvernance ou de contrat.

Les journaux sont structurés et pseudonymisés. Ils excluent le texte complet
des conversations par défaut.

## 11. Déploiement et exploitation

Un Compose de production unique remplace les chemins concurrents. Derrière
Nginx, il contient :

- le cockpit Next.js ;
- `rag-engine` ;
- PostgreSQL/pgvector ;
- Redis ;
- la supervision et la collecte de journaux nécessaires.

OpenRouter est la dépendance générative sortante. Les modèles locaux
d'embedding et de reranking sont chargés une seule fois par processus
dimensionné ; le nombre de workers n'est pas multiplié sans test mémoire.

Le déploiement impose :

- des images et dépendances figées ;
- des conteneurs non-root, `read_only` et sans privilèges ;
- aucun port de données exposé publiquement ;
- des secrets injectés avec permissions `0600` ;
- des healthchecks et readiness checks distincts ;
- des migrations transactionnelles et un rollback documenté ;
- des sauvegardes chiffrées hors serveur ;
- un exercice de restauration réussi ;
- des alertes sur erreurs, latence, saturation, quotas et disponibilité
  OpenRouter.

Le serveur unique reste un point de défaillance accepté par la contrainte
d'hébergement. Ce risque est compensé par une restauration éprouvée, des
sauvegardes hors hôte et une procédure de reprise. Il ne doit pas être
présenté comme de la haute disponibilité.

## 12. Performance et résilience

Le profil J1 garantit trois conversations simultanées. Le test de charge
reproduit :

- authentification et chargement du profil ;
- retrieval ;
- génération OpenRouter ;
- validation et streaming de la réponse ;
- journalisation et métriques.

Le service applique une file bornée et une contre-pression claire. Une panne
OpenRouter ne déclenche jamais une réponse inventée ou un mock ; elle produit
un état temporairement indisponible et conserve le retrieval cité si le
contrat utilisateur le permet.

## 13. Barrières de lancement

Le go-live reste interdit tant que tous les points suivants ne sont pas
prouvés :

1. build reproductible depuis un clone propre ;
2. lint, types et tests verts sur tous les services et le cockpit ;
3. tests de contrat Python/TypeScript ;
4. tests PostgreSQL/pgvector réels non ignorés en CI ;
5. E2E avec session Nexus réelle ou environnement d'identité fidèle ;
6. preuve exhaustive de couverture des 59 collections ;
7. golden queries et évaluations génératives sur les 59 collections ;
8. aucune citation inventée ni contenu hors profil dans le jeu de validation ;
9. zéro vulnérabilité critique ou élevée connue ;
10. tests d'autorisation, SSRF, injection, isolation et quotas ;
11. charge de trois conversations simultanées réussie ;
12. sauvegarde, restauration et rollback exécutés ;
13. supervision et procédures d'incident vérifiées ;
14. conformité légale, confidentialité et données de mineurs validées ;
15. transitions de gouvernance autorisées et ADR acceptés ;
16. checklist de production entièrement renseignée avec preuves.

Un déploiement sombre et un soak test précèdent l'ouverture. Les 59
collections sont ensuite activées publiquement dans une même décision de
release. Le rollback coupe la génération et l'interface publique sans
affaiblir les verrous ni altérer les preuves de publication.

## 14. Livrables attendus

- ADR acceptés pour le contrat conversationnel, le SSO, OpenRouter, la chaîne
  de publication et les transitions de verrous ;
- contrats versionnés et clients générés ;
- cockpit Next.js et BFF Auth.js ;
- API `rag-engine` convergée ;
- chaîne d'ingestion gouvernée et publisher signé ;
- corpus substantiel des 59 collections ;
- évaluations exhaustives et rapports de preuve ;
- Compose unique durci ;
- supervision, sauvegarde, restauration, rollback et runbooks ;
- rapport final de go-live sans dette release-blocking connue.

## 15. Hors périmètre J1

- haute disponibilité multi-nœuds ;
- ouverture anonyme ;
- fallback vers des modèles non évalués ;
- génération à partir de documents non publiés ;
- couverture déclarative ou partielle présentée comme complète ;
- activation implicite d'un verrou ;
- compatibilité indéfinie avec les routes legacy.

