# LOT_GO_LIVE_FINAL_CS_RENEW_RUNTIME_AND_LOT41A_AUTHORIZATIONS

- **Branche** : `go-live/renew-lot41a-authorizations-with-sealed-evidence`
- **Base** : `39f1314e` (#242, ADR-0058)
- **Décision attendue** : `GO_LIVE_CS_RENEW_RUNTIME_AND_AUTHORIZATIONS_PR_OPEN`
- **Amende** : `staging_ssh_authorization.json` (CH2, CH3, CH4, CH6, CH7B → **CS**)

> Ce lot **n'enregistre aucune autorisation** et **n'exécute aucune
> ingestion**. L'enregistrement des onze aura lieu **pendant que cette PR est
> ouverte et approuvée**, avant fusion — voir « Ordre d'exécution ».

## Trois choses liées, et pourquoi elles ne se séparent pas

Sans le nouveau digest, le renouvellement ne peut pas être vérifié par le
runtime qui exécutera ; sans le renouvellement, le digest n'autorise rien
d'utile ; et sans la correction de `merge_sha`, la prochaine signature
désignerait à nouveau le mauvais code.

## 1. Le runtime était périmé, et c'était invisible

L'image autorisée par CH7B, `sha256:1fb70485…`, a été construite depuis
`f66a04cb` — **avant** ADR-0058. Mesuré dans ses octets :

| Dans l'image de CH7B | |
|---|---|
| `_verify_sealed_review` | **absent** |
| `_verify_live_review` utilisé à l'usage | **oui** |
| contrat `trusted_review_evidence` | **absent** |

Elle aurait refusé les onze autorisations même renouvelées, avec
`pull_request_not_open` — le blocage d'origine, intact.

**La leçon se répète** : une image épinglée par digest conserve exactement
son contenu. Fusionner du code sur `main` ne la met pas à jour. C'était vrai
de CH6 → CH7B, ce l'est de CH7B → CS, et ce le sera de tout successeur.

### L'image autorisée

```
ghcr.io/cyranoaladin/rag-multilevel-worker-production@sha256:431264a02e2e2a5484cef7d5ac620a3aa7fa16f66be1497fde886dfb7f83ccd8
```

Construite par `production-image-provenance.yml`, run `35593843678`, sur
`refs/heads/main` au commit `39f1314e` — celui qui porte ADR-0058. Rien
construit sur `nexus-prod`.

Vérifié **dans l'image**, hors `nexus-prod`, par tirage au digest puis
exécutions `--network none` :

| Contrôle | Résultat |
|---|---|
| `_verify_sealed_review` | présent |
| `_verify_live_review` à l'usage | **non** |
| contrat `trusted_review_evidence` | installé |
| `staging_readiness_gate.py` | présent |
| `enforce_staging_readiness_gate` appelé | oui |
| garde `NEXUS_ACTUAL_WORKER_IMAGE` | présente |
| `nexus-contracts` | 0.19.0 |
| secrets, clés, graines, manifeste, ancre | 0 — **mesurés sur cette image** |

Les gardes apportées par CQ, CR et CH7A sont toutes présentes : un rebuild ne
doit rien perdre.

## 2. `merge_sha` nommait le mauvais commit

Le contrat définit `merge_sha` comme « le commit de `main` dont l'image
worker a été construite ». La première signature a nommé `133159cb`, le
commit d'**autorisation**, alors que l'image venait de `f66a04cb`. Le
manifeste désignait un code que l'image ne portait pas, et rien ne le
vérifiait.

C'est aussi ce qui créait une boucle : si le manifeste devait nommer le
commit d'autorisation, chaque PR documentaire autorisant une image imposerait
de la reconstruire pour que le manifeste redevienne vrai.

Le runbook le dit désormais explicitement, et le validateur exige que la
déclaration d'autorisation nomme le commit de **build**.

## 3. Onze autorisations renouvelées, sans réécrire l'histoire

Les onze d'origine ont été enregistrées sous le modèle de revue vivante.
Leur preuve n'existe pas et **ne peut pas être reconstituée** : une revue ne
se rejoue pas après coup. Elles sont refusées à l'usage, ce qui est voulu.

**Elles ne sont ni modifiées, ni supprimées.** La base a enregistré leur
chemin canonique ; le déplacer rendrait l'historique invérifiable. Onze
nouvelles autorisations sont créées avec des identifiants neufs (`…-r2`), et
`docs/governance/lot41a_staging_v2_renewal_map.json` dit laquelle remplace
laquelle.

### Ce qui est préservé, et ce qui ne l'est pas

Identique champ pour champ : scope, collection, `manifest_digest`, profil,
empreinte de profil, domaines autorisés, catégories de droits, exclusions,
attestation PII, **et la fenêtre de validité** — l'étendre serait une
décision distincte, pas une conséquence du renouvellement.

Ce que la carte ne prétend pas : les enveloppes **ne sont pas** identiques
octet pour octet. `authorization_id` y figure, donc le sha256 diffère. Le
dire autrement serait faux ; l'invariance porte sur le métier, et 26 épreuves
la vérifient champ par champ.

## Preuves

```
scripts/qualification    367 passés, 3 ignorés
  (rejoué dans un venv propre, sans psycopg, comme le job de CI)
ruff / governance locks  verts, 18/18
check_staging_authorization : aucun écart de périmètre
```

### Quatre gardes recadrées, et un couplage supprimé

Le renouvellement a fait tomber des épreuves écrites pour des lots
antérieurs. Elles avaient raison de tomber :

1. la carte de correspondance, placée dans `governance/authorizations/`,
   tombait dans le glob des autorisations et s'y faisait compter. Déplacée
   dans `docs/governance/` ;
2. les épreuves comptaient « exactement onze fichiers ». Il y en a vingt-deux :
   onze actifs, onze remplacés. Elles lisent désormais la carte, au lieu de
   deviner par un suffixe ;
3. `test_6quater` comparait « la branche courante » au commit source de
   l'image — elle cassait sur tout lot suivant. Recadrée sur le commit de
   CH7B lui-même : un fait historique ;
4. le fichier de CH7B affirmait « l'autorisation en vigueur nomme *mon*
   digest ». Faux dès CS, et faux à chaque rebuild. Il porte désormais sur sa
   preuve versionnée, qui ne bouge plus.

Et un couplage a été **supprimé** plutôt que déplacé : le fichier de CH6
codait en dur le chemin de la preuve courante, ce qui obligeait à le
repointer à chaque lot — il l'a été deux fois. Il lit maintenant ce chemin
**dans l'autorisation**. Le prochain rebuild ne le fera plus tomber.

## Schéma de staging : 14 → 15, appliqué

```
MIGRATIONS_APPLIED=1   SCHEMA_VERIFICATION=OK   SCHEMA_HEAD=15
```

Vérifié après coup : deux colonnes, deux contraintes, le registre de
révocation, **zéro ligne avec preuve scellée** — conforme, aucun backfill.

**Un point que la vérification a rattrapé** : la migration seule n'accorde
aucun droit. Le registre appartenait au seul propriétaire, et le worker
aurait échoué sur `permission denied` à l'usage. Après provisionnement
canonique :

| Rôle | `revoked_review_evidence` |
|---|---|
| `ingestion_control_app` | SELECT |
| `ingestion_control_attestor` | SELECT |
| `ingestion_control_authority` | SELECT, INSERT |

Le worker lit les révocations sans pouvoir en écrire ; l'autorité écrit en
append-only.

## Ordre d'exécution — ce qui doit se passer pendant que la PR est ouverte

1. PR ouverte, CI verte ;
2. approbation humaine au head exact, contexte `trusted-human-review/head-pinned` vert ;
3. **enregistrement des onze autorisations** par `authorize_scope_cli`,
   pendant que la PR est ouverte — l'artefact est relu au head approuvé ;
4. vérification des onze : preuve scellée présente, digest concordant,
   challenge redérivé, usage accepté par le runtime destiné à l'exécution ;
5. fusion **seulement ensuite**.

Aucun commit ne sera poussé après l'approbation : cela changerait le head et
invaliderait la revue. Les reçus d'enregistrement seront consignés dans un
lot de preuve séparé, après fusion.
