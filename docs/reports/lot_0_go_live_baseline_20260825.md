# Lot 0 — Baseline et matrice de fermeture go-live

## Référence et méthode

- Date : 2026-08-25.
- Repository : `cyranoaladin/RAG`.
- SHA : `3566cafb44138d6a7f00296dc0654257f9bf0ad6`.
- Tree : `8c5081a52096d531f1bd027790e600eb83b05bd5`.
- `main` : propre, identique à `origin/main` après avance rapide.
- CI dépôt de référence : run GitHub Actions `32823019934`, conclusion
  `success` ; aucun E2E production n'est exécuté par ce run.
- Audit : code et historique locaux, GitHub en lecture seule, infrastructure et
  endpoints publics en lecture seule. Aucune mutation de production.

Les preuves de mécanisme, fixtures, mocks et déclarations documentaires ne sont
pas élevées au rang de preuve de production. Les seuls statuts utilisés sont
`ABSENT`, `PARTIAL`, `IMPLEMENTED_UNVERIFIED`, `VERIFIED_LOCAL`,
`VERIFIED_STAGING`, `VERIFIED_PRODUCTION` et `BLOCKED`.

## Matrice de fermeture

| Capacité | Code | Unitaires | Intégration | E2E | Données réelles | Déployé | Observabilité | Sécurité | Sauvegarde | Rollback | Statut vérifié | Écart restant | Lot |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Gouvernance Git, protection `main`, CI | Oui | Oui | Oui | Contrôles GitHub live, pas d'E2E production | Oui | GitHub | Oui | Protection stricte | n/a | Revert PR | `VERIFIED_PRODUCTION` | Maintenir la revue exacte-head pour chaque lot | 0–9 |
| Environment GitHub `production` | Oui | Oui | n/a | Lecture API | Oui | Oui | GitHub | Reviewer requis, main-only, no bypass | n/a | Config réversible | `VERIFIED_PRODUCTION` | Aucun déploiement enregistré, aucun secret/variable | 8–9 |
| Configuration et secrets du runtime canonique | Noms documentés | Partiels | Non | Non | GitHub repo/environment : 0 secret, 0 variable | Variables legacy seulement | Non | Secrets hors Git requis | n/a | Reprovision | `BLOCKED` | Provisionner hors Git les dépendances canoniques requises ; `secrets=0` de l'Environment est conforme | 8–9 |
| Moteur A legacy Chroma/Ollama/Streamlit | Oui | Partiels | Partiels | Non actuel | 23 904 vecteurs | Oui | Partielle | Legacy, mutations hors gouvernance B | Archives quotidiennes | Restore non prouvé | `VERIFIED_PRODUCTION` | Inventaire/parité/migration/restore avant retrait | 2, 8 |
| Moteur B pgvector/retrieval | Oui | Oui | PostgreSQL/Docker | Rehearsal mécanisme | DB réelle vide | Version canonique au SHA de référence non déployée ; ancien runtime `27a4558…` public | Prometheus partiel | Read/review-only fail-closed | Backup/restore pgvector | Rehearsal DB | `IMPLEMENTED_UNVERIFIED` | Déployer SHA canonique, migrer et charger corpus gouverné | 2, 7–9 |
| Contrat `RetrievalRequest → RetrievalResponse` | Oui, package 0.14.0 | Oui | Oui | Non externe | Non | Consommé localement | Partielle | Validation stricte | n/a | Version Git | `VERIFIED_LOCAL` | Version exposée, request ID et erreurs publiques stables | 3 |
| `/search/v2` context-only avec citations | Oui | Oui | PostgreSQL avec doubles ML | Pas de black-box cible | Non | Runtime live ancien | Métriques code | Identité BFF interne | n/a | Release atomique prévu | `IMPLEMENTED_UNVERIFIED` | API agents tierce, corpus réel et preuve externe | 3 |
| `/collections/v2` | Oui | Oui | Oui | Endpoint live 401 sans auth | Runtime ancien répond | Ancien runtime | Partielle | Scope signé | n/a | Release | `IMPLEMENTED_UNVERIFIED` | Déployer version canonique et tester les scopes | 3, 6 |
| `/collections/readiness` | Oui | Oui | Oui | Endpoint live 404 | Non | Non | Code présent | Fail-closed | n/a | Release | `IMPLEMENTED_UNVERIFIED` | Déployer et lier au corpus final | 3, 7 |
| Lifecycle clés API externes | Table seulement | Non canonique | Non | Non | `rag_api_keys=0` | Non | Non | Incomplet | n/a | Non | `ABSENT` | One-time raw, hash, scopes, expiration, révocation, rotation, audit | 3 |
| Rate limit, quotas, concurrence | Nginx par IP dans templates | Tests partiels | Non | Aucun 429/charge | Non | Absent des vhosts actifs | Non | Incomplet | n/a | Config | `PARTIAL` | Per-key quotas, saturation, limites et charge observée | 3 |
| Reverse proxy/TLS API | Templates canoniques | Tests scripts | Non | TLS et health live | Oui | Legacy actif | `/metrics` public | Pas de rate limit actif | Config | Nginx rollback | `PARTIAL` | Déployer templates : CSP, CORS restrictif, fermeture de `/metrics` et rate limiting | 3, 8 |
| Cockpit Next.js, frontière BFF → engine | Oui | Oui | BFF mocké | Aucun navigateur réel | Non | Non | Partielle | Aucun accès DB direct | n/a | Build immuable absent | `VERIFIED_LOCAL` | Généraliser les scopes et prouver E2E | 6 |
| Recherche Cockpit | Oui | Oui | API mockée | Non | Non | Streamlit servi à la place | Non | Session same-origin | n/a | Non | `PARTIAL` | Auth réelle, request ID, accessibilité, visuel, E2E | 6 |
| Administration Cockpit | Composants statiques/demo | Partiels | Non | Non | Non | Non | Non | Non prouvée | n/a | Non | `ABSENT` | Connecteurs, queues, quarantaines, revue et clés | 6 |
| Déploiement Cockpit Next.js | Aucun compose/image/proxy courant | Build CI | Non | Non | Non | Non | Non | CSP actuelle insuffisante | n/a | Non | `ABSENT` | Image immuable, BFF, health, proxy et rollback | 6 |
| Ingestion Web discovery/fetch | Oui, staging | Oui | Partielle | Non gouverné complet | Sources Eduscol partielles | Timer absent | Rapports seulement | Robots/rate limit présents | Snapshots incomplets | Reprise partielle | `PARTIAL` | Raccorder au ledger B et au gate sans écriture directe | 4 |
| Pipeline Web canonique `quality → gate → review` | Primitives B présentes | Oui | PostgreSQL | Non source→retrieval | Non | Workers non déployés | Partielle | Fail-closed | Ledger | Retry/DLQ partiels | `IMPLEMENTED_UNVERIFIED` | Snapshot, versions, tombstones, idempotence et E2E réel | 4 |
| Connecteur Google Drive B | Route `501` | Test existence | Non | Non | Non | Non | Non | Validation seulement | Non | Non | `ABSENT` | Inventaire, formats, changes API, checkpoints, ACL, gouvernance | 5 |
| Connecteur Drive legacy A | Oui | Deux tests | Non exhaustive | Snapshot/rclone seulement | 2 584 objets | Credentials legacy | Faible | `drive.readonly`, mais écrit Chroma | Snapshot | Reprise insuffisante | `PARTIAL` | Migrer sans contourner le gate, deuxième sync et réconciliation | 5 |
| Comptabilité snapshot Drive | Rapports/scellement | Validateurs | rclone | Snapshot 2026-08-15 | 2 584 fichiers, 2 583 entrées appariées, 2 582 SHA, 1 objet extra non comptabilisé | n/a | Rapport | Read-only | Mapping seulement, pas une sauvegarde de contenu | Rejouabilité partielle | `PARTIAL` | Comptabiliser l'objet extra, puis une décision gouvernée par objet et snapshot frais | 5, 7 |
| Profils/placements production N=26 | Oui | Oui | Oui | Gate local | 26 contenus réels | Non | Rapports | PII/currentness | Inputs partiels hors Git | Recompute | `VERIFIED_LOCAL` | Autorisations et pipeline réel | 7 |
| PII corpus entier | Oui | Oui | Scan réel rapporté | Non rejouable seul | 2 476 PDF, 2 475 SHA | n/a | Rapport | 146 quarantaines, 43 échecs | Inputs hors Git | Non | `IMPLEMENTED_UNVERIFIED` | Rendre les inputs probants accessibles/rejouables | 7 |
| Autorisations/campagne/republish/H2 N=26 | Mécanismes présents | Oui | Rehearsals | Aucun run réel | 0/26 | Non | Rapports à zéro | Review-binding requis | n/a | Contractuel | `BLOCKED` | Rotation, trusted review, autorisations et H2 réels | 1, 7 |
| Ingestion pgvector/discoverability N=26 | Oui | Oui | Rehearsals DB | Non | `rag_chunks=0` | Non | Partielle | Writer gouverné | Backup DB | Restore attesté | `ABSENT` | Migrations, ingestion réelle et search par contenu | 7–9 |
| Migrations produit 001–004 + contrôle 001–013 | Oui | Oui | Restore isolé | Plan 18 étapes | État DB réel audité | Non appliquées | Audit DB | Cible vérifiée | Backup frais | Down/restore | `VERIFIED_STAGING` | Revalider au SHA gelé puis gate cutover | 8–9 |
| Backup/restore pgvector | Oui | Checksums | Restore isolé | Oui hors prod | Base réelle sauvegardée | Backup présent | Rapport | Globals assainis | Oui | Oui | `VERIFIED_STAGING` | Nouveau backup au cutover | 8–9 |
| Backup/restore Chroma | Cron archives | Non | Non | Aucun restore | Sept archives | Oui | Cron | Non évaluée | Oui | Non prouvé | `IMPLEMENTED_UNVERIFIED` | Restore réel avant convergence | 2, 8 |
| Docker V2 atomicité/rollback | Harnais PR #132 | Oui | Rehearsal branche | Non dans main | Fixtures | Non | Transcript | Isolation prévue | n/a | Oui sur branche | `IMPLEMENTED_UNVERIFIED` | Faire merger/rejouer sur SHA final | 8–9 |
| Image provenance/promotion | Workflows présents | Tests scripts | Non | Aucun run | Non | Zéro déploiement GitHub | GitHub | Digests prévus | n/a | Release | `IMPLEMENTED_UNVERIFIED` | Exécuter après freeze et approvals | 9 |
| Observabilité/alerting | Prometheus/code métriques | Partiels | Live partiel | 2/5 targets up | Oui | Partielle | Zéro règle/alerte | Metrics publiques | n/a | Runbook | `PARTIAL` | Fermer metrics, health workers, règles, alertes, logs | 8 |
| Runbooks go-live/incident/rollback | Oui | Tests partiels | Non | Non complet | Non | Documentation | n/a | Revue requise | Références | Procédures | `IMPLEMENTED_UNVERIFIED` | Rejouer scénario général complet | 8–9 |

## Vérité production observée

- DNS : `rag-ui.nexusreussite.academy` et `rag-api.nexusreussite.academy`
  pointent vers `88.99.254.59`.
- TLS Let's Encrypt valide ; renouvellement Certbot actif.
- L'API publique répond `200` sur `/health`, `401` sur `/collections/v2`
  sans authentification, `404` sur `/collections/readiness`.
- `/metrics` est publiquement accessible ; OpenAPI et `/docs` répondent `404`.
- Le release courant est basé sur le commit
  `27a4558a1abca304d415240b9ec0c06000cd2db5`, pas sur `main`.
- L'application active est `api:app` et l'UI active est Streamlit ; le runtime
  canonique `api_v2:app` et le Cockpit Next.js ne sont pas déployés.
- PostgreSQL 16.14/pgvector 0.8.2 est la bonne cible mais contient zéro chunk.
- Chroma legacy contient 23 904 vecteurs dans cinq collections peuplées.
- GitHub repo et Environment `production` exposent zéro secret et zéro
  variable. C'est conforme pour l'Environment lui-même, mais la cible auditée
  ne possède pas les paramètres canoniques requis : `PG_RAG_DSN`,
  `PG_REVIEW_DSN`, `RAG_BFF_SERVICE_TOKEN`, `NEXUS_INTERNAL_TOKEN_SECRET`,
  `RAG_ENGINE_INTERNAL_TOKEN`, `NEXTAUTH_SECRET` et les paramètres d'identité
  SSO. Seuls des noms legacy ont été observés : `API_SECRET_KEY`,
  `INGESTOR_API_TOKEN`, `INGEST_AUTH_TOKEN`, `LEGACY_ADMIN_API_TOKEN` et
  `REDIS_PASSWORD`. Aucune valeur n'a été lue dans le rapport.
- Le scan `gitleaks dir --redact=100 .` au SHA de base remonte 190 constats
  préexistants ; le fichier de ce rapport, scanné isolément, n'en ajoute aucun.
  Cette dette n'est pas assimilée à un contrôle secrets vert.

## Risques P1 ouverts

1. Le mot de passe Redis est visible dans les arguments/métadonnées du
   conteneur via `--requirepass`. Sa valeur n'a pas été copiée dans ce rapport.
2. `/opt/rag-v2/current` cible un répertoire en mode `0777`.
3. Les conteneurs applicatifs s'exécutent sans utilisateur explicite et donc
   comme root, sans suppression de capabilities démontrée.
4. `/metrics` est public et volumineux.
5. Les vhosts Nginx actifs n'appliquent ni rate limiting ni CSP adéquate.
6. Les images applicatives actives utilisent des tags mutables `latest`, sans
   référence GHCR immuable ni provenance attestée ; `ollama/ollama:latest` est
   également mutable.
7. Les secrets et paramètres d'identité nécessaires au runtime canonique sont
   absents de la cible auditée ; seuls les paramètres du runtime legacy sont
   présents.

Ces points relèvent du Lot 8. Toute rotation de secret ou mutation de
production requiert le gate opérateur prévu.

## État GitHub et lots actifs

- PR #134 : autorisations candidates, `APPROVED`, mais GitGuardian rouge et
  mergeabilité `UNSTABLE` ; aucune autorisation de production n'est effective.
- PR #132 : harnais Docker V2, branche en retard et trusted review absente.
- PR #98 : evidence-only, à fermer comme superseded après création de
  l'autorisation P24 finale issue du tree/profil/manifest courant.
- Production-image-provenance, promotion et H2 réutilisable : zéro run.

| Lot | Branche | PR | SHA | CI | Revue | Déployé | Preuve réelle | Rollback | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | `docs/go-live-baseline-matrix-20260825` | à ouvrir | à figer | à exécuter | à obtenir | non | audits code/GitHub/prod read-only | n/a | `VERIFIED_LOCAL` |
| 1 | `ops/review-binding-rotation-20260825` | à ouvrir | à figer | ciblée à exécuter | trusted review requise | non | clé primaire générée, backup/restauration en attente | remplacement par nouvelle rotation | `PARTIAL` |
| 2 | à créer | — | — | — | — | non | moteur A live et B local | à prouver | `PARTIAL` |
| 3 | à créer | — | — | — | — | non | API legacy live seulement | à prouver | `PARTIAL` |
| 4 | à créer | — | — | — | — | non | collecte staging partielle | à prouver | `PARTIAL` |
| 5 | à créer | — | — | — | — | legacy seulement | snapshot Drive réel ancien | à prouver | `PARTIAL` |
| 6 | à créer | — | — | CI Cockpit main verte | — | non | frontière statique locale | à prouver | `PARTIAL` |
| 7 | PR #134 partielle | #134 | `140b157f…` | GitGuardian rouge | review non suffisante | non | profils N=26, autorisations/H2=0 | contractuel | `BLOCKED` |
| 8 | PR #132 partielle | #132 | `c98ad5e…` | branche en retard | requise | non | backup/restore DB staging | partiel | `PARTIAL` |
| 9 | à créer | — | — | aucun run réel | requise | non | aucune répétition générale | non prouvé | `ABSENT` |

## Verdict

`NO_GO`

Les blockers structurants sont : rotation review-binding incomplète, API clé
externe absente, Web non raccordé au pipeline gouverné, connecteur Drive B
absent, Cockpit non déployé, autorisations/H2/ingestion N=26 à zéro, harnais
Docker V2 non fusionné et sept P1 d'exploitation ouverts.
