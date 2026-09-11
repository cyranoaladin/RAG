# Revue contradictoire de #184 — garde `--assert-ready`

La revue automatique Codex est indisponible : quota atteint. Cette revue la
remplace. Elle n'est pas une approbation — elle ne remplace pas la revue humaine
liée au HEAD, qui reste requise par la protection de branche. Elle documente ce
qui a été **mesuré**, pas ce qui est affirmé.

## Le défaut que ce lot corrige

`--check-only` rend `0` même quand le système n'est pas prêt. C'est légitime pour
un mode diagnostic, et dangereux si quelqu'un s'en sert comme garde : la chaîne
de déploiement verrait un vert là où rien n'est prêt.

Mesuré sur la branche, avec sept bloqueurs ouverts :

```
--check-only     exit=0    GO_LIVE_READY=false
--assert-ready   exit=1    GO_LIVE_READY=false
```

Les deux modes disent la même chose ; seul le code de retour diffère. C'est
exactement la distinction qui manquait.

## Vérifications, chacune par mesure

| Contrôle | Méthode | Résultat |
| --- | --- | --- |
| Aucune production touchée | diff de fichiers contre `main` | 0 fichier runtime, infra, DB, DNS |
| Aucune ingestion | aucun script d'ingestion appelé | conforme |
| Aucune bascule courante | aucun changement de pointeur | conforme |
| `--assert-ready` échoue si non prêt | exécution réelle | `exit=1` |
| `--assert-ready` réussit si tout fermé | dépôt fictif tout-fermé | `exit=0` |
| Entrée manquante distinguée | dépôt fictif amputé | `exit=2`, `GO_LIVE_READY=unknown` |
| `--verify-snapshot` n'autorise rien | sortie du mode | `SNAPSHOT_AUTHORIZATION=false` |
| Compteurs métier intacts | diff sur fichiers PII/programme/actualité/non-PDF | 0 fichier touché |
| Fichiers hors périmètre | diff contre la liste autorisée | 0 |
| Chemins machine-locaux nouveaux | grep sur les lignes ajoutées | 0 |
| Secrets | grep sur les lignes ajoutées | 0 |

## Ce que la revue a cherché à casser

Quatre mutations appliquées au garde, chacune devant faire tomber une épreuve :

| Mutation | Résultat |
| --- | --- |
| `--assert-ready` rend toujours `0` | 8 épreuves rouges |
| Le garde ignore l'état calculé | 8 épreuves rouges |
| Entrée manquante rendue comme un refus ordinaire | 1 épreuve rouge |
| L'instantané se déclare autorisant | 1 épreuve rouge |

Aucune mutation n'a survécu. Une mutation qui survit signale une épreuve qui ne
prouve pas ce qu'elle annonce ; il n'y en a pas ici.

## Les six bloqueurs, éprouvés isolément

Chaque bloqueur, seul, doit suffire à faire échouer le garde. Sans cela, un seul
oubli le rendrait permissif. Les six cas sont paramétrés et passent :
PII indécise, programme incompatible, politique d'actualité non appliquée,
réacquisition incomplète, PR bloquante, gate de qualification ouvert.

## État au moment de la revue

```
GO_LIVE_READY=false
pii_undecided=149          program_incompatible_in_servable_set=1
currentness_policy_applied=false
non_pdf_servable_reacquired=0/37
open_prs_blocking=6        go_live_qualification_blockers=13
```

## Limite de cette revue

Elle est écrite par l'auteur du lot. Elle ne peut donc pas tenir lieu de regard
extérieur, et elle ne prétend pas le faire. Ce qu'elle apporte est vérifiable
par quiconque : chaque ligne du tableau ci-dessus est une commande à relancer.

Trois compteurs restent hors de portée de toute mesure du dépôt — écritures en
base de production, déploiements, bascule courante. Ils sont déclarés, et le
fichier d'état le dit.
