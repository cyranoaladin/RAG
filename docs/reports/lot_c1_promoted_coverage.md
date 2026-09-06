# LOT — C1 : couvrir la lignée COURANTE, pas seulement la revue passée

## Le défaut

`Corpus CAS reproducibility (C1)` confronte le store adressable par contenu à
l'ensemble de **320 objets** que la revue humaine du 2026-09-03 a scellé
(`pii_review_index_20260903.json`, `content_set_sha256=77f01c82…`,
`counts.scanned=320`).

Cette épreuve prouve que le store est celui d'une lignée **figée**. Elle ne
demande jamais si l'ensemble que la lignée **promeut aujourd'hui** y est
couvert. Une lignée régénérée après la revue servirait donc des documents
irreproductibles hors poste, et C1 resterait vert : il vérifierait toujours,
fidèlement, un corpus qui n'est plus celui qu'on sert.

L'écart n'est pas théorique. L'index a été produit à `21:53:59Z`, trois
minutes après `a4b1f96` — le dernier changement de la lignée à cette date. Rien
n'empêche le prochain changement de rompre l'inclusion, et rien ne le dirait.

## La preuve rouge

Sur les données réelles, avant correctif :

```
python scripts/qualification/verify_corpus_cas.py --cas-root … \
  --expect-content-set-sha256 77f01c82… --expect-count 320
→ RC=0
```

vert, sans qu'aucune assertion ne porte sur les contenus servis aujourd'hui.

Le premier correctif — celui de la contribution entrante — introduisait
`--promoted-content-set`. Il portait toutefois la faille qu'il prétendait
fermer :

```python
verify(cas_root, digest, count, promoted=set())
→ code = 0
→ PROMOTED_CAS_COVERAGE_MISSING=0
```

Un ensemble promu **vide** ne manque jamais de rien. C'est la manière exacte
dont un gate devient vert en *perdant* ses données : moins on en sait, plus le
compte est bon.

## L'autorité lue

Le producteur ne part plus d'un manifeste historique nommé en dur. Il part du
**registre canonique**, seule autorité qui désigne les releases actives, et
descend la chaîne en confrontant chaque maillon à son sceau :

```
release-registry.json
→ manifestes de release actifs      (expected_manifest_sha256)
→ manifestes de sujet scellés       (subjects[].sha256)
→ occurrences de contenu promu      (expected_counts.artifacts)
→ ensemble de contenus distincts
```

`--release-registry` accepte un registre figé : la qualification du
`FULL_GO_LIVE_CANDIDATE` réutilisera ce script tel quel, sans réécriture.

## Le compte mesuré

```
Occurrences d'artefact (11 sujets)   486
Contenus DISTINCTS promus            319
Partages multi-sujets                167
PROMOTED_CONTENT_SET_SHA256          d06d6051e7037372acf4dca4675a1c999c198129433d68491221a9d03bb821cd
```

Les 167 partages sont exactement ce que la PR #146 a légitimé. Le compte de
319 est corroboré par deux chemins indépendants : la déduplication des
`content_sha256`, et `expected_counts.artifacts = 486` que la release déclare.

## Sémantique de la couverture

« Couvert » ne veut pas dire « déclaré au manifeste du store ». Un contenu peut
y figurer sans qu'aucun octet lisible ne lui corresponde. Quatre compteurs
distinguent désormais ce que l'on sait :

| Compteur | Ce qu'il compte |
|---|---|
| `PROMOTED_CAS_DECLARATION_MISSING` | promu, absent du manifeste du store |
| `PROMOTED_CAS_BLOB_MISSING` | déclaré, mais aucun objet sur disque |
| `PROMOTED_CAS_HASH_MISMATCH` | objet présent, octets hachant ailleurs, ou localisateur hors store |
| `PROMOTED_CAS_COVERAGE_MISSING` | promu **sans objet CAS vérifié** — l'union des trois |

Seul le dernier fait échouer le gate, et c'est lui qui porte la question :
*ce document servi, sait-on le relire hors du poste ?*

## Les mutants

Chaque garde est prouvée par la mutation qu'elle refuse.

| Mutation | Attendu | Observé |
|---|---|---|
| ensemble promu vide | refus | « la couverture serait vraie par vacuité » |
| registre sans release active | refus | « aucune release active » |
| release sans sujet | refus | « aucun sujet » |
| sujet sans artefact | refus | « aucun artefact » |
| manifeste de sujet réécrit sans son sceau | refus | déclare `5f4af613…`, vaut `dbe72c70…` |
| manifeste de release réécrit sans son sceau | refus | « l'autorité déclare » |
| `expected_counts.artifacts` absent, `"4"`, `0`, `-1`, `True` | refus | « expected_counts » |
| occurrences lues ≠ déclarées | refus | « contre 9 déclarées » |
| `manifest_path` en `../` | refus | « hors de la racine gouvernée » |
| composant du chemin en lien symbolique | refus | « est un lien symbolique » |
| JSON malformé | `RC=2` | `PROMOTED_CONTENT_SET_INVALID` |
| blob supprimé | refus | `BLOB_MISSING=1`, `COVERAGE_MISSING=1` |
| octets remplacés | refus | `HASH_MISMATCH=1`, `COVERAGE_MISSING=1` |

Sur l'arbre réel, la mutation d'un sujet sans mise à jour de son sceau rend
`RC=2` en nommant le sujet, l'empreinte déclarée et l'empreinte mesurée.

## Déclenchement

Le filtre de chemins du workflow est volontairement **large** —
`services/rag-pedago/data/releases/**` et `scripts/qualification/**` — plutôt
qu'une allowlist. L'ensemble servi dépend du registre, des manifestes qu'il
désigne et des sujets joignables depuis eux : les énumérer un par un
laisserait un changement de registre seul, ou une release nouvellement
désignée, éviter C1 sans que rien ne le dise.

## La frontière de la clé privée

Le workflow C1 refuse de se déclencher sur `pull_request`, et c'est la bonne
décision : il porte la clé d'accès au corpus privé, qu'un job de PR — donc du
code que personne n'a encore revu — pourrait exfiltrer en une étape ajoutée.

Conséquence non voulue : ses épreuves **unitaires**, qui n'ont besoin d'aucun
secret, ne tournaient nulle part avant la fusion. Le job `scripts/qualification`
de `ci.yml` les exécute désormais sur les PR, sur données publiques
uniquement. La séparation reste stricte :

```
PR CI            → données publiques seules, jamais la clé CAS
main post-merge  → clé CAS, confrontation au store privé
```

## Ce qui reste à prouver après la fusion

Ce lot rend le gate **capable** de poser la question. La réponse exige le job
privilégié post-fusion, sur le commit exact de `main` :

```
CURRENT_PROMOTED_CONTENTS=<mesuré>
PROMOTED_CAS_DECLARATION_MISSING=0
PROMOTED_CAS_BLOB_MISSING=0
PROMOTED_CAS_HASH_MISMATCH=0
PROMOTED_CAS_COVERAGE_MISSING=0
```

Alors seulement `C1_CURRENT_LINEAGE=PASS`.

`C1_FULL_GO_LIVE_CORPUS` reste **ouvert** : il sera prouvé contre le
`FULL_GO_LIVE_CANDIDATE`, dont le CAS devra recevoir chaque source promue —
PDF, binaire Drive, document d'URL matérialisé, et GeoGebra s'il est servi
comme artefact. Le store peut être sur-ensemble ; jamais sous-ensemble.

## Provenance de ce lot

La contribution initiale vient d'une autre instance (PR #153, `d8e8415`). Elle
n'a été ni fusionnée par confiance, ni rejetée pour son origine : le défaut
qu'elle vise a été confirmé par mesure, son correctif adopté, et les trous
qu'il laissait — vacuité, sceaux non confrontés, compte déclaré facultatif,
chemins non bornés, sémantique de couverture — fermés au-dessus.
