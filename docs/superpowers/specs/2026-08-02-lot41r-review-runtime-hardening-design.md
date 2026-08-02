# LOT41R — Durcissement runtime et chemin de review authentifié

Date : 2026-08-02

## Contexte et objectif

Les revues automatisées postérieures aux fusions des LOT40 et LOT41 ont mis en
évidence trois défauts P1 : l'image ingestor v2 ne peut pas charger le retrieval
LOT40 depuis son layout Python aplati, aucune route BFF ne permet à un reviewer
authentifié d'atteindre les opérations de review désormais protégées, et une
première connexion Redis rejetée empoisonne le store de session jusqu'au
redémarrage du Cockpit.

LOT41R corrige ces trois frontières sans activer le pilote, sans modifier le
schéma PostgreSQL, sans autoriser de publication automatique et sans lever de
verrou de gouvernance. Le projet reste `GO_LIVE: NO_GO` après ce lot.

## Décision

Le lot retient un correctif de compatibilité ciblé plutôt qu'une restructuration
globale de l'image Docker. `retrieval_pg_v2.py` et
`retrieval_scope_v2.py`, tous deux traversés par l'import réel de `api`,
acceptent à la fois le mode package `ingestor.*` utilisé par les tests et le
mode top-level utilisé par `uvicorn api:app`. Un test de runtime importe
l'application depuis un `sys.path` limité au répertoire copié par le
Dockerfile ; il constitue la preuve de la topologie réellement déployée.

Le Cockpit expose deux routes same-origin explicites :

- `GET /api/review/queue` ;
- `POST /api/review/decide`.

Elles exigent une session NextAuth valide, non révoquée, portant le rôle
`reviewer` ou `admin`. Le navigateur ne reçoit jamais le credential machine et
ne fournit jamais l'enveloppe d'identité. Le BFF extrait l'identité de la session
chiffrée, transmet séparément `Authorization: Bearer <service>` et
`X-Nexus-Identity: <enveloppe signée>`, puis le moteur réapplique ses propres
contrôles de rôle, de tenant, de collection et de transition. Une collection
fournie par le client ne peut que restreindre les collections signées.

Le protocole de review devient un contrat partagé additif
`nexus-contracts==0.5.0`. Conformément à l'ADR-0002, l'ajout rétrocompatible de
nouveaux modèles est une évolution mineure, et non un patch. L'ADR du lot amende
explicitement le périmètre historique du package pour inclure cette frontière
de gouvernance. Les modèles `ReviewQueuePayload` et `ReviewDecisionPayload`
décrivent le navigateur → BFF sans tenant ; `ReviewDecisionRequest` décrit le
BFF → moteur avec le tenant signé ; `ReviewQueueResponse` et
`ReviewDecisionResponse` décrivent les sorties. Ils sont définis une seule fois
dans `packages/contracts`, exportés en JSON Schema puis générés dans le
Cockpit. Le moteur remplace son modèle local de décision par le modèle partagé.
Aucune structure de review n'est redéfinie dans un service.

Enfin, le store de sécurité de session conserve une seule tentative Redis
concurrente, mais retire du cache uniquement la promesse qui vient d'échouer.
Les appels ayant partagé cette tentative échouent tous fermés. Le premier appel
ultérieur crée une nouvelle connexion. La fin tardive d'une ancienne tentative
ne peut pas effacer une promesse plus récente. Aucune mémoire locale ni
tolérance permissive n'est introduite.

## Contrats et flux

### Queue

Le navigateur peut fournir `collection`, `limit` et `offset`. Le BFF valide les
bornes contractuelles, refuse les clés de requête inconnues ou dupliquées et
interdit une collection hors du scope signé avant tout appel moteur. Le tenant
est dérivé de l'identité et n'est pas accepté comme autorité navigateur.

Le moteur retourne uniquement les métadonnées déjà prévues par la queue LOT41 :
identifiants document et collection, provenance, droits, type, compte de chunks
et dates d'indexation. Aucun texte brut ni PII élève n'est exposé.

### Décision

Le navigateur peut demander `reviewed` ou `quarantined` pour un document ou un
chunk et une collection optionnelle. Le champ libre historique `reason` est
retiré : le moteur l'acceptait sans le persister ni l'auditer, et le transporter
aurait créé une fausse preuve ainsi qu'un canal potentiel de PII. Le BFF valide
le payload partagé, vérifie le rôle et la collection, puis construit la requête
moteur en ajoutant le tenant signé. Le moteur reste l'autorité finale et garde
les transitions asymétriques existantes :

- `needs_review → reviewed` ;
- `needs_review|reviewed → quarantined` ;
- aucune réactivation ni retour à `needs_review`.

## Gestion des erreurs

- Session absente, invalide, expirée ou révoquée : `401` avant appel moteur.
- Rôle autre que `reviewer|admin` ou collection hors scope : `403` avant appel
  moteur.
- Requête mal formée ou paramètres hors bornes : `400` avant appel moteur.
- Cible invisible, hors scope ou transition impossible : réponse générique
  `404` produite par le moteur, sans révéler l'identifiant.
- Réponse moteur non conforme au contrat ou indisponibilité : `503` générique,
  sans fuite du credential, du token signé ni des détails internes.
- Redis indisponible : l'appel courant reste refusé ; une nouvelle tentative
  n'est permise que lors d'un appel ultérieur.

## Tests et preuves

Le développement suit des cycles TDD séparés :

1. test rouge d'import de `api` avec le seul layout aplati, puis compatibilité
   d'import minimale ;
2. tests rouges des modèles de review et génération déterministe, puis contrat
   0.5.0 et ADR amendant le périmètre de l'ADR-0002 ;
3. tests rouges des routes queue/décision pour authentification, rôle, scope,
   validation, headers et réponses invalides, puis implémentation BFF ;
4. tests rouges Redis prouvant qu'une tentative concurrente unique échoue
   fermée pour tous ses appelants, que l'appel suivant réussit, et que la fin
   tardive d'une ancienne tentative ne peut pas effacer une promesse récente ;
   puis éviction conditionnelle de la promesse rejetée.

Les vérifications finales couvrent les suites ciblées, l'ensemble des tests des
trois composants concernés, Ruff, mypy, ESLint, TypeScript, build Next.js, la
génération contractuelle, les contrôles de gouvernance et la CI locale racine.
Le rapport `docs/reports/lot_41r_review_runtime_hardening.md` consigne les SHA et
les résultats frais avant passage de la PR vers `main`.

## Alternatives écartées

La conservation des tokens humains directs sur le moteur est écartée : elle
réintroduirait un bypass du BFF et contredirait l'ADR-0022. Un proxy opaque sans
contrat partagé est écarté : il créerait une seconde définition implicite du
protocole. La restructuration immédiate de l'image en package `ingestor` est
écartée pour ce correctif car elle modifierait simultanément les entrypoints
Uvicorn et Celery ainsi que plusieurs manifests Compose, avec un rayon d'impact
sans rapport avec les trois P1.

## Retour arrière

Le rollback retire ensemble les routes BFF, les schémas review 0.5.0 et leur
consommation moteur, puis restaure les imports et le cache Redis antérieurs. Il
ne touche ni aux données, ni aux migrations, ni aux verrous. Tant que le chemin
BFF n'est pas disponible, les opérations de review restent fermées ; aucun
fallback direct ou permissif n'est autorisé.
