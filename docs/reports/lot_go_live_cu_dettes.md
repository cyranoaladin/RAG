# LOT CU — dettes constatées, avec antériorité prouvée

La suite d'intégration `services/rag-engine/tests/integration/` porte des
échecs **antérieurs à ce lot**. Chacun est reproduit à l'identique sur le
commit parent `b0c87971d52cc5637ed30f20c498c204dd8b251b`, dans un worktree
détaché, avec le même interpréteur et la même machine.

Aucun n'a été neutralisé, assoupli ni ignoré. Chacun est diagnostiqué
ci-dessous : dans les trois cas, **la garantie tient** — c'est l'attente de
l'épreuve qui a vieilli.

## 0. `make typecheck` était rouge — donc `make test` ne tournait pas (CLOS par ce lot)

**Symptôme.** Le job CI `services/rag-engine` s'arrête à `make typecheck` :
13 constats `mypy` dans 6 fichiers. La cible suivante, `make test`, n'est
donc **jamais exécutée** dans ce job — le garde-fou du service était inerte.

**Antériorité prouvée.** Les **mêmes 13 constats, dans les mêmes 6 fichiers**,
sont rendus au commit parent `b0c87971` (worktree détaché, même interpréteur,
même commande `mypy src`) ; seuls les numéros de ligne diffèrent, de ce que
ce lot a inséré. Le job CI était donc rouge avant ce lot, et ses tests non
joués.

**Pourquoi ce lot le clôt, alors qu'il ne rouvre pas les sous-lots.** Parce
que c'est le garde-fou de CE lot qui était hors service : `make test` est la
suite unitaire qui couvre tout ce que ce lot modifie. Le laisser inerte
aurait rendu la CI incapable de contredire quoi que ce soit.

**Ce qui a été fait, et ce qui ne l'a pas été.** Aucune logique n'est
touchée. Une identité relue en base est annotée `UUID`, des octets
canoniques `bytes`, un digest `str`, le catalogue scellé porte son vrai type
au lieu de `object | None` (par un import réservé au typage, le chargement
reste paresseux), et les autorités scellées du CLI d'attestation voyagent
dans une structure nommée au lieu d'un `dict[str, object]` — ce dernier
empêchait mypy de dire quoi que ce soit des cinq appels qui la
consommaient.

**Résultat mesuré** : `mypy src` — *Success: no issues found in 147 source
files*. Suite unitaire 3 955 verte, acceptation batch 15/15 et ingestion
scellée 13/13 rejouées après la modification.

## 1. Treize épreuves de `test_lot41a_scope_authority.py` attendent un ancien message

**Épreuves concernées** : `TestLiveGitHubProofIsFieldByField` (11) et
`TestDatabaseTamperingNeverSurvives` (2).

**Symptôme.** Le refus a bien lieu, et il échoue fermé. C'est le **texte**
attendu qui ne correspond plus. Exemple mesuré sur
`test_github_outage_is_denied_not_assumed_valid` :

```
Regex attendue : 'live GitHub verification failed'
Message rendu  : "authorization 'auth-nsi-terminale-2026': cannot re-read the
                  reviewed artifact governance/authorizations/… at bbbb… :
                  GitHub returned HTTP 503 for … — failing closed"
```

**Cause.** Le vérificateur d'autorisation **relit l'artefact approuvé à
chaque usage** (établi par le lot CT). Une panne GitHub est donc rencontrée
plus tôt, à la relecture, et nommée par le message de la relecture. Les
épreuves citent le message du chemin précédent.

Les deux épreuves de `TestDatabaseTamperingNeverSurvives` relèvent du même
vieillissement, pour une raison plus nette encore : la falsification est
refusée **plus tôt et plus précisément** que ce que l'épreuve attend.

```
Regex attendue : 'authorization_digest'
Refus rendu    : "authorization 'auth-nsi-terminale-2026': sealed trusted
                  review evidence disagrees with the recorded authorization:
                  [\"artifact_blob_sha: sealed='20d7f348…', recorded='a0a78294…'\"]"
```

La preuve de revue scellée (ADR-0058) détecte la dérive du blob **avant** le
contrôle de digest que l'épreuve nomme. La garantie est donc renforcée, et
c'est l'attente qui est restée sur l'ancien point de détection.

**Ce qui n'est pas en cause.** La propriété testée — « une panne, une dérive
de champ, une revue rejetée, une tête différente, une falsification en base
ne valident jamais » — est tenue dans les treize cas : l'exception levée est
bien un refus explicite. Seul le motif attendu est périmé.

**Antériorité prouvée.** Les treize échouent à l'identique au commit parent.

## 2. Une tête de schéma périmée — un échec et douze erreurs (CLOS par ce lot)

**Symptôme, mesuré :**

```
assert 'SCHEMA_HEAD=15' in 'MIGRATIONS_APPLIED=0
                            SCHEMA_VERIFICATION=OK
                            BOOTSTRAP_COMPLETE
                            SCHEMA_HEAD=17'
```

**Cause.** Les migrations `016_lot42_batch_release_identity.sql` et
`017_sealed_release_projection.sql` ont été ajoutées après l'écriture de ces
attentes, sans qu'elles soient mises à jour. Le bootstrap dit vrai : la tête
est bien **17**.

**Portée.** Deux endroits, pour un seul et même littéral :

| Endroit | Effet |
|---|---|
| `test_lot42_v2_migration_013::test_bootstrap_declares_013_as_head` | 1 échec — et le nom même de l'épreuve ne décrit plus ce qu'elle vérifie |
| fixture de module de `test_sealed_trusted_review_evidence_pg.py` (ligne 84) | **12 erreurs** : la fixture tombe, donc les douze épreuves du module n'exécutent rien |

Les douze erreurs de la suite d'intégration ont donc **une seule cause**, et
ce n'est pas un défaut de la preuve de revue scellée : c'est son banc qui ne
démarre pas.

**Antériorité prouvée.** Échoue à l'identique au commit parent.

**Pourquoi ce lot le clôt.** Parmi les douze épreuves que la fixture
emportait se trouve
`test_11_une_preuve_scellee_reste_valide_apres_fusion_de_la_pr` — la seule
qui établisse qu'une preuve de revue **tient après la fusion de sa PR**.
C'est une des propriétés que ce lot doit démontrer ; la laisser inexécutable
aurait été s'en remettre à un test qui ne tourne pas.

**Ce qui a été fait.** Le littéral n'a pas été réécrit de 15 à 17 — il
aurait pourri de nouveau à la migration suivante. Les trois attentes
dérivent désormais le nombre de migrations **livrées par le dépôt**
(`declared_schema_head()`), ce que le bootstrap déclare précisément, et dont
il refuse déjà qu'il diverge du fichier `HEAD`. C'est d'ailleurs la forme
qu'emploient déjà les modules voisins (`_MIGRATION_VERSIONS[-1]`, `_HEAD`) :
les trois littéraux étaient les exceptions.

**Résultat mesuré** : 25 épreuves repassent au vert (13 + 12), et les douze
erreurs de la suite d'intégration disparaissent.

## 3. Deux épreuves de `test_startup_gate_requires_readiness_manifest.py`

**Épreuves concernées** :
`test_the_worker_refuses_to_start_without_a_readiness_manifest` et
`test_the_worker_refuses_a_manifest_for_another_release`.

**Symptôme.**

```
__main__.py: error: the following arguments are required: --repository-root
```

**Cause.** L'argv que l'épreuve construit (`_worker_argv`) ne porte pas
`--repository-root`, devenu **obligatoire** pour le worker par un lot
antérieur. `argparse` refuse donc avant que le gate de readiness ne soit
atteint, et l'épreuve ne mesure plus le point d'application qu'elle nomme.

**Ce qui n'est pas en cause.** Le gate de readiness lui-même : le banc de ce
lot démarre Worker B avec un manifeste signé et son ancre, et le refus
s'applique quand il manque.

**Antériorité prouvée.** Les deux échouent à l'identique au commit parent.

## 4. Le script de rollback place un `LOCK TABLE` hors transaction

**Épreuves concernées** :
`test_lot44f_rollback_runner.py::TestRollbackRunnerRange` (2) et
`test_lot44f_migration_rollback_rehearsal.py::…::test_rollback_009_preserves_v1_rows_restores_v1_schema_and_reapplies` (1).

**Symptôme, mesuré :**

```
psql:…:9:   WARNING:  there is already a transaction in progress
psql:…:100: ERROR:  LOCK TABLE can only be used in transaction blocks
            WARNING:  there is no transaction in progress
returncode = 3
```

**Ce qui distingue cette dette des trois autres.** Ici l'attente de
l'épreuve est juste : le rollback **doit** rendre 0. C'est
`infra/scripts/rollback_ingestion_control_schema.sh` qui compose un script
SQL dont l'ouverture de transaction et le `LOCK TABLE` ne s'accordent pas.
C'est donc un défaut d'outillage, pas un vieillissement de test — et il
concerne la procédure de retour arrière du schéma de contrôle.

**Ce que ce lot n'y touche pas.** La procédure de rollback appartient au
LOT44F ; la corriger depuis ici serait modifier une procédure de reprise
sans mandat, ce que ce lot refuse. Elle est signalée telle quelle.

## Ce que ce lot n'a pas fait, et pourquoi

- **Aucune de ces épreuves n'a été corrigée.** Elles portent sur des lots
  clos (LOT41A, LOT42 migration 013, gate de readiness) et les toucher
  serait rouvrir leur périmètre sans mandat. Chacune est une correction
  d'une ligne ou deux, mais la décision appartient au lot concerné.
- **Aucune n'a été marquée `xfail` ni ignorée.** Un rouge tracé dit l'état
  du dépôt ; un `xfail` le dissimulerait derrière un vert.
- **Aucun message de production n'a été réaligné sur une attente de test.**
  Le message actuel est plus précis que l'ancien ; c'est l'attente qui doit
  suivre, pas l'inverse.

## Périmètre du lot CU

Les suites que ce lot fait vivre sont **vertes** :

| Suite | Résultat |
|---|---|
| `tests/integration/test_batch_publication_cli_acceptance.py` | 15 / 15 |
| `tests/integration/test_sealed_release_ingestion_pg.py` | 13 / 13 |
| `tests/integration/test_h2f_artifact_attribution_pg.py` | 40 / 40 |
| `tests/integration/test_lot42_v2_migration_013.py` | 13 / 13 (débloqué) |
| `tests/integration/test_sealed_trusted_review_evidence_pg.py` | 12 / 12 (débloqué) |
| Suite unitaire `rag-engine` | 3 955, 0 échec |
| `nexus-contracts` | 925, 0 échec |
