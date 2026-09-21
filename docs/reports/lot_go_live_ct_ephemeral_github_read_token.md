# Lot CT — accès GitHub éphémère en lecture seule pour l'ingestion staging

**Branche** : `go-live/ct-ephemeral-github-read-token-for-staging-ingestion`
**Base** : `main` = `486a1ab9` (lot CS)
**Nature** : amendement opérationnel de l'autorisation staging. Aucun artefact
LOT41A n'est touché, aucune autorisation n'est réenregistrée, aucun code
d'ingestion n'est modifié.

## 1. Le problème, tel qu'il s'est présenté

Les onze autorisations LOT41A sont enregistrées en staging avec leur preuve
scellée (ADR-0058), et vérifiées **depuis le poste** dans l'image épinglée
`sha256:431264a0…` — onze sur onze. La vérification dans le contexte réel du
worker staging reste à effectuer ; elle est l'objet de ce lot.

Ce qui manque n'est pas une décision de gouvernance : c'est un accès réseau.
`_verify_reviewed_artifact` relit l'artefact d'autorisation sur GitHub **à
chaque usage**. Ce n'est pas un reliquat du modèle « revue vivante » qu'ADR-0058
a remplacé : c'est le seul contrôle capable de détecter qu'un artefact aurait
été modifié *après* son approbation. Le sceau enregistre ce qui **était** ; il
ne peut pas voir ce qui a changé depuis. Sans cette relecture, une modification
post-approbation passerait inaperçue.

Le worker a donc besoin de lire `cyranoaladin/RAG` — et de rien d'autre.

## 2. Ce que ce lot autorise

Un *fine-grained personal access token* dédié :

| Dimension | Valeur |
|---|---|
| Permissions | `contents: read`, `metadata: read` — et strictement rien d'autre |
| Dépôts | `cyranoaladin/RAG` seul |
| Durée | 1 jour maximum |
| Distinct de | le jeton d'administration du dépôt **et** le jeton de revue d'`abenrhouma` |

Le worker n'hérite jamais des privilèges d'une revue. Un jeton capable
d'approuver une PR, de pousser un commit ou de fusionner n'a rien à faire dans
un processus d'ingestion : il lui permettrait de fabriquer l'autorisation qu'il
est censé vérifier.

La clé privée d'une application GitHub ne serait de toute façon jamais
transférée — aucune application utilisable n'existe sur ce dépôt (`gh api` :
403/401), d'où le choix du PAT restreint.

## 3. L'injection : par fichier, jamais par l'environnement

| Règle | Raison |
|---|---|
| `NEXUS_GITHUB_TOKEN_FILE` porte un **chemin** | `/proc/<pid>/environ` est lisible ; la valeur ne doit pas y figurer |
| `NEXUS_GITHUB_TOKEN` (la valeur) : interdit | même raison |
| Jamais dans les arguments de commande | `ps`, historiques shell, traces `-x` |
| Répertoire `0700`, fichier `0600` | le montage est lisible par le seul processus concerné |
| Pas de surcharge de `NEXUS_GITHUB_API_BASE` | un jeton envoyé vers un serveur non prévu est un jeton divulgué |
| Pas de désactivation de TLS, pas de proxy improvisé | idem |

Rien de la configuration `gh` du poste, aucun trousseau, aucun fichier
d'environnement n'est copié : une copie temporaire du seul jeton dédié.

## 4. Base de données : le worker n'obtient pas l'autorité en passant

Le worker tourne sous `ingestion_control_app`. Le DSN d'autorité n'est **pas**
monté dans le worker, même pour faciliter un test : `ingestion_control_authority`
écrit des autorisations, et c'est précisément le droit qu'un processus vérifiant
des autorisations ne doit pas avoir.

## 5. `loopback_only` → `no_inbound_exposure` : une clarification, pas un élargissement

`loopback_only` décrivait l'**exposition** du service : aucun port publié,
aucune écoute au-delà de `127.0.0.1`. Il n'a jamais décrit la **sortie**, et
n'a jamais interdit un appel HTTPS sortant — le worker en émet déjà vers l'API
GitHub. La formulation était ambiguë ; elle est précisée.

Le document enregistre explicitement `inbound_exposure_added: false` et
`firewall_modified: false`. Aucune permission n'est ajoutée. Le pare-feu de
production n'est pas touché. La sortie autorisée est énumérée, et se limite à
`https://api.github.com`.

Trois épreuves antérieures (CH6, CH7B, CS) fixaient l'ancienne valeur. Elles
sont mises à jour dans ce diff — visiblement, sous revue — et assertent
désormais l'invariant sur ses **deux** axes au lieu d'un seul. Aucune n'est
supprimée ni affaiblie.

## 6. Fin d'opération : quatre gestes, aucun facultatif

1. arrêt des processus concernés ;
2. retrait du montage ;
3. suppression de la copie temporaire ;
4. **révocation du jeton dédié par son détenteur**.

La suppression du fichier et la révocation de l'accès sont deux résultats
distincts, constatés séparément. Une expiration future annoncée n'est pas une
révocation effectuée : tant que le jeton n'est pas révoqué, il vaut.

## 7. Ce qui ne bouge pas

- les onze artefacts LOT41A : aucun octet ;
- les onze autorisations enregistrées : aucun `UPDATE`, aucune suppression ;
- la release V2 : aucune modification ;
- le digest de l'image worker (`sha256:431264a0…`) et celui de l'image API ;
- `current_switch`, `production_db_write`, `production_db_read`,
  `public_exposure`, `production_secret_read` : interdits ;
- Worker B (`multilevel_publication_resume_cli`) : hors autorisation ;
- le trust-anchor de production, la base de production, le pare-feu.

## 8. Vérification

```
scripts/qualification : 404 passed, 3 skipped
ruff                  : All checks passed
```

Les épreuves du lot couvrent : la lecture seule et le refus de toute permission
supplémentaire, la sélection d'un seul dépôt, la durée bornée, la distinction
d'avec le jeton de revue, les cinq relâchements d'injection refusés un par un,
l'interdiction de surcharger la base d'API ou de désactiver TLS, le refus du DSN
d'autorité dans le worker, chacun des quatre gestes de fin d'opération pris
isolément, et la clarification réseau prouvée non élargissante.

## 9. Ce que ce lot ne prétend pas

Il **n'exécute pas** l'ingestion. Il n'autorise pas la publication. Il ne
constitue pas `GO_LIVE_READY`.

Le jeton n'est créé et déposé qu'**après** l'entrée en vigueur de cet amendement
selon la procédure du dépôt. Une approbation en conversation ne remplace pas la
revue épinglée exigée par cette procédure.
