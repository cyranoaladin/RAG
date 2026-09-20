# ADR-0057 — Chaîne de readiness de répétition, distincte de la production

- **Statut** : Proposé — HUMAN GATE requis sur la PR
- **Date** : 2026-09-20
- **Décideur attendu** : reviewer humain habilité, lié au HEAD exact de la PR
- **S'appuie sur** : ADR-0036 (chaîne de promotion gouvernée), ADR-0056
  (revue de publication LOT42 pour release scellée)

> Cette ADR **n'autorise aucune exécution**, ne crée aucune clé, ne publie
> aucune ancre et ne signe aucun manifeste. Elle définit un protocole, ses
> refus, et la cérémonie humaine qui seule peut lui donner une autorité.

## Contexte — le fait qui force la décision

Le point d'entrée d'ingestion de release scellée (#236) appelle
`enforce_readiness_gate()`, comme Worker A. Mesuré sur le staging réel :

```
WORKER_READINESS_GATE_FAILED: NEXUS_EXPECTED_READINESS_PROTOCOL must explicitly pin V1 or V2
WORKER_READINESS_GATE_FAILED: NEXUS_READINESS_MANIFEST_PATH is not configured
```

Il n'existe, ni dans le dépôt ni sur l'hôte, **aucune** ancre de répétition,
**aucun** manifeste de readiness de répétition, **aucune** variable
`NEXUS_READINESS_*`. Worker A n'a donc jamais été démarrable sur ce staging
non plus. Le seul producteur de matériel de répétition est
`atomic_docker_v2_rehearsal_fixture.py` : une fabrique de **fixture de test**,
avec PR 9001, relecteur `nexus-fixture-reviewer` et clés éphémères.

## Le piège qu'on refuse

La réponse immédiate serait de réutiliser `NEXUS-PRODUCTION-READINESS-V1` en
mode répétition — ce mode existe déjà. Mesuré sur le contrat, voilà ce qu'il
faudrait affirmer pour une exécution qui **ne déploie rien** :

| Ce que le contrat impose | Ce que la répétition ferait |
|---|---|
| `environment: "production"` (littéral) | déclarer « production » pour ne rien déployer |
| `gate_result: "pass"` | affirmer le verdict d'une porte de déploiement |
| `release_tag: release/rag/YYYYMMDD-<merge12>` | nommer une release qui n'existe pas |
| `h2b_report_digest`, `catalog_digest`, `sealed_manifest_digest`, `review_binding_digest`, `authorization_digest`, `revocation_registry_digest`, `trust_anchor_digest` | sept digests de preuves de promotion |
| `application_image_digests`, `upstream_image_digests`, `compose_digest` | le compose de **production** résolu |
| `workflow_path`, `run_id`, `run_attempt` | un run du workflow de promotion |

Vingt-six faits de déploiement de production pour autoriser une écriture dans
un plan de contrôle de staging. Ce n'est pas une formalité pénible : c'est
une fabrication. On ne fabrique pas d'ancre ; on ne fabrique pas de faits non
plus.

`enforce_readiness_gate` répond correctement à la question qu'il pose —
*l'hôte exécute-t-il exactement la release relue et promue ?* Ce n'est
simplement pas la question posée par une ingestion de staging.

## Décision

### 1. Un protocole propre : `NEXUS-STAGING-READINESS-V1`

Il ne déclare que ce qui est vrai pour une ingestion de répétition :

| Champ | Ce qu'il fixe | Vérifiable contre |
|---|---|---|
| `environment` | `"rehearsal"`, littéral | — |
| `repository`, `merge_sha` | le code réellement exécuté | un commit de ce dépôt |
| `worker_image` | l'image, épinglée par digest | l'inventaire de provenance (CH6) |
| `allowed_release_id` | le corpus couvert, et lui seul | le manifeste de la release |
| `allowed_release_manifest_sha256` | ses octets exacts | recalculé au chargement |
| `control_dsn_differs_from_product` | le cloisonnement | mesuré à l'exécution |
| `key_id`, `issued_at`, `expires_at` | qui, quand, jusqu'à quand | l'ancre publique |

**Une autorisation de répétition expire.** Sans `expires_at`, elle
deviendrait une autorisation permanente que personne n'a décidé d'accorder.

### 2. `enforce_readiness_gate` n'est pas touché

Pas une ligne. Trois tests le prouvent par `git diff` contre `origin/main` :
le gate de production, le contrat de production et l'ancre de production sont
byte-identiques. La chaîne de répétition ne les appelle pas, ne les importe
pas — à deux constantes près, empruntées délibérément : le nom de la variable
`NEXUS_ENVIRONMENT`, et **le chemin de l'ancre gouvernée qu'elle refuse**.
Emprunter la valeur qu'on refuse est plus sûr que la recopier : une
divergence future ne créerait pas un trou.

### 3. « rehearsal ≠ production » est structurel, pas déclaratif

Trois barrières indépendantes, chacune suffisante :

1. **Le protocole.** L'ancre de production porte
   `NEXUS-PRODUCTION-READINESS-V1` : présentée comme ancre de répétition,
   elle échoue au parsing. Pointer la variable sur son chemin ne marche pas ;
2. **Le refus nommé.** Le gate de répétition refuse explicitement un chemin
   d'ancre qui désigne l'ancre gouvernée de production, **avant** de la lire —
   pour que l'opérateur lise un refus, pas une erreur de parsing ;
3. **Les littéraux.** `environment: "rehearsal"` sur le manifeste *et* sur
   chaque clé de l'ancre. Une clé de production ne peut pas y figurer, et une
   clé de répétition ne peut rien signer pour la production.

La première suffirait. Les trois existent parce qu'une seule garde, un jour,
se contourne par un chemin auquel personne n'avait pensé.

### 4. Aucune valeur de repli, aucune variable vide tolérée

Les cinq variables — `NEXUS_ENVIRONMENT`,
`NEXUS_EXPECTED_READINESS_PROTOCOL`, `NEXUS_READINESS_MANIFEST_PATH`,
`NEXUS_READINESS_MANIFEST_SHA256`, `NEXUS_STAGING_READINESS_TRUST_ANCHOR` —
n'ont **aucun** défaut. Absente, vide, ou faite d'espaces : même refus. Le
cas des espaces est le plus traître — la variable « existe », passe un test
de présence, et ne nomme rien.

`NEXUS_READINESS_MANIFEST_SHA256` n'est pas décoratif : les octets du
manifeste sont rehachés et comparés avant toute vérification de signature.

### 5. Une fixture de test ne fait jamais autorité

Le contrat refuse, à la validation, tout `key_id` contenant `ephemeral`,
`fixture`, `sample`, `dummy` ou `example` — dans l'ancre **comme** dans le
manifeste. Les trois identités de `atomic_docker_v2_rehearsal_fixture.py`
sont donc structurellement inacceptables comme autorité.

Cela n'interdit pas à un test de signer ses propres octets : sans signature
vraie, « un manifeste valide est accepté » ne prouverait rien. La frontière
est nette — un test signe ce qu'il vérifie, une fixture ne fait pas autorité
sur un hôte.

### 6. L'autorité nomme un corpus, pas seulement un hôte

Le point d'entrée vérifie que `allowed_release_id` et
`allowed_release_manifest_sha256` sont **ceux de la release qu'il charge**.
Sans cette liaison, un manifeste valide autoriserait l'ingestion de n'importe
quelle release : l'autorité porterait sur la machine, pas sur ce qu'on y
écrit.

### 7. La clé est générée hors dépôt, et cette ADR ne la contient pas

Aucune clé privée, aucune clé publique, aucune ancre, aucun manifeste signé
n'est livré ici — et aucun placeholder non plus. Une clé qu'un outil
automatique génère et conserve est éphémère par nature ; l'ancre de
production le dit déjà pour elle-même : *« private key held offline outside
this repository/host »*. La répétition suit la même discipline.

La cérémonie est décrite dans
`docs/runbooks/ceremonie_cle_readiness_repetition.md`. Tant qu'elle n'a pas
eu lieu, la chaîne existe et refuse tout — ce qui est exactement le
comportement attendu d'une chaîne sans autorité.

## Conséquences

**Ce que cela débloque.** Rien immédiatement. Après la cérémonie et le lot
CH6 (image worker épinglée), le point d'entrée devient exécutable sur
staging. Les deux lots sont cumulatifs : ni l'un ni l'autre ne suffit.

**Ce que cela ne débloque pas.** Ni Worker A, ni Worker B, ni la publication,
ni l'attestation LOT42, ni `STAGING_EXTERNE`, ni quoi que ce soit en
production. Ce protocole n'a aucune autorité hors de la répétition, et le
type l'interdit.

**Ce qu'il faudra décider plus tard.** Worker A et Worker B appellent
`enforce_readiness_gate` et restent donc non démarrables en répétition. Cette
ADR ne tranche pas leur cas : elle n'ouvre que la porte dont le lot CO a
besoin. Étendre la chaîne de répétition aux workers est une décision
distincte, qui devra dire ce qu'une répétition de publication signifie.
