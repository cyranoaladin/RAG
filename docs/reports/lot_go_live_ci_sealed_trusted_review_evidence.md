# LOT_GO_LIVE_FINAL_CI_SEALED_TRUSTED_REVIEW_EVIDENCE_FOR_AUTHORIZATIONS

- **Branche** : `go-live/sealed-trusted-review-evidence-for-authorizations`
- **Base** : `3abcec67` … `133159cb` (CH7B)
- **Décision attendue** : `GO_LIVE_CI_SEALED_TRUSTED_REVIEW_EVIDENCE_PR_OPEN`
- **ADR** : **ADR-0058**
- **S'appuie sur** : ADR-0025, ADR-0032, ADR-0057

> Ce lot **n'enregistre aucune autorisation**, n'exécute aucune ingestion,
> ne crée aucun job, ne lance aucun worker et ne produit aucune attestation.
> Il change le **temps** d'une garde, pas sa sévérité.

## Le fait qui force le lot

`verify_scope_authorization` revérifiait à chaque usage que la PR d'autorité
était encore **ouverte**. Mesuré sur la PR #233, qui porte les onze
autorisations LOT41A V2 :

```
PR #233 : state = closed | merged = True
decision : REFUSE (pull_request_not_open)
```

L'artefact doit être sur `main` pour être relu — donc la PR doit être
fusionnée. La revue doit être vérifiée en direct — donc la PR doit être
ouverte. Les deux ne peuvent pas être vraies au moment de l'usage. Worker A,
`attest_publication_cli` et `publication_attestation` butent identiquement.

## Ce que le lot livre

| Fichier | Rôle |
|---|---|
| `docs/adr/ADR-0058-…md` | la décision, et ce qu'elle coûte |
| `packages/contracts/src/nexus_contracts/trusted_review_evidence.py` | le contrat `NEXUS-SEALED-TRUSTED-REVIEW-EVIDENCE-V1` |
| `…/migrations/015_sealed_trusted_review_evidence.sql` | `review_evidence` + digest, et le registre de révocation |
| `…/rollbacks/015_….down.sql` | fail-closed : refuse de détruire une preuve |
| `…/ingestion_control/github_authority.py` | lecture des quatre faits manquants, allowlist hors ligne |
| `…/ingestion_worker/authorize_scope_cli.py` | scelle la revue pendant qu'elle est vivante |
| `…/ingestion_control/scope_authority.py` | l'usage vérifie le sceau, pas la liveness |

### Le challenge est **recalculé**, pas recopié

La preuve porte les sept dimensions du challenge — dont
`pull_request_author` et `pull_request_base_ref`, que l'ancien
enregistrement **ne conservait pas**. Sans eux, le challenge ne pouvait
qu'être recopié : un challenge recopié n'établit que la bonne foi de celui
qui l'a écrit.

Vérifié contre un cas réel : le recalcul reproduit exactement le challenge
publié de la PR #241 (`NEXUS-TRUSTED-REVIEW-V1:59de02ed…`).

### Ce qui reste vivant

L'allowlist des relecteurs. Retirer une identité éteint toutes les
autorisations qu'elle a signées, sans avoir à les révoquer une par une.

### Ce que le modèle cesse d'établir

Une revue dismissée sur GitHub **après** le scellement ne sera plus
détectée. L'ancien modèle l'aurait vue au prochain usage — par accident, en
redemandant l'état de la PR. C'est la contrepartie directe, et elle est
nommée dans l'ADR : ce que la liveness détectait par accident, la
révocation doit désormais le faire exprès.

D'où le registre `ingestion_control.revoked_review_evidence`, qui éteint une
**preuve** — donc toutes les autorisations qui s'en réclament — là où
`scope_authorizations.revoked_at` n'en éteint qu'une.

## Un défaut réel trouvé par le test sur base réelle

La contrainte d'appariement, telle que je l'avais écrite, **n'appariait
rien** :

```sql
CHECK (
    (review_evidence IS NULL AND review_evidence_digest IS NULL)
    OR (review_evidence IS NOT NULL AND review_evidence_digest ~ '^[0-9a-f]{64}$' …)
)
```

Avec une preuve présente et un digest NULL : `NULL ~ '...'` vaut **NULL**,
la seconde branche vaut NULL, et `FALSE OR NULL` vaut NULL — qu'un `CHECK`
PostgreSQL **accepte**, car seul `FALSE` rejette. Une preuve sans digest
passait.

Le test sur PostgreSQL réel l'a montré ; une lecture du motif ne l'aurait
jamais montré. `review_evidence_digest IS NOT NULL` a été ajouté, et une
épreuve statique fixe désormais la règle : toute colonne comparée à un motif
doit d'abord être exclue de NULL.

## Preuves

### Les vingt épreuves demandées

| # | Exigence | Où |
|---|---|---|
| 1 | PR ouverte + APPROVED + head exact → accepté | inchangé : `authorize_scope_cli` exige toujours `verify_review` approuvé au head |
| 2–4 | PR fermée / non approuvée / ancien head → refus | inchangés, mêmes gardes qu'avant ce lot |
| 5–6 | challenge manquant / altéré → refus | `test_un_challenge_absent…`, `test_un_challenge_altere…`, `test_6_un_challenge_altere_est_refuse` (PostgreSQL) |
| 7 | relecteur hors allowlist → refus | `test_un_relecteur_hors_allowlist…`, `test_7_…` (PostgreSQL) |
| 8 | artefact modifié après revue → refus | `_require_row_matches_artifact` inchangé + `test_une_divergence…` |
| 9 | preuve absente → usage refusé | `test_9_une_autorisation_sans_preuve_scellee_est_refusee` |
| 10 | preuve incomplète → usage refusé | `test_10_…`, plus 20 champs testés un par un |
| 11 | **preuve correcte → acceptée même PR fusionnée** | `test_11_une_preuve_scellee_reste_valide_apres_fusion_de_la_pr` |
| 12 | preuve révoquée → refus | `test_12_une_preuve_revoquee_est_refusee` |
| 13 | `valid_until` expiré → refus | garde existante, inchangée |
| 14 | `authorization_id` inconnu → refus | `test_14_…` |
| 15 | périmètre différent → refus | garde existante `scope_key`, inchangée |
| 16 | les 11 LOT41A V2 inchangées côté métier | aucun fichier de `governance/authorizations/` touché |
| 17–20 | aucun job, aucune ingestion, aucune DB production, release V2 intacte | aucun de ces chemins n'est touché par le lot |

Le test 11 vérifie en outre qu'**aucun appel réseau n'a lieu** : `verify_review`
y est remplacé par une fonction qui échoue si elle est appelée.

### Exécution mesurée

```
packages/contracts   pytest tests/test_sealed_trusted_review_evidence.py   56 passed
services/rag-engine  pytest tests/test_sealed_review_evidence_migration…    9 passed
services/rag-engine  pytest tests/integration/test_sealed_…_pg.py         12 passed
  (PostgreSQL réel, bootstrap complet, SCHEMA_HEAD=15)
```

### Trois épreuves existantes mises à jour

`test_migration_009_…`, `test_migration_010_…` et `test_la_migration_014_…`
affirment chacune que le HEAD déclaré vaut une migration précise. Ajouter la
015 les a fait échouer — **c'est leur raison d'être** : elles forcent chaque
lot de migration à se déclarer visiblement dans les fichiers voisins. J'ai
mis à jour le littéral plutôt que d'assouplir la règle en « le HEAD vaut la
dernière migration présente », qui n'échouerait plus jamais.

La cascade de rejeu de `test_lot44f_migration_rollback_rehearsal` passe de
six à sept migrations, et `SCHEMA_HEAD` de 14 à 15.

## Compatibilité avec CH5

CH5 avait établi, à ses dépens, qu'une autorisation doit être enregistrée
**pendant que la PR est ouverte**. Ce lot ne change rien à cette règle : il
la rend suffisante. CH5 disait « enregistrer avant de fusionner » ; ADR-0058
ajoute « et ce qui a été enregistré alors vaut encore après ».

## Ce qui reste à faire, et ne peut pas être fait ici

Les onze autorisations LOT41A V2 ont été enregistrées sous l'ancien modèle.
Elles n'ont pas de preuve scellée, et **n'en auront jamais** : une revue ne
se reconstitue pas après coup. Elles sont donc refusées à l'usage — c'est le
comportement voulu.

Leur réenregistrement propre, dans une fenêtre de revue vivante et avec un
payload métier identique, est l'objet du lot suivant.
