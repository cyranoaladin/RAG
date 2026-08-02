# LOT41S — Provenance des checks CI protégés

## Verdict

**LOT41S_READY_FOR_REVIEW**

Le lot supprime l’ambiguïté de provenance des six checks protégés avant fusion
et corrige les instructions historiques de preuve LOT37R. Ce verdict concerne
uniquement la topologie CI et ne vaut ni validation fonctionnelle du pilote ni
autorisation de mise en production.

**GO_LIVE: NO_GO**

## Périmètre

| Élément | Valeur |
| --- | --- |
| Date | 2026-08-02 |
| Baseline | `6e4e241d6ca0c5a0151b500a3d9eb18527283235` |
| Branche | `lot-41s-ci-provenance` |
| Workflow concerné | `.github/workflows/ci.yml` |
| Politique concernée | `scripts/github/main-protection-policy.json` |

LOT41S modifie la topologie des déclencheurs du workflow canonique, renforce
les tests fail-safe et précise la portée exacte des artefacts de preuve. Il ne
change aucun job métier, aucun nom de contexte protégé, aucune règle active de
protection de `main` et aucun verrou de gouvernance.

## Reproduction initiale

Le défaut a été reproduit sur le head
`8cafdc652060973f5bf738777486e5192afb82e0`. Deux exécutions du même workflow
étaient attachées à ce SHA :

| Run | Événement | Constat |
| --- | --- | --- |
| `30734892670` | `push` | publiait les six noms protégés |
| `30734894002` | `pull_request` | publiait les mêmes six noms protégés |

Les noms dupliqués étaient :

- `packages/contracts` ;
- `services/rag-pedago` ;
- `services/rag-engine` ;
- `services/cockpit` ;
- `governance locks guard` ;
- `repository controls`.

La protection de branche identifie un check par son contexte, pas par
l’événement GitHub Actions qui l’a produit. Un succès du run `push` pouvait donc
rendre la provenance ambiguë, voire satisfaire un contexte alors que le run
`pull_request` correspondant échouait.

## Cause racine

Le workflow canonique acceptait simultanément `push` sur `main`, `lot-*` et
`lot-*/**`, ainsi que `pull_request` vers `main`. Un head de branche de lot
déclenchait donc deux runs concurrents portant exactement les mêmes noms de
jobs. L’artefact LOT37R savait sélectionner un run `pull_request`, mais cette
sélection documentaire ne modifiait pas la façon dont GitHub associait les
contextes requis au SHA.

Une seconde ambiguïté documentaire provenait de l’ajout d’un artefact dans un
commit postérieur au SHA qu’il certifiait. L’artefact reste valable pour son
`headSha`, mais ne peut pas constituer une preuve du commit qui l’ajoute.

## Solution appliquée

Le workflow canonique accepte désormais exactement :

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
```

Avant fusion, un SHA de branche ne peut donc recevoir les six contextes
protégés que du run `pull_request`. Après fusion, le SHA de squash distinct sur
`main` est revalidé par `push`. Le contrôle fail-safe impose également :

- l’ensemble exact des deux événements autorisés ;
- l’absence de branche de lot dans `push` ;
- une occurrence statique unique de chaque contexte protégé ;
- la propriété de ces six contextes par le seul fichier `ci.yml` ;
- le refus des noms calculés dynamiquement et des jobs protégés matriciels,
  dont les noms effectifs ne seraient pas démontrables statiquement.

Le plan historique LOT37R précise maintenant qu’un artefact versionné certifie
seulement le SHA qu’il nomme. Les checks du commit documentaire qui l’ajoute
restent une preuve externe consultée sur GitHub ; l’artefact parent-SHA ne les
revendique pas.

## Cycles TDD et preuves locales

| Cycle | État attendu observé | Résultat |
| --- | --- | --- |
| Contrat initial des déclencheurs | RED sur le workflow encore permissif | 46 réussites, 1 échec |
| Revue — extraction du validateur des contextes | RED avant raccordement complet | 46 réussites, 2 échecs |
| Revue — extraction du validateur des contextes | GREEN après raccordement | 48 réussites, 0 échec |
| Revue — noms dynamiques et matrices | RED avant durcissement | 48 réussites, 2 échecs |
| Revue — noms dynamiques et matrices | GREEN final | 50 réussites, 0 échec |

Le test de topologie accepte la fixture canonique et rejette ses 22 mutations.
La politique de protection de `main` conserve ses 31 tests réussis. La
relecture live en mode non mutatif a retourné :
`OK: main protection matches policy for cyranoaladin/RAG`.

Ces résultats attestent la vérification locale et la relecture de la politique
active. Ils ne pré-déclarent pas les checks GitHub du head final de la future
PR LOT41S, qui devront être observés après publication sur ce SHA exact.

## Commits du lot

| SHA | Objet |
| --- | --- |
| `a11d013` | spécification de la provenance CI |
| `6111512` | plan d’implémentation LOT41S |
| `3cb518c` | restriction initiale des déclencheurs et cycle TDD |
| `d84f1a5` | extraction du contrôle des contextes protégés |
| `b0f7ad0` | refus des noms dynamiques et des matrices |

La spécification a reçu une revue indépendante avec verdict **APPROVE**. La
revue qualité indépendante de l’implémentation a également conclu **APPROVE**,
sans constat bloquant restant dans son périmètre.

## Exclusions et suites

LOT41S ne prétend pas authentifier les approbations humaines, signer les
attestations de qualité ou lier une publication métier à son scope autorisé.
Ces preuves de gouvernance sont traitées séparément par LOT41T afin de ne pas
mélanger une correction de topologie CI avec la logique métier de promotion.

Sont également exclus : la revue substantielle complète du corpus, les portes
humaines restantes, le déploiement public et les autres lots fonctionnels de la
trajectoire go-live. Chacun conserve ses propres critères et preuves.

## Décision de livraison

LOT41S peut être proposé en PR dédiée après vérification locale complète. La
fusion reste conditionnée aux checks du head publié exact, à l’absence de run
`push` sur ce head de branche, aux revues finales et au respect de la protection
de `main`. Le SHA de squash devra ensuite être revalidé séparément par le run
`push` de `main`.
