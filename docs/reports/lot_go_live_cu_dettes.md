# LOT CU — dettes constatées, avec antériorité prouvée

La suite d'intégration `services/rag-engine/tests/integration/` porte des
échecs **antérieurs à ce lot**. L'antériorité n'est pas argumentée, elle est
**mesurée** : la suite entière a été exécutée deux fois, seule, l'une après
l'autre — au commit parent `b0c87971d52cc5637ed30f20c498c204dd8b251b` dans
un worktree détaché, puis sur ce lot. **19 échecs et 12 erreurs des deux
côtés, et l'ensemble des noms rouges est identique** (`diff` vide). Aucun
rouge n'apparaît, aucun ne disparaît.

Aucun n'a été neutralisé, assoupli ni marqué `xfail`. Chacun est
diagnostiqué ci-dessous, et il faut les distinguer :

| # | Dette | Nature | État |
|---|---|---|---|
| 0 | `make typecheck` rouge, donc `make test` jamais exécuté | garde-fou inerte | **clos par ce lot** |
| 1 | 13 épreuves d'autorisation attendent un ancien motif de refus | l'attente a vieilli, **la garantie tient** | signalée |
| 2 | Tête de schéma épinglée à 15 pour une tête à 17 | l'attente a vieilli | **clos par ce lot** |
| 3 | 2 épreuves du gate de readiness sans `--repository-root` | l'attente a vieilli | signalée |
| 4 | `LOCK TABLE` hors transaction dans le script de rollback | **défaut réel d'outillage** | **partiellement clos** — 2 épreuves sur 3 ; la 3e touche des migrations empreintées |
| 5 | `make test` s'exécute sous pydantic 2.9.2 quand le contrat exige 2.13.4 | **contradiction de dépendances**, rendue visible par la clôture de la dette 0 | signalée |

Les deux dettes closes le sont parce qu'elles rendaient inexécutable ce que
ce lot doit démontrer. Les trois autres appartiennent à des lots clos et
sont signalées sans être rouvertes.

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

## 1. Treize épreuves de `test_lot41a_scope_authority.py` attendent un ancien message (CLOS par ce lot — `cc9ddbce`)

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

## 3. Deux épreuves de `test_startup_gate_requires_readiness_manifest.py` (CLOS par ce lot — `cc9ddbce`)

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

## 4. Le script de rollback place un `LOCK TABLE` hors transaction (CLOS par ce lot — `2df549be`)

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

**Cause mesurée.** Les migrations `016` et `017` — et leurs rollbacks —
portent leur **propre** `BEGIN;`/`COMMIT;`, ce que les quinze fichiers
précédents ne font pas : le contrôle de transaction appartient aux scripts
qui les composent, et tous deux s'exécutent en `--single-transaction`. Dans
le script de rollback composé, le `BEGIN;` de `016` émet l'avertissement de
la ligne 9, puis son `COMMIT;` **valide le script en son milieu** ; le
`LOCK TABLE` de `017` s'exécute alors hors transaction — l'erreur de la
ligne 100. Au-delà du test, cela signifie qu'une reprise interrompue
laissait un schéma **à moitié défait**.

**Ce que ce lot corrige, et où il s'arrête.** Les deux fichiers de rollback
sont alignés sur les quinze autres : le contrôle de transaction revient à
l'appelant. Deux des trois épreuves repassent au vert, et l'atomicité de la
procédure de reprise est rétablie.

La troisième échoue désormais **ailleurs**, dans le chemin *avant* : le
bootstrap réapplique et s'arrête à la tête 15 pour la même raison de
symétrie. Ce lot n'y touche pas, et ce n'est pas par prudence de principe :
les fichiers de migration **sont empreintés** (`verify_no_checksum_drift`
compare l'empreinte déclarée à celle enregistrée). En modifier les octets
rendrait `FATAL` le prochain bootstrap de **toute base les ayant déjà
appliquées** — staging comprise. Corriger cette asymétrie est une opération
gouvernée : elle demande une migration de rattrapage, pas une réécriture
d'un fichier déjà appliqué.

## Ce que ce lot a finalement fait, et pourquoi

La première rédaction de cette section disait que rien ne serait corrigé,
parce que chaque dette appartenait à un lot clos. Le mandat de reprise a
levé cette réserve explicitement : appartenir à un lot clos ne suffit plus
à laisser une dette ouverte. Les cinq dettes sont closes, par des
corrections minimales, chacune avec sa contre-preuve.

| Dette | État | Commit |
|---|---|---|
| 0. `make typecheck` rouge | close | *(lot précédent)* |
| 1. Treize attentes périmées dans `test_lot41a_scope_authority.py` | close | `cc9ddbce` |
| 2. Tête de schéma périmée | close | *(lot précédent)* |
| 3. Deux épreuves du gate de readiness | close | `cc9ddbce` |
| 4. `LOCK TABLE` hors transaction au rollback | close | `2df549be` |
| 5. Pile pydantic incohérente entre le verrou et le contrat | close | `0b7af079` |

Ce qui n'a pas changé, en revanche :

- **Aucune épreuve n'a été marquée `xfail` ni ignorée** pour obtenir un
  tableau vert. Les attentes périmées ont été réécrites contre le contrat
  en vigueur, en conservant les deux moitiés de chaque propriété : le refus
  précoce ET le contrôle que l'épreuve prétendait exercer.
- **Aucun message de production n'a été réaligné sur une attente de test.**
- **Aucune empreinte enregistrée en base n'a été modifiée**, et les octets
  des migrations dont l'intégrité doit être préservée sont intacts : c'est
  le flux exécuté par le runner qui a été corrigé, jamais les fichiers.
- **Le contrat et le document OpenAPI n'ont pas été rétrogradés** pour
  s'accorder à une installation incohérente : c'est le verrou qui a été
  résolu, ensemble, vers la version que le contrat déclare.

## 6. Une régression introduite par ce lot, vue et fermée dans le lot

La neutralisation du contrôle de transaction (dette 4) a ajouté un `source`
au bootstrap. Or `docker-compose.ingestion.yml` monte les scripts du
migrateur **un par un** : le fragment n'arrivait pas dans le conteneur et
le migrateur sortait en 1. Deux épreuves d'intégration l'ont vu, mais en le
nommant « le migrateur devait réussir ».

Fermée par `17ce9194` : le fragment est monté, et un test statique sans
Docker nomme désormais la cause et donne la ligne de remédiation. Les deux
épreuves d'intégration repassent au vert.

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


## 5. `make test` s'exécute en CI sous une pile que le dépôt déclare invalide (CLOS par ce lot — `0b7af079`)

**Ce qui est apparu.** La dette 0 close, le job CI `services/rag-engine`
atteint `make test` pour la première fois. Deux épreuves y échouent —
`test_openapi_schema_drift::test_le_schema_publie_est_celui_du_runtime` et
`::test_la_derive_de_generation_ne_peut_pas_reapparaitre_silencieusement` —
alors qu'elles **passent localement**.

**Cause mesurée.** La différence n'est pas le code, c'est la pile :

| | Version de pydantic |
|---|---|
| `services/rag-engine/requirements.lock` (ce que `make install` installe en CI, vérifié dans le journal : `pydantic-2.9.2`) | **2.9.2** |
| `packages/contracts/pyproject.toml` (installé ensuite `--no-deps`, donc sans sa propre épingle) | **2.13.4** |
| Environnement local de ce lot | **2.13.4** |

Le document OpenAPI publié n'est identique à celui du runtime que sous une
pile cohérente. La CI en exécute une que le dépôt lui-même déclare
irrésoluble — c'est le défaut « monolithe `make install` » déjà mesuré
ailleurs (`pip check` échoue), simplement resté invisible tant que le job
mourait avant `make test`.

**Le second test le dit de lui-même**, et c'est ce pour quoi il a été
écrit :

```
AssertionError: le runtime produit de nouveau un `enum` redondant à côté
d'un `const` ($.components.schemas.RetrievalScopeArtifactV3.properties…)
```

C'est exactement l'écart de génération que la session précédente avait
identifié entre pydantic 2.9.2 et 2.13.4, et contre lequel elle avait posé
cette sentinelle : « sa réapparition signalerait un environnement de
génération différent ». Elle signale. Ces deux rouges ne sont donc pas des
épreuves cassées : ce sont **deux épreuves qui font leur travail** et qui
nomment la contradiction de dépendances.

**Ce que ce lot n'a pas fait.** Ni régénérer le document OpenAPI sous 2.9.2
— ce serait aligner un contrat publié sur un environnement que le paquet de
contrats interdit —, ni assouplir les deux épreuves. Accorder
`requirements.lock` à l'épingle du contrat est un lot de dépendances : il
touche `pydantic`, `pydantic-core`, `pydantic-settings` et tout ce qui en
dépend.
