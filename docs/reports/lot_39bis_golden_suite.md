# LOT39bis — Spécification de la suite golden du pilote

## Verdict

**LOT39BIS_TECHNICALLY_VALID_AWAITING_HUMAN_REVIEW**

**GO_LIVE: NO_GO**

Ce verdict porte uniquement sur la spécification d’évaluation. L’intégrité
technique est verte et adressée, mais la revue humaine est encore `pending` et
le diagnostic de promotion retourne volontairement le code `3`. Le lot ne vaut
ni qualification d’un corpus réel, ni baseline retrieval, ni certification de
réponse générée. La fusion est interdite tant que la CI, les revues finales, les
checks GitHub et la revue humaine exhaustive ne sont pas tous prouvés sur la
même tête.

## Périmètre

LOT39bis doit fixer, sans lire de document réel :

- les textes et attentes de 255 requêtes ;
- les quatre catégories `positive`, `no_source`, `confusion` et
  `adversarial` ;
- les filtres exacts du scope LOT38 ;
- les seuils absolus de recette ;
- le digest de tous les fichiers normatifs ;
- une frontière fail-closed pour la revue humaine de 100 % du contenu.

Le lot ne modifie ni `packages/contracts`, ni `rag-engine`, ni `cockpit`, ni les
verrous de gouvernance. Il ne contient aucun document de corpus, identifiant de
document/chunk, résultat de retrieval, score, baseline ou déclaration de
substance. La résolution vers des ressources publiées appartient à LOT42.

## Base et source canonique

La branche `lot-39bis-specification-golden` part de
`main@56d8389f132de8f8a575efce5c856bb8b11adda9`, squash de la PR LOT38 #81.
Le scope canonique est `libre_terminale_maths_nsi_real_v1`, année scolaire
`2026-2027`, pour 13 notions de Mathématiques et 26 notions de NSI.

Les digests hérités de LOT38 sont :

- scope : `b55ef1383fceabbbe0bf30c47a45a1fce607697f56bac340162156fabcf0fe26` ;
- taxonomie Mathématiques :
  `4a91661a381751573425b30667c53fc8f44df04fa4e0f7a0c4e71f0ec64005a6` ;
- taxonomie NSI :
  `b93a3e4017e99f1647861abac46b5f3136ee8611e7142d4fca2a33a5929eb05f`.

## Audit du stash historique

Le stash immuable
`7ffde33ac4255e314762a0fc4616f8fc7fb03d4a` a été inspecté sans être appliqué,
modifié ou supprimé. Il contient 41 chemins mêlant migrations, retrieval,
gouvernance, review et Compose. Concernant les goldens, il ne contient que la
suppression de `services/rag-pedago/tests/golden_queries/.gitkeep` : aucune
requête, aucun jugement et aucun digest réutilisable.

LOT39bis repart donc de la taxonomie et du scope canoniques, et non du stash.
Les stashes historiques restent des artefacts locaux non livrés et ne sont pas
une source de vérité.

## Cardinalités obligatoires

| Catégorie | Mathématiques | NSI | Total | Attente |
|---|---:|---:|---:|---|
| positives | 65 | 130 | 195 | cinq requêtes distinctes par notion |
| sans source | 10 | 10 | 20 | refus pour preuve insuffisante |
| confusion | 10 | 10 | 20 | résultat in-scope, fuite interdite |
| adversarial | 10 | 10 | 20 | injection/exfiltration neutralisée |
| **Total** | **95** | **160** | **255** | couverture exhaustive |

Les seuils obligatoires sont ceux de la section 11.1 du design : Recall@5
`>= 0.80`, Recall@10 `>= 0.90`, Recall@20 `>= 0.95`, nDCG@10 `>= 0.85`, MRR
`>= 0.85`, aucune fuite `must_not_return`, citations complètes et valides à
100 %, réussite à 100 % des cas sans source/confusion/adversariaux, taux de
réponse vide positive `<= 2 %` et aucune notion à 100 % vide. Ils s’appliquent
globalement, par matière et par notion.

## Revue humaine obligatoire

Une validation automatique ne constitue pas une revue humaine. Le manifeste
de revue reste `pending` jusqu’à ce qu’une personne identifiée atteste avoir
relu les 255 textes et leurs jugements sur le digest exact du paquet de revue.
L’agent auteur et ses reviewers automatiques ne peuvent pas produire cette
attestation. Toute divergence de digest, couverture partielle, identité ou
preuve absente doit rendre la revue invalide.

Le paquet de revue exhaustif est
[`golden_human_review_packet.md`](evidence/lot_39bis/golden_human_review_packet.md),
SHA-256
`8b4621bda39a93600b7bc47c28180a4087cf3ba86d91d16d70806ef06e01645f`.
Il contient les 255 identifiants uniques et quatre attestations globales, toutes
non cochées. Il lie explicitement les deux fichiers YAML normatifs et leur
digest ; il ne préremplit ni reviewer, ni heure, ni approbation.

## Digest et corrections de substance

Le digest normatif de la spécification est
`d00c7e0fcf6870111b46d07ddc5531d15184ba7dbf2f780af81b6b2a416ddee4`.
Le lock JSON a pour SHA-256 brut
`a92ceb4a4bdd0f4f7abd9303d29a0b90793b67a82fd0939299801883a7d13275`.
Il adresse le manifeste, le scope, les deux taxonomies et les deux fichiers de
requêtes. Les requêtes Mathématiques ont pour SHA-256
`ced6822a448f177940c6c87a29562569dc3349d0116f2940180357d1e68cea7b` ;
les requêtes NSI,
`9b7ecb5f37b9cb233c792e6e637353eee20f0c4df5aa52d6ac7127899d7f7ba6`.

Les revues automatiques croisées ne remplacent pas la revue humaine, mais ont
déjà relu les 255 cas et corrigé cinq défauts de substance avant gel : un total
combinatoire `215` corrigé en `265`, une convention de hauteur d’arbre rendue
explicite, une requête SQL recentrée hors jointures, deux oracles de test
diversifiés et les dix classes de source NSI `no_source` normalisées à `none`.
Après correction, les revues croisées Mathématiques et NSI ont rendu
`APPROVE`, sans finding résiduel.

La revue technique a ensuite durci l'audit lui-même : les ancres lexicales
chevauchantes sont dédupliquées sur les 39 notions, les confusions exigent dans
`must_not_return` un scope explicitement différent du scope courant, et les
adversariaux une menace précise. Les graphes d'alias YAML partagés sont visités
une seule fois avec un budget global de 4 096 nœuds, et chaque libellé normalisé
de métadonnée ou de digest du paquet humain doit apparaître exactement une fois,
y compris face aux variantes de casse ou d'espacement. Ces contrôles
automatiques restent des garde-fous structurels ; ils ne se substituent pas à
l'attestation humaine exhaustive.

## Vérifications et matrice de preuve

| Critère | Artefact ou commande | Digest / résultat | Verdict |
|---|---|---|---|
| Spécification et cardinalités | `python3 scripts/pilot_golden_spec_audit.py` | `SPECIFICATION_VALID`, 255, `LOCK_VALID` | PASS technique ; code `3` attendu pour revue pending |
| Digest normatif | `pilot_golden_spec.lock.json` | `d00c7e0fcf6870111b46d07ddc5531d15184ba7dbf2f780af81b6b2a416ddee4` | PASS |
| Revue humaine 255/255 | paquet de revue LOT39bis | 255 cases + 4 attestations non cochées | PENDING |
| Tests ciblés | `python3 -m pytest -q tests/unit/test_pilot_golden_spec.py tests/unit/test_make_target_safety_audit.py` | `307 passed` | PASS |
| Ruff et mypy | trois fichiers Ruff ; module + CLI mypy | `All checks passed!` ; `Success: no issues found` | PASS |
| Garde Make | `python3 scripts/make_target_safety_audit.py` | 55/55, cible en `SAFE_DIAGNOSTIC` | PASS |
| Verrous de gouvernance | `bash scripts/check-governance-locks.sh` | 18/18, aucune modification protégée | PASS |
| CI locale canonique | `bash scripts/ci-local.sh` | exécution de référence 13/13 verte, invalidée comme preuve finale par les correctifs postérieurs | PENDING sur le SHA final |
| Revue indépendante | diff technique final | `APPROVE` (confiance haute), aucun P0/P1 ; couverture P2 tenant ajoutée | PASS technique |
| Checks PR GitHub | run de la tête finale | `PENDING` | PENDING |

## Décision de livraison

LOT39bis reste non livrable et le projet reste `GO_LIVE: NO_GO`. Une
spécification techniquement valide mais sans revue humaine exhaustive ne peut
pas être fusionnée et ne débloque pas LOT40. Le code retour `3` de la cible
canonique rend cette frontière exécutable plutôt que déclarative.
