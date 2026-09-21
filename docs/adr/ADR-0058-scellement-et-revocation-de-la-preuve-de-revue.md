# ADR-0058 — Scellement et révocation de la preuve de revue de confiance

- **Statut** : Proposé — HUMAN GATE requis sur la PR
- **Date** : 2026-09-20
- **Décideur attendu** : reviewer humain habilité, lié au HEAD exact de la PR
- **S'appuie sur** : ADR-0025 (revue humaine de confiance), ADR-0032
  (autorisation de scope LOT41A), ADR-0042, ADR-0057

> Cette ADR **n'autorise rien**, n'enregistre aucune autorisation et
> n'exécute aucune ingestion. Elle déplace une garde dans le temps, sans la
> desserrer.

## Le fait qui force la décision

`verify_scope_authorization` revérifiait, **à chaque usage**, que la pull
request d'autorité était encore **ouverte** et approuvée. Mesuré sur la PR
#233, qui porte les onze autorisations LOT41A de la release V2 :

```
PR #233 : state = closed | merged = True
decision : REFUSE (pull_request_not_open)
```

La revue humaine avait bien eu lieu, au bon head, par le bon relecteur. Elle
était simplement **derrière** : la PR avait été fusionnée, comme elle devait
l'être pour que l'artefact d'autorisation atteigne `main` et puisse y être
relu.

C'est une contradiction structurelle, pas un incident :

| Exigence | Impose |
|---|---|
| l'artefact doit être relu sur `main` | la PR est **fusionnée** |
| la revue doit être vérifiée en direct | la PR est **ouverte** |

Les deux ne peuvent pas être vraies au moment de l'usage. Et cela ne
concerne pas un seul consommateur : `runner.py` (Worker A),
`attest_publication_cli` et `publication_attestation` appellent tous
`verify_scope_authorization`.

## Ce qui a été écarté

**Une fenêtre de revue vivante à chaque usage.** Ouvrir une PR, l'y laisser
ouverte le temps d'exécuter, fusionner ensuite. C'est ce que le lot CH5 a
fait pour l'enregistrement, et ça marche — une fois. En faire le modèle
durable signifierait qu'aucune ingestion, aucune attestation, aucune reprise
après incident ne peut avoir lieu sans rouvrir une fenêtre humaine. La garde
deviendrait un obstacle à sa propre application, et la tentation d'y passer
outre croîtrait à chaque itération.

## Décision

Le modèle change de **temps**, pas de **sévérité**.

### 1. À l'enregistrement, tout reste exigé en direct

Rien n'est retiré. Au moment où l'autorisation est enregistrée :

- la pull request est **ouverte** ;
- elle est **APPROVED** par un relecteur de l'allowlist gouvernée ;
- l'approbation porte sur le **head exact** ;
- le **challenge** d'ADR-0025 est correct ;
- le contexte `trusted-human-review/head-pinned` est **success** sur ce head ;
- l'artefact est relu **octet à octet** au commit approuvé.

Une PR fermée à l'enregistrement est refusée, comme avant.

### 2. Ce que la preuve scelle

`NEXUS-SEALED-TRUSTED-REVIEW-EVIDENCE-V1` conserve :

| Champ | Ce qu'il fixe |
|---|---|
| `repository`, `pull_request` | la décision dont il s'agit |
| `pull_request_base_ref`, `pull_request_base_sha`, `pull_request_head_sha` | la révision exacte relue |
| `pull_request_author` | la septième dimension du challenge |
| `authorization_id`, `artifact_path`, `artifact_sha256`, `artifact_blob_sha` | ce qui était autorisé, par ses octets |
| `reviewer`, `review_id`, `review_node_id`, `review_submitted_at` | qui a approuvé, et quand |
| `challenge_protocol`, `challenge` | sous quel protocole |
| `head_pinned_status`, `head_pinned_context` | que la porte était passée |
| `recorded_at`, `recorder_version`, `workflow_run_id` | qui a scellé, avec quoi |

`pull_request_author` et `pull_request_base_ref` **n'existaient pas** dans
l'ancien enregistrement. Ils sont ajoutés parce qu'ils sont nécessaires : sans
eux, le challenge ne peut qu'être recopié, jamais **recalculé**.

### 3. À l'usage, la preuve est vérifiée — et le challenge recalculé

Huit contrôles, chacun refusant :

1. la preuve existe ;
2. elle valide strictement contre son contrat ;
3. son digest est celui enregistré avec elle ;
4. **son challenge se redérive de ses propres dimensions** ;
5. son relecteur est **encore** dans l'allowlist gouvernée ;
6. le contexte de protection y est scellé au vert ;
7. elle décrit la même revue que les colonnes typées de la ligne ;
8. elle n'a pas été révoquée.

Le point 4 est ce qui distingue une preuve d'une copie : un challenge
enregistré tel quel n'établirait que la bonne foi de celui qui l'a écrit.
Recalculé, il lie les sept dimensions entre elles.

Le point 5 reste **vivant** : retirer une identité de l'allowlist éteint
toutes les autorisations qu'elle a signées, sans avoir à les révoquer une
par une.

### 4. Ce que la preuve ne prétend plus établir

Il faut le dire, parce que c'est exactement ce que le changement coûte :

- **elle n'affirme rien sur l'état de la PR après l'enregistrement.** Une PR
  fusionnée, fermée ou supprimée ne change plus rien ;
- **elle ne détecte pas une revue retirée hors modèle.** Si une approbation
  est dismissée sur GitHub après le scellement, l'ancien modèle l'aurait vu
  au prochain usage ; celui-ci ne le verra pas ;
- **elle ne remplace pas une révocation.** C'est la contrepartie directe du
  point précédent : ce que la liveness détectait par accident, la révocation
  doit maintenant le faire **exprès**.

### 5. La révocation, contrepartie obligatoire

Une preuve scellée sans registre de révocation serait une autorisation
éternelle. Deux niveaux, déjà distincts :

- `scope_authorizations.revoked_at` éteint **une** autorisation ;
- `ingestion_control.revoked_review_evidence` éteint **une preuve**, donc
  toutes les autorisations qui s'en réclament — le cas d'une revue qu'on
  découvre après coup ne pas avoir eu la portée qu'on croyait.

La révocation est elle-même une décision humaine gouvernée : la table porte
sa propre preuve de revue.

### 6. Aucun backfill, aucune tolérance

Les lignes enregistrées sous l'ancien modèle n'ont pas de preuve scellée, et
**n'en auront jamais** : une revue ne se reconstitue pas après coup. Elles
deviennent inutilisables à l'usage. C'est voulu — pas de preuve, pas
d'autorisation.

Les onze autorisations LOT41A V2 devront donc être réenregistrées sous le
nouveau modèle, dans une fenêtre de revue vivante, avec un payload métier
identique. C'est l'objet d'un lot séparé.

### 7. Compatibilité avec CH5

Le lot CH5 avait établi, à ses dépens, qu'une autorisation doit être
enregistrée **pendant que la PR est ouverte**. Cette ADR ne change rien à
cette règle : elle la rend seulement suffisante. CH5 disait « enregistrer
avant de fusionner » ; ADR-0058 dit « et ce que vous avez enregistré alors
vaut encore après ».

## Conséquences

**Ce que cela débloque.** L'usage d'une autorisation cesse de dépendre de
l'état d'une PR que le temps ferme nécessairement. Worker A,
`attest_publication_cli` et le point d'entrée de release scellée en
bénéficient identiquement, sans modification de leur part.

**Ce que cela exige.** Que la révocation soit réellement utilisée quand une
revue doit être invalidée. Une garde déplacée dans le temps n'est pas une
garde supprimée, à condition que le mécanisme compensatoire existe et soit
employé.

**Ce que cela ne touche pas.** ADR-0025 reste inchangée : la décision de
revue est toujours rendue par `evaluate_trusted_review`, et le scellement ne
fait que la conserver. La chaîne de readiness de production
(`enforce_readiness_gate`) n'est pas concernée.
