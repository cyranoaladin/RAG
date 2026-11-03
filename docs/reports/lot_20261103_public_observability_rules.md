# Lot 2026-11-03 — règles d'alerte du stack public final

## Déclencheur

Relevé en lecture seule sur `korrigo` le 2 novembre 2026 : le Prometheus de la pile publique (loopback `19091`) voit **2 cibles sur 5 `up`** et charge **0 groupe de règles, 0 règle, 0 alerte**. Un Prometheus sans règle n'observe rien : il collecte.

Les trois cibles `down` ne sont **pas des pannes**, et c'est le point méthodologique du lot. Leurs `lastError` respectifs le disent :

| Cible | `lastError` | Nature réelle |
| --- | --- | --- |
| `chroma` | `lookup chroma on 127.0.0.1` | Nom d'hôte appartenant au réseau Docker du projet `compose` (pile V1), scruté depuis le projet `infra`. Le service est `healthy`. |
| `ollama` | `HTTP 404` | Ollama n'expose pas d'endpoint Prometheus. Le service est `healthy`. |
| `ui` | `expected a valid start token, got "<"` | La cible renvoie du HTML, pas des métriques. |

Trois faux `down` permanents sont exactement ce qui fait ignorer les vraies alertes.

Base : `origin/main=99178e64a9eaa8c758a907d226f23ac2b68c4066`, arbre `cf5b5356ffc5d7ac9426366ae6bf26f128c16995`, worktree propre et détaché.

## Pourquoi un fichier distinct de `rag-alerts.yml`

`rag-alerts.yml` porte 20 alertes, dont `RAGChromaDBDown`, `RAGOllamaDown` et `RAGUIDown` : ces trois cibles appartiennent à la **pile V1 historique**, sur un autre réseau Docker, non routée publiquement. Les charger dans le Prometheus de la release publique produirait trois `critical` permanents et faux.

`prometheus.v2.yml` ne chargeait que `retrieval.rules.yml`, soit **4 alertes sur les 26 présentes dans le dépôt**. Ce lot ajoute un fichier dédié au périmètre public et le câble, sans toucher aux fichiers existants.

## Les dix alertes ajoutées

Seuils alignés sur le **budget de charge C0 gelé** : 8 clients, 240 requêtes, p50 ≤ 3 000 ms, p95 ≤ 6 000 ms, p99 ≤ 7 500 ms, erreurs = 0, timeouts = 0, connexions DB ≤ 10.

| Dimension exigée | Alerte | Expression | Sévérité |
| --- | --- | --- | --- |
| API indisponible | `PublicRetrievalScrapeFailed` | `up{job="rag-engine-v2"} == 0` | critical |
| recherche 5xx | `PublicRetrievalServiceUnavailable` | `increase(retrieval_http_503_total[5m]) > 0` | critical |
| latence p95 | `PublicRetrievalP95AboveBudget` | p95 > **6 s** avec garde de volume ≥ 20 req/5 min | warning |
| latence p99 | `PublicRetrievalP99AboveBudget` | p99 > **7,5 s** avec garde de volume | critical |
| erreurs de retrieval | `PublicRetrievalErrorsByCause` | `increase(retrieval_errors_total[5m]) > 0`, label `cause` | critical |
| saturation DB | `PublicRetrievalDbPoolSaturation` | `cause="pool_failure"` | critical |
| timeouts | `PublicRetrievalTimeouts` | `cause="timeout"` | critical |
| santé du classement | `PublicRetrievalAnnTieOverflow` | `increase(retrieval_tie_overflow_total[5m]) > 0` | warning |
| anomalie de résultat vide | `PublicRetrievalEmptyResultAnomaly` | ratio vides/requêtes > **50 %** sur 15 min, volume ≥ 20 | critical |
| refus de scope | `PublicRetrievalScopeRefusalSpike` | `increase(retrieval_scope_refusals_total[15m]) > 10` | warning |

Les gardes de volume (`>= 20` requêtes) évitent une alerte de latence calculée sur un échantillon vide. Les labels `cause` sont tous pris dans l'ensemble borné du contrat : `authentication`, `invalid_request`, `scope_refusal`, `timeout`, `pool_failure`, `ann_overflow`, `service_unavailable`, `internal_error`.

## Ce que ce lot ne couvre pas, et pourquoi il ne le simule pas

Deux dimensions demandées **n'ont aucune métrique exposée** :

- **santé de l'index vectoriel** : `retrieval_database_ready()` est une fonction de readiness appelée au démarrage, pas une série Prometheus. Aucune gauge `*_database_ready` n'est exportée par `src/ingestor/metrics.py`.
- **échec d'un job Worker A/B** : ce sont des CLI gouvernés, pas un service scruté.

**Déclarer une alerte sur une métrique absente ne protège rien** : elle ne se déclenche jamais et produit une fausse assurance. Ces deux trous exigent du code — une gauge de santé d'index et un signal de job worker — et non une règle. Ils sont inscrits en tête du fichier de règles pour que personne ne les croie couverts.

`OBSERVABILITY_READY=true` ne peut donc **pas** être déclaré par ce lot seul : il y faut aussi ces deux métriques, le chargement effectif des règles sur la couleur candidate, et la suppression des trois faux targets de l'ancienne configuration.

## Vérifications exécutées

| Contrôle | Résultat |
| --- | --- |
| YAML de `public-release.rules.yml`, `retrieval.rules.yml`, `prometheus.v2.yml` | parse OK |
| Schéma des 10 alertes (`alert`, `expr`, `labels.severity`, `annotations.summary`) | **0 erreur** |
| Métriques référencées existantes dans `src/ingestor/metrics.py` | **7 / 7 ; 0 métrique inexistante** |
| Labels `cause` dans l'ensemble borné du contrat | **0 cause hors contrat** |
| `scripts/check-governance-locks.sh` | 18/18 conformes |
| `git diff --check` | propre |

`promtool check rules` **n'a pas pu être exécuté** : l'outil est absent du poste, son téléchargement et l'exécution d'un conteneur de validation sur l'hôte ont tous deux été refusés par la politique de l'environnement. La validation PromQL formelle reste donc **due** et doit être faite en CI ou par l'opérateur avant fusion. Les expressions p95/p99 reprennent la forme exacte de `RAGRetrievalP95High`, déjà chargée et évaluée sans erreur sur le Prometheus de staging.

## Gate

Review exact-HEAD, CI standard verte, puis `promtool check rules` sur ce HEAD avant fusion. Le chargement effectif des règles devra être constaté sur la couleur candidate — un fichier dans le dépôt n'est pas une alerte active.
